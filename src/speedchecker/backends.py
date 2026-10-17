"""Network backends for ExpressVPN, bundled Speedtest and offline demos."""

import math
import shutil
import subprocess
import time
from urllib.parse import urlparse

from ._vendor import speedtest as bundled_speedtest
from .models import CheckerError, Measurement


class CommandRunner:
    def run(self, args: list[str], timeout: float) -> str:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CheckerError(f"{args[0]} timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise CheckerError(f"Cannot run {args[0]}: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            raise CheckerError(f"{args[0]} exited with code {result.returncode}: {detail}")
        return result.stdout


class ExpressVPN:
    def __init__(self, runner=None, command_timeout=30.0, connection_timeout=60.0):
        self.runner = runner or CommandRunner()
        self.command_timeout = command_timeout
        self.connection_timeout = connection_timeout

    def _run(self, *args: str, timeout: float | None = None) -> str:
        return self.runner.run(
            ["expressvpnctl", *args],
            self.command_timeout if timeout is None else timeout,
        ).strip()

    def regions(self) -> list[str]:
        regions = [
            line.strip() for line in self._run("get", "regions").splitlines() if line.strip()
        ]
        if not regions:
            raise CheckerError("ExpressVPN returned no regions. Check activation and login.")
        return regions

    def state(self) -> str:
        return self._run("get", "connectionstate").casefold()

    def _wait_for(self, expected: str) -> None:
        deadline = time.monotonic() + self.connection_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckerError(
                    f"VPN did not become {expected} within {self.connection_timeout:g}s"
                )
            state = self._run(
                "get",
                "connectionstate",
                timeout=min(self.command_timeout, remaining),
            ).casefold()
            if state == expected:
                return
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))

    def connect(self, region: str) -> float:
        start = time.monotonic()
        self._run("connect", region)
        self._wait_for("connected")
        return time.monotonic() - start

    def disconnect(self) -> None:
        self._run("disconnect")
        self._wait_for("disconnected")


class BundledSpeedtest:
    """Run the vendored speedtest-cli Python engine without a separate binary."""

    def __init__(self, timeout=180.0, speedtest_factory=None):
        self.timeout = timeout
        self.speedtest_factory = speedtest_factory or bundled_speedtest.Speedtest

    @staticmethod
    def _number(value, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CheckerError(f"Bundled Speedtest returned an invalid {label} value.")
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise CheckerError(f"Bundled Speedtest returned a non-finite {label} value.")
        return result

    def measure(self) -> Measurement:
        try:
            engine = self.speedtest_factory(timeout=self.timeout, secure=True)
            selected_server = engine.get_best_server()
            download_bps = self._number(engine.download(), "download")
            upload_bps = self._number(engine.upload(pre_allocate=False), "upload")
            result = engine.results.dict()
            server = result.get("server") or selected_server or {}
            if not isinstance(server, dict):
                raise CheckerError("Bundled Speedtest returned invalid server metadata.")

            host = (
                server.get("host") or server.get("url") or server.get("sponsor") or server.get("id")
            )
            if host is None:
                host = "Unknown speedtest server"
            host = str(host)
            parsed_host = urlparse(host).netloc
            if parsed_host:
                host = parsed_host
            country = server.get("country", "")
            location = server.get("location") or server.get("name") or ""
            server_location = ", ".join(str(value) for value in (country, location) if value)
            latency = result.get("ping", getattr(engine.results, "ping", None))
            return Measurement(
                download_bps / 1_000_000,
                upload_bps / 1_000_000,
                self._number(latency, "latency"),
                host,
                server_location,
            )
        except CheckerError:
            raise
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            raise CheckerError(f"Bundled Speedtest failed: {message}") from exc


class OoklaSpeedtest:
    """Optional adapter for users who specifically want Ookla's official CLI."""

    def __init__(self, runner=None, timeout=180.0, accept_license=False):
        self.runner = runner or CommandRunner()
        self.timeout = timeout
        self.accept_license = accept_license

    def measure(self) -> Measurement:
        args = ["speedtest", "--format=json", "--progress=no"]
        if self.accept_license:
            args.extend(["--accept-license", "--accept-gdpr"])
        return Measurement.from_json(self.runner.run(args, self.timeout))


def check_dependencies(require_ookla: bool = True) -> None:
    """Check ExpressVPN and, optionally, Ookla's non-bundled command-line app."""
    required = ["expressvpnctl"]
    if require_ookla:
        required.append("speedtest")
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        raise CheckerError("Missing executable(s) in PATH: " + ", ".join(missing))


class DemoVPN:
    """Offline simulator; never inspects or changes the host's network."""

    def __init__(self, regions: list[str]):
        self._regions = regions
        self.connected = False

    def regions(self) -> list[str]:
        return self._regions

    def state(self) -> str:
        return "connected" if self.connected else "disconnected"

    def connect(self, region: str) -> float:
        self.connected = True
        return 0.125

    def disconnect(self) -> None:
        self.connected = False


class DemoSpeedtest:
    def __init__(self, vpn: DemoVPN):
        self.vpn = vpn

    def measure(self) -> Measurement:
        return Measurement(
            80.25 if self.vpn.connected else 100.5,
            30.5 if self.vpn.connected else 40.75,
            25.0 if self.vpn.connected else 10.0,
            "demo.invalid",
            "Simulated server",
        )
