"""Assembler tests against real logs recorded on macOS 27.2.1 (2026-11-11).

Every expected value below was observed in the spike, not derived from the
parser's own output. The scenarios, all run from Claude Code
(com.anthropic.claude-code) with ``osascript``:

* compact-finder-allowed.log   Finder x2, already allowed.
* compact-prompts-allowed.log  Finder (allowed), then Music and TextEdit:
                               first request prompted and allowed, second
                               request allowed silently.
* compact-prompt-denied.log    Safari: prompted and denied ("Don't Allow"),
                               then a remembered denial with no prompt.
* ndjson-allowed-and-denied.ndjson  Finder (allowed) and Safari (remembered
                               denial), in the collector's ndjson format.
"""

import unittest
from functools import lru_cache
from pathlib import Path

from sticky.assembler import Assembler, assemble
from sticky.logsource import LogRecord, read_records

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = "com.anthropic.claude-code"
CLAUDE_PATH_SUFFIX = "/Claude/claude-code/2.1.321/ddbdf2b334e1/claude.app"


@lru_cache(maxsize=None)
def load(name):
    return assemble(read_records(str(FIXTURES / name)))


def automation(name):
    events, _ = load(name)
    return [
        e for e in events
        if e.service == "kTCCServiceAppleEvents" and e.client_id == CLAUDE and e.is_decision
    ]


def summary(e):
    return (e.target_id, e.outcome, e.auth_before, e.auth_after, e.requirements_match, e.client_result)


ALL_FIXTURES = [
    "compact-finder-allowed.log",
    "compact-prompts-allowed.log",
    "compact-prompt-denied.log",
    "ndjson-allowed-and-denied.ndjson",
]


class GroupingTests(unittest.TestCase):
    def test_every_request_is_accounted_for(self):
        for name in ALL_FIXTURES:
            with self.subTest(name):
                events, asm = load(name)
                s = asm.stats
                self.assertEqual(s["msg_id_mismatch"], 0)
                self.assertEqual(s["incomplete_at_end"], 0)
                self.assertEqual(s["requests"], s["complete"] + s["ended_without_reply"])
                # A request may only end without a REPLY if it is an entitlement
                # shortcut or a system-side stub whose msgID was forwarded.
                forwarded_ids = {e.msg_id for e in events if e.forwarded}
                for e in events:
                    if e.ended_by == "next_request":
                        self.assertTrue(e.entitled or e.msg_id in forwarded_ids, e)

    def test_request_counts_match_spike(self):
        # 160 + 34 requests with numeric msgIDs were counted independently
        # (REQUEST/REPLY on the same thread) during the spike.
        self.assertEqual(load("compact-prompts-allowed.log")[1].stats["complete"], 161)
        self.assertEqual(load("compact-prompt-denied.log")[1].stats["complete"], 34)


class AutomationDecisionTests(unittest.TestCase):
    def test_already_allowed(self):
        self.assertEqual(
            [summary(e) for e in automation("compact-finder-allowed.log")],
            [("com.apple.finder", "allowed", 2, None, True, 1)] * 2,
        )

    def test_prompted_then_allowed(self):
        self.assertEqual(
            [summary(e) for e in automation("compact-prompts-allowed.log")],
            [
                ("com.apple.finder", "allowed", 2, None, True, 1),
                ("com.apple.Music", "prompted-allowed", 1, 2, False, 1),
                ("com.apple.Music", "allowed", 2, None, True, 1),
                ("com.apple.TextEdit", "prompted-allowed", 1, 2, False, 1),
                ("com.apple.TextEdit", "allowed", 2, None, True, 1),
            ],
        )

    def test_prompted_then_denied_then_remembered(self):
        self.assertEqual(
            [summary(e) for e in automation("compact-prompt-denied.log")],
            [
                ("com.apple.Safari", "prompted-denied", 1, 0, False, 0),
                ("com.apple.Safari", "denied", 0, None, True, 0),
            ],
        )

    def test_ndjson_matches_compact(self):
        self.assertEqual(
            [summary(e) for e in automation("ndjson-allowed-and-denied.ndjson")],
            [
                ("com.apple.finder", "allowed", 2, None, True, 1),
                ("com.apple.Safari", "denied", 0, None, True, 0),
            ],
        )

    def test_prompt_details(self):
        prompts = [
            e for name in ("compact-prompts-allowed.log", "compact-prompt-denied.log")
            for e in automation(name) if e.prompted
        ]
        self.assertEqual([e.target_name for e in prompts], ["Music", "TextEdit", "Safari"])
        for e in prompts:
            self.assertEqual(e.client_name, "claude")
            self.assertTrue(e.usage_string, "claude declares NSAppleEventsUsageDescription")
            self.assertIs(e.policy_allowed, False)
            self.assertEqual(e.tccd_scope, "user")

    def test_denial_prompt_waited_for_the_user(self):
        denied = automation("compact-prompt-denied.log")[0]
        self.assertEqual(denied.ts_start[:19], "2026-11-11 04:16:05")
        self.assertEqual(denied.ts_end[:21], "2026-11-11 04:16:10.7")  # ~4.8 s later


class IdentityTests(unittest.TestCase):
    def test_client_path_and_version(self):
        for name in ALL_FIXTURES:
            for e in automation(name):
                with self.subTest(name=name, ts=e.ts_start):
                    self.assertTrue(e.client_path.endswith(CLAUDE_PATH_SUFFIX), e.client_path)
                    self.assertEqual(e.client_version, "2.1.321")

    def test_signing_requirement_names_team_not_path(self):
        textedit_prompt = automation("compact-prompts-allowed.log")[3]
        self.assertEqual(textedit_prompt.client_type, 0)  # identified by bundle id
        self.assertIn('identifier "com.anthropic.claude-code"', textedit_prompt.client_dr)
        self.assertIn("Q6L2SF6YDW", textedit_prompt.client_dr)
        self.assertNotIn("/Users/", textedit_prompt.client_dr)


class DirectRequestTests(unittest.TestCase):
    def test_osascript_input_monitoring_preflight(self):
        events, _ = load("compact-finder-allowed.log")
        checks = [
            e for e in events
            if e.service == "kTCCServiceListenEvent" and e.responsible_id == CLAUDE
        ]
        # Per osascript run: one check from osascript itself, and two from
        # WindowServer asking on osascript's behalf (accessing=osascript).
        self.assertEqual(len(checks), 6)
        self.assertEqual(
            sorted((e.requesting_id, e.accessing_id) for e in checks),
            [("com.apple.WindowServer", "com.apple.osascript")] * 4
            + [("com.apple.osascript", None)] * 2,
        )
        for e in checks:
            self.assertEqual(e.tccd_scope, "system")
            self.assertTrue(e.preflight)
            self.assertEqual(e.auth_result, 1)
            self.assertEqual(e.outcome, "undetermined")

    def test_entitled_shortcut(self):
        events, _ = load("compact-prompts-allowed.log")
        e = next(e for e in events if e.msg_id == "471.2139")
        self.assertTrue(e.entitled)
        self.assertEqual(e.service, "kTCCServiceListenEvent")
        self.assertEqual(e.client_id, "com.apple.finder")
        self.assertEqual(e.outcome, "allowed")
        self.assertEqual(e.ended_by, "next_request")

    def test_forwarded_from_system_tccd(self):
        events, _ = load("compact-prompts-allowed.log")
        system_side, user_side = sorted(
            (e for e in events if e.msg_id == "613.329"), key=lambda e: e.tccd_uid
        )
        self.assertEqual(system_side.tccd_scope, "system")
        self.assertFalse(system_side.is_decision)
        self.assertEqual(system_side.ended_by, "next_request")
        self.assertTrue(user_side.forwarded)
        self.assertEqual(user_side.service, "kTCCServiceMicrophone")
        self.assertEqual(user_side.client_id, "com.apple.Music")
        self.assertEqual(user_side.outcome, "undetermined")


class SyntheticTests(unittest.TestCase):
    """Edge cases that the recorded logs don't happen to contain."""

    def feed(self, lines):
        asm = Assembler()
        out = []
        for i, (proc, pid, tid, msg) in enumerate(lines):
            out += asm.feed(LogRecord(f"2026-01-01 00:00:00.{i:03d}", proc, pid, tid, "Info", msg))
        return out + asm.flush(), asm

    def test_msg_id_mismatch_is_counted(self):
        _, asm = self.feed([
            ("tccd", 1, 9, "REQUEST: tccd_uid=501, sender_pid=5, sender_uid=501, sender_auid=501, function=TCCAccessRequest, msgID=5.1"),
            ("tccd", 1, 9, "REPLY: (501) function=TCCAccessRequest, msgID=5.2"),
        ])
        self.assertEqual(asm.stats["msg_id_mismatch"], 1)

    def test_open_request_flushed_at_end(self):
        (ev,), asm = self.feed([
            ("tccd", 1, 9, "REQUEST: tccd_uid=501, sender_pid=5, sender_uid=501, sender_auid=501, function=TCCAccessRequest, msgID=5.1"),
        ])
        self.assertEqual(ev.ended_by, "end_of_log")
        self.assertEqual(asm.stats["incomplete_at_end"], 1)

    def test_redacted_decision_line_uses_bundle_line(self):
        (ev,), _ = self.feed([
            ("tccd", 1, 9, "REQUEST: tccd_uid=501, sender_pid=5, sender_uid=501, sender_auid=501, function=TCCAccessRequestIndirect, msgID=5.1"),
            ("tccd", 1, 9, "AttributionChain: accessing={TCCDProcess: identifier=com.apple.Music, pid=5, auid=501, euid=501, binary_path=/System/Applications/Music.app/Contents/MacOS/Music}, requesting={TCCDProcess: identifier=com.apple.Music, pid=5, auid=501, euid=501, binary_path=/x}, "),
            ("tccd", 1, 9, "-[TCCDAccessIdentity initWithIdentifier:type:executableURL:SDKVersion:platformType:]: self.bundle=0x1, bundle:<TCCDBundle: bundleID=com.example.tool, version=1.0, path=/Applications/Tool.app>; for: com.example.tool, URL: file:///x, "),
            ("tccd", 1, 9, "Handling access request: kTCCServiceAppleEvents:<private>:<private>, default_allow: 0, authValue: 1, "),
            ("tccd", 1, 9, "REPLY: (501) function=TCCAccessRequestIndirect, msgID=5.1"),
        ])
        self.assertEqual(ev.client_id, "com.example.tool")
        self.assertEqual(ev.client_path, "/Applications/Tool.app")
        self.assertEqual(ev.target_id, "com.apple.Music")  # from the "accessing" process
        self.assertEqual(ev.outcome, "undetermined")

    def test_client_result_links_to_sender(self):
        events, asm = self.feed([
            ("tccd", 1, 9, "REQUEST: tccd_uid=501, sender_pid=77, sender_uid=501, sender_auid=501, function=TCCAccessRequestIndirect, msgID=77.1"),
            ("tccd", 1, 9, "Handling access request: kTCCServiceAppleEvents:<private>:com.apple.Safari, default_allow: 0, authValue: 0, "),
            ("tccd", 1, 9, "REPLY: (501) function=TCCAccessRequestIndirect, msgID=77.1"),
            ("Other", 78, 3, "TCCAccessRequestIndirect_block_invoke: access request result was 1, timeout was 0"),
            ("Safari", 77, 3, "TCCAccessRequestIndirect_block_invoke: access request result was 0, timeout was 0"),
        ])
        self.assertEqual(events[0].client_result, 0)
        self.assertEqual(asm.stats["client_results_linked"], 1)


if __name__ == "__main__":
    unittest.main()
