import SwiftUI
import AppKit
import ServiceManagement

/// §5.4 — one compact window, tabs: General · Agents · Voice · Projects.
struct SettingsView: View {
    @Bindable var coordinator: Coordinator
    var body: some View {
        TabView {
            GeneralTab(coordinator: coordinator).tabItem { Label("General", systemImage: "slider.horizontal.3") }
            AgentsTab(coordinator: coordinator).tabItem { Label("Agents", systemImage: "terminal") }
            VoiceTab(coordinator: coordinator).tabItem { Label("Voice", systemImage: "waveform") }
            ProjectsTab(registry: coordinator.registry, settings: coordinator.settings).tabItem { Label("Projects", systemImage: "folder") }
            MemoryTab(memory: coordinator.memory).tabItem { Label("Memory", systemImage: "brain") }
        }
        .frame(width: 520, height: 420)
    }
}

struct GeneralTab: View {
    @Bindable var coordinator: Coordinator
    var body: some View {
        @Bindable var s = coordinator.settings
        Form {
            Section("Shortcuts") {
                LabeledContent("Push to talk") { ShortcutRecorder(hotkey: $s.settings.pushToTalk) }
                LabeledContent("Toggle sessions overlay") { ShortcutRecorder(hotkey: $s.settings.overlayToggle) }
                if let e = coordinator.hotkeyError { Text(e).font(.caption).foregroundStyle(.red) }
            }
            Section {
                Toggle("Launch at login", isOn: Binding(get: { s.settings.launchAtLogin }, set: { v in
                    s.settings.launchAtLogin = v
                    do { if v { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() } } catch { s.settings.launchAtLogin = false }
                }))
                Slider(value: $s.settings.overlayOpacity, in: 0.5...1) { Text("Overlay opacity") }
                Toggle("Speak completion summaries", isOn: $s.settings.speakSummaries)
                Toggle("Mute while a Focus is on", isOn: $s.settings.muteDuringFocus)
                Toggle("Blip when the chord is pressed", isOn: $s.settings.blipOnChordDown)
            }
        }
        .formStyle(.grouped)
        .onChange(of: s.settings.pushToTalk) { coordinator.registerHotkeys() }
        .onChange(of: s.settings.overlayToggle) { coordinator.registerHotkeys() }
    }
}

struct AgentsTab: View {
    @Bindable var coordinator: Coordinator
    @State private var claudeVersion = "…"
    @State private var codexVersion = "…"
    var body: some View {
        @Bindable var s = coordinator.settings
        Form {
            Section("Detected") {
                LabeledContent("claude") { Text(coordinator.claudePath.map { "\($0)  ·  \(claudeVersion)" } ?? "not found").font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }
                LabeledContent("codex") { Text(coordinator.codexPath.map { "\($0)  ·  \(codexVersion)" } ?? "not found").font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }
            }
            Section("Defaults") {
                Picker("Default agent", selection: $s.settings.defaultAgent) { ForEach(AgentKind.allCases) { Text($0.displayName).tag($0) } }
                Picker("Claude permission mode", selection: $s.settings.claudePermissionMode) { ForEach(PermissionMode.allCases) { Text($0.displayName).tag($0) } }
                Picker("Codex permission mode", selection: $s.settings.codexPermissionMode) { ForEach(PermissionMode.allCases) { Text($0.displayName).tag($0) } }
                Stepper("Max concurrent sessions: \(s.settings.maxConcurrentSessions)", value: $s.settings.maxConcurrentSessions, in: 1...6)
            }
        }
        .formStyle(.grouped)
        .task {
            if let p = coordinator.claudePath { claudeVersion = await CLILocator.version(of: p) ?? "?" }
            if let p = coordinator.codexPath { codexVersion = await CLILocator.version(of: p) ?? "?" }
        }
    }
}

struct VoiceTab: View {
    @Bindable var coordinator: Coordinator
    @State private var keyField = ""
    @State private var hasKey = Keychain.get(Keychain.fishKey) != nil
    @State private var balance: String = ""
    @State private var query = ""
    @State private var voices: [FishAudio.Voice] = []
    @State private var status = ""

    var body: some View {
        @Bindable var s = coordinator.settings
        Form {
            Section("Fish Audio") {
                if hasKey {
                    LabeledContent("API key") {
                        HStack { Text("Stored in Keychain").foregroundStyle(.secondary); Button("Clear") { Keychain.delete(Keychain.fishKey); hasKey = false; balance = "" } }
                    }
                    LabeledContent("Credits") { Text(balance.isEmpty ? "…" : balance).foregroundStyle(.secondary) }
                    Picker("Model", selection: $s.settings.fishModel) {
                        Text("Auto (Pro, free if no API credit)").tag("auto")
                        Text("S2.1 Pro — uses API credit").tag("s2.1-pro")
                        Text("S2.1 Pro Free — $0").tag("s2.1-pro-free")
                    }
                    Text("Plan package credits only cover the Fish website. The API bills a separate USD “API credit” balance; the Free model costs nothing.")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    LabeledContent("API key") {
                        SecureField("Paste your Fish Audio key", text: $keyField)
                            .textFieldStyle(.roundedBorder)
                            .frame(minWidth: 260)
                            .onSubmit { saveKey() }
                    }
                    HStack {
                        Spacer()
                        Button("Save to Keychain") { saveKey() }.buttonStyle(.borderedProminent).disabled(keyField.isEmpty)
                    }
                }
                if !status.isEmpty { Text(status).font(.caption).foregroundStyle(.secondary) }
            }
            Section("Voice") {
                LabeledContent("Current") { Text(s.settings.fishVoiceName).foregroundStyle(.secondary) }
                LabeledContent("Search voices") {
                    HStack {
                        TextField("e.g. calm female", text: $query).textFieldStyle(.roundedBorder).frame(minWidth: 160).onSubmit { Task { await search() } }
                        Button("Search") { Task { await search() } }.disabled(!hasKey)
                        Button("Preview") { coordinator.voice.speak("Hi, I'm ready.") }
                    }
                }
                if !voices.isEmpty {
                    List(voices) { v in
                        HStack {
                            VStack(alignment: .leading) { Text(v.title); Text(v.tags.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            if v.id == s.settings.fishVoiceID { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
                        }
                        .contentShape(Rectangle())
                        .onTapGesture { s.settings.fishVoiceID = v.id; s.settings.fishVoiceName = v.title }
                    }.frame(height: 120)
                }
                Slider(value: $s.settings.speakingRate, in: 0.7...1.4) { Text("Speaking rate") }
                Toggle("Fall back to the system voice", isOn: $s.settings.systemVoiceFallback)
            }
        }
        .formStyle(.grouped)
        .task { await refreshBalance() }
    }

    private func saveKey() {
        let k = keyField.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !k.isEmpty else { return }
        if Keychain.set(k, for: Keychain.fishKey) { hasKey = true; keyField = ""; status = ""; Task { await refreshBalance() } }
        else { status = "Couldn't write to the Keychain." }
    }

    private func refreshBalance() async {
        guard let key = Keychain.get(Keychain.fishKey) else { return }
        do { let b = try await FishAudio.balance(apiKey: key); balance = "API credit $\(b.apiCreditUSD) · package \(b.balance.formatted()) (\(b.type))"; status = "" }
        catch { status = "Couldn't fetch balance: \(error)" }
    }
    private func search() async {
        guard let key = Keychain.get(Keychain.fishKey) else { return }
        do { voices = try await FishAudio.searchVoices(apiKey: key, query: query); status = "" } catch { status = "\(error)" }
    }
}

struct ProjectsTab: View {
    @Bindable var registry: ProjectRegistry
    @Bindable var settings: SettingsStore
    @State private var selection: Project.ID?
    var body: some View {
        VStack(spacing: 8) {
            Table(registry.projects, selection: $selection) {
                TableColumn("Name") { p in EditableText(text: binding(p, \.name)) }
                TableColumn("Path") { p in Text(p.path).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle) }
                TableColumn("Aliases") { p in
                    EditableText(text: Binding(get: { p.aliases.joined(separator: ", ") },
                                               set: { v in var q = p; q.aliases = v.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }; registry.update(q) }))
                }
                TableColumn("Agent") { p in
                    Picker("", selection: binding(p, \.defaultAgent)) { ForEach(AgentKind.allCases) { Text($0.displayName).tag($0) } }.labelsHidden()
                }.width(90)
                TableColumn("Permissions") { p in
                    HStack(spacing: 4) {
                        Picker("", selection: binding(p, \.permissionMode)) { ForEach(PermissionMode.allCases) { Text($0.displayName).tag($0) } }.labelsHidden()
                        if p.permissionMode == .acceptEdits { Image(systemName: "hand.raised").foregroundStyle(.secondary).help("Shell commands will be blocked — headless sessions can't approve prompts") }
                    }
                }.width(150)
            }
            .onDrop(of: [.fileURL], isTargeted: nil) { providers in
                for p in providers {
                    _ = p.loadObject(ofClass: URL.self) { url, _ in
                        guard let url, url.hasDirectoryPath else { return }
                        Task { @MainActor in registry.add(Project(name: ProjectRegistry.suggestedName(for: url), path: url.path)) }
                    }
                }
                return true
            }
            HStack {
                Button("+") { addFolder() }
                Button("−") { if let selection { registry.remove(selection) } }.disabled(selection == nil)
                Spacer()
                Text("Drop a folder here to add it").font(.caption).foregroundStyle(.tertiary)
            }
            HStack {
                Text("New projects by voice go in").font(.caption).foregroundStyle(.secondary)
                TextField("~/Projects", text: $settings.settings.projectsRoot).textFieldStyle(.roundedBorder).frame(maxWidth: 220)
                Button("Choose…") {
                    let p = NSOpenPanel(); p.canChooseDirectories = true; p.canChooseFiles = false
                    if p.runModal() == .OK, let u = p.url { settings.settings.projectsRoot = u.path }
                }.controlSize(.small)
            }
            .padding(.horizontal, 12).padding(.bottom, 8)
            .padding(.horizontal, 12).padding(.bottom, 8)
        }
    }

    private func binding<T>(_ p: Project, _ kp: WritableKeyPath<Project, T>) -> Binding<T> {
        Binding(get: { registry.projects.first { $0.id == p.id }?[keyPath: kp] ?? p[keyPath: kp] },
                set: { v in var q = registry.projects.first { $0.id == p.id } ?? p; q[keyPath: kp] = v; registry.update(q) })
    }

    private func addFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            registry.add(Project(name: ProjectRegistry.suggestedName(for: url), path: url.path))
        }
    }
}

struct EditableText: View {
    @Binding var text: String
    var body: some View { TextField("", text: $text).textFieldStyle(.plain) }
}

/// Long-term memory: what Conductor has been told to remember, editable by hand.
struct MemoryTab: View {
    @Bindable var memory: MemoryStore
    @State private var draft = ""
    @State private var selection: Memory.ID?
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Say “remember …” while talking, or add a note here. These are given to the orchestrator on every turn and to every coding agent it starts.")
                .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 12).padding(.top, 10)
            List(selection: $selection) {
                ForEach(memory.memories) { m in
                    HStack(alignment: .top) {
                        Text(m.text).textSelection(.enabled)
                        Spacer()
                        Text(m.createdAt, style: .date).font(.caption2).foregroundStyle(.tertiary)
                    }.tag(m.id)
                }
                if memory.memories.isEmpty { Text("Nothing remembered yet.").foregroundStyle(.tertiary) }
            }
            HStack {
                TextField("Add something to remember…", text: $draft).textFieldStyle(.roundedBorder).onSubmit(add)
                Button("Add", action: add).disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                Button("−") { if let selection { memory.remove(selection); self.selection = nil } }.disabled(selection == nil)
            }.padding(.horizontal, 12)
            HStack {
                Text("\(memory.turns.count) recent exchanges kept for context").font(.caption).foregroundStyle(.tertiary)
                Spacer()
                Button("Clear conversation") { memory.clearTurns() }.controlSize(.small).disabled(memory.turns.isEmpty)
                Button("Forget everything") { memory.clearMemories() }.controlSize(.small).disabled(memory.memories.isEmpty)
            }.padding(.horizontal, 12).padding(.bottom, 8)
        }
    }
    private func add() { memory.remember(draft); draft = "" }
}
