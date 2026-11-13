import AppKit
import Foundation
import StickyCore

// `StickyBar --dump` fetches the report the way the app does and prints a
// summary, without any UI. Useful for checking the setup from Terminal.
if CommandLine.arguments.contains("--dump") {
    let done = DispatchSemaphore(value: 0)
    let status = DumpStatus()
    Task {
        defer { done.signal() }
        guard let exe = StickyCLI.locate() else {
            print(StickyCLIError.notFound.localizedDescription)
            status.code = 2
            return
        }
        do {
            let r = try await StickyCLI.report(executable: exe)
            print("sticky \(r.stickyVersion) at \(exe)")
            print("recorder: \(r.recorder.state), last log line \(StickyTime.ago(r.recorder.lastRecord))")
            print("problems: \(r.problems.count)")
            for p in r.problems { print("  - \(p.appName): \(p.title) [\(p.label)]") }
            print("apps: \(r.apps.count)")
        } catch {
            print("error: \(error.localizedDescription)")
            status.code = 1
        }
    }
    done.wait()
    exit(status.code)
} else if let i = CommandLine.arguments.firstIndex(of: "--snapshot"), i + 1 < CommandLine.arguments.count {
    // Render every page to PNGs (see Snapshotter); no windows, no notifications.
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    let args = CommandLine.arguments
    let dir = args[i + 1]
    let dark = args.contains("--dark")
    let page = args.firstIndex(of: "--page").flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil } ?? "overview"
    MainActor.assumeIsolated { Snapshotter.run(page: page, to: dir, dark: dark) }
    app.run()
} else {
    StickyBarApp.main()
}

final class DumpStatus: @unchecked Sendable {
    var code: Int32 = 0
}
