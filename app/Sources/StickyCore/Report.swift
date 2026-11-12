import Foundation

/// The JSON printed by `sticky report --compact` (see src/sticky/report.py).
/// Keys are snake_case in JSON; decode with `Report.decoder`.
public struct Report: Decodable, Sendable {
    public let stickyVersion: String
    public let generatedAt: String
    public let since: String?
    public let recorder: RecorderHealth
    public let problems: [Problem]
    public let apps: [AppSummary]

    public static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    public static func decode(_ data: Data) throws -> Report {
        try decoder.decode(Report.self, from: data)
    }
}

public struct RecorderHealth: Decodable, Sendable {
    /// running | stale | stopped | never
    public let state: String
    public let agentInstalled: Bool
    public let agentLoaded: Bool
    public let decisionsTotal: Int
    public let stoppedReason: String?
    public let pid: Int?
    public let runId: Int?
    public let startedAt: String?
    public let heartbeat: String?
    public let lastRecord: String?
    public let records: Int?
    public let requests: Int?
    public let decisions: Int?
    public let restarts: Int?

    public var isRecording: Bool { state == "running" }
}

/// A button the UI can show for a finding.
public struct FixAction: Decodable, Sendable, Hashable {
    /// open_url | copy
    public let kind: String
    public let label: String
    public let value: String
}

public struct Finding: Decodable, Sendable, Hashable {
    public let rule: String
    /// problem | info | ok
    public let severity: String
    public let clientId: String
    public let service: String
    public let target: String?
    public let title: String
    public let detail: [String]
    public let fix: [String]
    public let when: String?
    public let began: String?
    public let actions: [FixAction]
    public let key: String
}

/// A problem finding with the app and permission it belongs to.
public struct Problem: Decodable, Sendable, Hashable, Identifiable {
    public let rule: String
    public let severity: String
    public let clientId: String
    public let service: String
    public let target: String?
    public let title: String
    public let detail: [String]
    public let fix: [String]
    public let when: String?
    public let began: String?
    public let actions: [FixAction]
    public let key: String
    public let appName: String
    public let appPath: String?
    public let serviceName: String
    public let label: String

    public var id: String { key }
}

public struct Permission: Decodable, Sendable, Hashable {
    public let service: String
    public let serviceName: String
    public let target: String?
    public let label: String
    public let requests: Int
    public let lastSeen: String
    public let lastOutcome: String?
    /// problem | info | ok | none
    public let status: String
    public let findings: [Finding]
}

public struct AppSummary: Decodable, Sendable, Hashable, Identifiable {
    public let clientId: String
    public let appName: String
    public let appPath: String?
    public let lastSeen: String
    public let status: String
    public let permissions: [Permission]

    public var id: String { clientId }
}

/// Timestamps in reports are local wall-clock strings: "YYYY-MM-DD HH:MM:SS.mmm".
public enum StickyTime {
    public static func parse(_ text: String?) -> Date? {
        guard let text, text.count >= 19 else { return nil }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.date(from: String(text.prefix(19)))
    }

    /// "12s ago", "5m ago", "3h ago", "2d ago" (or "never").
    public static func ago(_ text: String?, now: Date = Date()) -> String {
        guard let date = parse(text) else { return "never" }
        let secs = max(0, Int(now.timeIntervalSince(date)))
        switch secs {
        case ..<120: return "\(secs)s ago"
        case ..<7200: return "\(secs / 60)m ago"
        case ..<172_800: return "\(secs / 3600)h ago"
        default: return "\(secs / 86400)d ago"
        }
    }
}
