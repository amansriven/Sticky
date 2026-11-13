"""`sticky report --json`: the contract the menu bar app reads."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from sticky import cli
from sticky.assembler import assemble
from sticky.logsource import read_records
from sticky.recorder import Recorder
from sticky.report import app_name, build_report
from sticky.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "s.db"
        self.store = Store(self.db)
        Recorder(self.store, command=["/bin/cat", str(FIXTURES / "ndjson-allowed-and-denied.ndjson")],
                 max_restarts=0, backoff=lambda n: 0, log=lambda m: None,
                 snapshot_identities=False).run()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def report(self):
        return build_report(self.store, since="all", agent_state=lambda: (True, False))

    def test_top_level_shape(self):
        r = self.report()
        self.assertEqual(set(r), {"sticky_version", "generated_at", "since", "recorder",
                                  "problems", "activity", "ignored", "apps"})
        json.dumps(r)  # serialisable

    def test_recorder_health(self):
        h = self.report()["recorder"]
        self.assertEqual(h["state"], "stopped")  # the replay run ended
        self.assertTrue(h["agent_installed"])
        self.assertFalse(h["agent_loaded"])
        self.assertEqual(h["records"], 330)

    def test_problem_for_remembered_denial(self):
        (p,) = self.report()["problems"]
        self.assertEqual((p["rule"], p["client_id"], p["target"], p["service_name"]),
                         ("R2", "com.anthropic.claude-code", "com.apple.Safari", "Automation"))
        self.assertEqual(p["label"], "Automation → com.apple.Safari")
        self.assertEqual([a["kind"] for a in p["actions"]], ["open_url", "copy"])
        self.assertTrue(p["key"].startswith("R2|com.anthropic.claude-code|kTCCServiceAppleEvents|"))

    def test_apps_and_permission_status(self):
        apps = {a["client_id"]: a for a in self.report()["apps"]}
        claude = apps["com.anthropic.claude-code"]
        self.assertEqual(claude["status"], "problem")
        statuses = {p["target"]: p["status"] for p in claude["permissions"]
                    if p["service"] == "kTCCServiceAppleEvents"}
        self.assertEqual(statuses, {"com.apple.Safari": "problem", "com.apple.finder": "ok"})
        # Problems are listed first.
        self.assertEqual(claude["permissions"][0]["status"], "problem")

    def test_activity_has_24_hourly_buckets(self):
        a = self.report()["activity"]
        self.assertEqual(len(a["hours"]), 24)
        self.assertEqual(set(a["totals"]), {"allowed", "denied", "asked", "apps"})
        self.assertTrue(all(h["hour"].endswith(":00") for h in a["hours"]))

    def test_activity_counts_recent_decisions(self):
        from sticky.report import activity
        from sticky.store import now_ts
        self.store.db.execute(
            "INSERT INTO events (ts_start, tccd_pid, tid, service, final_auth, prompted, preflight, "
            "entitled, client_id, client_path) VALUES "
            "(?, 9, 9, 'kTCCServiceCamera', 0, 0, 0, 0, 'com.x', '/Applications/X.app'), "
            "(?, 9, 8, 'kTCCServiceCamera', 2, 1, 0, 0, 'com.x', '/Applications/X.app'), "
            "(?, 9, 7, 'kTCCServiceSystemPolicyAllFiles', 0, 0, 0, 0, 'com.apple.dock', "
            "'/System/Library/CoreServices/Dock.app')", (now_ts(), now_ts(), now_ts()))
        a = activity(self.store)
        self.assertEqual(a["totals"], {"allowed": 0, "denied": 1, "asked": 1, "apps": 1})
        self.assertEqual(a["hours"][-1]["denied"], 1)
        self.assertEqual(activity(self.store, include_system=True)["totals"]["denied"], 2)

    def test_app_kind(self):
        from sticky.report import app_kind
        self.assertEqual(app_kind("com.apple.Music", "/System/Applications/Music.app", None), "system")
        self.assertEqual(app_kind("/usr/libexec/routined", None, None), "system")
        self.assertEqual(app_kind("com.apple.Xcode", "/Applications/Xcode.app", None), "app")
        self.assertEqual(app_kind("com.google.Chrome", "/Applications/Google Chrome.app", None), "app")
        self.assertEqual(app_kind("com.x", "/Applications/X.app", True), "system")

    def test_app_name(self):
        self.assertEqual(app_name("/usr/libexec/foo", None), "foo")
        self.assertEqual(app_name("com.example.Tool", "/nonexistent/Tool.app"), "Tool")
        self.assertEqual(app_name("com.example.Tool", None, "tool"), "tool")
        self.assertEqual(app_name("com.example.Tool", None), "Tool")

    def test_cli_outputs_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--db", str(self.db), "report", "--since", "all", "--compact"])
        r = json.loads(out.getvalue())
        self.assertEqual(len(r["problems"]), 1)


class EventsCommandTests(ReportTests):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", str(self.db), *argv])
        return code, json.loads(out.getvalue())

    def test_events_for_one_app_newest_first(self):
        code, r = self.run_cli("events", "com.anthropic.claude-code", "--since", "all", "--compact")
        self.assertEqual(code, 0)
        automation = [e for e in r["events"] if e["service"] == "kTCCServiceAppleEvents"]
        self.assertEqual([(e["target_id"], e["outcome"]) for e in automation],
                         [("com.apple.Safari", "denied"), ("com.apple.finder", "allowed")])
        e = automation[0]
        self.assertEqual(e["service_name"], "Automation")
        self.assertIs(e["prompted"], False)
        self.assertIsInstance(e["id"], int)
        times = [e["ts_start"] for e in r["events"]]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_exact_client_match_and_limit(self):
        _, r = self.run_cli("events", "claude", "--since", "all")
        self.assertEqual(r["events"], [])  # no substring matching
        _, r = self.run_cli("events", "com.anthropic.claude-code", "--since", "all", "--limit", "1")
        self.assertEqual(len(r["events"]), 1)


class PlatformFlagTests(unittest.TestCase):
    def test_platform_binary_flag_from_fixture(self):
        events, _ = assemble(read_records(str(FIXTURES / "compact-prompts-allowed.log")))
        flags = {}
        for e in events:
            if e.client_platform is not None:
                flags.setdefault(e.client_id, set()).add(e.client_platform)
        # Apple platform binaries...
        for apple in ("com.apple.Music", "/usr/libexec/milod", "/usr/libexec/routined"):
            self.assertEqual(flags[apple], {True}, apple)
        # ...and third-party apps (two anonymized as com.example.*).
        for other in ("com.anthropic.claude-code", "com.example.ChatApp", "com.example.Browser"):
            self.assertEqual(flags[other], {False}, other)


if __name__ == "__main__":
    unittest.main()
