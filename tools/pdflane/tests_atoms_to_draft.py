"""tests_atoms_to_draft — atoms/1.1 -> draft-1.0 converter (G8 bank backfill A1).

Covers the fidelity rules pinned in the module docstring: block rendering,
part/label mapping (sub-numbered leaves), questionRef resolution against the
core PastPaperIngestionService contract (exact-N or N-<label> prefix rules),
alternative merging (never emit 0-mark rows — core clamps Math.max(marks,1)),
pool cap visibility, levels flattening, guidance merge, and determinism.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from atoms_to_draft import (  # noqa: E402
    EXTRACTION_METHOD,
    SCHEMA_VERSION,
    _convert_atom_points,
    convert,
    render_blocks,
)


def _atom(**over):
    atom = {
        "number": 3,
        "type": "structured",
        "marks": 6,
        "commandWord": "Explain",
        "stem": [{"type": "para", "md": "Stem text."}],
        "parts": [
            {"id": "3a", "label": "a", "sub": None, "type": "open", "marks": 4,
             "commandWord": None, "prompt": [{"type": "para", "md": "Part a."}],
             "pages": [2]},
            {"id": "3b-i", "label": "b", "sub": "i", "type": "open", "marks": 1,
             "commandWord": None, "prompt": [{"type": "para", "md": "Part b i."}],
             "pages": [3]},
            {"id": "3b-ii", "label": "b", "sub": "ii", "type": "open", "marks": 1,
             "commandWord": None, "prompt": [{"type": "para", "md": "Part b ii."}],
             "pages": [3]},
        ],
        "markScheme": {
            "totals": {"printed": 6, "sum": 6, "verified": True},
            "guidance": [],
            "points": [
                {"id": "M1", "part": "a", "sub": None, "marks": 1, "md": "answer a1",
                 "allow": ["a1 variant"], "reject": [], "ignore": [], "notes": [],
                 "pages": [3]},
                {"id": "M2", "part": "a", "sub": None, "marks": 1, "md": "answer a2",
                 "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [3]},
                {"id": "B1", "part": "b", "sub": "i", "marks": 1, "md": "bi answer",
                 "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [4]},
                {"id": "B2", "part": "b", "sub": "ii", "marks": 1, "md": "bii answer",
                 "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [4]},
            ],
            "provenance": "pdf-parsed",
        },
        "provenance": "pdf-parsed",
        "flags": [],
    }
    atom.update(over)
    return atom


IDENTITY = {
    "board": "Edexcel", "qualification": "International GCSE", "subject": "Chemistry",
    "unit": None, "sessionLabel": "January 2012", "paperCode": "4CH0/1C",
    "questionPaperDocumentId": "qp-doc-id", "markSchemeDocumentId": "ms-doc-id",
}


class RenderBlocksTest(unittest.TestCase):
    def test_para_table_choices_rendered_answer_lines_dropped(self):
        blocks = [
            {"type": "para", "md": "Pick one."},
            {"type": "choices", "items": [{"label": "A", "md": "red"}, {"label": "B", "md": "blue"}]},
            {"type": "table", "md": "| a | b |\n|---|---|\n| 1 | 2 |"},
            {"type": "answer_lines", "count": 3},
            {"type": "image", "src": "assets/QP_p04_01.png", "alt": "apparatus"},
        ]
        text = render_blocks(blocks)
        self.assertIn("Pick one.", text)
        self.assertIn("A. red", text)
        self.assertIn("B. blue", text)
        self.assertIn("| a | b |", text)
        self.assertNotIn("....", text)
        self.assertIn("![apparatus](assets/QP_p04_01.png)", text)

    def test_empty_and_unknown_blocks(self):
        self.assertEqual(render_blocks(None), "")
        self.assertEqual(render_blocks([]), "")
        self.assertEqual(render_blocks([{"type": "future-kind"}]), "")


class QuestionRefContractTest(unittest.TestCase):
    """questionRef must satisfy core's pointsForQuestion/resolvePart rules:
    exact "<q>" for question-level, "<q>-<label>" where label is the DRAFT part
    label (letter or letter-sub)."""

    def test_refs_match_draft_part_labels(self):
        draft = convert({"questions": [_atom()]}, "4ch0/past-papers/2012-01/4CH0-1C", IDENTITY)
        labels = {p["label"] for p in draft["questions"][0]["parts"]}
        refs = {p["questionRef"] for p in draft["markScheme"]["points"]}
        self.assertEqual(labels, {"a", "b-i", "b-ii"})
        self.assertEqual(refs, {"3-a", "3-b-i", "3-b-ii"})
        for ref in refs:
            dash = ref.index("-")
            self.assertIn(ref[dash + 1:], labels)

    def test_question_level_ref_when_point_has_no_part(self):
        atom = _atom()
        atom["markScheme"]["points"].append(
            {"id": "M9", "part": None, "sub": None, "marks": 1, "md": "any order",
             "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [4]})
        pts = _convert_atom_points(atom)
        self.assertIn("3", [p["questionRef"] for p in pts])


class AlternativeMergingTest(unittest.TestCase):
    def test_zero_mark_alternative_never_emitted_as_row(self):
        atom = _atom()
        atom["markScheme"]["points"].insert(1, {
            "id": "M1-alt", "part": "a", "sub": None, "marks": 0,
            "md": "electrons transferred differently", "allow": [], "reject": [],
            "ignore": [], "notes": [], "pages": [3]})
        pts = _convert_atom_points(atom)
        self.assertEqual(len(pts), 4)  # M1, M2, B1, B2 — the alt adds NO row
        m1 = next(p for p in pts if p["text"] == "answer a1")
        self.assertTrue(any(a.startswith("Alternative:") for a in m1["acceptance"]))
        self.assertTrue(all(p["marks"] >= 1 for p in pts))

    def test_alternatives_only_group_promotes_first(self):
        atom = _atom()
        atom["markScheme"]["points"] = [
            {"id": "A1", "part": "a", "sub": None, "marks": 0, "md": "alt one",
             "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [3]},
            {"id": "A2", "part": "a", "sub": None, "marks": 0, "md": "alt two",
             "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [3]},
        ]
        pts = _convert_atom_points(atom)
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["marks"], 1)
        self.assertTrue(pts[0]["text"].startswith("[alternative answer]"))
        self.assertIn("Alternative: [alternative answer] alt two", pts[0]["acceptance"])


class PoolTest(unittest.TestCase):
    def test_pool_head_capped_prefix_and_scope(self):
        atom = _atom()
        pool_points = [
            {"id": f"M{i}", "part": "a", "sub": None, "marks": 1, "md": f"cand {i}",
             "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [3]}
            for i in range(1, 5)
        ]
        other = {"id": "M1", "part": "b", "sub": "i", "marks": 1, "md": "unrelated",
                 "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [4]}
        atom["markScheme"]["points"] = pool_points + [other]
        atom["markScheme"]["pools"] = [
            {"part": "a", "labels": ["M1", "M2", "M3", "M4"], "cap": 2,
             "reason": "line 278 'Any two for 1 each'"}]
        pts = _convert_atom_points(atom)
        heads = [p for p in pts if p["text"].startswith("[any 2 for 1 each]")]
        self.assertEqual(len(heads), 1)          # only the pool head, not the b-i M1
        self.assertEqual(heads[0]["questionRef"], "3-a")
        self.assertEqual(sum(p["marks"] for p in pts if p["questionRef"] == "3-a"), 4)


class LevelsTest(unittest.TestCase):
    def test_levels_single_point_keeps_sum_correct(self):
        atom = _atom()
        atom["markScheme"]["style"] = "levels"
        atom["markScheme"]["levels"] = {
            "maxMarks": 6,
            "bands": [
                {"level": 3, "markRange": {"min": 5, "max": 6}, "descriptor": "excellent"},
                {"level": 2, "markRange": {"min": 3, "max": 4}, "descriptor": "ok"},
                {"level": 1, "markRange": {"min": 1, "max": 2}, "descriptor": "weak"},
            ],
            "indicativeContent": ["mentions rust"],
        }
        pts = _convert_atom_points(atom)
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["marks"], 6)
        self.assertEqual(pts[0]["questionRef"], "3")
        self.assertIn("Level 3 (5-6): excellent", pts[0]["text"])
        self.assertIn("Indicative content: mentions rust", pts[0]["acceptance"])


class GuidanceAndMcqTest(unittest.TestCase):
    def test_guidance_merges_into_first_point_acceptance(self):
        atom = _atom()
        atom["markScheme"]["guidance"] = ["Accept any suitable scale."]
        pts = _convert_atom_points(atom)
        self.assertTrue(pts[0]["acceptance"][0].startswith("Guidance: Accept any suitable scale."))

    def test_mcq_correct_label_recorded(self):
        atom = _atom(type="mcq", parts=[
            {"id": "3a", "label": "a", "sub": None, "type": "mcq", "marks": 1,
             "commandWord": None, "prompt": [], "choices": [
                 {"label": "A", "md": "x"}, {"label": "B", "md": "y"}],
             "correct": ["B"], "answerLines": 0, "pages": [1]}])
        atom["markScheme"]["points"] = [
            {"id": "B1", "part": "a", "sub": None, "marks": 1, "md": "B",
             "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [2]}]
        pts = _convert_atom_points(atom)
        self.assertEqual(pts[0]["acceptance"], ["Correct answer: B"])


class EnvelopeTest(unittest.TestCase):
    def test_full_conversion_shape_and_identity(self):
        draft = convert(
            {"questions": [_atom()], "questionCount": 1, "totalMarks": 6,
             "marksVerified": True, "schema": "syllabai.pastpaper.atoms/1.1",
             "source": {"qp": "qp.pdf", "ms": "ms.pdf"}},
            "4ch0/past-papers/2012-01/4CH0-1C", IDENTITY)
        self.assertEqual(draft["schemaVersion"], SCHEMA_VERSION)
        self.assertTrue(draft["reviewRequired"])
        self.assertEqual(draft["extractionMethod"], EXTRACTION_METHOD)
        self.assertEqual(draft["paper"]["sessionLabel"], "January 2012")
        self.assertEqual(draft["paper"]["questionPaperDocumentId"], "qp-doc-id")
        self.assertEqual(draft["markScheme"]["sourceDocumentId"], "ms-doc-id")
        q = draft["questions"][0]
        self.assertEqual(q["externalRef"], "4ch0/past-papers/2012-01/4CH0-1C#q3")
        self.assertEqual(q["questionNumber"], "3")
        self.assertEqual(q["questionType"], "STRUCTURED")
        self.assertEqual(q["pageNumber"], 2)     # min over part pages
        self.assertEqual(q["marks"], 6)
        self.assertEqual(len(draft["markScheme"]["points"]), 4)

    def test_determinism_byte_identical(self):
        env = {"questions": [_atom()], "questionCount": 1, "totalMarks": 6,
               "marksVerified": True, "schema": "syllabai.pastpaper.atoms/1.1",
               "source": {"qp": "qp.pdf", "ms": "ms.pdf"}}
        a = json.dumps(convert(env, "d", IDENTITY), sort_keys=True)
        b = json.dumps(convert(env, "d", IDENTITY), sort_keys=True)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
