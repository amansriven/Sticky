import AppKit
import StickyCore
import UserNotifications

/// Posts a notification when a new permission problem appears.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()
    nonisolated static let category = "STICKY_PROBLEM"
    nonisolated static let openSettings = "OPEN_SETTINGS"
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

    nonisolated static let settingsURL = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension")!

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
        content.userInfo = ["clientId": problem.clientId]
        if let url = problem.actions.first(where: { $0.kind == "open_url" })?.value {
            content.userInfo["url"] = url
            content.categoryIdentifier = Self.category
        }
        center.add(UNNotificationRequest(identifier: problem.key, content: content, trigger: nil))
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    /// Clicking the notification opens that app's page in Sticky; its
    /// "Open Settings" button opens the System Settings page instead.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        let info = response.notification.request.content.userInfo
        let url = (info["url"] as? String).flatMap(URL.init(string:))
        let clientId = info["clientId"] as? String
        let openSettings = response.actionIdentifier == Self.openSettings
        await MainActor.run {
            if openSettings, let url {
                _ = NSWorkspace.shared.open(url)
            } else if let clientId {
                ReportModel.shared.show(app: clientId)
            } else if let url {
                _ = NSWorkspace.shared.open(url)
            }
        }
    }
}
