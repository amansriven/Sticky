import AppKit
import StickyCore
import UserNotifications

/// Posts a notification when a new permission problem appears.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()
    static let category = "STICKY_PROBLEM"
    static let openSettings = "OPEN_SETTINGS"
    private let defaults = UserDefaults.standard

    /// Notifications need a real app bundle; `swift run` has none.
    private var center: UNUserNotificationCenter? {
        Bundle.main.bundleIdentifier == nil ? nil : .current()
    }

    func setUp() {
        guard let center else { return }
        center.delegate = self
        let open = UNNotificationAction(identifier: Self.openSettings, title: "Open Settings",
                                        options: [.foreground])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: Self.category, actions: [open], intentIdentifiers: []),
        ])
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    /// true = allowed, false = turned off in System Settings, nil = not asked yet
    /// (or no app bundle).
    func authorization() async -> Bool? {
        guard let center else { return nil }
        switch await center.notificationSettings().authorizationStatus {
        case .authorized, .provisional, .ephemeral: return true
        case .denied: return false
        default: return nil
        }
    }

    static let settingsURL = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension")!

    func announce(_ problems: [Problem]) {
        let firstRun = !defaults.bool(forKey: "hasAnnouncedBefore")
        let seen = Set(defaults.stringArray(forKey: "seenProblemKeys") ?? [])
        let plan = NotificationPlanner.plan(problems: problems, seen: seen, firstRun: firstRun)
        defaults.set(Array(plan.seen), forKey: "seenProblemKeys")
        defaults.set(true, forKey: "hasAnnouncedBefore")
        guard let center else { return }
        for problem in plan.notify {
            post(problem, to: center)
        }
        if plan.summarized > 0 {
            let content = UNMutableNotificationContent()
            content.title = "Sticky: \(plan.summarized) more permission problems"
            content.body = "Open Sticky in the menu bar to see them."
            center.add(UNNotificationRequest(identifier: "summary-\(Date().timeIntervalSince1970)",
                                             content: content, trigger: nil))
        }
    }

    private func post(_ problem: Problem, to center: UNUserNotificationCenter) {
        let text = NotificationPlanner.content(for: problem)
        let content = UNMutableNotificationContent()
        content.title = text.title
        content.body = text.body
        content.sound = .default
        if let url = problem.actions.first(where: { $0.kind == "open_url" })?.value {
            content.userInfo = ["url": url]
            content.categoryIdentifier = Self.category
        }
        center.add(UNNotificationRequest(identifier: problem.key, content: content, trigger: nil))
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    /// Clicking the notification, or its "Open Settings" button, opens the
    /// System Settings page for that permission.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        guard let text = response.notification.request.content.userInfo["url"] as? String,
              let url = URL(string: text) else { return }
        await MainActor.run { _ = NSWorkspace.shared.open(url) }
    }
}
