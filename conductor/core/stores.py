"""JSON-backed stores — a 1:1 port of Stores.swift."""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .models import (
    AgentKind, ConversationTurn, Memory, Project, Session, SessionStatus, Settings,
)
from .paths import (
    JSONStore, AppLog, conversation_path, memory_path, projects_path, sessions_path,
    settings_path,
)


class _Observable:
    """Tiny listener bus so the Qt UI can refresh without polling."""

    def __init__(self) -> None:
        self._listeners: list[Callable[[], None]] = []
        self._lock = threading.RLock()

    def add_listener(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn()
            except Exception:
                pass


class SettingsStore(_Observable):
    def __init__(self) -> None:
        super().__init__()
        loaded = JSONStore.load_raw(settings_path())
        self._settings = Settings.from_dict(loaded if isinstance(loaded, dict) else None)

    @property
    def settings(self) -> Settings:
        return self._settings

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self._settings, k, v)
        self.save()

    def save(self) -> None:
        JSONStore.save_raw(self._settings.to_dict(), settings_path())
        self._notify()


class ProjectRegistry(_Observable):
    def __init__(self) -> None:
        super().__init__()
        loaded = JSONStore.load_raw(projects_path())
        self._projects = [Project.from_dict(d) for d in loaded] if isinstance(loaded, list) else []

    @property
    def projects(self) -> list[Project]:
        return self._projects

    def set_projects(self, projects: list[Project]) -> None:
        self._projects = list(projects)
        self._save()

    def add(self, p: Project) -> None:
        self._projects.append(p)
        self._save()

    def remove(self, project_id: str) -> None:
        self._projects = [p for p in self._projects if p.id != project_id]
        self._save()

    def update(self, p: Project) -> None:
        for i, q in enumerate(self._projects):
            if q.id == p.id:
                self._projects[i] = p
                break
        self._save()

    def resolve(self, name: Optional[str]) -> Optional[Project]:
        """Exact name, then alias, then case-insensitive substring."""
        if not name or not name.strip():
            return None
        key = name.strip().lower()
        for p in self._projects:
            if p.name.lower() == key:
                return p
        for p in self._projects:
            if any(a.lower() == key for a in p.aliases):
                return p
        # Fuzzy: whole-word containment either way, preferring the longest
        # (most specific) project name.
        q = _words(key)

        def words(x: str) -> set[str]:
            return _words(x)

        candidates = []
        for p in self._projects:
            pw = words(p.name.lower())
            if not pw:
                continue
            if pw.issubset(q) or q.issubset(pw) or any(words(a.lower()).issubset(q) for a in p.aliases):
                candidates.append(p)
        if not candidates:
            return None
        best = candidates[0]
        for p in candidates[1:]:
            if len(words(p.name)) > len(words(best.name)):
                best = p
        return best

    def _save(self) -> None:
        JSONStore.save_raw([p.to_dict() if hasattr(p, "to_dict") else _project_dict(p) for p in self._projects], projects_path())
        self._notify()

    @property
    def prompt_summary(self) -> str:
        """Summary block for the orchestrator prompt (§4.1)."""
        if not self._projects:
            return "- (none registered yet)"
        return "\n".join(
            f"- {p.name} · {p.path} · [{', '.join(p.aliases)}] · {p.defaultAgent.value}"
            for p in self._projects
        )

    @staticmethod
    def suggested_name(path: str | Path) -> str:
        return Path(path).name.replace("-", " ").replace("_", " ")


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id, "name": p.name, "path": p.path, "aliases": list(p.aliases),
        "defaultAgent": p.defaultAgent.value, "permissionMode": p.permissionMode.value,
    }


def _words(x: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", x.lower()) if w}


class SessionStore(_Observable):
    MAX_SESSIONS = 100

    def __init__(self) -> None:
        super().__init__()
        loaded_raw = JSONStore.load_raw(sessions_path())
        loaded = [Session.from_dict(d) for d in loaded_raw] if isinstance(loaded_raw, list) else []
        # Anything marked running at launch was orphaned by a previous crash —
        # kill + mark failed (§10.7).
        from .subprocess_ops import Subprocess
        changed = False
        out = []
        for s in loaded:
            if s.status == SessionStatus.running:
                if s.pid and Subprocess.is_alive(s.pid):
                    Subprocess.kill_group(s.pid)
                s.status = SessionStatus.failed
                s.finishedAt = s.finishedAt or datetime.now(timezone.utc)
                s.activity = "Interrupted by app restart"
                changed = True
            out.append(s)
        self._sessions = out
        counters = []
        for s in loaded:
            m = re.match(r"^s_(\d+)$", s.id)
            if m:
                counters.append(int(m.group(1)))
        self._counter = max(counters) if counters else 0
        if changed:
            self._save()

    @property
    def sessions(self) -> list[Session]:
        return self._sessions

    @property
    def running(self) -> list[Session]:
        return [s for s in self._sessions if s.status == SessionStatus.running]

    @property
    def visible(self) -> list[Session]:
        vis = [s for s in self._sessions if not s.dismissed]
        return sorted(vis, key=lambda s: (not s.status.is_active, -s.startedAt.timestamp()))

    def next_id(self) -> str:
        self._counter += 1
        return f"s_{self._counter:02d}"

    def insert(self, s: Session) -> None:
        self._sessions.insert(0, s)
        self._trim_and_save()

    def update(self, session_id: str, mutate: Callable[[Session], None]) -> None:
        for s in self._sessions:
            if s.id == session_id:
                mutate(s)
                self._trim_and_save()
                return

    def session(self, session_id: str) -> Optional[Session]:
        for s in self._sessions:
            if s.id == session_id:
                return s
        return None

    def dismiss(self, session_id: str) -> None:
        self.update(session_id, lambda s: setattr(s, "dismissed", True))

    def clear_finished(self) -> None:
        for s in self._sessions:
            if not s.status.is_active:
                self.dismiss(s.id)

    def _trim_and_save(self) -> None:
        if len(self._sessions) > self.MAX_SESSIONS:
            self._sessions = self._sessions[: self.MAX_SESSIONS]
        self._save()

    def _save(self) -> None:
        JSONStore.save_raw([_session_dict(s) for s in self._sessions], sessions_path())
        self._notify()

    @property
    def prompt_summary(self) -> str:
        """Summary block for the orchestrator prompt (§4.1)."""
        recent = self._sessions[:8]
        if not recent:
            return "- (none)"
        return "\n".join(
            f'- {s.id} · {s.projectName} · {s.agent.value} · {s.status.value} · "{s.task[:60]}" · {format_elapsed(s.elapsed)}'
            for s in recent
        )

    @staticmethod
    def format(t: float) -> str:
        return format_elapsed(t)


def _session_dict(s: Session) -> dict:
    from .paths import format_datetime
    return {
        "id": s.id, "projectName": s.projectName, "projectPath": s.projectPath,
        "agent": s.agent.value, "task": s.task, "status": s.status.value,
        "activity": s.activity, "startedAt": format_datetime(s.startedAt),
        "finishedAt": format_datetime(s.finishedAt) if s.finishedAt else None,
        "agentSessionID": s.agentSessionID, "resultText": s.resultText,
        "pid": s.pid, "dismissed": s.dismissed,
    }


def format_elapsed(t: float) -> str:
    s = int(t)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


class MemoryStore(_Observable):
    """Long-term memory (§ memory): facts the user asked Conductor to keep,
    plus a short rolling conversation history. Facts are injected into every
    orchestrator turn and into every coding-agent session; turns only into
    the orchestrator."""

    max_memories = 200
    max_turns = 12

    def __init__(self) -> None:
        super().__init__()
        m_raw = JSONStore.load_raw(memory_path())
        self._memories = [Memory.from_dict(d) for d in m_raw] if isinstance(m_raw, list) else []
        t_raw = JSONStore.load_raw(conversation_path())
        self._turns = [ConversationTurn.from_dict(d) for d in t_raw] if isinstance(t_raw, list) else []

    @property
    def memories(self) -> list[Memory]:
        return self._memories

    @property
    def turns(self) -> list[ConversationTurn]:
        return self._turns

    def remember(self, raw: str) -> None:
        """Adds a fact; near-duplicates (case-insensitive) are replaced so the
        list never accumulates repeats."""
        text = (raw or "").strip()
        if not text:
            return
        self._memories = [m for m in self._memories if m.text.lower() != text.lower()]
        self._memories.append(Memory(text=text))
        if len(self._memories) > self.max_memories:
            self._memories = self._memories[-self.max_memories:]
        AppLog.write(f"memory +: {text}")
        self._save()

    def forget(self, phrase: str) -> int:
        """Removes memories matching the phrase (case-insensitive substring,
        either direction). Returns how many were dropped."""
        q = (phrase or "").strip().lower()
        if not q:
            return 0
        before = len(self._memories)
        self._memories = [
            m for m in self._memories
            if not (m.text.lower() in q or q in m.text.lower())
        ]
        removed = before - len(self._memories)
        AppLog.write(f"memory -: {phrase} ({removed} removed)")
        self._save()
        return removed

    def remove(self, memory_id: str) -> None:
        self._memories = [m for m in self._memories if m.id != memory_id]
        self._save()

    def clear_memories(self) -> None:
        self._memories = []
        self._save()

    def clear_turns(self) -> None:
        self._turns = []
        self._save()

    def record(self, heard: str, said: str, action: str,
               task: Optional[str] = None, project: Optional[str] = None) -> None:
        self._turns.append(ConversationTurn(heard=heard, said=said, action=action, task=task, project=project))
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns:]
        self._save()

    def _save(self) -> None:
        JSONStore.save_raw(
            [{"id": m.id, "text": m.text, "createdAt": _iso(m.createdAt)} for m in self._memories],
            memory_path(),
        )
        JSONStore.save_raw(
            [{"at": _iso(t.at), "heard": t.heard, "said": t.said, "action": t.action,
              "task": t.task, "project": t.project} for t in self._turns],
            conversation_path(),
        )
        self._notify()

    @property
    def prompt_summary(self) -> str:
        """Block for the orchestrator prompt."""
        if not self._memories:
            return "- (nothing saved yet)"
        return "\n".join(f"- {m.text}" for m in self._memories)

    @property
    def turns_summary(self) -> str:
        """Recent exchanges, oldest first, for the orchestrator prompt."""
        if not self._turns:
            return "- (none)"
        lines = []
        for t in self._turns:
            line = f'- [{relative_time(t.at)}] heard: "{t.heard}" → {t.action}'
            if t.project:
                line += f' project="{t.project}"'
            if t.task:
                line += f' task="{t.task}"'
            if t.said:
                line += f' · said: "{t.said}"'
            lines.append(line)
        return "\n".join(lines)

    @property
    def agent_guidance(self) -> Optional[str]:
        """Text appended to coding-agent sessions so they honour the user's
        standing preferences."""
        if not self._memories:
            return None
        return (
            "Standing preferences the developer has told the assistant to remember "
            "(honour any that apply; ignore the rest):\n"
            + "\n".join(f"- {m.text}" for m in self._memories)
        )


def _iso(dt: datetime) -> str:
    from .paths import format_datetime
    return format_datetime(dt)


def relative_time(then: datetime, now: Optional[datetime] = None) -> str:
    """RelativeDateTimeFormatter(.abbreviated) equivalent: 'just now', '5m ago', '3h ago'."""
    now = now or datetime.now(timezone.utc)
    secs = max(0, int((now - then).total_seconds()))
    if secs < 45:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"
