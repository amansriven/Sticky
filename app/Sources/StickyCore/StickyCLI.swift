import Foundation

public enum StickyCLIError: Error, LocalizedError, Equatable {
    case notFound
    /// The installed `sticky` predates `sticky report` (added after 0.1.1).
    case outdated
    case failed(status: Int32, message: String)
    case badOutput(String)

    public var errorDescription: String? {
        switch self {
        case .notFound:
            return "The sticky command isn't installed. Install it with: brew install amansriven/tap/sticky"
        case .outdated:
            return "Your sticky command is too old for this app. Update it with: brew upgrade sticky"
        case let .failed(status, message):
            return "sticky report failed (exit \(status)): \(message)"
        case let .badOutput(reason):
            return "Couldn't read sticky's report: \(reason)"
        }
    }
}

/// Runs the `sticky` command-line tool, which holds all the diagnosis logic.
public enum StickyCLI {
    /// Where Homebrew installs `sticky`, in order. `STICKY_BIN` overrides.
    public static let candidates = ["/opt/homebrew/bin/sticky", "/usr/local/bin/sticky"]

    public static func locate(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }
    ) -> String? {
        if let override = environment["STICKY_BIN"], isExecutable(override) { return override }
        return candidates.first(where: isExecutable)
    }

    /// Run `sticky report --compact` and decode it. Runs off the main thread.
    public static func report(executable: String, since: String = "30d") async throws -> Report {
        let (status, out, err) = try await run(executable, ["report", "--compact", "--since", since])
        guard status == 0 else {
            let message = String(decoding: err, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            if message.contains("invalid choice: 'report'") { throw StickyCLIError.outdated }
            throw StickyCLIError.failed(status: status, message: message)
        }
        do {
            return try Report.decode(out)
        } catch {
            throw StickyCLIError.badOutput(String(describing: error))
        }
    }

    /// Run a process and collect its output. Reads stdout to EOF before
    /// waiting, so large reports can't fill the pipe and deadlock.
    static func run(_ executable: String, _ arguments: [String]) async throws -> (Int32, Data, Data) {
        try await Task.detached(priority: .utility) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = arguments
            let out = Pipe(), err = Pipe()
            process.standardOutput = out
            process.standardError = err
            process.standardInput = FileHandle.nullDevice
            do {
                try process.run()
            } catch {
                throw StickyCLIError.notFound
            }
            let outData = out.fileHandleForReading.readDataToEndOfFile()
            let errData = err.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (process.terminationStatus, outData, errData)
        }.value
    }
}
