import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from speedchecker.cli import main, parser

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_invalid_arguments(self):
        for args in [
            [],
            ["locations.json", "-r", "0"],
            ["locations.json", "-r", "-1"],
            ["locations.json", "--connection-timeout", "nan"],
            ["locations.json", "--speedtest-timeout", "inf"],
            ["locations.json", "--command-timeout", "0"],
        ]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    parser().parse_args(args)
                self.assertEqual(caught.exception.code, 2)

    def test_legacy_flags(self):
        args = parser().parse_args(["-s", "-r3", "locations.json"])
        self.assertEqual(args.repeat, 3)
        self.assertTrue(args.serial)
        args = parser().parse_args(["--repeatSpeedTest", "2", "locations.json"])
        self.assertEqual(args.repeat, 2)

    def test_demo_does_not_check_external_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("speedchecker.cli.check_dependencies") as check:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main([str(ROOT / "locations.json"), "--demo", "-o", str(path)])
            self.assertEqual(code, 0)
            check.assert_not_called()
            self.assertTrue(json.loads(path.read_text())["Demo"])

    def test_module_end_to_end_both_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            for serial in (True, False):
                path = Path(directory) / f"report-{serial}.json"
                cmd = [
                    sys.executable,
                    "-m",
                    "speedchecker",
                    str(ROOT / "locations.json"),
                    "--demo",
                    "-r",
                    "3",
                    "-o",
                    str(path),
                ] + (["-s"] if serial else [])
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(len(report["VPNStats"]), 3)
                self.assertEqual(report["Baseline"]["SuccessfulTests"], 3)
                # Existing results are not clobbered on a subsequent invocation.
                before = path.read_bytes()
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(path.read_bytes(), before)
