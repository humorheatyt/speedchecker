"""Exercise real subprocess orchestration with isolated fake CLI executables."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

VPN_SCRIPT = """
import os
import sys
from pathlib import Path
state = Path(os.environ["FAKE_VPN_STATE"])
args = sys.argv[1:]
if args == ["get", "regions"]:
    print("canada\\ncanada-toronto")
elif args == ["get", "connectionstate"]:
    print(state.read_text() if state.exists() else "Disconnected")
elif args == ["connect", "canada-toronto"]:
    state.write_text("Connected")
    if os.environ.get("FAKE_CONNECT_FAILURE"):
        sys.exit(1)
elif args == ["disconnect"]:
    state.write_text("Disconnected")
else:
    sys.exit(2)
"""

SPEED_SCRIPT = """
import json
import os
import sys
from pathlib import Path
assert "--format=json" in sys.argv
assert "--progress=no" in sys.argv
assert "--accept-license" in sys.argv
assert "--accept-gdpr" in sys.argv
path = Path(os.environ["FAKE_VPN_STATE"])
connected = path.exists() and path.read_text() == "Connected"
print("Diagnostic on stderr, not part of JSON", file=sys.stderr)
print(json.dumps({
    "download": {"bandwidth": 10031250 if connected else 12562500},
    "upload": {"bandwidth": 3812500 if connected else 5093750},
    "ping": {"latency": 25 if connected else 10},
    "server": {"host": "fake.invalid", "country": "Canada", "location": "Toronto"}
}))
"""


@unittest.skipIf(os.name == "nt", "Fake executable scripts use POSIX shebangs")
class SubprocessIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {
            **os.environ,
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "FAKE_VPN_STATE": str(self.root / "state"),
        }
        for name, source in [("expressvpnctl", VPN_SCRIPT), ("speedtest", SPEED_SCRIPT)]:
            executable = self.root / name
            executable.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
            executable.chmod(0o755)
        self.input = self.root / "locations.json"
        self.input.write_text(json.dumps({"locations": [{"country": "Canada", "city": "Toronto"}]}))

    def invoke(self, serial=False):
        output = self.root / f"report-{serial}.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "vpnchecker",
                str(self.input),
                "--accept-license",
                "-r",
                "3",
                "--output",
                str(output),
            ]
            + (["-s"] if serial else []),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result, json.loads(output.read_text(encoding="utf-8"))

    def test_real_command_path_in_serial_and_parallel_modes(self):
        for serial in (True, False):
            with self.subTest(serial=serial):
                result, report = self.invoke(serial)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(report["Demo"])
                self.assertEqual(report["Status"], "completed")
                self.assertEqual(report["Baseline"]["DownloadMbps"], 100.5)
                self.assertEqual(report["VPNStats"][0]["DownloadMbps"], 80.25)
                self.assertEqual(report["VPNStats"][0]["SuccessfulTests"], 3)
                self.assertEqual((self.root / "state").read_text(), "Disconnected")

    def test_failed_connect_command_cleans_up_actual_subprocess_state(self):
        self.env["FAKE_CONNECT_FAILURE"] = "1"
        result, report = self.invoke()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(report["Status"], "partial")
        self.assertEqual(report["VPNStats"], [])
        self.assertEqual((self.root / "state").read_text(), "Disconnected")
