"""§5.2 — the 360-pt glass board of session cards, draggable by background.
Port of SessionsOverlayView.swift."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from ..core.models import Session, SessionStatus
from ..core.stores import SessionStore, format_elapsed
from . import theme
from .icons import draw_icon


def status_color(status: SessionStatus) -> QColor:
    return {
        SessionStatus.running: theme.ACCENT,
        SessionStatus.done: theme.GREEN,
        SessionStatus.needsInput: theme.ORANGE,
        SessionStatus.failed: theme.RED,
        SessionStatus.cancelled: theme.GRAY,
    }.get(status, theme.GRAY)


class StatusDot(QWidget):
    def __init__(self, status: SessionStatus, parent=None):
        super().__init__(parent)
        self.status = status
        self.setFixedSize(10, 10)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(status_color(self.status))
        p.drawEllipse(1, 1, 8, 8)
        p.end()


class Shimmer(QWidget):
    """1-pt shimmer along the bottom edge of a running card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self._phase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1600)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_value)
        if not theme.reduce_motion():
            self._anim.start()

    def _on_value(self, v) -> None:
        self._phase = float(v)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        band = max(24, int(w * 0.4))
        x = int((self._phase * 1.4 - 0.4) * w)
        color = QColor(theme.ACCENT.red(), theme.ACCENT.green(), theme.ACCENT.blue(), 180)
        p.setPen(QPen(color, 1))
        p.drawLine(x, 0, x + band, 0)
        p.end()


class IconButton(QFrame):
    def __init__(self, icon: str, label: str, on_click: Callable[[], None], parent=None):
        super().__init__(parent)
        self._icon = icon
        self._label = label
        self._on_click = on_click
        self.setToolTip(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(26, 22)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_icon(p, self._icon, QRectF(6, 5, 12, 12), theme.SECONDARY)
        p.end()


class SessionCard(QFrame):
    def __init__(self, session: Session, now_provider: Callable[[], float],
                 on_open: Callable[[], None], on_log: Callable[[], None],
                 on_reply: Callable[[str], None], on_stop: Callable[[], None],
                 on_dismiss: Callable[[], None], parent=None):
        super().__init__(parent)
        self.session = session
        self._now = now_provider
        self._reply_cb = on_reply
        self._replying = False
        self.setObjectName("card")
        self.setStyleSheet(
            "QFrame#card { background: rgba(255,255,255,14); border-radius: 14px; }"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)

        # Row 1: status dot · project · agent capsule · time
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._dot = StatusDot(session.status)
        row1.addWidget(self._dot)
        name = QLabel(session.projectName)
        name.setFont(theme.font(15, QFont.Weight.DemiBold))
        name.setStyleSheet("color: white;")
        row1.addWidget(name)
        capsule = QFrame()
        capsule.setStyleSheet("background: rgba(255,255,255,28); border-radius: 9px;")
        cap_lay = QHBoxLayout(capsule)
        cap_lay.setContentsMargins(7, 2, 7, 2)
        cap_lay.setSpacing(4)
        agent_label = QLabel(session.agent.display_name)
        agent_label.setFont(theme.font(11))
        agent_label.setStyleSheet("color: rgba(235,235,240,190);")
        cap_lay.addWidget(agent_label)
        row1.addWidget(capsule)
        row1.addStretch(1)
        self._time = QLabel("")
        self._time.setFont(theme.font(11))
        self._time.setStyleSheet("color: rgba(235,235,240,120);")
        row1.addWidget(self._time)
        self._layout.addLayout(row1)

        self._task = QLabel(session.task)
        self._task.setFont(theme.font(13))
        self._task.setStyleSheet("color: rgba(235,235,240,190);")
        self._task.setWordWrap(True)
        self._layout.addWidget(self._task)

        self._activity = QLabel(session.activity)
        self._activity.setFont(theme.font(11))
        mono = theme.font(11)
        mono.setFamily("Consolas")
        self._activity.setFont(mono)
        self._activity.setStyleSheet("color: rgba(235,235,240,190);")
        self._layout.addWidget(self._activity)

        self._needs = QLabel("Needs input — open it and continue with --resume")
        self._needs.setFont(theme.font(11))
        self._needs.setStyleSheet("color: #FFB340;")
        self._layout.addWidget(self._needs)

        self._reply_edit = QLineEdit()
        self._reply_edit.setPlaceholderText("Follow-up…")
        self._reply_edit.setFont(theme.font(12))
        self._reply_edit.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,18); border: 1px solid rgba(255,255,255,36);"
            " border-radius: 8px; padding: 4px 8px; color: white; }"
        )
        self._reply_edit.returnPressed.connect(self._submit_reply)
        self._layout.addWidget(self._reply_edit)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(6)
        self._actions.addWidget(IconButton("terminal", "Open", on_open))
        self._actions.addWidget(IconButton("doc", "Show log", on_log))
        if session.status == SessionStatus.running or session.agentSessionID:
            self._actions.addWidget(IconButton("reply", "Reply", self._toggle_reply))
        if session.status == SessionStatus.running:
            self._actions.addWidget(IconButton("stop", "Stop", on_stop))
        else:
            self._actions.addWidget(IconButton("close", "Dismiss", on_dismiss))
        self._actions.addStretch(1)
        self._actions_widget = QWidget()
        self._actions_widget.setLayout(self._actions)
        self._layout.addWidget(self._actions_widget)

        if session.status == SessionStatus.running:
            self._shimmer = Shimmer()
            self._layout.addWidget(self._shimmer)

        self._apply_state()

    def _toggle_reply(self) -> None:
        self._replying = not self._replying
        self._apply_state()
        if self._replying:
            self._reply_edit.setFocus()

    def _submit_reply(self) -> None:
        t = self._reply_edit.text().strip()
        self._reply_edit.clear()
        self._replying = False
        self._apply_state()
        if t:
            self._reply_cb(t)

    def _apply_state(self) -> None:
        self._reply_edit.setVisible(self._replying)
        self._dot.status = self.session.status
        self._needs.setVisible(self.session.status == SessionStatus.needsInput)
        self._activity.setVisible(bool(self.session.activity) and self.session.status == SessionStatus.running)
        self._actions_widget.setVisible(self.underMouse() or self._replying)

    def enterEvent(self, event) -> None:
        self._actions_widget.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._replying:
            self._actions_widget.setVisible(False)
        super().leaveEvent(event)

    def refresh_labels(self) -> None:
        s = self.session
        self._task.setText(s.task)
        self._activity.setText(s.activity)
        if s.status == SessionStatus.running:
            self._time.setText(format_elapsed(self._now() - s.startedAt.timestamp()))
        elif s.finishedAt:
            ago = self._now() - s.finishedAt.timestamp()
            self._time.setText("just now" if ago < 60 else f"{format_elapsed(ago)} ago")
        else:
            self._time.setText("")
        self._apply_state()


class SessionsOverlay(QWidget):
    """Header + scrolling card list, 360 pt wide."""

    def __init__(self, store: SessionStore, chord_text: str,
                 on_close: Callable[[], None],
                 on_open: Callable[[Session], None],
                 on_log: Callable[[Session], None],
                 on_reply: Callable[[Session, str], None],
                 on_stop: Callable[[Session], None],
                 on_dismiss: Callable[[Session], None], parent=None):
        super().__init__(parent)
        self.store = store
        self.chord_text = chord_text
        self._on_close = on_close
        self._on_open = on_open
        self._on_log = on_log
        self._on_reply = on_reply
        self._on_stop = on_stop
        self._on_dismiss = on_dismiss
        self._cards: dict[str, SessionCard] = {}

        self.setFixedWidth(360)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Sessions")
        title.setFont(theme.font(13, QFont.Weight.DemiBold))
        title.setStyleSheet("color: rgba(235,235,240,190);")
        header.addWidget(title)
        self._count = QLabel("")
        self._count.setFont(theme.font(11, QFont.Weight.DemiBold))
        self._count.setStyleSheet(
            "background: rgba(76,194,255,38); color: #4CC2FF; border-radius: 9px;"
            " padding: 1px 6px;"
        )
        header.addWidget(self._count)
        header.addStretch(1)
        close_btn = IconButton("close", "Close", on_close)
        header.addWidget(close_btn)
        self._layout.addLayout(header)

        self._empty = QLabel(f"Hold {chord_text} and say what you need.")
        self._empty.setFont(theme.font(13))
        self._empty.setStyleSheet("color: rgba(235,235,240,120);")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._empty)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QWidget#cards { background: transparent; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,40); border-radius: 2px; }"
        )
        self._cards_host = QWidget()
        self._cards_host.setObjectName("cards")
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 4, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._cards_host)
        self._layout.addWidget(self._scroll)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh_times)
        self._tick.start()

        store.add_listener(self.rebuild)
        self.rebuild()

    @staticmethod
    def _now() -> float:
        import time
        return time.time()

    def rebuild(self) -> None:
        # Clear current cards (keep the trailing stretch).
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()

        visible = self.store.visible
        self._empty.setVisible(not visible)
        self._scroll.setVisible(bool(visible))
        running = len(self.store.running)
        self._count.setText(str(running) if running else "")
        self._count.setVisible(bool(running))

        for s in visible:
            card = SessionCard(
                s, self._now,
                on_open=lambda sess=s: self._on_open(sess),
                on_log=lambda sess=s: self._on_log(sess),
                on_reply=lambda t, sess=s: self._on_reply(sess, t),
                on_stop=lambda sess=s: self._on_stop(sess),
                on_dismiss=lambda sess=s: self._on_dismiss(sess),
            )
            self._cards[s.id] = card
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    def _refresh_times(self) -> None:
        for card in self._cards.values():
            try:
                card.refresh_labels()
            except RuntimeError:
                pass

    def sizeHint(self):
        from PySide6.QtCore import QSize
        h = 88
        for card in self._cards.values():
            h += card.sizeHint().height() + 8
        return QSize(360, min(max(h, 88), 560))
