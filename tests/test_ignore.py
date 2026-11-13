"""Ignoring findings: once, always for an app + permission, or a whole app."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from sticky import cli
from sticky.recorder import Recorder
from sticky.report import build_report
from sticky.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = "com.anthropic.claude-code"


class IgnoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "s.db"
        self.store = Store(self.db)
        # Replay: Finder allowed, Safari remembered denial (one R2 problem).
        Recorder(self.store, command=["/bin/cat", str(FIXTURES / "ndjson-allowed-and-denied.ndjson")],
                 max_restarts=0, backoff=lambda n: 0, log=lambda m: None, snapshot_identities=False).run()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def report(self):
        return build_report(self.store, since="all", agent_state=lambda: (True, True))

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--db", str(self.db), *argv])
        return code, out.getvalue()

    def safari_problem(self):
        (p,) = self.report()["problems"]
        return p

    def test_ignore_one_finding(self):
        key = self.safari_problem()["key"]
        ig = self.store.add_ignore("finding", CLAUDE, "kTCCServiceAppleEvents", "com.apple.Safari", key)
        r = self.report()
        self.assertEqual(r["problems"], [])
        (rule,) = r["ignored"]
        app = next(a for a in r["apps"] if a["client_id"] == CLAUDE)
        self.assertEqual((rule["id"], rule["scope"], rule["hiding"], rule["app_name"]),
                         (ig, "finding", 1, app["app_name"]))
        # The app no longer shows as having a problem, and the finding says why.
        self.assertEqual(app["status"], "ok")
        safari = next(p for p in app["permissions"] if p["target"] == "com.apple.Safari")
        self.assertEqual(safari["findings"][0]["ignored_by"], ig)

    def test_ignore_permission_and_app_scopes(self):
        ig = self.store.add_ignore("permission", CLAUDE, "kTCCServiceAppleEvents", "com.apple.Safari")
        self.assertEqual(self.report()["problems"], [])
        self.assertTrue(self.store.remove_ignore(ig))
        self.assertEqual(len(self.report()["problems"]), 1)
        # A different target doesn't match.
        self.store.add_ignore("permission", CLAUDE, "kTCCServiceAppleEvents", "com.apple.finder")
        self.assertEqual(len(self.report()["problems"]), 1)
        self.store.add_ignore("app", CLAUDE)
        self.assertEqual(self.report()["problems"], [])

    def test_add_ignore_is_idempotent_and_validated(self):
        a = self.store.add_ignore("app", CLAUDE)
        self.assertEqual(self.store.add_ignore("app", CLAUDE), a)
        with self.assertRaises(ValueError):
            self.store.add_ignore("everything", CLAUDE)
        self.assertFalse(self.store.remove_ignore(9999))

    def test_cli_round_trip(self):
        key = self.safari_problem()["key"]
        code, out = self.cli("ignore", key)
        self.assertEqual(code, 0)
        self.assertIn("Undo with: sticky unignore", out)
        _, why = self.cli("why", "claude", "--since", "all")
        self.assertNotIn("Denied: requests are refused silently", why)
        self.assertIn("1 ignored finding hidden", why)
        _, why_all = self.cli("why", "claude", "--since", "all", "--include-ignored")
        self.assertIn("Denied: requests are refused silently", why_all)
        _, listing = self.cli("ignores")
        rule_id = int(listing.split()[0])
        code, out = self.cli("unignore", str(rule_id))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.report()["problems"]), 1)

    def test_cli_ignore_permission_by_friendly_service(self):
        code, out = self.cli("ignore", "--app", CLAUDE, "--service", "AppleEvents", "--target", "com.apple.Safari")
        self.assertEqual(code, 0)
        self.assertEqual(self.report()["problems"], [])
        self.assertEqual(self.store.list_ignores()[0]["service"], "kTCCServiceAppleEvents")

    def test_cli_rejects_bad_input(self):
        self.assertEqual(self.cli("ignore", "not-a-key")[0], 2)
        self.assertEqual(self.cli("ignore")[0], 2)


if __name__ == "__main__":
    unittest.main()
