import AppKit
import StickyCore
import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings: AppSettings
    @ObservedObject var model: ReportModel

    var body: some View {
        Form {
            Section("General") {
                Toggle("Open Sticky at login", isOn: Binding(
                    get: { settings.launchAtLogin },
                    set: { settings.setLaunchAtLogin($0) }))
                if let note = settings.launchAtLoginNote {
                    Text(note).font(.caption).foregroundStyle(.secondary)
                }
                Toggle("Show in the Dock", isOn: $settings.showInDock)
                Text("When off, Sticky lives in the menu bar and appears in the Dock only while its window is open.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("Notifications") {
                Toggle("Notify me about new permission problems", isOn: $settings.notificationsEnabled)
                if model.notificationsAllowed == false {
                    HStack {
                        Text("Notifications are turned off for Sticky in System Settings.")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button("Open Settings") { NSWorkspace.shared.open(Notifier.settingsURL) }
                    }
                }
            }

            if model.ignoreRules.isEmpty {
                Section("Ignored") {
                    Text("Nothing is ignored. Use Ignore on any problem to hide it.").foregroundStyle(.secondary)
                }
            } else {
                IgnoredSection(model: model, rules: model.ignoreRules)
            }

            Section("Data") {
                Picker("Show history from", selection: $settings.history) {
                    ForEach(AppSettings.historyChoices, id: \.value) { Text($0.label).tag($0.value) }
                }
                Picker("Check for changes", selection: $settings.refreshInterval) {
                    ForEach(AppSettings.refreshChoices, id: \.value) { Text($0.label).tag($0.value) }
                }
                Text("Recorded data stays on this Mac, in ~/Library/Application Support/Sticky, and is kept for 30 days.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("Recorder") {
                if let h = model.report?.recorder {
                    LabeledContent("Status", value: h.isRecording ? "Recording" : "Not recording")
                    LabeledContent("Sticky engine", value: model.report.map { "sticky \($0.stickyVersion)" } ?? "–")
                }
                LabeledContent("Command", value: StickyCLI.locate() ?? "Not found")
                HStack {
                    Button("Restart recorder") { model.installAgent() }
                        .disabled(model.isInstallingAgent || StickyCLI.locate() == nil)
                    if let message = model.agentMessage {
                        Text(message).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .onAppear { settings.syncLaunchAtLogin() }
    }
}
