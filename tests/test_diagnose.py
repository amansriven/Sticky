"""Week 3: identity inspection, diagnosis rules and `sticky why` / `inspect`."""

import contextlib
import io
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from sticky import cli
from sticky.diagnose import diagnose, group_events, settings_url, tccutil_command
from sticky.identity import code_path_for, inspect, parse_codesign_details, parse_requirement, Identity
from sticky.recorder import Recorder
from sticky.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = "com.anthropic.claude-code"
TEAM_DR = ('identifier "com.anthropic.claude-code" and anchor apple generic and certificate '
           'leaf[subject.OU] = Q6L2SF6YDW')


def ev(ts, outcome, *, client=CLAUDE, service="kTCCServiceAppleEvents", target="com.apple.finder",
       dr=None, path="/Apps/Tool.app", client_type=0, requesting=None, preflight=False,
       entitled=False):
    """A minimal stored event. ``outcome`` is one of the Event.outcome values."""
    prompted = outcome.startswith("prompted")
    final = {"allowed": 2, "denied": 0, "undetermined": 1, "prompted-allowed": 2,
             "prompted-denied": 0}[outcome]
    return {
        "ts_start": f"2026-11-11 {ts}.000", "outcome": outcome, "client_id": client,
        "service": service, "target_id": target, "target_name": None, "client_dr": dr,
        "client_path": path, "client_type": client_type, "requesting_id": requesting,
        "accessing_id": None, "prompted": int(prompted), "final_auth": final,
        "auth_before": 1 if prompted else final, "requirements_match": int(final == 2 and not prompted),
        "preflight": int(preflight), "entitled": int(entitled),
    }


def rules(events):
    return [f.rule for _, findings in diagnose(events) for f in findings]


class RuleTests(unittest.TestCase):
    def test_allowed_and_matching_is_ok(self):
        events = [ev("10:00:00", "prompted-allowed", dr=TEAM_DR), ev("10:05:00", "allowed")]
        ((g, (f,)),) = diagnose(events)
        self.assertEqual(f.rule, "OK")
        self.assertIn("matched on 1 of 2", f.detail[0])

    def test_r1b_signing_identity_changed(self):
        events = [
            ev("10:00:00", "prompted-allowed", dr='cdhash H"aaaa"'),
            ev("10:01:00", "allowed"),
            ev("10:30:00", "prompted-allowed", dr='cdhash H"bbbb"'),
        ]
        ((g, findings),) = diagnose(events)
        (f,) = [f for f in findings if f.rule == "R1b"]
        self.assertIn('cdhash H"aaaa"', "\n".join(f.detail))
        self.assertIn('cdhash H"bbbb"', "\n".join(f.detail))
        self.assertIn("ad-hoc", " ".join(f.detail))
        self.assertTrue(any("codesign -s" in x for x in f.fix))

    def test_r1a_path_identity_moved(self):
        events = [
            ev("10:00:00", "prompted-allowed", path="/opt/tool-1/tool", client="/opt/tool", client_type=1),
            ev("11:00:00", "prompted-allowed", path="/opt/tool-2/tool", client="/opt/tool", client_type=1),
        ]
        self.assertIn("R1a", rules(events))

    def test_path_change_with_stable_identity_is_not_r1a(self):
        events = [
            ev("10:00:00", "prompted-allowed", dr=TEAM_DR, path="/a/1/claude.app"),
            ev("11:00:00", "prompted-allowed", dr=TEAM_DR, path="/a/2/claude.app"),
        ]
        self.assertEqual(rules(events), ["R1d"])

    def test_r1d_reset_externally(self):
        events = [
            ev("10:00:00", "prompted-allowed", dr=TEAM_DR),
            ev("12:00:00", "prompted-allowed", dr=TEAM_DR),
        ]
        self.assertEqual(rules(events), ["R1d"])

    def test_r1c_blamed_on_a_different_app(self):
        events = [
            ev("10:00:00", "prompted-allowed", client="com.apple.Terminal", requesting="com.example.cli"),
            ev("11:00:00", "prompted-allowed", client="com.googlecode.iterm2", requesting="com.example.cli"),
        ]
        results = dict((g.client_id, [f.rule for f in fs]) for g, fs in diagnose(events))
        self.assertIn("R1c", results["com.googlecode.iterm2"])
        self.assertNotIn("R1c", results["com.apple.Terminal"])

    def test_r2_denied_then_refused_silently(self):
        events = [ev("04:16:05", "prompted-denied"), ev("04:16:15", "denied")]
        ((g, (f,)),) = diagnose(events)
        self.assertEqual(f.rule, "R2")
        self.assertIn("11-11 04:16", f.detail[0])
        self.assertIn("1 request since was refused", f.detail[1])
        self.assertTrue(f.fix[0].endswith('?Privacy_Automation"'))
        self.assertIn("tccutil reset AppleEvents com.anthropic.claude-code", f.fix[1])

    def test_r2_denied_before_recording(self):
        ((g, (f,)),) = diagnose([ev("09:00:00", "denied"), ev("09:05:00", "denied")])
        self.assertEqual(f.rule, "R2")
        self.assertIn("before Sticky started recording", f.detail[0])

    def test_r4_prompt_storm(self):
        events = [ev(f"1{i}:00:00", "prompted-allowed", dr=f'cdhash H"{i}"') for i in range(3)]
        self.assertEqual(sorted(rules(events)), ["R1b", "R1b", "R4"])

    def test_preflight_and_entitled_checks_are_ignored(self):
        events = [ev("10:00:00", "undetermined", preflight=True),
                  ev("10:00:01", "allowed", entitled=True)]
        self.assertEqual(group_events(events), [])

    def test_developer_tool_checks_are_ignored(self):
        # syspolicyd checks Developer Tools on every launch; "deny" is the default.
        events = [ev("10:00:00", "denied", service="kTCCServiceDeveloperTool", target=None)]
        self.assertEqual(rules(events), [])

    def test_r5_kept_grant_after_rebuild(self):
        # Mirrors the week 3 BrokenTool run on macOS 27.2.1.
        v1, v2 = 'cdhash H"90e03ff5"', 'cdhash H"7289ee52"'
        events = [
            ev("05:16:35", "prompted-allowed", dr=v1),
            ev("05:16:42", "allowed"),                       # v1 again: grant matched
            dict(ev("05:16:54", "allowed"), requirements_match=0),  # v2: no match line
        ]
        builds = {CLAUDE: [{"dr": v1, "first_seen": "2026-11-11 05:16:35.000"},
                           {"dr": v2, "first_seen": "2026-11-11 05:18:38.000"}]}
        ((g, findings),) = diagnose(events, builds)
        self.assertEqual([f.rule for f in findings], ["R5", "OK"])
        self.assertIn(v1, findings[0].detail[0])
        self.assertIn(v2, findings[0].detail[1])

    def test_r5_needs_a_different_current_build(self):
        v1 = 'cdhash H"90e03ff5"'
        events = [ev("05:16:35", "prompted-allowed", dr=v1),
                  dict(ev("05:16:54", "allowed"), requirements_match=0)]
        same = {CLAUDE: [{"dr": v1, "first_seen": "2026-11-11 05:16:35.000"}]}
        self.assertEqual(rules(events), ["OK"])  # no build history at all
        self.assertEqual([f.rule for _, fs in diagnose(events, same) for f in fs], ["OK"])

    def test_fix_helpers(self):
        self.assertEqual(settings_url("kTCCServiceCamera"),
                         "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera")
        self.assertIsNone(tccutil_command("kTCCServiceCamera", "/usr/local/bin/tool"))


class FixtureDiagnosisTests(unittest.TestCase):
    def replay(self, name):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / "s.db")
        self.addCleanup(store.close)
        Recorder(store, command=["/bin/cat", str(FIXTURES / name)], max_restarts=0,
                 backoff=lambda n: 0, log=lambda m: None, snapshot_identities=False).run()
        return store

    def test_recorded_denial_is_r2(self):
        # The recorder reads ndjson, so replay the ndjson fixture.
        store = self.replay("ndjson-allowed-and-denied.ndjson")
        found = {(g.target, f.rule) for g, fs in diagnose(store.query_events(client="claude"))
                 for f in fs}
        self.assertEqual(found, {("com.apple.finder", "OK"), ("com.apple.Safari", "R2")})


class IdentityParsingTests(unittest.TestCase):
    DEV_ID = """Executable=/x/claude.app/Contents/MacOS/claude
Identifier=com.anthropic.claude-code
CodeDirectory v=20500 size=631301 flags=0x10000(runtime) hashes=19717+7 location=embedded
CDHash=2c9b480e0613f2f17027cfc4fcaa54c1a86ca49a
Authority=Developer ID Application: Anthropic PBC (Q6L2SF6YDW)
Authority=Developer ID Certification Authority
Authority=Apple Root CA
Notarization Ticket=stapled
TeamIdentifier=Q6L2SF6YDW
"""
    ADHOC = """Identifier=dev.sticky.test
CodeDirectory v=20400 size=232 flags=0x20002(adhoc,linker-signed) hashes=2+2 location=embedded
CDHash=af084b77a154f9d454095d2be392073219482d28
Signature=adhoc
TeamIdentifier=not set
"""

    def test_developer_id(self):
        i = Identity(path="x", code_path="x")
        parse_codesign_details(self.DEV_ID, i)
        self.assertEqual((i.sign_kind, i.team_id, i.hardened_runtime, i.notarization),
                         ("developer-id", "Q6L2SF6YDW", True, "stapled"))

    def test_adhoc_linker_signed(self):
        i = Identity(path="x", code_path="x")
        parse_codesign_details(self.ADHOC, i)
        self.assertEqual((i.sign_kind, i.team_id, i.linker_signed), ("adhoc", None, True))
        i.designated_requirement = parse_requirement('# designated => cdhash H"af08"')
        self.assertEqual(i.dr_kind, "cdhash")
        self.assertFalse(i.stable)

    def test_unsigned(self):
        i = Identity(path="x", code_path="x")
        parse_codesign_details("x: code object is not signed at all\n", i)
        self.assertEqual((i.sign_kind, i.dr_kind, i.stable), ("unsigned", "path", False))

    def test_code_path_for_bundle_executable(self):
        self.assertEqual(code_path_for("/A/claude.app/Contents/MacOS/claude"), Path("/A/claude.app"))
        self.assertEqual(code_path_for("/usr/bin/osascript"), Path("/usr/bin/osascript"))


@unittest.skipUnless(shutil.which("cc") and Path("/usr/bin/codesign").exists(), "needs cc and codesign")
class LiveIdentityTests(unittest.TestCase):
    def test_apple_app_is_stable(self):
        i = inspect("/System/Applications/TextEdit.app")
        self.assertEqual((i.identifier, i.sign_kind, i.dr_kind, i.stable),
                         ("com.apple.TextEdit", "apple", "apple", True))

    def test_rebuilt_adhoc_binary_gets_a_new_identity(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "t.c", Path(d) / "tool"
            src.write_text("int main(void){return 0;}\n")
            subprocess.run(["cc", "-o", str(out), str(src)], check=True)
            first = inspect(out)
            src.write_text("int main(void){return 1;}\n")
            subprocess.run(["cc", "-o", str(out), str(src)], check=True)
            second = inspect(out)
        self.assertEqual(first.dr_kind, "cdhash")
        self.assertNotEqual(first.designated_requirement, second.designated_requirement)

    def test_recorder_resnapshots_after_rebuild(self):
        from sticky.assembler import Event

        with tempfile.TemporaryDirectory() as d:
            app = Path(d) / "T.app"
            (app / "Contents" / "MacOS").mkdir(parents=True)
            src = Path(d) / "t.c"
            exe = app / "Contents" / "MacOS" / "T"

            def build(code):
                src.write_text(f"int main(void){{return {code};}}\n")
                subprocess.run(["cc", "-o", str(exe), str(src)], check=True)
                subprocess.run(["codesign", "-f", "-s", "-", str(app)], check=True,
                               capture_output=True)

            with Store(Path(d) / "s.db") as store:
                rec = Recorder(store, log=lambda m: None)
                e = Event(tccd_pid=1, tid=1, ts_start="2026-01-01 00:00:00.000",
                          client_id="dev.t", client_path=str(app))
                build(0)
                rec._snapshot(e)
                rec._snapshot(e)  # unchanged: no second snapshot
                self.assertEqual(len(store.identities_for("dev.t")), 1)
                time.sleep(1.1)  # make sure the signature file's mtime changes
                build(1)
                rec._snapshot(e)
                builds = store.identities_for("dev.t")
        self.assertEqual(len(builds), 2)
        self.assertNotEqual(builds[0]["dr"], builds[1]["dr"])

    def test_missing_file(self):
        i = inspect("/nonexistent/Thing.app/Contents/MacOS/Thing")
        self.assertFalse(i.exists)
        self.assertEqual(i.code_path, "/nonexistent/Thing.app")


class WhyCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "s.db"
        with Store(self.db) as store:
            Recorder(store, command=["/bin/cat", str(FIXTURES / "ndjson-allowed-and-denied.ndjson")],
                     max_restarts=0, backoff=lambda n: 0, log=lambda m: None,
                     snapshot_identities=False).run()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", str(self.db), *argv])
        return code, out.getvalue()

    def test_why_explains_denial_and_ok(self):
        code, out = self.run_cli("why", "claude", "--since", "all")
        self.assertEqual(code, 1)  # a problem was found
        self.assertIn("Automation → com.apple.Safari", out)
        self.assertIn("✗ Denied: requests are refused silently", out)
        self.assertIn("Automation → com.apple.finder", out)
        self.assertIn("✓ Allowed", out)
        # Problems are listed before healthy permissions.
        self.assertLess(out.index("com.apple.Safari"), out.index("com.apple.finder"))

    def test_why_unknown_app(self):
        code, out = self.run_cli("why", "no-such-app", "--since", "all")
        self.assertEqual(code, 1)
        self.assertIn("No recorded permission requests for 'no-such-app'", out)
        self.assertIn("only sees requests made while it was recording", out)

    def test_why_json(self):
        _, out = self.run_cli("why", "claude", "--since", "all", "--json")
        self.assertIn('"rule": "R2"', out)


if __name__ == "__main__":
    unittest.main()
