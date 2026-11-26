"""§3.6 — global chords via a low-level keyboard hook (SetWindowsHookEx
WH_KEYBOARD_LL). Delivers both press and release, needs no admin, and the
chord is swallowed (never reaches the focused app). Port of
HotkeyMonitor.swift + the Hotkey display helpers.

The message pump of the thread that installs the hook delivers callbacks —
on the Qt main thread that is the normal event loop. All API is main-thread.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from ..core.models import Hotkey, MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN
from ..core.paths import AppLog

IS_WINDOWS = sys.platform == "win32"

# Virtual-key names for display ("Ctrl+Shift+Space").
VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps Lock",
    0x1B: "Esc", 0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End",
    0x24: "Home", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2C: "Print Screen",
    0x2D: "Insert", 0x2E: "Delete", 0x5B: "Win", 0x5C: "Win",
    0x90: "Num Lock", 0x91: "Scroll Lock",
}
for _i in range(1, 13):
    VK_NAMES[0x70 + _i - 1] = f"F{_i}"
for _c in range(ord("A"), ord("Z") + 1):
    VK_NAMES[_c] = chr(_c)
for _d in range(ord("0"), ord("9") + 1):
    VK_NAMES[_d] = chr(_d)

_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def key_name(code: int) -> str:
    return VK_NAMES.get(code, f"Key {code:#x}")


def hotkey_display(hotkey: Hotkey) -> str:
    s = ""
    if hotkey.modifiers & MOD_WIN:
        s += "Win+"
    if hotkey.modifiers & MOD_CTRL:
        s += "Ctrl+"
    if hotkey.modifiers & MOD_SHIFT:
        s += "Shift+"
    if hotkey.modifiers & MOD_ALT:
        s += "Alt+"
    return s + key_name(hotkey.keyCode)


def modifiers_from_state(ctrl: bool, alt: bool, shift: bool, win: bool) -> int:
    m = 0
    if ctrl:
        m |= MOD_CTRL
    if alt:
        m |= MOD_ALT
    if shift:
        m |= MOD_SHIFT
    if win:
        m |= MOD_WIN
    return m


def chord_matches(hotkey: Hotkey, key_code: int, modifiers: int) -> bool:
    if key_code != hotkey.keyCode:
        return False
    if hotkey.modifiers == 0:
        return modifiers == 0
    return modifiers == hotkey.modifiers


class HotkeyMonitor:
    """Singleton wrapping the hook. Returns a registration id, or None if the
    chord cannot be used (mirrors macOS refusing when another app owns it)."""

    _shared: Optional["HotkeyMonitor"] = None

    @classmethod
    def shared(cls) -> "HotkeyMonitor":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self) -> None:
        self._handlers: dict[int, dict] = {}
        self._next_id = 1
        self._active_chord: Optional[int] = None   # registration id currently held
        self._recorder: Optional[Callable[[Hotkey], None]] = None
        self._hook = None
        self._proc_ref = None
        self._installed = False

    # -- registration -----------------------------------------------------

    def register(self, hotkey: Hotkey,
                 pressed: Callable[[], None],
                 released: Optional[Callable[[], None]] = None) -> Optional[int]:
        reg_id = self._next_id
        self._next_id += 1
        self._handlers[reg_id] = {"hotkey": hotkey, "pressed": pressed,
                                  "released": released or (lambda: None)}
        self._ensure_hook()
        return reg_id

    def unregister(self, reg_id: Optional[int]) -> None:
        if reg_id is not None:
            self._handlers.pop(reg_id, None)
            if self._active_chord == reg_id:
                self._active_chord = None

    @staticmethod
    def can_register(hotkey: Hotkey) -> bool:
        """Probe whether the chord is owned by another app (PowerToys, Windows
        Terminal quake, …) via a throwaway RegisterHotKey."""
        return _probe_register_hotkey(hotkey)

    # -- raw capture for the shortcut recorder ----------------------------

    def begin_recording(self, callback: Callable[[Hotkey], None]) -> None:
        self._recorder = callback
        self._ensure_hook()

    def end_recording(self) -> None:
        self._recorder = None

    # -- the hook --------------------------------------------------------

    def _ensure_hook(self) -> None:
        if self._installed or not IS_WINDOWS:
            return
        import ctypes

        from ..core import winhook
        self._proc_ref = winhook.install(self._on_event)
        self._installed = self._proc_ref is not None
        if not self._installed:
            AppLog.write("hotkey: failed to install keyboard hook")

    def _on_event(self, key_code: int, is_keydown: bool, ctrl: bool, alt: bool,
                  shift: bool, win: bool) -> bool:
        """Returns True to swallow the key."""
        mods = modifiers_from_state(ctrl, alt, shift, win)
        is_modifier = key_code in _MODIFIER_VKS

        # Recorder mode: capture the chord (a non-modifier key + ≥1 modifier).
        if self._recorder is not None:
            if is_keydown and not is_modifier:
                if mods == 0:
                    return False   # let bare keys through; UI shows the hint
                hk = Hotkey(keyCode=key_code, modifiers=mods)
                cb = self._recorder
                self._recorder = None
                if cb:
                    cb(hk)
                return True
            return is_keydown or not is_modifier

        if is_modifier:
            return False

        if is_keydown:
            if self._active_chord is not None:
                # Swallow everything typed while the push-to-talk chord is held.
                return True
            for reg_id, h in list(self._handlers.items()):
                if chord_matches(h["hotkey"], key_code, mods):
                    self._active_chord = reg_id
                    try:
                        h["pressed"]()
                    except Exception:
                        pass
                    return True
            return False

        # key up
        if self._active_chord is not None:
            h = self._handlers.get(self._active_chord)
            reg = self._active_chord
            self._active_chord = None
            if h and h["hotkey"].keyCode == key_code:
                try:
                    h["released"]()
                except Exception:
                    pass
                return True
            _ = reg
            return True
        return False


def _probe_register_hotkey(hotkey: Hotkey) -> bool:
    if not IS_WINDOWS:
        return True
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    # Map our modifier bits onto MOD_* RegisterHotKey flags.
    mods = 0
    if hotkey.modifiers & MOD_CTRL:
        mods |= 0x0002
    if hotkey.modifiers & MOD_ALT:
        mods |= 0x0001
    if hotkey.modifiers & MOD_SHIFT:
        mods |= 0x0004
    if hotkey.modifiers & MOD_WIN:
        mods |= 0x0008
    probe_id = 0xBEEF
    ok = user32.RegisterHotKey(None, probe_id, mods, hotkey.keyCode)
    if ok:
        user32.UnregisterHotKey(None, probe_id)
        return True
    return False
