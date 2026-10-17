import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from vpnchecker.backends import DemoSpeedtest, DemoVPN
from vpnchecker.desktop import SPEED_UNITS, History, Session, Settings, ordered
from vpnchecker.models import CheckerError


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.history = History(Path(self.tmp.name) / "nested" / "history.db")
        self.stop = threading.Event()
        self.events = []
        self.vpn = DemoVPN(["b", "a"])

    def session(self, settings=None, factory=None, vpn=None):
        return Session(
            vpn or self.vpn,
            settings or Settings(baseline=False),
            self.history,
            self.events.append,
            self.stop,
            factory or (lambda: DemoSpeedtest(self.vpn)),
        )

    def test_units_and_order(self):
        self.assertEqual(80e6 / SPEED_UNITS["MB/s"], 10)
        self.assertEqual(80e6 / SPEED_UNITS["KB/s"], 10000)
        self.assertEqual(ordered(["b", "a", "b"], "Alphabetical"), ["a", "b"])
        self.assertEqual(ordered(["b", "a"], "Provider order"), ["b", "a"])
        self.assertCountEqual(ordered(["b", "a"], "Random"), ["a", "b"])

    def test_serial_and_baseline_history(self):
        self.session(Settings(repeat=2, baseline=True)).run(["a", "b"])
        rows = self.history.rows()
        self.assertEqual(len(rows), 6)
        self.assertEqual({r["status"] for r in rows}, {"success"})
        self.assertEqual(sum(r["region"] == "Baseline (no VPN)" for r in rows), 2)
        self.assertFalse(self.vpn.connected)
        self.assertEqual(len(History(self.history.path).rows()), 6)

    def test_parallelism_is_bounded(self):
        lock = threading.Lock()
        active, peak = 0, 0

        class Meter:
            def measure(inner):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.025)
                with lock:
                    active -= 1
                return DemoSpeedtest(self.vpn).measure()

        self.session(Settings(repeat=7, workers=3, baseline=False), Meter).run(["a"])
        self.assertEqual(peak, 3)
        self.assertEqual(len(self.history.rows()), 7)

    def test_failed_measurements_are_durable(self):
        class Meter:
            def measure(self):
                raise CheckerError("network failed")

        self.session(factory=Meter).run(["a"])
        self.assertEqual(self.history.rows()[0]["status"], "error")
        self.assertIn("network failed", self.history.rows()[0]["error"])
        self.assertFalse(self.vpn.connected)

    def test_connect_failure_still_disconnects(self):
        with patch.object(self.vpn, "connect", side_effect=CheckerError("connect failed")):
            with patch.object(self.vpn, "disconnect", wraps=self.vpn.disconnect) as disconnect:
                self.session().run(["a"])
                disconnect.assert_called_once()
        self.assertEqual(self.history.rows()[0]["attempt"], 0)

    def test_cleanup_failure_aborts_next_location(self):
        with patch.object(self.vpn, "disconnect", side_effect=CheckerError("cleanup failed")):
            with self.assertRaisesRegex(CheckerError, "cleanup failed"):
                self.session().run(["a", "b"])
        self.assertEqual(len(self.history.rows()), 1)

    def test_existing_connection_needs_consent(self):
        self.vpn.connected = True
        with self.assertRaisesRegex(CheckerError, "already active"):
            self.session().run(["a"])
        self.assertTrue(self.vpn.connected)
        self.assertEqual(self.history.rows(), [])

    def test_existing_connection_with_consent(self):
        self.vpn.connected = True
        self.session(Settings(baseline=False, disconnect_existing=True)).run(["a"])
        self.assertFalse(self.vpn.connected)

    def test_cancel_prevents_remaining_locations(self):
        def meter():
            self.stop.set()
            return DemoSpeedtest(self.vpn)

        self.session(Settings(repeat=50, baseline=False), meter).run(["a", "b"])
        self.assertEqual(len(self.history.rows()), 1)
        self.assertFalse(self.vpn.connected)

    def test_stop_before_start_creates_no_attempts(self):
        self.stop.set()
        self.session().run(["a"])
        self.assertEqual(self.history.rows(), [])


class LoggedRunnerTests(unittest.TestCase):
    def test_streams_stdout_and_stderr_separately(self):
        import sys

        from vpnchecker.desktop import LoggedRunner

        events = []
        result = LoggedRunner(events.append, threading.Event()).run(
            [sys.executable, "-c", "import sys; print('alias'); print('note', file=sys.stderr)"], 3
        )
        self.assertEqual(result.strip(), "alias")
        self.assertTrue(any("stderr: note" in e["text"] for e in events))

    def test_timeout(self):
        import sys

        from vpnchecker.desktop import LoggedRunner

        with self.assertRaisesRegex(CheckerError, "timed out"):
            LoggedRunner(lambda e: None, threading.Event()).run(
                [sys.executable, "-c", "import time; time.sleep(30)"], 0.1
            )

    def test_cancel_before_command(self):
        from vpnchecker.desktop import LoggedRunner

        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(CheckerError, "Cancelled"):
            LoggedRunner(lambda e: None, stop).run(["missing", "connect"], 1)

    def test_missing_executable_is_actionable(self):
        from vpnchecker.desktop import LoggedRunner

        with self.assertRaisesRegex(CheckerError, "Cannot run"):
            LoggedRunner(lambda e: None, threading.Event()).run(["nonexistent-speedchecker-123"], 1)
