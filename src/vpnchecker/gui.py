"""PyQt desktop UI. All VPN/network work lives outside the GUI thread."""

import csv
import json
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .backends import DemoSpeedtest, DemoVPN, ExpressVPN
from .desktop import (
    SIZE_UNITS,
    SPEED_UNITS,
    History,
    LoggedRunner,
    Session,
    Settings,
    ordered,
)
from .models import load_locations

ROOT = Path(__file__).resolve().parents[2]
DEMO_REGIONS = [
    "germany-frankfurt",
    "germany-nuremberg",
    "uk-london",
    "usa-new-york",
    "canada-toronto",
    "japan-tokyo",
    "singapore",
    "france-paris",
]


class Task(QThread):
    event = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        try:
            self.action(self.event.emit)
        except Exception as exc:
            self.failed.emit(str(exc))


class Chart(QWidget):
    def __init__(self):
        super().__init__()
        self.points = deque(maxlen=150)
        self.setMinimumHeight(150)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111c30"))
        painter.setPen(QColor("#8fabc7"))
        painter.drawText(14, 22, "LIVE TRANSFER · rolling samples · shared connection")
        peak = max([value for value, phase in self.points] + [1])
        width, height = self.width() - 28, self.height() - 48
        for i in range(1, len(self.points)):
            value, phase = self.points[i]
            prev, prev_phase = self.points[i - 1]
            if phase != prev_phase:
                continue
            painter.setPen(QPen(QColor("#45dbbe" if phase == "download" else "#ab9bff"), 2))
            painter.drawLine(
                int(14 + (i - 1) * width / max(1, len(self.points) - 1)),
                int(35 + height * (1 - prev / peak)),
                int(14 + i * width / max(1, len(self.points) - 1)),
                int(35 + height * (1 - value / peak)),
            )


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Speedchecker • VPN performance studio")
        self.resize(1280, 900)
        self.prefs = QSettings("speedchecker", "desktop")
        data = Path.home() / ".speedchecker"
        self.history = History(data / "history.sqlite3")
        self.log_dir = data / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
        self.task = None
        self.stop = threading.Event()
        self.regions = []
        self.display_order = []
        self.plan = []
        self.last_live = {}
        self.build()
        self.restore()
        self.refresh_history()

    def build(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("SPEEDCHECKER  /  VPN performance studio")
        title.setStyleSheet("font-size:24px; font-weight:700; color:#45dbbe; padding:12px")
        layout.addWidget(title)
        self.status = QLabel("Ready · Load all VPN locations to begin")
        status_bar = QHBoxLayout()
        status_bar.addWidget(self.status, 1)
        self.stop_button = QPushButton("■ Stop safely")
        self.stop_button.clicked.connect(self.cancel)
        self.stop_button.setEnabled(False)
        status_bar.addWidget(self.stop_button)
        layout.addLayout(status_bar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)
        page = QWidget()
        body = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.demo = QCheckBox("Offline demo (synthetic)")
        self.demo.toggled.connect(self.mode_changed)
        self.load_button = QPushButton("↻ Load ALL VPN locations")
        self.load_button.clicked.connect(self.load_regions)
        self.import_button = QPushButton("Import JSON plan…")
        self.import_button.clicked.connect(self.import_plan)
        for widget in (self.demo, self.load_button, self.import_button):
            bar.addWidget(widget)
        body.addLayout(bar)
        self.warning = QLabel(
            "Real mode requires an activated ExpressVPN app with expressvpnctl. "
            "Tests consume data. VPN locations run sequentially; workers share one tunnel."
        )
        self.warning.setWordWrap(True)
        body.addWidget(self.warning)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter VPN locations / country / endpoint alias…")
        self.search.textChanged.connect(self.populate)
        self.order = QComboBox()
        self.order.addItems(
            [
                "Provider order",
                "Alphabetical",
                "Reverse alphabetical",
                "Random",
                "Location group",
                "JSON plan order",
            ]
        )
        self.order.currentTextChanged.connect(self.populate)
        self.group = QCheckBox("Group by location prefix")
        self.group.setChecked(True)
        self.group.toggled.connect(self.populate)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.order)
        filters.addWidget(self.group)
        body.addLayout(filters)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["VPN location / endpoint alias", "Selection"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        body.addWidget(self.tree, 1)
        selection = QHBoxLayout()
        for text, action in [
            ("Check visible", lambda: self.check_visible(True)),
            ("Uncheck visible", lambda: self.check_visible(False)),
        ]:
            button = QPushButton(text)
            button.clicked.connect(action)
            selection.addWidget(button)
        self.selected_count = QLabel("0 locations loaded")
        selection.addWidget(self.selected_count)
        body.addLayout(selection)
        controls = QHBoxLayout()
        self.start_button = QPushButton("▶ Test checked locations")
        self.start_button.clicked.connect(self.start)
        self.single_button = QPushButton("Test highlighted location")
        self.single_button.clicked.connect(lambda: self.start(single=True))
        for widget in (self.start_button, self.single_button):
            controls.addWidget(widget)
        body.addLayout(controls)
        self.tabs.addTab(page, "01  Locations")

        settings_page = QWidget()
        form = QFormLayout(settings_page)
        self.repeat = self.spin(1, 10000, 1)
        self.workers = self.spin(1, 32, 1)
        self.command_timeout = self.spin(1, 600, 30)
        self.connection_timeout = self.spin(1, 900, 60)
        self.test_timeout = self.spin(5, 3600, 180)
        self.socket_timeout = self.spin(1, 300, 15)
        self.pause = self.spin(0, 600, 0)
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText(
            "Automatic nearest endpoint (or numeric speedtest server ID)"
        )
        self.baseline = QCheckBox("Measure without VPN before selected locations")
        self.baseline.setChecked(True)
        self.disconnect_existing = QCheckBox(
            "Allow disconnecting current VPN (will NOT restore it)"
        )
        self.speed_unit = QComboBox()
        self.speed_unit.addItems(SPEED_UNITS)
        self.size_unit = QComboBox()
        self.size_unit.addItems(SIZE_UNITS)
        self.size_unit.setCurrentText("MB")
        self.speed_unit.currentTextChanged.connect(self.units_changed)
        self.size_unit.currentTextChanged.connect(self.units_changed)
        fields = [
            ("Repetitions per location", self.repeat),
            ("Concurrent tests on SAME location", self.workers),
            ("VPN command timeout (s)", self.command_timeout),
            ("Connection state wait (s)", self.connection_timeout),
            ("Whole speed test deadline (s)", self.test_timeout),
            ("HTTP socket timeout (s)", self.socket_timeout),
            ("Pause between locations (s)", self.pause),
            ("Measurement endpoint ID", self.endpoint),
            ("Speed display units", self.speed_unit),
            ("Transfer size units", self.size_unit),
            ("Baseline", self.baseline),
            ("Existing connection", self.disconnect_existing),
        ]
        for label, widget in fields:
            form.addRow(label, widget)
        note = QLabel(
            "Concurrent tests share bandwidth; results are not independent line speeds.\n"
            "Grouping uses provider alias prefixes, not an authoritative geographic catalogue.\n"
            "Upload live bytes are handed to the network stack, not acknowledged.\n"
            "Changing display units never modifies stored Mbps measurements."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(settings_page, "02  Settings")

        live = QWidget()
        live_layout = QVBoxLayout(live)
        self.live_label = QLabel("No measurement yet")
        self.live_label.setStyleSheet("font-size:23px;color:#45dbbe;padding:14px")
        live_layout.addWidget(self.live_label)
        self.chart = Chart()
        live_layout.addWidget(self.chart)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(5000)
        self.logs.setPlaceholderText(
            "Live commands, command output, endpoint metadata, progress and errors…"
        )
        live_layout.addWidget(self.logs, 1)
        export_log = QPushButton("Save session log…")
        export_log.clicked.connect(self.export_log)
        live_layout.addWidget(export_log)
        self.tabs.addTab(live, "03  Live / logs")

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_filters = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search location, endpoint, error or date…")
        self.history_search.textChanged.connect(self.refresh_history)
        self.history_status = QComboBox()
        self.history_status.addItems(["All statuses", "success", "error", "cancelled"])
        self.history_status.currentTextChanged.connect(self.refresh_history)
        self.history_mode = QComboBox()
        self.history_mode.addItems(["Real + demo", "Real only", "Demo only"])
        self.history_mode.currentTextChanged.connect(self.refresh_history)
        self.min_speed = QDoubleSpinBox()
        self.min_speed.setRange(0, 1e9)
        self.min_speed.setPrefix("Min down (Mbps): ")
        self.min_speed.valueChanged.connect(self.refresh_history)
        for widget in (self.history_search, self.history_status, self.history_mode, self.min_speed):
            history_filters.addWidget(widget)
        history_layout.addLayout(history_filters)
        self.history_summary = QLabel()
        history_layout.addWidget(self.history_summary)
        self.table = QTableWidget(0, 11)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        history_layout.addWidget(self.table)
        export = QPushButton("Export filtered history (CSV / JSON)…")
        export.clicked.connect(self.export_history)
        history_layout.addWidget(export)
        self.tabs.addTab(history_page, "04  History")

    @staticmethod
    def spin(low, high, value):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        return widget

    def mode_changed(self):
        self.regions = []
        self.plan = []
        self.populate()
        self.status.setText(
            "DEMO · synthetic data, no network changes"
            if self.demo.isChecked()
            else "REAL mode · load VPN locations before testing"
        )

    def settings(self):
        return Settings(
            **{
                name: getattr(self, name).value()
                for name in (
                    "repeat",
                    "workers",
                    "command_timeout",
                    "connection_timeout",
                    "test_timeout",
                    "socket_timeout",
                    "pause",
                )
            },
            endpoint=self.endpoint.text().strip(),
            baseline=self.baseline.isChecked(),
            disconnect_existing=self.disconnect_existing.isChecked(),
            demo=self.demo.isChecked(),
        )

    def vpn(self, settings, emit):
        if settings.demo:
            return DemoVPN(DEMO_REGIONS)
        return ExpressVPN(
            LoggedRunner(emit, self.stop), settings.command_timeout, settings.connection_timeout
        )

    def launch(self, action):
        self.stop.clear()
        self.set_busy(True)
        self.task = Task(action)
        self.task.event.connect(self.on_event)
        self.task.failed.connect(self.error)
        self.task.finished.connect(self.finished)
        self.task.start()

    def set_busy(self, busy):
        for widget in (
            self.load_button,
            self.start_button,
            self.single_button,
            self.import_button,
            self.demo,
        ):
            widget.setEnabled(not busy)
        self.tabs.setTabEnabled(1, not busy)
        self.stop_button.setEnabled(busy)

    def finished(self):
        self.set_busy(False)
        self.status.setText(
            "Stopped · completed attempts saved" if self.stop.is_set() else "Ready · task finished"
        )
        self.refresh_history()

    def error(self, text):
        self.on_event({"type": "log", "text": "ERROR: " + text})
        QMessageBox.warning(self, "Speedchecker", text)

    def load_regions(self):
        settings = self.settings()

        def action(emit):
            regions = self.vpn(settings, emit).regions()
            emit({"type": "regions", "regions": regions})

        self.launch(action)

    def leaves(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.childCount():
                for j in range(item.childCount()):
                    yield item.child(j)
            else:
                yield item

    def populate(self):
        checked = {
            i.data(0, Qt.ItemDataRole.UserRole)
            for i in self.leaves()
            if i.checkState(0) == Qt.CheckState.Checked
        }
        self.tree.clear()
        regions = self.plan if self.order.currentText() == "JSON plan order" else self.regions
        regions = ordered(regions, self.order.currentText())
        self.display_order = regions
        parents = {}
        for region in regions:
            if self.search.text().casefold() not in region.casefold():
                continue
            parent = self.tree
            if self.group.isChecked():
                key = region.split("-")[0].replace("_", " ").title()
                if key not in parents:
                    parents[key] = QTreeWidgetItem(self.tree, [key])
                parent = parents[key]
            item = QTreeWidgetItem(parent, [region, "Check to include"])
            item.setData(0, Qt.ItemDataRole.UserRole, region)
            item.setCheckState(
                0, Qt.CheckState.Checked if region in checked else Qt.CheckState.Unchecked
            )
        self.tree.expandAll()
        self.selected_count.setText(
            f"{len(self.regions)} loaded · {sum(1 for _ in self.leaves())} shown"
        )

    def check_visible(self, checked):
        for item in self.leaves():
            item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def import_plan(self):
        if not self.regions:
            self.error("Load all VPN locations first so the JSON plan can be validated.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "JSON location plan", "", "JSON (*.json)")
        if not path:
            return
        try:
            locations = load_locations(Path(path))
            matched = [loc.find_region(self.regions) for loc in locations]
            missing = [
                loc.name for loc, region in zip(locations, matched, strict=True) if region is None
            ]
            if missing:
                raise ValueError("Unmatched locations: " + ", ".join(missing))
            self.plan = list(dict.fromkeys(matched))
            self.order.setCurrentText("JSON plan order")
            self.populate()
            self.check_visible(True)
        except Exception as exc:
            self.error(str(exc))

    def start(self, single=False):
        if single:
            item = self.tree.currentItem()
            selected = [item.data(0, Qt.ItemDataRole.UserRole)] if item else []
            selected = [r for r in selected if r]
        else:
            selected = [
                i.data(0, Qt.ItemDataRole.UserRole)
                for i in self.leaves()
                if i.checkState(0) == Qt.CheckState.Checked
            ]
        selected = [region for region in self.display_order if region in selected]
        if not selected:
            self.error("Select at least one VPN location.")
            return
        settings = self.settings()
        if settings.endpoint and (
            not settings.endpoint.isascii() or not settings.endpoint.isdigit()
        ):
            self.error("Measurement endpoint ID must be numeric (or empty for automatic).")
            return
        if (
            not settings.demo
            and QMessageBox.question(
                self,
                "Start real tests?",
                f"Test {len(selected)} locations × {settings.repeat} repetitions? "
                "This changes your VPN "
                "and consumes data. Created connections will be disconnected. "
                "Original VPN is not restored.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.save_preferences()
        self.chart.points.clear()
        self.last_live.clear()
        self.tabs.setCurrentIndex(2)
        self.status.setText(("DEMO" if settings.demo else "REAL") + " · running")

        def action(emit):
            vpn = self.vpn(settings, emit)
            Session(
                vpn,
                settings,
                self.history,
                emit,
                self.stop,
                factory=(lambda: DemoSpeedtest(vpn)) if settings.demo else None,
            ).run(selected)

        self.launch(action)

    def cancel(self):
        self.stop.set()
        self.status.setText("Stopping… waiting for bounded VPN command / disconnect cleanup")
        self.stop_button.setEnabled(False)

    def on_event(self, data):
        kind = data.get("type")
        if kind == "regions":
            self.regions = data["regions"]
            self.plan = []
            self.populate()
        elif kind == "progress":
            self.last_live = data
            self.chart.points.append((data["bps"], data["phase"]))
            self.chart.update()
            self.render_live()
        elif kind == "saved":
            self.refresh_history()
        # Progress is also saved to disk, without filling the visible log every 250 ms.
        text = json.dumps(data, ensure_ascii=False)
        line = f"{datetime.now().isoformat(timespec='milliseconds')} {text}"
        try:
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        except OSError as exc:
            self.status.setText(f"Log write failed: {exc}")
        if kind != "progress":
            self.logs.appendPlainText(line)

    def render_live(self):
        d = self.last_live
        if not d:
            return
        unit, size = self.speed_unit.currentText(), self.size_unit.currentText()
        self.live_label.setText(
            f"{d.get('region', '')} · #{d.get('attempt', '')} · {d['phase'].upper()}\n"
            f"{d['bps'] / SPEED_UNITS[unit]:.2f} {unit}   |   "
            f"{d['bytes'] / SIZE_UNITS[size]:.2f} {size}"
        )

    def units_changed(self):
        if hasattr(self, "table"):
            self.render_live()
            self.refresh_history()

    def refresh_history(self):
        if not hasattr(self, "table"):
            return
        try:
            rows = self.history.rows()
        except Exception as exc:
            self.status.setText(f"History error: {exc}")
            return
        query = self.history_search.text().casefold()
        status = self.history_status.currentText()
        mode = self.history_mode.currentIndex()
        rows = [
            r
            for r in rows
            if (status == "All statuses" or r["status"] == status)
            and (mode == 0 or bool(r["demo"]) == (mode == 2))
            and (self.min_speed.value() == 0 or (r["download"] or 0) >= self.min_speed.value())
            and query in " ".join(str(v) for v in r.values()).casefold()
        ]
        self.filtered_rows = rows
        unit = self.speed_unit.currentText()
        factor = 1e6 / SPEED_UNITS[unit]
        self.table.setSortingEnabled(False)
        self.table.setHorizontalHeaderLabels(
            [
                "UTC time",
                "VPN location",
                "Attempt",
                "Status",
                f"Down ({unit})",
                f"Up ({unit})",
                "Latency (ms)",
                "Endpoint",
                "Error",
                "Mode",
                "Settings",
            ]
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [
                r["time"],
                r["region"],
                r["attempt"],
                r["status"],
                round(r["download"] * factor, 3) if r["download"] is not None else "",
                round(r["upload"] * factor, 3) if r["upload"] is not None else "",
                round(r["latency"], 3) if r["latency"] is not None else "",
                r["endpoint"],
                r["error"],
                "DEMO" if r["demo"] else "REAL",
                r["settings"],
            ]
            for j, value in enumerate(values):
                cell = QTableWidgetItem()
                cell.setData(Qt.ItemDataRole.DisplayRole, value)
                cell.setToolTip(str(value))
                self.table.setItem(i, j, cell)
        self.table.setSortingEnabled(True)
        successful = [r for r in rows if r["status"] == "success"]
        average = sum(r["download"] for r in successful) / len(successful) if successful else 0
        self.history_summary.setText(
            f"{len(rows)} attempts · {len(successful)} successful · "
            f"average download {average * factor:.2f} {unit} · raw exports use Mbps"
        )

    def export_history(self):
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export filtered history", "history.json", "JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv") or selected_filter.startswith("CSV"):
                with open(path, "w", encoding="utf-8-sig", newline="") as file:
                    if self.filtered_rows:
                        writer = csv.DictWriter(file, fieldnames=self.filtered_rows[0].keys())
                        writer.writeheader()
                        writer.writerows(self.filtered_rows)
            else:
                Path(path).write_text(
                    json.dumps(self.filtered_rows, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        except OSError as exc:
            self.error(str(exc))

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save session log", "speedchecker.log", "Log (*.log)"
        )
        if path:
            try:
                Path(path).write_text(
                    self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else "",
                    encoding="utf-8",
                )
            except OSError as exc:
                self.error(str(exc))

    def save_preferences(self):
        for name in (
            "repeat",
            "workers",
            "command_timeout",
            "connection_timeout",
            "test_timeout",
            "socket_timeout",
            "pause",
        ):
            self.prefs.setValue(name, getattr(self, name).value())
        for name in ("speed_unit", "size_unit", "order"):
            self.prefs.setValue(name, getattr(self, name).currentText())
        self.prefs.setValue("endpoint", self.endpoint.text())
        self.prefs.setValue("baseline", self.baseline.isChecked())
        # Never persist destructive consent, or silently start in demo mode.

    def restore(self):
        for name in (
            "repeat",
            "workers",
            "command_timeout",
            "connection_timeout",
            "test_timeout",
            "socket_timeout",
            "pause",
        ):
            widget = getattr(self, name)
            widget.setValue(int(self.prefs.value(name, widget.value())))
        for name in ("speed_unit", "size_unit", "order"):
            widget = getattr(self, name)
            widget.setCurrentText(str(self.prefs.value(name, widget.currentText())))
        self.endpoint.setText(str(self.prefs.value("endpoint", "")))
        self.baseline.setChecked(self.prefs.value("baseline", True, type=bool))

    def closeEvent(self, event):
        if self.task and self.task.isRunning():
            self.cancel()
            QMessageBox.information(
                self,
                "Stopping safely",
                "Wait for test cancellation and VPN cleanup before closing.",
            )
            event.ignore()
            return
        self.save_preferences()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget { background:#0b1220; color:#dbe8f6; font-size:13px; }
        QMainWindow { background:#0b1220; }
        QTabWidget::pane, QGroupBox { border:1px solid #26354e; border-radius:8px; }
        QTabBar::tab { padding:13px 24px; background:#142037; }
        QTabBar::tab:selected { color:#45dbbe; border-bottom:2px solid #45dbbe; }
        QPushButton { background:#1b3550; border:1px solid #31516b; border-radius:7px;
            padding:10px 16px; }
        QPushButton:hover { background:#254a65; }
        QPushButton:disabled { color:#62748b; background:#152032; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:#152238;
            padding:8px; border:1px solid #2d405c; border-radius:5px; }
        QTreeWidget, QTableWidget, QPlainTextEdit { background:#111c30; border:1px solid #26354e;
            selection-background-color:#23566b; }
        QHeaderView::section { background:#1b2d46; color:#93b9cf; padding:8px; border:0; }
        QCheckBox { padding:6px; }
        QCheckBox::indicator { width:18px; height:18px; }
        QScrollBar:vertical { background:#142037; width:12px; }
        QScrollBar::handle:vertical { background:#3a5576; min-height:20px; }
    """)
    window = Window()
    window.show()
    return app.exec()
