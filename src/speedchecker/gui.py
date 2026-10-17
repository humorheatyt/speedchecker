"""SpeedChecker PyQt6 GUI — modern, bilingual (EN/FA), fully live.

Run it with ``python app.py`` (project root) or ``speedchecker-gui``.
Everything is here: ExpressVPN region catalogue and grouped selection,
single/batch tests, repeat count, timeouts, unit selection, live gauges +
chart, history with filters, and a live log of everything that happens.
"""

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .backends import (
    DemoVPN,
    ExpressVPN,
    FallbackSpeedtest,
    OoklaSpeedtest,
    bundled_speedtest_binary,
)
from .engine import BuiltinSpeedtest, DemoSpeedtestLive
from .history import HistoryStore, filter_history
from .i18n import is_rtl, tr
from .models import CheckerError
from .ookla_download import OFFICIAL_PAGE, download_ookla
from .servers import (
    Server,
    demo_servers,
    express_region,
    group_servers,
    load_servers_file,
    ordered_servers,
    sort_servers,
)
from .units import SPEED_DESCRIPTIONS, SPEED_UNITS, convert_speed, format_size
from .widgets import GaugeWidget, LiveChart, ServerTree

STYLE = """
QMainWindow, QWidget { background:#0f172a; color:#e2e8f0;
  font-family:'Segoe UI',Tahoma,sans-serif; font-size:10pt; }
QTabWidget::pane { border:1px solid #334155; border-radius:14px; }
QWidget { alternate-background-color:#17283e; }
QTabBar::tab { background:#1e293b; padding:9px 18px; margin-right:3px;
  border-top-left-radius:10px; border-top-right-radius:10px; }
QTabBar::tab:selected { background:#0ea5e9; color:white;
  font-weight:bold; }
QPushButton { background:#0ea5e9; color:white; border:none;
  border-radius:9px; padding:9px 16px; font-weight:bold; }
QPushButton:hover { background:#38bdf8; }
QPushButton:pressed { background:#0284c7; }
QPushButton:disabled { background:#334155; color:#94a3b8; }
QPushButton#danger { background:#e11d48; }
QPushButton#secondary { background:#334155; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget,
QTreeWidget, QPlainTextEdit { background:#1e293b; border:1px solid #334155;
  border-radius:8px; padding:6px; selection-background-color:#0ea5e9; }
QGroupBox { border:1px solid #334155; border-radius:10px;
  margin-top:12px; padding-top:14px; font-weight:bold; }
QProgressBar { background:#1e293b; border-radius:8px; height:16px; text-align:center; }
QProgressBar::chunk { background:#22c55e; border-radius:8px; }
QHeaderView::section { background:#243751; color:#7dd3fc; padding:8px;
  border:none; font-weight:bold; }
QTreeWidget::item:selected, QTableWidget::item:selected { background:#155e75; color:white; }
QCheckBox::indicator:checked { background:#22d3ee; border-radius:4px; }
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TestWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(str, float, int)  # phase, live Mbps, bytes
    record = pyqtSignal(dict)  # one finished server record
    downloaded = pyqtSignal(str)
    download_progress = pyqtSignal(int, int)  # bytes done, total (0 = unknown)
    fetched = pyqtSignal(list)  # VPN regions (list[dict])
    failed = pyqtSignal(str)  # action failed (fetch/download); tests record per server
    busy = pyqtSignal(bool)

    def __init__(self, action: str, payload: dict, parent=None):
        super().__init__(parent)
        self.action, self.payload = action, payload
        self.cancel_event = threading.Event()
        self._prefer_builtin = False  # set after an Ookla failure in auto mode

    # -- engine factory ---------------------------------------------------
    def _builtin_engine(self, server: Server | None):
        p = self.payload

        def emit(phase, mbps, done):
            self.progress.emit(phase, mbps, done)

        return BuiltinSpeedtest(
            server,
            timeout=p["test_timeout"],
            duration=p["duration"],
            connections=p["connections"],
            progress=emit,
            log=self.log.emit,
            cancel=self.cancel_event,
        )

    def _engine(self, server: Server | None):
        p = self.payload
        if p["backend"] == "demo":
            return DemoSpeedtestLive(
                server,
                duration=min(p["duration"], 4.0),
                progress=lambda phase, mbps, done: self.progress.emit(phase, mbps, done),
                log=self.log.emit,
                cancel=self.cancel_event,
            )
        binary = bundled_speedtest_binary()
        use_ookla = p["backend"] == "ookla" or (
            p["backend"] == "auto" and binary and not self._prefer_builtin
        )
        if use_ookla:
            self.log.emit(f"Engine: Ookla binary {binary or 'from PATH'}")
            engine = OoklaSpeedtest(
                timeout=p["test_timeout"],
                accept_license=p["accept_license"],
                server_id=server.id if server and server.id else "",
                log=self.log.emit,
                cancel=self.cancel_event,
            )
            if p["backend"] == "auto":
                # "Auto" only stays automatic if a failed Ookla run can fall
                # back to the bundled engine instead of losing the result.
                return FallbackSpeedtest(
                    engine,
                    lambda: self._builtin_engine(server),
                    log=self.log.emit,
                    on_fallback=self._use_builtin_after_ookla_failure,
                )
            return engine
        if p["backend"] == "auto" and self._prefer_builtin:
            self.log.emit("Engine: built-in (Ookla fallback from earlier in this run)")
        else:
            self.log.emit(
                "Engine: built-in (bundled with the project, no external speedtest needed)"
            )
        return self._builtin_engine(server)

    def _use_builtin_after_ookla_failure(self):
        self._prefer_builtin = True

    def _vpn(self, regions_servers):
        p = self.payload
        if not p["vpn_mode"]:
            return None
        if p["backend"] == "demo":
            return DemoVPN([s.host for s in regions_servers])
        return ExpressVPN(command_timeout=p["cmd_timeout"], connection_timeout=p["conn_timeout"])

    def _measure_server(self, server: Server, vpn) -> dict:
        p = self.payload
        record = {
            "time": _now(),
            "server": server.host,
            "location": server.label,
            "sponsor": server.sponsor,
            "status": "ok",
            "error": "",
            "mode": p["backend"],
            "download_mbps": None,
            "upload_mbps": None,
            "latency_ms": None,
            "repeat": p["repeat"],
            "connection": "vpn" if vpn else "direct",
        }
        connected = False
        try:
            if vpn is not None:
                region = server.host
                self.log.emit(f"VPN: connecting to {region} …")
                connected = True  # connect may establish a tunnel before raising
                elapsed = vpn.connect(region)
                self.log.emit(f"VPN: connected in {elapsed:.2f}s")
            # VPN region IDs are not Ookla IDs/hosts. A custom speed-test
            # endpoint, however, must keep its explicit server selection.
            target = server if p["backend"] == "demo" or server.id or server.url else None
            # One engine per server so an "auto" fallback also covers repeats.
            engine = self._engine(target)
            samples = []
            for i in range(p["repeat"]):
                if self.cancel_event.is_set():
                    raise CheckerError("Test cancelled by user.")
                self.log.emit(f"— {server.label} ({server.host}) test {i + 1}/{p['repeat']} —")
                samples.append(engine.measure())
            record.update(
                download_mbps=round(fmean(s.download_mbps for s in samples), 3),
                upload_mbps=round(fmean(s.upload_mbps for s in samples), 3),
                latency_ms=round(fmean(s.latency_ms for s in samples), 2),
                server=samples[-1].server,
            )
            self.log.emit(
                f"✓ {server.label}: ↓{record['download_mbps']} Mbps "
                f"↑{record['upload_mbps']} Mbps ping {record['latency_ms']} ms"
            )
        except Exception as exc:  # keep batch going; history keeps the error
            record.update(status="error", error=str(exc))
            self.log.emit(f"✗ {server.label}: {exc}")
        finally:
            if connected:
                try:
                    vpn.disconnect()
                    self.log.emit("VPN: disconnected")
                except Exception as exc:
                    record.update(status="error", error=f"VPN disconnect failed: {exc}")
                    self.cancel_event.set()
                    self.log.emit(record["error"])
        return record

    def run(self):  # noqa: C901 - one clear dispatch
        self.busy.emit(True)
        try:
            if self.action == "fetch":
                if self.payload["backend"] == "demo":
                    servers = demo_servers()
                else:
                    regions = ExpressVPN(command_timeout=self.payload["cmd_timeout"]).regions()
                    servers = [express_region(r) for r in regions]
                self.fetched.emit([s.to_dict() for s in servers])
            elif self.action == "download":
                self.downloaded.emit(
                    str(
                        download_ookla(
                            self.log.emit,
                            progress=lambda done, total: self.download_progress.emit(done, total),
                        )
                    )
                )
            elif self.action in ("single", "batch"):
                servers = [Server.from_dict(d) for d in self.payload["servers"]]
                vpn = self._vpn(servers)
                if self.payload["baseline"] and not vpn:
                    raise CheckerError("Enable ExpressVPN mode for a verified direct baseline.")
                if not vpn and self.payload["backend"] != "demo" and any(
                    s.sponsor.startswith("ExpressVPN") for s in servers
                ):
                    raise CheckerError(
                        "Enable ExpressVPN mode to test VPN locations. "
                        "Direct testing of a VPN region cannot measure that location."
                    )
                if vpn and vpn.state() != "disconnected":
                    if not self.payload["disconnect_existing"]:
                        raise CheckerError(
                            "VPN already connected. Disconnect it first or enable "
                            "Disconnect existing VPN."
                        )
                    vpn.disconnect()
                if self.payload["baseline"]:
                    if self.cancel_event.is_set():
                        raise CheckerError("Test cancelled by user.")
                    self.log.emit("Measuring direct connection once before VPN tests…")
                    baseline = Server(host="direct", city="Without VPN", sponsor="Baseline")
                    original = self.payload["repeat"]
                    self.payload["repeat"] = 1
                    try:
                        self.record.emit(self._measure_server(baseline, None))
                    finally:
                        self.payload["repeat"] = original
                for server in servers:
                    if self.cancel_event.is_set():
                        self.log.emit("Stopped by user.")
                        break
                    self.record.emit(self._measure_server(server, vpn))
            else:
                raise CheckerError(f"Unknown action {self.action}")
        except Exception as exc:
            self.log.emit(f"✗ {exc}")
            self.failed.emit(str(exc))
        finally:
            self.busy.emit(False)


class HistoryItem(QTableWidgetItem):
    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a < b
        return super().__lt__(other)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.lang = "en"
        self.servers: list[Server] = []
        self.history = HistoryStore()
        self.worker: TestWorker | None = None
        self._current_action = ""
        self._downloading = False
        self._download_logged = 0  # last logged download milestone (25 %)
        self._build_ui()
        self._refresh_history()
        self.log_line(
            "SpeedChecker ready. Fetch the server list or load one from a JSON file "
            "(Demo mode works fully offline)."
        )
        binary = bundled_speedtest_binary()
        self.log_line(
            f"Bundled Ookla binary: {binary or 'not present (built-in engine will be used)'}"
        )

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setWindowTitle(tr(self.lang, "app_title"))
        self.resize(1240, 820)
        self.setStyleSheet(STYLE)
        tabs = QTabWidget()
        self.tabs = tabs
        tabs.addTab(self._home_tab(), "")
        tabs.addTab(self._servers_tab(), "")
        tabs.addTab(self._history_tab(), "")
        tabs.addTab(self._logs_tab(), "")
        tabs.addTab(self._settings_tab(), "")
        self.setCentralWidget(tabs)
        self._retranslate()

    def _home_tab(self) -> QWidget:
        w, layout = QWidget(), QVBoxLayout()
        gauges = QHBoxLayout()
        self.gauge_down, self.gauge_up = GaugeWidget(color="#22d3ee"), GaugeWidget(color="#a78bfa")
        gauges.addWidget(self.gauge_down, 1)
        gauges.addWidget(self.gauge_up, 1)
        info = QVBoxLayout()
        self.lbl_latency, self.lbl_server, self.lbl_live, self.lbl_status = (
            QLabel("—") for _ in range(4)
        )
        for label in (self.lbl_latency, self.lbl_server, self.lbl_live, self.lbl_status):
            label.setStyleSheet("font-size:12pt; padding:4px;")
            info.addWidget(label)
        info.addStretch(1)
        gauges.addLayout(info, 1)
        layout.addLayout(gauges)
        self.chart = LiveChart()
        layout.addWidget(self.chart)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        buttons = QHBoxLayout()
        self.btn_start, self.btn_stop = QPushButton(), QPushButton()
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(lambda: self.start_tests(batch=False))
        self.btn_stop.clicked.connect(self.stop_tests)
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_stop)
        layout.addLayout(buttons)
        w.setLayout(layout)
        return w

    def _servers_tab(self) -> QWidget:
        w, layout = QWidget(), QVBoxLayout()
        top = QHBoxLayout()
        self.btn_fetch, self.btn_load = QPushButton(), QPushButton(objectName="secondary")
        self.btn_test_sel, self.btn_batch = QPushButton(), QPushButton()
        self.btn_fetch.clicked.connect(self.fetch_servers)
        self.btn_load.clicked.connect(self.load_file)
        self.btn_test_sel.clicked.connect(lambda: self.start_tests(batch=False))
        self.btn_batch.clicked.connect(lambda: self.start_tests(batch=True))
        for b in (self.btn_fetch, self.btn_load, self.btn_test_sel, self.btn_batch):
            top.addWidget(b)
        layout.addLayout(top)
        filt = QHBoxLayout()
        self.search = QLineEdit()
        self.search.textChanged.connect(self.refresh_server_tree)
        self.combo_group, self.combo_sort = QComboBox(), QComboBox()
        self.combo_group.addItems(["none", "country", "sponsor", "letter"])
        self.combo_sort.addItems(
            ["file", "name", "country", "city", "sponsor", "host", "distance", "latency", "random"]
        )
        self.combo_group.setCurrentText("country")
        self.combo_sort.setCurrentText("country")
        for combo in (self.combo_group, self.combo_sort):
            combo.currentTextChanged.connect(self.refresh_server_tree)
        self.lbl_group, self.lbl_sort = QLabel(), QLabel()
        for widget in (
            self.search,
            self.lbl_group,
            self.combo_group,
            self.lbl_sort,
            self.combo_sort,
        ):
            filt.addWidget(widget)
        layout.addLayout(filt)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.tree = ServerTree()
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setColumnCount(5)
        for column, width in enumerate((280, 180, 320, 110, 110)):
            self.tree.setColumnWidth(column, width)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(lambda *_: self.start_tests(batch=False))
        layout.addWidget(self.tree)
        w.setLayout(layout)
        return w

    def _history_tab(self) -> QWidget:
        w, layout = QWidget(), QVBoxLayout()
        filt = QHBoxLayout()
        self.combo_hstatus = QComboBox()
        self.combo_hstatus.addItems(["all", "ok", "error"])
        self.htext = QLineEdit()
        self.hmin_down = QDoubleSpinBox(maximum=100000)
        self.hmin_down.setSpecialValueText("—")
        self.hmax_lat = QDoubleSpinBox(maximum=100000)
        self.hmax_lat.setSpecialValueText("—")
        self.btn_clear_hist, self.btn_export = QPushButton(), QPushButton(objectName="secondary")
        for combo in (self.combo_hstatus,):
            combo.currentTextChanged.connect(self._refresh_history)
        self.htext.textChanged.connect(self._refresh_history)
        self.hmin_down.valueChanged.connect(self._refresh_history)
        self.hmax_lat.valueChanged.connect(self._refresh_history)
        self.btn_clear_hist.clicked.connect(self._clear_history)
        self.btn_export.clicked.connect(self._export_history)
        for widget in (
            self.combo_hstatus,
            self.htext,
            self.hmin_down,
            self.hmax_lat,
            self.btn_clear_hist,
            self.btn_export,
        ):
            filt.addWidget(widget)
        layout.addLayout(filt)
        self.history_table = QTableWidget(0, 9)
        self.history_table.setSortingEnabled(True)
        self.history_table.setAlternatingRowColors(True)
        layout.addWidget(self.history_table)
        w.setLayout(layout)
        return w

    def _logs_tab(self) -> QWidget:
        w, layout = QWidget(), QVBoxLayout()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view)
        row = QHBoxLayout()
        self.btn_clear_log, self.btn_save_log = (
            QPushButton(objectName="secondary"),
            QPushButton(objectName="secondary"),
        )
        self.btn_clear_log.clicked.connect(self.log_view.clear)
        self.btn_save_log.clicked.connect(self._save_log)
        row.addWidget(self.btn_clear_log)
        row.addWidget(self.btn_save_log)
        row.addStretch(1)
        layout.addLayout(row)
        w.setLayout(layout)
        return w

    def _settings_tab(self) -> QWidget:
        w, form = QWidget(), QFormLayout()
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["en", "fa"])
        self.combo_lang.currentTextChanged.connect(self._set_language)
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(list(SPEED_UNITS))
        self.combo_unit.currentTextChanged.connect(self._unit_changed)
        self.unit_description = QLabel()
        self.combo_backend = QComboBox()
        self.combo_backend.addItems(["auto", "builtin", "ookla", "demo"])
        self.spin_repeat = QSpinBox(minimum=1, maximum=100, value=1)
        self.spin_conn_to = QDoubleSpinBox(minimum=1, maximum=3600, value=60)
        self.spin_cmd_to = QDoubleSpinBox(minimum=1, maximum=3600, value=30)
        self.spin_test_to = QDoubleSpinBox(minimum=1, maximum=3600, value=180)
        self.spin_duration = QDoubleSpinBox(minimum=1, maximum=300, value=10)
        self.spin_conns = QSpinBox(minimum=1, maximum=16, value=4)
        self.chk_accept = QCheckBox()
        self.chk_vpn = QCheckBox()
        self.chk_vpn.setChecked(True)
        self.chk_disconnect = QCheckBox()
        self.chk_baseline = QCheckBox()
        self.btn_download = QPushButton()
        self.btn_download.clicked.connect(self._download_ookla)
        self.btn_ookla_page = QPushButton(objectName="secondary")
        self.btn_ookla_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OFFICIAL_PAGE)))
        # Live feedback for the Ookla CLI download (Settings tab).
        self.download_bar = QProgressBar()
        self.download_bar.setVisible(False)
        self.download_status = QLabel()
        self.download_status.setWordWrap(True)
        self.download_panel = QWidget()
        download_layout = QHBoxLayout(self.download_panel)
        download_layout.setContentsMargins(0, 0, 0, 0)
        download_layout.addWidget(self.download_status, 1)
        download_layout.addWidget(self.download_bar)
        self._form_rows = [
            ("language", self.combo_lang),
            ("unit", self.combo_unit),
            ("backend", self.combo_backend),
            ("repeat", self.spin_repeat),
            ("timeout_conn", self.spin_conn_to),
            ("timeout_cmd", self.spin_cmd_to),
            ("timeout_test", self.spin_test_to),
            ("duration", self.spin_duration),
            ("connections", self.spin_conns),
            ("accept_license", self.chk_accept),
            ("vpn_mode", self.chk_vpn),
            ("disconnect_existing", self.chk_disconnect),
            ("baseline", self.chk_baseline),
            ("download_ookla", self.btn_download),
            ("download_status", self.download_panel),
            ("ookla_page", self.btn_ookla_page),
        ]
        for _, widget in self._form_rows:
            form.addRow(QLabel(), widget)
        form.addRow("", self.unit_description)
        w.setLayout(form)
        return w

    # -------------------------------------------------------------- i18n
    def _set_language(self, lang: str):
        self.lang = lang
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl(lang) else Qt.LayoutDirection.LeftToRight
        )
        self._retranslate()

    def _retranslate(self):
        def t(key):
            return tr(self.lang, key)

        self.setWindowTitle(t("app_title"))
        for i, key in enumerate(("home", "servers", "history", "logs", "settings")):
            self.tabs.setTabText(i, t(key))
        self.gauge_down.set_title(t("download"))
        self.gauge_up.set_title(t("upload"))
        self.btn_start.setText(t("start_test"))
        self.btn_stop.setText(t("stop"))
        self.btn_fetch.setText(t("fetch_servers"))
        self.btn_load.setText(t("load_file"))
        self.btn_test_sel.setText(t("test_selected"))
        self.btn_batch.setText(t("batch_test"))
        self.search.setPlaceholderText(t("search"))
        self.lbl_group.setText(t("group_by"))
        self.lbl_sort.setText(t("sort_by"))
        self.hint.setText(t("group_servers_hint"))
        self.tree.setHeaderLabels(
            [t("location"), t("sponsor"), t("host"), t("distance"), t("latency")]
        )
        self.history_table.setHorizontalHeaderLabels(
            [
                t("time"),
                t("location"),
                t("jitter_server"),
                t("download"),
                t("upload"),
                t("latency"),
                t("status"),
                t("connection"),
                t("error"),
            ]
        )
        self.btn_clear_hist.setText(t("clear_history"))
        self.btn_export.setText(t("export"))
        self.btn_clear_log.setText(t("clear_log"))
        self.btn_save_log.setText(t("save_log"))
        self.btn_download.setText(t("download_button"))
        self.btn_ookla_page.setText(t("ookla_page_button"))
        self.htext.setPlaceholderText(t("filter_text"))
        backend_labels = {
            "auto": t("backend_auto"),
            "builtin": t("backend_builtin"),
            "ookla": t("backend_ookla"),
            "demo": t("backend_demo"),
        }
        current = self.combo_backend.currentData() or "auto"
        self.combo_backend.blockSignals(True)
        self.combo_backend.clear()
        for code, label in backend_labels.items():
            self.combo_backend.addItem(label, code)
        index = self.combo_backend.findData(current)
        self.combo_backend.setCurrentIndex(index if index >= 0 else 0)
        self.combo_backend.blockSignals(False)
        labels = {
            "language": t("language"),
            "unit": t("unit"),
            "backend": t("backend"),
            "repeat": t("repeat"),
            "timeout_conn": t("timeout_conn"),
            "timeout_cmd": t("timeout_cmd"),
            "timeout_test": t("timeout_test"),
            "duration": t("duration"),
            "connections": t("connections"),
            "accept_license": t("accept_license"),
            "vpn_mode": t("vpn_mode"),
            "disconnect_existing": t("disconnect_existing"),
            "baseline": t("baseline"),
            "download_ookla": t("download_ookla"),
            "download_status": t("download_status"),
            "ookla_page": t("ookla_page"),
        }
        form = self._settings_tab_layout()
        for row, (key, _w) in enumerate(self._form_rows):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item and item.widget():
                item.widget().setText(labels[key])
        self._retranslate_tooltips()
        if not self._downloading:
            self._show_ookla_status()
        self._unit_changed(self.combo_unit.currentText())

    def _retranslate_tooltips(self):
        t = lambda key: tr(self.lang, key)  # noqa: E731 - tiny local helper
        self.combo_backend.setToolTip(t("tip_backend"))
        self.spin_repeat.setToolTip(t("tip_repeat"))
        self.spin_conn_to.setToolTip(t("tip_timeout_conn"))
        self.spin_cmd_to.setToolTip(t("tip_timeout_cmd"))
        self.spin_test_to.setToolTip(t("tip_timeout_test"))
        self.spin_duration.setToolTip(t("tip_duration"))
        self.spin_conns.setToolTip(t("tip_connections"))
        self.chk_accept.setToolTip(t("tip_accept_license"))
        self.chk_vpn.setToolTip(t("tip_vpn_mode"))
        self.chk_disconnect.setToolTip(t("tip_disconnect_existing"))
        self.chk_baseline.setToolTip(t("tip_baseline"))

    def _show_ookla_status(self):
        """Show whether the official binary exists, and where."""
        binary = bundled_speedtest_binary()
        if binary is None:
            self.download_status.setText(tr(self.lang, "ookla_missing"))
            return
        try:
            size = format_size(binary.stat().st_size)
        except OSError:
            size = "—"
        self.download_status.setText(tr(self.lang, "ookla_ready").format(path=binary, size=size))
        self.btn_download.setText(tr(self.lang, "redownload_ookla"))

    def _settings_tab_layout(self) -> QFormLayout:
        return self.tabs.widget(4).layout()

    def _backend(self) -> str:
        return self.combo_backend.currentData() or "auto"

    def _unit_changed(self, unit: str):
        description = SPEED_DESCRIPTIONS[unit][1 if self.lang == "fa" else 0]
        self.unit_description.setText(f"{unit} ({description})")
        self.gauge_down.set_unit(unit)
        self.gauge_up.set_unit(unit)
        self._refresh_history()

    # ------------------------------------------------------------- servers
    def _payload(self, servers: list[Server]) -> dict:
        return {
            "servers": [s.to_dict() for s in servers],
            "backend": self._backend(),
            "repeat": self.spin_repeat.value(),
            "conn_timeout": self.spin_conn_to.value(),
            "cmd_timeout": self.spin_cmd_to.value(),
            "test_timeout": self.spin_test_to.value(),
            "duration": self.spin_duration.value(),
            "connections": self.spin_conns.value(),
            "accept_license": self.chk_accept.isChecked(),
            "vpn_mode": self.chk_vpn.isChecked(),
            "baseline": self.chk_baseline.isChecked(),
            "disconnect_existing": self.chk_disconnect.isChecked(),
        }

    def _run_worker(self, action: str, payload: dict):
        self._current_action = action
        self.worker = TestWorker(action, payload, self)
        self.worker.log.connect(self.log_line)
        self.worker.progress.connect(self._on_progress)
        self.worker.record.connect(self._on_record)
        self.worker.fetched.connect(self._on_fetched)
        self.worker.downloaded.connect(self._on_downloaded)
        self.worker.download_progress.connect(self._on_download_progress)
        self.worker.failed.connect(self._on_failed)
        self.worker.busy.connect(self._on_busy)
        self.worker.start()

    def fetch_servers(self):
        self.log_line("Fetching all ExpressVPN regions from expressvpnctl …")
        self._run_worker("fetch", self._payload([]))

    def _download_ookla(self):
        if not self.chk_accept.isChecked():
            QMessageBox.warning(self, "Ookla", tr(self.lang, "accept_first"))
            return
        self._downloading = True
        self._download_logged = 0
        self.download_bar.setVisible(True)
        self.download_bar.setRange(0, 0)  # size unknown until headers arrive
        self.download_bar.setValue(0)
        self.download_status.setText(tr(self.lang, "download_start"))
        self.log_line(tr(self.lang, "download_start"))
        self._run_worker("download", self._payload([]))

    def _on_download_progress(self, done: int, total: int):
        if total > 0:
            percent = min(100, int(done * 100 / total))
            self.download_bar.setRange(0, 100)
            self.download_bar.setValue(percent)
            self.download_status.setText(
                tr(self.lang, "download_progress").format(
                    percent=percent,
                    done=format_size(done),
                    total=format_size(total),
                )
            )
        else:
            percent = 0
            self.download_status.setText(
                tr(self.lang, "download_progress_unknown").format(done=format_size(done))
            )
        if percent >= self._download_logged + 25:
            self._download_logged = percent
            self.log_line(
                tr(self.lang, "download_progress").format(
                    percent=percent,
                    done=format_size(done),
                    total=format_size(total) if total else "?",
                )
            )

    def _on_downloaded(self, path: str):
        self._downloading = False
        self.download_bar.setVisible(False)
        self.download_bar.setRange(0, 100)
        self.download_bar.setValue(100)
        try:
            size = format_size(Path(path).stat().st_size)
        except OSError:
            size = "—"
        self.download_status.setText(tr(self.lang, "ookla_ready").format(path=path, size=size))
        self.btn_download.setText(tr(self.lang, "redownload_ookla"))
        self.log_line(f"✓ Ookla CLI downloaded ({size}): {path}")
        index = self.combo_backend.findData("ookla")
        if index >= 0:
            self.combo_backend.setCurrentIndex(index)
        QMessageBox.information(
            self,
            tr(self.lang, "download_done_title"),
            tr(self.lang, "download_done").format(path=path, size=size),
        )

    def _on_failed(self, message: str):
        if self._current_action != "download":
            return
        self._downloading = False
        self.download_bar.setVisible(False)
        self.download_status.setText(tr(self.lang, "download_failed_status"))
        QMessageBox.critical(
            self,
            tr(self.lang, "download_failed_title"),
            message,
        )

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr(self.lang, "load_file"), "", "JSON (*.json)")
        if not path:
            return
        try:
            self.servers = load_servers_file(path, log=self.log_line)
        except CheckerError as exc:
            self.log_line(f"✗ {exc}")
            return
        self.refresh_server_tree()

    def _on_fetched(self, items: list):
        self.servers = [Server.from_dict(d) for d in items]
        self.log_line(f"ExpressVPN locations ready: {len(self.servers)} endpoints.")
        self.refresh_server_tree()
        self.tabs.setCurrentIndex(1)

    def _displayed_servers(self) -> list[Server]:
        needle = self.search.text().strip().casefold()
        servers = [
            s
            for s in self.servers
            if not needle
            or needle in f"{s.label} {s.country} {s.city} {s.sponsor} {s.host}".casefold()
        ]
        return sort_servers(servers, self.combo_sort.currentText())

    def refresh_server_tree(self):
        # The tree owns the selection order; rebuilding it (sort/group/search)
        # must not lose what the user selected, even if the filter hides it.
        remembered = self.tree.remember_selection({s.host for s in self.servers})
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            servers = self._displayed_servers()
            groups = group_servers(servers, self.combo_group.currentText())
            for group, members in groups.items():
                parent = (
                    QTreeWidgetItem(self.tree, [group or "—", "", "", "", ""]) if group else None
                )
                root = parent if parent else self.tree.invisibleRootItem()
                for s in members:
                    item = QTreeWidgetItem(
                        root,
                        [
                            s.label,
                            s.sponsor,
                            s.host,
                            f"{s.distance_km:.0f} km" if s.distance_km is not None else "—",
                            f"{s.latency_ms:.0f} ms" if s.latency_ms is not None else "—",
                        ],
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, s.host)
                if parent:
                    parent.setExpanded(True)
            self.tree.restore_selection(remembered)
        finally:
            self.tree.blockSignals(False)

    def _selected_servers(self) -> list[Server]:
        """Selected endpoints in the order they were selected."""
        return ordered_servers(self.tree.selected_hosts(), self.servers)

    # -------------------------------------------------------------- testing
    def start_tests(self, batch: bool):
        if not self.servers and self._backend() == "demo":
            self.servers = demo_servers()
            self.refresh_server_tree()
            self.log_line("Demo mode: loaded the offline simulated server list.")
        selected = self._selected_servers()
        # Batch tests follow the selection order when something is selected;
        # otherwise they run over the whole visible list.
        servers = (selected or self._displayed_servers()) if batch else selected
        if not servers:
            if not batch and self.servers:
                servers = self._displayed_servers()[:1]
            else:
                self.log_line(
                    "No location selected — fetch ExpressVPN locations first (Servers tab)."
                )
                self.tabs.setCurrentIndex(1)
                return
        self.gauge_down.reset()
        self.gauge_up.reset()
        self.chart.clear_chart()
        self.progress_bar.setValue(0)
        self.lbl_status.setText(
            f"{tr(self.lang, 'testing')} {len(servers)} server(s), "
            f"{tr(self.lang, 'avg_of').format(n=self.spin_repeat.value())}"
        )
        self.log_line(
            f"Starting {'batch' if batch else 'single'} test: {len(servers)} server(s), "
            f"repeat={self.spin_repeat.value()}, unit={self.combo_unit.currentText()}, "
            f"connection timeout={self.spin_conn_to.value():g}s"
        )
        self._run_worker("batch" if batch or len(servers) > 1 else "single", self._payload(servers))

    def stop_tests(self):
        if self.worker:
            self.worker.cancel_event.set()
            self.log_line("Stop requested — finishing the current operation…")

    def _on_busy(self, busy: bool):
        for b in (
            self.btn_start, self.btn_fetch, self.btn_test_sel,
            self.btn_batch, self.btn_load, self.btn_download,
        ):
            b.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if not busy:
            self.lbl_status.setText(tr(self.lang, "ready"))
            self.progress_bar.setValue(100 if self.progress_bar.value() else 0)

    def _on_progress(self, phase: str, mbps: float, done: int):
        unit = self.combo_unit.currentText()
        if phase == "download":
            self.gauge_down.set_value(convert_speed(mbps, unit))
        elif phase == "upload":
            self.gauge_up.set_value(convert_speed(mbps, unit))
        if phase in ("download", "upload"):
            self.chart.push(phase, mbps)
            self.lbl_live.setText(
                f"{tr(self.lang, 'live')}: {phase} "
                f"{convert_speed(mbps, unit):.2f} {unit}  ({format_size(done)})"
            )
            self.progress_bar.setValue(50 if phase == "download" else 90)

    def _on_record(self, record: dict):
        try:
            self.history.append(record)
        except CheckerError as exc:
            self.log_line(f"✗ history: {exc}")
        self._refresh_history()
        if record.get("download_mbps") is not None:
            unit = self.combo_unit.currentText()
            self.gauge_down.set_value(convert_speed(record["download_mbps"], unit))
            self.gauge_up.set_value(convert_speed(record["upload_mbps"], unit))
            self.lbl_latency.setText(f"{tr(self.lang, 'latency')}: {record['latency_ms']} ms")
            self.lbl_server.setText(
                f"{tr(self.lang, 'jitter_server')}: {record['location']} ({record['server']})"
            )
        self.tabs.setCurrentIndex(0)

    # ------------------------------------------------------------- history
    def _refresh_history(self):
        try:
            records = self.history.load()
        except CheckerError as exc:
            self.log_line(f"✗ {exc}")
            return
        records = filter_history(
            records,
            status=self.combo_hstatus.currentText(),
            text=self.htext.text(),
            min_download=self.hmin_down.value() or None,
            max_latency=self.hmax_lat.value() or None,
        )
        unit = self.combo_unit.currentText()
        self.history_table.setSortingEnabled(False)
        self.history_table.setRowCount(0)
        for record in reversed(records):
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            down = record.get("download_mbps")
            up = record.get("upload_mbps")
            values = [
                str(record.get("time", ""))[:19].replace("T", " "),
                str(record.get("location", "")),
                str(record.get("server", "")),
                f"{convert_speed(down, unit):.2f} {unit}" if down is not None else "—",
                f"{convert_speed(up, unit):.2f} {unit}" if up is not None else "—",
                f"{record['latency_ms']}" if record.get("latency_ms") is not None else "—",
                str(record.get("status", "")),
                str(record.get("connection", "")),
                str(record.get("error", "")),
            ]
            for col, value in enumerate(values):
                item = HistoryItem(value)
                if col in (3, 4, 5):
                    key = {3: "download_mbps", 4: "upload_mbps", 5: "latency_ms"}[col]
                    metric = record.get(key)
                    item.setData(
                        Qt.ItemDataRole.UserRole, float(metric) if metric is not None else -1
                    )
                if record.get("status") == "error":
                    color = "#fb7185"
                elif record.get("connection") == "direct":
                    color = "#fbbf24"
                else:
                    color = "#34d399" if col in (3, 4, 6) else "#93c5fd"
                item.setForeground(QColor(color))
                self.history_table.setItem(row, col, item)
        self.history_table.setSortingEnabled(True)

    def _clear_history(self):
        self.history.clear()
        self._refresh_history()
        self.log_line("History cleared.")

    def _export_history(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr(self.lang, "export"), "history.json", "JSON (*.json)"
        )
        if path:
            Path(path).write_text(
                json.dumps(self.history.load(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self.log_line(f"History exported to {path}")

    # ---------------------------------------------------------------- logs
    def log_line(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {message}")

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr(self.lang, "save_log"), "speedchecker.log", "Log (*.log *.txt)"
        )
        if path:
            Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    app = QApplication(list(argv) if argv else sys.argv[:1])
    app.setApplicationName("SpeedChecker")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
