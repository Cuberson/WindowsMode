# Conductor (VoiceMode) — Windows edition

A personal, local-only Windows tray app: **hold a hotkey, speak a request, and it spins up Claude Code or Codex sessions in the background** — shows their status in a floating glass overlay and talks back to you with Fish Audio.

- Hold **Ctrl+Shift+Space** → a frosted-glass pill appears and listens
- Say *"Update the website — change the hero headline and deploy"*
- Release → an orchestrator (Claude Haiku, running through your Claude Code subscription) picks the agent and project, and a headless session starts
- A session card streams live status; when it finishes, Fish Audio speaks a one-sentence summary
- Hold the key again to ask for status, send follow-ups into a running session, or cancel it

Everything runs on your own machine. No server, no database, no accounts, no API keys in code — the only secret (your Fish Audio key) is stored in the **Windows Credential Manager**.

This is the Windows port of [albertshiney/VoiceMode](https://github.com/albertshiney/VoiceMode) (the macOS original lives in that repo and in this repo's git history). Same features, same data layout, same voice loop — adapted to Windows idioms: tray instead of menu bar, Ctrl+Shift+Space instead of ⇧⌘Space, Credential Manager instead of Keychain, Acrylic/Mica glass on Windows 11, Windows speech recognition instead of Apple's.

## Requirements

- **Windows 10 or 11**
- **Python 3.11+** (or use the packaged `Conductor.exe`, see below)
- **Claude Code CLI** (`claude`) installed and logged in with your subscription
- **Codex CLI** (`codex`) — optional, only if you want to route tasks to Codex too
- **A Fish Audio account** with some credits, for the spoken replies (the only thing that costs anything beyond your existing subscriptions)

Speech-to-text happens on-device via **Windows.Media.SpeechRecognition** (the Windows equivalent of Apple's on-device recognizer) — nothing leaves your PC. Optionally install a [Vosk](https://alphacephei.com/vosk/) model as a fallback engine.

The app finds `claude`/`codex` on your PATH and in the usual install locations (`%APPDATA%\npm`, Node.js, bun, volta, scoop). You can also point it at a specific binary in Settings.

## Install & run

```powershell
git clone https://github.com/albertshiney/VoiceMode.git
cd VoiceMode
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.pyw
```

Conductor lives in the notification area (tray). To build a standalone `Conductor.exe`:

```bat
.\scripts\build-exe.bat
:: → dist\Conductor.exe
```

## First-run setup

Conductor walks you through onboarding on first launch:

1. **Microphone** and **Speech Recognition** — allow them under *Settings › Privacy & security › Microphone / Speech*. Speech happens on-device; nothing is uploaded.
2. **Push to talk** — hold **Ctrl+Shift+Space** and release; the wizard captures both events. The chord is configurable in Settings.
3. **CLI check** — it verifies `claude` (and optionally `codex`) are installed and authenticated.
4. **Voice** — paste your Fish Audio API key once; it's stored in the Windows Credential Manager (`ai.conductor.app`), never in a file.
5. **Projects** — register the folders you want to drive by voice (e.g. `C:\Projects\website`). The orchestrator matches your spoken request against this registry.

Then just hold **Ctrl+Shift+Space** and talk.

### Keyboard

| Chord | Action |
|---|---|
| **Ctrl+Shift+Space** (hold) | Push to talk — hold, speak, release |
| **Ctrl+Shift+O** | Toggle the sessions overlay |
| **Esc** (while the pill is up) | Abandon the current exchange |

Both chords are remappable in Settings → General.

## Where your data lives

Plain JSON files under `%APPDATA%\Conductor\`:

| File | Contents |
|---|---|
| `projects.json` | your registered projects |
| `sessions.json` | session history |
| `settings.json` | app settings |
| `memory.json` / `conversation.json` | orchestrator memory & conversation state |
| `logs\*.ndjson` | per-session agent output logs |
| `logs\app.log` | diagnostics |

Delete that folder (and the Credential Manager item `ai.conductor.app`) to fully reset. The JSON keys are identical to the macOS app's, so a data folder can be copied over wholesale.

### Scripting / testing hook

`conductor://say?text=...` feeds a transcript without the mic; `conductor://overlay` toggles the overlay. From a terminal:

```powershell
Start-Process "conductor://say?text=what%27s%20the%20status%3F"
```

## Development

```powershell
pip install -r requirements.txt
python -m unittest discover -s tests -t .    # runs in an isolated temp data dir — never touches your real data
```

Source layout:

- `conductor/app.py` — app entry point (tray, panels, URL scheme, single-instance)
- `conductor/core` — models, JSON stores, Credential Manager, CLI locator, subprocess plumbing
- `conductor/services` — orchestrator brain, agent runner, hotkey hook, speech in (Windows/Vosk) / voice out (Fish Audio), stream parsers
- `conductor/ui` — listening pill, sessions overlay, onboarding, settings (glass styling via DWM Acrylic/Mica)
- `tests` — ported test suite (parsers, orchestrator, stores, coordinator) + Qt offscreen UI smoke tests

## Cost & privacy notes

- Agent work bills to your existing **Claude Code / Codex subscriptions** — the orchestrator calls Haiku *through the Claude Code CLI*, never a raw API key. `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` are actively stripped from child-process environments so nothing accidentally bills an API account.
- **Fish Audio TTS** is the only per-use cost. Without a key the app falls back to the built-in Windows system voice and stays fully functional.
- Speech recognition is on-device. Nothing is uploaded anywhere except the agent CLIs you already use.
