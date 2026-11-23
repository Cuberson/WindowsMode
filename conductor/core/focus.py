"""Best-effort Focus / Do-Not-Disturb detection (the port of the macOS
DoNotDisturb/DB/Assertions.json check).

Windows keeps Focus state in undocumented places; the practical proxy is the
per-user "notifications disabled" flag. Set CONDUCTOR_FORCE_DND=1 to simulate.
"""

from __future__ import annotations

import os
import sys


def is_do_not_disturb() -> bool:
    if os.environ.get("CONDUCTOR_FORCE_DND") == "1":
        return True
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings",
            0, winreg.KEY_READ,
        )
        try:
            value, _ = winreg.QueryValueEx(key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED")
        finally:
            winreg.CloseKey(key)
        return int(value) == 0
    except Exception:
        return False
