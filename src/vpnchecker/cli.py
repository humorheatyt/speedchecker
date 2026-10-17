"""CLI entry point shared by vpnchecker and expressvpnspeedtest."""

import argparse
import math
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .backends import DemoSpeedtest, DemoVPN, ExpressVPN, OoklaSpeedtest, check_dependencies
from .benchmark import benchmark
from .models import CheckerError, load_locations, slug
from .storage import ReportStore


def positive_int(value: str) -> int:
    try:
        result = int(value)
        if result < 1:
            raise ValueError
        return result
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer greater than zero") from exc


def positive_float(value: str) -> float:
    try:
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError
        return result
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Benchmark ExpressVPN locations using the official Ookla Speedtest CLI.",
        epilog="Tests consume substantial data. VPN connections made by this tool are disconnected "
        "after testing. Use --demo for an offline simulation without network changes.",
    )
    result.add_argument("input_file", type=Path, help="JSON file containing a locations array")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    result.add_argument("-s", "--serial", action="store_true", help="run tests one after another")
    result.add_argument(
        "-r",
        "--repeat",
        "--repeatSpeedTest",
        type=positive_int,
        default=5,
        help="tests per baseline/location (default: 5; at most 32 simultaneous workers)",
    )
    result.add_argument(
        "-o", "--output", type=Path, help="new JSON report path (never overwritten)"
    )
    result.add_argument(
        "--command-timeout",
        type=positive_float,
        default=30,
        help="timeout per VPN CLI command in seconds (default: 30)",
    )
    result.add_argument(
        "--connection-timeout",
        type=positive_float,
        default=60,
        help="timeout for each connected/disconnected state wait (default: 60)",
    )
    result.add_argument(
        "--speedtest-timeout",
        type=positive_float,
        default=180,
        help="timeout per speed test in seconds (default: 180)",
    )
    result.add_argument(
        "--disconnect-existing",
        action="store_true",
        help="allow disconnecting an existing VPN; it will NOT be restored",
    )
    result.add_argument(
        "--accept-license",
        action="store_true",
        help="explicitly accept Ookla's license and GDPR terms for the Speedtest CLI",
    )
    result.add_argument(
        "--demo", action="store_true", help="use simulated data; no external commands"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    old_handler = None
    handler_installed = False
    try:
        locations = load_locations(args.input_file)
        if args.demo:
            vpn = DemoVPN(
                [
                    loc.region or slug("-".join(filter(None, (loc.country, loc.city))))
                    for loc in locations
                ]
            )
            speedtest = DemoSpeedtest(vpn)
            print("DEMO: synthetic measurements; no network or VPN changes.")
        else:
            check_dependencies()
            vpn = ExpressVPN(
                command_timeout=args.command_timeout,
                connection_timeout=args.connection_timeout,
            )
            speedtest = OoklaSpeedtest(
                timeout=args.speedtest_timeout,
                accept_license=args.accept_license,
            )
        output = args.output or Path(
            "results-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
        )

        def interrupt(signum, frame):
            raise KeyboardInterrupt

        # Let SIGTERM follow the same cleanup path as Ctrl+C.
        old_handler = signal.signal(signal.SIGTERM, interrupt)
        handler_installed = True
        report = benchmark(
            locations,
            vpn,
            speedtest,
            ReportStore(output),
            count=args.repeat,
            serial=args.serial,
            disconnect_existing=args.disconnect_existing,
            demo=args.demo,
        )
        print(f"Report: {output} ({report['Status']})")
        return 0 if report["Status"] == "completed" else 1
    except CheckerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Any completed measurements were saved.", file=sys.stderr)
        return 130
    finally:
        if handler_installed:
            signal.signal(signal.SIGTERM, old_handler)
