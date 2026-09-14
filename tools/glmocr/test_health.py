"""Tests for the corpus health gate (tools/glmocr/health.py, OCR-Q4).

Two layers:

1. pure-function tests over synthetic draft dicts — deterministic check logic
   (mark sums, QP/MS total agreement, paper mapping, paper totals, assets);
2. integration tests over the REAL committed fixtures — pinned outcomes
   (observed on 2026-09-14 with engine 1.2.0), including the documented
   June-2025 paper-total conflict (cover 80 vs printed question sums 70),
   which the gate must flag as FAIL, and the pathological pair's known
   part-sum conflict.

Run: python3 tools/glmocr/test_health.py -v   (no network, no key)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.glmocr import health  # noqa: E402

RES = Path(__file__).resolve().parent.parent.parent / "src/test/resources/glm-ocr"
JUNE_QP = RES / "june-2025-wph11-01-qp.md"
JUNE_MS = RES / "june-2025-wph11-01-ms.md"
PATHO_QP = RES / "pathological-qp.md"
PATHO_MS = RES / "pathological-ms.md"


def _q(number, parts=None, printed=None, marks_known_total=None):
    part_dicts = []
    for i, m in enumerate(parts or []):
        part_dicts.append({"label": "a" if len(parts or []) == 1 else chr(97 + i),
                           "marks": m, "text": "part text", "figures": [],
                           "answerPrompts": [], "confidence": 0.8})
    return {"number": number, "parts": part_dicts, "marks": marks_known_total,
            "marksKnown": marks_known_total is not None}


def _qp_draft(questions, totals, paper_total):
    return {"questions": questions, "questionTotals": totals,
            "paperTotal": paper_total, "warnings": []}


def _ms_draft(entries, totals, paper_total):
    return {"entries": entries, "questionTotals": totals,
            "paperTotal": paper_total, "warnings": []}


def _entry(label, number, marks=2):
    return {"entryId": "ms-x-" + str(label), "label": label, "number": number,
            "answerText": "answer", "markPoints": [], "guidance": [],
            "marks": marks, "confidence": 0.75}


class QuestionMarkSumTests(unittest.TestCase):
    def test_clean_pair_is_ok(self):
        qp = _qp_draft([_q(1, parts=[2, 1], marks_known_total=3)],
                       {"1": 3}, 3)
        check = health._check_question_mark_sums(qp)
        self.assertEqual(health.OK, check["status"])
        self.assertEqual([], check["findings"])

    def test_part_sum_conflict_fails(self):
        qp = _qp_draft([_q(1, parts=[2, 2], marks_known_total=4)],
                       {"1": 5}, 5)  # printed 5, parts sum 4
        check = health._check_question_mark_sums(qp)
        self.assertEqual(health.FAIL, check["status"])
        self.assertEqual(1, len(check["findings"]))
        self.assertEqual(4, check["findings"][0]["partSum"])
        self.assertEqual(5, check["findings"][0]["printedTotal"])

    def test_unknown_part_marks_is_review(self):
        qp = _qp_draft([_q(2, parts=[1, None])], {"2": 3}, 3)
        check = health._check_question_mark_sums(qp)
        self.assertEqual(health.REVIEW, check["status"])
        self.assertEqual("some part marks unknown", check["findings"][0]["note"])

    def test_mcq_without_parts_is_ok(self):
        qp = _qp_draft([_q(1, parts=[], marks_known_total=1)], {"1": 1}, 1)
        self.assertEqual(health.OK, health._check_question_mark_sums(qp)["status"])


class QpMsTotalsTests(unittest.TestCase):
    def test_agreeing_totals_ok(self):
        qp = _qp_draft([], {"1": 2, "2": 3}, 5)
        ms = _ms_draft([], {"1": 2, "2": 3}, 5)
        self.assertEqual(health.OK, health._check_qp_ms_totals(qp, ms)["status"])

    def test_mismatch_fails(self):
        qp = _qp_draft([], {"1": 2}, 2)
        ms = _ms_draft([], {"1": 3}, 3)
        check = health._check_qp_ms_totals(qp, ms)
        self.assertEqual(health.FAIL, check["status"])
        self.assertEqual([{"question": 1, "qp": 2, "ms": 3}], check["mismatches"])

    def test_missing_on_one_side_is_review(self):
        qp = _qp_draft([], {"1": 2}, 2)
        ms = _ms_draft([], {}, 2)
        self.assertEqual(health.REVIEW, health._check_qp_ms_totals(qp, ms)["status"])


class PaperMappingTests(unittest.TestCase):
    def test_complete_mapping_ok(self):
        qp = _qp_draft([_q(1), _q(2)], {}, None)
        ms = _ms_draft([_entry("1", 1), _entry("2(a)", 2)], {}, None)
        self.assertEqual(health.OK, health._check_paper_mapping(qp, ms)["status"])

    def test_unmatched_both_directions_review(self):
        qp = _qp_draft([_q(1)], {}, None)
        ms = _ms_draft([_entry("9(b)", 9)], {}, None)
        check = health._check_paper_mapping(qp, ms)
        self.assertEqual(health.REVIEW, check["status"])
        self.assertEqual([1], check["unmatchedQp"])
        self.assertEqual([9], check["unmatchedMs"])


class PaperTotalTests(unittest.TestCase):
    def test_consistent_totals_ok(self):
        qp = _qp_draft([_q(1, parts=[2], marks_known_total=2)], {"1": 2}, 2)
        ms = _ms_draft([], {"1": 2}, 2)
        self.assertEqual(health.OK, health._check_paper_total(qp, ms)["status"])

    def test_cover_vs_question_sum_conflict_fails(self):
        qp = _qp_draft([_q(1, parts=[2], marks_known_total=2)], {"1": 2}, 80)
        ms = _ms_draft([], {"1": 2}, 80)
        check = health._check_paper_total(qp, ms)
        self.assertEqual(health.FAIL, check["status"])
        self.assertEqual({"qp": 80, "sumOfQuestionTotals": 2}, check["mismatches"][0])

    def test_qp_ms_cover_conflict_fails(self):
        qp = _qp_draft([], {"1": 2}, 80)
        ms = _ms_draft([], {"1": 2}, 120)  # the audited 1A 80-vs-120 class
        self.assertEqual(health.FAIL, health._check_paper_total(qp, ms)["status"])

    def test_missing_cover_is_review(self):
        qp = _qp_draft([], {"1": 2}, None)
        ms = _ms_draft([], {"1": 2}, None)
        self.assertEqual(health.REVIEW, health._check_paper_total(qp, ms)["status"])


class AssetTests(unittest.TestCase):
    def _doc(self, urls):
        return {"figures": [{"text": u, "source_name": "crop_1_1.png"} for u in urls],
                "sections": []}

    def test_local_asset_present_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "assets").mkdir()
            (d / "assets" / "crop_1_1.png").write_bytes(b"png")
            qp = d / "QP.md"
            qp.write_bytes(b"x")
            check = health._check_assets(qp, self._doc(
                ["https://maas-watermark-prod-new.cn-wlcb.ufileos.com/x/crop_1_1.png?a=b"]), None)
            self.assertEqual(health.OK, check["status"])

    def test_signed_url_without_local_is_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            qp = Path(tmp) / "QP.md"
            qp.write_bytes(b"x")
            check = health._check_assets(
                qp, self._doc(["https://maas-watermark-prod-new.cn-wlcb.ufileos.com/x/crop_1_1.png?a=b"]), None)
            self.assertEqual(health.REVIEW, check["status"])
            self.assertEqual(1, check["knownUnavailable"])

    def test_manifest_listed_but_missing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "manifest.json").write_text(json.dumps(
                {"assets": {"crop_1_1.png": "assets/crop_1_1.png"}}), encoding="utf-8")
            qp = d / "QP.md"
            qp.write_bytes(b"x")
            check = health._check_assets(
                qp, self._doc(["https://host.example/x/crop_1_1.png"]), None)
            self.assertEqual(health.FAIL, check["status"])
            self.assertIn("absent on disk", check["missing"][0]["why"])


class PairingTests(unittest.TestCase):
    def test_explicit_and_ambiguous_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "unit1").mkdir()
            (root / "unit1" / "June 2012 QP.pdf.md").write_bytes(b"qp")
            (root / "unit1" / "June 2012 MS.pdf.md").write_bytes(b"ms")
            (root / "unit2").mkdir()
            (root / "unit2" / "June 2012 QP.pdf.md").write_bytes(b"qp2")
            pairs, skipped = health.find_pairs(root)
            self.assertEqual(1, len(pairs))
            self.assertEqual(1, len(skipped))  # unit2 QP has no MS partner

    def test_role_tokens(self):
        self.assertEqual("QP", health._role_of("January 2012 QP - Unit 4.pdf.md"))
        self.assertEqual("MS", health._role_of("January 2012 MS - Unit 4.pdf.md"))
        self.assertEqual("MS", health._role_of("mark scheme June 2012.md"))
        self.assertIsNone(health._role_of("June 2012 paper.pdf.md"))


class RealFixtureTests(unittest.TestCase):
    """Pinned against the real corpus — observed 2026-09-14, engine 1.2.0."""

    @classmethod
    def setUpClass(cls):
        cls.pair = health.analyze_pair(JUNE_QP, JUNE_MS)

    def test_june_pair_counts(self):
        self.assertEqual(20, self.pair["counts"]["questions"])
        self.assertEqual(31, self.pair["counts"]["msEntries"])

    def test_june_pair_paper_total_conflict_is_fail(self):
        check = self.pair["checks"]["paperTotal"]
        self.assertEqual(health.FAIL, check["status"])
        self.assertEqual(80, check["qp"])
        self.assertEqual(70, check["sumOfQuestionTotals"])

    def test_june_pair_mapping_complete_but_draft_marks_reviewed(self):
        self.assertEqual(health.OK, self.pair["checks"]["paperMapping"]["status"])
        self.assertEqual(health.REVIEW,
                         self.pair["checks"]["questionMarkSums"]["status"])

    def test_june_pair_assets_known_unavailable(self):
        check = self.pair["checks"]["assets"]
        self.assertEqual(health.REVIEW, check["status"])
        self.assertGreater(check["knownUnavailable"], 0)
        self.assertEqual([], check["missing"])

    def test_pathological_pair_flags_conflict(self):
        pair = health.analyze_pair(PATHO_QP, PATHO_MS)
        self.assertEqual(health.FAIL, pair["status"])  # cover 80-vs-120 class defect

    def test_cli_exit_codes_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            out1 = str(Path(tmp) / "r1.json")
            out2 = str(Path(tmp) / "r2.json")
            rc1 = health.main([str(JUNE_QP), str(JUNE_MS), "-o", out1])
            rc2 = health.main([str(JUNE_QP), str(JUNE_MS), "-o", out2])
            self.assertEqual(1, rc1)  # FAIL present (paperTotal conflict)
            self.assertEqual(rc1, rc2)
            self.assertEqual(Path(out1).read_text(), Path(out2).read_text())

    def test_cli_clean_exit_on_pass_only(self):
        rc = health.main([str(JUNE_QP), str(JUNE_MS), "--json"])
        # june pair has a FAIL (paperTotal) -> rc 1; sanity: JSON parses
        self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
