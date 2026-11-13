import AppKit
import StickyCore
import SwiftUI

struct StickyBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @ObservedObject private var model = ReportModel.shared

    var body: some Scene {
        Window("Sticky", id: MainWindowID.value) {
            MainWindow(model: model)
        }
        .defaultSize(width: 1000, height: 680)

        Settings {
            SettingsView(settings: AppSettings.shared, model: model)
        }

        MenuBarExtra {
            MenuView(model: model)
        } label: {
            MenuBarLabel(model: model)
        }
        .menuBarExtraStyle(.window)
    }
}

enum MainWindowID {
    static let value = "main"
}

/// The menu bar icon. It's always on screen, so it also hands the model a way
/// to open the main window from places SwiftUI doesn't reach (notification
/// clicks, the Dock icon).
struct MenuBarLabel: View {
    @ObservedObject var model: ReportModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Image(systemName: model.menuBarSymbol)
            .accessibilityLabel("Sticky")
            .onAppear {
                model.openMainWindow = {
                    openWindow(id: MainWindowID.value)
                    NSApp.activate(ignoringOtherApps: true)
                }
            }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        MainActor.assumeIsolated {
            Notifier.shared.setUp()
            ReportModel.shared.start()
        }
    }

    /// Closing the window leaves Sticky in the menu bar.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// Clicking the Dock icon with no window open brings the window back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { MainActor.assumeIsolated { ReportModel.shared.openMainWindow?() } }
        return true
    }
}
