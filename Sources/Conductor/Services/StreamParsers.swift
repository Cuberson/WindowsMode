import Foundation

/// Events normalised across both agents.
enum AgentEvent: Equatable, Sendable {
    case sessionID(String)
    case activity(String)          // "Edit src/Hero.tsx"
    case text(String)              // assistant prose
    case needsInput                // permission denial / blocked
    case result(text: String, isError: Bool)
}

/// Parser for `claude -p --output-format stream-json --verbose` NDJSON.
/// Written against Tests/ConductorTests/Fixtures/claude-stream.ndjson captured from claude 2.1.239.
enum ClaudeStreamParser {
    static func parse(line: String) -> [AgentEvent] {
        guard let data = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [] }
        var events: [AgentEvent] = []
        let type = obj["type"] as? String ?? ""

        switch type {
        case "system":
            if obj["subtype"] as? String == "init", let sid = obj["session_id"] as? String { events.append(.sessionID(sid)) }
            if obj["subtype"] as? String == "task_summary", let d = obj["detail"] as? String, !d.isEmpty { events.append(.activity(d)) }
        case "assistant":
            guard let msg = obj["message"] as? [String: Any], let content = msg["content"] as? [[String: Any]] else { break }
            for block in content {
                switch block["type"] as? String {
                case "tool_use":
                    let name = block["name"] as? String ?? "Tool"
                    let input = block["input"] as? [String: Any] ?? [:]
                    events.append(.activity(describeTool(name, input)))
                case "text":
                    if let t = block["text"] as? String, !t.isEmpty { events.append(.text(t)) }
                default: break
                }
            }
        case "result":
            let isError = obj["is_error"] as? Bool ?? false
            let text = obj["result"] as? String ?? (obj["subtype"] as? String ?? "")
            if let sid = obj["session_id"] as? String { events.append(.sessionID(sid)) }
            if let denials = obj["permission_denials"] as? [[String: Any]], !denials.isEmpty { events.append(.needsInput) }
            events.append(.result(text: text, isError: isError))
        default:
            break
        }
        return events
    }

    static func describeTool(_ name: String, _ input: [String: Any]) -> String {
        func short(_ p: String) -> String {
            let parts = p.split(separator: "/")
            return parts.suffix(3).joined(separator: "/")
        }
        if let fp = input["file_path"] as? String { return "\(name) \(short(fp))" }
        if let cmd = input["command"] as? String { return "Run \(cmd.prefix(60))" }
        if let pat = input["pattern"] as? String { return "\(name) \(pat.prefix(40))" }
        if let q = input["query"] as? String { return "\(name) \(q.prefix(40))" }
        if let d = input["description"] as? String { return "\(name) \(d.prefix(50))" }
        return name
    }
}

/// Parser for `codex exec --json` JSONL (codex-cli 0.147).
/// Written against Tests/ConductorTests/Fixtures/codex-stream.ndjson.
enum CodexStreamParser {
    static func parse(line: String) -> [AgentEvent] {
        guard let data = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [] }
        let type = obj["type"] as? String ?? ""
        switch type {
        case "thread.started":
            if let id = obj["thread_id"] as? String { return [.sessionID(id)] }
        case "item.started", "item.completed":
            guard let item = obj["item"] as? [String: Any] else { return [] }
            switch item["type"] as? String {
            case "agent_message":
                if let t = item["text"] as? String, !t.isEmpty { return [.text(t)] }
            case "file_change":
                let paths = (item["changes"] as? [[String: Any]] ?? []).compactMap { $0["path"] as? String }
                if let p = paths.first { return [.activity("Edit \(p.split(separator: "/").suffix(2).joined(separator: "/"))")] }
            case "command_execution":
                if let c = item["command"] as? String { return [.activity("Run \(c.prefix(60))")] }
            case "reasoning":
                return [.activity("Thinking…")]
            default: break
            }
        case "turn.completed":
            return [.result(text: "", isError: false)]
        case "turn.failed", "error":
            let msg = (obj["error"] as? [String: Any])?["message"] as? String ?? obj["message"] as? String ?? "Codex error"
            return [.result(text: msg, isError: true)]
        default: break
        }
        return []
    }
}
