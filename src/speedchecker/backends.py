"""External CLIs are invoked without a shell, with bounded command/state waits."""

import shutil
import subprocess
import time
from pathlib import Path

from .models import CheckerError, Measurement


def bundled_speedtest_binary() -> Path | None:
    """Ookla binary bundled with the project: ``<repo>/vendor/speedtest[.exe]``.

    Drop the official binary there and it is used automatically — no
    system-wide ``speedtest`` installation needed. Falls back to PATH.
    """
    root = Path(__file__).resolve().parents[2]
    for name in ("speedtest.exe", "speedtest"):
        candidate = root / "vendor" / name
        if candidate.is_file():
            return candidate
    found = shutil.which("speedtest")
    return Path(found) if found else None


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


class OoklaSpeedtest:
    def __init__(self, runner=None, timeout=180.0, accept_license=False, server_id: str = ""):
        self.runner = runner or CommandRunner()
        self.timeout = timeout
        self.accept_license = accept_license
        self.server_id = server_id

    def measure(self) -> Measurement:
        binary = bundled_speedtest_binary()
        if binary is None:
            raise CheckerError(
                "No Ookla speedtest binary found. Put it in vendor/ (see vendor/README.md), "
                "add it to PATH, or use the built-in engine."
            )
        args = [str(binary), "--format=json", "--progress=no"]
        if self.server_id:
            args.append(f"--server-id={self.server_id}")
        if self.accept_license:
            args.extend(["--accept-license", "--accept-gdpr"])
        return Measurement.from_json(self.runner.run(args, self.timeout))


def check_dependencies(require_speedtest_binary: bool = False) -> None:
    missing = []
    if not shutil.which("expressvpnctl"):
        missing.append("expressvpnctl")
    if require_speedtest_binary and bundled_speedtest_binary() is None:
        missing.append("speedtest (vendor/ or PATH)")
    if missing:
        raise CheckerError("Missing executable(s): " + ", ".join(missing))


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
