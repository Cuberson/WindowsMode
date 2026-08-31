import Foundation

// MARK: - Agents

enum AgentKind: String, Codable, CaseIterable, Sendable, Identifiable {
    case claude, codex
    var id: String { rawValue }
    var displayName: String { self == .claude ? "Claude" : "Codex" }
}

enum PermissionMode: String, Codable, CaseIterable, Sendable, Identifiable {
    /// Claude: `--permission-mode acceptEdits` · Codex: `-s workspace-write`
    case acceptEdits
    /// Claude: `--permission-mode bypassPermissions` · Codex: `--dangerously-bypass-approvals-and-sandbox`
    case bypassPermissions
    var id: String { rawValue }
    var displayName: String { self == .acceptEdits ? "Accept edits" : "Bypass permissions" }
}

// MARK: - Projects

struct Project: Codable, Identifiable, Hashable, Sendable {
    var id: UUID = UUID()
    var name: String
    var path: String
    var aliases: [String] = []
    var defaultAgent: AgentKind = .claude
    var permissionMode: PermissionMode = .bypassPermissions

    var url: URL { URL(fileURLWithPath: (path as NSString).expandingTildeInPath) }
}

// MARK: - Sessions

enum SessionStatus: String, Codable, Sendable {
    case running, done, needsInput, failed, cancelled
    var isActive: Bool { self == .running }
}

struct Session: Codable, Identifiable, Hashable, Sendable {
    var id: String                 // short id like "s_01"
    var projectName: String
    var projectPath: String
    var agent: AgentKind
    var task: String
    var status: SessionStatus = .running
    var activity: String = ""      // e.g. "Edit src/Hero.tsx"
    var startedAt: Date = Date()
    var finishedAt: Date? = nil
    var agentSessionID: String? = nil   // claude session_id / codex thread_id, for --resume
    var resultText: String = ""         // final agent result (truncated)
    var pid: Int32? = nil
    var dismissed: Bool = false

    var elapsed: TimeInterval { (finishedAt ?? Date()).timeIntervalSince(startedAt) }
}

// MARK: - Orchestrator contract (§4.2)

enum OrchestratorActionKind: String, Codable, Sendable {
    case spawn, followup, cancel, status, open, clarify, chitchat, create
}

struct OrchestratorAction: Codable, Sendable, Equatable {
    var action: OrchestratorActionKind
    var agent: AgentKind?
    var project: String?
    var sessionID: String?
    var task: String?
    var speak: String
    /// A durable fact/preference to store in long-term memory (any action may carry one). nil = nothing new.
    var remember: String? = nil
    /// A phrase identifying a memory to delete. nil = nothing to forget.
    var forget: String? = nil

    enum CodingKeys: String, CodingKey {
        case action, agent, project, task, speak, remember, forget
        case sessionID = "session_id"
    }

    static let jsonSchema: String = """
    {"type":"object","additionalProperties":false,"properties":{"action":{"type":"string","enum":["spawn","followup","cancel","status","open","clarify","chitchat","create"]},"agent":{"type":["string","null"],"enum":["claude","codex",null]},"project":{"type":["string","null"]},"session_id":{"type":["string","null"]},"task":{"type":["string","null"]},"speak":{"type":"string"},"remember":{"type":["string","null"]},"forget":{"type":["string","null"]}},"required":["action","agent","project","session_id","task","speak","remember","forget"]}
    """
}

// MARK: - Memory

/// One durable fact the user told Conductor ("I prefer Tailwind", "call me Albert", "always use Codex for the API project").
struct Memory: Codable, Identifiable, Hashable, Sendable {
    var id: UUID = UUID()
    var text: String
    var createdAt: Date = Date()
}

/// One exchange in the rolling conversation history (what was heard, what was said back).
struct ConversationTurn: Codable, Hashable, Sendable {
    var at: Date = Date()
    var heard: String
    var said: String
    var action: String
    var task: String? = nil
    var project: String? = nil
}

// MARK: - Settings

struct Hotkey: Codable, Hashable, Sendable {
    var keyCode: UInt32
    var modifiers: UInt32   // Carbon modifier mask (cmdKey | shiftKey | optionKey | controlKey)

    static let pushToTalk = Hotkey(keyCode: 49 /* kVK_Space */, modifiers: 0x0100 | 0x0200) // cmd | shift
    static let overlay = Hotkey(keyCode: 31 /* kVK_ANSI_O */, modifiers: 0x0100 | 0x0200)
}

struct Settings: Codable, Sendable {
    var pushToTalk: Hotkey = .pushToTalk
    var overlayToggle: Hotkey = .overlay
    var launchAtLogin: Bool = false
    var overlayOpacity: Double = 1.0
    var speakSummaries: Bool = true
    var muteDuringFocus: Bool = true
    var blipOnChordDown: Bool = true
    var defaultAgent: AgentKind = .claude
    /// Headless sessions cannot answer permission prompts, so "bypass" is the only mode where shell commands actually run.
    var claudePermissionMode: PermissionMode = .bypassPermissions
    var codexPermissionMode: PermissionMode = .bypassPermissions
    var maxConcurrentSessions: Int = 6
    var fishVoiceID: String = "933563129e564b19a115bedd57b7406a" // "Sarah" — picked via search_voices at build time
    var fishVoiceName: String = "Sarah"
    /// "s2.1-pro" bills Fish API credit (USD); "s2.1-pro-free" is $0 and needs no API credit. "auto" tries pro, falls back to free on 402.
    var fishModel: String = "auto"
    var speakingRate: Double = 1.0
    var systemVoiceFallback: Bool = true
    var overlayOrigin: CGPoint? = nil
    var overlayVisible: Bool = true
    var onboardingComplete: Bool = false
    /// Where voice-created projects are made (§ create action).
    var projectsRoot: String = "~/Projects"
    var claudePathOverride: String? = nil
    var codexPathOverride: String? = nil
}
