# Conductor (VoiceMode)

A personal, local-only macOS menu-bar app: **hold a hotkey, speak a request, and it spins up Claude Code or Codex sessions in the background** — shows their status in a floating glass overlay and talks back to you with Fish Audio.

- Hold **⇧⌘Space** → a frosted-glass pill appears and listens
- Say *"Update the website — change the hero headline and deploy"*
- Release → an orchestrator (Claude Haiku, running through your Claude Code subscription) picks the agent and project, and a headless session starts
- A session card streams live status; when it finishes, Fish Audio speaks a one-sentence summary
- Hold the key again to ask for status, send follow-ups into a running session, or cancel it

Everything runs on your own machine. No server, no database, no accounts, no API keys in code — the only secret (your Fish Audio key) is stored in the macOS Keychain.

## Requirements

- **macOS 15 (Sequoia) or newer**
- **Xcode 16+ or the Command Line Tools** (Swift 6 toolchain) — `xcode-select --install`
- **Claude Code CLI** (`claude`) installed and logged in with your subscription
- **Codex CLI** (`codex`) — optional, only if you want to route tasks to Codex too
- **A Fish Audio account** with some credits, for the spoken replies (the only thing that costs anything beyond your existing subscriptions)

The app finds `claude`/`codex` on your PATH and in the usual install locations (Homebrew, `~/.local/bin`, npm/bun/volta globals). You can also point it at a specific binary in Settings.

## Build & run

```bash
git clone https://github.com/albertshiney/VoiceMode.git
cd VoiceMode
./scripts/build-app.sh
open build/Conductor.app
```

The build script compiles the SwiftPM package in release mode, assembles `build/Conductor.app`, and code-signs it. If you have a real signing identity in your keychain it uses that (so macOS remembers your mic/speech permission grants across rebuilds); otherwise it falls back to ad-hoc signing — which works fine, but macOS will re-ask for permissions after every rebuild. Force ad-hoc with `CONDUCTOR_SIGN=adhoc ./scripts/build-app.sh`.

For a quick debug build: `./scripts/build-app.sh debug`.

## First-run setup

Conductor walks you through onboarding on first launch:

1. **Microphone** and **Speech Recognition** permissions — speech-to-text happens on-device via Apple's recognizer; nothing leaves your Mac. No Accessibility/hotkey permission is needed (the push-to-talk chord is unbound by default in macOS).
2. **Fish Audio API key** — paste it once; it's stored in the macOS Keychain (`ai.conductor.app`), never in a file.
3. **CLI check** — it verifies `claude` (and optionally `codex`) are installed and authenticated.
4. **Projects** — register the folders you want to drive by voice (e.g. `~/Projects/website`). The orchestrator matches your spoken request against this registry.

Then just hold **⇧⌘Space** and talk. The chord is configurable in Settings.

## Where your data lives

Plain JSON files under `~/Library/Application Support/Conductor/`:

| File | Contents |
|---|---|
| `projects.json` | your registered projects |
| `sessions.json` | session history |
| `settings.json` | app settings |
| `memory.json` / `conversation.json` | orchestrator memory & conversation state |
| `logs/*.ndjson` | per-session agent output logs |

Delete that folder (and the Keychain item `ai.conductor.app`) to fully reset.

## Development

```bash
swift build          # compile
swift test           # run the test suite (uses an isolated temp data dir — never touches your real data)
```

Source layout:

- `Sources/Conductor/App` — app entry point
- `Sources/Conductor/Core` — models, JSON stores, Keychain, CLI locator, subprocess plumbing
- `Sources/Conductor/Services` — orchestrator brain, agent runner, hotkey monitor, speech in (Apple) / voice out (Fish Audio), stream parsers
- `Sources/Conductor/UI` — listening pill, sessions overlay, onboarding, settings (SwiftUI, glass styling)

## Cost & privacy notes

- Agent work bills to your existing **Claude Code / Codex subscriptions** — the orchestrator calls Haiku *through the Claude Code CLI*, never a raw API key. `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` are actively stripped from child-process environments so nothing accidentally bills an API account.
- **Fish Audio TTS** is the only per-use cost.
- Speech recognition is on-device. Nothing is uploaded anywhere except the agent CLIs you already use.
