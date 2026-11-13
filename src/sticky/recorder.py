"""The recorder: run ``log stream`` and store every permission decision.

Detailed permission lines expire from the system log within minutes, so
Sticky has to record them live. The recorder:

* starts ``/usr/bin/log stream --style ndjson`` filtered to the permissions
  service (no Full Disk Access or root needed);
* feeds each line to the ``Assembler`` and stores finished decisions in
  SQLite, updating a row if the target app's result line arrives later;
* restarts ``log stream`` with backoff if it exits (sleep, crashes);
* records a heartbeat, counters and unrecognised line templates for
  ``sticky status``;
* stops cleanly on SIGTERM / SIGINT (launchd sends SIGTERM).

Always call ``/usr/bin/log`` by its full path: zsh has a built-in ``log``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import timedelta
from typing import Callable, Sequence

from .assembler import Assembler, Event
from .logsource import iter_ndjson
from .store import Store, now_ts, ts_ago

PREDICATE = 'subsystem == "com.apple.TCC" AND category == "access"'
LOG_COMMAND = (
    "/usr/bin/log", "stream", "--info", "--debug", "--style", "ndjson",
    "--predicate", PREDICATE,
)

HEARTBEAT_SECONDS = 60
FIRST_HEARTBEAT_SECONDS = 5
# Close requests still open after this long. Longer than anyone leaves a
# permission prompt unanswered; short enough that memory stays flat.
OPEN_REQUEST_TIMEOUT = timedelta(minutes=15)
PURGE_EVERY_SECONDS = 24 * 3600
MAX_BACKOFF_SECONDS = 60


def worth_storing(ev: Event) -> bool:
    """Only decisions Sticky can diagnose are stored.

    Skipped: requests that decided nothing; entitlement shortcuts (they can
    never prompt or change); and decisions not attributable to any app. Over a
    24-hour run these were about 85% of all decisions.
    """
    return ev.is_decision and not ev.entitled and ev.client_id is not None


class Recorder:
    def __init__(
        self,
        store: Store,
        command: Sequence[str] = LOG_COMMAND,
        max_restarts: int | None = None,
        backoff: Callable[[int], float] | None = None,
        log: Callable[[str], None] | None = None,
        store_all: bool = False,
        snapshot_identities: bool = True,
    ) -> None:
        self.store = store
        self.command = list(command)
        self.max_restarts = max_restarts  # None = forever (production)
        self.backoff = backoff or (lambda n: min(MAX_BACKOFF_SECONDS, 2 ** min(n, 6)))
        self.log = log or (lambda msg: print(f"{now_ts()} {msg}", file=sys.stderr, flush=True))
        self.store_all = store_all  # also store requests that decided nothing
        self.snapshot_identities = snapshot_identities
        self._inspected: dict[str, float] = {}  # client path -> signature mtime when snapshotted
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self.run_id: int | None = None
        self.skipped = 0  # requests not stored: no decision, entitlement shortcuts, no app
        self.counts = {"records": 0, "requests": 0, "decisions": 0, "restarts": 0}
        self.last_record: str | None = None

    # Control --------------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.stop())

    # Main loop ------------------------------------------------------------------
    def run(self) -> int:
        self.run_id = self.store.start_run(os.getpid())
        purged = self.store.purge()
        pruned = self.store.prune_noise()
        self.log(f"recorder started (run {self.run_id}, db {self.store.path}, purged {purged} old "
                 f"events" + (f", removed {pruned} stored entitlement/unattributed rows" if pruned else "")
                 + ")")
        note = "stopped"
        failures = 0
        last_purge = time.monotonic()
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                code = self._stream_once()
                if self._stop.is_set():
                    break
                # A stream that ran a while is healthy: reset the backoff.
                failures = 0 if time.monotonic() - started > 300 else failures + 1
                if self.max_restarts is not None and self.counts["restarts"] >= self.max_restarts:
                    note = f"log stream exited ({code}); restart limit reached"
                    break
                delay = self.backoff(failures)
                self.counts["restarts"] += 1
                self.log(f"log stream exited with {code}; restarting in {delay:.0f}s")
                if self._stop.wait(delay):
                    break
                if time.monotonic() - last_purge > PURGE_EVERY_SECONDS:
                    self.store.purge()
                    last_purge = time.monotonic()
        finally:
            self._heartbeat(ended_at=now_ts(), note=note)
            self.log(f"recorder stopped: {self.counts}, not stored: {self.skipped}")
        return 0

    def _stream_once(self) -> int | None:
        asm = Assembler(on_client_result=self._update_row)
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as e:
            self.log(f"could not start {self.command[0]}: {e}")
            return None

        # First heartbeat soon after start, so `sticky status` isn't stale for a minute.
        next_beat = time.monotonic() + FIRST_HEARTBEAT_SECONDS
        try:
            for rec in iter_ndjson(self._proc.stdout):
                self.counts["records"] += 1
                self.last_record = rec.ts
                for ev in asm.feed(rec):
                    self._save(ev)
                if time.monotonic() >= next_beat:
                    for ev in asm.expire(ts_ago(OPEN_REQUEST_TIMEOUT)):
                        self._save(ev)
                    self._flush_health(asm)
                    next_beat = time.monotonic() + HEARTBEAT_SECONDS
                if self._stop.is_set():
                    break
        finally:
            for ev in asm.flush():
                self._save(ev)
            self._flush_health(asm)
            if self._proc.poll() is None:
                self._proc.terminate()
            try:
                code = self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                code = self._proc.wait()
            self._proc.stdout.close()
        return code

    # Storage --------------------------------------------------------------------
    def _save(self, ev: Event) -> None:
        self.counts["requests"] += 1
        if not self.store_all and not worth_storing(ev):
            self.skipped += 1
            return
        row = self.store.insert_event(ev, self.run_id)
        if row is not None:
            self.counts["decisions"] += 1
            ev._row_id = row
            self._heartbeat()  # keep `sticky status` current; decisions are rare
            self._snapshot(ev)

    def _snapshot(self, ev: Event) -> None:
        """Record the signing identity of each app build the first time it's seen.

        Runs ``codesign`` (tens of ms) once per path, and again whenever the
        app's signature file changes (a rebuild or update in place).
        """
        path = ev.client_path
        if not self.snapshot_identities or not path or ev.entitled:
            return
        from .identity import inspect, signature_mtime

        mtime = signature_mtime(path)
        if self._inspected.get(path) == mtime:
            return
        self._inspected[path] = mtime
        try:
            self.store.upsert_identity(inspect(path), ev.client_id)
        except Exception as e:  # never let a snapshot stop recording
            self.log(f"identity snapshot failed for {path}: {e}")

    def _update_row(self, ev: Event) -> None:
        # The target app's result line arrived after the event was stored.
        if ev._row_id is not None:
            self.store.update_client_result(ev._row_id, ev)

    def _flush_health(self, asm: Assembler) -> None:
        if asm.unrecognised:
            self.store.add_unrecognised(dict(asm.unrecognised))
            asm.unrecognised.clear()
        self._heartbeat()

    def _heartbeat(self, **extra) -> None:
        if self.run_id is None:
            return
        self.store.update_run(
            self.run_id,
            heartbeat=now_ts(),
            last_record=self.last_record,
            **self.counts,
            **extra,
        )
