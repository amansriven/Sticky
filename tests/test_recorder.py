"""Week 2: store, recorder, agent and `sticky log`.

The recorder is tested by replaying a recorded ndjson log through ``cat``
in place of ``/usr/bin/log stream``, so these tests don't touch the live
system log or launchd.
"""

import contextlib
import io
import plistlib
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path
from subprocess import CompletedProcess

from sticky import agent, cli
from sticky.assembler import Assembler
from sticky.logsource import LogRecord
from sticky.recorder import Recorder
from sticky.store import Store, parse_duration, ts_ago

FIXTURES = Path(__file__).parent / "fixtures"
NDJSON = FIXTURES / "ndjson-allowed-and-denied.ndjson"
QUIET = lambda msg: None  # noqa: E731


class TempDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "sticky.db"
        self.store = Store(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def replay(self, path=NDJSON, **kw):
        rec = Recorder(self.store, command=["/bin/cat", str(path)], max_restarts=0,
                       backoff=lambda n: 0, log=QUIET, **kw)
        rec.run()
        return rec

    def automation_rows(self):
        return [
            dict(r) for r in self.store.query_events(service="AppleEvents", client="claude-code")
        ]


class RecorderTests(TempDB):
    def test_replay_stores_decisions_with_late_client_results(self):
        rec = self.replay()
        rows = self.automation_rows()
        self.assertEqual(
            [(r["target_id"], r["outcome"], r["auth_before"], r["client_result"]) for r in rows],
            [("com.apple.finder", "allowed", 2, 1), ("com.apple.Safari", "denied", 0, 0)],
        )
        self.assertEqual(rec.counts["records"], 330)
        self.assertEqual(rec.counts["requests"], 10)

    def test_client_result_arrives_after_row_is_written(self):
        # The target app logs its result line after tccd's REPLY, so the row
        # is inserted first and updated afterwards. Prove that path ran.
        updates = []
        original = self.store.update_client_result
        self.store.update_client_result = lambda row, ev: (updates.append(row), original(row, ev))
        self.replay()
        self.assertEqual(len(updates), 2)

    def test_replaying_the_same_log_twice_does_not_duplicate(self):
        self.replay()
        first = self.store.count_events()
        self.replay()
        self.assertEqual(self.store.count_events(), first)

    def test_run_row_records_counters_and_reason(self):
        self.replay()
        run = self.store.latest_run()
        self.assertIsNotNone(run["ended_at"])
        self.assertEqual(run["records"], 330)
        self.assertIn("restart limit", run["note"])
        self.assertEqual(run["last_record"][:16], "2026-11-11 04:40")

    def test_restarts_log_stream_when_it_exits(self):
        rec = Recorder(self.store, command=["/usr/bin/true"], max_restarts=3,
                       backoff=lambda n: 0, log=QUIET)
        rec.run()
        self.assertEqual(rec.counts["restarts"], 3)
        self.assertEqual(self.store.latest_run()["restarts"], 3)

    def test_backoff_grows_and_caps(self):
        delays = []
        rec = Recorder(self.store, command=["/usr/bin/true"], max_restarts=8,
                       backoff=None, log=QUIET)
        rec._stop.wait = lambda d: (delays.append(d), False)[1]  # don't actually sleep
        rec.run()
        self.assertEqual(delays, [2, 4, 8, 16, 32, 60, 60, 60])

    def test_stop_ends_a_running_stream_promptly(self):
        rec = Recorder(self.store, command=["/bin/sleep", "30"], log=QUIET)
        t = threading.Thread(target=rec.run)
        t.start()
        time.sleep(0.3)
        started = time.monotonic()
        rec.stop()
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.store.latest_run()["note"], "stopped")

    def test_missing_command_is_retried_not_fatal(self):
        rec = Recorder(self.store, command=["/nonexistent/log"], max_restarts=1,
                       backoff=lambda n: 0, log=QUIET)
        rec.run()
        self.assertEqual(rec.counts["restarts"], 1)

    def test_unrecognised_templates_are_counted(self):
        self.replay()
        top = self.store.top_unrecognised()
        self.assertTrue(top)
        self.assertGreater(top[0]["count"], 0)


class StoreTests(TempDB):
    def test_parse_duration(self):
        self.assertEqual(parse_duration("90s"), timedelta(seconds=90))
        self.assertEqual(parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(parse_duration("1w"), timedelta(weeks=1))
        for bad in ("", "h", "2x", "-1h", "1.5h"):
            with self.assertRaises(ValueError):
                parse_duration(bad)

    def test_filters(self):
        self.replay()
        self.assertEqual(len(self.store.query_events(outcome="denied", service="AppleEvents")), 1)
        self.assertEqual(len(self.store.query_events(client="ChatApp")), 0)
        self.assertTrue(self.store.query_events(since="2026-11-11 04:40:25"))
        self.assertFalse(self.store.query_events(since="2099-01-01 00:00:00"))
        everything = self.store.query_events(include_entitled=True)
        self.assertGreaterEqual(len(everything), len(self.store.query_events()))

    def test_limit_keeps_newest_but_prints_oldest_first(self):
        self.replay()
        rows = self.store.query_events(limit=2)
        self.assertEqual(len(rows), 2)
        self.assertLessEqual(rows[0]["ts_start"], rows[1]["ts_start"])
        newest = self.store.query_events()[-1]["ts_start"]
        self.assertEqual(rows[-1]["ts_start"], newest)

    def test_old_database_gets_new_columns(self):
        import sqlite3

        old = Path(self.tmp.name) / "old.db"
        db = sqlite3.connect(old)
        db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, run_id INTEGER, ts_start TEXT, "
                   "tccd_pid INTEGER, tid INTEGER, UNIQUE (tccd_pid, tid, ts_start))")
        db.close()
        with Store(old) as store:
            cols = {r[1] for r in store.db.execute("PRAGMA table_info(events)")}
        self.assertIn("stored_dr", cols)
        self.assertIn("stored_dr_status", cols)

    def test_purge_removes_old_events(self):
        self.replay()  # fixture events are from 2026-11-11
        old = ts_ago(timedelta(days=45))[:20]  # "YYYY-MM-DD HH:MM:SS."
        self.store.db.execute("UPDATE events SET ts_start = ? || printf('%03d', id)", (old,))
        removed = self.store.purge(days=30)
        self.assertGreater(removed, 0)
        self.assertEqual(self.store.count_events(), 0)


class ExpireTests(unittest.TestCase):
    def test_expire_closes_stale_open_requests(self):
        asm = Assembler()
        asm.feed(LogRecord("2026-01-01 00:00:00.000", "tccd", 1, 9, "Default",
                           "REQUEST: tccd_uid=501, sender_pid=5, sender_uid=501, sender_auid=501, "
                           "function=TCCAccessRequestIndirect, msgID=5.1"))
        self.assertEqual(asm.expire("2025-12-31 00:00:00.000"), [])
        (ev,) = asm.expire("2026-01-01 00:20:00.000")
        self.assertEqual(ev.ended_by, "timeout")
        self.assertEqual(asm.flush(), [])
        self.assertEqual(asm._awaiting_result, {})


class FakeLaunchctl:
    def __init__(self, loaded=False):
        self.loaded = loaded
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd[1])
        if cmd[1] == "print":
            return CompletedProcess(cmd, 0 if self.loaded else 113, "", "")
        if cmd[1] == "bootstrap":
            self.loaded = True
        if cmd[1] == "bootout":
            self.loaded = False
        return CompletedProcess(cmd, 0, "", "")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plist_runs_recorder_in_background(self):
        p = agent.build_plist(python="/usr/bin/python3", db_path="/x.db", home=self.home)
        self.assertEqual(p["Label"], agent.LABEL)
        self.assertEqual(p["ProgramArguments"], ["/usr/bin/python3", "-m", "sticky", "record"])
        self.assertTrue(p["RunAtLoad"] and p["KeepAlive"])
        self.assertEqual(p["ProcessType"], "Background")
        self.assertEqual(p["EnvironmentVariables"]["STICKY_DB"], "/x.db")
        self.assertTrue(p["StandardErrorPath"].startswith(str(self.home)))

    def test_install_writes_plist_and_bootstraps(self):
        fake = FakeLaunchctl()
        path = agent.install(python="/usr/bin/python3", home=self.home, run=fake)
        self.assertTrue(path.exists())
        with open(path, "rb") as f:
            self.assertEqual(plistlib.load(f)["Label"], agent.LABEL)
        self.assertEqual(fake.calls, ["print", "bootstrap"])

    def test_reinstall_boots_out_first(self):
        fake = FakeLaunchctl(loaded=True)
        agent.install(python="/usr/bin/python3", home=self.home, run=fake)
        self.assertEqual(fake.calls, ["print", "bootout", "bootstrap"])

    def test_uninstall_removes_everything(self):
        fake = FakeLaunchctl()
        path = agent.install(python="/usr/bin/python3", home=self.home, run=fake)
        self.assertTrue(agent.uninstall(home=self.home, run=fake))
        self.assertFalse(path.exists())
        self.assertFalse(fake.loaded)
        self.assertFalse(agent.uninstall(home=self.home, run=fake))

    def test_failed_bootstrap_raises(self):
        def failing(cmd):
            code = 113 if cmd[1] == "print" else 5
            return CompletedProcess(cmd, code, "", "Bootstrap failed: 5: Input/output error")
        with self.assertRaises(RuntimeError):
            agent.install(python="/usr/bin/python3", home=self.home, run=failing)


class LogCommandTests(TempDB):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", str(self.db_path), *argv])
        return code, out.getvalue()

    def test_log_shows_recorded_decisions(self):
        self.replay()
        code, out = self.run_cli("log", "--since", "all", "--service", "AppleEvents")
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 3)  # header + Finder + Safari
        self.assertIn("com.apple.finder", lines[1])
        self.assertTrue(lines[1].rstrip().endswith("allowed"))
        self.assertIn("com.apple.Safari", lines[2])
        self.assertTrue(lines[2].rstrip().endswith("DENIED"))

    def test_log_json(self):
        self.replay()
        _, out = self.run_cli("log", "--since", "all", "--outcome", "denied", "--json")
        self.assertIn('"target_id": "com.apple.Safari"', out)

    def test_log_empty_and_bad_duration(self):
        _, out = self.run_cli("log", "--since", "1h")
        self.assertIn("No permission decisions recorded in the last 1h", out)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self.run_cli("log", "--since", "soon")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
