# Changelog

## 0.3.0

- **The Mac app gets a window.** Overview (status, 24-hour activity chart, what needs attention), Problems (evidence, numbered fix steps, Settings buttons), per-app pages (permissions, signing identity, day-by-day timeline), and Settings (open at login, Dock icon, notifications, history). Native grouped layouts that wrap text correctly in light and dark mode, and a new app icon: a permission switch taped ON.
- **Ignore findings.** Ignore one once, always for an app's permission, or for a whole app, from the app or with `sticky ignore`; list and restore them with `sticky ignores` / `sticky unignore`. Ignored findings don't count as problems or send notifications. `sticky why` notes hidden findings (`--include-ignored` shows them).
- **New:** `sticky events ID --json` (one app's decisions, for timelines). `sticky report` adds 24-hour activity for your apps, whether each app is an app or a system service, structured evidence on findings, and ignore rules. `sticky inspect --json` includes the plain-English verdict.
- **Readable names** for over 20 more permissions, for example Passkeys, App Management and Home.
- **Fix:** `sticky status` no longer says "Last log line: never" for up to a minute after the recorder starts.

## 0.2.0

- **Menu bar app (preview):** a SwiftUI app in `app/` that shows recording status and current problems with fix buttons, and notifies you about new problems: each one once, at most three at a time, and none on first launch. Built with the command-line tools; ad-hoc signed for local use.
- **`sticky report --json`:** recorder health and every finding in one document, with a stable key per problem and structured fix actions.
- **Fewer false alarms:** refusals that are just the default are no longer reported. That covers permissions such as Full Disk Access that were never switched on, and Apple platform binaries, which can never prompt. "Refused silently" now applies only to permissions macOS normally asks about, or after you clicked "Don't Allow".
- **New finding: "Lost a permission it had"** for default-off permissions that were allowed before and are denied now.
- **Much smaller database:** entitlement shortcuts (`Granting … via entitlement`) are now recognised, and only decisions Sticky can diagnose are stored. On a real 24-hour run that's 88 % fewer rows (7.2 MB → 1.3 MB). Old rows are cleaned up once, when the recorder starts.
- **Fix:** "macOS blamed a different app" no longer mistakes the target of an Automation request (such as Finder) for the tool that asked.

## 0.1.1

- **Fix:** running `sticky install-agent` again (for example after `brew upgrade`) could fail with `Bootstrap failed: 5: Input/output error` and leave no recorder running. Sticky now waits for launchd to finish unloading the old agent, and retries starting the new one. If it still can't, the error shows the `launchctl` command to run by hand.
- If you hit this on 0.1.0, upgrade and run `sticky install-agent` again.

## 0.1.0

First release. Command-line only; a menu bar app is planned.

- **Recording:** `sticky install-agent` runs a per-user LaunchAgent that records every permission decision from the system log (`/usr/bin/log stream`). It needs no sudo and no Full Disk Access, and uses about 0.03 % of one CPU core and about 20 MB of memory. Data stays on your Mac for 30 days.
- **Diagnosis:** `sticky why APP` explains each permission an app asked for, with a fix for each finding:
  - switched on, but not for this build;
  - asked again because the signing identity changed, the app moved, macOS blamed a different app, or the saved answer was removed;
  - refused silently after an earlier denial;
  - kept a permission after a rebuild.
- **Identity:** `sticky inspect` shows an app's signing identity and whether its permissions will survive updates.
- **Timeline and health:** `sticky log` and `sticky status`.
- Tested on macOS 27.2.1. The permissions log format is undocumented, so `sticky status` reports lines it doesn't recognise.
