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

    def test_gauge_value_and_scale(self):
        gauge = GaugeWidget("Download")
        gauge.set_value(250)
        self.assertGreaterEqual(gauge._max, 250)


if __name__ == "__main__":
    unittest.main()
