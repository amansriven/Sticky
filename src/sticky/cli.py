"""Command-line entry point.

Week 1 has one command, ``sticky parse``, for checking the parser against a
saved log. ``why``, ``log``, ``inspect``, ``fix`` and ``doctor`` arrive in
weeks 2-3 (see sticky-design.md).
"""

from __future__ import annotations

import argparse
import json
import sys

from .assembler import assemble
from .logsource import read_records


def _short(value: str | None, width: int) -> str:
    value = value or "-"
    return value if len(value) <= width else value[: width - 1] + "…"


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
        print(f"{'time':<12} {'scope':<6} {'service':<22} {'client':<28} {'target':<20} outcome")
        for e in shown:
            service = (e.service or "-").removeprefix("kTCCService")
            print(
                f"{e.ts_start[11:23]:<12} {e.tccd_scope or '-':<6} {_short(service, 22):<22} "
                f"{_short(e.client_id, 28):<28} {_short(e.target_id or e.target_name, 20):<20} "
                f"{e.outcome}"
            )

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sticky", description="Why does your Mac keep asking?")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="parse a saved permissions log and list decisions")
    p.add_argument("file")
    p.add_argument("--format", choices=["ndjson", "compact"], help="default: detect")
    p.add_argument("--all", action="store_true", help="include requests that decided nothing")
    p.add_argument("--service", help="filter, e.g. AppleEvents")
    p.add_argument("--client", help="filter by client bundle id")
    p.add_argument("--json", action="store_true", help="one JSON object per event")
    p.set_defaults(func=cmd_parse)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
