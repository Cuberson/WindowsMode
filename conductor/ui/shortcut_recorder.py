""""Record shortcut" field: click, press a chord, it validates before saving
(§3.6). Port of ShortcutRecorder.swift."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..core.models import Hotkey
from ..services.hotkey import HotkeyMonitor, hotkey_display
from . import theme


class ShortcutRecorder(QWidget):
    def __init__(self, get_hotkey: Callable[[], Hotkey],
                 set_hotkey: Callable[[Hotkey], None], parent=None):
        super().__init__(parent)
        self._get = get_hotkey
        self._set = set_hotkey
        self._recording = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._button = QPushButton()
        self._button.setFixedHeight(28)
        self._button.setMinimumWidth(130)
        self._button.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,16); border: none; border-radius: 8px;"
            " color: white; font-family: 'Segoe UI'; font-size: 13px; padding: 4px 10px; }"
            "QPushButton:hover { background: rgba(255,255,255,26); }"
        )
        self._button.clicked.connect(self._toggle)
        lay.addWidget(self._button)

        self._message = QLabel("")
        self._message.setStyleSheet("color: #FF6B6B; font-size: 11px;")
        lay.addWidget(self._message)
        lay.addStretch(1)
        self._refresh_label()

    def _refresh_label(self) -> None:
        if self._recording:
            self._button.setText("Press a chord…")
        else:
            self._button.setText(hotkey_display(self._get()))

    def _toggle(self) -> None:
        if self._recording:
            self._end()
        else:
            self._begin()

    def _begin(self) -> None:
        self._recording = True
        self._message.setText("")
        self._refresh_label()
        HotkeyMonitor.shared().begin_recording(self._captured)

    def _end(self) -> None:
        self._recording = False
        HotkeyMonitor.shared().end_recording()
        self._refresh_label()

    def _captured(self, hotkey: Hotkey) -> None:
        self._recording = False
        if hotkey.modifiers == 0 and hotkey.keyCode != 0x1B:
            self._message.setText("Add at least one modifier (Ctrl Shift Alt Win)")
        elif HotkeyMonitor.can_register(hotkey):
            self._set(hotkey)
            self._message.setText("")
        else:
            self._message.setText(f"{hotkey_display(hotkey)} is taken by another app")
        self._refresh_label()
