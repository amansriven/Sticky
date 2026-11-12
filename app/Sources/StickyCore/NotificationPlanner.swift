import Foundation

/// Decides which problems deserve a notification.
///
/// Each problem has a stable `key` (rule, app, permission, and when the
/// problem began), so a problem is announced once, not on every refresh. On
/// the very first launch nothing is announced: existing problems show up in
/// the menu instead of as a burst of notifications.
public struct NotificationPlanner: Sendable {
    public static let maxPerRefresh = 3

    public struct Plan: Equatable, Sendable {
        public let notify: [Problem]
        /// More new problems than `maxPerRefresh`; announce them as one summary.
        public let summarized: Int
        public let seen: Set<String>
    }

    public static func plan(problems: [Problem], seen: Set<String>, firstRun: Bool) -> Plan {
        let current = Set(problems.map(\.key))
        if firstRun {
            return Plan(notify: [], summarized: 0, seen: current)
        }
        let fresh = problems.filter { !seen.contains($0.key) }
        let notify = Array(fresh.prefix(maxPerRefresh))
        // Remember only problems that still exist, so the set can't grow forever,
        // and a problem that goes away and comes back later is announced again.
        return Plan(notify: notify, summarized: fresh.count - notify.count, seen: current)
    }

    /// Notification text for one problem.
    public static func content(for p: Problem) -> (title: String, body: String) {
        let title = "\(p.appName): \(p.title)"
        let body = ([p.label] + p.detail.prefix(1)).joined(separator: " — ")
        return (title, body)
    }
}
