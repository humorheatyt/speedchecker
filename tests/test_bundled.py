import json
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from vpnchecker.bundled import BundledSpeedtest
from vpnchecker.models import CheckerError

REAL_POPEN = subprocess.Popen


class BundledTests(unittest.TestCase):
    def run_script(self, source, meter=None):
        def launch(args, **kwargs):
            return REAL_POPEN([sys.executable, "-u", "-c", source], **kwargs)

        with patch("vpnchecker.bundled.subprocess.Popen", side_effect=launch):
            return (meter or BundledSpeedtest()).measure()

    def test_result_progress_and_diagnostics(self):
        events = []
        payload = {
            "type": "result",
            "result": {
                "download": 80e6,
                "upload": 24e6,
                "ping": 15.5,
                "server": {"host": "test.invalid", "name": "Test"},
            },
        }
        source = "print('diagnostic')\nprint(" + repr(json.dumps(payload)) + ")"
        result = self.run_script(source, BundledSpeedtest(event=events.append))
        self.assertEqual(result.download_mbps, 80)
        self.assertEqual(result.upload_mbps, 24)
        self.assertTrue(any(e.get("text") == "diagnostic" for e in events))

    def test_whole_test_deadline_kills_process(self):
        with self.assertRaisesRegex(CheckerError, "timed out"):
            self.run_script("import time; time.sleep(30)", BundledSpeedtest(timeout=0.15))

    def test_cancel_kills_process(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(CheckerError, "Cancelled"):
            self.run_script("import time; time.sleep(30)", BundledSpeedtest(stop=stop))

    def test_remote_error(self):
        with self.assertRaisesRegex(CheckerError, "unavailable"):
            self.run_script('print(\'{"type":"error","text":"unavailable"}\')')

    def test_empty_exit(self):
        with self.assertRaisesRegex(CheckerError, "without a valid result"):
            self.run_script("pass")
