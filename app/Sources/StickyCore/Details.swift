import Foundation

/// `sticky events <client_id> --compact`: one app's decisions, newest first.
public struct EventsResponse: Decodable, Sendable {
    public let clientId: String
    public let since: String?
    public let events: [TimelineEvent]
}

public struct TimelineEvent: Decodable, Sendable, Hashable, Identifiable {
    public let id: Int
    public let tsStart: String
    public let tsEnd: String?
    public let service: String?
    public let serviceName: String
    public let targetId: String?
    public let targetName: String?
    /// allowed | denied | prompted-allowed | prompted-denied | undetermined | …
    public let outcome: String
    public let prompted: Bool
    public let preflight: Bool
    public let authBefore: Int?
    public let authAfter: Int?
    public let finalAuth: Int?
    public let requirementsMatch: Bool
    /// 0 = the build matched the saved approval; -67050 = it didn't.
    public let storedDrStatus: Int?
    public let clientVersion: String?
    public let clientPath: String?
    public let clientDr: String?
    public let requestingId: String?
    public let accessingId: String?
    public let tccdScope: String?

    public var target: String? { targetId ?? targetName }

    /// "Automation → com.apple.Safari", or just "Accessibility".
    public var permissionLabel: String {
        target.map { "\(serviceName) → \($0)" } ?? serviceName
    }

    public var outcomeLabel: String {
        switch outcome {
        case "allowed": return "Allowed"
        case "denied": return "Denied"
        case "prompted-allowed": return "Asked → Allowed"
        case "prompted-denied": return "Asked → Denied"
        case "prompted": return "Asked (no answer)"
        case "undetermined": return "Not decided"
        case "limited": return "Limited"
        default: return outcome
        }
    }

    /// Why it went that way, when the log said so.
    public var note: String? {
        if storedDrStatus == -67050 { return "This build doesn't match the saved approval" }
        if prompted { return "macOS showed a permission prompt" }
        if requirementsMatch || storedDrStatus == 0 {
            // The signature matched what's saved; what's saved may be "off".
            return finalAuth == 0 ? "Switched off in System Settings" : "Matched the saved approval"
        }
        return nil
    }

    /// Developer Tools checks run on every app launch and are never a problem.
    public var isRoutine: Bool { service == "kTCCServiceDeveloperTool" || (preflight && finalAuth == 1) }
}

/// `sticky inspect <path> --json`: an app's signing identity.
public struct AppIdentity: Decodable, Sendable, Hashable {
    public let path: String
    public let codePath: String
    public let exists: Bool
    public let identifier: String?
    public let name: String?
    public let version: String?
    /// apple | app-store | developer-id | development | adhoc | unsigned | other | unknown
    public let signKind: String
    public let linkerSigned: Bool
    public let teamId: String?
    public let authority: String?
    public let cdhash: String?
    public let hardenedRuntime: Bool
    public let notarization: String?
    public let designatedRequirement: String?
    public let usageKeys: [String: String]
    public let error: String?
    /// team | apple | cdhash | path | other | unknown
    public let drKind: String
    /// Will permission grants survive updates?
    public let stable: Bool
    public let explanation: String?

    public var signatureLabel: String {
        switch signKind {
        case "apple": return "Apple"
        case "app-store": return "Mac App Store"
        case "developer-id": return "Developer ID" + (teamId.map { " (\($0))" } ?? "")
        case "development": return "Development certificate"
        case "adhoc": return linkerSigned ? "Ad-hoc (linker-signed)" : "Ad-hoc"
        case "unsigned": return "Not signed"
        default: return signKind.capitalized
        }
    }

    /// "AppleEvents", "Camera"… from NSAppleEventsUsageDescription etc.
    public var declaredUsage: [String] {
        usageKeys.keys
            .map { $0.replacingOccurrences(of: "NS", with: "", options: .anchored)
                .replacingOccurrences(of: "UsageDescription", with: "") }
            .sorted()
    }
}
