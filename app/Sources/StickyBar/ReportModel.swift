import Foundation
import StickyCore

/// Holds the latest report and refreshes it every minute.
@MainActor
final class ReportModel: ObservableObject {
    static let shared = ReportModel()
    static let refreshInterval: TimeInterval = 60

    @Published private(set) var report: Report?
    @Published private(set) var errorMessage: String?
    @Published private(set) var stickyMissing = false
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var isRefreshing = false
    /// false when the user has turned Sticky's notifications off.
    @Published private(set) var notificationsAllowed: Bool?
    /// Keys of problems whose details are expanded in the menu.
    @Published private(set) var expanded: Set<String> = []
    private var timer: Timer?

    var problems: [Problem] { report?.problems ?? [] }

    var menuBarSymbol: String {
        guard let r = report else { return errorMessage == nil ? "shield" : "exclamationmark.shield" }
        if !r.problems.isEmpty { return "exclamationmark.shield.fill" }
        return r.recorder.isRecording ? "checkmark.shield" : "shield.slash"
    }

    func toggleExpanded(_ key: String) {
        if expanded.contains(key) { expanded.remove(key) } else { expanded.insert(key) }
    }

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: Self.refreshInterval, repeats: true) { _ in
            Task { @MainActor in ReportModel.shared.refresh() }
        }
    }

    func refresh() {
        guard !isRefreshing else { return }
        isRefreshing = true
        Task {
            defer {
                isRefreshing = false
                lastRefresh = Date()
            }
            guard let exe = StickyCLI.locate() else {
                stickyMissing = true
                errorMessage = StickyCLIError.notFound.localizedDescription
                report = nil
                return
            }
            stickyMissing = false
            notificationsAllowed = await Notifier.shared.authorization()
            do {
                let r = try await StickyCLI.report(executable: exe)
                report = r
                errorMessage = nil
                Notifier.shared.announce(r.problems)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
