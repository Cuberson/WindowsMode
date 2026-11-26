"""Port of OrchestratorTests.swift + the schema-decode test from MemoryTests.swift."""

import unittest

from conductor.core.cli_locator import CLILocator
from conductor.core.models import OrchestratorAction, OrchestratorActionKind
from conductor.services.agent_runner import AgentRunner
from conductor.services.orchestrator import Orchestrator

from .support import fixture


class OrchestratorParseTests(unittest.TestCase):
    def test_parses_structured_output_envelope(self):
        # Real envelope captured from claude 2.1.239 (2-field schema); missing
        # optional keys decode as None.
        a = Orchestrator.parse(fixture("orchestrator-result.json"))
        self.assertIsNotNone(a)
        self.assertEqual(a.action, OrchestratorActionKind.status)
        self.assertIsNone(a.project)
        self.assertTrue(a.speak)

    def test_parses_full_contract(self):
        import json
        action = {
            "action": "spawn", "agent": "claude", "project": "website", "session_id": None,
            "task": "Change the hero headline to 'Build faster with AI' and deploy",
            "speak": "On it.",
        }
        env = {"type": "result", "result": json.dumps(action), "structured_output": action}
        a = Orchestrator.parse(json.dumps(env))
        self.assertEqual(a.action, OrchestratorActionKind.spawn)
        self.assertEqual(a.agent.value, "claude")
        self.assertEqual(a.project, "website")
        self.assertIsNone(a.session_id)
        self.assertEqual(a.speak, "On it.")

    def test_falls_back_to_result_text_with_prose(self):
        import json
        env = {"type": "result",
               "result": 'Sure! {"action":"status","agent":null,"project":null,'
                         '"session_id":null,"task":null,"speak":"Nothing running."}'}
        self.assertEqual(Orchestrator.parse(json.dumps(env)).action, OrchestratorActionKind.status)

    def test_schema_decodes_memory_fields(self):
        import json
        raw = ('{"action":"chitchat","agent":null,"project":null,"session_id":null,"task":null,'
               '"speak":"Got it.","remember":"Prefers Tailwind","forget":null}')
        a = OrchestratorAction.from_dict(json.loads(raw))
        self.assertEqual(a.remember, "Prefers Tailwind")
        self.assertIsNone(a.forget)

    def test_args_never_contain_api_keys(self):
        joined = " ".join(Orchestrator.base_args())
        self.assertNotIn("api-key", joined)
        self.assertIn("--tools ", joined)
        self.assertNotIn("ANTHROPIC_API_KEY", CLILocator.child_environment())
        self.assertNotIn("OPENAI_API_KEY", CLILocator.child_environment())

    def test_user_prompt_contains_context(self):
        p = Orchestrator.user_prompt(
            projects="- web", sessions="- (none)", max_sessions=6, running_count=0,
            transcript="do the thing", context="the thing = deploy",
            memories="- Prefers Tailwind", history="- [2m ago] heard: hi → chitchat",
        )
        self.assertIn("Prefers Tailwind", p)
        self.assertIn("combine them with the transcript): the thing = deploy", p)
        self.assertIn('Transcript: "do the thing"', p)
        self.assertIn("0/6 running", p)


class RunnerArgumentsTests(unittest.TestCase):
    def test_runner_arguments(self):
        self.assertEqual(AgentRunner.arguments("codex", "t", "acceptEdits", None)[:2],
                         ["exec", "--json"])
        self.assertEqual(AgentRunner.arguments("codex", "t", "acceptEdits", "abc")[:3],
                         ["exec", "resume", "abc"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox",
                      AgentRunner.arguments("codex", "t", "bypassPermissions", None))
        c = AgentRunner.arguments("claude", "t", "acceptEdits", "sid")
        self.assertIn("--resume", c)
        self.assertIn("acceptEdits", c)
        self.assertIn("stream-json", c)

    def test_agent_args_carry_memory(self):
        args = AgentRunner.arguments("claude", "x", "bypassPermissions", None,
                                     extra_guidance="Standing preferences:\n- Prefers Tailwind")
        i = args.index("--append-system-prompt")
        self.assertIn("Prefers Tailwind", args[i + 1])
        self.assertIn("headlessly", args[i + 1])


if __name__ == "__main__":
    unittest.main()
