import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from test_models import payload

from vpnchecker.backends import CommandRunner, ExpressVPN, OoklaSpeedtest, check_dependencies
from vpnchecker.models import CheckerError


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
            CommandRunner().run(["vpnchecker-nonexistent-binary"], 1)

    @patch("vpnchecker.backends.shutil.which", return_value=None)
    def test_dependencies(self, which):
        with self.assertRaisesRegex(CheckerError, "expressvpnctl, speedtest"):
            check_dependencies()

    @patch("vpnchecker.backends.subprocess.run")
    def test_json_stdout_is_separate_from_stderr(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, payload(), "some warning")
        result = OoklaSpeedtest().measure()
        self.assertEqual(result.download_mbps, 100.5)
        self.assertNotIn("shell", run.call_args.kwargs)


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

    @patch("vpnchecker.backends.time.sleep")
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
