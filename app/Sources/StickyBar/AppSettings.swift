import Foundation
import ServiceManagement

/// User preferences, stored in UserDefaults.
@MainActor
final class AppSettings: ObservableObject {
    static let shared = AppSettings()
    private let defaults = UserDefaults.standard

    static let historyChoices: [(label: String, value: String)] = [
        ("Last 24 hours", "24h"), ("Last 7 days", "7d"), ("Last 30 days", "30d"),
    ]
    static let refreshChoices: [(label: String, value: TimeInterval)] = [
        ("Every 30 seconds", 30), ("Every minute", 60), ("Every 5 minutes", 300),
    ]

    @Published var notificationsEnabled: Bool {
        didSet { defaults.set(notificationsEnabled, forKey: "notificationsEnabled") }
    }
    @Published var history: String {
        didSet { defaults.set(history, forKey: "history") }
    }
    @Published var refreshInterval: TimeInterval {
        didSet {
            defaults.set(refreshInterval, forKey: "refreshInterval")
            ReportModel.shared.scheduleTimer()
        }
    }
    @Published var showInDock: Bool {
        didSet {
            defaults.set(showInDock, forKey: "showInDock")
            DockPolicy.apply(windowOpen: true)
        }
    }
    /// Mirrors SMAppService; set through `setLaunchAtLogin`.
    @Published private(set) var launchAtLogin = false
    @Published private(set) var launchAtLoginNote: String?

    private init() {
        defaults.register(defaults: [
            "notificationsEnabled": true, "history": "30d", "refreshInterval": 60.0, "showInDock": true,
        ])
        notificationsEnabled = defaults.bool(forKey: "notificationsEnabled")
        history = defaults.string(forKey: "history") ?? "30d"
        refreshInterval = defaults.double(forKey: "refreshInterval")
        showInDock = defaults.bool(forKey: "showInDock")
        syncLaunchAtLogin()
    }

    func syncLaunchAtLogin() {
        let status = SMAppService.mainApp.status
        launchAtLogin = status == .enabled
        launchAtLoginNote = status == .requiresApproval
            ? "Approve Sticky in System Settings → General → Login Items." : nil
    }

    func setLaunchAtLogin(_ on: Bool) {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            launchAtLoginNote = nil
        } catch {
            launchAtLoginNote = "Couldn't change it: \(error.localizedDescription)"
        }
        syncLaunchAtLogin()
    }
}
