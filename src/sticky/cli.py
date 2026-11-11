"""Command-line entry point.

Commands:
  sticky parse FILE        list decisions in a saved log (for development)
  sticky record            run the recorder in the foreground
  sticky install-agent     run the recorder in the background from login
  sticky uninstall-agent   stop it and remove it
  sticky status            is the recorder running and healthy?
  sticky log               timeline of recorded permission decisions
  sticky why APP           explain why an app keeps being asked, or is refused
  sticky inspect PATH|ID   an app's signing identity: will grants stick?
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from . import __version__, agent
from .assembler import assemble
from .logsource import read_records
from .store import Store, now_ts, parse_duration, ts_ago

OUTCOME_LABELS = {
    "allowed": "allowed",
    "denied": "DENIED",
    "prompted-allowed": "prompt → allowed",
    "prompted-denied": "prompt → DENIED",
    "prompted": "prompt (no answer)",
    "undetermined": "not decided",
    "limited": "limited",
    "unknown": "?",
}


def _short(value: str | None, width: int) -> str:
    value = value or "-"
    return value if len(value) <= width else value[: width - 1] + "…"


def print_table(events: Iterable[Mapping], with_date: bool = False) -> int:
    """Print events (Event.to_dict() or DB rows) as a table. Returns the count."""
    tw = 19 if with_date else 12
    print(f"{'time':<{tw}} {'scope':<6} {'service':<20} {'client':<28} {'target':<20} outcome")
    n = 0
    for e in events:
        ts = e["ts_start"][5:19] if with_date else e["ts_start"][11:23]
        service = (e["service"] or "-").removeprefix("kTCCService")
        target = e["target_id"] or e["target_name"]
        print(
            f"{ts:<{tw}} {e['tccd_scope'] or '-':<6} {_short(service, 20):<20} "
            f"{_short(e['client_id'], 28):<28} {_short(target, 20):<20} "
            f"{OUTCOME_LABELS.get(e['outcome'], e['outcome'])}"
        )
        n += 1
    return n


def _open_store(args) -> Store:
    return Store(args.db) if args.db else Store()


# Commands ------------------------------------------------------------------
def cmd_parse(args: argparse.Namespace) -> int:
    events, asm = assemble(read_records(args.file, args.format))
    # Entitled checks are Apple's own processes using built-in permissions:
    # they never prompt, so they are noise unless --all is given.
    shown = [e for e in events if args.all or (e.is_decision and not e.entitled)]
    if args.service:
        shown = [e for e in shown if e.service and args.service.lower() in e.service.lower()]
    if args.client:
        shown = [e for e in shown if e.client_id and args.client.lower() in e.client_id.lower()]

    if args.json:
        for e in shown:
            print(json.dumps(e.to_dict()))
    else:
        print_table(e.to_dict() for e in shown)

    s = asm.stats
    print(
        f"\n{s['requests']} requests: {s['complete']} ended with a reply, "
        f"{s['ended_without_reply']} without one (forwarded or entitled), "
        f"{s['incomplete_at_end']} still open at end of log; "
        f"{s['forwarded']} forwarded, {s['msg_id_mismatch']} msgID mismatches, "
        f"{sum(1 for e in events if e.is_decision)} access decisions",
        file=sys.stderr,
    )
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    from .recorder import Recorder

    store = _open_store(args)
    rec = Recorder(store, store_all=args.store_all)
    rec.install_signal_handlers()
    try:
        return rec.run()
    finally:
        store.close()


def cmd_log(args: argparse.Namespace) -> int:
    try:
        since = None if args.since in (None, "all") else ts_ago(parse_duration(args.since))
    except ValueError as e:
        print(f"sticky log: {e}", file=sys.stderr)
        return 2
    with _open_store(args) as store:
        return _show_log(args, store, since)


def _show_log(args: argparse.Namespace, store: Store, since: str | None) -> int:
    rows = store.query_events(
        since=since,
        client=args.client,
        service=args.service,
        outcome=args.outcome,
        include_entitled=args.all,
        limit=args.limit,
    )
    if args.json:
        for r in rows:
            print(json.dumps(dict(r)))
        return 0
    if not rows:
        window = f" in the last {args.since}" if args.since not in (None, "all") else ""
        print(f"No permission decisions recorded{window}.")
        if not agent.is_installed() and store.latest_run() is None:
            print("The recorder hasn't run yet. Start it with `sticky install-agent` (background) "
                  "or `sticky record` (foreground).")
        return 0
    print_table(rows, with_date=True)
    return 0


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _age(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        then = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts
    secs = int((datetime.now() - then).total_seconds())
    if secs < 120:
        return f"{secs}s ago"
    if secs < 7200:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def cmd_status(args: argparse.Namespace) -> int:
    installed = agent.is_installed()
    loaded = agent.is_loaded() if installed else False
    print(f"Background agent: {'installed' if installed else 'not installed'}"
          + (", loaded in launchd" if loaded else (", NOT loaded" if installed else "")))

    with _open_store(args) as store:
        return _show_status(store)


def _show_status(store: Store) -> int:
    print(f"Database:         {store.path} ({store.count_events()} decisions)")
    run = store.latest_run()
    if run is None:
        print("Recorder:         has never run")
        return 1
    running = run["ended_at"] is None and _pid_alive(run["pid"])
    stale = run["heartbeat"] is not None and run["heartbeat"] < ts_ago(parse_duration("3m"))
    if running and not stale:
        state = "running"
    elif running:
        state = "running, but no heartbeat for over 3 minutes"
    else:
        note = run["note"] or "process ended without saying why"
        state = "stopped" if note == "stopped" else f"stopped: {note}"
    print(f"Recorder:         {state}, pid {run['pid']}, run #{run['id']} since {run['started_at'][:19]}")
    print(f"Last log line:    {_age(run['last_record'])}; heartbeat {_age(run['heartbeat'])}")
    print(f"This run:         {run['records']} log lines, {run['requests']} requests, "
          f"{run['decisions']} decisions stored, {run['restarts']} restarts of log stream")
    unknown = store.top_unrecognised()
    if unknown:
        print("Unrecognised log lines (most common):")
        for row in unknown:
            print(f"  {row['count']:>7}  {_short(row['template'].replace(chr(10), ' '), 90)}")
    return 0 if running and not stale else 1


MARKS = {"problem": "✗", "info": "!", "ok": "✓"}


def _print_identity(ident, indent: str = "  ") -> None:
    if not ident.exists:
        print(f"{indent}Identity: {ident.code_path} no longer exists ({ident.error}).")
        return
    mark = "✓" if ident.stable else "⚠"
    print(f"{indent}Identity: {mark} {ident.explain()}")


def cmd_why(args: argparse.Namespace) -> int:
    from .diagnose import diagnose
    from .identity import inspect

    try:
        since = None if args.since in (None, "all") else ts_ago(parse_duration(args.since))
    except ValueError as e:
        print(f"sticky why: {e}", file=sys.stderr)
        return 2

    with _open_store(args) as store:
        rows = store.query_events(since=since, client=args.app)
        clients = {r["client_id"] for r in rows if r["client_id"]}
        results = diagnose(rows, {c: store.identities_for(c) for c in clients})
        if args.json:
            for g, findings in results:
                print(json.dumps({"client_id": g.client_id, "service": g.service,
                                  "target": g.target, "requests": len(g.events),
                                  "findings": [f.to_dict() for f in findings]}))
            return 0
        if not results:
            started = store.first_run_started()
            print(f"No recorded permission requests for {args.app!r}"
                  + (f" in the last {args.since}." if since else "."))
            if started:
                print(f"Sticky only sees requests made while it was recording (since {started[:16]}).")
            if os.path.exists(args.app):
                print()
                _print_identity(inspect(args.app), indent="")
            return 1

        by_client: dict[str, list] = {}
        for g, findings in results:
            by_client.setdefault(g.client_id, []).append((g, findings))

        problems = 0
        for client_id, items in by_client.items():
            latest = max((e for g, _ in items for e in g.events), key=lambda e: e["ts_start"])
            path = latest.get("client_path") or store.latest_path_for(client_id)
            ident = inspect(path) if path else None
            name = (ident.name if ident and ident.exists else None) or latest.get("client_name") or client_id
            version = latest.get("client_version") or (ident.version if ident else None)
            print(f"{name}  ({client_id}{' ' + version if version else ''})")
            if ident:
                _print_identity(ident)
            builds = store.identities_for(client_id)
            if len({b["cdhash"] for b in builds}) > 1 and builds[-1]["dr_kind"] == "cdhash":
                print(f"  Builds seen: {len(builds)}, each with a different identity.")
            # Problems first, then info, then OK.
            order = {"problem": 0, "info": 1, "ok": 2}
            items.sort(key=lambda gf: min((order[f.severity] for f in gf[1]), default=3))
            for g, findings in items:
                print(f"\n  {g.label}   ({len(g.events)} request{'s' if len(g.events) != 1 else ''})")
                if not findings:
                    last = g.latest
                    print(f"    · last request {last['ts_start'][5:16]}: {last['outcome']}")
                for f in findings:
                    problems += f.severity == "problem"
                    print(f"    {MARKS[f.severity]} {f.title}")
                    for line in f.detail:
                        print(f"      {line}")
                    for line in f.fix:
                        print(f"      Fix: {line}")
            print()
        return 1 if problems else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    from .identity import USAGE_KEYS, find_app_by_bundle_id, inspect

    target = args.target
    if not os.path.exists(target):
        with _open_store(args) as store:
            path = store.latest_path_for(target)
        path = path or find_app_by_bundle_id(target)
        if not path:
            print(f"sticky inspect: {target!r} is not a path, and no app with that bundle id was found.",
                  file=sys.stderr)
            return 2
        target = path
    ident = inspect(target)
    if args.json:
        print(json.dumps(ident.to_dict()))
        return 0
    if not ident.exists:
        print(f"{ident.code_path}: {ident.error}")
        return 1
    print(f"{ident.name}  ({ident.identifier or 'no identifier'}{' ' + ident.version if ident.version else ''})")
    print(f"  Path:        {ident.code_path}")
    kind = ident.sign_kind + (" (linker-signed)" if ident.linker_signed else "")
    print(f"  Signature:   {kind}" + (f", team {ident.team_id}" if ident.team_id else "")
          + (f", {ident.authority}" if ident.authority and ident.sign_kind != "adhoc" else ""))
    print(f"  Hardened runtime: {'yes' if ident.hardened_runtime else 'no'}"
          + (f"; notarization ticket {ident.notarization}" if ident.notarization else ""))
    print(f"  Requirement: {ident.designated_requirement or 'none'}")
    print(f"  Verdict:     {'✓' if ident.stable else '⚠'} {ident.explain()}")
    declared = sorted(ident.usage_keys)
    missing = sorted(set(USAGE_KEYS.values()) - set(ident.usage_keys))
    print(f"  Usage descriptions declared: {', '.join(declared) if declared else 'none'}")
    if declared or Path(ident.code_path).suffix == ".app":
        print(f"  Not declared (macOS may refuse these, or ask without a reason): "
              f"{', '.join(k.removeprefix('NS').removesuffix('UsageDescription') for k in missing)}")
    return 0 if ident.stable else 1


def cmd_install_agent(args: argparse.Namespace) -> int:
    if args.dry_run:
        import plistlib
        sys.stdout.write(plistlib.dumps(agent.build_plist(db_path=args.db)).decode())
        return 0
    path = agent.install(db_path=args.db)
    print(f"Installed {path}")
    print(f"The recorder is running in the background. Logs: {agent.log_path()}")
    print("macOS may show a 'Background Items Added' notification; that's this agent.")
    return 0


def cmd_uninstall_agent(args: argparse.Namespace) -> int:
    if agent.uninstall():
        print("Stopped and removed the recorder agent. Recorded data was kept.")
    else:
        print("The recorder agent wasn't installed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sticky", description="Why does your Mac keep asking?")
    parser.add_argument("--version", action="version", version=f"sticky {__version__}")
    parser.add_argument("--db", help="database path (default: ~/Library/Application Support/Sticky/sticky.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="list decisions in a saved permissions log")
    p.add_argument("file")
    p.add_argument("--format", choices=["ndjson", "compact"], help="default: detect")
    p.add_argument("--all", action="store_true", help="include entitled checks and non-decisions")
    p.add_argument("--service", help="filter, e.g. AppleEvents")
    p.add_argument("--client", help="filter by client bundle id")
    p.add_argument("--json", action="store_true", help="one JSON object per event")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("record", help="record permission decisions (foreground)")
    p.add_argument("--store-all", action="store_true", help="also store requests that decided nothing")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("log", help="timeline of recorded permission decisions")
    p.add_argument("--since", default="24h", help="how far back: 30m, 2h, 7d or all (default 24h)")
    p.add_argument("--client", help="filter: bundle id, path or name contains this")
    p.add_argument("--service", help="filter, e.g. AppleEvents, Camera")
    p.add_argument("--outcome", choices=sorted(OUTCOME_LABELS), help="filter by outcome")
    p.add_argument("--all", action="store_true", help="include Apple's entitled checks")
    p.add_argument("--limit", type=int, default=200, help="newest N (default 200)")
    p.add_argument("--json", action="store_true", help="one JSON object per event")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("why", help="explain why an app keeps being asked (or is refused)")
    p.add_argument("app", help="bundle id, name or path fragment, e.g. claude or com.apple.Terminal")
    p.add_argument("--since", default="30d", help="how far back: 2h, 7d or all (default 30d)")
    p.add_argument("--json", action="store_true", help="one JSON object per app + permission + target")
    p.set_defaults(func=cmd_why)

    p = sub.add_parser("inspect", help="show an app's signing identity and whether grants will stick")
    p.add_argument("target", help="path to an app or tool, or a bundle id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("status", help="is the recorder running and healthy?")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("install-agent", help="run the recorder in the background from login")
    p.add_argument("--dry-run", action="store_true", help="print the LaunchAgent plist, change nothing")
    p.set_defaults(func=cmd_install_agent)

    p = sub.add_parser("uninstall-agent", help="stop and remove the background recorder")
    p.set_defaults(func=cmd_uninstall_agent)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
