"""Sequential VPN changes, concurrent measurements, single-writer reports."""

import platform
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .models import Batch, CheckerError, Location


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_batch(speedtest, count: int, serial: bool) -> Batch:
    if count < 1:
        raise CheckerError("Repeat count must be at least 1.")
    samples, errors = {}, {}

    def collect(index, action):
        try:
            samples[index] = action()
        except CheckerError as exc:
            errors[index] = str(exc)

    if serial:
        for index in range(count):
            collect(index, speedtest.measure)
    else:
        # Bound resource usage even when a large repeat count is requested.
        with ThreadPoolExecutor(max_workers=min(count, 32)) as executor:
            futures = {executor.submit(speedtest.measure): index for index in range(count)}
            try:
                for future in as_completed(futures):
                    collect(futures[future], future.result)
            finally:
                for future in futures:
                    future.cancel()
    return Batch(
        [samples[index] for index in sorted(samples)],
        [errors[index] for index in sorted(errors)],
    )


def benchmark(
    locations: list[Location],
    vpn,
    speedtest,
    store,
    *,
    count=5,
    serial=False,
    disconnect_existing=False,
    demo=False,
    log=print,
) -> dict:
    report = {
        "SchemaVersion": 2,
        "MachineName": socket.gethostname(),
        "OS": platform.platform(),
        "WithoutVPN": "",
        "Baseline": None,
        "VPNStats": [],
        "Errors": [],
        "StartedAt": timestamp(),
        "Status": "running",
        "Demo": demo,
        "Settings": {"Repeat": count, "Serial": serial},
    }
    store.reserve()
    store.save(report)
    try:
        regions = vpn.regions()
        state = vpn.state()
        if state != "disconnected":
            if not disconnect_existing:
                raise CheckerError(
                    f"VPN state is {state!r}. Disconnect it first, or explicitly use "
                    "--disconnect-existing. The original connection will not be restored."
                )
            log("Disconnecting existing VPN connection before baseline measurement...")
            vpn.disconnect()
        log(f"Measuring baseline: {count} test(s) {'in series' if serial else 'in parallel'}...")
        baseline = run_batch(speedtest, count, serial).summary()
        report["Baseline"] = baseline
        report["WithoutVPN"] = (
            f"{baseline['DownloadMbps']:.2f}Mbps ▼  {baseline['UploadMbps']:.2f}Mbps ▲"
        )
        store.save(report)
        for location in locations:
            region = location.find_region(regions)
            if region is None:
                message = f"No matching region for {location.name}"
                report["Errors"].append({"Location": location.name, "Error": message})
                log(f"Skipping: {message}")
                store.save(report)
                continue
            log(f"Connecting to {location.name} ({region})...")
            try:
                elapsed = vpn.connect(region)
                summary = run_batch(speedtest, count, serial).summary()
                report["VPNStats"].append(
                    {
                        "LocationName": location.name,
                        "Region": region,
                        "TimeToConnect": f"{elapsed:.3f}s",
                        "VPNDownloadSpeed": f"{summary['DownloadMbps']:.2f}Mbps",
                        "VPNUploadSpeed": f"{summary['UploadMbps']:.2f}Mbps",
                        "VPNLatency": f"{summary['LatencyMs']:.2f}ms",
                        "Server": ", ".join(dict.fromkeys(s["server"] for s in summary["Samples"])),
                        "Date/Time": timestamp(),
                        "Mode": (
                            "Tests ran in series (one after another)"
                            if serial
                            else "Tests ran in parallel"
                        ),
                        **summary,
                    }
                )
                log(
                    f"  {summary['DownloadMbps']:.2f} Mbps down / "
                    f"{summary['UploadMbps']:.2f} Mbps up / {summary['LatencyMs']:.2f} ms"
                )
            except CheckerError as exc:
                report["Errors"].append({"Location": location.name, "Error": str(exc)})
                log(f"Failed: {exc}")
            finally:
                # A failed connect command may still have established a tunnel.
                # If cleanup fails, abort rather than measure the next region on that tunnel.
                try:
                    vpn.disconnect()
                finally:
                    store.save(report)
        partial = (
            report["Errors"]
            or baseline["FailedTests"]
            or any(stat["FailedTests"] for stat in report["VPNStats"])
        )
        report["Status"] = "partial" if partial else "completed"
    except KeyboardInterrupt:
        report["Status"] = "interrupted"
        report["Errors"].append({"Error": "Interrupted by user"})
        raise
    except Exception as exc:
        report["Status"] = "failed"
        report["Errors"].append({"Error": str(exc)})
        raise
    finally:
        report["FinishedAt"] = timestamp()
        store.save(report)
    return report
