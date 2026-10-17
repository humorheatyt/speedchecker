"""Bounded subprocess wrapper; cancellation kills only our measurement child."""

import json
import math
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from .models import CheckerError, Measurement


class BundledSpeedtest:
    def __init__(self, timeout=180, socket_timeout=15, endpoint="", stop=None, event=None):
        self.timeout = timeout
        self.socket_timeout = socket_timeout
        self.endpoint = endpoint
        self.stop = stop or threading.Event()
        self.event = event or (lambda data: None)

    def measure(self):
        command = [
            sys.executable,
            str(Path(__file__).with_name("speed_worker.py")),
            str(self.socket_timeout),
            str(self.endpoint),
        ]
        self.event({"type": "log", "text": "Execute: " + " ".join(command)})
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines = queue.Queue()

        def read():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + self.timeout
        result = None
        try:
            while True:
                if self.stop.is_set():
                    raise CheckerError("Cancelled")
                if time.monotonic() >= deadline:
                    raise CheckerError(f"Speed test timed out after {self.timeout}s")
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                try:
                    data = json.loads(line)
                except ValueError:
                    self.event({"type": "log", "text": line.rstrip()})
                    continue
                self.event(data)
                if data["type"] == "error":
                    raise CheckerError(data["text"])
                if data["type"] == "result":
                    result = data["result"]
            process.wait(timeout=2)
            if process.returncode or result is None:
                raise CheckerError("Bundled speedtest exited without a valid result")
            try:
                numbers = [result[key] for key in ("download", "upload", "ping")]
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                    for value in numbers
                ):
                    raise ValueError("speed and latency must be finite non-negative numbers")
                host = result["server"]["host"]
                if not isinstance(host, str) or not host:
                    raise ValueError("missing endpoint host")
                measurement = Measurement(
                    numbers[0] / 1e6,
                    numbers[1] / 1e6,
                    numbers[2],
                    host,
                    result["server"].get("name", ""),
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise CheckerError(f"Invalid bundled speedtest result: {exc}") from exc
            return measurement
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=2)
            process.stdout.close()
