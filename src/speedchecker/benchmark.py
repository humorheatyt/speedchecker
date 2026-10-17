"""Sequential VPN changes, bounded concurrent measurements, live progress."""

import platform
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .models import Batch, CheckerError, Location, Measurement
from .units import convert_latency, format_speed


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_batch(speedtest, count: int, serial: bool, *, on_sample=None, stop_event=None) -> Batch:
    if count < 1:
        raise CheckerError("Repeat count must be at least 1.")
    samples, errors = {}, {}

    def check_stop():
        if stop_event is not None and stop_event.is_set():
            raise KeyboardInterrupt("Stop requested from dashboard")

    def collect(index, action):
        try:
            samples[index] = action()
        except CheckerError as exc:
            errors[index] = str(exc)
        finally:
            if on_sample is not None:
                on_sample(index, samples.get(index), errors.get(index))

    if serial:
        for index in range(count):
            if stop_event is not None and stop_event.is_set():
                if samples or errors:
                    break
                check_stop()
            collect(index, speedtest.measure)
    else:
        check_stop()
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
    display_unit="Mbps",
    latency_unit="ms",
    log=print,
    progress=None,
    report_callback=None,
    stop_event=None,
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
        "Settings": {
            "Repeat": count,
            "Serial": serial,
            "DisplayUnit": display_unit,
            "LatencyUnit": latency_unit,
        },
    }

    def save_report():
        store.save(report)
        if report_callback is not None:
            report_callback(report)

    def emit(event_type: str, **values):
        if progress is not None:
            progress({"type": event_type, "at": timestamp(), **values})

    def check_stop():
        if stop_event is not None and stop_event.is_set():
            raise KeyboardInterrupt("Stop requested from dashboard")

    def batch_callback(phase: str, location: str | None = None):
        lock = threading.Lock()
        completed = 0

        def on_sample(index: int, sample: Measurement | None, error: str | None):
            nonlocal completed
            with lock:
                completed += 1
                done = completed
            event = {
                "type": "sample",
                "at": timestamp(),
                "phase": phase,
                "location": location,
                "index": index + 1,
                "completed": done,
                "total": count,
            }
            if sample is not None:
                event["measurement"] = {
                    "download_mbps": sample.download_mbps,
                    "upload_mbps": sample.upload_mbps,
                    "latency_ms": sample.latency_ms,
                    "server": sample.server,
                    "server_location": sample.server_location,
                }
            else:
                event["error"] = error or "Measurement failed"
            if progress is not None:
                progress(event)

        return on_sample

    store.reserve()
    save_report()
    emit("job_started", message="Benchmark started", total_locations=len(locations))
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
            emit("log", message="Disconnecting the existing VPN before the baseline.")
            vpn.disconnect()
        check_stop()
        log(f"Measuring baseline: {count} test(s) {'in series' if serial else 'in parallel'}...")
        emit(
            "phase",
            phase="baseline",
            current=0,
            total=count,
            message="در حال سنجش اتصال پایه، پیش از مقایسهٔ VPN",
        )
        baseline_batch = run_batch(
            speedtest,
            count,
            serial,
            on_sample=batch_callback("baseline"),
            stop_event=stop_event,
        )
        if stop_event is not None and stop_event.is_set() and not baseline_batch.samples:
            report["Errors"].append({"Error": "Stopped before a successful baseline measurement"})
            raise KeyboardInterrupt("Stop requested from dashboard")
        baseline = baseline_batch.summary()
        report["Baseline"] = baseline
        report["WithoutVPN"] = (
            f"{baseline['DownloadMbps']:.2f}Mbps ▼  {baseline['UploadMbps']:.2f}Mbps ▲"
        )
        save_report()
        emit("baseline_complete", message="سنجش اتصال پایه کامل شد.", summary=baseline)
        check_stop()

        for index, location in enumerate(locations, 1):
            check_stop()
            region = location.find_region(regions)
            if region is None:
                message = f"No matching region for {location.name}"
                report["Errors"].append({"Location": location.name, "Error": message})
                log(f"Skipping: {message}")
                emit("location_skipped", location=location.name, message=message)
                save_report()
                continue
            log(f"Connecting to {location.name} ({region})...")
            emit(
                "location_start",
                phase="connecting",
                location=location.name,
                region=region,
                location_index=index,
                location_total=len(locations),
                message=f"در حال اتصال به {location.name}",
            )
            try:
                elapsed = vpn.connect(region)
                check_stop()
                emit(
                    "phase",
                    phase="vpn-test",
                    current=0,
                    total=count,
                    location=location.name,
                    message=f"در حال سنجش سرعت در {location.name}",
                )
                batch = run_batch(
                    speedtest,
                    count,
                    serial,
                    on_sample=batch_callback("vpn", location.name),
                    stop_event=stop_event,
                )
                if stop_event is not None and stop_event.is_set() and not batch.samples:
                    report["Errors"].append(
                        {
                            "Location": location.name,
                            "Error": "Stopped before a successful location measurement",
                        }
                    )
                    raise KeyboardInterrupt("Stop requested from dashboard")
                summary = batch.summary()
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
                    f"  {format_speed(summary['DownloadMbps'], display_unit)} down / "
                    f"{format_speed(summary['UploadMbps'], display_unit)} up / "
                    f"{convert_latency(summary['LatencyMs'], latency_unit):.2f} {latency_unit}"
                )
                emit(
                    "location_complete",
                    location=location.name,
                    region=region,
                    summary=summary,
                    message=f"اندازه‌گیری {location.name} کامل شد.",
                )
                check_stop()
            except CheckerError as exc:
                report["Errors"].append({"Location": location.name, "Error": str(exc)})
                log(f"Failed: {exc}")
                emit("location_failed", location=location.name, message=str(exc))
            finally:
                # A failed connect command may still have established a tunnel.
                # Always clean up before testing another region or stopping.
                try:
                    vpn.disconnect()
                finally:
                    save_report()
        partial = (
            report["Errors"]
            or baseline["FailedTests"]
            or any(stat["FailedTests"] for stat in report["VPNStats"])
        )
        report["Status"] = "partial" if partial else "completed"
    except KeyboardInterrupt:
        report["Status"] = "interrupted"
        report["Errors"].append({"Error": "Interrupted by user"})
        emit("stopping", message="Stopping safely and cleaning up the VPN connection")
        raise
    except Exception as exc:
        report["Status"] = "failed"
        report["Errors"].append({"Error": str(exc)})
        emit("run_failed", message=str(exc))
        raise
    finally:
        report["FinishedAt"] = timestamp()
        save_report()
        emit("job_finished", status=report["Status"], message="اجرای تست پایان یافت.")
    return report
