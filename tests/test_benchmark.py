import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from vpnchecker.backends import DemoSpeedtest, DemoVPN
from vpnchecker.benchmark import benchmark, run_batch
from vpnchecker.models import CheckerError, Location, Measurement
from vpnchecker.storage import ReportStore

SAMPLE = Measurement(100.5, 40.75, 10.25, "demo.invalid", "Test")


class BatchTests(unittest.TestCase):
    def test_serial_and_parallel_count(self):
        for serial in (True, False):
            with self.subTest(serial=serial):
                speedtest = Mock()
                speedtest.measure.return_value = SAMPLE
                batch = run_batch(speedtest, 5, serial)
                self.assertEqual(batch.samples, [SAMPLE] * 5)
                self.assertEqual(speedtest.measure.call_count, 5)

    def test_parallel_workers_overlap(self):
        barrier = threading.Barrier(3)
        speedtest = Mock()

        def measure():
            barrier.wait(timeout=5)
            return SAMPLE

        speedtest.measure.side_effect = measure
        self.assertEqual(len(run_batch(speedtest, 3, False).samples), 3)

    def test_partial_failure_continues(self):
        for serial in (True, False):
            speedtest = Mock()
            speedtest.measure.side_effect = [CheckerError("failed"), SAMPLE, SAMPLE]
            batch = run_batch(speedtest, 3, serial)
            self.assertEqual(batch.summary()["SuccessfulTests"], 2)
            self.assertEqual(batch.errors, ["failed"])

    def test_zero_repeats(self):
        with self.assertRaises(CheckerError):
            run_batch(Mock(), 0, True)


class StorageTests(unittest.TestCase):
    def test_atomic_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "report.json"
            store = ReportStore(path)
            store.reserve()
            report = {"WithoutVPN": "100Mbps ▼", "VPNStats": []}
            store.save(report)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)
            with self.assertRaises(CheckerError):
                store.reserve()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)

    def test_failed_replace_keeps_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            store = ReportStore(path)
            store.reserve()
            store.save({"old": True})
            with patch("vpnchecker.storage.os.replace", side_effect=OSError("denied")):
                with self.assertRaises(CheckerError):
                    store.save({"new": True})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(directory).iterdir()), [path])


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "report.json"
        self.store = ReportStore(self.path)
        self.vpn = Mock()
        self.vpn.regions.return_value = ["canada", "canada-toronto"]
        self.vpn.state.return_value = "disconnected"
        self.vpn.connect.return_value = 0.125
        self.speed = Mock()
        self.speed.measure.return_value = SAMPLE

    def run_benchmark(self, **kwargs):
        return benchmark(
            [Location("Canada", "Toronto")],
            self.vpn,
            self.speed,
            self.store,
            count=2,
            serial=True,
            log=lambda _: None,
            **kwargs,
        )

    def report(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_success(self):
        report = self.run_benchmark()
        self.assertEqual(report["Status"], "completed")
        self.assertEqual(report["Baseline"]["SuccessfulTests"], 2)
        self.assertEqual(report["WithoutVPN"], "100.50Mbps ▼  40.75Mbps ▲")
        self.assertEqual(report["VPNStats"][0]["VPNLatency"], "10.25ms")
        self.assertEqual(report["VPNStats"][0]["LocationName"], "Canada, Toronto")
        self.vpn.connect.assert_called_once_with("canada-toronto")
        self.vpn.disconnect.assert_called_once()
        self.assertEqual(self.report(), report)

    def test_existing_connection_untouched_without_consent(self):
        self.vpn.state.return_value = "connected"
        with self.assertRaisesRegex(CheckerError, "--disconnect-existing"):
            self.run_benchmark()
        self.vpn.disconnect.assert_not_called()
        self.speed.measure.assert_not_called()
        self.assertEqual(self.report()["Status"], "failed")

    def test_existing_connection_disconnects_before_baseline(self):
        self.vpn.state.return_value = "connected"
        events = []
        self.vpn.disconnect.side_effect = lambda: events.append("disconnect")
        self.speed.measure.side_effect = lambda: (events.append("test"), SAMPLE)[1]
        self.run_benchmark(disconnect_existing=True)
        self.assertEqual(events[0], "disconnect")
        self.assertEqual(self.vpn.disconnect.call_count, 2)

    def test_unknown_region_retains_baseline(self):
        self.vpn.regions.return_value = ["germany"]
        report = self.run_benchmark()
        self.assertEqual(report["Status"], "partial")
        self.assertIsNotNone(report["Baseline"])
        self.assertEqual(report["VPNStats"], [])
        self.vpn.connect.assert_not_called()

    def test_failed_connect_still_disconnects(self):
        self.vpn.connect.side_effect = CheckerError("connect failed")
        report = self.run_benchmark()
        self.vpn.disconnect.assert_called_once()
        self.assertEqual(report["Status"], "partial")

    def test_failed_speed_tests_still_disconnect(self):
        self.speed.measure.side_effect = [SAMPLE, SAMPLE, CheckerError("x"), CheckerError("y")]
        report = self.run_benchmark()
        self.vpn.disconnect.assert_called_once()
        self.assertEqual(report["Status"], "partial")
        self.assertEqual(report["VPNStats"], [])

    def test_partial_baseline_is_reported(self):
        self.speed.measure.side_effect = [CheckerError("failed"), SAMPLE, SAMPLE, SAMPLE]
        report = self.run_benchmark()
        self.assertEqual(report["Status"], "partial")
        self.assertEqual(report["Baseline"]["FailedTests"], 1)

    def test_baseline_failure_stops_before_connect(self):
        self.speed.measure.side_effect = CheckerError("speedtest failed")
        with self.assertRaises(CheckerError):
            self.run_benchmark()
        self.vpn.connect.assert_not_called()
        self.assertEqual(self.report()["Status"], "failed")

    def test_disconnect_failure_aborts_run_but_saves_measurements(self):
        self.vpn.disconnect.side_effect = CheckerError("disconnect failed")
        with self.assertRaisesRegex(CheckerError, "disconnect failed"):
            self.run_benchmark()
        report = self.report()
        self.assertEqual(report["Status"], "failed")
        self.assertEqual(len(report["VPNStats"]), 1)

    def test_keyboard_interrupt_cleans_up_and_saves(self):
        self.speed.measure.side_effect = [SAMPLE, SAMPLE, KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.run_benchmark()
        self.vpn.disconnect.assert_called_once()
        report = self.report()
        self.assertEqual(report["Status"], "interrupted")
        self.assertIsNotNone(report["Baseline"])

    def test_demo_is_marked_synthetic(self):
        vpn = DemoVPN(["canada"])
        report = benchmark(
            [Location("Canada")],
            vpn,
            DemoSpeedtest(vpn),
            self.store,
            count=3,
            demo=True,
            log=lambda _: None,
        )
        self.assertTrue(report["Demo"])
        self.assertEqual(report["Baseline"]["DownloadMbps"], 100.5)
        self.assertEqual(report["VPNStats"][0]["DownloadMbps"], 80.25)
        self.assertFalse(vpn.connected)
