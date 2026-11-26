"""Windows shell integrations: launch-at-login (HKCU Run) and the
``conductor://`` URL scheme (HKCU URL protocol), the port of the macOS
SMAppService registration + CFBundleURLTypes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from .paths import AppLog, inbox_path

IS_WINDOWS = sys.platform == "win32"


def launch_command() -> str:
    if getattr(sys, "frozen", False):        # PyInstaller build
        return f'"{sys.executable}"'
    script = Path(__file__).resolve().parents[2] / "run.pyw"
    pythonw = Path(sys.executable)
    if pythonw.name.lower() == "python.exe":
        pythonw = pythonw.with_name("pythonw.exe")
    return f'"{pythonw}" "{script}"'


def set_launch_at_login(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                winreg.SetValueEx(key, "Conductor", 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, "Conductor")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception as e:
        AppLog.write(f"launch-at-login failed: {e}")
        return False


def register_url_scheme() -> bool:
    """Registers conductor://say?text=... etc. (HKCU, per-user, no admin)."""
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        base = r"Software\Classes\conductor"
        for path, name, value in [
            (base, None, "URL:Conductor"),
            (base, "URL Protocol", ""),
            (base + r"\shell\open\command", None, launch_command() + ' "%1"'),
        ]:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
            try:
                if name is None:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            finally:
                winreg.CloseKey(key)
        return True
    except Exception as e:
        AppLog.write(f"url scheme registration failed: {e}")
        return False


def push_url_to_running_instance(url: str) -> None:
    """Second launch → hand the URL to the running instance and exit."""
    try:
        with open(inbox_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": url}) + "\n")
    except OSError:
        pass


def drain_inbox() -> list[str]:
    """Pops every queued URL from the inbox (called by the running instance)."""
    path = inbox_path()
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        path.write_text("", encoding="utf-8")
    except OSError:
        return []
    urls = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("url"):
                urls.append(str(obj["url"]))
        except json.JSONDecodeError:
            if line.startswith("conductor://"):
                urls.append(line)
    return urls
