"""ctypes plumbing for the low-level keyboard hook (WH_KEYBOARD_LL).

Kept in its own module so the rest of the app never touches ctypes.wintypes.
The callback receives (vk_code, is_keydown, ctrl, alt, shift, win) and returns
True to swallow the key. Windows only — install() returns None elsewhere.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WH_KEYBOARD_LL = 13

VK_CONTROL = 0x11
VK_MENU = 0x12          # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C

_hook_id = None
_callback_ref: Optional[Callable] = None
_proc_ref = None


def install(callback: Callable[[int, bool, bool, bool, bool, bool], bool]):
    """Installs the hook on the calling thread (which must pump messages —
    the Qt main loop does). Returns the hook handle, or None on failure."""
    global _hook_id, _callback_ref, _proc_ref
    if not IS_WINDOWS:
        return None
    import ctypes
    import ctypes.wintypes as wt

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wt.DWORD),
            ("scanCode", wt.DWORD),
            ("flags", wt.DWORD),
            ("time", wt.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
        ]

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    HOOKPROC = ctypes.WINFUNCTYPE(
        LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM
    )

    def _proc(n_code, w_param, l_param):
        try:
            if n_code == 0:  # HC_ACTION
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                msg = int(w_param)
                if msg in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                    is_down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                    alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                    shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                    win = bool(
                        (user32.GetAsyncKeyState(VK_LWIN) | user32.GetAsyncKeyState(VK_RWIN)) & 0x8000
                    )
                    if callback(int(kb.vkCode), is_down, ctrl, alt, shift, win):
                        return 1
        except Exception:
            pass
        return user32.CallNextHookEx(_hook_id, n_code, w_param, l_param)

    _proc_ref = HOOKPROC(_proc)   # must stay referenced or the hook dies
    _callback_ref = callback
    _hook_id = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _proc_ref, kernel32.GetModuleHandleW(None), 0
    )
    return _hook_id or None


def uninstall() -> None:
    global _hook_id, _proc_ref, _callback_ref
    if not IS_WINDOWS or _hook_id is None:
        return
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.UnhookWindowsHookEx(_hook_id)
    _hook_id = None
    _proc_ref = None
    _callback_ref = None
