"""Model JSON round-trips — keys must match the macOS app's files exactly."""

import unittest

from conductor.core.models import (
    AgentKind, Hotkey, OrchestratorAction, OrchestratorActionKind, PermissionMode,
    Project, Session, SessionStatus, Settings,
)
from conductor.core.paths import format_datetime, parse_datetime


class SettingsTests(unittest.TestCase):
    def test_defaults_match_macos(self):
        s = Settings()
        self.assertEqual(s.pushToTalk.keyCode, 0x20)
        self.assertEqual(s.maxConcurrentSessions, 6)
        self.assertEqual(s.fishVoiceName, "Sarah")
        self.assertEqual(s.fishModel, "auto")
        self.assertEqual(s.projectsRoot, "~/Projects")
        self.assertTrue(s.speakSummaries)
        self.assertTrue(s.blipOnChordDown)

    def test_round_trip(self):
        s = Settings()
        s.defaultAgent = AgentKind.codex
        s.overlayOrigin = {"x": 12.0, "y": 34.0}
        s.claudePathOverride = "C:/bin/claude.cmd"
        d = s.to_dict()
        self.assertEqual(d["defaultAgent"], "codex")
        self.assertEqual(d["pushToTalk"], {"keyCode": 32, "modifiers": 5})
        back = Settings.from_dict(d)
        self.assertEqual(back.defaultAgent, AgentKind.codex)
        self.assertEqual(back.overlayOrigin, {"x": 12.0, "y": 34.0})
        self.assertEqual(back.claudePathOverride, "C:/bin/claude.cmd")

    def test_unknown_and_missing_keys_tolerated(self):
        s = Settings.from_dict({"overlayOpacity": 0.7, "bogusKey": 1, "fishModel": None})
        self.assertEqual(s.overlayOpacity, 0.7)
        self.assertEqual(s.fishModel, "auto")


class ActionJSONTests(unittest.TestCase):
    def test_session_id_key(self):
        d = OrchestratorAction(
            action=OrchestratorActionKind.followup, session_id="s_01", task="t", speak="ok",
        ).to_dict()
        self.assertIn("session_id", d)
        self.assertNotIn("sessionID", d)

    def test_schema_has_all_required(self):
        import json
        schema = json.loads(OrchestratorAction.JSON_SCHEMA)
        self.assertEqual(
            set(schema["required"]),
            {"action", "agent", "project", "session_id", "task", "speak", "remember", "forget"},
        )
        self.assertEqual(
            set(schema["properties"]["action"]["enum"]),
            {"spawn", "followup", "cancel", "status", "open", "clarify", "chitchat", "create"},
        )


class SessionJSONTests(unittest.TestCase):
    def test_session_round_trip(self):
        s = Session(id="s_01", projectName="web", projectPath="C:/web",
                    agent=AgentKind.codex, task="do it")
        from conductor.core.stores import _session_dict
        d = _session_dict(s)
        self.assertEqual(set(d.keys()), {
            "id", "projectName", "projectPath", "agent", "task", "status", "activity",
            "startedAt", "finishedAt", "agentSessionID", "resultText", "pid", "dismissed",
        })
        back = Session.from_dict(d)
        self.assertEqual(back.agent, AgentKind.codex)
        self.assertEqual(back.status, SessionStatus.running)
        # ISO-8601 has second precision, so elapsed can be up to ~1 s here.
        self.assertLess(back.elapsed, 2.0)


class DateTimeTests(unittest.TestCase):
    def test_iso_format_matches_foundation(self):
        import datetime as dt
        d = dt.datetime(2026, 11, 21, 10, 30, 5, tzinfo=dt.timezone.utc)
        self.assertEqual(format_datetime(d), "2026-11-21T10:30:05Z")
        self.assertEqual(parse_datetime("2026-11-21T10:30:05Z"), d)
        self.assertIsNone(parse_datetime("garbage"))
        self.assertIsNone(parse_datetime(None))


class HotkeyTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(Hotkey.push_to_talk().keyCode, 0x20)
        self.assertEqual(Hotkey.push_to_talk().modifiers, 5)  # ctrl|shift
        self.assertEqual(Hotkey.overlay().keyCode, 0x4F)


if __name__ == "__main__":
    unittest.main()
