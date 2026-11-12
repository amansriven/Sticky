import AppKit
import StickyCore
import SwiftUI

struct StickyBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @ObservedObject private var model = ReportModel.shared

    var body: some Scene {
        MenuBarExtra {
            MenuView(model: model)
        } label: {
            Image(systemName: model.menuBarSymbol)
                .accessibilityLabel("Sticky")
        }
        .menuBarExtraStyle(.window)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        MainActor.assumeIsolated {
            Notifier.shared.setUp()
            ReportModel.shared.start()
        }
    }
}
