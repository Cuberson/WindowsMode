import XCTest
@testable import Conductor

final class ParserTests: XCTestCase {
    private func fixture(_ name: String) throws -> String {
        let url = Bundle.module.url(forResource: "Fixtures", withExtension: nil)!.appendingPathComponent(name)
        return try String(contentsOf: url, encoding: .utf8)
    }

    func testClaudeStreamFixture() throws {
        let events = try fixture("claude-stream.ndjson").split(separator: "\n").flatMap { ClaudeStreamParser.parse(line: String($0)) }
        XCTAssertTrue(events.contains(.sessionID("9e420cbc-12de-4457-b50b-67e7c18c3af5")))
        XCTAssertTrue(events.contains(.activity("Write Projects/website/hello.txt")))
        XCTAssertTrue(events.contains(.activity("Writing hello.txt")))
        XCTAssertTrue(events.contains(.text("Done.")))
        XCTAssertTrue(events.contains(.result(text: "Done.", isError: false)))
        XCTAssertFalse(events.contains(.needsInput))
    }

    func testCodexStreamFixture() throws {
        let events = try fixture("codex-stream.ndjson").split(separator: "\n").flatMap { CodexStreamParser.parse(line: String($0)) }
        XCTAssertTrue(events.contains(.sessionID("01a02d7f-1dcf-7842-a741-d4ffadca1a1a")))
        XCTAssertTrue(events.contains(.activity("Edit website/bye.txt")))
        XCTAssertTrue(events.contains(.text("Creating `bye.txt` with the requested content.")))
        XCTAssertEqual(events.last, .result(text: "", isError: false))
    }

    func testGarbageLinesIgnored() {
        XCTAssertTrue(ClaudeStreamParser.parse(line: "not json").isEmpty)
        XCTAssertTrue(CodexStreamParser.parse(line: "Reading additional input from stdin...").isEmpty)
    }
}

final class OrchestratorTests: XCTestCase {
    func testParsesStructuredOutputEnvelope() throws {
        let url = Bundle.module.url(forResource: "Fixtures", withExtension: nil)!.appendingPathComponent("orchestrator-result.json")
        let json = try String(contentsOf: url, encoding: .utf8)
        // Real envelope captured from claude 2.1.239 (2-field schema); missing optional keys decode as nil.
        let a = Orchestrator.parse(resultJSON: json)
        XCTAssertEqual(a?.action, .status); XCTAssertNil(a?.project); XCTAssertFalse(a?.speak.isEmpty ?? true)
    }

    func testParsesFullContract() {
        let env = #"{"type":"result","result":"{\"action\":\"spawn\",\"agent\":\"claude\",\"project\":\"website\",\"session_id\":null,\"task\":\"Change the hero headline to 'Build faster with AI' and deploy\",\"speak\":\"On it.\"}","structured_output":{"action":"spawn","agent":"claude","project":"website","session_id":null,"task":"Change the hero headline to 'Build faster with AI' and deploy","speak":"On it."}}"#
        let a = Orchestrator.parse(resultJSON: env)
        XCTAssertEqual(a?.action, .spawn)
        XCTAssertEqual(a?.agent, .claude)
        XCTAssertEqual(a?.project, "website")
        XCTAssertNil(a?.sessionID)
        XCTAssertEqual(a?.speak, "On it.")
    }

    func testFallsBackToResultTextWithProse() {
        let env = #"{"type":"result","result":"Sure! {\"action\":\"status\",\"agent\":null,\"project\":null,\"session_id\":null,\"task\":null,\"speak\":\"Nothing running.\"}"}"#
        XCTAssertEqual(Orchestrator.parse(resultJSON: env)?.action, .status)
    }

    func testArgsNeverContainAPIKeys() {
        let args = Orchestrator.baseArgs().joined(separator: " ")
        XCTAssertFalse(args.contains("api-key")); XCTAssertTrue(args.contains("--tools "))
        XCTAssertNil(CLILocator.childEnvironment["ANTHROPIC_API_KEY"])
        XCTAssertNil(CLILocator.childEnvironment["OPENAI_API_KEY"])
    }

    func testRunnerArguments() {
        XCTAssertEqual(AgentRunner.arguments(agent: .codex, task: "t", mode: .acceptEdits, resume: nil).prefix(2), ["exec", "--json"])
        XCTAssertEqual(AgentRunner.arguments(agent: .codex, task: "t", mode: .acceptEdits, resume: "abc").prefix(3), ["exec", "resume", "abc"])
        XCTAssertTrue(AgentRunner.arguments(agent: .codex, task: "t", mode: .bypassPermissions, resume: nil).contains("--dangerously-bypass-approvals-and-sandbox"))
        let c = AgentRunner.arguments(agent: .claude, task: "t", mode: .acceptEdits, resume: "sid")
        XCTAssertTrue(c.contains("--resume")); XCTAssertTrue(c.contains("acceptEdits")); XCTAssertTrue(c.contains("stream-json"))
    }
}

@MainActor
final class StoreTests: XCTestCase {
    func testRegistryResolution() {
        let r = ProjectRegistry()
        r.projects = [Project(name: "website", path: "~/Projects/website", aliases: ["the site", "homepage"]),
                      Project(name: "api", path: "~/Projects/api")]
        XCTAssertEqual(r.resolve("Website")?.name, "website")
        XCTAssertEqual(r.resolve("the site")?.name, "website")
        XCTAssertEqual(r.resolve("API project")?.name, "api")
        XCTAssertNil(r.resolve(nil)); XCTAssertNil(r.resolve("unknown"))
    }
}
