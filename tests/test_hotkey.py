"""Hotkey display + chord matching (the platform-neutral half of §3.6)."""

import unittest

from conductor.core.models import Hotkey, MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN
from conductor.services.hotkey import chord_matches, hotkey_display, key_name, modifiers_from_state


class HotkeyDisplayTests(unittest.TestCase):
    def test_display(self):
        self.assertEqual(hotkey_display(Hotkey(0x20, MOD_CTRL | MOD_SHIFT)), "Ctrl+Shift+Space")
        self.assertEqual(hotkey_display(Hotkey(0x4F, MOD_CTRL | MOD_SHIFT)), "Ctrl+Shift+O")
        self.assertEqual(hotkey_display(Hotkey(0x1B, 0)), "Esc")
        self.assertEqual(hotkey_display(Hotkey(0x70, MOD_ALT)), "Alt+F1")
        self.assertEqual(hotkey_display(Hotkey(0x41, MOD_WIN | MOD_SHIFT)), "Win+Shift+A")

    def test_key_names(self):
        self.assertEqual(key_name(0x20), "Space")
        self.assertEqual(key_name(0x1B), "Esc")
        self.assertEqual(key_name(0x5A), "Z")
        self.assertEqual(key_name(0x99), "Key 0x99")


class ChordMatchTests(unittest.TestCase):
    def test_exact_modifiers_required(self):
        hk = Hotkey(0x20, MOD_CTRL | MOD_SHIFT)
        self.assertTrue(chord_matches(hk, 0x20, MOD_CTRL | MOD_SHIFT))
        self.assertFalse(chord_matches(hk, 0x20, MOD_CTRL))
        self.assertFalse(chord_matches(hk, 0x20, MOD_CTRL | MOD_SHIFT | MOD_ALT))
        self.assertFalse(chord_matches(hk, 0x41, MOD_CTRL | MOD_SHIFT))

    def test_bare_key_chord(self):
        esc = Hotkey(0x1B, 0)
        self.assertTrue(chord_matches(esc, 0x1B, 0))
        self.assertFalse(chord_matches(esc, 0x1B, MOD_CTRL))

    def test_modifier_state_packing(self):
        self.assertEqual(modifiers_from_state(True, False, True, False), MOD_CTRL | MOD_SHIFT)
        self.assertEqual(modifiers_from_state(False, True, False, True), MOD_ALT | MOD_WIN)


if __name__ == "__main__":
    unittest.main()
