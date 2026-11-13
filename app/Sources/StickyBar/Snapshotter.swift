import AppKit
import StickyCore
import SwiftUI

/// `StickyBar --snapshot DIR --page PAGE [--dark]` renders one page offscreen,
/// with live data, into a PNG (see app/snapshot.sh for all pages). It's for
/// reviewing the design without screen recording permission. Notifications
/// are never posted in this mode.
@MainActor
enum Snapshotter {
    static var isActive = false

    /// `--size WIDTHxHEIGHT` (default 1100x760).
    static var windowSize: CGSize {
        let args = CommandLine.arguments
        guard let i = args.firstIndex(of: "--size"), i + 1 < args.count else { return CGSize(width: 1100, height: 760) }
        let parts = args[i + 1].split(separator: "x").compactMap { Double($0) }
        return parts.count == 2 ? CGSize(width: parts[0], height: parts[1]) : CGSize(width: 1100, height: 760)
    }

    /// Render one page: overview | problems | menu | settings | app:<client id>.
    /// One page per process: after the first capture, offscreen windows in the
    /// same process come out black (layer-drawn content isn't captured).
    static func run(page: String, to dir: String, dark: Bool) {
        isActive = true
        Task { @MainActor in
            try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
            NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            let size = CommandLine.arguments.contains("--size") ? "-\(Int(windowSize.width))" : ""
            let name = page.replacingOccurrences(of: "app:", with: "app-")
                .replacingOccurrences(of: "/", with: "_") + size + (dark ? "-dark" : "")
            let path = "\(dir)/\(name).png"
            let model = ReportModel.shared
            model.refresh()
            await waitUntil { !model.isRefreshing && (model.report != nil || model.errorMessage != nil) }
            switch page {
            case "menu":
                render(MenuView(model: model).fixedSize(horizontal: false, vertical: true),
                       size: CGSize(width: 380, height: 560), to: path)
            case "settings":
                render(SettingsView(settings: AppSettings.shared, model: model),
                       size: CGSize(width: 480, height: 640), to: path)
            default:
                if page == "problems" {
                    model.selection = .problems
                } else if page.hasPrefix("app:") {
                    let id = String(page.dropFirst(4))
                    model.selection = .app(id)
                    model.loadDetail(id, force: true)
                    await waitUntil { model.detail(id).loadedAt != nil }
                } else {
                    model.selection = .overview
                }
                render(MainWindow(model: model), size: windowSize, to: path)
            }
            print(path)
            exit(0)
        }
    }

    private static func waitUntil(timeout: TimeInterval = 20, _ done: @escaping () -> Bool) async {
        let start = Date()
        while !done() && Date().timeIntervalSince(start) < timeout {
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
    }

    /// Draw a view in an offscreen window (AppKit-backed views like List and
    /// ScrollView render properly this way, unlike with ImageRenderer).
    private static func render<V: View>(_ view: V, size: CGSize, to path: String) {
        let host = NSHostingView(rootView: view.frame(width: size.width, height: size.height)
            .background(Theme.pageFill))
        host.frame = CGRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = NSApp.appearance
        window.backgroundColor = .windowBackgroundColor
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        // Let any appearance transitions finish before capturing.
        RunLoop.current.run(until: Date().addingTimeInterval(2.0))
        host.layoutSubtreeIfNeeded()
        host.display()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
        host.cacheDisplay(in: host.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }
}

extension View {
    /// Copyable text, except in snapshots: selectable text is drawn through
    /// AppKit in a way offscreen capture doesn't see (it renders black).
    @ViewBuilder func selectableText() -> some View {
        if Snapshotter.isActive { self } else { textSelection(.enabled) }
    }
}
