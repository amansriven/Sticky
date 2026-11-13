import AppKit
import StickyCore
import SwiftUI

/// The menu bar dropdown: a glance at what's wrong, and a way into the window.
struct MenuView: View {
    @ObservedObject var model: ReportModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if model.notificationsAllowed == false && model.settings.notificationsEnabled {
                notificationsOff
            }
            content
            if let apps = model.report?.apps {
                let yours = apps.filter { !$0.isSystem && !stickyOwnBundleIDs.contains($0.clientId) }
                if !yours.isEmpty {
                    Divider()
                    recentApps(Array(yours.prefix(4)))
                }
            }
            Divider()
            footer
        }
        .padding(16)
        .frame(width: 360)
    }

    private func openWindow(selecting item: SidebarItem? = nil) {
        if let item { model.selection = item }
        openWindow(id: MainWindowID.value)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 10) {
            Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 34, height: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text("Sticky").font(.headline)
                HStack(spacing: 5) {
                    Circle().fill(statusColor).frame(width: 7, height: 7)
                    Text(statusLine).font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer()
        }
    }

    private var statusColor: Color {
        guard let h = model.report?.recorder else { return .secondary }
        switch h.state {
        case "running": return Theme.ok
        case "stale": return Theme.problem
        default: return Theme.denied
        }
    }

    private var statusLine: String {
        guard let r = model.report else { return model.errorMessage == nil ? "Loading…" : "Can't reach the engine" }
        let h = r.recorder
        switch h.state {
        case "running": return "Recording · last activity \(StickyTime.ago(h.lastRecord))"
        case "stale": return "Recorder not responding"
        default: return "Not recording"
        }
    }

    private var notificationsOff: some View {
        HStack(spacing: 8) {
            Image(systemName: "bell.slash.fill").foregroundStyle(Theme.problem)
            Text("Notifications are off").font(.caption)
            Spacer()
            Button("Turn on") { NSWorkspace.shared.open(Notifier.settingsURL) }.controlSize(.small)
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.problem.opacity(0.10)))
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
            if !r.recorder.isRecording {
                HStack {
                    Label("Sticky isn't recording", systemImage: "pause.circle.fill").foregroundStyle(Theme.denied)
                    Spacer()
                    Button("Start") { model.installAgent() }.controlSize(.small)
                }
            }
            if r.problems.isEmpty {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.seal.fill").font(.title2).foregroundStyle(Theme.ok)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("All permissions are working").font(.callout.weight(.semibold))
                        Text("\(r.activity?.totals.apps ?? r.apps.count) apps asked for access today")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(r.problems.count == 1 ? "1 problem" : "\(r.problems.count) problems")
                        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    ForEach(r.problems.prefix(4)) { p in
                        ProblemRow(problem: p, open: { openWindow(selecting: .app(p.clientId)) })
                    }
                    if r.problems.count > 4 {
                        Button("Show all \(r.problems.count) problems…") { openWindow(selecting: .problems) }
                            .buttonStyle(.link).font(.caption)
                    }
                }
            }
        } else {
            ProgressView().controlSize(.small)
        }
    }

    // MARK: Recent apps

    private func recentApps(_ apps: [AppSummary]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Recently active").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            ForEach(apps) { app in
                Button { openWindow(selecting: .app(app.clientId)) } label: {
                    HStack(spacing: 8) {
                        AppIcon(path: app.appPath, size: 20)
                        Text(app.appName).lineLimit(1)
                        Text(app.permissionSummary).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        Spacer()
                        Text(StickyTime.ago(app.lastSeen)).font(.caption).foregroundStyle(.tertiary)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: Footer

    private var footer: some View {
        HStack(spacing: 8) {
            Button { openWindow() } label: { Text("Open Sticky").frame(maxWidth: .infinity) }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut("o")
            SettingsLink { Image(systemName: "gearshape") }
                .help("Settings")
            Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }
                .disabled(model.isRefreshing)
                .help("Refresh")
            Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }
                .help("Quit Sticky")
        }
    }
}

struct ProblemRow: View {
    let problem: Problem
    let open: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Button(action: open) {
                HStack(spacing: 10) {
                    AppIcon(path: problem.appPath, size: 28)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(problem.appName).font(.callout.weight(.semibold))
                        Text("\(problem.title) · \(problem.serviceName)")
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 4)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if let fix = problem.actions.first(where: { $0.kind == "open_url" }) {
                Button("Fix") { perform(fix) }
                    .controlSize(.small)
                    .help(fix.label)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.problem.opacity(0.08)))
    }
}

func copy(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}
