import unittest
from pathlib import Path

from sticky.logsource import detect_format, iter_compact, iter_ndjson, read_records

FIXTURES = Path(__file__).parent / "fixtures"


class CompactTests(unittest.TestCase):
    def test_parses_fields_and_hex_thread_id(self):
        lines = [
            'Filtering the log data using "subsystem == "com.apple.TCC""\n',
            "Timestamp               Ty Process[PID:TID]\n",
            "2026-11-11 04:14:14.554 I  tccd[14004:219b51] [com.apple.TCC:access] "
            "do_TCCAccessRequestIndirect: checking access against database\n",
        ]
        (rec,) = list(iter_compact(lines))
        self.assertEqual(rec.ts, "2026-11-11 04:14:14.554")
        self.assertEqual(rec.process, "tccd")
        self.assertEqual(rec.pid, 14004)
        self.assertEqual(rec.tid, 0x219B51)
        self.assertEqual(rec.level, "Info")
        self.assertEqual(rec.message, "do_TCCAccessRequestIndirect: checking access against database")
        self.assertIsNone(rec.fmt)

    def test_joins_tab_continuation_lines(self):
        lines = [
            "2026-11-11 04:14:01.835 I  tccd[473:2196aa] [com.apple.TCC:access] REQUEST_MSG: msgID=613.329, msg={\n",
            '\tservice="kTCCServiceMicrophone"\n',
            "}\n",
            "2026-11-11 04:14:01.836 Df tccd[473:2196aa] [com.apple.TCC:access] next\n",
        ]
        first, second = list(iter_compact(lines))
        self.assertEqual(first.message.splitlines()[1], '\tservice="kTCCServiceMicrophone"')
        self.assertEqual(second.level, "Default")

    def test_process_names_with_spaces(self):
        line = "2026-11-11 04:14:01.835 I  Google Chrome Helper[900:1a] [com.apple.TCC:access] hi\n"
        (rec,) = list(iter_compact([line]))
        self.assertEqual(rec.process, "Google Chrome Helper")
        self.assertEqual(rec.pid, 900)


class NdjsonTests(unittest.TestCase):
    def test_reads_fixture_with_format_strings(self):
        recs = list(read_records(str(FIXTURES / "ndjson-allowed-and-denied.ndjson")))
        self.assertEqual(len(recs), 330)  # 331 lines minus the "Filtering…" header
        self.assertTrue(all(len(r.ts) == 23 for r in recs))
        reply = next(r for r in recs if r.message.startswith("REPLY:"))
        self.assertEqual(reply.process, "tccd")
        self.assertEqual(reply.fmt, "REPLY: (%d) function=%{public}s, msgID=%{public}s")

    def test_skips_non_json_and_non_log_events(self):
        lines = [
            "Filtering the log data using …\n",
            '{"eventType":"activityCreateEvent","eventMessage":"x"}\n',
            '{"eventType":"logEvent","timestamp":"2026-11-11 04:40:21.269123-0800",'
            '"processImagePath":"/usr/libexec/tccd","processID":5,"threadID":7,'
            '"messageType":"Default","eventMessage":"hello","formatString":"%s"}\n',
        ]
        (rec,) = list(iter_ndjson(lines))
        self.assertEqual((rec.process, rec.pid, rec.tid, rec.ts), ("tccd", 5, 7, "2026-11-11 04:40:21.269"))


class DetectTests(unittest.TestCase):
    def test_detects_both_formats(self):
        for name, expected in [
            ("ndjson-allowed-and-denied.ndjson", "ndjson"),
            ("compact-finder-allowed.log", "compact"),
        ]:
            with open(FIXTURES / name) as f:
                self.assertEqual(detect_format([f.readline() for _ in range(5)]), expected, name)


if __name__ == "__main__":
    unittest.main()
