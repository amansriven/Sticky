import Foundation

/// The JSON printed by `sticky report --compact` (see src/sticky/report.py).
/// Keys are snake_case in JSON; decode with `Report.decoder`.
public struct Report: Decodable, Sendable {
    public let stickyVersion: String
    public let generatedAt: String
    public let since: String?
    public let recorder: RecorderHealth
    public let problems: [Problem]
    /// Decisions per hour for your apps (not system services), last 24 hours.
    public let activity: Activity?
    /// Ignore rules the user set, with how many findings each hides now.
    public let ignored: [IgnoreRule]?
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

public struct Activity: Decodable, Sendable, Hashable {
    public let hours: [HourBucket]
    public let totals: ActivityTotals
}

public struct HourBucket: Decodable, Sendable, Hashable, Identifiable {
    /// "YYYY-MM-DD HH:00"
    public let hour: String
    public let allowed: Int
    public let denied: Int
    public let asked: Int
    public var id: String { hour }
    public var total: Int { allowed + denied + asked }
}

public struct ActivityTotals: Decodable, Sendable, Hashable {
    public let allowed: Int
    public let denied: Int
    public let asked: Int
    public let apps: Int
}

public struct IgnoreRule: Decodable, Sendable, Hashable, Identifiable {
    public let id: Int
    /// finding | permission | app
    public let scope: String
    public let clientId: String
    public let service: String?
    public let target: String?
    public let findingKey: String?
    public let createdAt: String
    public let appName: String
    public let serviceName: String?
    public let hiding: Int

    /// "Pluely · Microphone", "Claude Code · Automation → Safari", "Everything about Zoom"
    public var description: String {
        switch scope {
        case "app": return "All alerts for \(appName)"
        case "permission":
            return "\(appName) · \(serviceName ?? "permission")" + (target.map { " → \($0)" } ?? "")
        default:
            return "\(appName) · \(serviceName ?? "one problem") (this time)"
        }
    }
}

/// What a UI can draw instead of prose: two builds, or two paths.
public struct Evidence: Decodable, Sendable, Hashable {
    /// builds | paths
    public let kind: String
    public let approved: String?
    public let current: String?
    public let before: String?
    public let after: String?
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
    public let evidence: Evidence?
    /// The ignore rule hiding this finding, if any.
    public let ignoredBy: Int?
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
    public let evidence: Evidence?
    public let appName: String
    public let appPath: String?
    /// app | system
    public let appKind: String?
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
    /// app | system (Apple's own processes and daemons)
    public let kind: String
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
