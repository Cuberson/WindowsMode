import SwiftUI
import AppKit
import AVFoundation
import Speech

/// §6 — six steps, each with a real check. 520 × 600.
struct OnboardingView: View {
    @Bindable var coordinator: Coordinator
    let onDone: () -> Void
    @State private var step = 0
    @State private var micOK = SpeechService.micStatus == .authorized
    @State private var speechOK = SpeechService.speechStatus == .authorized
    @State private var chordPressed = false
    @State private var chordReleased = false
    @State private var chordProbe: UInt32?
    @State private var claudeVersion: String?
    @State private var codexVersion: String?
    @State private var claudeLoggedIn: Bool?
    @State private var codexLoggedIn: Bool?
    @State private var fishKey = ""
    @State private var fishStatus = ""
    @State private var hasFish = Keychain.get(Keychain.fishKey) != nil
    @State private var projectURL: URL?
    @State private var projectName = ""
    @State private var projectAliases = ""
    @State private var projectAgent: AgentKind = .claude

    private let titles = ["Welcome", "Permissions", "Push to talk", "Agents", "Voice", "First project"]

    var body: some View {
        VStack(spacing: 0) {
            dots.padding(.top, 24)
            Spacer(minLength: 16)
            Group {
                switch step {
                case 0: welcome
                case 1: permissions
                case 2: chord
                case 3: agents
                case 4: voiceStep
                default: project
                }
            }
            .frame(maxWidth: 400)
            .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .move(edge: .leading).combined(with: .opacity)))
            .id(step)
            Spacer()
            footer.padding(24)
        }
        .frame(width: 520, height: 600)
        .background(.ultraThinMaterial)
        .animation(Motion.spring, value: step)
        .onChange(of: step) { if step == 2 { startChordTest() } else { stopChordTest() } }
        .onDisappear { stopChordTest() }
    }

    private var dots: some View {
        HStack(spacing: 8) {
            ForEach(0..<6) { i in
                Capsule().fill(i == step ? Color.accentColor : Color.primary.opacity(0.15)).frame(width: i == step ? 20 : 6, height: 6)
            }
        }
    }

    private func title(_ t: String, _ sub: String) -> some View {
        VStack(spacing: 8) {
            Text(t).font(.system(size: 28, weight: .semibold)).tracking(-0.4)
            Text(sub).font(.system(size: 15)).foregroundStyle(.secondary).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func check(_ ok: Bool?, _ label: String, detail: String? = nil, action: String? = nil, _ act: (() -> Void)? = nil) -> some View {
        HStack(spacing: 12) {
            Image(systemName: ok == true ? "checkmark.circle.fill" : (ok == nil ? "circle.dotted" : "circle"))
                .foregroundStyle(ok == true ? Color.green : Color.secondary).font(.system(size: 18))
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.system(size: 15, weight: .medium))
                if let detail { Text(detail).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(2) }
            }
            Spacer()
            if let action, let act, ok != true { Button(action, action: act).controlSize(.small) }
        }
        .padding(12)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    // MARK: steps

    private var welcome: some View {
        VStack(spacing: 24) {
            Image(systemName: "waveform").font(.system(size: 44, weight: .light)).foregroundStyle(Color.accentColor)
            title("Conductor", "Hold a key, say what you need, and Claude Code or Codex gets to work in the background.")
            Text("Uses your existing Claude Code and Codex subscriptions. Only Fish Audio voice costs credits.")
                .font(.system(size: 13)).foregroundStyle(.secondary).multilineTextAlignment(.center)
                .padding(12).background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }

    private var permissions: some View {
        VStack(spacing: 16) {
            title("Permissions", "Speech stays on this Mac. No hotkey permission is needed.")
            check(micOK, "Microphone", action: "Allow") { Task { micOK = await AVCaptureDevice.requestAccess(for: .audio); if !micOK { openPane("Privacy_Microphone") } } }
            check(speechOK, "Speech Recognition", detail: "On-device dictation", action: "Allow") {
                Task {
                    let ok = await SpeechService.requestSpeechAuthorization()
                    speechOK = ok
                    if !ok { openPane("Privacy_SpeechRecognition") }
                }
            }
        }
    }

    private var chord: some View {
        VStack(spacing: 16) {
            title("Push to talk", "Hold \(coordinator.settings.settings.pushToTalk.display) now. Release to finish.")
            check(chordPressed, "Press captured")
            check(chordReleased, "Release captured")
            if coordinator.hotkeyError != nil || chordProbe == nil {
                VStack(spacing: 8) {
                    Text("That chord is owned by another app. Pick a different one:").font(.system(size: 12)).foregroundStyle(.secondary)
                    ShortcutRecorder(hotkey: Binding(get: { coordinator.settings.settings.pushToTalk }, set: { coordinator.settings.settings.pushToTalk = $0; startChordTest() }))
                }
            }
        }
    }

    private var agents: some View {
        VStack(spacing: 16) {
            title("Agents", "Conductor drives the CLIs you already have.")
            check(claudeVersion != nil && claudeLoggedIn == true, "Claude Code",
                  detail: claudeVersion.map { "\($0) · \(claudeLoggedIn == true ? "logged in" : "not logged in")" } ?? "Not found on PATH",
                  action: claudeVersion == nil ? "Install" : "Log in") {
                if claudeVersion == nil { NSWorkspace.shared.open(URL(string: "https://docs.anthropic.com/en/docs/claude-code")!) }
                else { coordinator.openTerminal(at: URL(fileURLWithPath: NSHomeDirectory()), command: "claude auth login") }
            }
            check(codexVersion != nil && codexLoggedIn == true, "Codex (optional)",
                  detail: codexVersion.map { "\($0) · \(codexLoggedIn == true ? "logged in" : "not logged in")" } ?? "Not found on PATH",
                  action: codexVersion == nil ? "Install" : "Log in") {
                if codexVersion == nil { NSWorkspace.shared.open(URL(string: "https://github.com/openai/codex")!) }
                else { coordinator.openTerminal(at: URL(fileURLWithPath: NSHomeDirectory()), command: "codex login") }
            }
            Button("Re-check") { Task { await detectAgents() } }.controlSize(.small)
        }
        .task { await detectAgents() }
    }

    private var voiceStep: some View {
        VStack(spacing: 16) {
            title("Voice", "Fish Audio speaks the replies. This is the only thing that costs credits.")
            if hasFish {
                check(true, "API key stored in Keychain", detail: fishStatus.isEmpty ? nil : fishStatus)
                Button("Hear a sample") { coordinator.voice.speak("Hi, I'm ready.") }
            } else {
                SecureField("Fish Audio API key", text: $fishKey).textFieldStyle(.roundedBorder)
                Button("Save & test") {
                    Keychain.set(fishKey, for: Keychain.fishKey); hasFish = true; fishKey = ""
                    Task {
                        if let k = Keychain.get(Keychain.fishKey), let b = try? await FishAudio.balance(apiKey: k) { fishStatus = "\(b.balance.formatted()) credits" }
                        coordinator.voice.speak("Hi, I'm ready.")
                    }
                }.disabled(fishKey.isEmpty)
                Text("Skip to use the built-in system voice.").font(.system(size: 12)).foregroundStyle(.tertiary)
            }
        }
    }

    private var project: some View {
        VStack(spacing: 16) {
            title("First project", "Drop a folder, give it a name and a few spoken aliases.")
            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.05)).frame(height: 72)
                Text(projectURL?.path ?? "Drop a folder here or click to choose").font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle).padding()
            }
            .onTapGesture {
                let p = NSOpenPanel(); p.canChooseDirectories = true; p.canChooseFiles = false
                if p.runModal() == .OK, let u = p.url { projectURL = u; projectName = ProjectRegistry.suggestedName(for: u) }
            }
            .onDrop(of: [.fileURL], isTargeted: nil) { providers in
                _ = providers.first?.loadObject(ofClass: URL.self) { u, _ in
                    Task { @MainActor in if let u { projectURL = u; projectName = ProjectRegistry.suggestedName(for: u) } }
                }
                return true
            }
            TextField("Name", text: $projectName).textFieldStyle(.roundedBorder)
            TextField("Aliases (comma separated)", text: $projectAliases).textFieldStyle(.roundedBorder)
            Picker("Default agent", selection: $projectAgent) { ForEach(AgentKind.allCases) { Text($0.displayName).tag($0) } }.pickerStyle(.segmented)
            if !coordinator.registry.projects.isEmpty {
                Text("Hold \(coordinator.settings.settings.pushToTalk.display) and try: “What's the status?”").font(.system(size: 13)).foregroundStyle(.secondary)
            }
        }
    }

    private var footer: some View {
        HStack {
            if step > 0 { Button("Back") { step -= 1 } }
            Spacer()
            if skippable { Button("Skip for now") { advance() } }
            Button(step == 5 ? "Finish" : "Continue") {
                if step == 5, let u = projectURL, !projectName.isEmpty {
                    coordinator.registry.add(Project(name: projectName, path: u.path,
                                                     aliases: projectAliases.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty },
                                                     defaultAgent: projectAgent))
                }
                advance()
            }
            .buttonStyle(.borderedProminent).disabled(!canContinue)
        }
    }

    private var skippable: Bool { step == 3 || step == 4 || step == 5 }
    private var canContinue: Bool {
        switch step {
        case 1: micOK && speechOK
        case 2: chordPressed && chordReleased
        case 3: claudeVersion != nil
        case 5: projectURL != nil && !projectName.isEmpty || !coordinator.registry.projects.isEmpty
        default: true
        }
    }

    private func advance() {
        if step == 5 { coordinator.settings.settings.onboardingComplete = true; onDone() } else { step += 1 }
    }

    private func openPane(_ anchor: String) {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!)
    }

    private func startChordTest() {
        stopChordTest()
        chordPressed = false; chordReleased = false
        // Temporarily take over the chord for the live test.
        coordinator.unregisterPushToTalk()
        chordProbe = HotkeyMonitor.shared.register(coordinator.settings.settings.pushToTalk,
                                                   pressed: { chordPressed = true }, released: { chordReleased = true })
    }
    private func stopChordTest() {
        if chordProbe != nil { HotkeyMonitor.shared.unregister(chordProbe); chordProbe = nil; coordinator.registerHotkeys() }
    }

    private func detectAgents() async {
        if let p = coordinator.claudePath {
            claudeVersion = await CLILocator.version(of: p)
            let r = await CLILocator.run(p, ["auth", "status"], timeout: 20)
            claudeLoggedIn = r.stdout.contains("\"loggedIn\": true") || r.stdout.contains("\"loggedIn\":true")
        } else { claudeVersion = nil; claudeLoggedIn = nil }
        if let p = coordinator.codexPath {
            codexVersion = await CLILocator.version(of: p)
            let r = await CLILocator.run(p, ["login", "status"], timeout: 20)
            codexLoggedIn = (r.stdout + r.stderr).localizedCaseInsensitiveContains("logged in")
        } else { codexVersion = nil; codexLoggedIn = nil }
    }
}
