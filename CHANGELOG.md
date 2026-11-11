# Changelog

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
