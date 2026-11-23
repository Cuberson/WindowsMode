"""§3.8 — plain JSON files in the per-user app-data directory.

Windows equivalent of the macOS layout:
``%APPDATA%\\Conductor\\`` (override with CONDUCTOR_DATA_DIR, which is what the
tests use so they can never clobber real projects/sessions/memory).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "Conductor"


def data_dir() -> Path:
    override = os.environ.get("CONDUCTOR_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(roaming) / APP_NAME
    else:
        base = Path.home() / ".conductor"  # dev/test convenience on non-Windows
    (base / "logs").mkdir(parents=True, exist_ok=True)
    return base


def projects_path() -> Path:
    return data_dir() / "projects.json"


def sessions_path() -> Path:
    return data_dir() / "sessions.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def memory_path() -> Path:
    return data_dir() / "memory.json"


def conversation_path() -> Path:
    return data_dir() / "conversation.json"


def logs_dir() -> Path:
    return data_dir() / "logs"


def log_for(session_id: str) -> Path:
    return logs_dir() / f"{session_id}.ndjson"


def inbox_path() -> Path:
    """URL-scheme inbox: a second launch writes here so the running instance can pick it up."""
    return data_dir() / "inbox.ndjson"


# ---------------------------------------------------------------------------
# Crash-safe JSON persistence: encode → write temp → atomic rename.
# ---------------------------------------------------------------------------

def _default(obj):
    import dataclasses
    import enum
    import uuid

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _default(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, _dt.datetime):
        return format_datetime(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (list, tuple)):
        return [_default(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _default(v) for k, v in obj.items()}
    return obj


def format_datetime(dt: _dt.datetime) -> str:
    """ISO-8601, matching Foundation's .iso8601 strategy (UTC, no fractional seconds)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(_dt.timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        dt = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


class JSONStore:
    @staticmethod
    def load_raw(path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def save_raw(value, path: Path) -> None:
        try:
            data = json.dumps(_default(value), indent=2, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                path.write_text(data, encoding="utf-8")
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Append-only diagnostic log (rotated at 1 MB).
# ---------------------------------------------------------------------------

class AppLog:
    _lock = threading.Lock()
    _handle = None
    _path: Optional[Path] = None

    @classmethod
    def write(cls, msg: str) -> None:
        with cls._lock:
            path = logs_dir() / "app.log"
            if cls._handle is None or cls._path != path:
                if cls._handle is not None:
                    try:
                        cls._handle.close()
                    except OSError:
                        pass
                    cls._handle = None
                try:
                    if path.exists() and path.stat().st_size > 1_000_000:
                        path.unlink()
                except OSError:
                    pass
                try:
                    cls._handle = open(path, "a", encoding="utf-8")
                    cls._path = path
                except OSError:
                    return
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                cls._handle.write(f"{stamp} {msg}\n")
                cls._handle.flush()
            except OSError:
                pass
