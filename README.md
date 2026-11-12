# Sticky

**Find out why your Mac keeps asking for permissions, and make them stick.**

On macOS 27, apps keep asking again for permissions you already granted, and some quietly stop working while System Settings still shows them switched on. Developer tools are hit hardest. System Settings shows only a switch and never says why.

Sticky records the reasoning macOS writes to its own log each time it decides a permission request: which app asked, which app macOS held responsible, which build the saved approval is for, whether the running app matches it, and what you answered. Then it explains what went wrong in plain English and how to fix it.

```text
$ sticky why brokentool
BrokenTool  (dev.sticky.brokentool 1.0)
  Identity: ⚠ Ad-hoc signed: no developer identity. Its signature is a hash of this exact build, …
  Builds seen: 3, each with a different identity.

  Accessibility   (9 requests)
    ✗ Switched on, but not for this build
      Your approval is saved for the build signed as cdhash H"970b1915…".
      The current build is signed as cdhash H"c1296205…", which doesn't match it, so macOS denies access without asking.
      It worked until 11-11 06:30; 2 requests since were denied.
      System Settings → Privacy & Security → Accessibility may still show it switched on.
      Fix: Re-approve this build: in System Settings → Accessibility, remove the app with − and add it again with + …
           Switching it off and on isn't enough: the approval keeps naming the old build.
```

## Install

```bash
brew install amansriven/tap/sticky
```

Then start recording in the background. It runs as you, with no sudo and no Full Disk Access:

```bash
sticky install-agent
```

Sticky can only explain requests made while it's recording, so install the agent before the next time something goes wrong.

## Use

| Command | What it does |
|---|---|
| `sticky why APP` | Explain every permission an app asked for, with fixes. `APP` is a name, bundle id or path fragment. |
| `sticky inspect PATH\|BUNDLE-ID` | Show an app's signing identity and whether its permissions will survive updates |
| `sticky log` | Timeline of decisions: `--since 2h`, `--client`, `--service`, `--outcome denied`, `--json` |
| `sticky status` | Is the recorder running? When did it last see a log line? |
| `sticky report --json` | Recorder health and every finding as JSON (what the menu bar app reads) |
| `sticky install-agent` | Record in the background from login (`--dry-run` prints the LaunchAgent and changes nothing) |
| `sticky uninstall-agent` | Stop recording and remove the agent; recorded data is kept |
| `sticky record` | Record in the foreground (Ctrl+C to stop) |

## What it can tell you

| Finding | What happened |
|---|---|
| **Switched on, but not for this build** | Your approval names an earlier build of the app. macOS checks the running build against it, the check fails, and access is denied without asking. Common after rebuilding or updating an ad-hoc signed app (seen with Accessibility). |
| **Asked again: the signing identity changed** | macOS treated a rebuilt or updated app as a new app and prompted again |
| **Asked again: the app moved** | The app is identified by its location, and it moved |
| **Asked again: macOS blamed a different app** | Permissions belong to the app macOS holds responsible (often your terminal), not the tool you ran |
| **Asked again: the saved answer was removed** | Same app, same place, but the approval disappeared: `tccutil`, System Settings, or a management profile |
| **Denied: refused silently** | A permission macOS normally asks about was refused without asking, because a "Don't Allow" is saved |
| **Lost a permission it had** | A permission that's off by default (Full Disk Access, Accessibility…) was allowed before and is denied now |
| **Kept its permission after a rebuild** | Informational: macOS carried an approval over to a new build (seen with Automation) |

Each finding names the System Settings page to open, or the `tccutil` command that resets just that app.

Sticky doesn't flag refusals that are simply the default: permissions like Full Disk Access that were never switched on, or Apple's own background services, which macOS never lets ask.

## Menu bar app (preview)

`app/` holds a SwiftUI menu bar app. It shows recording status and current problems with one-click fixes, and notifies you when a new problem appears. For example, about 10 seconds after an app silently loses Accessibility, you get "BrokenTool: Switched on, but not for this build".

It runs `sticky report` (Sticky 0.2.0 or later), so all the diagnosis logic stays in one place. For now, build it from this repository; it needs only the Xcode command-line tools:

```bash
app/build.sh
```

```bash
open app/build/Sticky.app
```

It finds `sticky` in Homebrew's usual locations. To use a source checkout instead, run `open --env STICKY_BIN="$PWD/scripts/sticky-dev" app/build/Sticky.app`. The build is ad-hoc signed for local use; a signed download is planned.

## Privacy and resource use

- Everything stays on your Mac, in `~/Library/Application Support/Sticky/sticky.db`. Nothing is sent anywhere.
- Data is kept for 30 days.
- The recorder reads the system log with `/usr/bin/log stream`, which needs no extra permissions. It uses about 0.03 % of one CPU core and about 20 MB of memory.

## Requirements and limits

- macOS 27 (tested on 27.2.1). Earlier versions are untested.
- The permissions log format is undocumented and can change in any macOS update. `sticky status` reports log lines it didn't recognise. If that list grows after an update, please open an issue.
- Sticky reads and explains; it never changes permissions itself.

## Uninstall

```bash
sticky uninstall-agent
```

```bash
brew uninstall sticky
```

To delete the recorded data too, remove `~/Library/Application Support/Sticky` and `~/Library/Logs/Sticky`.

## Development

Requires Python 3.10+ and no third-party packages.

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`sticky parse FILE` lists the decisions in a saved log, which is useful for building fixtures:

```bash
/usr/bin/log stream --info --debug --style ndjson --predicate 'subsystem == "com.apple.TCC"' > tcc.ndjson
```

Use the full path, `/usr/bin/log`: in zsh, plain `log` is a built-in command. Press Ctrl+C to stop, then run `sticky parse tcc.ndjson`.

| Path | What it is |
|---|---|
| `src/sticky/logsource.py` | Reads `log stream` output (ndjson or compact) into uniform records |
| `src/sticky/rules.py` | Patterns for the permissions-service log lines, verified on macOS 27.2.1 |
| `src/sticky/assembler.py` | Groups each request's lines (by tccd thread, REQUEST → REPLY) into one `Event` |
| `src/sticky/store.py` | SQLite storage: events, recorder runs, app builds, unrecognised line templates |
| `src/sticky/recorder.py` | Runs `log stream`, stores decisions, restarts with backoff, heartbeat |
| `src/sticky/agent.py` | Installs the recorder as a LaunchAgent |
| `src/sticky/identity.py` | Reads an app's signing identity with `codesign` |
| `src/sticky/diagnose.py` | Diagnosis rules R1–R7 |
| `src/sticky/report.py` | `sticky report`: health and findings as JSON for the app |
| `src/sticky/cli.py` | The `sticky` command |
| `app/` | The SwiftUI menu bar app (`StickyCore`: models, CLI bridge, notification planning; `StickyBar`: UI). Test with `cd app && swift test` |
| `scripts/sticky-dev` | Runs `sticky` from this checkout (for the app, or without installing) |
| `tools/brokentool/` | A deliberately fragile ad-hoc signed app for testing (`build.sh [tag]`, then `run.sh` for Automation or `run.sh ax` for Accessibility) |
| `tests/fixtures/` | Real logs recorded on macOS 27.2.1, anonymized |
| `packaging/homebrew/sticky.rb` | The Homebrew formula (published copy lives in `amansriven/homebrew-tap`) |
| `sticky-design.md` | Architecture, diagnosis rules, test results and milestones |

When a new macOS version ships, record new fixtures first: every pattern in `rules.py` is tested against them.

## License

MIT
