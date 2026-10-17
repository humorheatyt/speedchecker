"""Headless GUI smoke test (skipped when Qt system libraries are absent)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication

    from speedchecker.gui import MainWindow
    from speedchecker.widgets import GaugeWidget

    QT_AVAILABLE = True
except Exception:  # ImportError/OSError when libGL etc. are missing
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PyQt6 / Qt system libraries not available")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication([])

    def test_window_bilingual_demo_flow(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from speedchecker.history import HistoryStore

        window = MainWindow()
        with (
            tempfile.TemporaryDirectory() as d,
            patch.object(window, "history", HistoryStore(Path(d) / "history.json")),
        ):
            window.combo_lang.setCurrentText("fa")
            self.assertIn("خانه", [window.tabs.tabText(i) for i in range(window.tabs.count())])
            window.combo_lang.setCurrentText("en")
            window.combo_unit.setCurrentText("MB/s")
            self.assertEqual(window.gauge_down._unit, "MB/s")
            demo_index = window.combo_backend.findData("demo")
            window.combo_backend.setCurrentIndex(demo_index)
            self.assertEqual(window._backend(), "demo")
            window.spin_duration.setValue(1)
            window.start_tests(batch=True)
            self.app.processEvents()
            window.worker.wait(60_000)
            self.app.processEvents()
            records = window.history.load()
            self.assertTrue(records)
            self.assertTrue(all(r["status"] == "ok" for r in records))

    def test_baseline_group_selection_and_numeric_sort(self):
        import tempfile
        from pathlib import Path

        from speedchecker.history import HistoryStore
        from speedchecker.servers import demo_servers

        window = MainWindow()
        window.history = HistoryStore(Path(tempfile.mkdtemp()) / "history.json")
        window.combo_backend.setCurrentIndex(window.combo_backend.findData("demo"))
        window.spin_duration.setValue(1)
        window.chk_baseline.setChecked(True)
        window.servers = demo_servers()
        window.refresh_server_tree()
        parent = next(window.tree.topLevelItem(i) for i in range(window.tree.topLevelItemCount())
                      if window.tree.topLevelItem(i).text(0) == "Germany")
        parent.setSelected(True)
        self.assertEqual(len(window._selected_servers()), 2)
        window.start_tests(batch=False)
        window.worker.wait(60_000)
        self.app.processEvents()
        records = window.history.load()
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["connection"], "direct")
        self.assertEqual(records[0]["repeat"], 1)
        self.assertTrue(all(r["connection"] == "vpn" for r in records[1:]))
        self.assertEqual(window.history_table.rowCount(), 3)
        window.history_table.sortItems(3)
        self.assertLessEqual(window.history_table.item(0, 3).data(0x0100),
                             window.history_table.item(1, 3).data(0x0100))

    def test_fetch_uses_every_express_region_not_nearby_speedtest_servers(self):
        from unittest.mock import patch

        from speedchecker.gui import TestWorker
        from speedchecker.servers import Server

        window = MainWindow()
        regions = ["germany-frankfurt-1", "germany-berlin", "japan-tokyo"]
        received = []
        worker = TestWorker("fetch", window._payload([]))
        worker.fetched.connect(received.append)
        with patch("speedchecker.gui.ExpressVPN") as vpn, patch(
            "speedchecker.gui.fetch_servers", create=True
        ) as speedtest_servers:
            vpn.return_value.regions.return_value = regions
            worker.run()
            self.assertFalse(speedtest_servers.called)
        self.assertEqual([Server.from_dict(s).host for s in received[0]], regions)

    def test_vpn_region_does_not_become_ookla_server_id(self):
        from speedchecker.gui import TestWorker
        from speedchecker.servers import express_region

        window = MainWindow()
        window.combo_backend.setCurrentIndex(window.combo_backend.findData("ookla"))
        worker = TestWorker("single", window._payload([express_region("germany-berlin")]))
        engine = worker._engine(None)
        self.assertEqual(engine.server_id, "")

    def test_group_selection_order_and_rebuilds(self):
        from PyQt6.QtCore import Qt

        from speedchecker.servers import demo_servers

        window = MainWindow()
        window.servers = demo_servers()
        window.refresh_server_tree()

        def item_for(host):
            for index in range(window.tree.topLevelItemCount()):
                group = window.tree.topLevelItem(index)
                for child_index in range(group.childCount()):
                    child = group.child(child_index)
                    if child.data(0, Qt.ItemDataRole.UserRole) == host:
                        return child
            raise AssertionError(host)

        germany = next(
            window.tree.topLevelItem(i)
            for i in range(window.tree.topLevelItemCount())
            if window.tree.topLevelItem(i).text(0) == "Germany"
        )
        # Selecting a group selects every endpoint inside it.
        germany.setSelected(True)
        cities = [s.city for s in window._selected_servers()]
        self.assertEqual(sorted(cities), ["Berlin", "Frankfurt"])
        # Deselecting the group deselects the endpoints again.
        germany.setSelected(False)
        self.assertEqual(window._selected_servers(), [])

        # Endpoints are tested in the order they were selected, not list order.
        frankfurt = item_for("fra.speed.invalid:8080")
        berlin = item_for("ber.speed.invalid:8080")
        frankfurt.setSelected(True)
        berlin.setSelected(True)
        self.assertEqual([s.city for s in window._selected_servers()], ["Frankfurt", "Berlin"])

        # Re-sorting / re-grouping keeps both the selection and its order.
        window.combo_sort.setCurrentText("name")
        self.assertEqual([s.city for s in window._selected_servers()], ["Frankfurt", "Berlin"])

        # A search hides one endpoint but does not forget it, or its position.
        window.search.setText("Berlin")
        self.assertEqual([s.city for s in window._selected_servers()], ["Berlin"])
        window.search.clear()
        self.assertEqual([s.city for s in window._selected_servers()], ["Frankfurt", "Berlin"])

    def test_auto_engine_falls_back_and_remembers(self):
        from unittest.mock import Mock, patch

        from speedchecker.gui import TestWorker
        from speedchecker.models import CheckerError, Measurement

        window = MainWindow()
        worker = TestWorker("single", window._payload([]))
        worker.payload["backend"] = "auto"
        ookla, builtin = Mock(), Mock()
        ookla.measure.side_effect = CheckerError("speedtest exited with code 2: Cannot write")
        builtin.measure.return_value = Measurement(1.0, 2.0, 3.0, "h", "l")
        with (
            patch("speedchecker.gui.bundled_speedtest_binary", return_value="speedtest"),
            patch("speedchecker.gui.OoklaSpeedtest", return_value=ookla),
            patch.object(worker, "_builtin_engine", return_value=builtin),
        ):
            engine = worker._engine(None)
            self.assertEqual(engine.measure().download_mbps, 1.0)
            self.assertTrue(worker._prefer_builtin)
            # Later servers in the same run go straight to the built-in engine.
            self.assertIs(worker._engine(None), builtin)
            self.assertEqual(ookla.measure.call_count, 1)

    def test_download_reports_progress_and_result(self):
        from unittest.mock import patch

        from speedchecker.gui import TestWorker

        window = MainWindow()
        worker = TestWorker("download", window._payload([]))
        seen, done, failed = [], [], []
        worker.download_progress.connect(lambda d, t: seen.append((d, t)))
        worker.downloaded.connect(done.append)
        worker.failed.connect(failed.append)

        def fake_download(log=lambda message: None, *, destination=None, progress=None):
            progress(10, 20)
            progress(20, 20)
            return "/tmp/fake-speedtest"

        with patch("speedchecker.gui.download_ookla", side_effect=fake_download):
            worker.run()
        self.assertEqual(seen, [(10, 20), (20, 20)])
        self.assertEqual(done, ["/tmp/fake-speedtest"])
        self.assertEqual(failed, [])

    def test_download_failure_is_reported(self):
        from unittest.mock import patch

        from speedchecker.gui import TestWorker
        from speedchecker.models import CheckerError

        window = MainWindow()
        worker = TestWorker("download", window._payload([]))
        failed = []
        worker.failed.connect(failed.append)
        with patch("speedchecker.gui.download_ookla", side_effect=CheckerError("boom")):
            worker.run()
        self.assertEqual(failed, ["boom"])

    def test_gauge_value_and_scale(self):
        gauge = GaugeWidget("Download")
        gauge.set_value(250)
        self.assertGreaterEqual(gauge._max, 250)


if __name__ == "__main__":
    unittest.main()
