"""Port of the Coordinator tests from MemoryTests.swift (sanitize,
normalize_transcript) + blip WAV + create_project naming rules."""

import struct
import unittest
from pathlib import Path

from conductor.core import audio
from conductor.core.models import OrchestratorAction, OrchestratorActionKind
from conductor.services.coordinator import Coordinator

from .support import IsolatedDataDirTest


def _open(task=None):
    return OrchestratorAction(action=OrchestratorActionKind.open, project="Plumber Website", task=task,
                              speak="Opening.")


class SanitizeTests(unittest.TestCase):
    def test_localhost_open_becomes_work(self):
        a = Coordinator.sanitize(_open(), "open the plumber website on localhost")
        self.assertEqual(a.action, OrchestratorActionKind.followup)
        self.assertEqual(a.task, "open the plumber website on localhost")

    def test_browser_open_with_task_keeps_task(self):
        a = Coordinator.sanitize(_open("run it on port 6000"),
                                 "run the hair salon site on localhost 6000 and open it in my browser")
        self.assertEqual(a.action, OrchestratorActionKind.followup)
        self.assertEqual(a.task, "run it on port 6000")

    def test_literal_terminal_stays_open(self):
        self.assertEqual(Coordinator.sanitize(_open(), "open a terminal in the plumber project").action,
                         OrchestratorActionKind.open)
        self.assertEqual(Coordinator.sanitize(_open(), "open the plumber folder").action,
                         OrchestratorActionKind.open)


class TranscriptNormalizeTests(unittest.TestCase):
    def test_codex_variants(self):
        for v in ["use kodex for this", "tell codecs to fix it", "start co-dex on the plumber",
                  "Code X should do it", "give it to Cortex"]:
            self.assertIn("Codex", Coordinator.normalize_transcript(v), v)

    def test_claude_variants(self):
        self.assertEqual(Coordinator.normalize_transcript("tell claud to do it"), "tell Claude to do it")
        self.assertEqual(Coordinator.normalize_transcript("deploy to the cloud"), "deploy to the cloud")


class BlipTests(unittest.TestCase):
    def test_blip_wav_structure(self):
        wav = audio.blip_wav()
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertIn(b"data", wav)
        # 40 ms of 16-bit mono 44.1 kHz = 3528 bytes of PCM.
        idx = wav.index(b"data")
        (size,) = struct.unpack_from("<I", wav, idx + 4)
        self.assertEqual(size, 3528)


class CreateProjectTests(IsolatedDataDirTest):
    def setUp(self):
        super().setUp()
        self.coord = Coordinator()
        self.root = self.data_dir / "Projects"
        self.coord.settings.update(projectsRoot=str(self.root))

    def test_creates_slug_and_registers(self):
        p = self.coord.create_project("Plumber Website")
        self.assertEqual(p.name, "Plumber Website")
        self.assertTrue((self.root / "plumber-website").is_dir())
        self.assertIn(p, self.coord.registry.projects)

    def test_rejects_generic_names(self):
        with self.assertRaises(ValueError):
            self.coord.create_project("website")
        with self.assertRaises(ValueError):
            self.coord.create_project("new")

    def test_reuses_existing(self):
        p1 = self.coord.create_project("Bakery Site")
        p2 = self.coord.create_project("bakery site")
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(len(self.coord.registry.projects), 1)


if __name__ == "__main__":
    unittest.main()
