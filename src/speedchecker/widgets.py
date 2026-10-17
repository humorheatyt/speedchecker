"""Custom painted widgets: speedometer gauge + live line chart."""

import math
from collections import deque

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class GaugeWidget(QWidget):
    """Round speedometer: coloured arc + needle + big digital readout."""

    def __init__(self, title: str = "", color: str = "#22d3ee", parent=None):
        super().__init__(parent)
        self._title, self._color = title, QColor(color)
        self._value, self._max = 0.0, 100.0
        self._unit = "Mbps"
        self.setMinimumSize(230, 230)

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_unit(self, unit: str) -> None:
        self._unit = unit
        self.update()

    def set_value(self, value: float) -> None:
        self._value = max(0.0, value)
        if self._value > self._max:  # adaptive scale
            self._max = self._value * 1.25
        self.update()

    def reset(self) -> None:
        self._value, self._max = 0.0, 100.0
        self.update()

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
            label = f"{self._max * i / 10:.0f}"
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
            if len(series) < 2:
                continue
            painter.setPen(QPen(QColor(color), 2))
            step = self.width() / 119
            points = [
                (int(i * step), int(self.height() - 6 - (v / peak) * (self.height() - 14)))
                for i, v in enumerate(series)
            ]
            for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
                painter.drawLine(x1, y1, x2, y2)
        painter.setPen(QColor("#64748b"))
        painter.drawText(8, 16, f"max ≈ {peak / 1.15:.1f} Mbps   ● download   ● upload")
