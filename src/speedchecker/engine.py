"""Built-in pure-Python speed-test engine — bundled with the project.

No external ``speedtest`` executable is required: cloning the repo is
enough. It speaks to ordinary Speedtest.net servers over HTTP:

* latency  – repeated GET of ``latency.txt`` (min value wins)
* download – streamed ``random{350,500,750,1000,1500,2000,2500,3000,3500,4000}x…jpg``
* upload   – POST of generated payloads to the server's upload endpoint

Progress is reported live through ``progress(phase, value, bytes_done)``:
``value`` is Mbps for download/upload and milliseconds for latency. This keeps
both gauges, the chart, and the ping readout current in real time. Cancellation
is cooperative via a ``threading.Event``.
"""

import http.client
import random
import threading
import time
import urllib.parse
import urllib.request

from .models import CheckerError, Measurement
from .servers import Server

_SIZES = (350, 500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000)
# Keep uploads ≤1.5 MiB — larger bodies trigger HTTP 500 on many
# Speedtest.net hosts and trip Windows firewall/AV (WSAECONNABORTED 10053).
_PAYLOADS = (100_000, 300_000, 500_000, 800_000, 1_000_000, 1_500_000)


class BuiltinSpeedtest:
    """Drop-in replacement for the Ookla binary backend (``.measure()``)."""

    def __init__(
        self,
        server: Server | None = None,
        *,
        timeout: float = 30.0,
        duration: float = 10.0,
        connections: int = 4,
        progress=None,
        log=lambda msg: None,
        cancel: threading.Event | None = None,
    ):
        self.server = server
        self.timeout = timeout
        self.duration = max(1.0, duration)
        self.connections = max(1, min(connections, 16))
        self.progress = progress or (lambda phase, mbps, done: None)
        self.log = log
        self.cancel = cancel or threading.Event()

    # -- helpers ---------------------------------------------------------
    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise CheckerError("Test cancelled by user.")

    def _latency(self, server: Server) -> float:
        url = server.base_url + "latency.txt"
        self.log(f"Ping {url}")
        best: float | None = None
        for _ in range(3):
            self._check_cancel()
            start = time.perf_counter()
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "speedchecker/2.0"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response.read()
            except Exception as exc:
                self.log(f"  latency probe failed: {exc}")
                continue
            elapsed = (time.perf_counter() - start) * 1000
            best = elapsed if best is None else min(best, elapsed)
            self.progress("latency", best, 0)
        if best is None:  # fall back to a raw TCP connect timing
            import socket

            host = server.host.split(":")[0]
            port = int(server.host.rsplit(":", 1)[1]) if ":" in server.host else 80
            start = time.perf_counter()
            try:
                with socket.create_connection((host, port), timeout=self.timeout):
                    pass
            except OSError as exc:
                raise CheckerError(f"Cannot reach {server.host}: {exc}") from exc
            best = (time.perf_counter() - start) * 1000
            self.progress("latency", best, 0)
        self.log(f"  latency {best:.2f} ms")
        return best

    def _transfer(self, server: Server, phase: str) -> float:
        """Run one phase with N parallel workers; return average Mbps."""
        total = [0]  # bytes accepted for the final throughput result
        live_total = [0]  # bytes transferred so far, including in-flight uploads
        lock = threading.Lock()
        deadline = time.monotonic() + self.duration
        started = time.monotonic()

        def report_progress(n: int, *, accepted: bool) -> None:
            with lock:
                live_total[0] += n
                if accepted:
                    total[0] += n
                progress_bytes = live_total[0]
            elapsed = max(time.monotonic() - started, 0.001)
            self.progress(phase, progress_bytes * 8 / elapsed / 1_000_000, progress_bytes)

        def bump(n: int) -> None:
            report_progress(n, accepted=True)

        def report_upload_chunk(n: int) -> None:
            report_progress(n, accepted=False)

        def accept_upload(n: int) -> None:
            with lock:
                total[0] += n

        def download_worker() -> None:
            size_index = 0
            while time.monotonic() < deadline and not self.cancel.is_set():
                size = _SIZES[min(size_index, len(_SIZES) - 1)]
                size_index += 1
                url = f"{server.base_url}random{size}x{size}.jpg"
                try:
                    request = urllib.request.Request(
                        url, headers={"User-Agent": "speedchecker/2.0"}
                    )
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        while time.monotonic() < deadline and not self.cancel.is_set():
                            chunk = response.read(65_536)
                            if not chunk:
                                break
                            bump(len(chunk))
                except Exception as exc:
                    self.log(f"  download stream error: {exc}")
                    time.sleep(0.1)

        def upload_worker() -> None:
            index = 0
            rng = random.Random()
            consecutive_errors = 0
            while time.monotonic() < deadline and not self.cancel.is_set():
                size = _PAYLOADS[min(index, len(_PAYLOADS) - 1)]
                body = rng.randbytes(size)
                parts = urllib.parse.urlsplit(server.url or server.base_url + "upload.php")
                conn = None
                try:
                    conn_cls = (
                        http.client.HTTPSConnection
                        if parts.scheme == "https"
                        else http.client.HTTPConnection
                    )
                    conn = conn_cls(parts.hostname, parts.port, timeout=self.timeout)
                    target = parts.path or "/"
                    if parts.query:
                        target = f"{target}?{parts.query}"
                    conn.putrequest("POST", target)
                    # Host must include port for non-standard ports (e.g. :8080)
                    # or some servers return 500.
                    if parts.netloc:
                        conn.putheader("Host", parts.netloc)
                    conn.putheader("User-Agent", "speedchecker/2.0")
                    conn.putheader("Content-Type", "application/octet-stream")
                    conn.putheader("Content-Length", str(len(body)))
                    conn.putheader("Connection", "close")
                    conn.putheader("Accept", "*/*")
                    conn.endheaders()
                    # Send in chunks so upload gauges are refreshed while data
                    # is actually moving, not only after the server responds.
                    for offset in range(0, len(body), 65_536):
                        if self.cancel.is_set():
                            return
                        chunk = body[offset : offset + 65_536]
                        conn.send(chunk)
                        report_upload_chunk(len(chunk))
                    response = conn.getresponse()
                    response.read()
                    if response.status < 200 or response.status >= 300:
                        raise CheckerError(f"Upload rejected: HTTP {response.status}")
                    accept_upload(len(body))
                    consecutive_errors = 0
                    # Grow payload on success; shrink on failure to stay compatible.
                    index = min(index + 1, len(_PAYLOADS) - 1)
                except CheckerError as exc:
                    # HTTP 5xx / explicit rejection — try smaller body next time
                    self.log(f"  upload stream error: {exc}")
                    consecutive_errors += 1
                    index = max(0, index - 1) if consecutive_errors >= 2 else index
                    time.sleep(0.15)
                except Exception as exc:
                    self.log(f"  upload stream error: {exc}")
                    consecutive_errors += 1
                    # On transport errors (e.g. WinError 10053) keep size stable
                    time.sleep(0.15)
                finally:
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass

        worker = download_worker if phase == "download" else upload_worker
        self.log(
            f"{phase.capitalize()} test: {self.connections} connection(s), "
            f"~{self.duration:g}s, server {server.host}"
        )
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(self.connections)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=self.duration + self.timeout + 5)
        self._check_cancel()
        elapsed = max(time.monotonic() - started, 0.001)
        mbps = total[0] * 8 / elapsed / 1_000_000
        self.log(f"  {phase}: {total[0]} bytes in {elapsed:.2f}s = {mbps:.2f} Mbps")
        if total[0] == 0:
            raise CheckerError(f"{phase.capitalize()} test transferred no data via {server.host}.")
        return mbps

    # -- public API (same shape as OoklaSpeedtest) ------------------------
    def measure(self) -> Measurement:
        from .servers import fetch_servers, sort_servers

        server = self.server
        if server is None:
            self.log("No server selected — fetching list and choosing the nearest…")
            server = sort_servers(fetch_servers(timeout=self.timeout, log=self.log), "distance")[0]
        self.log(
            f"Testing against {server.label} ({server.host}) sponsored by {server.sponsor or '—'}"
        )
        latency = self._latency(server)
        download = self._transfer(server, "download")
        upload = self._transfer(server, "upload")
        self.progress("done", 0.0, 0)
        return Measurement(download, upload, latency, server.host, server.label)


class DemoSpeedtestLive:
    """Simulated engine with live progress (offline demo mode)."""

    def __init__(
        self,
        server: Server | None = None,
        *,
        duration: float = 3.0,
        progress=None,
        log=lambda msg: None,
        cancel: threading.Event | None = None,
        base_download: float = 92.0,
        base_upload: float = 38.0,
    ):
        self.server = server
        self.duration = max(0.5, duration)
        self.progress = progress or (lambda phase, mbps, done: None)
        self.log = log
        self.cancel = cancel or threading.Event()
        self.base_download, self.base_upload = base_download, base_upload

    def measure(self) -> Measurement:
        server = self.server
        label = server.label if server else "Demo server"
        host = server.host if server else "demo.invalid"
        self.log(f"[demo] Testing against {label} ({host})")
        rng = random.Random()
        latency = rng.uniform(8, 45)
        self.progress("latency", latency, 0)
        results = {}
        for phase, base in (("download", self.base_download), ("upload", self.base_upload)):
            steps = 20
            done = 0
            for _step in range(steps):
                if self.cancel.is_set():
                    raise CheckerError("Test cancelled by user.")
                time.sleep(self.duration / steps)
                live = base * rng.uniform(0.75, 1.1)
                done += int(live * 1_000_000 / 8 * (self.duration / steps))
                self.progress(phase, live, done)
            results[phase] = base * rng.uniform(0.92, 1.02)
            self.log(f"[demo] {phase}: {results[phase]:.2f} Mbps")
        return Measurement(results["download"], results["upload"], latency, host, label)
