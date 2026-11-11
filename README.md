# Sticky

**Find out why your Mac keeps asking for permissions, and make them stick.**

On macOS 27, apps (especially developer tools) keep asking again for permissions you already granted. Sticky records the reasoning macOS writes to its own log every time it decides a permission request: which app asked, which app it blamed, whether the saved grant still matched, and what you answered. Then it explains what went wrong in plain English.

> Status: early development (week 2 of the [MVP plan](sticky-design.md)). The parser and the background recorder work; `sticky why` is next.

## What works today

Record permission decisions in the background (a per-user LaunchAgent: no sudo, no Full Disk Access), then look at the timeline:

```bash
sticky install-agent
```

```text
$ sticky log --since 1h --service AppleEvents
time                scope  service              client                       target               outcome
11-11 04:59:35      user   AppleEvents          com.anthropic.claude-code    com.apple.finder     allowed
11-11 04:59:55      user   AppleEvents          com.anthropic.claude-code    com.apple.Safari     DENIED
```

| Command | What it does |
|---|---|
| `sticky install-agent` | Record in the background from login (`--dry-run` prints the plist and changes nothing) |
| `sticky uninstall-agent` | Stop recording and remove the agent; recorded data is kept |
| `sticky record` | Record in the foreground (Ctrl+C to stop) |
| `sticky status` | Is the recorder running? When did it last see a log line? |
| `sticky log` | Timeline of decisions: `--since 2h`, `--client`, `--service`, `--outcome denied`, `--json` |
| `sticky parse FILE` | Decisions in a saved log file (development) |

Data stays on your Mac in `~/Library/Application Support/Sticky/sticky.db` and is kept for 30 days. The recorder uses about 0.03 % of one CPU core and about 20 MB of memory.

`sticky parse` reads a saved permissions log and lists every decision:

```text
$ sticky parse tests/fixtures/compact-prompt-denied.log --service AppleEvents
time         scope  service                client                       target               outcome
04:16:05.965 user   AppleEvents            com.anthropic.claude-code    com.apple.Safari     prompted-denied
04:16:15.031 user   AppleEvents            com.anthropic.claude-code    com.apple.Safari     denied
```

To record your own log (no Full Disk Access or sudo needed):

```bash
/usr/bin/log stream --info --debug --style ndjson --predicate 'subsystem == "com.apple.TCC"' > tcc.ndjson
```

Use the full path, `/usr/bin/log`: in zsh, plain `log` is a built-in command. Press Ctrl+C to stop, then run `sticky parse tcc.ndjson`.

## Development

Requires Python 3.10+ and no third-party packages.

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

| Path | What it is |
|---|---|
| `src/sticky/logsource.py` | Reads `log stream` output (ndjson or compact) into uniform records |
| `src/sticky/rules.py` | Patterns for the permissions-service log lines, verified on macOS 27.2.1 |
| `src/sticky/assembler.py` | Groups each request's lines (by tccd thread, REQUEST → REPLY) into one `Event` |
| `src/sticky/store.py` | SQLite storage: events, recorder runs, unrecognised line templates |
| `src/sticky/recorder.py` | Runs `log stream`, stores decisions, restarts with backoff, heartbeat |
| `src/sticky/agent.py` | Installs the recorder as a LaunchAgent |
| `src/sticky/cli.py` | The `sticky` command |
| `tests/fixtures/` | Real logs recorded on macOS 27.2.1, with the username replaced by `user` |
| `sticky-design.md` | Architecture, diagnosis rules and milestones |

The macOS log format is undocumented and can change in any update. Every pattern in `rules.py` is tested against the recorded fixtures. When a new macOS version ships, record new fixtures first.
