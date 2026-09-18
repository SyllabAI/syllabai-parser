"""v1.1 capability selftests (levels marking, MCQ correct labels, bbox shape).

Run:  python3 -m pdflane.tests_atoms_v11
Exit 0 = all green. These exercise the NEW v1.1 surfaces with synthetic
fixtures — the benchmark papers re-run separately (chemistry corpus contains
neither levels grids nor MCQ parts, so only synthetic fixtures can prove
these paths here).
"""
import unittest

from pdflane import emit_atoms, validate_atoms


def envelope(atoms, total):
    return {"schema": "syllabai.pastpaper.atoms/1.1",
            "source": {"qp": "qp.pdf", "ms": "ms.pdf"},
            "questionCount": len(atoms), "totalMarks": total,
            "marksVerified": True, "questions": atoms}


def ms_point(pid, part, marks, md):
    return {"id": pid, "part": part, "sub": None, "marks": marks, "md": md,
            "allow": [], "reject": [], "ignore": [], "notes": [], "pages": [1]}


def levels_bands():
    return [
        {"level": 3, "markRange": {"min": 5, "max": 6},
         "descriptor": "explanation covers both effects with correct chemistry"},
        {"level": 2, "markRange": {"min": 3, "max": 4},
         "descriptor": "explanation covers one effect"},
        {"level": 1, "markRange": {"min": 1, "max": 2},
         "descriptor": "simple statements with limited chemistry"},
    ]


def levels_ms():
    return {"totals": {"printed": 6, "sum": 6, "verified": True},
            "guidance": [], "points": [], "provenance": "pdf-parsed",
            "style": "levels",
            "levels": {"maxMarks": 6, "bands": levels_bands()}}


class DetectLevelsTests(unittest.TestCase):
    GUIDANCE = [
        "Marking grid — award the marks as follows:",
        "Level 3 (5\u20136 marks): explains both effects using correct chemistry",
        "and links them to the observations.",
        "Level 2 (3\u20134 marks): explains one effect only",
        "Level 1 (1\u20132 marks): simple statements, limited chemistry",
        "Do not accept reference to yield alone.",
    ]

    def test_three_bands_detected(self):
        lv = emit_atoms._detect_levels(self.GUIDANCE)
        self.assertIsNotNone(lv)
        self.assertEqual(lv["maxMarks"], 6)
        self.assertEqual([b["level"] for b in lv["bands"]], [3, 2, 1])
        self.assertEqual(lv["bands"][0]["markRange"], {"min": 5, "max": 6})
        # continuation line attaches to the preceding band
        self.assertIn("links them to the observations", lv["bands"][0]["descriptor"])

    def test_single_band_is_not_levels(self):
        self.assertIsNone(emit_atoms._detect_levels(
            ["Level 3 (5\u20136 marks): good answer"]))

    def test_no_bands(self):
        self.assertIsNone(emit_atoms._detect_levels(["accept any sensible answer"]))

    def test_build_mark_scheme_promotes_style(self):
        q = {"points": [], "guidance": [{"text": g} for g in self.GUIDANCE],
             "total_row": 6}
        ms = emit_atoms.build_mark_scheme(None, q)
        self.assertEqual(ms["style"], "levels")
        self.assertEqual(ms["totals"]["sum"], 6)
        self.assertTrue(ms["totals"]["verified"])


class McqLettersTests(unittest.TestCase):
    def test_patterns(self):
        f = emit_atoms._mcq_letters
        self.assertEqual(f("B"), ["B"])
        self.assertEqual(f("(c)"), ["c"])
        self.assertEqual(f("The correct answer is D"), ["D"])
        self.assertEqual(f("answer is: A"), ["A"])
        self.assertEqual(f("B is correct"), [])
        self.assertEqual(f("sodium hydroxide"), [])

    def test_build_document_extracts_correct(self):
        qp_atom = {"number": 1, "total": 1, "pages": {1}, "_stem_marks": [],
                   "stem": [], "parts": [{
                       "id": "1a", "label": "a", "sub": None, "type": "mcq",
                       "marks": 1, "commandWord": None,
                       "prompt": [{"type": "choices", "items": [
                           {"label": "A", "md": "chromatography"},
                           {"label": "B", "md": "condensation"}]}],
                       "answerLines": 0, "pages": [1]}]}
        ms_q = {"number": 1, "points": [{"label": "M1", "part": "a", "sub": None, "marks": 1,
                            "text": ["B"], "notes": [], "page": 1}],
                "guidance": [], "total_row": 1}
        doc = emit_atoms.build_document([qp_atom], [ms_q])
        self.assertEqual(doc["questions"][0]["parts"][0]["correct"], ["B"])

    def test_build_document_omits_nonderivable_correct(self):
        qp_atom = {"number": 1, "total": 1, "pages": {1}, "_stem_marks": [],
                   "stem": [], "parts": [{
                       "id": "1a", "label": "a", "sub": None, "type": "mcq",
                       "marks": 1, "commandWord": None,
                       "prompt": [{"type": "choices", "items": [
                           {"label": "A", "md": "chromatography"},
                           {"label": "B", "md": "condensation"}]}],
                       "answerLines": 0, "pages": [1]}]}
        ms_q = {"number": 1, "points": [{"label": "M1", "part": "a", "sub": None, "marks": 1,
                            "text": ["sodium hydroxide"], "notes": [], "page": 1}],
                "guidance": [], "total_row": 1}
        doc = emit_atoms.build_document([qp_atom], [ms_q])
        self.assertNotIn("correct", doc["questions"][0]["parts"][0])


class ValidatorTests(unittest.TestCase):
    def base_levels_doc(self):
        atom = {"number": 1, "type": "open", "marks": 6, "commandWord": None,
                "stem": [], "parts": [], "markScheme": levels_ms(),
                "provenance": "pdf-parsed"}
        return envelope([atom], 6)

    def test_levels_document_passes(self):
        self.assertEqual(validate_atoms.validate_document(self.base_levels_doc()), [])

    def test_levels_without_style_fails_v1(self):
        doc = self.base_levels_doc()
        del doc["questions"][0]["markScheme"]["style"]
        self.assertTrue(any(f.startswith("V1") for f in
                            validate_atoms.validate_document(doc)))

    def test_style_levels_without_levels_fails_v1(self):
        doc = self.base_levels_doc()
        del doc["questions"][0]["markScheme"]["levels"]
        self.assertTrue(any(f.startswith("V1") for f in
                            validate_atoms.validate_document(doc)))

    def test_band_range_inversion_fails_v2(self):
        doc = self.base_levels_doc()
        bands = doc["questions"][0]["markScheme"]["levels"]["bands"]
        bands[0]["markRange"] = {"min": 6, "max": 5}
        fs = validate_atoms.validate_document(doc)
        self.assertTrue(any("markRange min" in f for f in fs))

    def test_max_marks_mismatch_fails_v2(self):
        doc = self.base_levels_doc()
        doc["questions"][0]["markScheme"]["levels"]["maxMarks"] = 5
        fs = validate_atoms.validate_document(doc)
        self.assertTrue(any("levels.maxMarks" in f for f in fs))

    def test_legacy_tag_rejected(self):
        doc = self.base_levels_doc()
        doc["schema"] = "syllabai.pastpaper.atoms/1.0"
        fs = validate_atoms.validate_document(doc)
        self.assertTrue(any("unexpected schema tag" in f for f in fs))

    def mcq_doc(self, correct=None, ptype="mcq", md="B"):
        part = {"id": "1a", "label": "a", "sub": None, "type": ptype,
                "marks": 1, "commandWord": None,
                "prompt": [{"type": "choices", "items": [
                    {"label": "A", "md": "chromatography"},
                    {"label": "B", "md": "condensation"}]}],
                "answerLines": 0, "pages": [1]}
        if correct:
            part["correct"] = correct
        atom = {"number": 1, "type": "structured", "marks": 1, "commandWord": None,
                "stem": [], "parts": [part],
                "markScheme": {"totals": {"printed": 1, "sum": 1, "verified": True},
                               "guidance": [], "points": [ms_point("M1", "a", 1, md)],
                               "provenance": "pdf-parsed"},
                "provenance": "pdf-parsed"}
        return envelope([atom], 1)

    def test_mcq_correct_passes(self):
        self.assertEqual(validate_atoms.validate_document(self.mcq_doc(["B"])), [])

    def test_correct_on_open_part_fails(self):
        fs = validate_atoms.validate_document(self.mcq_doc(["B"], ptype="open"))
        self.assertTrue(any("carries correct" in f for f in fs))

    def test_correct_label_unknown_fails(self):
        fs = validate_atoms.validate_document(self.mcq_doc(["D"]))
        self.assertTrue(any("not in choices" in f for f in fs))

    def test_point_image_counts_for_v4(self):
        doc = self.mcq_doc(["B"])
        doc["questions"][0]["markScheme"]["points"][0]["image"] = \
            {"src": "assets/MS_p03_01.png", "pages": [3]}
        fs = validate_atoms.validate_document(doc, assets_dir=None)
        self.assertEqual(fs, [])  # V4 asset checks need a dir; shape check only


class RendererTests(unittest.TestCase):
    def test_ms_md_renders_levels(self):
        atom = {"number": 2, "type": "open", "marks": 6, "commandWord": None,
                "stem": [], "parts": [], "markScheme": levels_ms(),
                "provenance": "pdf-parsed"}
        out = emit_atoms.render_ms_md(envelope([atom], 6))
        self.assertIn("Levels-based marking (max 6 marks)", out)
        self.assertIn("**Level 3** (5\u20136 marks)", out)

    def test_ms_md_renders_ms_images(self):
        ms = levels_ms()
        ms["images"] = [{"src": "assets/MS_p03_01.png", "alt": "trajectory", "pages": [3]}]
        atom = {"number": 2, "type": "open", "marks": 6, "commandWord": None,
                "stem": [], "parts": [], "markScheme": ms, "provenance": "pdf-parsed"}
        out = emit_atoms.render_ms_md(envelope([atom], 6))
        self.assertIn("![trajectory](assets/MS_p03_01.png)", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
