"""Port of CueTests from MemoryTests.swift + Fish Audio request building."""

import unittest

from conductor.services.voice import FishAudio, strip_cues


class CueTests(unittest.TestCase):
    def test_strip_cues(self):
        self.assertEqual(strip_cues("[chuckles] Six already? [serious] Finish one first."),
                         "Six already? Finish one first.")
        self.assertEqual(strip_cues("On it."), "On it.")


class FishAudioBodyTests(unittest.TestCase):
    def test_tts_body(self):
        body = FishAudio.build_tts_body("Hi", "voice-id", 1.2)
        self.assertEqual(body["text"], "Hi")
        self.assertEqual(body["reference_id"], "voice-id")
        self.assertEqual(body["format"], "mp3")
        self.assertEqual(body["mp3_bitrate"], 128)
        self.assertEqual(body["latency"], "low")
        self.assertTrue(body["normalize"])
        self.assertEqual(body["prosody"], {"speed": 1.2, "volume": 0})


if __name__ == "__main__":
    unittest.main()
