"""Flask dashboard and background benchmark job manager."""

from __future__ import annotations

import copy
import math
import shutil
import threading
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import __version__
from .backends import BundledSpeedtest, DemoSpeedtest, DemoVPN, ExpressVPN, check_dependencies
from .benchmark import benchmark
from .models import CheckerError, load_locations, slug
from .storage import ReportStore
from .units import LATENCY_UNITS, SPEED_UNITS


def _project_locations_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    checkout_locations = project_root / "locations.json"
    if checkout_locations.is_file():
        return checkout_locations
    return Path(__file__).resolve().parent / "data" / "locations.json"


def _positive_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number greater than zero.")
    result = float(value)
    if not math.isfinite(result) or result <= 0 or result > 3600:
        raise ValueError(f"{name} must be between zero and 3600 seconds.")
    return result


def _compact_report(report: dict | None) -> dict | None:
    if report is None:
        return None

    def compact(summary):
        if not summary:
            return None
        return {
            key: summary.get(key)
            for key in (
                "DownloadMbps",
                "UploadMbps",
                "LatencyMs",
                "SuccessfulTests",
                "FailedTests",
            )
        }

    return {
        "status": report.get("Status", "running"),
        "demo": report.get("Demo", False),
        "baseline": compact(report.get("Baseline")),
        "stats": [
            {
                "LocationName": stat.get("LocationName", ""),
                "Region": stat.get("Region", ""),
                "TimeToConnect": stat.get("TimeToConnect", ""),
                "DownloadMbps": stat.get("DownloadMbps"),
                "UploadMbps": stat.get("UploadMbps"),
                "LatencyMs": stat.get("LatencyMs"),
                "SuccessfulTests": stat.get("SuccessfulTests", 0),
                "FailedTests": stat.get("FailedTests", 0),
            }
            for stat in report.get("VPNStats", [])
        ],
        "errors": copy.deepcopy(report.get("Errors", [])),
    }


class JobManager:
    """Own one active test run and a small, replayable stream of UI events."""

    def __init__(self, locations_path: Path, output_dir: Path, event_limit: int = 500):
        self.locations_path = Path(locations_path)
        self.output_dir = Path(output_dir)
        self._lock = threading.RLock()
        self._events = deque(maxlen=event_limit)
        self._event_id = 0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._output_path: Path | None = None
        self._state = self._idle_state()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "active": False,
            "status": "idle",
            "phase": "idle",
            "message": "آمادهٔ شروع تست هستید.",
            "progress": {"current": 0, "total": 0},
            "currentLocation": None,
            "output": None,
            "report": None,
            "error": None,
            "startedAt": None,
            "finishedAt": None,
        }

    def _publish(self, event: dict) -> None:
        with self._lock:
            self._event_id += 1
            item = {"id": self._event_id, **copy.deepcopy(event)}
            self._events.append(item)
            event_type = item.get("type")
            message = item.get("message")
            if message:
                self._state["message"] = message
            if event_type == "job_started":
                self._state["active"] = True
                self._state["status"] = "running"
                self._state["startedAt"] = item.get("at")
                self._state["error"] = None
            elif event_type in {"phase", "sample"}:
                if item.get("phase"):
                    self._state["phase"] = item["phase"]
                if item.get("location"):
                    self._state["currentLocation"] = item["location"]
                if item.get("total") is not None and item.get("completed") is not None:
                    self._state["progress"] = {
                        "current": item["completed"],
                        "total": item["total"],
                    }
                elif item.get("total") is not None:
                    self._state["progress"] = {
                        "current": item.get("current", 0),
                        "total": item["total"],
                    }
            elif event_type == "location_start":
                self._state["phase"] = "connecting"
                self._state["currentLocation"] = item.get("location")
                self._state["progress"] = {"current": 0, "total": 0}
            elif event_type == "stopping":
                self._state["status"] = "stopping"
            elif event_type == "run_failed":
                self._state["error"] = message
            elif event_type == "job_finished":
                self._state["active"] = False
                self._state["status"] = item.get("status", "failed")
                self._state["phase"] = "finished"
                self._state["finishedAt"] = item.get("at")

    def _set_report(self, report: dict) -> None:
        with self._lock:
            self._state["report"] = _compact_report(report)

    def start(self, options: dict) -> dict:
        if not isinstance(options, dict):
            raise ValueError("The request body must be a JSON object.")
        repeat = options.get("repeat", 3)
        if type(repeat) is not int or not 1 <= repeat <= 32:
            raise ValueError("Repeat count must be an integer from 1 to 32.")
        for key in ("serial", "demo", "disconnectExisting"):
            if key in options and type(options[key]) is not bool:
                raise ValueError(f"{key} must be true or false.")
        display_unit = options.get("displayUnit", "Mbps")
        latency_unit = options.get("latencyUnit", "ms")
        if display_unit not in SPEED_UNITS:
            raise ValueError("Choose a supported speed unit.")
        if latency_unit not in LATENCY_UNITS:
            raise ValueError("Choose a supported latency unit.")
        timeouts = {
            "speedtestTimeout": _positive_number(
                options.get("speedtestTimeout", 180), "Speedtest timeout"
            ),
            "commandTimeout": _positive_number(
                options.get("commandTimeout", 30), "VPN command timeout"
            ),
            "connectionTimeout": _positive_number(
                options.get("connectionTimeout", 60), "VPN connection timeout"
            ),
        }
        settings = {
            "repeat": repeat,
            "serial": options.get("serial", True),
            "demo": options.get("demo", False),
            "disconnect_existing": options.get("disconnectExisting", False),
            "display_unit": display_unit,
            "latency_unit": latency_unit,
            **timeouts,
        }
        locations = load_locations(self.locations_path)
        with self._lock:
            if self._state["active"]:
                raise ValueError("A test is already running.")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            self._output_path = self.output_dir / f"results-web-{stamp}.json"
            self._stop_event = threading.Event()
            self._state = {
                **self._idle_state(),
                "active": True,
                "status": "running",
                "phase": "preparing",
                "message": "در حال آماده‌سازی تست…",
                "progress": {"current": 0, "total": repeat},
                "output": self._output_path.name,
                "startedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            worker = threading.Thread(
                target=self._run,
                args=(locations, settings, self._output_path, self._stop_event),
                name="speedchecker-benchmark",
                daemon=True,
            )
            self._thread = worker
            self._publish(
                {
                    "type": "job_started",
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "message": "تست جدید شروع شد.",
                    "repeat": repeat,
                    "total_locations": len(locations),
                }
            )
            worker.start()
        return self.snapshot()["job"]

    def _run(self, locations, settings: dict, output_path: Path, stop_event) -> None:
        status = "failed"
        try:
            if settings["demo"]:
                vpn = DemoVPN(
                    [
                        loc.region or slug("-".join(filter(None, (loc.country, loc.city))))
                        for loc in locations
                    ]
                )
                speedtest = DemoSpeedtest(vpn)
                self._publish(
                    {
                        "type": "log",
                        "message": "حالت دمو: اعداد شبیه‌سازی‌شده‌اند و شبکه تغییر نمی‌کند.",
                    }
                )
            else:
                check_dependencies(require_ookla=False)
                vpn = ExpressVPN(
                    command_timeout=settings["commandTimeout"],
                    connection_timeout=settings["connectionTimeout"],
                )
                speedtest = BundledSpeedtest(timeout=settings["speedtestTimeout"])
            report = benchmark(
                locations,
                vpn,
                speedtest,
                ReportStore(output_path),
                count=settings["repeat"],
                serial=settings["serial"],
                disconnect_existing=settings["disconnect_existing"],
                demo=settings["demo"],
                display_unit=settings["display_unit"],
                latency_unit=settings["latency_unit"],
                log=lambda message: self._publish({"type": "log", "message": message}),
                progress=self._publish,
                report_callback=self._set_report,
                stop_event=stop_event,
            )
            status = report["Status"]
        except KeyboardInterrupt:
            status = "interrupted"
        except (CheckerError, ValueError) as exc:
            self._publish({"type": "run_failed", "message": str(exc)})
            status = "failed"
        except Exception as exc:
            self._publish(
                {
                    "type": "run_failed",
                    "message": f"Unexpected error: {exc.__class__.__name__}: {exc}",
                }
            )
            status = "failed"
        finally:
            self._publish(
                {
                    "type": "job_finished",
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "status": status,
                    "message": {
                        "completed": "تست با موفقیت تمام شد.",
                        "partial": "تست تمام شد، اما بخشی از اندازه‌گیری‌ها خطا داشت.",
                        "failed": "اجرای تست با خطا متوقف شد.",
                        "interrupted": "تست با درخواست شما متوقف شد.",
                    }.get(status, "اجرای تست پایان یافت."),
                }
            )

    def stop(self) -> bool:
        with self._lock:
            if not self._state["active"]:
                return False
            self._stop_event.set()
            self._state["status"] = "stopping"
            self._publish(
                {
                    "type": "stopping",
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "message": "درخواست توقف ثبت شد؛ تست جاری کامل و اتصال VPN ایمن قطع می‌شود.",
                }
            )
            return True

    def snapshot(self, after: int = 0) -> dict:
        with self._lock:
            events = [copy.deepcopy(event) for event in self._events if event["id"] > after]
            return {
                "job": copy.deepcopy(self._state),
                "events": events,
                "cursor": self._event_id,
                "reset": bool(self._events and after < self._events[0]["id"] - 1),
            }

    @property
    def output_path(self) -> Path | None:
        with self._lock:
            return self._output_path


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(JSON_AS_ASCII=False, MAX_CONTENT_LENGTH=32 * 1024)
    if config:
        app.config.update(config)
    manager = app.config.get("JOB_MANAGER") or JobManager(
        app.config.get("LOCATIONS_PATH", _project_locations_path()),
        app.config.get("OUTPUT_DIR", Path.cwd()),
    )
    app.extensions["speedchecker_job_manager"] = manager

    @app.get("/")
    def index():
        return render_template("index.html", version=__version__)

    @app.get("/api/config")
    def api_config():
        try:
            locations = [asdict(location) for location in load_locations(manager.locations_path)]
        except CheckerError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(
            {
                "version": __version__,
                "locations": locations,
                "speedUnits": [
                    {"value": value, **metadata} for value, metadata in SPEED_UNITS.items()
                ],
                "latencyUnits": [
                    {"value": value, **metadata} for value, metadata in LATENCY_UNITS.items()
                ],
                "speedtest": {
                    "bundled": True,
                    "version": "2.1.3",
                    "engine": "speedtest-cli (vendored Python engine)",
                },
                "expressVpnCliAvailable": bool(shutil.which("expressvpnctl")),
                "locationsFile": manager.locations_path.name,
            }
        )

    @app.get("/api/status")
    def api_status():
        try:
            after = int(request.args.get("after", "0"))
            if after < 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "after must be a non-negative event id"}), 400
        return jsonify(manager.snapshot(after))

    @app.post("/api/run")
    def api_run():
        payload = request.get_json(silent=True)
        try:
            job = manager.start(payload)
        except (CheckerError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job": job}), 202

    @app.post("/api/stop")
    def api_stop():
        if not manager.stop():
            return jsonify({"error": "No benchmark is currently running."}), 409
        return jsonify({"status": "stopping"}), 202

    @app.get("/api/report")
    def api_report():
        output_path = manager.output_path
        if output_path is None or not output_path.is_file():
            return jsonify({"error": "No saved report is available yet."}), 404
        return send_file(output_path, as_attachment=True, download_name=output_path.name)

    return app
