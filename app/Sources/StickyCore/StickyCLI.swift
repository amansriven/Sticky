import Foundation

public enum StickyCLIError: Error, LocalizedError, Equatable {
    case notFound
    /// The installed `sticky` predates a command this app needs.
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
        try await json(executable, ["report", "--compact", "--since", since], as: Report.self)
    }

    /// One app's decisions for the timeline (`sticky events`, 0.2.1+).
    public static func events(executable: String, clientId: String, since: String = "30d",
                              limit: Int = 500) async throws -> EventsResponse {
        try await json(executable, ["events", clientId, "--compact", "--since", since,
                                    "--limit", String(limit)], as: EventsResponse.self)
    }

    /// An app's signing identity (`sticky inspect --json`). Exit status 1
    /// only means "identity isn't stable", so the JSON is still read.
    public static func inspect(executable: String, target: String) async throws -> AppIdentity {
        try await json(executable, ["inspect", target, "--json"], as: AppIdentity.self, okStatuses: [0, 1])
    }

    /// Start (or restart) the background recorder. Returns sticky's message.
    public static func installAgent(executable: String) async throws -> String {
        let (status, out, err) = try await run(executable, ["install-agent"])
        let text = String(decoding: status == 0 ? out : err, as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard status == 0 else { throw StickyCLIError.failed(status: status, message: text) }
        return text.split(separator: "\n").dropFirst().first.map(String.init) ?? "The recorder is running."
    }

    /// Ignore a finding once (by key), or always for an app's permission or the whole app.
    public enum IgnoreScope: Sendable {
        case finding(key: String)
        case permission(clientId: String, service: String, target: String?)
        case app(clientId: String)

        var arguments: [String] {
            switch self {
            case let .finding(key): return ["ignore", key]
            case let .permission(client, service, target):
                return ["ignore", "--app", client, "--service", service] + (target.map { ["--target", $0] } ?? [])
            case let .app(client): return ["ignore", "--app", client]
            }
        }
    }

    public static func ignore(executable: String, _ scope: IgnoreScope) async throws {
        let (status, _, err) = try await run(executable, scope.arguments)
        guard status == 0 else {
            throw StickyCLIError.failed(status: status, message: String(decoding: err, as: UTF8.self))
        }
    }

    public static func unignore(executable: String, id: Int) async throws {
        let (status, _, err) = try await run(executable, ["unignore", String(id)])
        guard status == 0 else {
            throw StickyCLIError.failed(status: status, message: String(decoding: err, as: UTF8.self))
        }
    }

    static func json<T: Decodable>(_ executable: String, _ arguments: [String], as type: T.Type,
                                   okStatuses: Set<Int32> = [0]) async throws -> T {
        let (status, out, err) = try await run(executable, arguments)
        guard okStatuses.contains(status) else {
            let message = String(decoding: err, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            if message.contains("invalid choice: '\(arguments[0])'") { throw StickyCLIError.outdated }
            throw StickyCLIError.failed(status: status, message: message)
        }
        do {
            return try Report.decoder.decode(T.self, from: out)
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
