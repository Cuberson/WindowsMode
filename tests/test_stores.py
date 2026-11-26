"""Port of StoreTests/ResolveTests from MemoryTests.swift + store semantics."""

import unittest

from conductor.core.models import (
    AgentKind, Memory, Project, Session, SessionStatus,
)
from conductor.core.stores import (
    MemoryStore, ProjectRegistry, SessionStore, format_elapsed,
)

from .support import IsolatedDataDirTest


class ResolveTests(IsolatedDataDirTest):
    def test_prefers_most_specific_project(self):
        r = ProjectRegistry()
        r.set_projects([
            Project(name="website", path="~/x"),
            Project(name="New Construction Website", path="~/y"),
            Project(name="Plumber Website", path="~/z", aliases=["plumber"]),
        ])
        self.assertEqual(r.resolve("New Construction Website").name, "New Construction Website")
        self.assertEqual(r.resolve("the plumber site").name, "Plumber Website")
        self.assertEqual(r.resolve("website").name, "website")
        self.assertIsNone(r.resolve("bakery"))

    def test_registry_resolution(self):
        r = ProjectRegistry()
        r.set_projects([
            Project(name="website", path="~/Projects/website", aliases=["the site", "homepage"]),
            Project(name="api", path="~/Projects/api"),
        ])
        self.assertEqual(r.resolve("Website").name, "website")
        self.assertEqual(r.resolve("the site").name, "website")
        self.assertEqual(r.resolve("API project").name, "api")
        self.assertIsNone(r.resolve(None))
        self.assertIsNone(r.resolve("unknown"))

    def test_prompt_summary(self):
        r = ProjectRegistry()
        self.assertEqual(r.prompt_summary, "- (none registered yet)")
        r.add(Project(name="website", path="C:/x", aliases=["the site"], defaultAgent=AgentKind.claude))
        self.assertIn("- website · C:/x · [the site] · claude", r.prompt_summary)


class SessionStoreTests(IsolatedDataDirTest):
    def test_next_id_format(self):
        s = SessionStore()
        self.assertEqual(s.next_id(), "s_01")
        self.assertEqual(s.next_id(), "s_02")

    def test_format_elapsed(self):
        self.assertEqual(format_elapsed(5), "5s")
        self.assertEqual(format_elapsed(125), "2m05s")
        self.assertEqual(format_elapsed(3905), "1h05m")

    def test_orphaned_running_sessions_are_killed_on_launch(self):
        s = SessionStore()
        s.insert(Session(id="s_01", projectName="w", projectPath="C:/w", agent=AgentKind.claude,
                         task="t", status=SessionStatus.running, pid=999999))
        s2 = SessionStore()   # relaunch
        sess = s2.session("s_01")
        self.assertEqual(sess.status, SessionStatus.failed)
        self.assertEqual(sess.activity, "Interrupted by app restart")

    def test_visible_sorts_active_first(self):
        s = SessionStore()
        s.insert(Session(id="s_01", projectName="a", projectPath="p", agent=AgentKind.claude,
                         task="old", status=SessionStatus.done))
        s.insert(Session(id="s_02", projectName="b", projectPath="p", agent=AgentKind.claude,
                         task="running", status=SessionStatus.running))
        visible = s.visible
        self.assertEqual(visible[0].id, "s_02")

    def test_prompt_summary(self):
        s = SessionStore()
        self.assertEqual(s.prompt_summary, "- (none)")
        s.insert(Session(id="s_01", projectName="w", projectPath="p", agent=AgentKind.claude,
                         task="hello world"))
        self.assertIn('s_01 · w · claude · running · "hello world"', s.prompt_summary)


class MemoryTests(IsolatedDataDirTest):
    def test_remember_dedupes_case_insensitively(self):
        m = MemoryStore()
        m.remember("Prefers Tailwind")
        m.remember("prefers tailwind")
        self.assertEqual(len(m.memories), 1)

    def test_forget_substring_either_direction(self):
        m = MemoryStore()
        m.remember("Prefers Tailwind over plain CSS")
        m.remember("Plumber Website runs on port 3200")
        removed = m.forget("tailwind")
        self.assertEqual(removed, 1)
        self.assertEqual(len(m.memories), 1)

    def test_record_caps_turns(self):
        m = MemoryStore()
        for i in range(20):
            m.record(heard=f"h{i}", said="s", action="chitchat")
        self.assertEqual(len(m.turns), MemoryStore.max_turns)
        self.assertEqual(m.turns[0].heard, "h8")

    def test_agent_guidance(self):
        m = MemoryStore()
        self.assertIsNone(m.agent_guidance)
        m.remember("Prefers Tailwind")
        self.assertIn("Standing preferences", m.agent_guidance)
        self.assertIn("Prefers Tailwind", m.agent_guidance)

    def test_prompt_summaries(self):
        m = MemoryStore()
        self.assertEqual(m.prompt_summary, "- (nothing saved yet)")
        self.assertEqual(m.turns_summary, "- (none)")
        m.remember("Call me Albert")
        m.record(heard="hi", said="hello", action="chitchat")
        self.assertIn("- Call me Albert", m.prompt_summary)
        self.assertIn('heard: "hi" → chitchat', m.turns_summary)


if __name__ == "__main__":
    unittest.main()
