import Foundation
import AppKit
import AVFoundation
import Observation

/// Central state machine (§2). Owns the services and drives the pill + overlay.
@MainActor @Observable
final class Coordinator {
    let settings: SettingsStore
    let registry: ProjectRegistry
    let sessions: SessionStore
    let memory: MemoryStore
    let speech: SpeechService
    let voice: VoiceService
    let pill = PillModel()

    private var runners: [String: AgentRunner] = [:]
    private var clarifyContext: String?
    private var holdStart: Date?
    private var debounceTask: Task<Void, Never>?
    private var listeningActive = false
    private var hideTask: Task<Void, Never>?
    private var blip: AVAudioPlayer?
    private var pttID: UInt32?
    private var overlayID: UInt32?
    private var escID: UInt32?
    /// Bumped by Esc so an in-flight orchestrator turn's result is dropped instead of spoken.
    private var turnGeneration = 0

    var onPillChanged: (() -> Void)?

    private func pillDidChange() {
        onPillChanged?()
        syncEscapeHotkey()
    }

    /// Esc only exists as a hotkey while the pill is showing, so it never steals Esc from other apps.
    private func syncEscapeHotkey() {
        if pill.visible, escID == nil {
            escID = HotkeyMonitor.shared.register(Hotkey(keyCode: 53 /* kVK_Escape */, modifiers: 0), pressed: { [weak self] in self?.resetConversation() })
        } else if !pill.visible, let id = escID {
            HotkeyMonitor.shared.unregister(id); escID = nil
        }
    }

    /// Esc: abandon whatever is happening in the voice loop and start a fresh chat. Coding sessions are untouched.
    func resetConversation() {
        AppLog.write("escape: reset conversation")
        turnGeneration += 1
        voice.stop()
        if speech.isListening { Task { _ = await speech.stop() } }
        listeningActive = false; holdStart = nil
        debounceTask?.cancel(); debounceTask = nil
        hideTask?.cancel()
        clarifyContext = nil
        memory.record(heard: "(pressed Esc — cancelled that exchange)", said: "", action: "cancelled", task: nil)
        pill.visible = false; pill.secondary = ""; pill.transcript = ""; pill.state = .listening
        pillDidChange()
    }
    var onOverlayToggle: (() -> Void)?
    var onLevelChanged: (() -> Void)?
    private(set) var hotkeyError: String?

    var claudePath: String? { CLILocator.find("claude", override: settings.settings.claudePathOverride) }
    var codexPath: String? { CLILocator.find("codex", override: settings.settings.codexPathOverride) }

    init() {
        settings = SettingsStore()
        registry = ProjectRegistry()
        sessions = SessionStore()
        memory = MemoryStore()
        speech = SpeechService()
        voice = VoiceService(settings: settings)
        voice.onFinished = { [weak self] in self?.didFinishSpeaking() }
        blip = try? AVAudioPlayer(data: Self.blipWAV()); blip?.volume = 0.35; blip?.prepareToPlay()
        registerHotkeys()
        Self.rotateLogs()
    }

    /// Keep session logs for the sessions we still know about (≤100) and drop the rest.
    private static func rotateLogs() {
        let keep = Set((JSONStore.load([Session].self, from: AppPaths.sessions) ?? []).map { "\($0.id).ndjson" })
        let files = (try? FileManager.default.contentsOfDirectory(atPath: AppPaths.logs.path)) ?? []
        for f in files where f.hasSuffix(".ndjson") && !keep.contains(f) {
            try? FileManager.default.removeItem(at: AppPaths.logs.appendingPathComponent(f))
        }
    }

    // MARK: Hotkeys

    func registerHotkeys() {
        HotkeyMonitor.shared.unregister(pttID); HotkeyMonitor.shared.unregister(overlayID)
        pttID = HotkeyMonitor.shared.register(settings.settings.pushToTalk,
                                              pressed: { [weak self] in self?.chordDown() },
                                              released: { [weak self] in self?.chordUp() })
        overlayID = HotkeyMonitor.shared.register(settings.settings.overlayToggle, pressed: { [weak self] in self?.onOverlayToggle?() })
        AppLog.write("hotkeys: ptt=\(String(describing: pttID)) overlay=\(String(describing: overlayID))")
        hotkeyError = pttID == nil ? "\(settings.settings.pushToTalk.display) is owned by another app — change it in Settings." : nil
    }

    func unregisterPushToTalk() { HotkeyMonitor.shared.unregister(pttID); pttID = nil }

    // MARK: Push-to-talk (§3.6 semantics)

    private func chordDown() {
        AppLog.write("chord down")
        holdStart = Date()
        if voice.isSpeaking { voice.stop() }   // barge-in
        debounceTask?.cancel()
        debounceTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(150))
            guard let self, !Task.isCancelled, holdStart != nil else { return }
            beginListening()
        }
    }

    private func chordUp() {
        AppLog.write("chord up (listening=\(listeningActive))")
        let started = holdStart; holdStart = nil
        debounceTask?.cancel(); debounceTask = nil
        guard let started, Date().timeIntervalSince(started) >= 0.15, listeningActive else { return }
        Task { await finishListening() }
    }

    private func beginListening() {
        listeningActive = true
        hideTask?.cancel()
        if settings.settings.blipOnChordDown { blip?.currentTime = 0; blip?.play() }
        pill.state = .listening; pill.transcript = ""; pill.secondary = clarifyContext ?? ""; pill.fallbackBadge = false
        pill.visible = true; pillDidChange()
        speech.start()
        AppLog.write("stt start error=\(speech.error ?? "none") mic=\(SpeechService.micStatus.rawValue) speech=\(SpeechService.speechStatus.rawValue)")
        if let e = speech.error { showError(e); listeningActive = false; return }
        startLevelUpdates()
    }

    private func startLevelUpdates() {
        Task { @MainActor [weak self] in
            while let self, self.speech.isListening {
                self.pill.level = self.speech.level
                self.pill.transcript = self.speech.transcript
                self.onLevelChanged?()
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
    }

    /// Fix the mis-hearings that matter for routing before Haiku sees them.
    nonisolated static func normalizeTranscript(_ t: String) -> String {
        var s = t
        let fixes: [(String, String)] = [
            (#"\b(k|c)o[\s-]?de(x|cks|cs|ks|x's)\b"#, "Codex"), (#"\bcodecs?\b"#, "Codex"), (#"\bcode[\s-]?x\b"#, "Codex"), (#"\bcortex\b"#, "Codex"),
            (#"\bclaud\b"#, "Claude"), (#"\bcloud code\b"#, "Claude Code"), (#"\bcloud\b(?=\s+(to|and|should|can|will|code))"#, "Claude"),
        ]
        for (pat, rep) in fixes { s = s.replacingOccurrences(of: pat, with: rep, options: [.regularExpression, .caseInsensitive]) }
        return s
    }

    private func finishListening() async {
        listeningActive = false
        pill.state = .thinking; pillDidChange()
        let text = Self.normalizeTranscript(await speech.stop())
        AppLog.write("stt final: \"\(text)\"")
        pill.transcript = text; pillDidChange()
        guard !text.trimmingCharacters(in: .whitespaces).isEmpty else { dismissPill(after: 0.6); return }
        await handle(transcript: text)
    }

    // MARK: Orchestration (§4)

    private var orchestratorTurn: Task<Void, Never>?

    func handle(transcript: String) async {
        guard let claudePath else { showError("Claude Code CLI not found"); return }
        // One orchestrator turn at a time — concurrent `claude -p` instances slow each other down.
        let previous = orchestratorTurn
        let turn = Task { @MainActor in await previous?.value; await self.handleSerialized(transcript: transcript, claudePath: claudePath) }
        orchestratorTurn = turn
        await turn.value
    }

    private func handleSerialized(transcript: String, claudePath: String) async {
        let orch = Orchestrator(claudePath: claudePath)
        let gen = turnGeneration
        let action = await orch.decide(transcript: transcript, projects: registry.promptSummary, sessions: sessions.promptSummary,
                                       maxSessions: settings.settings.maxConcurrentSessions, runningCount: sessions.running.count,
                                       context: clarifyContext, memories: memory.promptSummary, history: memory.turnsSummary)
        guard gen == turnGeneration else { AppLog.write("turn dropped (escaped): \"\(transcript)\""); return }
        let priorContext = clarifyContext
        clarifyContext = nil
        AppLog.write("transcript=\"\(transcript)\" → \(action)")
        await perform(action, transcript: priorContext.map { "\($0) / \(transcript)" } ?? transcript)
    }

    /// Haiku sometimes routes "open it on localhost / in the browser" to `open`, which pops a Terminal window.
    /// Only a literal folder/terminal/editor request may reach `open`; everything else becomes agent work.
    static func sanitize(_ a: OrchestratorAction, transcript: String) -> OrchestratorAction {
        guard a.action == .open else { return a }
        let t = transcript.lowercased()
        let wantsShell = ["terminal", "finder", "folder", "directory", "editor", "vs code", "vscode", "cursor", "xcode"].contains { t.contains($0) }
        let wantsWork = ["localhost", "browser", "port", "http", "run ", "serve", "preview", "deploy", "test", "start", "website", "site", "app"].contains { t.contains($0) }
        if wantsShell && !wantsWork { return a }
        guard a.task != nil || wantsWork else { return a }   // bare "open X" with no work verbs: honour it
        var b = a
        b.action = .followup
        b.task = a.task ?? transcript
        b.sessionID = nil
        AppLog.write("sanitize: open → followup (\"\(transcript)\")")
        return b
    }

    func perform(_ raw: OrchestratorAction, transcript: String) async {
        let a = Self.sanitize(raw, transcript: transcript)
        // Memory side-effects happen regardless of which action was chosen.
        if let f = a.forget, !f.isEmpty { let n = memory.forget(f); if n == 0 && a.action == .chitchat { say("I didn't have anything like that saved."); memory.record(heard: transcript, said: "nothing to forget", action: "forget"); return } }
        if let r = a.remember, !r.isEmpty { memory.remember(r) }
        var speak = a.speak
        switch a.action {
        case .spawn:
            guard sessions.running.count < settings.settings.maxConcurrentSessions else { speak = "Six sessions are already running. Finish one first."; break }
            var resolved = registry.resolve(a.project) ?? (a.project == nil ? generalProject() : nil)
            // Unknown project name + a concrete task: create it on the spot rather than asking.
            if resolved == nil, let name = a.project, let task = a.task, !task.isEmpty, let made = try? createProject(named: name) {
                resolved = made
                if speak.isEmpty { speak = "Created \(made.name) — starting now." }
            }
            guard let project = resolved else {
                clarifyContext = transcript
                pill.state = .clarify; pill.secondary = registry.projects.isEmpty ? "No projects yet — add one in Settings." : "Which project?"
                speak = registry.projects.isEmpty ? "You haven't added any projects yet." : (a.speak.isEmpty ? "Which project?" : a.speak)
                break
            }
            guard let task = a.task, !task.isEmpty else { clarifyContext = transcript; pill.state = .clarify; speak = "What should it do?"; break }
            let agent = a.agent ?? project.defaultAgent
            if spawn(project: project, agent: agent, task: task) == false { speak = spawnFailureSpeech(project, agent) }
        case .followup:
            guard let task = a.task, !task.isEmpty else { speak = "What should it do?"; clarifyContext = transcript; pill.state = .clarify; break }
            if let s = resolveSession(a.sessionID, project: a.project) {
                followUp(session: s, task: task)
            } else if let project = registry.resolve(a.project) {
                // No session for that project yet — a follow-up is just a spawn.
                if spawn(project: project, agent: a.agent ?? project.defaultAgent, task: task) == false { speak = spawnFailureSpeech(project, project.defaultAgent) }
                else if speak.isEmpty { speak = "Starting on \(project.name)." }
            } else {
                speak = "Which project?"; clarifyContext = transcript; pill.state = .clarify
            }
        case .cancel:
            guard let s = resolveSession(a.sessionID, project: a.project, runningOnly: true) else { speak = sessions.running.isEmpty ? "Nothing is running." : "Which one?"; break }
            stop(sessionID: s.id)
        case .status:
            if speak.isEmpty { speak = statusSentence() }
        case .open:
            if let s = resolveSession(a.sessionID, project: a.project) { open(session: s) }
            else if let p = registry.resolve(a.project) { openTerminal(at: p.url) }
            else { speak = "Which project?" }
        case .clarify:
            clarifyContext = transcript
            pill.state = .clarify; pill.secondary = VoiceService.stripCues(a.speak)
        case .chitchat:
            if speak.isEmpty, a.remember != nil { speak = "Got it, I'll remember that." }
            if speak.isEmpty, a.forget != nil { speak = "Forgotten." }
        case .create:
            guard let name = a.project?.trimmingCharacters(in: .whitespaces), !name.isEmpty else {
                clarifyContext = transcript; pill.state = .clarify; pill.secondary = "What should it be called?"; speak = "What should the project be called?"; break
            }
            do {
                let project = try createProject(named: name)
                if let task = a.task, !task.isEmpty {
                    let agent = a.agent ?? settings.settings.defaultAgent
                    if spawn(project: project, agent: agent, task: task) == false { speak = spawnFailureSpeech(project, agent) }
                } else {
                    clarifyContext = transcript; pill.state = .clarify; pill.secondary = "What should I build?"
                    speak = "Created \(project.name). What should I build in it?"
                }
            } catch {
                speak = "Couldn't create the project: \(error.localizedDescription)"
            }
        }
        memory.record(heard: transcript, said: speak, action: a.action.rawValue, task: a.task, project: a.project)
        say(speak)
    }

    /// Workspace for non-project requests ("check my calendar"): `<projectsRoot>/general`, created on demand.
    /// Claude Code runs there with the user's normal MCP servers (calendar, mail, …) so it can actually do the job.
    func generalProject() -> Project? {
        let root = URL(fileURLWithPath: (settings.settings.projectsRoot as NSString).expandingTildeInPath, isDirectory: true)
        let dir = root.appendingPathComponent("general", isDirectory: true)
        guard (try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)) != nil else { return nil }
        return Project(name: "General", path: dir.path, aliases: ["general"], defaultAgent: .claude, permissionMode: settings.settings.claudePermissionMode)
    }

    private func spawnFailureSpeech(_ p: Project, _ agent: AgentKind) -> String {
        switch lastSpawnFailure {
        case .missingCLI: "\(agent.displayName) CLI isn't installed."
        case .missingFolder: "The folder for \(p.name) doesn't exist — fix its path in Settings."
        case .launch: "Couldn't launch \(agent.displayName) — check the log."
        case nil: "Couldn't start that."
        }
    }

    private func resolveSession(_ id: String?, project: String?, runningOnly: Bool = false) -> Session? {
        if let id, let s = sessions.session(id) { return s }
        let pool = runningOnly ? sessions.running : sessions.visible
        if let p = registry.resolve(project), let s = pool.first(where: { $0.projectName == p.name }) { return s }
        return pool.count == 1 ? pool.first : nil
    }

    func statusSentence() -> String {
        let r = sessions.running
        if r.isEmpty { return "Nothing is running right now." }
        return r.map { "\($0.projectName) on \($0.agent.displayName), \(SessionStore.format($0.elapsed))" }.joined(separator: "; ") + "."
    }

    // MARK: Sessions

    enum SpawnFailure { case missingCLI, missingFolder, launch(String) }
    private(set) var lastSpawnFailure: SpawnFailure?

    @discardableResult
    func spawn(project: Project, agent: AgentKind, task: String, resume: String? = nil, existingID: String? = nil) -> Bool {
        lastSpawnFailure = nil
        guard let exe = agent == .claude ? claudePath : codexPath else { lastSpawnFailure = .missingCLI; return false }
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: project.url.path, isDirectory: &isDir), isDir.boolValue else {
            lastSpawnFailure = .missingFolder
            AppLog.write("spawn refused: folder missing \(project.url.path)")
            return false
        }
        let id = existingID ?? sessions.nextID()
        if existingID == nil {
            sessions.insert(Session(id: id, projectName: project.name, projectPath: project.path, agent: agent, task: task))
        } else {
            sessions.update(id) { $0.status = .running; $0.task = task; $0.finishedAt = nil; $0.activity = ""; $0.startedAt = Date(); $0.dismissed = false }
        }
        let runner = AgentRunner(sessionID: id, agent: agent,
            onEvent: { [weak self] e in self?.handleEvent(e, for: id) },
            onExit: { [weak self] code, text in self?.handleExit(code: code, lastText: text, for: id) })
        let mode = project.permissionMode
        do {
            try runner.start(executable: exe, task: task, cwd: project.url.path, mode: mode, resume: resume, extraGuidance: memory.agentGuidance)
            runners[id] = runner
            sessions.update(id) { $0.pid = runner.pid }
            return true
        } catch {
            lastSpawnFailure = .launch("\(error)")
            sessions.update(id) { $0.status = .failed; $0.finishedAt = Date(); $0.activity = "Failed to launch: \(error)" }
            return false
        }
    }

    func followUp(session s: Session, task: String) {
        guard let project = registry.projects.first(where: { $0.name == s.projectName }) ?? registry.resolve(s.projectName) else { return }
        if s.status == .running {
            // A running headless session cannot take stdin; queue as a resume after it finishes.
            pendingFollowups[s.id, default: []].append(task)
            sessions.update(s.id) { $0.activity = "Follow-up queued" }
        } else {
            spawn(project: project, agent: s.agent, task: task, resume: s.agentSessionID, existingID: s.id)
        }
    }
    private var pendingFollowups: [String: [String]] = [:]

    func stop(sessionID: String) {
        guard let r = runners[sessionID] else { return }
        sessions.update(sessionID) { $0.status = .cancelled; $0.activity = "Stopping…" }
        r.stop()
    }

    func stopAll() {
        for (_, r) in runners { r.kill() }
        for s in sessions.running { sessions.update(s.id) { $0.status = .cancelled; $0.finishedAt = Date() } }
    }

    private func handleEvent(_ e: AgentEvent, for id: String) {
        switch e {
        case .sessionID(let sid): sessions.update(id) { $0.agentSessionID = sid }
        case .activity(let a): sessions.update(id) { if $0.status == .running { $0.activity = a } }
        case .text(let t): sessions.update(id) { $0.resultText = String(t.suffix(4000)) }
        case .needsInput: sessions.update(id) { $0.status = .needsInput }
        case .result(let t, let err):
            sessions.update(id) {
                if !t.isEmpty { $0.resultText = String(t.suffix(4000)) }
                if err && $0.status == .running { $0.status = .failed }
            }
        }
    }

    private func handleExit(code: Int32, lastText: String, for id: String) {
        AppLog.write("session \(id) exited \(code)")
        runners.removeValue(forKey: id)
        guard var s = sessions.session(id) else { return }
        let wasCancelled = s.status == .cancelled
        sessions.update(id) {
            $0.finishedAt = Date(); $0.pid = nil
            if $0.status == .running { $0.status = code == 0 ? .done : .failed }
            if $0.status == .cancelled { $0.activity = "" }
            if $0.status == .failed && code != 0 && $0.activity.isEmpty { $0.activity = "Exit \(code)" }
        }
        s = sessions.session(id)!
        if let next = pendingFollowups[id]?.first {
            pendingFollowups[id]?.removeFirst()
            if pendingFollowups[id]?.isEmpty == true { pendingFollowups[id] = nil }
            followUp(session: s, task: next)
            return
        }
        guard !wasCancelled, settings.settings.speakSummaries, let claudePath else { return }
        Task {
            let summary = await Orchestrator(claudePath: claudePath).summarize(task: s.task, project: s.projectName, result: s.resultText.isEmpty ? lastText : s.resultText,
                                                                              isError: s.status != .done, exitCode: code)
            announce(summary)
        }
    }

    // MARK: Create

    struct CreateError: LocalizedError { let msg: String; var errorDescription: String? { msg } }

    /// Makes `<projectsRoot>/<slug>`, `git init`s it, and registers it (reuses an existing folder or registry entry).
    @discardableResult
    func createProject(named rawName: String) throws -> Project {
        let name = rawName.replacingOccurrences(of: "project", with: "", options: .caseInsensitive).trimmingCharacters(in: .whitespaces)
        let generic: Set<String> = ["", "new", "a new", "another", "untitled", "site", "website", "app", "thing", "one"]
        if generic.contains(name.lowercased()) { throw CreateError(msg: "I need a real name for it — what should it be called?") }
        if let existing = registry.projects.first(where: { $0.name.caseInsensitiveCompare(name) == .orderedSame || $0.aliases.contains { $0.caseInsensitiveCompare(name) == .orderedSame } }) { return existing }
        let slug = name.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }.joined(separator: "-")
        guard !slug.isEmpty else { throw CreateError(msg: "I didn't catch a name.") }
        let root = URL(fileURLWithPath: (settings.settings.projectsRoot as NSString).expandingTildeInPath, isDirectory: true)
        let dir = root.appendingPathComponent(slug, isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: dir.appendingPathComponent(".git").path), let git = CLILocator.find("git") {
            Task.detached { _ = await CLILocator.run(git, ["init", "-q"], cwd: dir.path, timeout: 20) }
        }
        let aliases = [slug.replacingOccurrences(of: "-", with: " ")].filter { $0 != name.lowercased() }
        let agent = settings.settings.defaultAgent
        let project = Project(name: name, path: dir.path, aliases: aliases, defaultAgent: agent,
                              permissionMode: agent == .claude ? settings.settings.claudePermissionMode : settings.settings.codexPermissionMode)
        registry.add(project)
        AppLog.write("created project \(name) at \(dir.path)")
        return project
    }

    // MARK: Open

    func open(session s: Session) {
        let url = URL(fileURLWithPath: (s.projectPath as NSString).expandingTildeInPath)
        if s.agent == .claude, let sid = s.agentSessionID, s.status != .running {
            openTerminal(at: url, command: "claude --resume \(sid)")
        } else if s.agent == .codex, let sid = s.agentSessionID, s.status != .running {
            openTerminal(at: url, command: "codex resume \(sid)")
        } else {
            openTerminal(at: url)
        }
    }

    func openTerminal(at url: URL, command: String? = nil) {
        let path = url.path.replacingOccurrences(of: "'", with: "'\\''")
        var script = "tell application \"Terminal\"\nactivate\ndo script \"cd '\(path)'"
        if let command { script += "; \(command.replacingOccurrences(of: "\"", with: "\\\""))" }
        script += "\"\nend tell"
        NSAppleScript(source: script)?.executeAndReturnError(nil)
    }

    func showLog(_ s: Session) { NSWorkspace.shared.open(AppPaths.log(for: s.id)) }

    // MARK: Voice / pill

    private func say(_ text: String) {
        AppLog.write("speak: \(text)")
        guard !text.isEmpty else { dismissPill(after: 0.25); return }
        if pill.state != .clarify { pill.state = .speaking }
        pill.transcript = VoiceService.stripCues(text)
        pill.visible = true; pillDidChange()
        if isDoNotDisturb && settings.settings.muteDuringFocus { dismissPill(after: 2.5); return }
        voice.speak(text)
        pill.fallbackBadge = !voice.hasFishKey
        pillDidChange()
    }

    /// Completion summaries: speak (unless DND) and flash the pill.
    func announce(_ text: String) {
        AppLog.write("announce: \(text)")
        pill.state = .speaking; pill.transcript = VoiceService.stripCues(text); pill.secondary = ""; pill.visible = true; pillDidChange()
        if isDoNotDisturb && settings.settings.muteDuringFocus { dismissPill(after: 3); return }
        voice.speak(text); pill.fallbackBadge = !voice.hasFishKey; pillDidChange()
    }

    private func didFinishSpeaking() {
        if pill.state == .clarify { dismissPill(after: 8) } else { dismissPill(after: 0.25) }
    }

    private func showError(_ msg: String) {
        pill.state = .error; pill.transcript = pill.transcript.isEmpty ? "Couldn't listen" : pill.transcript; pill.secondary = msg
        pill.visible = true; pillDidChange()
        dismissPill(after: 3)
    }

    private func dismissPill(after s: TimeInterval) {
        hideTask?.cancel()
        hideTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(s))
            guard let self, !Task.isCancelled, !listeningActive else { return }
            pill.visible = false; pill.secondary = ""; pillDidChange()
        }
    }

    /// Best-effort Focus detection: macOS keeps Focus assertions in this per-user DB.
    var isDoNotDisturb: Bool {
        let url = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/DoNotDisturb/DB/Assertions.json")
        guard let data = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let records = (o["data"] as? [[String: Any]])?.first?["storeAssertionRecords"] as? [[String: Any]] else { return false }
        return !records.isEmpty
    }

    /// 40 ms 880 Hz sine with a half-sine envelope, as 16-bit mono WAV (§5.5 — no bundled asset needed).
    nonisolated static func blipWAV() -> Data {
        let sr = 44100, n = Int(0.04 * Double(sr))
        var pcm = Data(capacity: n * 2)
        for i in 0..<n {
            let env = sin(Double.pi * Double(i) / Double(n))
            let v = Int16(12000 * sin(2 * Double.pi * 880 * Double(i) / Double(sr)) * env)
            withUnsafeBytes(of: v.littleEndian) { pcm.append(contentsOf: $0) }
        }
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        d.append(contentsOf: Array("RIFF".utf8)); u32(UInt32(36 + pcm.count)); d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8)); u32(16); u16(1); u16(1); u32(UInt32(sr)); u32(UInt32(sr * 2)); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(UInt32(pcm.count)); d.append(pcm)
        return d
    }

    // MARK: Quit

    func prepareForQuit() { stopAll() }
}
