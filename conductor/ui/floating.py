"""FloatingPanel — the port of FloatingPanel.swift: non-activating,
always-on-top, taskbar-hidden, transparent window hosting the glass widgets."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from . import theme


class FloatingPanel(QWidget):
    def __init__(self, content: QWidget, draggable: bool = False,
                 activatable: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._content = content
        self._draggable = draggable
        self._activatable = activatable
        self._drag_offset: Optional[QPoint] = None

        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        if not activatable:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if not activatable:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowOpacity(1.0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)

        self._backdrop = theme.apply_backdrop(self, acrylic=True)

    # -- dragging (movableByWindowBackground) ----------------------------

    def mousePressEvent(self, event) -> None:
        if self._draggable and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.moved.emit()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    moved = Signal()

    # -- sizing ---------------------------------------------------------

    def fit_to_content(self, anchor_top_center: bool = False) -> None:
        top = self.y()
        hint = self._content.sizeHint()
        size = hint if hint.width() > 0 and hint.height() > 0 else self._content.minimumSizeHint()
        w = max(size.width(), 1)
        h = max(size.height(), 1)
        x = self.x()
        if anchor_top_center:
            x = self.x() + self.width() // 2 - w // 2
        self.setGeometry(x, top, w, h)

    # -- show / hide with a fade ----------------------------------------

    def show_animated(self, target_opacity: float = 1.0) -> None:
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        anim = theme.spring_animation(self, b"windowOpacity", 220)
        anim.setStartValue(0.0)
        anim.setEndValue(target_opacity)
        self._anim = anim
        anim.start()

    def hide_animated(self, done=None) -> None:
        anim = theme.spring_animation(self, b"windowOpacity", 180)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        if done:
            anim.finished.connect(lambda: (self.hide(), done()))
        else:
            anim.finished.connect(self.hide)
        self._anim = anim
        anim.start()

    def set_opacity(self, value: float) -> None:
        self.setWindowOpacity(value)
