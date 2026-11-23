"""Core data model — a 1:1 port of Models.swift.

JSON keys match the macOS app exactly (camelCase), so an existing Conductor
data folder could be copied over wholesale.
"""

from __future__ import annotations

import dataclasses
import enum
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .paths import parse_datetime


# MARK: - Agents

class AgentKind(str, enum.Enum):
    claude = "claude"
    codex = "codex"

    @property
    def display_name(self) -> str:
        return "Claude" if self is AgentKind.claude else "Codex"

    @property
    def id(self) -> str:
        return self.value


class PermissionMode(str, enum.Enum):
    #: Claude: `--permission-mode acceptEdits` · Codex: `-s workspace-write`
    acceptEdits = "acceptEdits"
    #: Claude: `--permission-mode bypassPermissions` · Codex: `--dangerously-bypass-approvals-and-sandbox`
    bypassPermissions = "bypassPermissions"

    @property
    def display_name(self) -> str:
        return "Accept edits" if self is PermissionMode.acceptEdits else "Bypass permissions"

    @property
    def id(self) -> str:
        return self.value


# MARK: - Helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def from_dict(cls, d: dict | None, **overrides):
    """Tolerant dataclass decode: unknown keys ignored, missing keys keep defaults."""
    if not isinstance(d, dict):
        d = {}
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in d:
            kwargs[f.name] = d[f.name]
    kwargs.update(overrides)
    return cls(**kwargs)


# MARK: - Projects

@dataclass
class Project:
    id: str = field(default_factory=_new_id)
    name: str = ""
    path: str = ""
    aliases: list[str] = field(default_factory=list)
    defaultAgent: AgentKind = AgentKind.claude
    permissionMode: PermissionMode = PermissionMode.bypassPermissions

    @property
    def url(self) -> Path:
        return Path(self.path).expanduser()

    @classmethod
    def from_dict(cls, d: dict | None) -> "Project":
        if not isinstance(d, dict):
            d = {}
        return cls(
            id=d.get("id") or _new_id(),
            name=str(d.get("name", "")),
            path=str(d.get("path", "")),
            aliases=[str(a) for a in d.get("aliases", []) if a],
            defaultAgent=_enum(AgentKind, d.get("defaultAgent"), AgentKind.claude),
            permissionMode=_enum(PermissionMode, d.get("permissionMode"), PermissionMode.bypassPermissions),
        )


# MARK: - Sessions

class SessionStatus(str, enum.Enum):
    running = "running"
    done = "done"
    needsInput = "needsInput"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_active(self) -> bool:
        return self is SessionStatus.running


@dataclass
class Session:
    id: str                       # short id like "s_01"
    projectName: str
    projectPath: str
    agent: AgentKind
    task: str
    status: SessionStatus = SessionStatus.running
    activity: str = ""            # e.g. "Edit src/Hero.tsx"
    startedAt: datetime = field(default_factory=_now)
    finishedAt: Optional[datetime] = None
    agentSessionID: Optional[str] = None   # claude session_id / codex thread_id, for --resume
    resultText: str = ""          # final agent result (truncated)
    pid: Optional[int] = None
    dismissed: bool = False

    @property
    def elapsed(self) -> float:
        end = self.finishedAt or _now()
        return max(0.0, (end - self.startedAt).total_seconds())

    @classmethod
    def from_dict(cls, d: dict | None) -> "Session":
        if not isinstance(d, dict):
            d = {}
        pid = d.get("pid")
        return cls(
            id=str(d.get("id", "")),
            projectName=str(d.get("projectName", "")),
            projectPath=str(d.get("projectPath", "")),
            agent=_enum(AgentKind, d.get("agent"), AgentKind.claude),
            task=str(d.get("task", "")),
            status=_enum(SessionStatus, d.get("status"), SessionStatus.running),
            activity=str(d.get("activity", "")),
            startedAt=parse_datetime(d.get("startedAt")) or _now(),
            finishedAt=parse_datetime(d.get("finishedAt")),
            agentSessionID=d.get("agentSessionID") or None,
            resultText=str(d.get("resultText", "")),
            pid=int(pid) if isinstance(pid, (int, float)) else None,
            dismissed=bool(d.get("dismissed", False)),
        )


# MARK: - Orchestrator contract (§4.2)

class OrchestratorActionKind(str, enum.Enum):
    spawn = "spawn"
    followup = "followup"
    cancel = "cancel"
    status = "status"
    open = "open"
    clarify = "clarify"
    chitchat = "chitchat"
    create = "create"


@dataclass
class OrchestratorAction:
    action: OrchestratorActionKind
    agent: Optional[AgentKind] = None
    project: Optional[str] = None
    session_id: Optional[str] = None
    task: Optional[str] = None
    speak: str = ""
    #: A durable fact/preference to store in long-term memory. None = nothing new.
    remember: Optional[str] = None
    #: A phrase identifying a memory to delete. None = nothing to forget.
    forget: Optional[str] = None

    JSON_SCHEMA = (
        '{"type":"object","additionalProperties":false,"properties":'
        '{"action":{"type":"string","enum":["spawn","followup","cancel","status","open","clarify","chitchat","create"]},'
        '"agent":{"type":["string","null"],"enum":["claude","codex",null]},'
        '"project":{"type":["string","null"]},"session_id":{"type":["string","null"]},'
        '"task":{"type":["string","null"]},"speak":{"type":"string"},'
        '"remember":{"type":["string","null"]},"forget":{"type":["string","null"]}},'
        '"required":["action","agent","project","session_id","task","speak","remember","forget"]}'
    )

    @classmethod
    def from_dict(cls, d: dict | None) -> Optional["OrchestratorAction"]:
        if not isinstance(d, dict):
            return None
        raw_action = d.get("action")
        try:
            action = OrchestratorActionKind(raw_action)
        except (TypeError, ValueError):
            return None
        return cls(
            action=action,
            agent=_enum(AgentKind, d.get("agent"), None),
            project=_opt_str(d.get("project")),
            session_id=_opt_str(d.get("session_id")),
            task=_opt_str(d.get("task")),
            speak=str(d.get("speak", "")),
            remember=_opt_str(d.get("remember")),
            forget=_opt_str(d.get("forget")),
        )

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "agent": self.agent.value if self.agent else None,
            "project": self.project,
            "session_id": self.session_id,
            "task": self.task,
            "speak": self.speak,
            "remember": self.remember,
            "forget": self.forget,
        }

    def __str__(self) -> str:  # for logs (AppLog prints `→ \(action)`)
        return f"{self.action.value}(project={self.project!r}, session={self.session_id!r}, task={self.task!r})"


# MARK: - Memory

@dataclass
class Memory:
    id: str = field(default_factory=_new_id)
    text: str = ""
    createdAt: datetime = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Memory":
        if not isinstance(d, dict):
            d = {}
        return cls(
            id=d.get("id") or _new_id(),
            text=str(d.get("text", "")),
            createdAt=parse_datetime(d.get("createdAt")) or _now(),
        )


@dataclass
class ConversationTurn:
    at: datetime = field(default_factory=_now)
    heard: str = ""
    said: str = ""
    action: str = ""
    task: Optional[str] = None
    project: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict | None) -> "ConversationTurn":
        if not isinstance(d, dict):
            d = {}
        return cls(
            at=parse_datetime(d.get("at")) or _now(),
            heard=str(d.get("heard", "")),
            said=str(d.get("said", "")),
            action=str(d.get("action", "")),
            task=_opt_str(d.get("task")),
            project=_opt_str(d.get("project")),
        )


# MARK: - Settings

#: Windows virtual-key + modifier mask. Modifiers: ctrl=1, alt=2, shift=4, win=8.
MOD_CTRL = 1
MOD_ALT = 2
MOD_SHIFT = 4
MOD_WIN = 8

VK_SPACE = 0x20
VK_ESCAPE = 0x1B
VK_O = 0x4F


@dataclass
class Hotkey:
    keyCode: int = VK_SPACE
    modifiers: int = MOD_CTRL | MOD_SHIFT

    @staticmethod
    def push_to_talk() -> "Hotkey":
        return Hotkey(VK_SPACE, MOD_CTRL | MOD_SHIFT)   # Ctrl+Shift+Space

    @staticmethod
    def overlay() -> "Hotkey":
        return Hotkey(VK_O, MOD_CTRL | MOD_SHIFT)       # Ctrl+Shift+O

    @classmethod
    def from_dict(cls, d: dict | None) -> "Hotkey":
        if not isinstance(d, dict):
            return cls()
        try:
            return cls(keyCode=int(d.get("keyCode", VK_SPACE)), modifiers=int(d.get("modifiers", 0)))
        except (TypeError, ValueError):
            return cls()

    def to_dict(self) -> dict:
        return {"keyCode": self.keyCode, "modifiers": self.modifiers}

    def __eq__(self, other) -> bool:
        return isinstance(other, Hotkey) and (self.keyCode, self.modifiers) == (other.keyCode, other.modifiers)

    def __hash__(self) -> int:
        return hash((self.keyCode, self.modifiers))


@dataclass
class Settings:
    pushToTalk: Hotkey = field(default_factory=Hotkey.push_to_talk)
    overlayToggle: Hotkey = field(default_factory=Hotkey.overlay)
    launchAtLogin: bool = False
    overlayOpacity: float = 1.0
    speakSummaries: bool = True
    muteDuringFocus: bool = True
    blipOnChordDown: bool = True
    defaultAgent: AgentKind = AgentKind.claude
    #: Headless sessions cannot answer permission prompts, so "bypass" is the
    #: only mode where shell commands actually run.
    claudePermissionMode: PermissionMode = PermissionMode.bypassPermissions
    codexPermissionMode: PermissionMode = PermissionMode.bypassPermissions
    maxConcurrentSessions: int = 6
    fishVoiceID: str = "933563129e564b19a115bedd57b7406a"  # "Sarah"
    fishVoiceName: str = "Sarah"
    #: "s2.1-pro" bills Fish API credit (USD); "s2.1-pro-free" is $0. "auto" tries pro, falls back to free on 402.
    fishModel: str = "auto"
    speakingRate: float = 1.0
    systemVoiceFallback: bool = True
    overlayOrigin: Optional[dict] = None   # {"x": .., "y": ..}
    overlayVisible: bool = True
    onboardingComplete: bool = False
    #: Where voice-created projects are made (§ create action).
    projectsRoot: str = "~/Projects"
    claudePathOverride: Optional[str] = None
    codexPathOverride: Optional[str] = None
    #: Speech-to-text backend: "auto" (Windows recognizer → Vosk), "windows", "vosk".
    sttBackend: str = "auto"

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        if not isinstance(d, dict):
            return cls()
        s = cls()
        for f in dataclasses.fields(cls):
            if f.name not in d or d[f.name] is None:
                continue
            raw = d[f.name]
            try:
                if f.name in ("pushToTalk", "overlayToggle"):
                    setattr(s, f.name, Hotkey.from_dict(raw))
                elif f.name == "defaultAgent":
                    setattr(s, f.name, _enum(AgentKind, raw, s.defaultAgent))
                elif f.name in ("claudePermissionMode", "codexPermissionMode"):
                    setattr(s, f.name, _enum(PermissionMode, raw, PermissionMode.bypassPermissions))
                elif f.name in ("claudePathOverride", "codexPathOverride"):
                    setattr(s, f.name, str(raw) or None)
                elif f.name == "overlayOrigin":
                    if isinstance(raw, dict) and "x" in raw and "y" in raw:
                        setattr(s, f.name, {"x": float(raw["x"]), "y": float(raw["y"])})
                elif f.name in ("overlayOpacity", "speakingRate"):
                    setattr(s, f.name, float(raw))
                elif f.name == "maxConcurrentSessions":
                    setattr(s, f.name, int(raw))
                elif f.name == "launchAtLogin":
                    setattr(s, f.name, bool(raw))
                else:
                    setattr(s, f.name, raw if isinstance(raw, type(getattr(s, f.name))) else raw)
            except (TypeError, ValueError):
                continue
        return s

    def to_dict(self) -> dict:
        d = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Hotkey):
                d[f.name] = v.to_dict()
            elif isinstance(v, enum.Enum):
                d[f.name] = v.value
            else:
                d[f.name] = v
        return d


# MARK: - small decode helpers

def _enum(cls, raw, default):
    try:
        return cls(raw)
    except (TypeError, ValueError):
        return default


def _opt_str(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
