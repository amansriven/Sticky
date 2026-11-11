"""Read macOS unified-log output into uniform ``LogRecord`` objects.

Two input formats are supported:

* ``ndjson`` -- ``log stream --style ndjson``. This is what the collector uses
  in production. Each line carries ``threadID``, ``processID`` and
  ``formatString`` as separate fields.
* ``compact`` -- ``log stream --style compact``. This is what the original
  spike captured. Messages that span several lines continue on lines that
  start with a tab.

Both are normalised to the same record shape so the assembler doesn't care
where a line came from.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, Iterator

# Compact-style level codes -> the names ndjson uses in ``messageType``.
COMPACT_LEVELS = {
    "Df": "Default",
    "I": "Info",
    "Db": "Debug",
    "E": "Error",
    "F": "Fault",
    "A": "Activity",
}


@dataclass(slots=True)
class LogRecord:
    ts: str  # local time, "YYYY-MM-DD HH:MM:SS.mmm" (sorts as a string)
    process: str  # executable name, e.g. "tccd"
    pid: int
    tid: int  # thread id (compact prints it in hex, ndjson in decimal)
    level: str  # Default | Info | Debug | Error | Fault | Activity
    message: str
    fmt: str | None = None  # the developer's format string (ndjson only)


# 2026-11-11 04:14:14.554 I  tccd[14004:219b51] [com.apple.TCC:access] message
_COMPACT_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+"
    r"(?P<level>[A-Za-z]+)\s+"
    r"(?P<process>.+?)\[(?P<pid>\d+):(?P<tid>[0-9a-f]+)\]\s+"
    r"(?:\[[^\]\s]+\]\s)?"  # optional [subsystem:category]
    r"(?P<message>.*)$"
)


def _normalise_ts(ts: str) -> str:
    """Trim to millisecond precision and drop any timezone suffix."""
    return ts[:23]


def iter_compact(lines: Iterable[str]) -> Iterator[LogRecord]:
    current: LogRecord | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        m = _COMPACT_LINE.match(line)
        if m:
            if current is not None:
                yield current
            current = LogRecord(
                ts=_normalise_ts(m["ts"]),
                process=m["process"],
                pid=int(m["pid"]),
                tid=int(m["tid"], 16),
                level=COMPACT_LEVELS.get(m["level"], m["level"]),
                message=m["message"],
            )
        elif current is not None:
            # Continuation of a multi-line message.
            current.message += "\n" + line
        # Lines before the first record are headers ("Filtering the log
        # data…", "Timestamp  Ty Process[PID:TID]") and are skipped.
    if current is not None:
        yield current


def iter_ndjson(lines: Iterable[str]) -> Iterator[LogRecord]:
    for raw in lines:
        raw = raw.strip()
        if not raw.startswith("{"):
            continue  # "Filtering the log data using…" header
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("eventType") not in (None, "logEvent"):
            continue  # activity / signpost / state events
        yield LogRecord(
            ts=_normalise_ts(d.get("timestamp", "")),
            process=os.path.basename(d.get("processImagePath") or ""),
            pid=int(d.get("processID", -1)),
            tid=int(d.get("threadID", -1)),
            level=d.get("messageType", ""),
            message=d.get("eventMessage", ""),
            fmt=d.get("formatString"),
        )


def detect_format(first_lines: Iterable[str]) -> str:
    for line in first_lines:
        s = line.strip()
        if s.startswith("{"):
            return "ndjson"
        if _COMPACT_LINE.match(s):
            return "compact"
    return "compact"


def read_records(path: str, fmt: str | None = None) -> Iterator[LogRecord]:
    """Read a saved log file, detecting the format if not given."""
    with open(path, encoding="utf-8", errors="replace") as f:
        if fmt is None:
            head = [f.readline() for _ in range(5)]
            fmt = detect_format(head)
            f.seek(0)
        reader = iter_ndjson if fmt == "ndjson" else iter_compact
        yield from reader(f)
