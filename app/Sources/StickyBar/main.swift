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
} else {
    StickyBarApp.main()
}

final class DumpStatus: @unchecked Sendable {
    var code: Int32 = 0
}
