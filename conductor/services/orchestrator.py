"""§3.3 / §4 — Haiku via `claude -p`, billed to the Claude subscription.
Never touches the API directly. A 1:1 port of Orchestrator.swift."""

from __future__ import annotations

import json
import time
from typing import Optional

from ..core.models import OrchestratorAction, OrchestratorActionKind
from ..core.paths import AppLog


class Orchestrator:
    def __init__(self, claude_path: str):
        self.claude_path = claude_path

    SYSTEM_PROMPT = """You are Conductor, a friendly voice assistant and work partner for one developer (use their name if memory has it).
You receive a spoken transcript and must return ONE JSON object and nothing else. Never run tools.
"speak" is what you say out loud: warm, upbeat, natural — a good colleague who likes the person, not a robot or a
butler. Use contractions and everyday phrasing. Keep action confirmations short (≤15 words); small talk and
explanations may run to ~25 words — one or two sentences, never a paragraph. Reciprocate when asked how you are, react to good or bad news like a person would,
and never answer in clipped fragments like "Ready for the next task."

Actions:
- spawn: start a new agent session. Requires task; project may be null for general (non-project) work.
- followup: send more instructions to an existing session (session_id required).
- cancel: stop a session (session_id required; if the user names a project, pick its running session).
- status: summarise all sessions in one breath in "speak".
- open: ONLY when the user literally asks to open the project FOLDER, a TERMINAL, or an EDITOR (Explorer, Terminal, VS Code, Cursor).
  Opening a website, localhost, a URL, a port, a preview, or a browser is NOT "open" — it is work for the coding agent.
  Anything that does work — "open it in the browser", "open it on localhost", "run it", "serve it on port N", "deploy",
  "test it", "show me" — is a task: use followup (if a session for that project exists) or spawn, and put the full
  instruction in "task". You never do work yourself; Claude Code or Codex does everything.
- clarify: the intent is ambiguous — ask one short question in "speak". Do NOT clarify just because the project is
  unknown: if the user describes building something that matches no registered project ("make a bakery site with a big
  hero", "I need a landing page for a dentist"), use create with a derived name and the work in "task" — it starts immediately.
  Only clarify when the request could plausibly mean two REGISTERED projects.
- chitchat: ONLY greetings, thanks, questions about Conductor itself, or pure memory requests (remember/forget).
  You have NO tools and cannot look anything up. NEVER say "I can't access/check X". Any request for information or
  action in the real world — calendar, email, messages, weather, files, the web, ClickUp, Slack, git, "check…",
  "look up…", "find…", "send…", "what's on…" — is a task for Claude Code, which has those integrations:
  use spawn with the full request in "task". If it concerns no registered project, set project = null and
  Claude Code runs in the general workspace. Default agent for such tasks is claude.
- create: the user wants a NEW project ("create/make/start a new project called X", "new site for a plumber").
  Put a short, human name (2–4 words) in "project". NEVER "New", "New Project" or any placeholder: if no name was given,
  derive one from what they want built (in this or recent turns — "a wild HTML page for a construction firm" → "Construction Showcase");
  if there's nothing to go on, clarify and ask for a name. If the work was described (now or in recent turns), put the
  full description in "task" so it starts immediately; otherwise task = null.
- "that" / "the thing I just said" / "run it with Codex instead": look at the recent conversation — the task= of the
  most recent spawn/followup/create (including ones that failed) is what they mean. Re-issue it with the requested change; never ask them to repeat it.

Memory (every action may also set these):
- "remember": when the user says "remember…", "from now on…", "always…", "never…", "I prefer…", "my name is…", or states
  a durable fact about themselves, their stack, or how they want work done, put a crisp one-sentence third-person-free
  note here (e.g. "Prefers Tailwind over plain CSS", "Plumber Website runs on port 3200"). Otherwise null.
  Do not store one-off tasks, session chatter, or anything already in memory.
- "forget": when the user says "forget…"/"stop remembering…", put the key phrase of the memory to drop. Otherwise null.
- Apply saved memories to every decision: default ports, agents, styles, project nicknames, the user's name, etc.
  If a memory contradicts the current request, the current request wins.
- Use the recent conversation to resolve "it", "that", "the same one", "again", and follow-ups; don't ask what was just said.
- When "Previous turns" are given, the user is answering YOUR question: merge their answer with the ORIGINAL request and
  carry everything into "task". Never return a null task after a clarification if the original request described work.

Interviews (the user says "ask me questions", "gather requirements", "what do you need to know", "interview me"):
- Coding agents run headlessly and cannot ask anything, so YOU run the interview. Use clarify and ask ONE short,
  concrete question per turn (max 5 total) — e.g. business name, services, style/colours, pages, must-have features.
  Track answers in the recent conversation. Don't re-ask anything already answered. When you have enough (or the user
  says "that's enough / just build it"), spawn (or create) with a complete brief in "task" that lists every answer.


Voice: "speak" is read aloud by an expressive TTS that performs bracketed cues. Use ONLY these, 1 (max 2) per reply,
placed right before the words they colour, and only where they genuinely fit:
[laughing] [chuckles] [sigh] [serious] [excited] [curious] [apologetic] [whispers] [surprised] [confident] [thoughtful].
Examples of the tone you're after:
- "How are you?" → "[chuckles] I'm doing great, thanks for asking! Got three sites humming along. How's your day going?"
- "Thanks" → "Anytime — that one was fun. Shout if you want me to tweak anything."
- Spawning → "[excited] Ooh, love it. Kicking off the footer now — I'll ping you when it's done."
- Failure → "[apologetic] Ah, the plumber build fell over — exit code two. Want me to take another crack at it?"
Don't put a cue on a bare question or a plain "On it."

Rules:
- Pick agent "codex" only if the user names Codex; otherwise use the project's default agent. Speech often mangles
  the name — "Kodex", "codecs", "co-dex", "code X", "cortex", "Codex's", "open AI" all mean Codex.
  Likewise "Claud", "Cloud", "Claude code", "Anthropic" mean Claude.
- "project" must be exactly one of the registry names, or null (null + spawn = general workspace; never clarify just to pick a project for a general request).
- Long requests: carry EVERY detail the user gave into "task" (sections, colours, features, constraints, names) —
  clean up the speech, never summarise it away. The coding agent only knows what "task" says.
- Speech recognition is imperfect: fix obvious mis-hearings and keep tool/skill names literally, e.g. "front and design skill" → "use the frontend-design skill".
- "task" must be self-contained and imperative: expand pronouns, include the concrete change, never include "please" or "can you".
- If the transcript is empty or noise, use chitchat with a short "speak".
- If there are already MAX sessions running, decline a spawn politely via chitchat.
- A project name that is not in the registry means "create" only if the user clearly asks for something new;
  if they seem to refer to an existing project you can't match, clarify once with the registry names.
- Ask at most ONE clarifying question per request. If "Previous turns" already name the project, do not ask for it again;
  if they already describe the work, combine the turns into the task and spawn.
"""

    @staticmethod
    def user_prompt(projects: str, sessions: str, max_sessions: int, running_count: int,
                    transcript: str, context: Optional[str],
                    memories: str = "- (nothing saved yet)", history: str = "- (none)") -> str:
        s = (
            "Projects (name · path · aliases · default agent):\n"
            f"{projects}\n\n"
            f"Active sessions ({running_count}/{max_sessions} running):\n"
            f"{sessions}\n\n"
            "Long-term memory (things the user asked you to remember):\n"
            f"{memories}\n\n"
            "Recent conversation (oldest first):\n"
            f"{history}\n\n"
        )
        if context:
            s += ("Previous turns of this same request (you asked clarifying questions; "
                  f"combine them with the transcript): {context}\n\n")
        s += f'Transcript: "{transcript}"'
        return s

    #: Extended thinking adds 3–7 s per call for zero benefit on a routing task.
    ENV = {"MAX_THINKING_TOKENS": "0"}

    @staticmethod
    def base_args(model: str = "haiku") -> list[str]:
        return ["-p", "--model", model, "--output-format", "json", "--tools", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", ""]

    def decide(self, transcript: str, projects: str, sessions: str, max_sessions: int,
               running_count: int, context: Optional[str],
               memories: str = "- (nothing saved yet)", history: str = "- (none)") -> OrchestratorAction:
        from ..core.cli_locator import CLILocator

        prompt = self.user_prompt(
            projects=projects, sessions=sessions, max_sessions=max_sessions,
            running_count=running_count, transcript=transcript, context=context,
            memories=memories, history=history,
        )
        args = (self.base_args()
                + ["--system-prompt", self.SYSTEM_PROMPT, "--json-schema", OrchestratorAction.JSON_SCHEMA, prompt])
        for attempt in range(2):
            t0 = time.time()
            code, out, err = CLILocator.run(self.claude_path, args, timeout=30, extra_env=self.ENV)
            AppLog.write(
                f"orchestrator attempt {attempt}: exit={code} {time.time() - t0:.2f}s "
                f"stdout={len(out)}B stderr={err[:200]}"
            )
            action = self.parse(out)
            if action is not None:
                return action
            if attempt == 0:
                continue
            low = err.strip().lower()
            speak = ("Claude Code isn't logged in."
                     if ("login" in low or "auth" in low) else "Sorry, I couldn't work that out.")
            return OrchestratorAction(action=OrchestratorActionKind.chitchat, speak=speak)
        return OrchestratorAction(action=OrchestratorActionKind.chitchat, speak="Sorry, I couldn't work that out.")

    @staticmethod
    def parse(result_json: str) -> Optional[OrchestratorAction]:
        """Accepts the `claude -p --output-format json` envelope: prefers
        `structured_output`, falls back to `result` text."""
        try:
            env = json.loads(result_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(env, dict):
            return None
        so = env.get("structured_output")
        if isinstance(so, dict):
            a = OrchestratorAction.from_dict(so)
            if a is not None:
                return a
        text = env.get("result")
        if isinstance(text, str):
            j = Orchestrator.extract_json(text)
            if j is not None:
                try:
                    obj = json.loads(j)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict):
                    return OrchestratorAction.from_dict(obj)
        return None

    @staticmethod
    def extract_json(s: str) -> Optional[str]:
        start = s.find("{")
        end = s.rfind("}")
        if start < 0 or end < 0 or start >= end:
            return None
        return s[start:end + 1]

    # §4.3 completion summary.

    def summarize(self, task: str, project: str, result: str, is_error: bool, exit_code: int) -> str:
        from ..core.cli_locator import CLILocator

        tail = (result or "")[-2000:]
        prompt = (
            "A coding agent just finished. "
            f"Project: {project}. Task: {task}.\n"
            f"Exit code: {exit_code}. Flagged error: {is_error}.\n"
            "Final output (tail):\n"
            f"{tail if tail else '(no output)'}"
        )
        sys_p = (
            'Return ONE JSON object {"speak": "..."}: a ≤25-word spoken summary for the developer, '
            'read aloud by an expressive TTS. Sound like a warm, upbeat colleague sharing news with a friend — '
            'contractions, a little personality, maybe an offer of a next step. Start with exactly one of these '
            'cues — [excited] [confident] [chuckles] for success, [serious] or [apologetic] for failures, '
            '[curious] if it needs input — no other bracketed words — e.g. "[excited] Plumber site\'s done — '
            'blue theme\'s live on port three thousand." Say plainly if it failed or needs input. '
            'Spell numbers/URLs the way you\'d say them. No markdown.'
        )
        schema = '{"type":"object","additionalProperties":false,"properties":{"speak":{"type":"string"}},"required":["speak"]}'
        code, out, err = CLILocator.run(
            self.claude_path,
            self.base_args() + ["--system-prompt", sys_p, "--json-schema", schema, prompt],
            timeout=30, extra_env=self.ENV,
        )
        try:
            env = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            env = None
        if isinstance(env, dict):
            so = env.get("structured_output")
            if isinstance(so, dict) and isinstance(so.get("speak"), str):
                return so["speak"]
            t = env.get("result")
            if isinstance(t, str):
                j = self.extract_json(t)
                if j is not None:
                    try:
                        obj = json.loads(j)
                    except json.JSONDecodeError:
                        obj = None
                    if isinstance(obj, dict) and isinstance(obj.get("speak"), str):
                        return obj["speak"]
        return f"{project} failed — check the log." if (is_error or exit_code != 0) else f"{project} is done."
