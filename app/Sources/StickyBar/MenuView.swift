import AppKit
import StickyCore
import SwiftUI

struct MenuView: View {
    @ObservedObject var model: ReportModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if model.notificationsAllowed == false {
                notificationsOff
            }
            Divider()
            content
            if let apps = model.report?.apps, !apps.isEmpty {
                Divider()
                recentApps(apps)
            }
            Divider()
            footer
        }
        .padding(14)
        .frame(width: 380)
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: model.menuBarSymbol)
                .font(.title2)
                .foregroundStyle(headerColor)
            VStack(alignment: .leading, spacing: 2) {
                Text("Sticky").font(.headline)
                Text(statusLine).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var headerColor: Color {
        guard let r = model.report else { return .secondary }
        if !r.problems.isEmpty { return .orange }
        return r.recorder.isRecording ? .green : .red
    }

    private var statusLine: String {
        guard let r = model.report else {
            return model.errorMessage ?? "Loading…"
        }
        let h = r.recorder
        switch h.state {
        case "running":
            return "Recording · last log line \(StickyTime.ago(h.lastRecord))"
        case "stale":
            return "The recorder isn't responding · last heartbeat \(StickyTime.ago(h.heartbeat))"
        case "stopped" where !h.agentLoaded:
            return "Not recording. Run `sticky install-agent` in Terminal."
        case "stopped":
            return "Not recording: \(h.stoppedReason ?? "stopped")"
        default:
            return "Not recording yet. Run `sticky install-agent` in Terminal."
        }
    }

    private var notificationsOff: some View {
        HStack(spacing: 8) {
            Image(systemName: "bell.slash").foregroundStyle(.orange)
            Text("Notifications are off, so you won't hear about new problems.")
                .font(.caption).fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button("Turn on") { NSWorkspace.shared.open(Notifier.settingsURL) }
                .controlSize(.small)
        }
    }

    // MARK: Problems

    @ViewBuilder
    private var content: some View {
        if model.report == nil, let error = model.errorMessage {
            VStack(alignment: .leading, spacing: 8) {
                Text(error).font(.callout).fixedSize(horizontal: false, vertical: true)
                if model.stickyMissing {
                    Button("Copy install command") {
                        copy("brew install amansriven/tap/sticky && sticky install-agent")
                    }
                }
            }
        } else if let r = model.report {
            if r.problems.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Label("No permission problems found", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("\(r.apps.count) apps and \(r.recorder.decisionsTotal) decisions recorded.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text(r.problems.count == 1 ? "1 permission problem" : "\(r.problems.count) permission problems")
                    .font(.subheadline.weight(.semibold))
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(r.problems) { problem in
                            ProblemRow(problem: problem,
                                       expanded: model.expanded.contains(problem.key),
                                       toggle: { model.toggleExpanded(problem.key) })
                        }
                    }
                }
                .frame(maxHeight: 360)
            }
        } else {
            ProgressView().controlSize(.small)
        }
    }

    // MARK: Recent apps

    private func recentApps(_ apps: [AppSummary]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Recently active").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            ForEach(apps.prefix(5)) { app in
                HStack(spacing: 8) {
                    Circle().fill(color(for: app.status)).frame(width: 7, height: 7)
                    Text(app.appName).font(.callout).lineLimit(1)
                    Spacer()
                    Text(StickyTime.ago(app.lastSeen)).font(.caption).foregroundStyle(.secondary)
                }
                .help(app.permissions.map(\.label).joined(separator: ", "))
            }
        }
    }

    private func color(for status: String) -> Color {
        switch status {
        case "problem": return .orange
        case "info": return .blue
        case "ok": return .green
        default: return .secondary
        }
    }

    // MARK: Footer

    private var footer: some View {
        HStack {
            Button("Refresh") { model.refresh() }
                .disabled(model.isRefreshing)
            if model.isRefreshing { ProgressView().controlSize(.small) }
            Spacer()
            if let last = model.lastRefresh {
                Text("Updated \(last, style: .relative) ago").font(.caption).foregroundStyle(.secondary)
            }
            Button("Quit") { NSApp.terminate(nil) }
        }
    }
}

struct ProblemRow: View {
    let problem: Problem
    // Kept in ReportModel, not @State: in the macOS 27 SDK @State is a macro
    // whose plugin ships only with Xcode, and this builds with the
    // command-line tools alone.
    let expanded: Bool
    let toggle: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { toggle() }
            } label: {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(problem.title).font(.callout.weight(.semibold))
                        Text("\(problem.appName) · \(problem.label)")
                            .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                    Spacer()
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(problem.detail, id: \.self) { line in
                        Text(line).font(.caption).fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(problem.fix, id: \.self) { line in
                        Text("Fix: \(line)").font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if !problem.actions.isEmpty {
                        HStack {
                            ForEach(problem.actions, id: \.self) { action in
                                Button(action.label) { perform(action) }.controlSize(.small)
                            }
                        }
                        .padding(.top, 2)
                    }
                }
                .padding(.leading, 24)
                .textSelection(.enabled)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.secondary.opacity(0.08)))
    }

    private func perform(_ action: FixAction) {
        switch action.kind {
        case "open_url":
            if let url = URL(string: action.value) { NSWorkspace.shared.open(url) }
        case "copy":
            copy(action.value)
        default:
            break
        }
    }
}

func copy(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}
