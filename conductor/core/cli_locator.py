"""Finds `claude` / `codex` on PATH and the usual extra install locations (§3.4).

Windows note: npm global installs land as ``claude.cmd`` shims in
``%APPDATA%\\npm`` — every candidate name is probed so the shims are found.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

_CANDIDATE_SUFFIXES = [".cmd", ".exe", ".bat", ""] if IS_WINDOWS else [""]


class CLILocator:
    @staticmethod
    def extra_dirs() -> list[str]:
        home = Path.home()
        dirs = [
            home / ".local" / "bin",
            home / ".bun" / "bin",
            home / ".volta" / "bin",
            home / ".codex" / "bin",
            home / "scoop" / "shims",
        ]
        if IS_WINDOWS:
            appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
            local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
            dirs += [
                appdata / "npm",
                local / "Programs" / "nodejs",
                Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "nodejs",
                home / ".npm-global" / "bin",
            ]
        else:
            dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin"), Path("/bin")]
        return [str(d) for d in dirs]

    @staticmethod
    def search_dirs() -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        raw = os.environ.get("PATH", "")
        parts = raw.split(os.pathsep) if raw else []
        for d in parts + CLILocator.extra_dirs():
            if d and d not in seen:
                seen.add(d)
                out.append(d)
        return out

    @staticmethod
    def search_path() -> str:
        return os.pathsep.join(CLILocator.search_dirs())

    @staticmethod
    def find(name: str, override: Optional[str] = None) -> Optional[str]:
        if override and override.strip() and os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        # Fast path: shutil.which with the widened PATH.
        widened = CLILocator.search_path()
        for suffix in _CANDIDATE_SUFFIXES:
            hit = shutil.which(name + suffix, path=widened)
            if hit:
                return hit
        for d in CLILocator.search_dirs():
            for suffix in _CANDIDATE_SUFFIXES:
                p = os.path.join(d, name + suffix)
                if os.path.isfile(p) and (os.access(p, os.X_OK) or suffix in (".cmd", ".bat")):
                    return p
        return None

    @staticmethod
    def child_environment() -> dict[str, str]:
        """Environment for child CLIs: inherit, widen PATH, and make sure no
        API keys leak in (§9 #9)."""
        env = dict(os.environ)
        env["PATH"] = CLILocator.search_path()
        env["HOME"] = str(Path.home())
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        return env

    @staticmethod
    def run(executable: str, arguments: list[str], cwd: Optional[str] = None,
            timeout: float = 60, extra_env: Optional[dict[str, str]] = None):
        from .subprocess_ops import run_capture
        return run_capture(executable, arguments, cwd=cwd, timeout=timeout,
                           environment=CLILocator.child_environment(), extra_env=extra_env)

    @staticmethod
    def version(executable: str) -> Optional[str]:
        code, out, err = CLILocator.run(executable, ["--version"], timeout=15)
        s = (out + err).strip()
        return s.split("\n")[0] if s else None
