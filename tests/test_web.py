import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from speedchecker.models import CheckerError
from speedchecker.web import create_app

ROOT = Path(__file__).resolve().parents[1]


class WebDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output_dir = Path(self.temporary.name)
        self.app = create_app(
            {
                "TESTING": True,
                "LOCATIONS_PATH": ROOT / "locations.json",
                "OUTPUT_DIR": self.output_dir,
            }
        )
        self.client = self.app.test_client()
        self.manager = self.app.extensions["speedchecker_job_manager"]

    def wait_for_job(self, timeout=5):
        deadline = time.monotonic() + timeout
        snapshot = None
        while time.monotonic() < deadline:
            response = self.client.get("/api/status?after=0")
            snapshot = response.get_json()
            if not snapshot["job"]["active"]:
                return snapshot
            time.sleep(0.01)
        self.fail(f"Job did not finish in time: {snapshot}")

    def test_dashboard_and_config_serve_bundled_engine_and_units(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("سرعت واقعی شبکه‌تان", page.get_data(as_text=True))
        self.assertIn('id="demoMode" type="checkbox" checked', page.get_data(as_text=True))

        config = self.client.get("/api/config").get_json()
        self.assertTrue(config["speedtest"]["bundled"])
        self.assertEqual(config["speedtest"]["version"], "2.1.3")
        self.assertIn("MB/s", {item["value"] for item in config["speedUnits"]})
        self.assertIn("MiB/s", {item["value"] for item in config["speedUnits"]})
        self.assertIn("s", {item["value"] for item in config["latencyUnits"]})
        self.assertEqual(len(config["locations"]), 3)

    def test_demo_run_streams_live_events_saves_json_and_respects_preferences(self):
        response = self.client.post(
            "/api/run",
            json={
                "repeat": 2,
                "serial": True,
                "demo": True,
                "displayUnit": "MB/s",
                "latencyUnit": "s",
            },
        )
        self.assertEqual(response.status_code, 202)
        snapshot = self.wait_for_job()
        job = snapshot["job"]
        self.assertEqual(job["status"], "completed")
        self.assertFalse(job["active"])
        self.assertTrue(job["report"]["demo"])
        self.assertEqual(job["report"]["baseline"]["DownloadMbps"], 100.5)
        self.assertEqual(len(job["report"]["stats"]), 3)

        event_types = {event["type"] for event in snapshot["events"]}
        self.assertIn("sample", event_types)
        self.assertIn("baseline_complete", event_types)
        self.assertIn("location_complete", event_types)

        output = self.manager.output_path
        self.assertTrue(output.is_file())
        report_data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report_data["Settings"]["DisplayUnit"], "MB/s")
        self.assertEqual(report_data["Settings"]["LatencyUnit"], "s")
        downloaded = self.client.get("/api/report")
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("attachment", downloaded.headers["Content-Disposition"])
        downloaded.close()

    def test_invalid_options_and_stop_without_active_job(self):
        response = self.client.post("/api/run", json={"repeat": 33, "demo": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("1 to 32", response.get_json()["error"])
        self.assertEqual(self.client.post("/api/stop").status_code, 409)
        self.assertEqual(self.client.get("/api/report").status_code, 404)

    def test_real_run_reports_missing_vpn_tool_without_needing_speedtest_cli(self):
        with patch(
            "speedchecker.web.check_dependencies", side_effect=CheckerError("expressvpnctl missing")
        ):
            response = self.client.post("/api/run", json={"demo": False, "repeat": 1})
            self.assertEqual(response.status_code, 202)
            snapshot = self.wait_for_job()
        self.assertEqual(snapshot["job"]["status"], "failed")
        self.assertIn("expressvpnctl missing", snapshot["job"]["error"])


if __name__ == "__main__":
    unittest.main()
