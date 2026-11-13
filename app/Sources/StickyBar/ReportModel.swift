import AppKit
import Foundation
import StickyCore

/// What the main window's sidebar shows.
enum SidebarItem: Hashable {
    case overview
    case problems
    case app(String)  // client id
}

/// Identity and timeline for one app, loaded when its page opens.
struct AppDetail {
    var identity: AppIdentity?
    var events: [TimelineEvent] = []
    var isLoading = false
    var error: String?
    var loadedAt: Date?
}

/// All app state. Views read it; nothing uses SwiftUI's @State, because in
/// the macOS 27 SDK that's a macro whose plugin ships only with Xcode.
@MainActor
final class ReportModel: ObservableObject {
    static let shared = ReportModel()

    // Report (menu bar and window)
    @Published private(set) var report: Report?
    @Published private(set) var errorMessage: String?
    @Published private(set) var stickyMissing = false
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var isRefreshing = false
    /// false when the user has turned Sticky's notifications off.
    @Published private(set) var notificationsAllowed: Bool?
    /// Keys of problems whose details are expanded in the menu.
    @Published private(set) var expanded: Set<String> = []

    // Main window
    @Published var selection: SidebarItem? = .overview
    @Published var search = ""
    @Published var showRoutineEvents = false
    /// Whether the sidebar's "System services" section is expanded.
    @Published var showSystem = false
    @Published private(set) var details: [String: AppDetail] = [:]
    @Published private(set) var agentMessage: String?
    @Published private(set) var isInstallingAgent = false

    private var timer: Timer?
    let settings = AppSettings.shared
    /// Set by the menu bar icon; opens (or focuses) the main window.
    var openMainWindow: (() -> Void)?

    /// Show one app's page in the main window.
    func show(app clientId: String) {
        selection = .app(clientId)
        openMainWindow?()
    }

    var problems: [Problem] { report?.problems ?? [] }
    var apps: [AppSummary] { report?.apps ?? [] }

    /// Apps matching the search, problems first, then most recently active.
    var filteredApps: [AppSummary] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        let order = ["problem": 0, "info": 1, "ok": 2, "none": 3]
        return apps
            .filter { q.isEmpty || $0.appName.lowercased().contains(q) || $0.clientId.lowercased().contains(q) }
            .sorted {
                let a = order[$0.status] ?? 3, b = order[$1.status] ?? 3
                return a != b ? a < b : $0.lastSeen > $1.lastSeen
            }
    }

    func app(_ clientId: String) -> AppSummary? { apps.first { $0.clientId == clientId } }

    var menuBarSymbol: String {
        guard let r = report else { return errorMessage == nil ? "shield" : "exclamationmark.shield" }
        if !r.problems.isEmpty { return "exclamationmark.shield.fill" }
        return r.recorder.isRecording ? "checkmark.shield" : "shield.slash"
    }

    func toggleExpanded(_ key: String) {
        if expanded.contains(key) { expanded.remove(key) } else { expanded.insert(key) }
    }

    // MARK: Refreshing

    func start() {
        refresh()
        scheduleTimer()
    }

    func scheduleTimer() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: settings.refreshInterval, repeats: true) { _ in
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
                let r = try await StickyCLI.report(executable: exe, since: settings.history)
                report = r
                errorMessage = nil
                if settings.notificationsEnabled && !Snapshotter.isActive { Notifier.shared.announce(r.problems) }
                // Keep an open app page current too.
                if case let .app(id)? = selection, details[id] != nil { loadDetail(id, force: true) }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    // MARK: App pages

    func detail(_ clientId: String) -> AppDetail { details[clientId] ?? AppDetail() }

    /// Load identity and timeline for an app page (cached for a minute).
    func loadDetail(_ clientId: String, force: Bool = false) {
        var d = detail(clientId)
        if d.isLoading { return }
        if !force, let at = d.loadedAt, Date().timeIntervalSince(at) < 60 { return }
        guard let exe = StickyCLI.locate() else { return }
        d.isLoading = true
        details[clientId] = d
        let path = app(clientId)?.appPath
        let since = settings.history
        Task {
            async let events = StickyCLI.events(executable: exe, clientId: clientId, since: since)
            async let identity: AppIdentity? = path == nil ? nil
                : try? await StickyCLI.inspect(executable: exe, target: path!)
            var updated = detail(clientId)
            do {
                updated.events = try await events.events
                updated.error = nil
            } catch {
                updated.error = error.localizedDescription
            }
            updated.identity = await identity
            updated.isLoading = false
            updated.loadedAt = Date()
            details[clientId] = updated
        }
    }

    // MARK: Actions

    /// Stop reporting a finding (once, for an app's permission, or for the app).
    func ignore(_ scope: StickyCLI.IgnoreScope) {
        guard let exe = StickyCLI.locate() else { return }
        Task {
            do {
                try await StickyCLI.ignore(executable: exe, scope)
            } catch {
                errorMessage = error.localizedDescription
            }
            refresh()
        }
    }

    /// Report a previously ignored finding again.
    func restore(_ ruleId: Int) {
        guard let exe = StickyCLI.locate() else { return }
        Task {
            try? await StickyCLI.unignore(executable: exe, id: ruleId)
            refresh()
        }
    }

    var ignoreRules: [IgnoreRule] { report?.ignored ?? [] }

    /// Start the background recorder (`sticky install-agent`).
    func installAgent() {
        guard let exe = StickyCLI.locate(), !isInstallingAgent else { return }
        isInstallingAgent = true
        agentMessage = nil
        Task {
            let result = try? await StickyCLI.installAgent(executable: exe)
            isInstallingAgent = false
            agentMessage = result ?? "Couldn't start the recorder. Run `sticky install-agent` in Terminal."
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            refresh()
        }
    }

    func reveal(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }
}
