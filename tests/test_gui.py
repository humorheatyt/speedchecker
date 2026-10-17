"""Qt integration: actual widgets/signals in offscreen mode, no network."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    from vpnchecker.gui import Window

    QT_ERROR = ""
except ImportError as exc:
    QT_ERROR = str(exc)


@unittest.skipIf(bool(QT_ERROR), "Qt native runtime unavailable: " + QT_ERROR)
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, self.temp.name)
        self.home = patch("pathlib.Path.home", return_value=Path(self.temp.name))
        self.home.start()
        self.addCleanup(self.home.stop)
        self.settings_patch = patch(
            "vpnchecker.gui.QSettings",
            side_effect=lambda *args: QSettings(
                str(Path(self.temp.name) / "prefs.ini"), QSettings.Format.IniFormat
            ),
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.dialogs = patch("vpnchecker.gui.QMessageBox.warning")
        self.dialogs.start()
        self.addCleanup(self.dialogs.stop)
        self.window = Window()
        self.addCleanup(self.cleanup_window)
        self.window.demo.setChecked(True)
        self.window.show()
        self.app.processEvents()

    def cleanup_window(self):
        if self.window.task and self.window.task.isRunning():
            self.window.cancel()
            self.wait_task()
        self.window.close()

    def wait_task(self):
        deadline = time.monotonic() + 15
        while self.window.task.isRunning() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.window.task.isRunning())
        self.app.processEvents()

    def load(self):
        self.window.load_regions()
        self.wait_task()
        self.assertEqual(len(self.window.regions), 8)

    def test_load_search_and_group(self):
        self.load()
        self.window.search.setText("germany")
        self.assertEqual(len(list(self.window.leaves())), 2)
        self.window.group.setChecked(False)
        self.assertEqual(self.window.tree.topLevelItemCount(), 2)

    def test_full_demo_workflow_and_history_units(self):
        self.load()
        self.window.baseline.setChecked(False)
        self.window.search.setText("japan")
        self.window.check_visible(True)
        self.window.start()
        self.wait_task()
        self.assertEqual(len(self.window.history.rows()), 1)
        self.assertEqual(self.window.table.rowCount(), 1)
        self.window.speed_unit.setCurrentText("MB/s")
        self.assertAlmostEqual(self.window.table.item(0, 4).data(0), 10.031, places=3)
        self.assertGreater(len(self.window.chart.points), 0)
        self.assertTrue(self.window.log_path.exists())
        self.window.history_status.setCurrentText("error")
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertFalse(self.window.stop_button.isEnabled())

    def test_cancel_demo_disconnects(self):
        self.load()
        self.window.repeat.setValue(100)
        self.window.baseline.setChecked(False)
        self.window.check_visible(True)
        self.window.start()
        time.sleep(0.05)
        self.window.cancel()
        self.wait_task()
        self.assertLess(len(self.window.history.rows()), 100)

    def test_numeric_sort(self):
        from vpnchecker.models import Measurement

        for speed in (9, 100, 20):
            self.window.history.add("test", 1, "success", Measurement(speed, 1, 2, "host", ""))
        self.window.speed_unit.setCurrentText("Mbps")
        self.window.refresh_history()
        from PyQt6.QtCore import Qt

        self.window.table.sortItems(4, Qt.SortOrder.AscendingOrder)
        values = [self.window.table.item(i, 4).data(0) for i in range(3)]
        self.assertEqual(values, [9, 20, 100])

    def test_json_order_survives_visual_grouping(self):
        self.load()
        self.window.baseline.setChecked(False)
        self.window.plan = ["germany-frankfurt", "japan-tokyo", "germany-nuremberg"]
        self.window.order.setCurrentText("JSON plan order")
        self.window.check_visible(True)
        with patch("vpnchecker.gui.Session") as session:
            self.window.start()
            self.wait_task()
            session.return_value.run.assert_called_once_with(self.window.plan)

    def test_import_json_validates_all_entries(self):
        import json

        self.load()
        path = Path(self.temp.name) / "plan.json"
        path.write_text(
            json.dumps({"locations": [{"country": "Germany", "region": "germany-frankfurt"}]})
        )
        with patch("vpnchecker.gui.QFileDialog.getOpenFileName", return_value=(str(path), "JSON")):
            self.window.import_plan()
        self.assertEqual(self.window.plan, ["germany-frankfurt"])
        self.assertEqual(self.window.order.currentText(), "JSON plan order")

    def test_invalid_endpoint_rejected_before_start(self):
        self.load()
        self.window.check_visible(True)
        self.window.endpoint.setText("not-a-number")
        with patch("vpnchecker.gui.Session") as session:
            self.window.start()
            session.assert_not_called()
        self.assertFalse(self.window.task.isRunning())
