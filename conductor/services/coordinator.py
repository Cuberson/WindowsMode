"""Central state machine (§2). Owns the services and drives the pill + overlay.
Port of Coordinator.swift."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..core import audio, focus
from ..core.models import (
    AgentKind, OrchestratorAction, OrchestratorActionKind, Project,
    Session, SessionStatus,
)
from ..core.paths import AppLog, JSONStore, log_for, logs_dir, sessions_path
from ..core.subprocess_ops import Subprocess
from ..core.cli_locator import CLILocator
from .agent_runner import AgentRunner
from .hotkey import HotkeyMonitor, hotkey_display
from .orchestrator import Orchestrator
from .speech import SpeechService
from .stream_parsers import AgentEvent
from .voice import VoiceService, strip_cues


class PillState:
    listening = "listening"
    thinking = "thinking"
    speaking = "speaking"
    clarify = "clarify"
    error = "error"


class PillModel:
    def __init__(self) -> None:
        self.state = PillState.listening
        self.transcript = ""
        self.secondary = ""      # clarify question / error text
        self.level = 0.0
        self.fallback_badge = False
        self.visible = False
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass


class SpawnFailure:
    MISSING_CLI = "missingCLI"
    MISSING_FOLDER = "missingFolder"
    LAUNCH = "launch"


class Coordinator:
    def __init__(self, post: Optional[Callable[[Callable[[], None]], None]] = None) -> None:
        from ..core.stores import MemoryStore, ProjectRegistry, SessionStore, SettingsStore

        self._post = post or (lambda fn: fn())
        self.settings = SettingsStore()
        self.registry = ProjectRegistry()
        self.sessions = SessionStore()
        self.memory = MemoryStore()
        self.speech = SpeechService(backend=self.settings.settings.sttBackend)
        self.voice = VoiceService(self.settings)
        self.voice.on_finished = lambda: self._post(self.did_finish_speaking)
        self.pill = PillModel()

        self.runners: dict[str, AgentRunner] = {}
        self.clarify_context: Optional[str] = None
        self.hold_start: Optional[datetime] = None
        self._debounce: Optional[threading.Timer] = None
        self.listening_active = False
        self._hide_task: Optional[threading.Timer] = None
        self._blip_wav = audio.blip_wav()
        self._ptt_id: Optional[int] = None
        self._overlay_id: Optional[int] = None
        self._esc_id: Optional[int] = None
        #: Bumped by Esc so an in-flight orchestrator turn's result is dropped
        #: instead of spoken.
        self.turn_generation = 0
        self.hotkey_error: Optional[str] = None
        self.pending_followups: dict[str, list[str]] = {}
        self.last_spawn_failure: Optional[str] = None

        self.on_pill_changed: Optional[Callable[[], None]] = None
        self.on_overlay_toggle: Optional[Callable[[], None]] = None
        self.on_level_changed: Optional[Callable[[], None]] = None

        self._turn_queue: list[str] = []
        self._turn_cv = threading.Condition()
        threading.Thread(target=self._orchestrator_loop, daemon=True).start()

        self.register_hotkeys()
        self._rotate_logs()

    # MARK: hotkeys

    def _pill_did_change(self) -> None:
        if self.on_pill_changed:
            self.on_pill_changed()
        self._sync_escape_hotkey()

    def _sync_escape_hotkey(self) -> None:
        """Esc only exists as a hotkey while the pill is showing, so it never
        steals Esc from other apps."""
        from ..core.models import Hotkey, VK_ESCAPE

        monitor = HotkeyMonitor.shared()
        if self.pill.visible and self._esc_id is None:
            self._esc_id = monitor.register(
                Hotkey(keyCode=VK_ESCAPE, modifiers=0),
                pressed=lambda: self._post(self.reset_conversation),
            )
        elif not self.pill.visible and self._esc_id is not None:
            monitor.unregister(self._esc_id)
            self._esc_id = None

    def reset_conversation(self) -> None:
        """Esc: abandon whatever is happening in the voice loop and start a
        fresh chat. Coding sessions are untouched."""
        AppLog.write("escape: reset conversation")
        self.turn_generation += 1
        self.voice.stop()
        if self.speech.is_listening:
            threading.Thread(target=self.speech.cancel, daemon=True).start()
        self.listening_active = False
        self.hold_start = None
        if self._debounce:
            self._debounce.cancel()
            self._debounce = None
        if self._hide_task:
            self._hide_task.cancel()
        self.clarify_context = None
        self.memory.record(heard="(pressed Esc — cancelled that exchange)", said="", action="cancelled")
        self.pill.visible = False
        self.pill.secondary = ""
        self.pill.transcript = ""
        self.pill.state = PillState.listening
        self._pill_did_change()

    @property
    def claude_path(self) -> Optional[str]:
        return CLILocator.find("claude", override=self.settings.settings.claudePathOverride)

    @property
    def codex_path(self) -> Optional[str]:
        return CLILocator.find("codex", override=self.settings.settings.codexPathOverride)

    def register_hotkeys(self) -> None:
        monitor = HotkeyMonitor.shared()
        monitor.unregister(self._ptt_id)
        monitor.unregister(self._overlay_id)
        s = self.settings.settings
        self._ptt_id = monitor.register(
            s.pushToTalk,
            pressed=lambda: self._post(self.chord_down),
            released=lambda: self._post(self.chord_up),
        )
        self._overlay_id = monitor.register(
            s.overlayToggle,
            pressed=lambda: (self.on_overlay_toggle and self.on_overlay_toggle()),
        )
        AppLog.write(f"hotkeys: ptt={self._ptt_id} overlay={self._overlay_id}")
        if self._ptt_id is None:
            self.hotkey_error = f"{hotkey_display(s.pushToTalk)} could not be registered — change it in Settings."
        elif HotkeyMonitor.can_register(s.pushToTalk) is False:
            self.hotkey_error = f"{hotkey_display(s.pushToTalk)} is owned by another app — change it in Settings."
        else:
            self.hotkey_error = None

    def unregister_push_to_talk(self) -> None:
        HotkeyMonitor.shared().unregister(self._ptt_id)
        self._ptt_id = None

    # MARK: push-to-talk (§3.6 semantics)

    def chord_down(self) -> None:
        AppLog.write("chord down")
        self.hold_start = datetime.now(timezone.utc)
        if self.voice.is_speaking:
            self.voice.stop()          # barge-in
        if self._debounce:
            self._debounce.cancel()

        def fire():
            self._post(lambda: self._begin_listening_if_held())

        self._debounce = threading.Timer(0.15, fire)
        self._debounce.start()

    def _begin_listening_if_held(self) -> None:
        if self.hold_start is None:
            return
        self.begin_listening()

    def chord_up(self) -> None:
        AppLog.write(f"chord up (listening={self.listening_active})")
        started = self.hold_start
        self.hold_start = None
        if self._debounce:
            self._debounce.cancel()
            self._debounce = None
        if started is None:
            return
        held = (datetime.now(timezone.utc) - started).total_seconds()
        if held >= 0.15 and self.listening_active:
            threading.Thread(target=self._finish_listening_thread, daemon=True).start()

    def begin_listening(self) -> None:
        self.listening_active = True
        if self._hide_task:
            self._hide_task.cancel()
            self._hide_task = None
        if self.settings.settings.blipOnChordDown:
            audio.play_blip(self._blip_wav)
        self.pill.state = PillState.listening
        self.pill.transcript = ""
        self.pill.secondary = self.clarify_context or ""
        self.pill.fallback_badge = False
        self.pill.visible = True
        self._pill_did_change()
        self.speech.start()
        AppLog.write(f"stt start error={self.speech.error or 'none'}")
        if self.speech.error:
            self._show_error(self.speech.error)
            self.listening_active = False
            return
        self._start_level_updates()

    def _start_level_updates(self) -> None:
        def loop():
            while self.speech.is_listening:
                self._post(self._apply_level)
                threading.Event().wait(0.05)
        threading.Thread(target=loop, daemon=True).start()

    def _apply_level(self) -> None:
        self.pill.level = self.speech.level
        self.pill.transcript = self.speech.transcript
        if self.on_level_changed:
            self.on_level_changed()

    @staticmethod
    def normalize_transcript(t: str) -> str:
        """Fix the mis-hearings that matter for routing before Haiku sees them."""
        fixes = [
            (r"\b(k|c)o[\s-]?de(x|cks|cs|ks|x's)\b", "Codex"),
            (r"\bcodecs?\b", "Codex"),
            (r"\bcode[\s-]?x\b", "Codex"),
            (r"\bcortex\b", "Codex"),
            (r"\bclaud\b", "Claude"),
            (r"\bcloud code\b", "Claude Code"),
            (r"\bcloud\b(?=\s+(to|and|should|can|will|code))", "Claude"),
        ]
        s = t
        for pat, rep in fixes:
            s = re.sub(pat, rep, s, flags=re.IGNORECASE)
        return s

    def _finish_listening_thread(self) -> None:
        self.listening_active = False
        self._post(lambda: setattr(self.pill, "state", PillState.thinking))
        self._post(self._pill_did_change)
        text = self.normalize_transcript(self.speech.stop())
        AppLog.write(f'stt final: "{text}"')

        def after():
            self.pill.transcript = text
            self._pill_did_change()
            if not text.strip():
                self._dismiss_pill(0.6)
                return
            self.handle(text)

        self._post(after)

    # MARK: orchestration (§4)

    def _orchestrator_loop(self) -> None:
        while True:
            with self._turn_cv:
                while not self._turn_queue:
                    self._turn_cv.wait()
                transcript = self._turn_queue.pop(0)
            try:
                self._handle_serialized(transcript)
            except Exception as e:
                AppLog.write(f"orchestrator turn failed: {e}")

    def handle(self, transcript: str) -> None:
        """One orchestrator turn at a time — concurrent `claude -p` instances
        slow each other down."""
        if not self.claude_path:
            self._post(lambda: self._show_error("Claude Code CLI not found"))
            return
        with self._turn_cv:
            self._turn_queue.append(transcript)
            self._turn_cv.notify()

    def _handle_serialized(self, transcript: str) -> None:
        claude = self.claude_path
        if not claude:
            return
        orch = Orchestrator(claude_path=claude)
        gen = self.turn_generation
        action = orch.decide(
            transcript=transcript,
            projects=self.registry.prompt_summary,
            sessions=self.sessions.prompt_summary,
            max_sessions=self.settings.settings.maxConcurrentSessions,
            running_count=len(self.sessions.running),
            context=self.clarify_context,
            memories=self.memory.prompt_summary,
            history=self.memory.turns_summary,
        )
        if gen != self.turn_generation:
            AppLog.write(f'turn dropped (escaped): "{transcript}"')
            return

        def after():
            prior = self.clarify_context
            self.clarify_context = None
            AppLog.write(f'transcript="{transcript}" → {action}')
            self.perform(action, f"{prior} / {transcript}" if prior else transcript)

        self._post(after)

    @staticmethod
    def sanitize(a: OrchestratorAction, transcript: str) -> OrchestratorAction:
        """Haiku sometimes routes "open it on localhost / in the browser" to
        `open`, which pops a Terminal window. Only a literal folder/terminal/
        editor request may reach `open`; everything else becomes agent work."""
        if a.action is not OrchestratorActionKind.open:
            return a
        t = transcript.lower()
        wants_shell = any(w in t for w in
                          ["terminal", "finder", "folder", "directory", "editor",
                           "vs code", "vscode", "cursor", "explorer", "xcode"])
        wants_work = any(w in t for w in
                         ["localhost", "browser", "port", "http", "run ", "serve",
                          "preview", "deploy", "test", "start", "website", "site", "app"])
        if wants_shell and not wants_work:
            return a
        if a.task is None and not wants_work:
            return a   # bare "open X" with no work verbs: honour it
        b = OrchestratorAction(
            action=OrchestratorActionKind.followup, agent=a.agent, project=a.project,
            session_id=None, task=a.task if a.task is not None else transcript,
            speak=a.speak, remember=a.remember, forget=a.forget,
        )
        AppLog.write(f'sanitize: open → followup ("{transcript}")')
        return b

    def perform(self, raw: OrchestratorAction, transcript: str) -> None:
        a = self.sanitize(raw, transcript=transcript)
        # Memory side-effects happen regardless of which action was chosen.
        if a.forget:
            removed = self.memory.forget(a.forget)
            if removed == 0 and a.action is OrchestratorActionKind.chitchat:
                self.say("I didn't have anything like that saved.")
                self.memory.record(heard=transcript, said="nothing to forget", action="forget")
                return
        if a.remember:
            self.memory.remember(a.remember)

        speak = a.speak or ""
        s = self.settings.settings

        if a.action is OrchestratorActionKind.spawn:
            if len(self.sessions.running) >= s.maxConcurrentSessions:
                speak = "Six sessions are already running. Finish one first."
            else:
                resolved = self.registry.resolve(a.project) if a.project else self.general_project()
                if resolved is None and a.project and a.task:
                    # Unknown project name + a concrete task: create it on the spot.
                    try:
                        resolved = self.create_project(a.project)
                        if not speak:
                            speak = f"Created {resolved.name} — starting now."
                    except Exception:
                        resolved = None
                if resolved is None:
                    self.clarify_context = transcript
                    self.pill.state = PillState.clarify
                    self.pill.secondary = ("No projects yet — add one in Settings."
                                           if not self.registry.projects else "Which project?")
                    speak = ("You haven't added any projects yet."
                             if not self.registry.projects else (a.speak or "Which project?"))
                elif not a.task:
                    self.clarify_context = transcript
                    self.pill.state = PillState.clarify
                    speak = "What should it do?"
                else:
                    agent = a.agent or resolved.defaultAgent
                    if not self.spawn(resolved, agent, a.task):
                        speak = self._spawn_failure_speech(resolved, agent)

        elif a.action is OrchestratorActionKind.followup:
            if not a.task:
                speak = "What should it do?"
                self.clarify_context = transcript
                self.pill.state = PillState.clarify
            else:
                sess = self._resolve_session(a.session_id, a.project)
                if sess is not None:
                    self.follow_up(sess, a.task)
                else:
                    project = self.registry.resolve(a.project)
                    if project is not None:
                        agent = a.agent or project.defaultAgent
                        if not self.spawn(project, agent, a.task):
                            speak = self._spawn_failure_speech(project, agent)
                        elif not speak:
                            speak = f"Starting on {project.name}."
                    else:
                        speak = "Which project?"
                        self.clarify_context = transcript
                        self.pill.state = PillState.clarify

        elif a.action is OrchestratorActionKind.cancel:
            sess = self._resolve_session(a.session_id, a.project, running_only=True)
            if sess is None:
                speak = "Nothing is running." if not self.sessions.running else "Which one?"
            else:
                self.stop(session_id=sess.id)

        elif a.action is OrchestratorActionKind.status:
            if not speak:
                speak = self.status_sentence()

        elif a.action is OrchestratorActionKind.open:
            sess = self._resolve_session(a.session_id, a.project)
            if sess is not None:
                self.open_session(sess)
            else:
                project = self.registry.resolve(a.project)
                if project is not None:
                    self.open_terminal(at=project.url, transcript=transcript)
                else:
                    speak = "Which project?"

        elif a.action is OrchestratorActionKind.clarify:
            self.clarify_context = transcript
            self.pill.state = PillState.clarify
            self.pill.secondary = strip_cues(a.speak)

        elif a.action is OrchestratorActionKind.chitchat:
            if not speak and a.remember:
                speak = "Got it, I'll remember that."
            if not speak and a.forget:
                speak = "Forgotten."

        elif a.action is OrchestratorActionKind.create:
            name = (a.project or "").strip()
            if not name:
                self.clarify_context = transcript
                self.pill.state = PillState.clarify
                self.pill.secondary = "What should it be called?"
                speak = "What should the project be called?"
            else:
                try:
                    project = self.create_project(name)
                    if a.task:
                        agent = a.agent or s.defaultAgent
                        if not self.spawn(project, agent, a.task):
                            speak = self._spawn_failure_speech(project, agent)
                    else:
                        self.clarify_context = transcript
                        self.pill.state = PillState.clarify
                        self.pill.secondary = "What should I build?"
                        speak = f"Created {project.name}. What should I build in it?"
                except Exception as e:
                    speak = f"Couldn't create the project: {e}"

        self.memory.record(heard=transcript, said=speak, action=a.action.value,
                           task=a.task, project=a.project)
        self.say(speak)

    def _spawn_failure_speech(self, p: Project, agent: AgentKind) -> str:
        if self.last_spawn_failure == SpawnFailure.MISSING_CLI:
            return f"{agent.display_name} CLI isn't installed."
        if self.last_spawn_failure == SpawnFailure.MISSING_FOLDER:
            return f"The folder for {p.name} doesn't exist — fix its path in Settings."
        if self.last_spawn_failure == SpawnFailure.LAUNCH:
            return f"Couldn't launch {agent.display_name} — check the log."
        return "Couldn't start that."

    def _resolve_session(self, sid: Optional[str], project: Optional[str],
                         running_only: bool = False) -> Optional[Session]:
        if sid:
            s = self.sessions.session(sid)
            if s is not None:
                return s
        pool = self.sessions.running if running_only else self.sessions.visible
        if project:
            p = self.registry.resolve(project)
            if p is not None:
                for s in pool:
                    if s.projectName == p.name:
                        return s
        return pool[0] if len(pool) == 1 else None

    def status_sentence(self) -> str:
        running = self.sessions.running
        if not running:
            return "Nothing is running right now."
        return "; ".join(
            f"{s.projectName} on {s.agent.display_name}, {self.sessions.format(s.elapsed)}"
            for s in running
        ) + "."

    # MARK: sessions

    def spawn(self, project: Project, agent: AgentKind, task: str,
              resume: Optional[str] = None, existing_id: Optional[str] = None) -> bool:
        self.last_spawn_failure = None
        exe = self.claude_path if agent is AgentKind.claude else self.codex_path
        if not exe:
            self.last_spawn_failure = SpawnFailure.MISSING_CLI
            return False
        if not project.url.is_dir():
            self.last_spawn_failure = SpawnFailure.MISSING_FOLDER
            AppLog.write(f"spawn refused: folder missing {project.url}")
            return False

        session_id = existing_id or self.sessions.next_id()
        if existing_id is None:
            self.sessions.insert(Session(
                id=session_id, projectName=project.name, projectPath=project.path,
                agent=agent, task=task,
            ))
        else:
            def reset(s: Session) -> None:
                s.status = SessionStatus.running
                s.task = task
                s.finishedAt = None
                s.activity = ""
                s.startedAt = datetime.now(timezone.utc)
                s.dismissed = False
            self.sessions.update(session_id, reset)

        runner = AgentRunner(
            session_id=session_id, agent=agent,
            on_event=lambda e, sid=session_id: self._post(lambda: self._handle_event(e, sid)),
            on_exit=lambda code, text, sid=session_id: self._post(lambda: self._handle_exit(code, text, sid)),
        )
        mode = project.permissionMode
        try:
            runner.start(exe, task, str(project.url), mode, resume, self.memory.agent_guidance)
            self.runners[session_id] = runner
            self.sessions.update(session_id, lambda s: setattr(s, "pid", runner.pid))
            return True
        except Exception as e:
            self.last_spawn_failure = SpawnFailure.LAUNCH
            AppLog.write(f"spawn failed: {e}")

            def mark_failed(s: Session) -> None:
                s.status = SessionStatus.failed
                s.finishedAt = datetime.now(timezone.utc)
                s.activity = f"Failed to launch: {e}"
            self.sessions.update(session_id, mark_failed)
            return False

    def follow_up(self, session: Session, task: str) -> None:
        project = None
        for p in self.registry.projects:
            if p.name == session.projectName:
                project = p
                break
        if project is None:
            project = self.registry.resolve(session.projectName)
        if project is None:
            return
        if session.status is SessionStatus.running:
            # A running headless session cannot take stdin; queue as a resume
            # after it finishes.
            self.pending_followups.setdefault(session.id, []).append(task)
            self.sessions.update(session.id, lambda s: setattr(s, "activity", "Follow-up queued"))
        else:
            self.spawn(project, session.agent, task,
                       resume=session.agentSessionID, existing_id=session.id)

    def stop(self, session_id: str) -> None:
        r = self.runners.get(session_id)
        if r is None:
            return
        self.sessions.update(session_id, lambda s: (
            setattr(s, "status", SessionStatus.cancelled), setattr(s, "activity", "Stopping…")))
        r.stop()

    def stop_all(self) -> None:
        for r in list(self.runners.values()):
            r.kill()
        for s in self.sessions.running:
            def mark_cancelled(s: Session) -> None:
                s.status = SessionStatus.cancelled
                s.finishedAt = datetime.now(timezone.utc)
            self.sessions.update(s.id, mark_cancelled)

    def _handle_event(self, e: AgentEvent, session_id: str) -> None:
        def mutate(s: Session) -> None:
            if e.kind == "sessionID":
                s.agentSessionID = e.text
            elif e.kind == "activity":
                if s.status is SessionStatus.running:
                    s.activity = e.text
            elif e.kind == "text":
                s.resultText = e.text[-4000:]
            elif e.kind == "needsInput":
                s.status = SessionStatus.needsInput
            elif e.kind == "result":
                if e.text:
                    s.resultText = e.text[-4000:]
                if e.is_error and s.status is SessionStatus.running:
                    s.status = SessionStatus.failed
        self.sessions.update(session_id, mutate)

    def _handle_exit(self, code: int, last_text: str, session_id: str) -> None:
        AppLog.write(f"session {session_id} exited {code}")
        self.runners.pop(session_id, None)
        s0 = self.sessions.session(session_id)
        if s0 is None:
            return
        was_cancelled = s0.status is SessionStatus.cancelled

        def finalize(s: Session) -> None:
            s.finishedAt = datetime.now(timezone.utc)
            s.pid = None
            if s.status is SessionStatus.running:
                s.status = SessionStatus.done if code == 0 else SessionStatus.failed
            if s.status is SessionStatus.cancelled:
                s.activity = ""
            if s.status is SessionStatus.failed and code != 0 and not s.activity:
                s.activity = f"Exit {code}"
        self.sessions.update(session_id, finalize)

        pending = self.pending_followups.get(session_id)
        if pending:
            nxt = pending.pop(0)
            if not pending:
                self.pending_followups.pop(session_id, None)
            sess = self.sessions.session(session_id)
            if sess is not None:
                self.follow_up(sess, nxt)
            return

        if was_cancelled or not self.settings.settings.speakSummaries:
            return
        claude = self.claude_path
        if not claude:
            return
        sess = self.sessions.session(session_id)
        if sess is None:
            return

        def summarize() -> None:
            summary = Orchestrator(claude_path=claude).summarize(
                task=sess.task, project=sess.projectName,
                result=sess.resultText or last_text,
                is_error=sess.status is not SessionStatus.done, exit_code=code,
            )
            self._post(lambda: self.announce(summary))

        threading.Thread(target=summarize, daemon=True).start()

    # MARK: create

    def create_project(self, raw_name: str) -> Project:
        """Makes `<projectsRoot>/<slug>`, `git init`s it, and registers it
        (reuses an existing folder or registry entry)."""
        name = re.sub("project", "", raw_name, flags=re.IGNORECASE).strip()
        generic = {"", "new", "a new", "another", "untitled", "site", "website", "app", "thing", "one"}
        if name.lower() in generic:
            raise ValueError("I need a real name for it — what should it be called?")
        for p in self.registry.projects:
            if p.name.lower() == name.lower() or any(a.lower() == name.lower() for a in p.aliases):
                return p
        slug = "-".join(w for w in re.split(r"[^a-z0-9]+", name.lower()) if w)
        if not slug:
            raise ValueError("I didn't catch a name.")
        root = Path(self.settings.settings.projectsRoot).expanduser()
        directory = root / slug
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / ".git").exists():
            git = CLILocator.find("git")
            if git:
                threading.Thread(
                    target=lambda: CLILocator.run(git, ["init", "-q"], cwd=str(directory), timeout=20),
                    daemon=True,
                ).start()
        alias = slug.replace("-", " ")
        aliases = [alias] if alias != name.lower() else []
        agent = self.settings.settings.defaultAgent
        project = Project(
            name=name, path=str(directory), aliases=aliases, defaultAgent=agent,
            permissionMode=(self.settings.settings.claudePermissionMode if agent is AgentKind.claude
                            else self.settings.settings.codexPermissionMode),
        )
        self.registry.add(project)
        AppLog.write(f"created project {name} at {directory}")
        return project

    def general_project(self) -> Optional[Project]:
        """Workspace for non-project requests ("check my calendar"):
        `<projectsRoot>/general`, created on demand."""
        try:
            root = Path(self.settings.settings.projectsRoot).expanduser()
            directory = root / "general"
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return Project(name="General", path=str(directory), aliases=["general"],
                       defaultAgent=AgentKind.claude,
                       permissionMode=self.settings.settings.claudePermissionMode)

    # MARK: open

    def open_session(self, s: Session) -> None:
        url = Path(s.projectPath).expanduser()
        if s.agent is AgentKind.claude and s.agentSessionID and s.status is not SessionStatus.running:
            self.open_terminal(at=url, command=f"claude --resume {s.agentSessionID}")
        elif s.agent is AgentKind.codex and s.agentSessionID and s.status is not SessionStatus.running:
            self.open_terminal(at=url, command=f"codex resume {s.agentSessionID}")
        else:
            self.open_terminal(at=url)

    def open_terminal(self, at: Path, command: Optional[str] = None,
                      transcript: Optional[str] = None) -> None:
        """Windows equivalent of the macOS Terminal AppleScript: Windows
        Terminal if present, else the classic console. A literal folder
        request opens Explorer instead (Finder → Explorer)."""
        path = str(at)
        if command is None and transcript:
            t = transcript.lower()
            wants_folder = any(w in t for w in ("folder", "directory", "explorer", "finder"))
            wants_console = any(w in t for w in ("terminal", "console", "command prompt", "powershell"))
            if wants_folder and not wants_console:
                try:
                    os.startfile(path)   # type: ignore[attr-defined]
                    return
                except Exception:
                    pass
        try:
            wt = CLILocator.find("wt")
            if wt:
                args = ["new-tab", "--startingDirectory", path]
                if command:
                    args += ["cmd", "/k", command]
                subprocess.Popen([wt] + args, env=CLILocator.child_environment())
                return
        except Exception:
            pass
        try:
            inner = f'cd /d "{path}"'
            if command:
                inner += f" && {command}"
            subprocess.Popen(["cmd", "/k", inner], env=CLILocator.child_environment())
        except Exception as e:
            AppLog.write(f"open terminal failed: {e}")

    def show_log(self, s: Session) -> None:
        p = log_for(s.id)
        try:
            os.startfile(str(p))   # type: ignore[attr-defined]
        except Exception:
            AppLog.write(f"show log failed: {p}")

    # MARK: voice / pill

    def say(self, text: str) -> None:
        AppLog.write(f"speak: {text}")
        if not text:
            self._dismiss_pill(0.25)
            return
        if self.pill.state != PillState.clarify:
            self.pill.state = PillState.speaking
        self.pill.transcript = strip_cues(text)
        self.pill.visible = True
        self._pill_did_change()
        if focus.is_do_not_disturb() and self.settings.settings.muteDuringFocus:
            self._dismiss_pill(2.5)
            return
        self.voice.speak(text)
        self.pill.fallback_badge = not self.voice.has_fish_key
        self._pill_did_change()

    def announce(self, text: str) -> None:
        """Completion summaries: speak (unless DND) and flash the pill."""
        AppLog.write(f"announce: {text}")
        self.pill.state = PillState.speaking
        self.pill.transcript = strip_cues(text)
        self.pill.secondary = ""
        self.pill.visible = True
        self._pill_did_change()
        if focus.is_do_not_disturb() and self.settings.settings.muteDuringFocus:
            self._dismiss_pill(3)
            return
        self.voice.speak(text)
        self.pill.fallback_badge = not self.voice.has_fish_key
        self._pill_did_change()

    def did_finish_speaking(self) -> None:
        if self.pill.state == PillState.clarify:
            self._dismiss_pill(8)
        else:
            self._dismiss_pill(0.25)

    def _show_error(self, msg: str) -> None:
        self.pill.state = PillState.error
        self.pill.transcript = self.pill.transcript or "Couldn't listen"
        self.pill.secondary = msg
        self.pill.visible = True
        self._pill_did_change()
        self._dismiss_pill(3)

    def _dismiss_pill(self, after: float) -> None:
        if self._hide_task:
            self._hide_task.cancel()

        def fire():
            def apply():
                if self.listening_active:
                    return
                self.pill.visible = False
                self.pill.secondary = ""
                self._pill_did_change()
            self._post(apply)

        self._hide_task = threading.Timer(after, fire)
        self._hide_task.start()

    # MARK: lifecycle

    @staticmethod
    def _rotate_logs() -> None:
        """Keep session logs for the sessions we still know about (≤100) and
        drop the rest."""
        raw = JSONStore.load_raw(sessions_path())
        keep = set()
        if isinstance(raw, list):
            for d in raw:
                sid = d.get("id") if isinstance(d, dict) else None
                if sid:
                    keep.add(f"{sid}.ndjson")
        try:
            for f in os.listdir(logs_dir()):
                if f.endswith(".ndjson") and f not in keep:
                    try:
                        (logs_dir() / f).unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    def prepare_for_quit(self) -> None:
        self.stop_all()
