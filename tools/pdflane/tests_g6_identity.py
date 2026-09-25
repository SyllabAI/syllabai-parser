#!/usr/bin/env python3
"""G6 identity-gate tests (F10 cure).

Covers: printed-identity extraction (refs / Paper: token / exam date / MS
session header), the check matrix (variant conflict, ref absent, co-printed
other-qualification refs fine, unreadable scan cover), session-drift-as-flag
(COVID June-print/November-admin pairing), MS-only path, gates.run G6 block
appearance/absence (byte-compat when no identity claimed), and the exact
user-reported case: dir claims 4CH1/1C, cover prints 4CH1/1CR -> FAIL.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdflane import gates, identity  # noqa: E402

# real-world cover shapes (Jan-2020 case that seeded the F10 repair)
COVER_1CR = """Pearson Edexcel International GCSE
Paper Reference 4CH1/1CR 4SD0/1CR
Paper: 1CR
Thursday 9 January 2020
Time 1 hour 10 minutes"""

COVER_1C = """Pearson Edexcel International GCSE
Paper Reference 4CH1/1C 4SD0/1C
Paper: 1C
Thursday 9 January 2020
Time 1 hour 10 minutes"""

MS_COVER = """Mark Scheme (Results)
January 2020
Paper 1C
Edexcel IGCSE Chemistry"""


class ExtractTests(unittest.TestCase):
    def test_refs_paper_and_date(self):
        got = identity.extract(COVER_1CR)
        self.assertEqual(got["refs"], ["4CH1/1CR", "4SD0/1CR"])
        self.assertEqual(got["paper"], "1CR")
        self.assertEqual(got["date"], "2020-01-09")

    def test_ms_session_header(self):
        got = identity.extract(MS_COVER)
        self.assertEqual(got["refs"], [])
        self.assertIsNone(got["paper"])          # 'Paper 1C' is not 'Paper: 1C'
        self.assertEqual(got["session_hint"], "January 2020")

    def test_blank_cover(self):
        got = identity.extract("")
        self.assertEqual(got, {"refs": [], "paper": None, "date": None,
                               "session_hint": None})


class CheckTests(unittest.TestCase):
    def test_variant_conflict_is_the_user_reported_case(self):
        printed = identity.extract(COVER_1CR)
        ok, detail = identity.check_qp("4CH1/1C", "January 2020", printed)
        self.assertFalse(ok)
        self.assertEqual(detail["mismatch"], "VARIANT-CONFLICT")
        self.assertEqual(detail["conflicting_refs"], ["4CH1/1CR"])

    def test_other_variant_printed_is_variant_conflict(self):
        # printing the sibling variant is MORE specific than plain absence
        printed = identity.extract("Paper Reference 4CH1/2C\nPaper: 2C\nMonday 20 January 2020")
        ok, detail = identity.check_qp("4CH1/1C", "January 2020", printed)
        self.assertFalse(ok)
        self.assertEqual(detail["mismatch"], "VARIANT-CONFLICT")
        self.assertEqual(detail["conflicting_refs"], ["4CH1/2C"])

    def test_ref_absent(self):
        # only a different qualification's ref printed: expected ref absent,
        # no same-unit conflict
        printed = identity.extract("Paper Reference 4SD0/1C\nMonday 20 January 2020")
        ok, detail = identity.check_qp("4CH1/1C", "January 2020", printed)
        self.assertFalse(ok)
        self.assertEqual(detail["mismatch"], "REF-ABSENT")

    def test_correct_identity_passes(self):
        printed = identity.extract(COVER_1C)
        ok, detail = identity.check_qp("4CH1/1C", "January 2020", printed)
        self.assertTrue(ok)
        self.assertNotIn("mismatch", detail)

    def test_unreadable_cover_is_indeterminate(self):
        ok, _ = identity.check_qp("4CH1/1C", "January 2020",
                                  {"refs": [], "paper": None, "date": None})
        self.assertIsNone(ok)

    def test_session_drift_is_a_flag_not_a_fail(self):
        # COVID June-print/November-administration pairing
        flag = identity.check_session("November 2020",
                                      {"refs": ["4CH1/1C"], "paper": "1C",
                                       "date": "2020-06-04"})
        self.assertIsNotNone(flag)
        self.assertEqual(flag["code"], "IDENTITY-SESSION-DRIFT")

    def test_matching_session_no_flag(self):
        self.assertIsNone(identity.check_session(
            "January 2020", {"refs": ["4CH1/1C"], "paper": "1C",
                             "date": "2020-01-09"}))

    def test_ms_paper_token_mismatch(self):
        flag = identity.check_ms("4CH1/1C", {"refs": [], "paper": "1CR",
                                             "date": None})
        self.assertIsNotNone(flag)
        self.assertEqual(flag["code"], "IDENTITY-MS-PAPER-TOKEN-MISMATCH")


def _base(**over):
    """Minimal gates.run() fixture (G1-G5 shaped as in tests_atoms_v11)."""
    ms_parse = {"questions": [
        {"number": 1, "total_row": 5, "arithmetic_ok": True, "pages": {4},
         "points": [{"label": "M1", "marks": 5}]}],
        "unclassified": [],
        "buckets": {"point": 0, "guidance": 0, "unclassified": 0, "continuation": 0}}
    qp_parse = {"questions": [{"number": 1, "total": 5, "orphan_total": False,
                               "pages": {2}, "prompt": "p"}],
                "witnesses": [{"value": 5}]}
    base = dict(probe={}, qp_parse=qp_parse, ms_parse=ms_parse,
                engine_texts={"pdftotext_ms_pages": [{"text": "Total 5"}]},
                assets_check={"refs": [], "existing": [], "embedded": 0})
    base.update(over)
    return base


class GatesIntegrationTests(unittest.TestCase):
    def test_g6_fails_on_variant_conflict(self):
        res = identity.build("4CH1/1C", "January 2020",
                             identity.extract(COVER_1CR),
                             identity.extract(MS_COVER))
        g = gates.run(**_base(expected_identity={
            "paper_code": "4CH1/1C", "session": "January 2020",
            "printed_qp": identity.extract(COVER_1CR),
            "printed_ms": identity.extract(MS_COVER)}))
        self.assertEqual(g["gates"]["G6"]["verdict"], "FAIL")
        self.assertIn("G6", g["failed_gates"])
        self.assertEqual(g["overall"], "FAIL")
        _ = res  # build() shape exercised via gates.run path

    def test_g6_passes_and_flags_on_session_drift(self):
        g = gates.run(**_base(expected_identity={
            "paper_code": "4CH1/1C", "session": "November 2020",
            "printed_qp": {"refs": ["4CH1/1C"], "paper": "1C",
                           "date": "2020-06-04"},
            "printed_ms": {"refs": [], "paper": "1C", "date": None}}))
        self.assertEqual(g["gates"]["G6"]["verdict"], "PASS_WITH_FLAGS")
        codes = [f["code"] for f in g["flags"]]
        self.assertIn("IDENTITY-SESSION-DRIFT", codes)
        self.assertNotIn("G6", g["failed_gates"])

    def test_g6_indeterminate_scan_cover(self):
        g = gates.run(**_base(expected_identity={
            "paper_code": "4CH1/1C", "session": "January 2020",
            "printed_qp": {"refs": [], "paper": None, "date": None},
            "printed_ms": {"refs": [], "paper": None, "date": None}}))
        self.assertEqual(g["gates"]["G6"]["verdict"], "PASS_WITH_FLAGS")
        self.assertIn("IDENTITY-COVER-UNREADABLE", [f["code"] for f in g["flags"]])

    def test_no_g6_block_without_claimed_identity(self):
        g = gates.run(**_base())
        self.assertNotIn("G6", g["gates"])       # byte-compat for old callers

    def test_ms_only_g6_uses_ms_cover(self):
        ms_parse = {"questions": [
            {"number": 1, "total_row": 4, "arithmetic_ok": True,
             "points": [{"label": "M1", "marks": 4}]}],
            "unclassified": [], "buckets": {"point": 1, "guidance": 0,
                                            "unclassified": 0, "continuation": 0}}
        g = gates.run_ms_only({}, ms_parse,
                              {"pdftotext_ms_pages": [{"text": "Total 4"}]},
                              {"refs": [], "existing": [], "embedded": 0},
                              expected_identity={
                                  "paper_code": "4CH1/1C", "session": "January 2020",
                                  "printed_ms": identity.extract(MS_COVER)})
        # MS cover prints 'Paper 1C' (no 'Paper:' token) -> no token flag, no QP;
        # MS session header matches -> PASS
        self.assertEqual(g["gates"]["G6"]["verdict"], "PASS")

    def test_ms_only_g6_token_mismatch(self):
        ms_parse = {"questions": [
            {"number": 1, "total_row": 4, "arithmetic_ok": True,
             "points": [{"label": "M1", "marks": 4}]}],
            "unclassified": [], "buckets": {"point": 1, "guidance": 0,
                                            "unclassified": 0, "continuation": 0}}
        g = gates.run_ms_only({}, ms_parse,
                              {"pdftotext_ms_pages": [{"text": "Total 4"}]},
                              {"refs": [], "existing": [], "embedded": 0},
                              expected_identity={
                                  "paper_code": "4CH1/1C", "session": "January 2020",
                                  "printed_ms": {"refs": [], "paper": "1CR",
                                                 "date": None}})
        self.assertIn("IDENTITY-MS-PAPER-TOKEN-MISMATCH",
                      [f["code"] for f in g["flags"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
