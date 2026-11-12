import Foundation
import Testing
@testable import StickyCore

/// A report produced by `sticky report` from the anonymized ndjson fixture
/// (Finder allowed, Safari remembered denial), so the Swift models are checked
/// against what the Python side really prints.
func fixtureReport() throws -> Report {
    let url = try #require(Bundle.module.url(forResource: "report", withExtension: "json",
                                             subdirectory: "Fixtures"))
    return try Report.decode(Data(contentsOf: url))
}

@Suite struct ReportDecodingTests {
    @Test func decodesRealReport() throws {
        let r = try fixtureReport()
        #expect(r.recorder.state == "stopped")
        #expect(r.recorder.agentInstalled)
        #expect(r.recorder.records == 330)
        #expect(r.problems.count == 1)
    }

    @Test func problemCarriesEverythingTheMenuShows() throws {
        let p = try #require(try fixtureReport().problems.first)
        #expect(p.rule == "R2")
        #expect(p.clientId == "com.anthropic.claude-code")
        #expect(p.label == "Automation → com.apple.Safari")
        #expect(p.serviceName == "Automation")
        #expect(p.actions.map(\.kind) == ["open_url", "copy"])
        #expect(p.actions[1].value == "tccutil reset AppleEvents com.anthropic.claude-code")
        #expect(p.key.hasPrefix("R2|com.anthropic.claude-code|"))
    }

    @Test func appsHavePermissionStatuses() throws {
        let app = try #require(try fixtureReport().apps.first { $0.clientId == "com.anthropic.claude-code" })
        #expect(app.status == "problem")
        let automation = app.permissions.filter { $0.service == "kTCCServiceAppleEvents" }
        #expect(Set(automation.map(\.status)) == ["problem", "ok"])
    }
}

@Suite struct NotificationPlannerTests {
    func problem(_ key: String) throws -> Problem {
        let base = try #require(try fixtureReport().problems.first)
        let json = """
        {"rule":"\(base.rule)","severity":"problem","client_id":"x","service":"s","target":null,
         "title":"T","detail":["d"],"fix":[],"when":null,"began":null,"actions":[],"key":"\(key)",
         "app_name":"App","app_path":null,"service_name":"S","label":"L"}
        """
        return try Report.decoder.decode(Problem.self, from: Data(json.utf8))
    }

    @Test func firstRunAnnouncesNothing() throws {
        let plan = NotificationPlanner.plan(problems: [try problem("a")], seen: [], firstRun: true)
        #expect(plan.notify.isEmpty)
        #expect(plan.seen == ["a"])
    }

    @Test func newProblemsAreAnnouncedOnce() throws {
        let a = try problem("a"), b = try problem("b")
        let first = NotificationPlanner.plan(problems: [a, b], seen: ["a"], firstRun: false)
        #expect(first.notify.map(\.key) == ["b"])
        let again = NotificationPlanner.plan(problems: [a, b], seen: first.seen, firstRun: false)
        #expect(again.notify.isEmpty)
    }

    @Test func burstIsCappedAndSummarized() throws {
        let many = try (0..<5).map { try problem("p\($0)") }
        let plan = NotificationPlanner.plan(problems: many, seen: [], firstRun: false)
        #expect(plan.notify.count == NotificationPlanner.maxPerRefresh)
        #expect(plan.summarized == 2)
    }

    @Test func resolvedProblemsAreForgotten() throws {
        let plan = NotificationPlanner.plan(problems: [try problem("b")], seen: ["a", "b"], firstRun: false)
        #expect(plan.seen == ["b"])
    }

    @Test func notificationText() throws {
        let p = try #require(try fixtureReport().problems.first)
        let (title, body) = NotificationPlanner.content(for: p)
        #expect(title.hasSuffix(": Denied: requests are refused silently"))
        #expect(body.hasPrefix("Automation → com.apple.Safari — "))
    }
}

@Suite struct StickyCLITests {
    @Test func locatePrefersOverrideThenHomebrew() {
        let all: (String) -> Bool = { _ in true }
        #expect(StickyCLI.locate(environment: ["STICKY_BIN": "/x/sticky"], isExecutable: all) == "/x/sticky")
        #expect(StickyCLI.locate(environment: [:], isExecutable: all) == "/opt/homebrew/bin/sticky")
        #expect(StickyCLI.locate(environment: [:], isExecutable: { $0 == "/usr/local/bin/sticky" })
                == "/usr/local/bin/sticky")
        #expect(StickyCLI.locate(environment: [:], isExecutable: { _ in false }) == nil)
    }

    @Test func reportsFailuresWithStatus() async throws {
        await #expect(throws: StickyCLIError.self) {
            _ = try await StickyCLI.report(executable: "/usr/bin/false")
        }
    }

    @Test func olderStickyWithoutReportCommand() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let fake = dir.appendingPathComponent("sticky")
        // What sticky 0.1.1 prints for `sticky report`.
        try """
        #!/bin/sh
        echo "sticky: error: argument command: invalid choice: 'report', maybe you meant 'record'?" >&2
        exit 2
        """.write(to: fake, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: fake.path)
        await #expect(throws: StickyCLIError.outdated) {
            _ = try await StickyCLI.report(executable: fake.path)
        }
    }

    @Test func missingExecutable() async throws {
        await #expect(throws: StickyCLIError.notFound) {
            _ = try await StickyCLI.report(executable: "/nonexistent/sticky")
        }
    }

    @Test func timeFormatting() throws {
        let now = try #require(StickyTime.parse("2026-11-11 10:00:00.000"))
        #expect(StickyTime.ago("2026-11-11 09:59:30.500", now: now) == "30s ago")
        #expect(StickyTime.ago("2026-11-11 09:00:00.000", now: now) == "60m ago")
        #expect(StickyTime.ago("2026-11-09 10:00:00.000", now: now) == "2d ago")
        #expect(StickyTime.ago(nil, now: now) == "never")
    }
}
