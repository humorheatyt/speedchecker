"""Tests for the v2 features: units, servers, engine, history, i18n, bundled binary."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from speedchecker.backends import bundled_speedtest_binary
from speedchecker.engine import DemoSpeedtestLive
from speedchecker.history import HistoryStore, filter_history
from speedchecker.i18n import is_rtl, tr
from speedchecker.models import CheckerError
from speedchecker.servers import (
    Server,
    demo_servers,
    group_servers,
    load_servers_file,
    ordered_servers,
    sort_servers,
)
from speedchecker.units import SPEED_UNITS, convert_speed, format_size, format_speed


class UnitTests(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(convert_speed(100, "Mbps"), 100)
        self.assertEqual(convert_speed(100, "MB/s"), 12.5)
        self.assertEqual(convert_speed(100, "Kbps"), 100_000)
        self.assertAlmostEqual(convert_speed(1000, "Gbps"), 1.0)
        self.assertEqual(format_speed(80, "MB/s"), "10.00 MB/s")
        self.assertEqual(format_size(1536), "1.50 KiB")
        self.assertEqual(format_size(2_000_000, "MB"), "2.00 MB")
        with self.assertRaises(ValueError):
            convert_speed(1, "furlongs/fortnight")

    def test_all_units_positive(self):
        for unit, factor in SPEED_UNITS.items():
            self.assertGreater(factor, 0, unit)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.servers = demo_servers()

    def test_demo_catalogue(self):
        self.assertGreaterEqual(len(self.servers), 5)
        self.assertTrue(all(s.host and s.country for s in self.servers))

    def test_sort_modes(self):
        shuffled = list(reversed(self.servers))
        self.assertEqual(sort_servers(shuffled, "file"), shuffled)
        by_country = sort_servers(shuffled, "country")
        self.assertEqual([s.country for s in by_country], sorted(s.country for s in self.servers))
        by_host = sort_servers(shuffled, "host")
        self.assertEqual([s.host for s in by_host], sorted(s.host for s in self.servers))
        randomised = sort_servers(shuffled, "random", seed=42)
        self.assertEqual(sorted(s.host for s in randomised), sorted(s.host for s in shuffled))
        self.assertNotEqual([s.host for s in randomised], [s.host for s in shuffled])
        with self.assertRaises(CheckerError):
            sort_servers(shuffled, "bogus")

    def test_selection_order_is_preserved(self):
        chosen = [self.servers[3], self.servers[0], self.servers[2]]
        self.assertEqual(ordered_servers([s.host for s in chosen], self.servers), chosen)
        self.assertEqual(
            ordered_servers(["missing", self.servers[1].host, self.servers[1].host], self.servers),
            [self.servers[1]],
        )
        self.assertEqual(ordered_servers([], self.servers), [])

    def test_grouping_like_expressvpn(self):
        groups = group_servers(self.servers, "country")
        self.assertEqual(sum(len(v) for v in groups.values()), len(self.servers))
        self.assertIn("Germany", groups)
        self.assertEqual(len(groups["Germany"]), 2)
        self.assertEqual(group_servers(self.servers, "none"), {"": self.servers})

    def test_base_url_and_locations_file(self):
        server = Server(host="h:8080", url="http://h:8080/speedtest/upload.php")
        self.assertEqual(server.base_url, "http://h:8080/speedtest/")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "locations.json"
            path.write_text(json.dumps({"locations": [{"country": "Canada", "city": "Toronto"}]}))
            loaded = load_servers_file(path)
            self.assertEqual(loaded[0].label, "Canada, Toronto")


class HistoryTests(unittest.TestCase):
    RECORDS = [
        {"status": "ok", "location": "Canada, Toronto", "download_mbps": 90, "latency_ms": 20},
        {
            "status": "error",
            "location": "Germany, Berlin",
            "error": "timeout",
            "download_mbps": None,
            "latency_ms": None,
        },
        {"status": "ok", "location": "Japan, Tokyo", "download_mbps": 10, "latency_ms": 200},
    ]

    def test_filters(self):
        self.assertEqual(len(filter_history(self.RECORDS, status="error")), 1)
        self.assertEqual(len(filter_history(self.RECORDS, status="ok")), 2)
        self.assertEqual(len(filter_history(self.RECORDS, min_download=50)), 1)
        self.assertEqual(len(filter_history(self.RECORDS, max_latency=100)), 1)
        self.assertEqual(len(filter_history(self.RECORDS, text="tokyo")), 1)
        with self.assertRaises(CheckerError):
            filter_history(self.RECORDS, status="bogus")

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = HistoryStore(Path(d) / "h.json")
            self.assertEqual(store.load(), [])
            store.append(self.RECORDS[0])
            self.assertEqual(store.load()[0]["location"], "Canada, Toronto")
            store.clear()
            self.assertEqual(store.load(), [])


class EngineTests(unittest.TestCase):
    def test_demo_engine_reports_live_progress(self):
        seen = []
        engine = DemoSpeedtestLive(
            demo_servers()[0], duration=0.5, progress=lambda p, m, b: seen.append((p, m))
        )
        result = engine.measure()
        self.assertGreater(result.download_mbps, 0)
        self.assertEqual({p for p, _ in seen}, {"latency", "download", "upload"})
        self.assertTrue(any(p == "latency" and m > 0 for p, m in seen))

    def test_demo_engine_cancellation(self):
        import threading

        cancel = threading.Event()
        cancel.set()
        engine = DemoSpeedtestLive(demo_servers()[0], duration=0.5, cancel=cancel)
        with self.assertRaises(CheckerError):
            engine.measure()

    def test_builtin_engine_against_local_speedtest_server(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from speedchecker.engine import BuiltinSpeedtest

        data = b"x" * 500_000

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = b"test" if "latency" in self.path else data
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                remaining = int(self.headers.get("Content-Length", 0))
                while remaining > 0:
                    remaining -= len(self.rfile.read(min(remaining, 65536)))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        server_http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server_http.serve_forever, daemon=True).start()
        self.addCleanup(server_http.shutdown)
        port = server_http.server_address[1]
        server = Server(
            city="Local",
            country="Testland",
            host=f"127.0.0.1:{port}",
            url=f"http://127.0.0.1:{port}/speedtest/upload.php",
        )
        progress = []
        result = BuiltinSpeedtest(
            server,
            timeout=5,
            duration=1,
            connections=2,
            progress=lambda phase, value, done: progress.append((phase, value, done)),
        ).measure()
        self.assertGreater(result.download_mbps, 0)
        self.assertGreater(result.upload_mbps, 0)
        self.assertGreater(result.latency_ms, 0)
        self.assertEqual(result.server_location, "Testland, Local")
        phases = {phase for phase, _, _ in progress}
        self.assertGreaterEqual(phases, {"latency", "download", "upload"})
        self.assertGreater(sum(phase == "upload" for phase, _, _ in progress), 1)

    def test_rejected_upload_shows_live_progress_but_is_not_counted_as_success(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from speedchecker.engine import BuiltinSpeedtest

        class RejectingHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                remaining = int(self.headers.get("Content-Length", 0))
                while remaining > 0:
                    remaining -= len(self.rfile.read(min(remaining, 65_536)))
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()

        http = ThreadingHTTPServer(("127.0.0.1", 0), RejectingHandler)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.shutdown)
        port = http.server_address[1]
        server = Server(
            host=f"127.0.0.1:{port}",
            url=f"http://127.0.0.1:{port}/upload.php",
        )
        progress = []
        engine = BuiltinSpeedtest(
            server,
            timeout=3,
            duration=1,
            connections=1,
            progress=lambda phase, value, done: progress.append((phase, value, done)),
        )
        with self.assertRaisesRegex(CheckerError, "Upload test transferred no data"):
            engine._transfer(server, "upload")
        self.assertTrue(any(phase == "upload" and done > 0 for phase, _, done in progress))

    def test_bundled_binary_prefers_vendor(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "vendor").mkdir()
            # On Windows the .exe candidate is preferred; on POSIX the plain name.
            binary = root / "vendor" / ("speedtest.exe" if os.name == "nt" else "speedtest")
            binary.write_text("#!/bin/sh\n")
            fake_file = root / "src" / "speedchecker" / "backends.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("")
            with patch("speedchecker.backends.__file__", str(fake_file)):
                found = bundled_speedtest_binary()
            self.assertIsNotNone(found)
            # Windows: TemporaryDirectory may use the 8.3 short name
            # (e.g. RUNNER~1) while resolve() returns the long name
            # (runneradmin) — compare resolved paths, not raw strings.
            self.assertEqual(found.resolve(), binary.resolve())


class I18nTests(unittest.TestCase):
    def test_both_languages_complete_and_rtl(self):
        from speedchecker.i18n import STRINGS

        self.assertEqual(set(STRINGS["en"]), set(STRINGS["fa"]))
        self.assertTrue(is_rtl("fa"))
        self.assertFalse(is_rtl("en"))
        self.assertNotEqual(tr("fa", "start_test"), tr("en", "start_test"))


if __name__ == "__main__":
    unittest.main()

class ExpressRegionTests(unittest.TestCase):
    def test_all_endpoints_keep_exact_region(self):
        from speedchecker.servers import express_region

        regions = ["germany-frankfurt-1", "germany-berlin", "united-states-new-york", "japan-tokyo"]
        servers = [express_region(region) for region in regions]
        self.assertEqual([s.host for s in servers], regions)
        self.assertEqual(len(group_servers(servers, "country")["Germany"]), 2)
        self.assertEqual(servers[2].country, "United States")
        self.assertTrue(all(s.id == "" and s.url == "" for s in servers))

    def test_download_unsupported_platform(self):
        from speedchecker.ookla_download import download_ookla

        with patch("speedchecker.ookla_download.platform.system", return_value="Unsupported"):
            with self.assertRaises(CheckerError):
                download_ookla()

    def test_download_extracts_only_executable(self):
        import io
        import tarfile

        from speedchecker.ookla_download import download_ookla

        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            payload = b"fake executable"
            member = tarfile.TarInfo("speedtest")
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "speedtest"
            class Response:
                """Stream once, then EOF — like a real HTTP response body."""

                def __init__(self):
                    self._sent = False

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    pass

                def read(self, _):
                    if self._sent:
                        return b""
                    self._sent = True
                    return archive.getvalue()

            seen = []
            with (
                patch("speedchecker.ookla_download.platform.system", return_value="Linux"),
                patch("speedchecker.ookla_download.platform.machine", return_value="x86_64"),
                patch(
                    "speedchecker.ookla_download.urllib.request.urlopen",
                    return_value=Response(),
                ),
            ):
                self.assertEqual(
                    download_ookla(
                        destination=target,
                        progress=lambda done, total: seen.append((done, total)),
                    ),
                    target,
                )
            self.assertEqual(target.read_bytes(), b"fake executable")
            self.assertEqual(seen[-1], (len(archive.getvalue()), 0))
