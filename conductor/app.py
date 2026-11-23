"""Conductor for Windows — app entry point. Port of ConductorApp.swift.

Tray-resident (no taskbar button): floating glass pill + sessions overlay,
settings and onboarding windows.
"""

from __future__ import annotations

import queue
import signal
import sys
import threading
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon,
)

from . import __version__
from .core import startup
from .core.paths import AppLog
from .services.coordinator import Coordinator, PillState
from .ui import theme
from .ui.floating import FloatingPanel
from .ui.onboarding import OnboardingWindow
from .ui.overlay import SessionsOverlay
from .ui.pill import ListeningPill
from .ui.settings_ui import SettingsWindow

IS_WINDOWS = sys.platform == "win32"


def _single_instance_lock() -> bool:
    """Named mutex: a second instance fails and forwards its URL to the first."""
    if not IS_WINDOWS:
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ERROR_ALREADY_EXISTS = 183
    handle = kernel32.CreateMutexW(None, False, "Local\\Conductor-SingleInstance")
    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _single_instance_lock.handle = handle  # keep alive
    return True


class Dispatcher(QObject):
    """Marshals worker-thread callbacks onto the Qt main thread."""

    fired = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self.fired.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def post(self, fn: Callable[[], None]) -> None:
        self._queue.put(fn)
        self.fired.emit(None)

    def _drain(self, *_args) -> None:
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as e:
                AppLog.write(f"dispatch error: {e}")


def tray_icon(running: bool = False) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(0x2B, 0x2B, 0x33, 235))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(1, 1, 30, 30, 8, 8)
    p.setBrush(QColor(0x4C, 0xC2, 0xFF))
    heights = [10, 18, 12, 16]
    for i, h in enumerate(heights):
        x = 7 + i * 5
        p.drawRoundedRect(x, 16 - h // 2, 3, h, 1.5, 1.5)
    if running:
        p.setBrush(QColor(0xFF, 0x5A, 0x5A))
        p.drawEllipse(23, 4, 7, 7)
    p.end()
    return QIcon(pm)


class ConductorApp:
    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.dispatcher = Dispatcher()
        self.coordinator = Coordinator(post=self.dispatcher.post)

        self.pill_panel: Optional[FloatingPanel] = None
        self.overlay_panel: Optional[FloatingPanel] = None
        self.settings_window: Optional[SettingsWindow] = None
        self.onboarding_window: Optional[OnboardingWindow] = None

        self._setup_tray()
        self._setup_panels()
        self.coordinator.on_pill_changed = self._refresh_pill
        self.coordinator.on_level_changed = self._refresh_pill
        self.coordinator.on_overlay_toggle = self.toggle_overlay

        # URL scheme inbox (conductor://… second-launch handoff).
        self._inbox_timer = QTimer()
        self._inbox_timer.setInterval(500)
        self._inbox_timer.timeout.connect(self._poll_inbox)
        self._inbox_timer.start()
        for url in startup.drain_inbox():
            self.handle_url(url)

        if not self.coordinator.settings.settings.onboardingComplete:
            self.show_onboarding()
        if self.coordinator.settings.settings.overlayVisible:
            self.show_overlay()

    # MARK: tray (§5.3)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(tray_icon(False), self.qt_app)
        menu = QMenu()
        menu.addAction("Toggle Sessions Overlay", self.toggle_overlay)
        menu.addSeparator()
        menu.addAction("Projects…", self.show_settings)
        menu.addAction("Settings…", self.show_settings)
        menu.addAction("Run Onboarding again", self.show_onboarding)
        menu.addSeparator()
        menu.addAction("About Conductor", self.show_about)
        menu.addAction("Quit Conductor", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Conductor")
        self.tray.show()

    def _update_tray_icon(self) -> None:
        self.tray.setIcon(tray_icon(bool(self.coordinator.sessions.running)))

    # MARK: panels

    def _setup_panels(self) -> None:
        pill_widget = ListeningPill(self.coordinator.pill)
        self.pill_panel = FloatingPanel(pill_widget, draggable=False, activatable=False)
        self.pill_panel.hide()

        overlay_widget = self._make_overlay()
        self.overlay_panel = FloatingPanel(overlay_widget, draggable=True, activatable=True)
        self.overlay_panel.moved.connect(self._save_overlay_origin)
        self.overlay_panel.hide()

    def _make_overlay(self) -> SessionsOverlay:
        s = self.coordinator.settings.settings
        return SessionsOverlay(
            store=self.coordinator.sessions,
            chord_text=_hotkey_text(s.pushToTalk),
            on_close=self.hide_overlay,
            on_open=lambda sess: self.coordinator.open_session(sess),
            on_log=lambda sess: self.coordinator.show_log(sess),
            on_reply=lambda sess, t: self.coordinator.follow_up(sess, t),
            on_stop=lambda sess: self.coordinator.stop(sess.id),
            on_dismiss=lambda sess: self.coordinator.sessions.dismiss(sess.id),
        )

    def _refresh_overlay(self) -> None:
        if self.overlay_panel is None:
            return
        opacity = self.coordinator.settings.settings.overlayOpacity
        if self.overlay_panel.isVisible():
            self.overlay_panel.set_opacity(opacity)
            self.overlay_panel.fit_to_content(anchor_top_center=False)

    def _position_pill_top_center(self) -> None:
        screen = self.qt_app.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.pill_panel.fit_to_content(anchor_top_center=True)
        w = self.pill_panel.width()
        self.pill_panel.move(geo.center().x() - w // 2, geo.top() + 12)

    def _refresh_pill(self) -> None:
        model = self.coordinator.pill
        if model.visible:
            self._position_pill_top_center()
            if not self.pill_panel.isVisible():
                self.pill_panel.show_animated(1.0)
        elif self.pill_panel.isVisible():
            self.pill_panel.hide_animated()
        self.pill_panel.update()

    def show_overlay(self) -> None:
        self._refresh_overlay()
        origin = self.coordinator.settings.settings.overlayOrigin
        screen = self.qt_app.primaryScreen()
        if isinstance(origin, dict) and screen is not None:
            self.overlay_panel.move(int(origin.get("x", 0)), int(origin.get("y", 0)))
        elif screen is not None:
            geo = screen.availableGeometry()
            self.overlay_panel.adjustSize()
            self.overlay_panel.move(geo.right() - 360 - 24, geo.top() + 24)
        self.overlay_panel.show_animated(self.coordinator.settings.settings.overlayOpacity)
        self.coordinator.settings.update(overlayVisible=True)

    def hide_overlay(self) -> None:
        if self.overlay_panel.isVisible():
            self.overlay_panel.hide_animated()
        self.coordinator.settings.update(overlayVisible=False)

    def toggle_overlay(self) -> None:
        if self.overlay_panel.isVisible():
            self.hide_overlay()
        else:
            self.show_overlay()

    def _save_overlay_origin(self) -> None:
        pos = self.overlay_panel.pos()
        self.coordinator.settings.update(overlayOrigin={"x": pos.x(), "y": pos.y()})

    # MARK: windows

    def show_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.coordinator)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def show_onboarding(self) -> None:
        if self.onboarding_window is None:
            self.onboarding_window = OnboardingWindow(
                self.coordinator, on_done=self._onboarding_done)
        self.onboarding_window.show()
        self.onboarding_window.raise_()
        self.onboarding_window.activateWindow()

    def _onboarding_done(self) -> None:
        self.onboarding_window = None

    def show_about(self) -> None:
        QMessageBox.about(
            None, "About Conductor",
            f"Conductor (VoiceMode) for Windows — {__version__}\n\n"
            "Voice-driven launcher for Claude Code and Codex. Local only.",
        )

    # MARK: URL scheme (conductor://say?text=…)

    def _poll_inbox(self) -> None:
        for url in startup.drain_inbox():
            self.handle_url(url)

    def handle_url(self, url: str) -> None:
        AppLog.write(f"open url: {url}")
        parsed = urlparse(url)
        host = parsed.hostname or parsed.path.lstrip("/").split("/")[0]
        if host == "say":
            text = parse_qs(parsed.query).get("text", [""])[0]
            if not text:
                return
            self.coordinator.pill.state = PillState.thinking
            self.coordinator.pill.transcript = text
            self.coordinator.pill.visible = True
            self._refresh_pill()
            threading.Thread(target=self.coordinator.handle, args=(text,), daemon=True).start()
        elif host == "overlay":
            self.toggle_overlay()
        elif host == "settings":
            self.show_settings()
        elif host == "onboarding":
            self.show_onboarding()

    # MARK: lifecycle

    def quit(self) -> None:
        running = len(self.coordinator.sessions.running)
        if running > 0:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Conductor")
            box.setText("One session is still running" if running == 1
                        else f"{running} sessions are still running")
            box.setInformativeText("Quitting will stop them.")
            quit_btn = box.addButton("Quit and Stop", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not quit_btn:
                return
        self.coordinator.prepare_for_quit()
        self.qt_app.quit()

    def poll_stores(self) -> None:
        """Tray badge + overlay refresh on store changes (called from a timer)."""
        self._update_tray_icon()
        self._refresh_overlay()


def _hotkey_text(hk) -> str:
    from .services.hotkey import hotkey_display
    return hotkey_display(hk)


def main() -> None:
    # URL args from a protocol launch (before the single-instance check so a
    # second launch can forward them).
    urls = [a for a in sys.argv[1:] if a.startswith("conductor://")]

    if not _single_instance_lock():
        for u in urls:
            startup.push_url_to_running_instance(u)
        return

    startup.register_url_scheme()
    AppLog.write(f"conductor starting ({__version__})")

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName("Conductor")
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ai.conductor.app")  # type: ignore[attr-defined]
        except Exception:
            pass

    app = ConductorApp(qt_app)
    for u in urls:
        app.handle_url(u)

    # SIGTERM/SIGHUP must still take the agent trees down — no orphans (§10.7).
    def on_signal(*_args):
        app.coordinator.prepare_for_quit()
        qt_app.quit()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, on_signal)
        except Exception:
            pass

    # Store-change polling for the tray badge (stores notify listeners; the
    # tray only needs a cheap periodic refresh).
    poll = QTimer()
    poll.setInterval(1000)
    poll.timeout.connect(app.poll_stores)
    poll.start()

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
