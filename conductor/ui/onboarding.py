"""§6 — six steps, each with a real check. Port of OnboardingView.swift."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import securestore
from ..core.models import AgentKind, Project
from ..core.stores import ProjectRegistry
from ..services.hotkey import HotkeyMonitor, hotkey_display
from ..services.speech import SpeechService
from ..services.voice import FishAudio
from . import theme
from .shortcut_recorder import ShortcutRecorder


def _title(t: str, sub: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    l1 = QLabel(t)
    l1.setFont(theme.font(28, QFont.Weight.DemiBold))
    l1.setStyleSheet("color: white;")
    l1.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l2 = QLabel(sub)
    l2.setFont(theme.font(15))
    l2.setStyleSheet("color: rgba(235,235,240,190);")
    l2.setWordWrap(True)
    l2.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(l1)
    lay.addWidget(l2)
    return w


class CheckRow(QWidget):
    def __init__(self, label: str, detail: Optional[str] = None,
                 action: Optional[str] = None, on_action=None, parent=None):
        super().__init__(parent)
        self._state: Optional[bool] = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self._icon = QLabel("○")
        self._icon.setFixedWidth(24)
        self._icon.setStyleSheet("color: rgba(235,235,240,190); font-size: 18px;")
        lay.addWidget(self._icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        self._label = QLabel(label)
        self._label.setFont(theme.font(15))
        self._label.setStyleSheet("color: white;")
        col.addWidget(self._label)
        self._detail = QLabel(detail or "")
        self._detail.setFont(theme.font(12))
        self._detail.setStyleSheet("color: rgba(235,235,240,190);")
        self._detail.setWordWrap(True)
        col.addWidget(self._detail)
        lay.addLayout(col, 1)
        self._button = QPushButton(action or "")
        self._button.setVisible(bool(action))
        if on_action:
            self._button.clicked.connect(on_action)
        lay.addWidget(self._button)
        self.setStyleSheet("background: rgba(255,255,255,14); border-radius: 12px;")

    def set_state(self, ok: Optional[bool], detail: Optional[str] = None) -> None:
        self._state = ok
        if ok is True:
            self._icon.setText("✔")
            self._icon.setStyleSheet("color: #6CCB5F; font-size: 18px;")
            self._button.setVisible(False)
        elif ok is None:
            self._icon.setText("◌")
            self._icon.setStyleSheet("color: rgba(235,235,240,190); font-size: 18px;")
        else:
            self._icon.setText("○")
            self._icon.setStyleSheet("color: rgba(235,235,240,190); font-size: 18px;")
        if detail is not None:
            self._detail.setText(detail)

    @property
    def ok(self) -> Optional[bool]:
        return self._state


class OnboardingWindow(QDialog):
    TITLES = ["Welcome", "Permissions", "Push to talk", "Agents", "Voice", "First project"]

    def __init__(self, coordinator, on_done, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self._on_done = on_done
        self.step = 0
        self.chord_probe: Optional[int] = None
        self.chord_pressed = False
        self.chord_released = False
        self._fish_key = ""
        self._project_path: Optional[str] = None

        self.setWindowTitle("Conductor")
        self.setFixedSize(560, 620)
        self.setStyleSheet("QDialog { background: #202026; } QLabel { color: rgba(235,235,240,190); }")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        self._dots = QHBoxLayout()
        self._dots.addStretch(1)
        self._dot_labels = []
        for i in range(6):
            d = QLabel("●")
            d.setFont(theme.font(10))
            self._dots.addWidget(d)
            self._dot_labels.append(d)
        self._dots.addStretch(1)
        root.addLayout(self._dots)

        self._stack = QStackedWidget()
        self._pages = [
            self._page_welcome(),
            self._page_permissions(),
            self._page_chord(),
            self._page_agents(),
            self._page_voice(),
            self._page_project(),
        ]
        for p in self._pages:
            self._stack.addWidget(p)
        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        self._back = QPushButton("Back")
        self._back.clicked.connect(lambda: self._goto(self.step - 1))
        footer.addWidget(self._back)
        footer.addStretch(1)
        self._skip = QPushButton("Skip for now")
        self._skip.clicked.connect(self._advance)
        footer.addWidget(self._skip)
        self._next = QPushButton("Continue")
        self._next.setStyleSheet(
            "QPushButton { background: #4CC2FF; color: #10202A; border: none;"
            " border-radius: 8px; padding: 8px 18px; font-weight: 600; }"
        )
        self._next.clicked.connect(self._on_next)
        footer.addWidget(self._next)
        root.addLayout(footer)

        self._goto(0)

    # -- pages ----------------------------------------------------------

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(24)
        lay.addStretch(1)
        icon = QLabel("≋")
        icon.setFont(theme.font(44))
        icon.setStyleSheet("color: #4CC2FF;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)
        lay.addWidget(_title("Conductor",
                            "Hold a key, say what you need, and Claude Code or Codex gets to work in the background."))
        note = QLabel("Uses your existing Claude Code and Codex subscriptions. Only Fish Audio voice costs credits.")
        note.setFont(theme.font(13))
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("background: rgba(255,255,255,14); border-radius: 12px; padding: 12px;")
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    def _page_permissions(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)
        lay.addWidget(_title("Permissions", "Speech stays on this PC. No accessibility permission is needed."))
        self._mic_check = CheckRow("Microphone", action="Allow", on_action=lambda: self._open_ms_settings("privacy-microphone"))
        self._speech_check = CheckRow("Speech Recognition", detail="On-device dictation",
                                      action="Allow", on_action=lambda: self._open_ms_settings("privacy-speech"))
        lay.addWidget(self._mic_check)
        lay.addWidget(self._speech_check)
        lay.addStretch(1)
        self._mic_check.set_state(SpeechService.mic_available())
        self._speech_check.set_state(SpeechService.speech_available())
        return w

    def _page_chord(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)
        chord = hotkey_display(self.coordinator.settings.settings.pushToTalk)
        lay.addWidget(_title("Push to talk", f"Hold {chord} now. Release to finish."))
        self._press_check = CheckRow("Press captured")
        self._release_check = CheckRow("Release captured")
        lay.addWidget(self._press_check)
        lay.addWidget(self._release_check)
        rec = ShortcutRecorder(
            lambda: self.coordinator.settings.settings.pushToTalk,
            self._set_push_to_talk,
        )
        lay.addWidget(rec)
        lay.addStretch(1)
        return w

    def _page_agents(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)
        lay.addWidget(_title("Agents", "Conductor drives the CLIs you already have."))
        self._claude_check = CheckRow("Claude Code", detail="Checking…",
                                      action="Install", on_action=lambda: self._open_url("https://docs.anthropic.com/en/docs/claude-code"))
        self._codex_check = CheckRow("Codex (optional)", detail="Checking…",
                                     action="Install", on_action=lambda: self._open_url("https://github.com/openai/codex"))
        lay.addWidget(self._claude_check)
        lay.addWidget(self._codex_check)
        recheck = QPushButton("Re-check")
        recheck.clicked.connect(lambda: threading.Thread(target=self._detect_agents, daemon=True).start())
        lay.addWidget(recheck, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        threading.Thread(target=self._detect_agents, daemon=True).start()
        return w

    def _page_voice(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)
        lay.addWidget(_title("Voice", "Fish Audio speaks the replies. This is the only thing that costs credits."))
        has_fish = securestore.get(securestore.FISH_KEY) is not None
        if has_fish:
            row = CheckRow("API key stored in Credential Manager")
            row.set_state(True)
            lay.addWidget(row)
            sample = QPushButton("Hear a sample")
            sample.clicked.connect(lambda: self.coordinator.voice.speak("Hi, I'm ready."))
            lay.addWidget(sample, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            self._fish_field = QLineEdit()
            self._fish_field.setPlaceholderText("Fish Audio API key")
            self._fish_field.setEchoMode(QLineEdit.EchoMode.Password)
            lay.addWidget(self._fish_field)
            save = QPushButton("Save & test")
            save.clicked.connect(self._save_fish)
            lay.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
            hint = QLabel("Skip to use the built-in system voice.")
            hint.setFont(theme.font(12))
            lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _page_project(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(_title("First project", "Choose a folder, give it a name and a few spoken aliases."))
        self._folder_btn = QPushButton("Choose a folder…")
        self._folder_btn.clicked.connect(self._pick_folder)
        lay.addWidget(self._folder_btn)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Name")
        lay.addWidget(self._name)
        self._aliases = QLineEdit()
        self._aliases.setPlaceholderText("Aliases (comma separated)")
        lay.addWidget(self._aliases)
        self._agent = QComboBox()
        for k in AgentKind:
            self._agent.addItem(k.display_name, k)
        lay.addWidget(self._agent)
        lay.addStretch(1)
        return w

    # -- logic ----------------------------------------------------------

    def _goto(self, step: int) -> None:
        self.step = max(0, min(5, step))
        self._stack.setCurrentIndex(self.step)
        for i, d in enumerate(self._dot_labels):
            d.setStyleSheet(f"color: {'#4CC2FF' if i == self.step else 'rgba(235,235,240,40)'};")
        self._back.setVisible(self.step > 0)
        self._skip.setVisible(self.step in (3, 4, 5))
        self._next.setText("Finish" if self.step == 5 else "Continue")
        if self.step == 2:
            self._start_chord_test()
        else:
            self._stop_chord_test()
        self._refresh_next()

    def _refresh_next(self) -> None:
        ok = True
        if self.step == 1:
            ok = bool(self._mic_check.ok) and bool(self._speech_check.ok)
        elif self.step == 2:
            ok = self.chord_pressed and self.chord_released
        elif self.step == 3:
            ok = self._claude_check.ok is True
        elif self.step == 5:
            ok = (self._project_path is not None and bool(self._name.text().strip())) \
                or bool(self.coordinator.registry.projects)
        self._next.setEnabled(ok)

    def _advance(self) -> None:
        if self.step == 5:
            self.coordinator.settings.update(onboardingComplete=True)
            self._stop_chord_test()
            self._on_done()
            self.accept()
        else:
            self._goto(self.step + 1)

    def _on_next(self) -> None:
        if self.step == 5 and self._project_path and self._name.text().strip():
            aliases = [a.strip() for a in self._aliases.text().split(",") if a.strip()]
            self.coordinator.registry.add(Project(
                name=self._name.text().strip(), path=self._project_path,
                aliases=aliases, defaultAgent=self._agent.currentData()))
        self._advance()

    # -- step helpers ---------------------------------------------------

    @staticmethod
    def _open_ms_settings(anchor: str) -> None:
        try:
            os.startfile(f"ms-settings:{anchor}")   # type: ignore[attr-defined]
        except Exception:
            pass

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            os.startfile(url)   # type: ignore[attr-defined]
        except Exception:
            pass

    def _set_push_to_talk(self, hk) -> None:
        self.coordinator.settings.update(pushToTalk=hk)
        self.coordinator.register_hotkeys()
        self._start_chord_test()

    def _start_chord_test(self) -> None:
        self._stop_chord_test()
        self.chord_pressed = False
        self.chord_released = False
        self._press_check.set_state(False)
        self._release_check.set_state(False)
        self.coordinator.unregister_push_to_talk()

        def on_press():
            self.chord_pressed = True
            self._press_check.set_state(True)
            self._refresh_next()

        def on_release():
            self.chord_released = True
            self._release_check.set_state(True)
            self._refresh_next()

        self.chord_probe = HotkeyMonitor.shared().register(
            self.coordinator.settings.settings.pushToTalk,
            pressed=on_press, released=on_release,
        )
        self._refresh_next()

    def _stop_chord_test(self) -> None:
        if self.chord_probe is not None:
            HotkeyMonitor.shared().unregister(self.chord_probe)
            self.chord_probe = None
            self.coordinator.register_hotkeys()

    def _detect_agents(self) -> None:
        from ..core.cli_locator import CLILocator

        c = self.coordinator.claude_path
        x = self.coordinator.codex_path
        c_ver = CLILocator.version(c) if c else None
        c_in = False
        if c:
            code, out, err = CLILocator.run(c, ["auth", "status"], timeout=20)
            c_in = '"loggedIn": true' in out or '"loggedIn":true' in out
        x_ver = CLILocator.version(x) if x else None
        x_in = False
        if x:
            code, out, err = CLILocator.run(x, ["login", "status"], timeout=20)
            x_in = "logged in" in (out + err).lower()

        def apply():
            self._claude_check.set_state(
                c_ver is not None and c_in,
                (f"{c_ver} · {'logged in' if c_in else 'not logged in'}" if c_ver else "Not found on PATH"))
            self._codex_check.set_state(
                x_ver is not None and x_in,
                (f"{x_ver} · {'logged in' if x_in else 'not logged in'}" if x_ver else "Not found on PATH"))
            self._refresh_next()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, apply)

    def _save_fish(self) -> None:
        key = self._fish_field.text().strip()
        if not key:
            return
        securestore.set_(key, securestore.FISH_KEY)
        self._fish_field.clear()
        threading.Thread(target=self._fish_test, daemon=True).start()

    def _fish_test(self) -> None:
        key = securestore.get(securestore.FISH_KEY)
        if key:
            try:
                FishAudio.balance(key)
            except Exception:
                pass
        self.coordinator.voice.speak("Hi, I'm ready.")

    def _pick_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose a project folder")
        if directory:
            self._project_path = directory
            self._folder_btn.setText(directory)
            self._name.setText(ProjectRegistry.suggested_name(directory))
            self._refresh_next()
