import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from test_models import payload

from speedchecker.backends import (
    BundledSpeedtest,
    CommandRunner,
    ExpressVPN,
    OoklaSpeedtest,
    check_dependencies,
)
from speedchecker.models import CheckerError


class CommandTests(unittest.TestCase):
    def test_actual_subprocess(self):
        result = CommandRunner().run([sys.executable, "-c", "print('ok')"], 5)
        self.assertEqual(result.strip(), "ok")

    def test_nonzero_exit(self):
        with self.assertRaisesRegex(CheckerError, "code 3: broken"):
            CommandRunner().run(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('broken', file=sys.stderr); sys.exit(3)",
                ],
                5,
            )

    def test_timeout(self):
        with self.assertRaisesRegex(CheckerError, "timed out"):
            CommandRunner().run([sys.executable, "-c", "import time; time.sleep(10)"], 0.05)

    def test_missing_executable(self):
        with self.assertRaisesRegex(CheckerError, "Cannot run"):
            CommandRunner().run(["speedchecker-nonexistent-binary"], 1)

    @patch("speedchecker.backends.shutil.which", return_value=None)
    def test_dependencies(self, which):
        with self.assertRaisesRegex(CheckerError, "expressvpnctl, speedtest"):
            check_dependencies()

    @patch("speedchecker.backends.subprocess.run")
    def test_json_stdout_is_separate_from_stderr(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, payload(), "some warning")
        result = OoklaSpeedtest().measure()
        self.assertEqual(result.download_mbps, 100.5)
        self.assertNotIn("shell", run.call_args.kwargs)


class BundledSpeedtestTests(unittest.TestCase):
    def test_bundled_engine_converts_bits_per_second_and_preserves_server(self):
        class Results:
            def dict(self):
                return {
                    "download": 125_500_000,
                    "upload": 33_000_000,
                    "ping": 12.5,
                    "server": {
                        "url": "https://speed.example/test/upload.php",
                        "country": "Germany",
                        "name": "Frankfurt",
                    },
                }

        class Engine:
            results = Results()

            def get_best_server(self):
                return {"id": "123", "country": "Germany", "name": "Frankfurt"}

            def download(self):
                return 125_500_000

            def upload(self, pre_allocate=True):
                self.pre_allocate = pre_allocate
                return 33_000_000

        calls = []

        def factory(**kwargs):
            calls.append(kwargs)
            return Engine()

        measurement = BundledSpeedtest(timeout=45, speedtest_factory=factory).measure()
        self.assertEqual(measurement.download_mbps, 125.5)
        self.assertEqual(measurement.upload_mbps, 33.0)
        self.assertEqual(measurement.latency_ms, 12.5)
        self.assertEqual(measurement.server, "speed.example")
        self.assertEqual(measurement.server_location, "Germany, Frankfurt")
        self.assertEqual(calls, [{"timeout": 45, "secure": True}])

    def test_bundled_engine_reports_clear_network_errors(self):
        def fail(**kwargs):
            raise OSError("offline")

        with self.assertRaisesRegex(CheckerError, "Bundled Speedtest failed: offline"):
            BundledSpeedtest(speedtest_factory=fail).measure()

    @patch(
        "speedchecker.backends.shutil.which",
        side_effect=lambda name: None if name == "expressvpnctl" else "/usr/bin/speedtest",
    )
    def test_bundled_mode_does_not_require_separate_speedtest_cli(self, which):
        with self.assertRaisesRegex(CheckerError, "expressvpnctl"):
            check_dependencies(require_ookla=False)
        self.assertEqual([call.args[0] for call in which.call_args_list], ["expressvpnctl"])


class VPNTests(unittest.TestCase):
    def test_regions(self):
        runner = Mock()
        runner.run.return_value = "  canada \n\ncanada-toronto\n"
        self.assertEqual(ExpressVPN(runner).regions(), ["canada", "canada-toronto"])
        runner.run.assert_called_once_with(["expressvpnctl", "get", "regions"], 30)

    def test_empty_regions(self):
        runner = Mock()
        runner.run.return_value = "\n"
        with self.assertRaises(CheckerError):
            ExpressVPN(runner).regions()

    @patch("speedchecker.backends.time.sleep")
    def test_connection_polling(self, sleep):
        runner = Mock()
        runner.run.side_effect = ["", "Connecting", " Connected\n"]
        self.assertGreaterEqual(ExpressVPN(runner).connect("canada"), 0)
        self.assertEqual(
            runner.run.call_args_list[0].args[0], ["expressvpnctl", "connect", "canada"]
        )
        self.assertEqual(sleep.call_count, 1)

    def test_connection_timeout_is_bounded(self):
        runner = Mock()
        runner.run.return_value = "Connecting"
        with self.assertRaisesRegex(CheckerError, "within"):
            ExpressVPN(runner, connection_timeout=0.01).connect("canada")

    def test_disconnect_waits_for_state(self):
        runner = Mock()
        runner.run.side_effect = ["", "Disconnected"]
        ExpressVPN(runner).disconnect()
        self.assertEqual(
            runner.run.call_args_list[1].args[0], ["expressvpnctl", "get", "connectionstate"]
        )

    def test_ookla_license_is_opt_in(self):
        runner = Mock()
        runner.run.return_value = payload()
        OoklaSpeedtest(runner).measure()
        self.assertNotIn("--accept-license", runner.run.call_args.args[0])
        OoklaSpeedtest(runner, accept_license=True).measure()
        self.assertIn("--accept-license", runner.run.call_args.args[0])
        self.assertIn("--accept-gdpr", runner.run.call_args.args[0])
