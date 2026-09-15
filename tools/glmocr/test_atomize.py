"""Tests for the per-sitting atomizer (tools/glmocr/atomize.py, OCR-Q4).

Pure-function tests pin the label-normalization and pairing rules; the
integration tests run the REAL June-2025 WPH11 pair end-to-end and pin the
observed shape (2026-09-14, engine 1.2.0): MCQ pairing via the bare-number
MS entry, structured-part pairing via "(a)(i)" suffixes, honest unmatched
reporting, and byte-identical determinism across runs.

Run: python3 tools/glmocr/test_atomize.py -v   (no network, no key)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.glmocr import atomize  # noqa: E402

RES = Path(__file__).resolve().parent.parent.parent / "src/test/resources/glm-ocr"
JUNE_QP = RES / "june-2025-wph11-01-qp.md"
JUNE_MS = RES / "june-2025-wph11-01-ms.md"


class LabelNormalizationTests(unittest.TestCase):
    def test_ms_suffix(self):
        self.assertEqual("(a)(i)", atomize.ms_suffix("1(a)(i)", 1))
        self.assertEqual("(a)", atomize.ms_suffix("12(a)", 12))
        self.assertEqual("", atomize.ms_suffix("1", 1))
        self.assertEqual("", atomize.ms_suffix("*14", 14))
        self.assertEqual("(c)", atomize.ms_suffix("*3(c)", 3))

    def test_qp_suffix(self):
        self.assertEqual("(a)", atomize.qp_suffix("a"))
        self.assertEqual("(a)(i)", atomize.qp_suffix("a-i"))
        self.assertEqual("", atomize.qp_suffix(""))
        self.assertEqual("", atomize.qp_suffix(None))

    def test_stem_chain(self):
        self.assertEqual(["a", "i"], atomize.stem_chain("a-i"))
        self.assertEqual(["b"], atomize.stem_chain("b"))


class PromptAssemblyTests(unittest.TestCase):
    def test_inheritance_joins_verbatim_slices(self):
        self.assertEqual("stem\n\nlead-in\n\nown",
                         atomize._assemble_prompt("stem", "lead-in", "own"))

    def test_empty_slices_dropped(self):
        self.assertEqual("own", atomize._assemble_prompt("", "", "own"))
        self.assertEqual("stem\n\nown", atomize._assemble_prompt("stem", "", "own"))


class PairingLogicTests(unittest.TestCase):
    def test_entries_grouped_by_number(self):
        ms = {"entries": [atomize_ms_entry("1", 1), atomize_ms_entry("3(a)", 3),
                          atomize_ms_entry("3(b)", 3)]}
        grouped = atomize._group_entries_by_number(ms)
        self.assertEqual({1, 3}, set(grouped.keys()))
        self.assertEqual(2, len(grouped[3]))

    def test_suffix_index_and_lookup(self):
        entries = [atomize_ms_entry("3(a)", 3), atomize_ms_entry("3(a)(i)", 3)]
        idx = atomize._index_entries_by_suffix(entries)
        self.assertIs(entries[0], idx["(a)"])
        self.assertIs(entries[1], idx["(a)(i)"])

    def test_ms_view_is_null_safe(self):
        self.assertIsNone(atomize._ms_view(None))
        self.assertEqual("1(a)", atomize._ms_view(
            atomize_ms_entry("1(a)", 1))["label"])


def atomize_ms_entry(label, number):
    return {"entryId": "ms-x-" + label.replace("(", "").replace(")", ""),
            "label": label, "number": number, "answerText": "ans",
            "markPoints": [], "guidance": [], "marks": 1, "confidence": 0.75}


class RealPairIntegrationTests(unittest.TestCase):
    """Pinned against the real June-2025 WPH11 pair — observed 2026-09-14."""

    @classmethod
    def setUpClass(cls):
        cls.export = atomize.atomize(
            JUNE_QP.read_bytes(), JUNE_MS.read_bytes(),
            JUNE_QP.name, JUNE_MS.name)

    def test_top_level_honesty(self):
        self.assertTrue(self.export["reviewRequired"])
        self.assertEqual("glmocr-atomize", self.export["tool"])
        self.assertEqual("1.0", self.export["schemaVersion"])
        self.assertEqual(20, len(self.export["questions"]))

    def test_mcq_pairs_with_bare_number_entry(self):
        q1 = next(q for q in self.export["questions"] if q["number"] == 1)
        self.assertTrue(q1["mcq"])
        self.assertIsNotNone(q1["markScheme"])
        self.assertEqual("1", q1["markScheme"]["label"])
        self.assertIn("The only correct answer is",
                      q1["markScheme"]["answerText"])

    def test_structured_parts_carry_inherited_stem_and_markscheme(self):
        q12 = next(q for q in self.export["questions"] if q["number"] == 12)
        self.assertTrue(q12["parts"])
        for part in q12["parts"]:
            self.assertIsNotNone(part["markScheme"])
            self.assertIn(part["text"], part["renderedPrompt"])
            if q12["stem"]:
                self.assertTrue(part["renderedPrompt"].startswith(q12["stem"]))

    def test_unmatched_parts_are_reported_not_guessed(self):
        warns = self.export["warnings"]["atomize"]
        flagged = [w for w in warns if "no mark-scheme entry" in w]
        self.assertTrue(flagged)
        for part_owner in flagged:
            self.assertIn("no mark-scheme entry for suffix", part_owner)

    def test_totals_block(self):
        totals = self.export["totals"]
        self.assertEqual(70, totals["sumOfQuestionTotals"])
        self.assertEqual(80, totals["paperTotal"])

    def test_determinism_byte_identical(self):
        again = atomize.atomize(JUNE_QP.read_bytes(), JUNE_MS.read_bytes(),
                                JUNE_QP.name, JUNE_MS.name)
        self.assertEqual(json.dumps(self.export, sort_keys=True),
                         json.dumps(again, sort_keys=True))

    def test_atomize_parsed_matches_atomize(self):
        """atomize() == atomize_parsed() over the same parsed documents —
        the split that lets conformance.py pin fixed identity on both sides."""
        from tools.glmocr.canonical import GlmOcrMarkdownParser
        parser = GlmOcrMarkdownParser()
        qp_doc = parser.parse(JUNE_QP.read_bytes(), JUNE_QP.name)
        ms_doc = parser.parse(JUNE_MS.read_bytes(), JUNE_MS.name)
        parsed = atomize.atomize_parsed(qp_doc, ms_doc, JUNE_QP.name, JUNE_MS.name)
        self.assertEqual(json.dumps(self.export, sort_keys=True),
                         json.dumps(parsed, sort_keys=True))

    def test_cli_writes_file_and_compact(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "paper.json"
            rc = atomize.main([str(JUNE_QP), str(JUNE_MS), "-o", str(out)])
            self.assertEqual(0, rc)
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(20, len(loaded["questions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
