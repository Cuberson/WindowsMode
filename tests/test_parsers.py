"""Port of ParserTests.swift — driven by the same captured fixtures."""

import unittest

from conductor.services.stream_parsers import ClaudeStreamParser, CodexStreamParser

from .support import fixture


class ParserTests(unittest.TestCase):
    def test_claude_stream_fixture(self):
        events = []
        for line in fixture("claude-stream.ndjson").splitlines():
            if line.strip():
                events += ClaudeStreamParser.parse(line)
        self.assertIn(("sessionID", "9e420cbc-12de-4457-b50b-67e7c18c3af5"),
                      [(e.kind, e.text) for e in events])
        self.assertIn(("activity", "Write Projects/website/hello.txt"),
                      [(e.kind, e.text) for e in events])
        self.assertIn(("activity", "Writing hello.txt"),
                      [(e.kind, e.text) for e in events])
        self.assertIn(("text", "Done."), [(e.kind, e.text) for e in events])
        self.assertIn(("result", "Done."), [(e.kind, e.text) for e in events if not e.is_error])
        self.assertFalse(any(e.kind == "needsInput" for e in events))

    def test_codex_stream_fixture(self):
        events = []
        for line in fixture("codex-stream.ndjson").splitlines():
            if line.strip():
                events += CodexStreamParser.parse(line)
        self.assertIn(("sessionID", "01a02d7f-1dcf-7842-a741-d4ffadca1a1a"),
                      [(e.kind, e.text) for e in events])
        self.assertIn(("activity", "Edit website/bye.txt"),
                      [(e.kind, e.text) for e in events])
        self.assertIn(("text", "Creating `bye.txt` with the requested content."),
                      [(e.kind, e.text) for e in events])
        last = events[-1]
        self.assertEqual((last.kind, last.text, last.is_error), ("result", "", False))

    def test_garbage_lines_ignored(self):
        self.assertEqual(ClaudeStreamParser.parse("not json"), [])
        self.assertEqual(CodexStreamParser.parse("Reading additional input from stdin..."), [])


if __name__ == "__main__":
    unittest.main()
