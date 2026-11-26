"""§5.4 — one compact window, tabs: General · Agents · Voice · Projects · Memory.
Port of SettingsView.swift."""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSlider, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..core import securestore, startup
from ..core.models import AgentKind, PermissionMode
from ..services.voice import FishAudio
from . import theme
from .shortcut_recorder import ShortcutRecorder


def _label(text: str, secondary: bool = True) -> QLabel:
    l = QLabel(text)
    l.setFont(theme.font(13))
    l.setStyleSheet(f"color: {'rgba(235,235,240,190)' if secondary else 'white'};")
    l.setWordWrap(True)
    return l


class SettingsWindow(QDialog):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self.setWindowTitle("Conductor Settings")
        self.setMinimumSize(560, 460)
        self.setStyleSheet("QDialog { background: #202026; } QLabel { color: rgba(235,235,240,190); }")

        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(GeneralTab(coordinator), "General")
        tabs.addTab(AgentsTab(coordinator), "Agents")
        tabs.addTab(VoiceTab(coordinator), "Voice")
        tabs.addTab(ProjectsTab(coordinator), "Projects")
        tabs.addTab(MemoryTab(coordinator), "Memory")
        lay.addWidget(tabs)


class GeneralTab(QWidget):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        s = coordinator.settings.settings
        form = QFormLayout(self)
        form.setVerticalSpacing(12)

        form.addRow("Push to talk", ShortcutRecorder(
            lambda: s.pushToTalk,
            lambda hk: self._set_hk("pushToTalk", hk),
        ))
        form.addRow("Toggle sessions overlay", ShortcutRecorder(
            lambda: s.overlayToggle,
            lambda hk: self._set_hk("overlayToggle", hk),
        ))
        if coordinator.hotkey_error:
            err = QLabel(coordinator.hotkey_error)
            err.setStyleSheet("color: #FF6B6B; font-size: 11px;")
            form.addRow("", err)

        self._login = QCheckBox("Launch at login")
        self._login.setChecked(s.launchAtLogin)
        self._login.toggled.connect(self._toggle_login)
        form.addRow("", self._login)

        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(50, 100)
        self._opacity.setValue(int(s.overlayOpacity * 100))
        self._opacity.valueChanged.connect(
            lambda v: coordinator.settings.update(overlayOpacity=v / 100.0))
        form.addRow("Overlay opacity", self._opacity)

        for key, text in [
            ("speakSummaries", "Speak completion summaries"),
            ("muteDuringFocus", "Mute while a Focus is on"),
            ("blipOnChordDown", "Blip when the chord is pressed"),
        ]:
            box = QCheckBox(text)
            box.setChecked(bool(getattr(s, key)))
            box.toggled.connect(lambda v, k=key: coordinator.settings.update(**{k: v}))
            form.addRow("", box)

    def _set_hk(self, key: str, hk) -> None:
        self.coordinator.settings.update(**{key: hk})
        self.coordinator.register_hotkeys()

    def _toggle_login(self, on: bool) -> None:
        if not startup.set_launch_at_login(on):
            self._login.blockSignals(True)
            self._login.setChecked(False)
            self._login.blockSignals(False)
        self.coordinator.settings.update(launchAtLogin=on)


class AgentsTab(QWidget):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        s = coordinator.settings.settings
        form = QFormLayout(self)
        form.setVerticalSpacing(12)

        self._claude = _label("…")
        self._codex = _label("…")
        form.addRow("claude", self._claude)
        form.addRow("codex", self._codex)

        self._default_agent = QComboBox()
        for k in AgentKind:
            self._default_agent.addItem(k.display_name, k)
        self._default_agent.setCurrentIndex(0 if s.defaultAgent is AgentKind.claude else 1)
        self._default_agent.currentIndexChanged.connect(
            lambda _: coordinator.settings.update(
                defaultAgent=self._default_agent.currentData()))
        form.addRow("Default agent", self._default_agent)

        for key, text in [("claudePermissionMode", "Claude permission mode"),
                          ("codexPermissionMode", "Codex permission mode")]:
            box = QComboBox()
            for m in PermissionMode:
                box.addItem(m.display_name, m)
            box.setCurrentIndex(0 if getattr(s, key) is PermissionMode.acceptEdits else 1)
            box.currentIndexChanged.connect(
                lambda _, b=box, k=key: coordinator.settings.update(**{k: b.currentData()}))
            form.addRow(text, box)

        self._max = QSpinBox()
        self._max.setRange(1, 6)
        self._max.setValue(s.maxConcurrentSessions)
        self._max.valueChanged.connect(
            lambda v: coordinator.settings.update(maxConcurrentSessions=v))
        form.addRow("Max concurrent sessions", self._max)

        threading.Thread(target=self._detect, daemon=True).start()

    def _detect(self) -> None:
        from ..core.cli_locator import CLILocator

        c = self.coordinator.claude_path
        x = self.coordinator.codex_path
        c_ver = CLILocator.version(c) if c else None
        x_ver = CLILocator.version(x) if x else None

        def apply():
            self._claude.setText(f"{c}  ·  {c_ver}" if c else "not found")
            self._codex.setText(f"{x}  ·  {x_ver}" if x else "not found")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, apply)


class VoiceTab(QWidget):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        s = coordinator.settings.settings
        self._has_key = securestore.get(securestore.FISH_KEY) is not None

        form = QFormLayout(self)
        form.setVerticalSpacing(12)

        if self._has_key:
            row = QHBoxLayout()
            row.addWidget(_label("Stored in Credential Manager"))
            clear = QPushButton("Clear")
            clear.clicked.connect(self._clear_key)
            row.addWidget(clear)
            row.addStretch(1)
            form.addRow("API key", row)
            self._balance = _label("…")
            form.addRow("Credits", self._balance)
        else:
            self._key_field = QLineEdit()
            self._key_field.setPlaceholderText("Paste your Fish Audio key")
            self._key_field.setEchoMode(QLineEdit.EchoMode.Password)
            save = QPushButton("Save to Credential Manager")
            save.clicked.connect(self._save_key)
            row = QHBoxLayout()
            row.addWidget(self._key_field)
            row.addWidget(save)
            form.addRow("API key", row)
            self._balance = None

        self._model = QComboBox()
        self._model.addItem("Auto (Pro, free if no API credit)", "auto")
        self._model.addItem("S2.1 Pro — uses API credit", "s2.1-pro")
        self._model.addItem("S2.1 Pro Free — $0", "s2.1-pro-free")
        idx = {"auto": 0, "s2.1-pro": 1, "s2.1-pro-free": 2}.get(s.fishModel, 0)
        self._model.setCurrentIndex(idx)
        self._model.currentIndexChanged.connect(
            lambda _: coordinator.settings.update(fishModel=self._model.currentData()))
        form.addRow("Model", self._model)

        form.addRow("", _label(
            "Plan package credits only cover the Fish website. The API bills a separate "
            "USD “API credit” balance; the Free model costs nothing."))

        self._voice_name = _label(s.fishVoiceName)
        form.addRow("Current voice", self._voice_name)

        self._query = QLineEdit()
        self._query.setPlaceholderText("e.g. calm female")
        search = QPushButton("Search")
        search.clicked.connect(self._search)
        preview = QPushButton("Preview")
        preview.clicked.connect(lambda: coordinator.voice.speak("Hi, I'm ready."))
        row = QHBoxLayout()
        row.addWidget(self._query)
        row.addWidget(search)
        row.addWidget(preview)
        form.addRow("Search voices", row)

        self._voices = QListWidget()
        self._voices.setMaximumHeight(130)
        self._voices.itemClicked.connect(self._pick_voice)
        form.addRow("", self._voices)

        self._rate = QSlider(Qt.Orientation.Horizontal)
        self._rate.setRange(70, 140)
        self._rate.setValue(int(s.speakingRate * 100))
        self._rate.valueChanged.connect(
            lambda v: coordinator.settings.update(speakingRate=v / 100.0))
        form.addRow("Speaking rate", self._rate)

        self._fallback = QCheckBox("Fall back to the system voice")
        self._fallback.setChecked(s.systemVoiceFallback)
        self._fallback.toggled.connect(
            lambda v: coordinator.settings.update(systemVoiceFallback=v))
        form.addRow("", self._fallback)

        if self._has_key:
            threading.Thread(target=self._refresh_balance, daemon=True).start()

    def _save_key(self) -> None:
        key = self._key_field.text().strip()
        if not key:
            return
        if securestore.set_(key, securestore.FISH_KEY):
            self._has_key = True
            self._key_field.clear()
            threading.Thread(target=self._refresh_balance, daemon=True).start()

    def _clear_key(self) -> None:
        securestore.delete(securestore.FISH_KEY)
        self._has_key = False
        if self._balance:
            self._balance.setText("")

    def _refresh_balance(self) -> None:
        key = securestore.get(securestore.FISH_KEY)
        if not key:
            return
        try:
            b = FishAudio.balance(key)
            text = f"API credit ${b['apiCreditUSD']} · package {b['balance']} ({b['type']})"
        except Exception as e:
            text = f"Couldn't fetch balance: {e}"
        if self._balance:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._balance.setText(text))

    def _search(self) -> None:
        threading.Thread(target=self._search_worker, daemon=True).start()

    def _search_worker(self) -> None:
        key = securestore.get(securestore.FISH_KEY)
        if not key:
            return
        try:
            voices = FishAudio.search_voices(key, self._query.text().strip())
        except Exception:
            return

        def apply():
            self._voices.clear()
            for v in voices:
                item = QListWidgetItem(f"{v['title']}  ·  {' · '.join(v['tags'])}")
                item.setData(Qt.ItemDataRole.UserRole, v)
                self._voices.addItem(item)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, apply)

    def _pick_voice(self, item: QListWidgetItem) -> None:
        v = item.data(Qt.ItemDataRole.UserRole)
        if v:
            self.coordinator.settings.update(fishVoiceID=v["id"], fishVoiceName=v["title"])
            self._voice_name.setText(v["title"])


class ProjectsTab(QWidget):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        lay = QVBoxLayout(self)

        self._list = QListWidget()
        self._list.setStyleSheet("QListWidget { background: rgba(255,255,255,12); border-radius: 10px; }")
        lay.addWidget(self._list)

        row = QHBoxLayout()
        add = QPushButton("+")
        add.clicked.connect(self._add_folder)
        remove = QPushButton("−")
        remove.clicked.connect(self._remove_selected)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(_label("Drop a folder here to add it"))
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(_label("New projects by voice go in"))
        self._root = QLineEdit(coordinator.settings.settings.projectsRoot)
        self._root.setMaximumWidth(260)
        self._root.editingFinished.connect(
            lambda: coordinator.settings.update(projectsRoot=self._root.text().strip()))
        row2.addWidget(self._root)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_root)
        row2.addWidget(choose)
        row2.addStretch(1)
        lay.addLayout(row2)

        self._refresh()
        coordinator.registry.add_listener(self._refresh)

    def _refresh(self) -> None:
        self._list.clear()
        for p in self.coordinator.registry.projects:
            self._list.addItem(f"{p.name}    {p.path}    [{', '.join(p.aliases)}]  ·  {p.defaultAgent.display_name}")

    def _add_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(self, "Choose a project folder")
        if directory:
            from ..core.models import Project
            from ..core.stores import ProjectRegistry
            self.coordinator.registry.add(Project(
                name=ProjectRegistry.suggested_name(directory), path=directory))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        projects = self.coordinator.registry.projects
        if 0 <= row < len(projects):
            self.coordinator.registry.remove(projects[row].id)

    def _choose_root(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(self, "Choose where new projects go")
        if directory:
            self._root.setText(directory)
            self.coordinator.settings.update(projectsRoot=directory)


class MemoryTab(QWidget):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            'Say “remember …” while talking, or add a note here. These are given to '
            'the orchestrator on every turn and to every coding agent it starts.'))

        self._list = QListWidget()
        self._list.setStyleSheet("QListWidget { background: rgba(255,255,255,12); border-radius: 10px; }")
        lay.addWidget(self._list)

        row = QHBoxLayout()
        self._draft = QLineEdit()
        self._draft.setPlaceholderText("Add something to remember…")
        self._draft.returnPressed.connect(self._add)
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        remove = QPushButton("−")
        remove.clicked.connect(self._remove_selected)
        row.addWidget(self._draft)
        row.addWidget(add)
        row.addWidget(remove)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self._count = QLabel("")
        row2.addWidget(self._count)
        row2.addStretch(1)
        clear_turns = QPushButton("Clear conversation")
        clear_turns.clicked.connect(self.coordinator.memory.clear_turns)
        forget_all = QPushButton("Forget everything")
        forget_all.clicked.connect(self.coordinator.memory.clear_memories)
        row2.addWidget(clear_turns)
        row2.addWidget(forget_all)
        lay.addLayout(row2)

        self._refresh()
        coordinator.memory.add_listener(self._refresh)

    def _refresh(self) -> None:
        self._list.clear()
        for m in self.coordinator.memory.memories:
            item = QListWidgetItem(m.text)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._list.addItem(item)
        self._count.setText(f"{len(self.coordinator.memory.turns)} recent exchanges kept for context")

    def _add(self) -> None:
        text = self._draft.text().strip()
        if text:
            self.coordinator.memory.remember(text)
            self._draft.clear()

    def _remove_selected(self) -> None:
        item = self._list.currentItem()
        if item:
            self.coordinator.memory.remove(item.data(Qt.ItemDataRole.UserRole))
