"""§5.1 — the 320 pt listening pill: transcript wraps to max 3 lines, newest
words kept visible. Port of ListeningPillView.swift (custom-painted)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..services.coordinator import PillModel, PillState
from . import theme
from .icons import draw_icon


class ListeningPill(QWidget):
    WIDTH = 320
    MIN_HEIGHT = 56

    def __init__(self, model: PillModel, parent=None):
        super().__init__(parent)
        self.model = model
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(self.MIN_HEIGHT)
        model.add_listener(self._on_model)

    def _on_model(self) -> None:
        if self.model.state in (PillState.listening, PillState.thinking, PillState.speaking):
            if not self._timer.isActive():
                self._t = 0.0
                self._timer.start()
        else:
            self._timer.stop()
        self.updateGeometry()
        self.update()

    def _tick(self) -> None:
        self._t += 0.08
        self.update()

    def sizeHint(self):
        return self._ideal_size()

    def minimumSizeHint(self):
        return self._ideal_size()

    def _ideal_size(self):
        h = self.MIN_HEIGHT
        text = self._primary_text()
        if self.model.visible and text:
            lines = max(1, min(3, (len(text) // 46) + 1))
            h = max(h, 24 + lines * 20 + (20 if self.model.secondary else 0))
        return QSize(self.WIDTH, int(h))

    # -- painting -------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        theme.glass_paint(p, rect, radius=28)

        if not self.model.visible:
            p.end()
            return

        accent = theme.ACCENT
        leading_w = 18
        trailing_w = 18
        x = 16.0
        cy = rect.center().y()
        state = self.model.state

        # Leading indicator -----------------------------------------------
        lead = QRectF(x, cy - 8, leading_w, 16)
        if state == PillState.listening:
            scale = 1.0 + float(self.model.level) * 0.9
            r = 6.0 * scale
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawEllipse(QRectF(lead.center().x() - r, lead.center().y() - r, 2 * r, 2 * r))
        elif state == PillState.thinking:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                opacity = 0.3 + 0.7 * abs(((self._t * 1.4 + i * 0.15) % 1.0) - 0.5) * 2
                p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), int(255 * opacity)))
                p.drawEllipse(QRectF(lead.left() + i * 6, cy - 2, 4, 4))
        elif state == PillState.speaking:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            for i in range(4):
                phase = self._t * 3.0 + i * 0.7
                h = 4 + 8 * abs((phase % 1.0) - 0.5) * 2
                p.drawRoundedRect(QRectF(lead.left() + i * 4, cy - h / 2, 2, h), 1, 1)
        elif state == PillState.clarify:
            draw_icon(p, "question", lead, accent)
        elif state == PillState.error:
            draw_icon(p, "warning", lead, theme.RED)

        # Text column ------------------------------------------------------
        text_x = x + leading_w + 12
        text_w = self.width() - text_x - trailing_w - 28
        primary = self._primary_text()
        p.setFont(theme.font(15, QFont.Weight.Medium))
        dim = (not self.model.transcript and state == PillState.listening)
        p.setPen(theme.SECONDARY if dim else theme.TEXT)
        text_rect = QRectF(text_x, 0, text_w, self.height())
        p.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                                  | Qt.TextFlag.TextWordWrap), primary)

        if self.model.secondary:
            p.setFont(theme.font(12))
            p.setPen(theme.RED if state == PillState.error else theme.SECONDARY)
            sec_rect = QRectF(text_x, self.height() - 30, text_w, 18)
            p.drawText(sec_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                                    | Qt.TextFlag.TextSingleLine), self.model.secondary)

        # Trailing ---------------------------------------------------------
        tr = QRectF(self.width() - trailing_w - 16, cy - 8, trailing_w, 16)
        if self.model.fallback_badge:
            draw_icon(p, "speaker", tr, theme.TERTIARY)
        elif state == PillState.listening:
            draw_icon(p, "mic", tr, theme.SECONDARY)
        elif state == PillState.speaking:
            draw_icon(p, "speaker", tr, theme.SECONDARY)
        elif state == PillState.clarify:
            draw_icon(p, "enter", tr, theme.SECONDARY)
        p.end()

    def _primary_text(self) -> str:
        state = self.model.state
        t = self.model.transcript
        if state == PillState.listening and not t:
            return "Listening…"
        if state == PillState.thinking and not t:
            return "Thinking…"
        if len(t) > 130:
            return "…" + t[-130:]
        return t
