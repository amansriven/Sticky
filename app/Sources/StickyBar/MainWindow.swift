import AppKit
import Charts
import StickyCore
import SwiftUI

// Pages are native grouped forms (like System Settings): consistent spacing,
// correct text wrapping, and light/dark handled by the system. Custom drawing
// is limited to a few pieces in Design.swift.

// MARK: - Window

struct MainWindow: View {
    @ObservedObject var model: ReportModel

    var body: some View {
        NavigationSplitView {
            Sidebar(model: model)
                .navigationSplitViewColumnWidth(min: 230, ideal: 260, max: 340)
        } detail: {
            detail
                .frame(minWidth: 560, maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Theme.pageFill)
        }
        .toolbar {
            ToolbarItem {
                Button { model.refresh() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                    .disabled(model.isRefreshing)
                    .help("Check for new permission decisions now")
            }
        }
        .onAppear { DockPolicy.apply(windowOpen: true) }
        .onDisappear { DockPolicy.apply(windowOpen: false) }
    }

    @ViewBuilder private var detail: some View {
        switch model.selection ?? .overview {
        case .overview:
            OverviewPage(model: model)
        case .problems:
            ProblemsPage(model: model)
        case let .app(id):
            if let app = model.app(id) {
                AppPage(model: model, app: app)
                    .task(id: id) { model.loadDetail(id) }
            } else {
                ContentUnavailableView("No recent activity", systemImage: "app.dashed",
                                       description: Text("Sticky hasn't seen this app in the selected history."))
            }
        }
    }
}

// MARK: - Sidebar

struct Sidebar: View {
    @ObservedObject var model: ReportModel

    var body: some View {
        let apps = model.filteredApps.filter { !stickyOwnBundleIDs.contains($0.clientId) }
        let attention = apps.filter { $0.status == "problem" }
        let yours = apps.filter { !$0.isSystem && $0.status != "problem" }
        let system = apps.filter { $0.isSystem && $0.status != "problem" }

        List(selection: $model.selection) {
            Section {
                Label("Overview", systemImage: "square.grid.2x2").tag(SidebarItem.overview)
                Label("Problems", systemImage: "exclamationmark.triangle")
                    .badge(model.problems.count)
                    .tag(SidebarItem.problems)
            }
            if !attention.isEmpty {
                Section("Needs attention") {
                    ForEach(attention) { AppRow(app: $0).tag(SidebarItem.app($0.clientId)) }
                }
            }
            Section("Apps") {
                ForEach(yours) { AppRow(app: $0).tag(SidebarItem.app($0.clientId)) }
            }
            Section(isExpanded: $model.showSystem) {
                ForEach(system) { AppRow(app: $0).tag(SidebarItem.app($0.clientId)) }
            } header: {
                Text("System services (\(system.count))")
            }
        }
        .searchable(text: $model.search, placement: .sidebar, prompt: "Search apps")
        .listStyle(.sidebar)
    }
}

struct AppRow: View {
    let app: AppSummary

    var body: some View {
        HStack(spacing: 9) {
            AppIcon(path: app.appPath, size: 22)
            VStack(alignment: .leading, spacing: 1) {
                Text(app.appName).lineLimit(1)
                Text(app.permissionSummary).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 4)
            if app.status == "problem" {
                Image(systemName: "exclamationmark.circle.fill").foregroundStyle(Theme.problem)
            }
        }
        .padding(.vertical, 1)
        .help("\(app.clientId) · last seen \(StickyTime.ago(app.lastSeen))")
    }
}

// MARK: - Overview

struct OverviewPage: View {
    @ObservedObject var model: ReportModel

    var body: some View {
        Form {
            if model.notificationsAllowed == false && model.settings.notificationsEnabled {
                Section { NotificationsOffRow() }
            }
            if let error = model.errorMessage, model.report == nil {
                Section("Can't reach the Sticky engine") {
                    Text(error).fixedSize(horizontal: false, vertical: true)
                }
            }
            if let r = model.report {
                Section { HeroRow(model: model, report: r) }

                if let activity = r.activity {
                    Section {
                        StatsRow(totals: activity.totals)
                        ActivityChart(activity: activity).padding(.vertical, 6)
                    } header: {
                        Text("Last 24 hours")
                    } footer: {
                        Text("Your apps only. System services are refused default-off permissions all day, so they aren't counted.")
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                Section("Needs attention") {
                    if r.problems.isEmpty {
                        Label("Nothing right now", systemImage: "checkmark.seal.fill").foregroundStyle(Theme.ok)
                    }
                    ForEach(r.problems.prefix(5)) { p in
                        LinkRow(iconPath: p.appPath, title: p.appName,
                                subtitle: "\(p.title) · \(p.serviceName)") {
                            model.selection = .app(p.clientId)
                        }
                    }
                    if r.problems.count > 5 {
                        Button("Show all \(r.problems.count) problems") { model.selection = .problems }
                            .buttonStyle(.link)
                    }
                }

                Section("Recently active") {
                    ForEach(r.apps.filter { !$0.isSystem && !stickyOwnBundleIDs.contains($0.clientId) }.prefix(6)) { app in
                        LinkRow(iconPath: app.appPath, title: app.appName, subtitle: app.permissionSummary,
                                trailing: StickyTime.ago(app.lastSeen)) {
                            model.selection = .app(app.clientId)
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
    }
}

/// The page headline: what's going on, in one sentence, with the next step.
struct HeroRow: View {
    @ObservedObject var model: ReportModel
    let report: Report

    var body: some View {
        let h = report.recorder
        let problemApps = report.problems.map(\.appName).uniqued()
        HStack(spacing: 14) {
            ZStack {
                Circle().fill(tint.gradient).frame(width: 44, height: 44)
                Image(systemName: symbol).font(.system(size: 20, weight: .bold)).foregroundStyle(.white)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(title(problemApps)).font(.title2.weight(.semibold))
                Text(subtitle(h)).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let message = model.agentMessage {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 12)
            if !h.isRecording {
                Button(h.agentInstalled ? "Restart Recording" : "Start Recording") { model.installAgent() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isInstallingAgent)
            } else if !report.problems.isEmpty {
                Button("Review Problems") { model.selection = .problems }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(.vertical, 6)
    }

    private var tint: Color {
        if !report.recorder.isRecording { return Theme.denied }
        return report.problems.isEmpty ? Theme.ok : Theme.problem
    }

    private var symbol: String {
        if !report.recorder.isRecording { return "pause.fill" }
        return report.problems.isEmpty ? "checkmark" : "exclamationmark"
    }

    private func title(_ apps: [String]) -> String {
        if !report.recorder.isRecording { return "Sticky isn't recording" }
        switch apps.count {
        case 0: return "All permissions are working"
        case 1: return "\(apps[0]) needs attention"
        default: return "\(apps.count) apps need attention"
        }
    }

    private func subtitle(_ h: RecorderHealth) -> String {
        if !h.isRecording {
            return "Start the background recorder so Sticky can see permission requests. It runs as you, with no admin password."
        }
        return "Recording since \(StickyTime.display(h.startedAt)) · last activity \(StickyTime.ago(h.lastRecord))"
    }
}

struct StatsRow: View {
    let totals: ActivityTotals

    var body: some View {
        HStack(spacing: 0) {
            stat("\(totals.apps)", "Apps", Color.indigo)
            Divider().frame(height: 34)
            stat("\(totals.allowed)", "Allowed", Theme.ok)
            Divider().frame(height: 34)
            stat("\(totals.denied)", "Denied", Theme.denied)
            Divider().frame(height: 34)
            stat("\(totals.asked)", "Prompts", Theme.asked)
        }
        .padding(.vertical, 4)
    }

    private func stat(_ value: String, _ label: String, _ tint: Color) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.title2.weight(.semibold)).monospacedDigit()
            HStack(spacing: 4) {
                Circle().fill(tint).frame(width: 6, height: 6)
                Text(label).font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

struct ActivityChart: View {
    let activity: Activity

    private struct Point: Identifiable {
        let id: String
        let hour: Date
        let kind: String
        let count: Int
    }

    var body: some View {
        let points = activity.hours.flatMap { b -> [Point] in
            guard let date = StickyTime.parse(b.hour + ":00.000") else { return [] }
            return [("Allowed", b.allowed), ("Denied", b.denied), ("Prompts", b.asked)].map {
                Point(id: b.hour + $0.0, hour: date, kind: $0.0, count: $0.1)
            }
        }
        Chart(points) { p in
            BarMark(x: .value("Hour", p.hour, unit: .hour), y: .value("Decisions", p.count))
                .foregroundStyle(by: .value("Result", p.kind))
                .cornerRadius(2)
        }
        .chartForegroundStyleScale(["Allowed": Theme.ok, "Denied": Theme.denied, "Prompts": Theme.asked])
        .chartXAxis {
            AxisMarks(values: .stride(by: .hour, count: 4)) { _ in
                AxisGridLine()
                AxisValueLabel(format: .dateTime.hour())
            }
        }
        .chartYAxis { AxisMarks(position: .leading) }
        .chartLegend(.hidden)
        .frame(height: 140)
    }
}

/// A tappable row: icon, title, subtitle, optional trailing text, chevron.
struct LinkRow: View {
    let iconPath: String?
    let title: String
    let subtitle: String
    var trailing: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                AppIcon(path: iconPath, size: 26)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                    Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
                if let trailing { Text(trailing).font(.caption).foregroundStyle(.secondary) }
                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Problems

struct ProblemsPage: View {
    @ObservedObject var model: ReportModel

    var body: some View {
        Form {
            if model.problems.isEmpty {
                Section {
                    Label("No problems. Everything Sticky recorded worked as expected.",
                          systemImage: "checkmark.seal.fill")
                        .foregroundStyle(Theme.ok)
                }
            }
            ForEach(model.problems) { p in
                FindingSection(model: model, finding: FindingContent(p), showsApp: true)
            }
            IgnoredSection(model: model, rules: model.ignoreRules)
        }
        .formStyle(.grouped)
    }
}

/// The parts of a finding a section shows (from a Problem or a Finding).
struct FindingContent {
    let key: String
    let clientId: String
    let service: String
    let serviceName: String
    let target: String?
    let appName: String
    let appPath: String?
    let severity: String
    let title: String
    let label: String
    let when: String?
    let detail: [String]
    let fix: [String]
    let actions: [FixAction]
    let evidence: Evidence?
    let ignoredBy: Int?

    init(_ p: Problem) {
        key = p.key; clientId = p.clientId; service = p.service; serviceName = p.serviceName
        target = p.target; appName = p.appName; appPath = p.appPath
        severity = p.severity; title = p.title; label = p.label; when = p.when
        detail = p.detail; fix = p.fix; actions = p.actions; evidence = p.evidence; ignoredBy = nil
    }

    init(_ f: Finding, permission: Permission, app: AppSummary) {
        key = f.key; clientId = f.clientId; service = f.service; serviceName = permission.serviceName
        target = f.target; appName = app.appName; appPath = app.appPath
        severity = f.severity; title = f.title; label = permission.label; when = f.when
        detail = f.detail; fix = f.fix; actions = f.actions; evidence = f.evidence; ignoredBy = f.ignoredBy
    }

    /// Prose lines not already shown by the evidence view.
    var explanation: [String] {
        guard evidence != nil else { return detail }
        return detail.filter { !$0.contains("signed as") && !$0.hasPrefix("  ") && !$0.hasSuffix(":") }
    }

    var isProblem: Bool { severity == "problem" }
}

/// One finding as a form section: what happened, the evidence, how to fix it.
struct FindingSection: View {
    @ObservedObject var model: ReportModel
    let finding: FindingContent
    let showsApp: Bool

    var body: some View {
        Section {
            HStack(alignment: .top, spacing: 12) {
                if showsApp {
                    AppIcon(path: finding.appPath, size: 36)
                } else {
                    Image(systemName: finding.isProblem ? "exclamationmark.triangle.fill" : "info.circle.fill")
                        .font(.title2)
                        .foregroundStyle(finding.isProblem ? Theme.problem : Theme.info)
                        .frame(width: 36)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(finding.title).font(.headline)
                    Text(subtitle).font(.callout).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                IgnoreMenu(model: model, finding: finding)
            }
            .padding(.vertical, 2)

            if let e = finding.evidence {
                EvidenceView(evidence: e, isProblem: finding.isProblem).padding(.vertical, 2)
            }

            if !finding.explanation.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(finding.explanation, id: \.self) {
                        Text($0).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .selectableText()
            }

            if !finding.fix.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("How to fix").font(.subheadline.weight(.semibold))
                    FixSteps(steps: finding.fix)
                    if !finding.actions.isEmpty {
                        ActionButtons(actions: finding.actions).padding(.top, 4)
                    }
                }
                .padding(.vertical, 2)
            }
        }
    }

    private var subtitle: String {
        let parts = (showsApp ? [finding.appName] : []) + [finding.label, StickyTime.ago(finding.when)]
        return parts.joined(separator: " · ")
    }
}

/// "Ignore" with a choice of how broadly.
struct IgnoreMenu: View {
    @ObservedObject var model: ReportModel
    let finding: FindingContent

    var body: some View {
        Menu {
            Button("Ignore This Time") { model.ignore(.finding(key: finding.key)) }
            Button("Always Ignore \(finding.label) for \(finding.appName)") {
                model.ignore(.permission(clientId: finding.clientId, service: finding.service, target: finding.target))
            }
            Divider()
            Button("Ignore All Alerts for \(finding.appName)") { model.ignore(.app(clientId: finding.clientId)) }
        } label: {
            Label("Ignore", systemImage: "eye.slash")
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help("Stop showing this. You can restore it from the Ignored list.")
    }
}

/// Ignore rules, each with a Restore button.
struct IgnoredSection: View {
    @ObservedObject var model: ReportModel
    let rules: [IgnoreRule]

    var body: some View {
        if !rules.isEmpty {
            Section {
                ForEach(rules) { rule in
                    HStack(spacing: 10) {
                        Image(systemName: "eye.slash").foregroundStyle(.secondary).frame(width: 20)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(rule.description)
                            Text(rule.hiding == 0 ? "Not hiding anything right now"
                                 : "Hiding \(rule.hiding) finding\(rule.hiding == 1 ? "" : "s")")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Restore") { model.restore(rule.id) }
                    }
                }
            } header: {
                Text("Ignored")
            } footer: {
                Text("Ignored findings don't appear as problems or send notifications.")
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

// MARK: - App page

struct AppPage: View {
    @ObservedObject var model: ReportModel
    let app: AppSummary

    var body: some View {
        let detail = model.detail(app.clientId)
        Form {
            Section { header(detail) }

            ForEach(activeFindings, id: \.key) { f in
                FindingSection(model: model, finding: f, showsApp: false)
            }

            Section("Permissions") {
                ForEach(Array(app.permissions.enumerated()), id: \.offset) { _, perm in
                    HStack(spacing: 10) {
                        OutcomeIcon(outcome: perm.lastOutcome).frame(width: 20)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(perm.label)
                            Text("\(perm.requests) request\(perm.requests == 1 ? "" : "s") · last \(StickyTime.ago(perm.lastSeen))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(outcomeLabel(perm.lastOutcome))
                            .font(.callout.weight(.medium))
                            .foregroundStyle(outcomeColor(perm.lastOutcome))
                    }
                }
            }

            IdentitySection(identity: detail.identity, isLoading: detail.isLoading && detail.identity == nil,
                            hasPath: app.appPath != nil)

            TimelineSections(model: model, detail: detail)

            let rules = model.ignoreRules.filter { $0.clientId == app.clientId }
            IgnoredSection(model: model, rules: rules)
        }
        .formStyle(.grouped)
    }

    private var activeFindings: [FindingContent] {
        app.permissions.flatMap { perm in
            perm.findings.filter { $0.severity != "ok" && $0.ignoredBy == nil }
                .map { FindingContent($0, permission: perm, app: app) }
        }
    }

    private func header(_ detail: AppDetail) -> some View {
        HStack(alignment: .center, spacing: 14) {
            AppIcon(path: app.appPath, size: 56)
            VStack(alignment: .leading, spacing: 3) {
                Text(app.appName).font(.title.weight(.semibold))
                Text([app.clientId, detail.identity?.version.map { "version \($0)" }].compactMap { $0 }
                    .joined(separator: " · "))
                    .font(.callout).foregroundStyle(.secondary).selectableText()
                HStack(spacing: 6) {
                    if app.isSystem { Pill(text: "System service", tint: .secondary) }
                    if let i = detail.identity, i.exists {
                        Pill(text: i.stable ? "Stable identity" : "Unstable identity",
                             systemImage: i.stable ? "checkmark.seal.fill" : "exclamationmark.triangle.fill",
                             tint: i.stable ? Theme.ok : Theme.problem)
                    }
                }
                .padding(.top, 2)
            }
            Spacer()
            if let path = app.appPath {
                Button { model.reveal(path) } label: { Label("Show in Finder", systemImage: "folder") }
            }
        }
        .padding(.vertical, 4)
    }
}

struct IdentitySection: View {
    let identity: AppIdentity?
    let isLoading: Bool
    let hasPath: Bool

    var body: some View {
        Section("Identity") {
            if let i = identity, i.exists {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: i.stable ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle(i.stable ? Theme.ok : Theme.problem)
                    Text(i.explanation ?? "").fixedSize(horizontal: false, vertical: true)
                }
                LabeledContent("Signature", value: i.signatureLabel)
                if let developer = i.developerName { LabeledContent("Developer", value: developer) }
                LabeledContent("Signing identity") { RequirementChip(requirement: i.designatedRequirement) }
                LabeledContent("Hardened runtime", value: i.hardenedRuntime ? "Yes" : "No")
                LabeledContent("Notarized", value: i.notarization == "stapled" ? "Yes" : "No ticket stapled")
                LabeledContent("Can ask for") {
                    Text(i.declaredUsage.isEmpty ? "None declared" : i.friendlyUsage.joined(separator: ", "))
                        .multilineTextAlignment(.trailing)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } else if let i = identity {
                Text(i.explanation ?? "The app's file couldn't be found.").foregroundStyle(.secondary)
            } else if isLoading {
                ProgressView().controlSize(.small)
            } else {
                Text(hasPath ? "Couldn't read the app's signature."
                     : "Sticky doesn't know where this app's file is, so it can't check its signature.")
                    .foregroundStyle(.secondary)
            }
        }
    }
}

/// One timeline entry: a decision, or several identical ones in the same second.
struct TimelineEntry: Identifiable {
    let event: TimelineEvent
    let count: Int
    var id: Int { event.id }

    static func collapse(_ events: [TimelineEvent]) -> [TimelineEntry] {
        var out: [TimelineEntry] = []
        for e in events {
            if let last = out.last, String(last.event.tsStart.prefix(19)) == String(e.tsStart.prefix(19)),
               last.event.permissionLabel == e.permissionLabel, last.event.outcome == e.outcome,
               last.event.clientDr == e.clientDr {
                out[out.count - 1] = TimelineEntry(event: last.event, count: last.count + 1)
            } else {
                out.append(TimelineEntry(event: e, count: 1))
            }
        }
        return out
    }
}

struct TimelineSections: View {
    @ObservedObject var model: ReportModel
    let detail: AppDetail

    var body: some View {
        let shown = detail.events.filter { model.showRoutineEvents || !$0.isRoutine }
        let days = Dictionary(grouping: shown.prefix(400)) { String($0.tsStart.prefix(10)) }
            .sorted { $0.key > $1.key }
        Section {
            if let error = detail.error {
                Text(error).foregroundStyle(.secondary)
            } else if detail.isLoading && detail.events.isEmpty {
                ProgressView().controlSize(.small)
            } else if shown.isEmpty {
                Text("No decisions to show.").foregroundStyle(.secondary)
            }
            Toggle("Show routine checks", isOn: $model.showRoutineEvents)
        } header: {
            Text("Timeline")
        } footer: {
            Text("Routine checks are launch-time and \"would this be allowed?\" checks that decide nothing.")
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        ForEach(days, id: \.key) { day, events in
            Section(dayLabel(day)) {
                let entries = TimelineEntry.collapse(events)
                ForEach(Array(entries.enumerated()), id: \.element.id) { index, entry in
                    TimelineRow(entry: entry,
                                buildChanged: index + 1 < entries.count
                                    && entries[index + 1].event.clientDr != nil
                                    && entry.event.clientDr != nil
                                    && entries[index + 1].event.clientDr != entry.event.clientDr)
                }
            }
        }
    }

    private func dayLabel(_ day: String) -> String {
        guard let date = StickyTime.parse(day + " 00:00:00.000") else { return day }
        if Calendar.current.isDateInToday(date) { return "Today" }
        if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
        let f = DateFormatter()
        f.dateFormat = "EEEE, MMMM d"
        return f.string(from: date)
    }
}

struct TimelineRow: View {
    let entry: TimelineEntry
    let buildChanged: Bool

    var body: some View {
        let e = entry.event
        HStack(alignment: .center, spacing: 10) {
            OutcomeIcon(outcome: e.outcome).frame(width: 20)
            Text(time).font(.callout.monospacedDigit()).foregroundStyle(.secondary)
                .frame(width: 44, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(e.permissionLabel).lineLimit(1)
                    if entry.count > 1 {
                        Text("×\(entry.count)").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    }
                }
                if buildChanged {
                    Text("New build: \(Requirement.short(e.clientDr))")
                        .font(.caption).foregroundStyle(Theme.problem)
                } else if let note = e.note {
                    Text(note).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 8)
            Text(e.outcomeLabel).font(.callout.weight(.medium)).foregroundStyle(outcomeColor(e.outcome))
        }
        .help([e.clientDr.map { "Signed as: \($0)" }, e.clientVersion.map { "Version \($0)" }]
            .compactMap { $0 }.joined(separator: "\n"))
    }

    private var time: String {
        guard let d = StickyTime.parse(entry.event.tsStart) else { return "" }
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: d)
    }
}

// MARK: - Shared pieces

struct NotificationsOffRow: View {
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "bell.slash.fill").foregroundStyle(Theme.problem)
            Text("Notifications are off, so you won't hear about new problems.")
            Spacer()
            Button("Turn On") { NSWorkspace.shared.open(Notifier.settingsURL) }
        }
    }
}

struct AppIcon: View {
    let path: String?
    let size: CGFloat
    var body: some View {
        Image(nsImage: path.map { NSWorkspace.shared.icon(forFile: $0) }
              ?? NSWorkspace.shared.icon(for: .applicationBundle))
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
    }
}

func outcomeColor(_ outcome: String?) -> Color {
    switch outcome {
    case "allowed", "prompted-allowed": return Theme.ok
    case "denied", "prompted-denied": return Theme.denied
    case "prompted": return Theme.asked
    default: return .secondary
    }
}

func outcomeLabel(_ outcome: String?) -> String {
    switch outcome {
    case "allowed": return "Allowed"
    case "denied": return "Denied"
    case "prompted-allowed": return "Asked → Allowed"
    case "prompted-denied": return "Asked → Denied"
    case "prompted": return "Asked"
    case "undetermined": return "Not decided"
    default: return outcome ?? "–"
    }
}

func perform(_ action: FixAction) {
    switch action.kind {
    case "open_url":
        if let url = URL(string: action.value) { NSWorkspace.shared.open(url) }
    case "copy":
        copy(action.value)
    default:
        break
    }
}

extension Sequence where Element: Hashable {
    func uniqued() -> [Element] {
        var seen = Set<Element>()
        return filter { seen.insert($0).inserted }
    }
}

extension StickyTime {
    /// "Nov 12, 12:16" (today: "12:16").
    static func display(_ text: String?) -> String {
        guard let date = parse(text) else { return "–" }
        let f = DateFormatter()
        f.dateFormat = Calendar.current.isDateInToday(date) ? "HH:mm" : "MMM d, HH:mm"
        return f.string(from: date)
    }
}

extension AppIdentity {
    /// "Aiginal Technologies Private Limited" from
    /// "Developer ID Application: Aiginal Technologies Private Limited (CJ38WK8T4L)".
    var developerName: String? {
        guard let a = authority, signKind != "adhoc", signKind != "apple" else { return nil }
        var name = a
        if let colon = name.range(of: ": ") { name = String(name[colon.upperBound...]) }
        if let paren = name.range(of: " (", options: .backwards) { name = String(name[..<paren.lowerBound]) }
        return name
    }

    /// Usage keys in the words System Settings uses.
    var friendlyUsage: [String] {
        let names = ["AppleEvents": "Automation", "AudioCapture": "System audio", "LocalNetwork": "Local network",
                     "ScreenCapture": "Screen recording", "SpeechRecognition": "Speech recognition",
                     "CalendarsFullAccess": "Calendars", "RemindersFullAccess": "Reminders",
                     "PhotoLibrary": "Photos", "BluetoothAlways": "Bluetooth", "DesktopFolder": "Desktop folder",
                     "DocumentsFolder": "Documents folder", "DownloadsFolder": "Downloads folder",
                     "Contacts": "Contacts", "Camera": "Camera", "Microphone": "Microphone"]
        return declaredUsage.map { names[$0] ?? $0 }
    }
}

/// Dock icon while the main window is open (or always, if the user wants it).
enum DockPolicy {
    @MainActor static func apply(windowOpen: Bool) {
        let regular = AppSettings.shared.showInDock || windowOpen
        NSApp.setActivationPolicy(regular ? .regular : .accessory)
        if windowOpen && !Snapshotter.isActive { NSApp.activate(ignoringOtherApps: true) }
    }
}
