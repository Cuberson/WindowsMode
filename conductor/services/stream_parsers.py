"""Events normalised across both agents + the NDJSON stream parsers —
a 1:1 port of StreamParsers.swift, written against the same fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AgentEvent:
    """kind: 'sessionID' | 'activity' | 'text' | 'needsInput' | 'result'"""
    kind: str
    text: str = ""
    is_error: bool = False

    @staticmethod
    def session_id(sid: str) -> "AgentEvent":
        return AgentEvent("sessionID", sid)

    @staticmethod
    def activity(a: str) -> "AgentEvent":
        return AgentEvent("activity", a)

    @staticmethod
    def text(t: str) -> "AgentEvent":
        return AgentEvent("text", t)

    @staticmethod
    def needs_input() -> "AgentEvent":
        return AgentEvent("needsInput")

    @staticmethod
    def result(text: str, is_error: bool) -> "AgentEvent":
        return AgentEvent("result", text, is_error)


def _loads(line: str) -> Optional[dict]:
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _short_path(p: str) -> str:
    parts = [x for x in p.replace("\\", "/").split("/") if x]
    return "/".join(parts[-3:])


def _describe_tool(name: str, inp: dict) -> str:
    if isinstance(inp.get("file_path"), str):
        return f"{name} {_short_path(inp['file_path'])}"
    if isinstance(inp.get("command"), str):
        return f"Run {inp['command'][:60]}"
    if isinstance(inp.get("pattern"), str):
        return f"{name} {inp['pattern'][:40]}"
    if isinstance(inp.get("query"), str):
        return f"{name} {inp['query'][:40]}"
    if isinstance(inp.get("description"), str):
        return f"{name} {inp['description'][:50]}"
    return name


class ClaudeStreamParser:
    """Parser for `claude -p --output-format stream-json --verbose` NDJSON."""

    @staticmethod
    def parse(line: str) -> list[AgentEvent]:
        obj = _loads(line)
        if obj is None:
            return []
        events: list[AgentEvent] = []
        typ = obj.get("type") or ""

        if typ == "system":
            if obj.get("subtype") == "init" and isinstance(obj.get("session_id"), str):
                events.append(AgentEvent.session_id(obj["session_id"]))
            detail = obj.get("detail")
            if obj.get("subtype") == "task_summary" and isinstance(detail, str) and detail:
                events.append(AgentEvent.activity(detail))

        elif typ == "assistant":
            msg = obj.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "tool_use":
                        name = block.get("name") or "Tool"
                        inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                        events.append(AgentEvent.activity(_describe_tool(name, inp)))
                    elif btype == "text":
                        t = block.get("text")
                        if isinstance(t, str) and t:
                            events.append(AgentEvent.text(t))

        elif typ == "result":
            is_error = bool(obj.get("is_error", False))
            text = obj.get("result")
            if not isinstance(text, str):
                text = obj.get("subtype") or ""
            sid = obj.get("session_id")
            if isinstance(sid, str):
                events.append(AgentEvent.session_id(sid))
            denials = obj.get("permission_denials")
            if isinstance(denials, list) and denials:
                events.append(AgentEvent.needs_input())
            events.append(AgentEvent.result(text, is_error))

        return events


class CodexStreamParser:
    """Parser for `codex exec --json` JSONL (codex-cli 0.147)."""

    @staticmethod
    def parse(line: str) -> list[AgentEvent]:
        obj = _loads(line)
        if obj is None:
            return []
        typ = obj.get("type") or ""

        if typ == "thread.started":
            tid = obj.get("thread_id")
            if isinstance(tid, str):
                return [AgentEvent.session_id(tid)]
            return []

        if typ in ("item.started", "item.completed"):
            item = obj.get("item")
            if not isinstance(item, dict):
                return []
            itype = item.get("type")
            if itype == "agent_message":
                t = item.get("text")
                if isinstance(t, str) and t:
                    return [AgentEvent.text(t)]
            elif itype == "file_change":
                changes = item.get("changes") if isinstance(item.get("changes"), list) else []
                paths = [c.get("path") for c in changes if isinstance(c, dict) and isinstance(c.get("path"), str)]
                if paths:
                    short = "/".join(paths[0].replace("\\", "/").split("/")[-2:])
                    return [AgentEvent.activity(f"Edit {short}")]
            elif itype == "command_execution":
                c = item.get("command")
                if isinstance(c, str):
                    return [AgentEvent.activity(f"Run {c[:60]}")]
            elif itype == "reasoning":
                return [AgentEvent.activity("Thinking…")]
            return []

        if typ == "turn.completed":
            return [AgentEvent.result("", False)]

        if typ in ("turn.failed", "error"):
            err = obj.get("error")
            msg = err.get("message") if isinstance(err, dict) else None
            if not isinstance(msg, str):
                msg = obj.get("message") if isinstance(obj.get("message"), str) else "Codex error"
            return [AgentEvent.result(msg, True)]

        return []
