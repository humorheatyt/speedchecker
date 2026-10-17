"""Custom widgets: speedometer gauge, live line chart, and the location tree."""

import math
from collections import deque

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget


class ServerTree(QTreeWidget):
    """Location tree with ordered, group-aware selection.

    * Selecting a group header (country/sponsor/letter) selects every endpoint
      inside it, and Ctrl-clicking it toggles the whole group.
    * :meth:`selected_hosts` returns endpoints in the exact order they were
      selected — that is the order tests are run in.
    * A selection survives rebuilding the tree (sort/group/search), including
      endpoints that are temporarily hidden by the search filter.
    """

    HOST_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, parent=None):
        super().__init__(parent)
        # Selected endpoints in selection order, including ones hidden by a filter.
        self._wanted: list[str] = []
        self._selected_items: list[QTreeWidgetItem] = []
        self._guard = False
        self.itemSelectionChanged.connect(self._on_selection_changed)

    # -- structure --------------------------------------------------------
    def host_of(self, item: QTreeWidgetItem | None) -> str:
        if item is None:
            return ""
        value = item.data(0, self.HOST_ROLE)
        return value if isinstance(value, str) else ""

    def is_group(self, item: QTreeWidgetItem | None) -> bool:
        return item is not None and item.childCount() > 0 and not self.host_of(item)

    def item_hosts(self, item: QTreeWidgetItem | None) -> list[str]:
        if item is None:
            return []
        if self.is_group(item):
            return [
                host
                for index in range(item.childCount())
                if (host := self.host_of(item.child(index)))
            ]
        host = self.host_of(item)
        return [host] if host else []

    def _items_in_order(self):
        for index in range(self.topLevelItemCount()):
            top = self.topLevelItem(index)
            yield top
            for child_index in range(top.childCount()):
                yield top.child(child_index)

    def present_hosts(self) -> list[str]:
        return [host for item in self._items_in_order() if (host := self.host_of(item))]

    def _selected_host_set(self) -> set[str]:
        return {host for item in self.selectedItems() for host in self.item_hosts(item)}

    def _set_children(self, item: QTreeWidgetItem, selected: bool) -> None:
        for index in range(item.childCount()):
            item.child(index).setSelected(selected)

    # -- public API -------------------------------------------------------
    def selected_hosts(self) -> list[str]:
        """Selected endpoints, in the order they were selected."""
        present = set(self.present_hosts())
        return [host for host in self._wanted if host in present]

    def remember_selection(self, valid_hosts=None) -> list[str]:
        """Selection to carry over a rebuild (hidden endpoints included)."""
        wanted = list(dict.fromkeys(self._wanted))
        if valid_hosts is not None:
            wanted = [host for host in wanted if host in valid_hosts]
        return wanted

    def restore_selection(self, hosts) -> None:
        """Select the given hosts in order; keep those not currently shown."""
        self._wanted = list(dict.fromkeys(hosts))
        visible = set(self.present_hosts())
        selected = {host for host in self._wanted if host in visible}
        self._guard = True
        try:
            for item in self._items_in_order():
                host = self.host_of(item)
                if host:
                    item.setSelected(host in selected)
            self._selected_items = [item for item in self._items_in_order() if item.isSelected()]
        finally:
            self._guard = False

    # -- selection bookkeeping -------------------------------------------
    def _on_selection_changed(self) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            # QTreeWidgetItem is not hashable in PyQt6 — track identity.
            before = {id(item) for item in self._selected_items}
            current = {id(item) for item in self.selectedItems()}
            items = list(self._items_in_order())
            added = [item for item in items if id(item) in current and id(item) not in before]
            removed = [item for item in self._selected_items if id(item) not in current]
            # A group header toggles its whole group.
            for item in added:
                if self.is_group(item):
                    self._set_children(item, True)
            for item in removed:
                if self.is_group(item):
                    keep = {id(child) for child in added}
                    for index in range(item.childCount()):
                        child = item.child(index)
                        if id(child) not in keep:
                            child.setSelected(False)
            current = {id(item) for item in self.selectedItems()}
            selected = self._selected_host_set()
            present = set(self.present_hosts())
            # Visible hosts that were deselected leave the order; hidden
            # selections are not affected by clicks on visible items.
            self._wanted = [
                host for host in self._wanted if host not in present or host in selected
            ]
            for item in items:
                if id(item) in current and id(item) not in before:
                    for host in self.item_hosts(item):
                        if host in selected and host not in self._wanted:
                            self._wanted.append(host)
            # Keyboard/programmatic changes (Ctrl+A, ranges) fall back to the
            # visible list order for endpoints that were not seen above.
            for host in self.present_hosts():
                if host in selected and host not in self._wanted:
                    self._wanted.append(host)
            self._selected_items = [item for item in items if id(item) in current]
        finally:
            self._guard = False


class GaugeWidget(QWidget):
    """Round speedometer: coloured arc + needle + big digital readout."""

    def __init__(self, title: str = "", color: str = "#22d3ee", parent=None):
        super().__init__(parent)
        self._title, self._color = title, QColor(color)
        self._value, self._max = 0.0, 100.0
        self._unit = "Mbps"
        self._has_value = False
        self._low_samples = 0
        self.setMinimumSize(230, 230)

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_unit(self, unit: str) -> None:
        self._unit = unit
        self.update()

    @staticmethod
    def _scale_for(value: float) -> float:
        """Choose a readable 1/2/5 scale with headroom above the needle."""
        if value <= 0 or not math.isfinite(value):
            return 100.0
        target = value / 0.75
        magnitude = 10 ** math.floor(math.log10(target))
        normalized = target / magnitude
        step = 1 if normalized <= 1 else 2 if normalized <= 2 else 5 if normalized <= 5 else 10
        return max(step * magnitude, value)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, value)
        if not self._has_value:
            self._max = self._scale_for(self._value)
            self._has_value = True
            self._low_samples = 0
        elif self._value > self._max:
            self._max = self._scale_for(self._value)
            self._low_samples = 0
        elif self._value < self._max * 0.25:
            # Shrink only after several low samples to avoid a twitchy needle
            # when measured speed varies around the current scale.
            self._low_samples += 1
            if self._low_samples >= 4:
                self._max = self._scale_for(self._value)
                self._low_samples = 0
        else:
            self._low_samples = 0
        self.update()

    def reset(self) -> None:
        self._value, self._max = 0.0, 100.0
        self._has_value = False
        self._low_samples = 0
        self.update()

    def _tick_label(self, value: float) -> str:
        if self._max >= 100:
            return f"{value:.0f}"
        if self._max >= 10:
            return f"{value:.1f}".rstrip("0").rstrip(".")
        if self._max >= 1:
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{value:.3g}"

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 16
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        center = rect.center()
        radius = side / 2

        # background track (start at 225°, sweeping clockwise 270°)
        painter.setPen(QPen(QColor("#1e293b"), 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, int(225 * 16), int(-270 * 16))

        fraction = min(self._value / self._max, 1.0) if self._max else 0.0
        painter.setPen(QPen(self._color, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if fraction > 0:
            painter.drawArc(rect, int(225 * 16), int(-270 * fraction * 16))

        # ticks
        painter.setPen(QPen(QColor("#64748b"), 2))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for i in range(11):
            angle = math.radians(225 - i * 27)
            inner = radius - 26
            x1, y1 = center.x() + inner * math.cos(angle), center.y() - inner * math.sin(angle)
            x2, y2 = (
                center.x() + (radius - 14) * math.cos(angle),
                center.y() - (radius - 14) * math.sin(angle),
            )
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            label = self._tick_label(self._max * i / 10)
            lx, ly = (
                center.x() + (radius - 42) * math.cos(angle),
                center.y() - (radius - 42) * math.sin(angle),
            )
            painter.drawText(int(lx) - 14, int(ly) - 6, 28, 12, Qt.AlignmentFlag.AlignCenter, label)

        # needle
        angle = math.radians(225 - fraction * 270)
        painter.setPen(QPen(QColor("#f8fafc"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        nx, ny = (
            center.x() + (radius - 34) * math.cos(angle),
            center.y() - (radius - 34) * math.sin(angle),
        )
        painter.drawLine(int(center.x()), int(center.y()), int(nx), int(ny))
        painter.setBrush(QColor("#f8fafc"))
        painter.drawEllipse(center, 6, 6)

        # texts (value below the hub, title under the unit — no overlaps)
        painter.setPen(QColor("#f8fafc"))
        font.setPointSize(26)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            int(rect.left()),
            int(center.y() + radius * 0.38),
            int(rect.width()),
            34,
            Qt.AlignmentFlag.AlignCenter,
            f"{self._value:.2f}",
        )
        painter.setPen(QColor("#94a3b8"))
        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(
            int(rect.left()),
            int(center.y() + radius * 0.38) + 36,
            int(rect.width()),
            20,
            Qt.AlignmentFlag.AlignCenter,
            self._unit,
        )
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            int(rect.left()),
            int(center.y() + radius * 0.38) + 58,
            int(rect.width()),
            22,
            Qt.AlignmentFlag.AlignCenter,
            self._title,
        )


class LiveChart(QWidget):
    """Scrolling live-speed chart for download/upload samples."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.download: deque[float] = deque(maxlen=120)
        self.upload: deque[float] = deque(maxlen=120)
        self.setMinimumHeight(110)

    def push(self, phase: str, mbps: float) -> None:
        (self.download if phase == "download" else self.upload).append(mbps)
        self.update()

    def clear_chart(self) -> None:
        self.download.clear()
        self.upload.clear()
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1220"))
        painter.setPen(QPen(QColor("#1e293b"), 1))
        for i in range(1, 4):
            y = self.height() * i // 4
            painter.drawLine(0, y, self.width(), y)
        peak = max([*self.download, *self.upload, 10.0]) * 1.15
        for series, color in ((self.download, "#22d3ee"), (self.upload, "#a78bfa")):
            if not series:
                continue
            painter.setPen(QPen(QColor(color), 2))
            step = self.width() / max(1, len(series) - 1)
            points = [
                (int(i * step), int(self.height() - 6 - (v / peak) * (self.height() - 14)))
                for i, v in enumerate(series)
            ]
            if len(points) == 1:
                painter.setBrush(QColor(color))
                painter.drawEllipse(points[0][0] - 3, points[0][1] - 3, 6, 6)
            else:
                for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
                    painter.drawLine(x1, y1, x2, y2)
                painter.setBrush(QColor(color))
                painter.drawEllipse(points[-1][0] - 3, points[-1][1] - 3, 6, 6)
        painter.setPen(QColor("#64748b"))
        painter.drawText(8, 16, f"max ≈ {peak / 1.15:.1f} Mbps   ● download   ● upload")
