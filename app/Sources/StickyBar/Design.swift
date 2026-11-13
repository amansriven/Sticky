import AppKit
import StickyCore
import SwiftUI

// The app's small design system: cards, pills, tiles, and how requirements
// and fix steps are shown. Pages are built only from these.

enum Theme {
    static let corner: CGFloat = 12
    static let pagePadding: CGFloat = 28
    static let gap: CGFloat = 16

    static let problem = Color.orange
    static let ok = Color.green
    static let info = Color.blue
    static let denied = Color.red
    static let asked = Color.orange

    static var cardFill: Color { Color(nsColor: .controlBackgroundColor) }
    static var cardStroke: Color { Color.primary.opacity(0.07) }
    static var pageFill: Color { Color(nsColor: .windowBackgroundColor) }
}

/// A rounded panel with an optional title row inside it.
struct Card<Content: View, Accessory: View>: View {
    let title: String?
    let systemImage: String?
    let accessory: Accessory
    let content: Content

    init(_ title: String? = nil, systemImage: String? = nil,
         @ViewBuilder accessory: () -> Accessory, @ViewBuilder content: () -> Content) {
        self.title = title
        self.systemImage = systemImage
        self.accessory = accessory()
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let title {
                HStack(spacing: 8) {
                    if let systemImage {
                        Image(systemName: systemImage).foregroundStyle(.secondary)
                    }
                    Text(title).font(.headline)
                    Spacer()
                    accessory
                }
            }
            content
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).fill(Theme.cardFill))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).strokeBorder(Theme.cardStroke))
    }
}

extension Card where Accessory == EmptyView {
    init(_ title: String? = nil, systemImage: String? = nil, @ViewBuilder content: () -> Content) {
        self.init(title, systemImage: systemImage, accessory: { EmptyView() }, content: content)
    }
}

/// A small coloured capsule label.
struct Pill: View {
    let text: String
    var systemImage: String?
    var tint: Color = .secondary

    var body: some View {
        HStack(spacing: 4) {
            if let systemImage { Image(systemName: systemImage).imageScale(.small) }
            Text(text)
        }
        .font(.caption.weight(.semibold))
        .foregroundStyle(tint)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Capsule().fill(tint.opacity(0.14)))
    }
}

/// A big number with a label.
struct StatTile: View {
    let value: String
    let label: String
    let systemImage: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: systemImage)
                .font(.title3)
                .foregroundStyle(tint)
                .frame(width: 30, height: 30)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(tint.opacity(0.14)))
            Text(value).font(.system(size: 26, weight: .semibold, design: .rounded)).monospacedDigit()
            Text(label).font(.callout).foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).fill(Theme.cardFill))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).strokeBorder(Theme.cardStroke))
    }
}

/// A code-signing requirement, shortened: "Build 970b1915" or "Team Q6L2SF6YDW".
struct RequirementChip: View {
    let requirement: String?
    var tint: Color = .primary

    var body: some View {
        Text(Requirement.short(requirement))
            .font(.callout.monospaced().weight(.medium))
            .foregroundStyle(tint)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(tint.opacity(0.10)))
            .help(requirement ?? "Unknown")
    }
}

enum Requirement {
    static func short(_ requirement: String?) -> String {
        guard let r = requirement, !r.isEmpty else { return "Unknown build" }
        if let range = r.range(of: #"cdhash H"([0-9a-f]{8})"#, options: .regularExpression) {
            let hex = r[range].dropFirst(#"cdhash H""#.count).prefix(8)
            return "Build \(hex)"
        }
        if let range = r.range(of: #"subject\.OU\] = "?([A-Z0-9]{10})"#, options: .regularExpression) {
            let team = r[range].filter { $0.isUppercase || $0.isNumber }.suffix(10)
            return "Team \(team)"
        }
        if r.contains("anchor apple") && !r.contains("generic") { return "Apple" }
        return String(r.prefix(24)) + (r.count > 24 ? "…" : "")
    }
}

/// "Approved build ≠ This build" for findings about a changed identity.
struct EvidenceView: View {
    let evidence: Evidence
    let isProblem: Bool

    var body: some View {
        HStack(spacing: 12) {
            column(evidence.kind == "paths" ? "Before" : "Approved build",
                   evidence.kind == "paths" ? evidence.before : evidence.approved, tint: .secondary)
            Image(systemName: isProblem ? "xmark.circle.fill" : "arrow.right.circle.fill")
                .font(.title2)
                .foregroundStyle(isProblem ? Theme.denied : Theme.info)
                .padding(.top, 14)
            column(evidence.kind == "paths" ? "Now" : "This build",
                   evidence.kind == "paths" ? evidence.after : evidence.current,
                   tint: isProblem ? Theme.problem : .primary)
            Spacer(minLength: 0)
        }
    }

    private func column(_ label: String, _ value: String?, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            if evidence.kind == "paths" {
                Text(value ?? "–").font(.callout.monospaced()).lineLimit(2).truncationMode(.middle)
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.06)))
                    .help(value ?? "")
            } else {
                RequirementChip(requirement: value, tint: tint)
            }
        }
    }
}

/// Numbered fix steps, without the raw settings URLs (buttons cover those).
struct FixSteps: View {
    let steps: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text("\(index + 1)")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(width: 18, height: 18)
                        .background(Circle().fill(Color.accentColor))
                    Text(FixSteps.clean(step)).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    static func clean(_ step: String) -> String {
        var s = step
        for pattern in [#" \(open "[^"]*"\)"#, #": open "[^"]*""#, #" open "[^"]*""#] {
            s = s.replacingOccurrences(of: pattern, with: "", options: .regularExpression)
        }
        return s.replacingOccurrences(of: "  ", with: " ")
    }
}

/// Action buttons; the first "open" action is the prominent one.
struct ActionButtons: View {
    let actions: [FixAction]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(Array(actions.enumerated()), id: \.offset) { index, a in
                if index == 0 {
                    Button { perform(a) } label: { Label(a.label, systemImage: icon(a)) }
                        .buttonStyle(.borderedProminent)
                } else {
                    Button { perform(a) } label: { Label(a.label, systemImage: icon(a)) }
                }
            }
        }
        .controlSize(.regular)
    }

    private func icon(_ a: FixAction) -> String {
        a.kind == "copy" ? "doc.on.doc" : "gearshape"
    }
}

/// Outcome of one decision as an icon.
struct OutcomeIcon: View {
    let outcome: String?
    var body: some View {
        Image(systemName: symbol).foregroundStyle(outcomeColor(outcome))
    }
    private var symbol: String {
        switch outcome {
        case "allowed": return "checkmark.circle.fill"
        case "denied": return "xmark.circle.fill"
        case "prompted-allowed": return "checkmark.bubble.fill"
        case "prompted-denied": return "xmark.bubble.fill"
        case "prompted": return "questionmark.bubble.fill"
        default: return "circle.dashed"
        }
    }
}

extension AppSummary {
    var isSystem: Bool { kind == "system" }
    /// "Automation, Accessibility"
    var permissionSummary: String {
        permissions.map(\.serviceName).uniqued().prefix(3).joined(separator: ", ")
    }
}

/// The ID of Sticky itself, which the window hides from its own lists.
let stickyOwnBundleIDs: Set<String> = ["dev.sticky.bar"]
