# Sticky

**Find out why your Mac keeps asking for permissions, and make them stick.**

On macOS 27, apps (especially developer tools) keep asking again for permissions you already granted. Sticky records the reasoning macOS writes to its own log every time it decides a permission request: which app asked, which app it blamed, whether the saved grant still matched, and what you answered. Then it explains what went wrong in plain English.

> Status: early development (week 1 of the [MVP plan](sticky-design.md)). The log parser works; the background recorder and `sticky why` are next.

## What works today

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
| `src/sticky/cli.py` | The `sticky` command |
| `tests/fixtures/` | Real logs recorded on macOS 27.2.1, with the username replaced by `user` |
| `sticky-design.md` | Architecture, diagnosis rules and milestones |

The macOS log format is undocumented and can change in any update. Every pattern in `rules.py` is tested against the recorded fixtures. When a new macOS version ships, record new fixtures first.
