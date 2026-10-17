"""UI-independent scheduling, units and durable per-attempt history."""

import json
import queue
import random
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .backends import CommandRunner
from .bundled import BundledSpeedtest
from .models import CheckerError

SPEED_UNITS = {
    "Mbps": 1e6,
    "MB/s": 8e6,
    "Kbps": 1e3,
    "KB/s": 8e3,
    "Gbps": 1e9,
    "GB/s": 8e9,
    "KiB/s": 8192,
    "MiB/s": 8388608,
}
SIZE_UNITS = {"B": 1, "KB": 1000, "MB": 1e6, "GB": 1e9, "KiB": 1024, "MiB": 1048576}


def ordered(regions, mode):
    values = list(dict.fromkeys(regions))
    if mode == "Alphabetical":
        values.sort(key=str.casefold)
    elif mode == "Reverse alphabetical":
        values.sort(key=str.casefold, reverse=True)
    elif mode == "Random":
        random.shuffle(values)
    elif mode == "Location group":
        values.sort(key=lambda s: (s.split("-")[0].casefold(), s.casefold()))
    return values


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS attempts
                (id INTEGER PRIMARY KEY, time TEXT, region TEXT, attempt INTEGER,
                status TEXT, download REAL, upload REAL, latency REAL,
                endpoint TEXT, error TEXT, demo INTEGER, settings TEXT)""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def add(self, region, attempt, status, measurement=None, error="", demo=False, settings=None):
        m = measurement
        with self.connect() as db:
            db.execute(
                "INSERT INTO attempts VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    region,
                    attempt,
                    status,
                    m.download_mbps if m else None,
                    m.upload_mbps if m else None,
                    m.latency_ms if m else None,
                    m.server if m else "",
                    error,
                    int(demo),
                    json.dumps(settings or {}),
                ),
            )

    def rows(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY id DESC")]


@dataclass
class Settings:
    repeat: int = 1
    workers: int = 1
    command_timeout: float = 30
    connection_timeout: float = 60
    test_timeout: float = 180
    socket_timeout: float = 15
    endpoint: str = ""
    baseline: bool = True
    disconnect_existing: bool = False
    demo: bool = False
    pause: float = 0


class LoggedRunner(CommandRunner):
    def __init__(self, event, stop):
        self.event, self.stop = event, stop

    def run(self, args, timeout):
        cleanup = args[1:] in (["disconnect"], ["get", "connectionstate"])
        if self.stop.is_set() and not cleanup:
            raise CheckerError("Cancelled")
        self.event({"type": "log", "text": f"Execute ({timeout:g}s timeout): {args!r}"})
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise CheckerError(f"Cannot run {args[0]}: {exc}") from exc
        messages = queue.Queue()

        def read(stream, channel):
            for line in stream:
                messages.put((channel, line))
            messages.put((channel, None))

        threads = [
            threading.Thread(target=read, args=(stream, channel), daemon=True)
            for stream, channel in ((process.stdout, "stdout"), (process.stderr, "stderr"))
        ]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + timeout
        output, errors, closed = [], [], 0
        try:
            while closed < 2:
                if self.stop.is_set() and not cleanup:
                    raise CheckerError("Cancelled")
                if time.monotonic() >= deadline:
                    raise CheckerError(f"{args[0]} timed out after {timeout:g}s")
                try:
                    channel, line = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    closed += 1
                    continue
                (output if channel == "stdout" else errors).append(line)
                self.event({"type": "log", "text": f"{channel}: {line.rstrip()}"})
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if process.returncode:
                detail = "".join(errors or output)[-2000:]
                raise CheckerError(f"{args[0]} exited with code {process.returncode}: {detail}")
            return "".join(output)
        except subprocess.TimeoutExpired as exc:
            raise CheckerError(f"{args[0]} timed out after {timeout:g}s") from exc
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            for thread in threads:
                thread.join(timeout=2)
            process.stdout.close()
            process.stderr.close()


class Session:
    def __init__(self, vpn, settings, history, event, stop, factory=None):
        self.vpn, self.settings, self.history = vpn, settings, history
        self.event, self.stop = event, stop
        self.factory = factory

    def batch(self, region):
        s = self.settings

        def attempt(index):
            if self.stop.is_set():
                return
            self.event({"type": "log", "text": f"{region}: attempt {index}/{s.repeat}"})

            def telemetry(data):
                self.event({**data, "region": region, "attempt": index})

            try:
                if self.factory:
                    meter = self.factory()
                else:
                    meter = BundledSpeedtest(
                        s.test_timeout, s.socket_timeout, s.endpoint, self.stop, telemetry
                    )
                if s.demo:
                    for phase in ("download", "upload"):
                        for tick in range(8):
                            if self.stop.wait(0.08):
                                raise CheckerError("Cancelled")
                            telemetry(
                                {
                                    "type": "progress",
                                    "phase": phase,
                                    "bps": (80 if phase == "download" else 30) * 1e6,
                                    "bytes": (tick + 1) * 500000,
                                }
                            )
                measurement = meter.measure()
                self.history.add(
                    region, index, "success", measurement, demo=s.demo, settings=asdict(s)
                )
                telemetry({"type": "measurement", **asdict(measurement)})
            except Exception as exc:
                self.history.add(
                    region,
                    index,
                    "cancelled" if self.stop.is_set() else "error",
                    error=str(exc),
                    demo=s.demo,
                    settings=asdict(s),
                )
                telemetry({"type": "log", "text": f"Attempt failed: {exc}"})
            self.event({"type": "saved"})

        with ThreadPoolExecutor(max_workers=min(s.workers, s.repeat)) as pool:
            # Bounded submission prevents a huge queue and makes cancellation predictable.
            pending = {}
            next_index = 1
            while next_index <= s.repeat or pending:
                while (
                    not self.stop.is_set() and next_index <= s.repeat and len(pending) < s.workers
                ):
                    pending[pool.submit(attempt, next_index)] = next_index
                    next_index += 1
                if not pending:
                    break
                future = next(as_completed(pending))
                future.result()
                del pending[future]

    def run(self, regions):
        s = self.settings
        if s.repeat < 1 or not 1 <= s.workers <= 32:
            raise CheckerError("Repeat must be positive; workers must be between 1 and 32")
        if self.stop.is_set():
            return
        if self.vpn.state() != "disconnected":
            if not s.disconnect_existing:
                raise CheckerError("VPN is already active. Enable disconnect-existing explicitly.")
            self.vpn.disconnect()
        if s.baseline and not self.stop.is_set():
            self.batch("Baseline (no VPN)")
        for region in regions:
            if self.stop.is_set():
                break
            try:
                self.event({"type": "log", "text": f"Connecting: {region}"})
                self.vpn.connect(region)
                if not self.stop.is_set():
                    self.batch(region)
            except Exception as exc:
                self.history.add(
                    region,
                    0,
                    "cancelled" if self.stop.is_set() else "error",
                    error=str(exc),
                    demo=s.demo,
                    settings=asdict(s),
                )
                self.event({"type": "saved"})
                self.event({"type": "log", "text": str(exc)})
            finally:
                # Abort if cleanup fails: never test the next location on the wrong tunnel.
                self.vpn.disconnect()
            if self.stop.wait(s.pause):
                break
        self.event(
            {"type": "log", "text": "Cancelled" if self.stop.is_set() else "Session complete"}
        )
