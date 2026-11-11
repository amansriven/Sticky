"""SQLite storage for permission events.

One database per user, by default at
``~/Library/Application Support/Sticky/sticky.db`` (override with the
``STICKY_DB`` environment variable or ``--db``). WAL mode lets the recorder
write while ``sticky log`` reads.

Timestamps are local wall-clock strings, ``YYYY-MM-DD HH:MM:SS.mmm``, as the
log prints them. They sort and compare correctly as strings.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .assembler import Event

SCHEMA_VERSION = 1
DEFAULT_RETENTION_DAYS = 30
TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

# Event fields stored as columns, in order. Booleans are stored as 0/1.
EVENT_COLUMNS = (
    "ts_start", "ts_end", "tccd_pid", "tid", "msg_id", "tccd_scope", "function",
    "ended_by", "forwarded", "service", "preflight",
    "client_id", "client_type", "client_path", "client_version", "client_dr",
    "responsible_id", "responsible_path", "requesting_id", "accessing_id",
    "target_id", "target_name", "client_name",
    "auth_before", "auth_result", "prompted", "auth_after", "client_result",
    "requirements_match", "usage_string", "policy_allowed", "entitled",
    "final_auth", "outcome", "stored_dr", "stored_dr_status",
)
TEXT_COLUMNS = {
    "ts_start", "ts_end", "msg_id", "tccd_scope", "function", "ended_by", "service",
    "client_id", "client_path", "client_version", "client_dr", "responsible_id",
    "responsible_path", "requesting_id", "accessing_id", "target_id", "target_name",
    "client_name", "outcome", "stored_dr",
}
_EVENT_COLUMN_DEFS = ",\n    ".join(
    f"{c} {'TEXT' if c in TEXT_COLUMNS else 'INTEGER'}" for c in EVENT_COLUMNS
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    pid         INTEGER,
    heartbeat   TEXT,          -- updated about once a minute while running
    last_record TEXT,          -- timestamp of the newest log line seen
    records     INTEGER DEFAULT 0,
    requests    INTEGER DEFAULT 0,
    decisions   INTEGER DEFAULT 0,
    restarts    INTEGER DEFAULT 0,
    note        TEXT           -- why the run ended
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    run_id  INTEGER REFERENCES runs(id),
    {_EVENT_COLUMN_DEFS},
    UNIQUE (tccd_pid, tid, ts_start)
);

CREATE TABLE IF NOT EXISTS identities (     -- one row per distinct build seen
    id          INTEGER PRIMARY KEY,
    client_id   TEXT,
    code_path   TEXT NOT NULL,
    version     TEXT,
    sign_kind   TEXT,
    team_id     TEXT,
    dr          TEXT,                      -- designated requirement
    dr_kind     TEXT,                      -- team | apple | cdhash | path | other
    cdhash      TEXT,
    usage_keys  TEXT,                      -- JSON list of NS*UsageDescription keys
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    UNIQUE (code_path, cdhash)
);

CREATE TABLE IF NOT EXISTS unrecognised (
    template TEXT PRIMARY KEY,  -- formatString (ndjson) or message prefix
    count    INTEGER NOT NULL,
    first_seen TEXT, last_seen TEXT
);
"""


# Created after migrations, since they may name columns older databases lack.
_INDEXES = """
CREATE INDEX IF NOT EXISTS events_ts ON events (ts_start);
CREATE INDEX IF NOT EXISTS events_key ON events (client_id, service, target_id, ts_start);
CREATE INDEX IF NOT EXISTS identities_client ON identities (client_id, first_seen);
"""


def default_db_path() -> Path:
    env = os.environ.get("STICKY_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Library" / "Application Support" / "Sticky" / "sticky.db"


def now_ts() -> str:
    return datetime.now().strftime(TS_FORMAT)[:23]


def ts_ago(delta: timedelta) -> str:
    return (datetime.now() - delta).strftime(TS_FORMAT)[:23]


def parse_duration(text: str) -> timedelta:
    """'90s', '30m', '2h', '7d' or '1w' -> timedelta."""
    text = text.strip().lower()
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    if len(text) < 2 or text[-1] not in units or not text[:-1].isdigit():
        raise ValueError(f"expected a duration like 30m, 2h or 7d, got {text!r}")
    return timedelta(**{units[text[-1]]: int(text[:-1])})


class Store:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection, used by one caller at a time; check_same_thread=False
        # only lets the recorder be stopped from a signal handler or thread.
        self.db = sqlite3.connect(
            str(self.path), timeout=10, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        self._add_missing_columns()
        self.db.executescript(_INDEXES)
        self.db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def _add_missing_columns(self) -> None:
        """Migrate databases created by older versions: add new event columns."""
        have = {row[1] for row in self.db.execute("PRAGMA table_info(events)")}
        for col in EVENT_COLUMNS:
            if col not in have:
                kind = "TEXT" if col in TEXT_COLUMNS else "INTEGER"
                self.db.execute(f"ALTER TABLE events ADD COLUMN {col} {kind}")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # Runs ---------------------------------------------------------------------
    def start_run(self, pid: int) -> int:
        ts = now_ts()
        cur = self.db.execute(
            "INSERT INTO runs (started_at, pid, heartbeat) VALUES (?, ?, ?)", (ts, pid, ts)
        )
        return int(cur.lastrowid)

    def update_run(self, run_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))

    def latest_run(self) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()

    # Events -------------------------------------------------------------------
    def insert_event(self, ev: Event, run_id: int | None = None) -> int | None:
        """Store one event. Returns its row id, or None if it was a duplicate."""
        d = ev.to_dict()
        values = [_to_sql(d.get(c)) for c in EVENT_COLUMNS]
        cur = self.db.execute(
            f"INSERT OR IGNORE INTO events (run_id, {', '.join(EVENT_COLUMNS)}) "
            f"VALUES (?, {', '.join('?' * len(EVENT_COLUMNS))})",
            (run_id, *values),
        )
        return int(cur.lastrowid) if cur.rowcount else None

    def update_client_result(self, row_id: int, ev: Event) -> None:
        self.db.execute(
            "UPDATE events SET client_result = ?, final_auth = ?, outcome = ? WHERE id = ?",
            (ev.client_result, ev.final_auth, ev.outcome, row_id),
        )

    def query_events(
        self,
        since: str | None = None,
        client: str | None = None,
        service: str | None = None,
        outcome: str | None = None,
        include_entitled: bool = False,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        where, args = [], []
        if since:
            where.append("ts_start >= ?")
            args.append(since)
        if client:
            where.append("(client_id LIKE ? OR client_path LIKE ? OR client_name LIKE ?)")
            args += [f"%{client}%"] * 3
        if service:
            where.append("service LIKE ?")
            args.append(f"%{service}%")
        if outcome:
            where.append("outcome = ?")
            args.append(outcome)
        if not include_entitled:
            where.append("entitled = 0")
        sql = "SELECT * FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts_start DESC, id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.db.execute(sql, args).fetchall()
        rows.reverse()  # oldest first for display
        return rows

    def count_events(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    # Identities -----------------------------------------------------------------
    def upsert_identity(self, ident, client_id: str | None = None) -> None:
        """Record one build of an app (an ``identity.Identity``)."""
        import json

        if not ident.exists:
            return
        ts = now_ts()
        self.db.execute(
            "INSERT INTO identities (client_id, code_path, version, sign_kind, team_id, dr, dr_kind, "
            "cdhash, usage_keys, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(code_path, cdhash) DO UPDATE SET last_seen = excluded.last_seen, "
            "client_id = COALESCE(excluded.client_id, client_id)",
            (client_id or ident.identifier, ident.code_path, ident.version, ident.sign_kind,
             ident.team_id, ident.designated_requirement, ident.dr_kind, ident.cdhash or "",
             json.dumps(sorted(ident.usage_keys)), ts, ts),
        )

    def identities_for(self, client_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM identities WHERE client_id = ? ORDER BY first_seen", (client_id,)
        ).fetchall()

    def latest_path_for(self, client_id: str) -> str | None:
        row = self.db.execute(
            "SELECT client_path FROM events WHERE client_id = ? AND client_path IS NOT NULL "
            "ORDER BY ts_start DESC LIMIT 1", (client_id,)
        ).fetchone()
        return row[0] if row else None

    def first_run_started(self) -> str | None:
        row = self.db.execute("SELECT MIN(started_at) FROM runs").fetchone()
        return row[0] if row else None

    # Health -------------------------------------------------------------------
    def add_unrecognised(self, counts: dict[str, int]) -> None:
        ts = now_ts()
        self.db.executemany(
            "INSERT INTO unrecognised (template, count, first_seen, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(template) DO UPDATE SET count = count + excluded.count, last_seen = excluded.last_seen",
            [(t, n, ts, ts) for t, n in counts.items()],
        )

    def top_unrecognised(self, n: int = 5) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT template, count FROM unrecognised ORDER BY count DESC LIMIT ?", (n,)
        ).fetchall()

    # Retention ----------------------------------------------------------------
    def purge(self, days: int = DEFAULT_RETENTION_DAYS) -> int:
        cutoff = ts_ago(timedelta(days=days))
        cur = self.db.execute("DELETE FROM events WHERE ts_start < ?", (cutoff,))
        self.db.execute("DELETE FROM runs WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,))
        return cur.rowcount


def _to_sql(value):
    if isinstance(value, bool):
        return int(value)
    return value


def iter_dicts(rows) -> Iterator[dict]:
    for r in rows:
        yield dict(r)
