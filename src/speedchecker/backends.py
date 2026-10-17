"""External CLIs are invoked without a shell, with bounded command/state waits."""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .models import CheckerError, Measurement

# Ookla's service can drop a transfer stream, answer with a 5xx, fail its
# HELLO handshake, or be unreachable via the VPN tunnel (DNS). These
# network/protocol failures are worth a retry; configuration/license errors
# are not.
_TRANSIENT_MARKERS = (
    "cannot write",
    "cannot retrieve configuration",
    "could not retrieve configuration",
    "could not read configuration",
    "configurationerror",
    "couldn't resolve host",
    "could not resolve host",
    "hostnotfound",
    "host not found",
    "name resolution",
    "11004",
    "wsa error",
    "cannot open",
    "connection reset",
    "connection refused",
    "connection aborted",
    "temporarily unavailable",
    "try again",
    "did not receive hello",
    "protocol error",
    "502",
    "503",
    "504",
)

_HINTS = (
    (
        "did not receive hello",
        "Ookla's protocol handshake failed — retry, check for proxy/firewall filtering, "
        "or use Auto/Built-in for the live Python engine",
    ),
    (
        "protocol error",
        "Ookla's protocol handshake failed — retry, check for proxy/firewall filtering, "
        "or use Auto/Built-in for the live Python engine",
    ),
    (
        "cannot write",
        "the upload/data stream was interrupted — retry; if it keeps happening "
        "check the VPN, firewall/antivirus, or MTU, or keep the built-in engine",
    ),
    (
        "cannot retrieve configuration",
        "Ookla's configuration service could not be reached — check the internet "
        "connection, VPN DNS, and firewall, or use the built-in engine (Auto/Built-in)",
    ),
    (
        "could not retrieve configuration",
        "Ookla's configuration service could not be reached — check the internet "
        "connection, VPN DNS, and firewall, or use the built-in engine (Auto/Built-in)",
    ),
    (
        "hostnotfound",
        "Ookla could not resolve the host — check VPN DNS, firewall, or try the built-in engine",
    ),
    (
        "couldn't resolve host",
        "Ookla could not resolve the host — check VPN DNS, firewall, or try the built-in engine",
    ),
    (
        "wsa error",
        "Windows network error (WSA) — check VPN, firewall/antivirus, or MTU, or keep the built-in engine",
    ),
    (
        "timed out",
        "raise the speed-test timeout in Settings and retry",
    ),
    (
        "cannot run",
        "the speedtest executable could not be started — check antivirus/permissions",
    ),
)


def _json_error(output: str) -> str | None:
    """Return Ookla's ``{"error": "..."}`` message when output is JSON."""
    for line in reversed((output or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            message = data["error"].strip().rstrip(":").strip()
            if message:
                return message
    return None


def _failure_detail(stderr: str, stdout: str) -> str:
    for output in (stderr, stdout):
        message = _json_error(output)
        if message is not None:
            return message
    return (stderr or stdout or "").strip()[-2000:]


def _is_transient(error: Exception) -> bool:
    message = str(error).casefold()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


def _with_hint(error: CheckerError) -> CheckerError:
    """Append an actionable hint to a known Ookla failure."""
    message = str(error)
    lowered = message.casefold()
    for marker, hint in _HINTS:
        if marker in lowered:
            return CheckerError(f"{message}\nHint: {hint}.")
    return error


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
            detail = _failure_detail(result.stderr, result.stdout)
            message = f"{args[0]} exited with code {result.returncode}"
            raise CheckerError(f"{message}: {detail}" if detail else message)
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
    """Official Ookla CLI, with one bounded retry for transient failures.

    ``attempts`` covers failures such as Ookla's ``{"error": "Cannot write: "}``
    (the transfer stream was interrupted) or a temporary 5xx from its
    configuration service.  Permanent errors (license, missing binary) are
    raised immediately, with an actionable hint.
    """

    def __init__(
        self,
        runner=None,
        timeout=180.0,
        accept_license=False,
        server_id: str = "",
        *,
        log=lambda message: None,
        attempts: int = 2,
        retry_delay: float = 1.5,
        cancel: threading.Event | None = None,
    ):
        self.runner = runner or CommandRunner()
        self.timeout = timeout
        self.accept_license = accept_license
        self.server_id = server_id
        self.log = log
        self.attempts = max(1, int(attempts))
        self.retry_delay = max(0.0, float(retry_delay))
        self.cancel = cancel

    def _args(self, binary: Path) -> list[str]:
        args = [str(binary), "--format=json", "--progress=no"]
        if self.server_id:
            args.append(f"--server-id={self.server_id}")
        if self.accept_license:
            args.extend(["--accept-license", "--accept-gdpr"])
        return args

    def _wait_before_retry(self) -> None:
        if self.cancel is not None:
            if self.cancel.wait(self.retry_delay):
                raise CheckerError("Test cancelled by user.")
        elif self.retry_delay:
            time.sleep(self.retry_delay)

    def measure(self) -> Measurement:
        binary = bundled_speedtest_binary()
        if binary is None:
            raise CheckerError(
                "No Ookla speedtest binary found. Put it in vendor/ (see vendor/README.md), "
                "add it to PATH, or use the built-in engine."
            )
        args = self._args(binary)
        error: CheckerError | None = None
        for attempt in range(1, self.attempts + 1):
            if self.cancel is not None and self.cancel.is_set():
                raise CheckerError("Test cancelled by user.")
            try:
                return Measurement.from_json(self.runner.run(args, self.timeout))
            except CheckerError as exc:
                error = exc
                if attempt >= self.attempts or not _is_transient(exc):
                    raise _with_hint(exc) from exc
                self.log(f"Ookla attempt {attempt}/{self.attempts} failed ({exc}) — retrying…")
                self._wait_before_retry()
        raise _with_hint(error)  # pragma: no cover - the loop always returns or raises


class FallbackSpeedtest:
    """Try one engine, then keep using its fallback for later measurements."""

    def __init__(
        self,
        primary,
        fallback_factory,
        log=lambda message: None,
        on_fallback=None,
        *,
        primary_name="primary",
        fallback_name="fallback",
    ):
        self.primary = primary
        self.fallback_factory = fallback_factory
        self.log = log
        self.on_fallback = on_fallback or (lambda: None)
        self.primary_name = primary_name
        self.fallback_name = fallback_name
        self._fallback = None

    def measure(self) -> Measurement:
        if self._fallback is not None:
            return self._fallback.measure()
        try:
            return self.primary.measure()
        except CheckerError as exc:
            if "cancelled by user" in str(exc).casefold():
                raise
            reason = " ".join(str(exc).split())
            if len(reason) > 240:
                reason = reason[:237] + "..."
            self._fallback = self.fallback_factory()
            self.on_fallback()
            self.log(
                f"↻ Engine fallback: {self.primary_name} failed ({reason}) — "
                f"using {self.fallback_name}."
            )
            return self._fallback.measure()


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
