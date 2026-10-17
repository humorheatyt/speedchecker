import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from test_models import payload

from speedchecker.backends import (
    CommandRunner,
    ExpressVPN,
    FallbackSpeedtest,
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
        # speedtest binary is optional now (built-in engine is bundled);
        # it is only required when explicitly requested.
        with self.assertRaisesRegex(CheckerError, "expressvpnctl"):
            check_dependencies()
        with self.assertRaisesRegex(CheckerError, r"expressvpnctl, speedtest \(vendor/ or PATH\)"):
            check_dependencies(require_speedtest_binary=True)

    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    @patch("speedchecker.backends.subprocess.run")
    def test_json_stdout_is_separate_from_stderr(self, run, _binary):
        run.return_value = subprocess.CompletedProcess([], 0, payload(), "some warning")
        result = OoklaSpeedtest().measure()
        self.assertEqual(result.download_mbps, 100.5)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_json_error_from_process_is_unwrapped(self):
        script = (
            "import sys; "
            "print('{\"error\":\"Cannot write: \"}', file=sys.stderr); "
            "sys.exit(2)"
        )
        with self.assertRaisesRegex(CheckerError, r"code 2: Cannot write$"):
            CommandRunner().run([sys.executable, "-c", script], 5)


class OoklaRecoveryTests(unittest.TestCase):
    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    def test_transient_cannot_write_is_retried_once(self, _binary):
        runner = Mock()
        runner.run.side_effect = [
            CheckerError("speedtest exited with code 2: Cannot write"),
            payload(),
        ]
        logs = []
        result = OoklaSpeedtest(
            runner, attempts=2, retry_delay=0, log=logs.append
        ).measure()
        self.assertEqual(result.download_mbps, 100.5)
        self.assertEqual(runner.run.call_count, 2)
        self.assertTrue(any("retrying" in line for line in logs))

    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    def test_protocol_hello_error_is_retried(self, _binary):
        runner = Mock()
        runner.run.side_effect = [
            CheckerError(
                "speedtest exited with code 2: Protocol error: Did not receive HELLO; input: secret"
            ),
            payload(),
        ]
        result = OoklaSpeedtest(runner, attempts=2, retry_delay=0).measure()
        self.assertEqual(result.download_mbps, 100.5)
        self.assertEqual(runner.run.call_count, 2)

    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    def test_persistent_failure_has_an_actionable_hint(self, _binary):
        runner = Mock()
        runner.run.side_effect = CheckerError("speedtest exited with code 2: Cannot write")
        with self.assertRaisesRegex(CheckerError, "Hint: .*firewall"):
            OoklaSpeedtest(runner, attempts=2, retry_delay=0).measure()
        self.assertEqual(runner.run.call_count, 2)

    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    def test_permanent_error_is_not_retried(self, _binary):
        runner = Mock()
        runner.run.side_effect = CheckerError("speedtest exited with code 2: License not accepted")
        with self.assertRaisesRegex(CheckerError, "License not accepted"):
            OoklaSpeedtest(runner, attempts=3, retry_delay=0).measure()
        self.assertEqual(runner.run.call_count, 1)

    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    def test_configuration_5xx_is_retried(self, _binary):
        runner = Mock()
        runner.run.side_effect = [
            CheckerError("Cannot retrieve configuration document (503)"),
            payload(),
        ]
        OoklaSpeedtest(runner, attempts=2, retry_delay=0).measure()
        self.assertEqual(runner.run.call_count, 2)

    def test_auto_fallback_switches_permanently(self):
        from speedchecker.models import Measurement

        primary = Mock()
        primary.measure.side_effect = CheckerError("speedtest exited with code 2: Cannot write")
        fallback = Mock()
        fallback.measure.return_value = Measurement(1.0, 2.0, 3.0, "h", "l")
        logs, switched = [], []
        engine = FallbackSpeedtest(
            primary,
            lambda: fallback,
            log=logs.append,
            on_fallback=lambda: switched.append(True),
            primary_name="Ookla",
            fallback_name="built-in",
        )
        self.assertIs(engine.measure(), fallback.measure.return_value)
        self.assertIs(engine.measure(), fallback.measure.return_value)
        self.assertEqual(primary.measure.call_count, 1)
        self.assertEqual(fallback.measure.call_count, 2)
        self.assertEqual(switched, [True])
        self.assertTrue(logs and "built-in" in logs[0])


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

    @patch("speedchecker.backends.bundled_speedtest_binary", return_value="speedtest")
    def test_ookla_license_is_opt_in(self, _binary):
        runner = Mock()
        runner.run.return_value = payload()
        OoklaSpeedtest(runner).measure()
        self.assertNotIn("--accept-license", runner.run.call_args.args[0])
        OoklaSpeedtest(runner, accept_license=True).measure()
        self.assertIn("--accept-license", runner.run.call_args.args[0])
        self.assertIn("--accept-gdpr", runner.run.call_args.args[0])
