"""Secrets live only in the Windows Credential Manager (§3.7, §3.8).

Backed by the `keyring` package (WinCred on Windows) — the exact equivalent of
the macOS Keychain item `ai.conductor.app`.
"""

from __future__ import annotations

from typing import Optional

from .paths import AppLog

SERVICE = "ai.conductor.app"
FISH_KEY = "fish-audio-api-key"

_backend_error: Optional[str] = None


def _keyring():
    global _backend_error
    try:
        import keyring
        return keyring
    except Exception as e:  # pragma: no cover - environment dependent
        _backend_error = str(e)
        return None


def get(account: str) -> Optional[str]:
    kr = _keyring()
    if kr is None:
        return None
    try:
        value = kr.get_password(SERVICE, account)
    except Exception as e:
        AppLog.write(f"credential read {account} failed: {e}")
        return None
    return value or None


def set_(value: str, account: str) -> bool:
    kr = _keyring()
    if kr is None:
        AppLog.write(f"credential write {account} failed: no keyring backend")
        return False
    try:
        kr.set_password(SERVICE, account, value)
        return True
    except Exception as e:
        AppLog.write(f"credential write {account} failed: {e}")
        return False


def delete(account: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, account)
    except Exception:
        pass
