"""Tiny vector icons drawn with QPainter — the port of AgentIcons.swift and
the SF Symbols used across the pill/overlay."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QBrush


def draw_icon(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, max(1.2, rect.width() / 9))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    fn = _ICONS.get(name)
    if fn:
        fn(painter, rect, color, pen)
    painter.restore()


def _mic(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    cx = r.center().x()
    top = r.top() + r.height() * 0.06
    body_w = r.width() * 0.42
    body_h = r.height() * 0.52
    p.drawRoundedRect(QRectF(cx - body_w / 2, top, body_w, body_h), body_w / 2, body_w / 2)
    arc = QRectF(cx - r.width() * 0.34, top + body_h * 0.45, r.width() * 0.68, r.height() * 0.55)
    p.drawArc(arc, -16 * 45, -16 * 90)
    p.drawLine(QPointF(cx, r.bottom() - r.height() * 0.02),
               QPointF(cx, top + body_h + r.height() * 0.22))


def _speaker(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    body = QBrush(c)
    p.setBrush(body)
    poly = [
        QPointF(x + w * 0.12, y + h * 0.38),
        QPointF(x + w * 0.36, y + h * 0.38),
        QPointF(x + w * 0.60, y + h * 0.16),
        QPointF(x + w * 0.60, y + h * 0.84),
        QPointF(x + w * 0.36, y + h * 0.62),
        QPointF(x + w * 0.12, y + h * 0.62),
    ]
    from PySide6.QtGui import QPolygonF
    p.drawPolygon(QPolygonF(poly))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(x + w * 0.52, y + h * 0.22, w * 0.36, h * 0.56), -16 * 60, -16 * 120)
    p.drawArc(QRectF(x + w * 0.52, y + h * 0.06, w * 0.52, h * 0.88), -16 * 55, -16 * 130)


def _question(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    p.setBrush(QBrush(c))
    p.drawEllipse(r)
    p.setPen(QPen(QColor(0x1C, 0x1C, 0x22), pen.widthF() * 1.1))
    f = p.font()
    f.setPixelSize(int(r.height() * 0.72))
    f.setBold(True)
    p.setFont(f)
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "?")


def _warning(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    p.setBrush(QBrush(c))
    p.drawEllipse(r)
    p.setPen(QPen(QColor(0x1C, 0x1C, 0x22), pen.widthF() * 1.1))
    p.drawLine(QPointF(r.center().x(), r.top() + r.height() * 0.24),
               QPointF(r.center().x(), r.center().y() + r.height() * 0.02))
    p.drawPoint(QPointF(r.center().x(), r.bottom() - r.height() * 0.24))


def _enter(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.drawLine(QPointF(x + w * 0.72, y + h * 0.12), QPointF(x + w * 0.72, y + h * 0.52))
    p.drawLine(QPointF(x + w * 0.72, y + h * 0.52), QPointF(x + w * 0.22, y + h * 0.52))
    p.drawLine(QPointF(x + w * 0.38, y + h * 0.32), QPointF(x + w * 0.20, y + h * 0.52))
    p.drawLine(QPointF(x + w * 0.38, y + h * 0.72), QPointF(x + w * 0.20, y + h * 0.52))


def _close(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    m = r.width() * 0.28
    p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
    p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))


def _terminal(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 2, 2)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.drawLine(QPointF(x + w * 0.22, y + h * 0.32), QPointF(x + w * 0.42, y + h * 0.5))
    p.drawLine(QPointF(x + w * 0.42, y + h * 0.5), QPointF(x + w * 0.22, y + h * 0.68))
    p.drawLine(QPointF(x + w * 0.48, y + h * 0.70), QPointF(x + w * 0.74, y + h * 0.70))


def _doc(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.drawRoundedRect(QRectF(x + w * 0.18, y + h * 0.08, w * 0.64, h * 0.84), 2, 2)
    for i, frac in enumerate((0.32, 0.48, 0.64)):
        p.drawLine(QPointF(x + w * 0.30, y + h * frac), QPointF(x + w * 0.70, y + h * frac))


def _reply(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.drawLine(QPointF(x + w * 0.32, y + h * 0.22), QPointF(x + w * 0.14, y + h * 0.46))
    p.drawLine(QPointF(x + w * 0.14, y + h * 0.46), QPointF(x + w * 0.32, y + h * 0.70))
    p.drawLine(QPointF(x + w * 0.16, y + h * 0.46), QPointF(x + w * 0.86, y + h * 0.46))
    p.drawRoundedRect(QRectF(x + w * 0.44, y + h * 0.30, w * 0.44, h * 0.46), 3, 3)


def _stop(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    m = r.width() * 0.22
    p.setBrush(QBrush(c))
    p.drawRoundedRect(r.adjusted(m, m, -m, -m), 2, 2)


def _check(p: QPainter, r: QRectF, c: QColor, pen: QPen) -> None:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.drawLine(QPointF(x + w * 0.22, y + h * 0.52), QPointF(x + w * 0.42, y + h * 0.72))
    p.drawLine(QPointF(x + w * 0.42, y + h * 0.72), QPointF(x + w * 0.78, y + h * 0.28))


_ICONS = {
    "mic": _mic,
    "speaker": _speaker,
    "question": _question,
    "warning": _warning,
    "enter": _enter,
    "close": _close,
    "terminal": _terminal,
    "doc": _doc,
    "reply": _reply,
    "stop": _stop,
    "check": _check,
}
