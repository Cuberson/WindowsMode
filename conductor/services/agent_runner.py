"""One headless CLI subprocess per session (§3.4). Both agents share this
runner; only the argv and the line parser differ. Port of AgentRunner.swift."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..core.models import AgentKind, PermissionMode
from ..core.paths import AppLog, log_for
from ..core.subprocess_ops import Subprocess
from .stream_parsers import AgentEvent, ClaudeStreamParser, CodexStreamParser

#: Sessions are headless and short-lived; anything meant to keep running must
#: be detached. (Windows wording of the macOS nohup/setsid guidance.)
SESSION_GUIDANCE = """You are run headlessly by a voice assistant; nobody can answer questions, so make sensible decisions and finish the job.
You have the user's connected tools (MCP servers: calendar, email, task managers, browsers…); use them for any
"check / look up / find / send" request and report the answer in your final sentence(s) — that text is read aloud.
If asked to run, serve, preview or open something: start servers DETACHED so they outlive this session
(e.g. `start /B python -m http.server 6000 > %TEMP%\\conductor-serve.log 2>&1` or the project's own dev server with `start /B`),
confirm the port is listening, and if asked to open it in the browser run `start http://localhost:<port>`.
End with one short sentence stating what changed and any URL.
"""


class AgentRunner:
    def __init__(self, session_id: str, agent: AgentKind,
                 on_event: Callable[[AgentEvent], None],
                 on_exit: Callable[[int, str], None]):
        self.session_id = session_id
        self.agent = agent
        self.on_event = on_event
        self.on_exit = on_exit
        self._process: Optional[Subprocess] = None
        self._log = None
        self._last_text = ""
        self._stop_presses = 0

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @staticmethod
    def arguments(agent: AgentKind, task: str, mode: PermissionMode,
                  resume: Optional[str], extra_guidance: Optional[str] = None) -> list[str]:
        agent = AgentKind(agent)          # tolerate plain strings ("claude")
        mode = PermissionMode(mode)
        guidance = SESSION_GUIDANCE + ("\n\n" + extra_guidance if extra_guidance else "")
        if agent is AgentKind.claude:
            a = ["-p", task, "--output-format", "stream-json", "--verbose",
                 "--append-system-prompt", guidance,
                 "--permission-mode", "bypassPermissions" if mode is PermissionMode.bypassPermissions else "acceptEdits"]
            # No --strict-mcp-config here: sessions must see the user's MCP servers.
            if resume:
                a += ["--resume", resume]
            return a
        # codex
        a = ["exec"]
        if resume:
            a += ["resume", resume]
        a += ["--json", "--skip-git-repo-check"]
        a += (["--dangerously-bypass-approvals-and-sandbox"] if mode is PermissionMode.bypassPermissions
              else ["-s", "workspace-write"])
        a += [task + "\n\n" + guidance]
        return a

    def start(self, executable: str, task: str, cwd: str, mode: PermissionMode,
              resume: Optional[str], extra_guidance: Optional[str] = None) -> None:
        args = self.arguments(self.agent, task, mode, resume, extra_guidance)
        from ..core.cli_locator import CLILocator

        p = Subprocess(executable=executable, arguments=args, cwd=cwd,
                       environment=CLILocator.child_environment())
        log_path = log_for(self.session_id)
        try:
            self._log = open(log_path, "a", encoding="utf-8")
        except OSError:
            self._log = None

        agent = self.agent
        log = self._log

        def on_line(line: str) -> None:
            if log:
                try:
                    log.write(line + "\n")
                    log.flush()
                except OSError:
                    pass
            parser = ClaudeStreamParser if agent is AgentKind.claude else CodexStreamParser
            events = parser.parse(line)
            if not events:
                return
            for e in events:
                if e.kind == "text":
                    self._last_text = e.text
                if e.kind == "result" and e.text:
                    self._last_text = e.text
                try:
                    self.on_event(e)
                except Exception:
                    pass

        def on_stderr(line: str) -> None:
            if log:
                try:
                    log.write("[stderr] " + line + "\n")
                    log.flush()
                except OSError:
                    pass

        def on_exit(code: int) -> None:
            if self._log:
                try:
                    self._log.close()
                except OSError:
                    pass
                self._log = None
            try:
                self.on_exit(code, self._last_text)
            except Exception:
                pass

        p.on_line = on_line
        p.on_stderr = on_stderr
        p.on_exit = on_exit
        self._process = p
        p.start()

    def stop(self) -> None:
        """First press interrupts (CTRL_BREAK → kill after 3 s); second press kills immediately."""
        self._stop_presses += 1
        if self._stop_presses >= 2:
            self.kill()
        elif self._process:
            self._process.interrupt()

    def kill(self) -> None:
        if self._process:
            self._process.kill()

    @property
    def is_running(self) -> bool:
        return self._process.is_running if self._process else False
