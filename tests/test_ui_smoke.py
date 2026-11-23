"""Qt offscreen smoke test: builds every widget and forces a paint pass so
construction/painting bugs surface in CI (no display needed)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except Exception:
    HAVE_QT = False

from .support import IsolatedDataDirTest


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class UISmokeTests(IsolatedDataDirTest):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _grab(self, widget):
        widget.resize(widget.sizeHint())
        img = widget.grab()
        self.assertFalse(img.isNull())

    def test_pill_paints_all_states(self):
        from conductor.services.coordinator import PillModel, PillState
        from conductor.ui.pill import ListeningPill

        model = PillModel()
        pill = ListeningPill(model)
        for state in (PillState.listening, PillState.thinking, PillState.speaking,
                      PillState.clarify, PillState.error):
            model.state = state
            model.visible = True
            model.transcript = "Update the website and deploy"
            model.secondary = "Which project?"
            model.level = 0.5
            self._grab(pill)
        model.visible = False
        self._grab(pill)

    def test_overlay_builds_cards(self):
        from conductor.core.models import AgentKind, Session, SessionStatus
        from conductor.core.stores import SessionStore
        from conductor.ui.overlay import SessionsOverlay

        store = SessionStore()
        store.insert(Session(id="s_01", projectName="Plumber Website", projectPath="C:/p",
                             agent=AgentKind.claude, task="Build the hero section",
                             status=SessionStatus.running, activity="Write hero.tsx"))
        store.insert(Session(id="s_02", projectName="Bakery", projectPath="C:/b",
                             agent=AgentKind.codex, task="Fix the oven", status=SessionStatus.done))
        overlay = SessionsOverlay(
            store, "Ctrl+Shift+Space",
            on_close=lambda: None, on_open=lambda s: None, on_log=lambda s: None,
            on_reply=lambda s, t: None, on_stop=lambda s: None, on_dismiss=lambda s: None,
        )
        self._grab(overlay)
        store.dismiss("s_01")
        self._grab(overlay)

    def test_settings_and_recorder(self):
        from conductor.services.coordinator import Coordinator
        from conductor.ui.settings_ui import SettingsWindow

        coord = Coordinator()
        win = SettingsWindow(coord)
        self._grab(win)

    def test_onboarding(self):
        from conductor.services.coordinator import Coordinator
        from conductor.ui.onboarding import OnboardingWindow

        coord = Coordinator()
        done = []
        win = OnboardingWindow(coord, on_done=lambda: done.append(1))
        for step in range(6):
            win._goto(step)
            self._grab(win)

    def test_floating_panel(self):
        from conductor.services.coordinator import PillModel
        from conductor.ui.floating import FloatingPanel
        from conductor.ui.pill import ListeningPill

        panel = FloatingPanel(ListeningPill(PillModel()), draggable=False)
        panel.fit_to_content()
        self.assertGreaterEqual(panel.width(), 1)


if __name__ == "__main__":
    unittest.main()
