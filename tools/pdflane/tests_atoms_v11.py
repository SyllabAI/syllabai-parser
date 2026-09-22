"""v1.1 capability selftests (levels marking, MCQ correct labels, bbox shape).

Run:  python3 -m pdflane.tests_atoms_v11
Exit 0 = all green. These exercise the NEW v1.1 surfaces with synthetic
fixtures — the benchmark papers re-run separately (chemistry corpus contains
neither levels grids nor MCQ parts, so only synthetic fixtures can prove
these paths here).
"""
import unittest

from pdflane import emit_atoms, gates, parse_ms, validate_atoms


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


class FurnitureImageTests(unittest.TestCase):
    STRIP = {"page": 3, "x0": -28.3, "y0": 34.4, "x1": -4.6, "y1": 796.1}

    def test_edge_strip_is_furniture(self):
        self.assertTrue(emit_atoms.is_furniture_image(self.STRIP))

    def test_real_figure_kept(self):
        self.assertFalse(emit_atoms.is_furniture_image(
            {"page": 5, "x0": 100, "y0": 120, "x1": 420, "y1": 330}))

    def test_small_sliver_kept(self):
        self.assertFalse(emit_atoms.is_furniture_image(
            {"page": 5, "x0": 0, "y0": 0, "x1": 10, "y1": 60}))

    def test_missing_or_bad_bbox_kept(self):
        self.assertFalse(emit_atoms.is_furniture_image(None))
        self.assertFalse(emit_atoms.is_furniture_image({"x0": "x"}))


def ms_grid_point(label, part, sub, marks, text):
    return {"label": label, "part": part, "sub": sub, "marks": marks,
            "text": [text], "notes": [], "page": 1}


class CorrectionsTests(unittest.TestCase):
    def qp_atom(self):
        return {"number": 3, "total": 13, "pages": {1}, "_stem_marks": [],
                "stem": [], "parts": []}

    def ms_q(self):
        return {"number": 3, "total_row": 11,
                "points": [ms_grid_point("M%d" % i, None, None, 1, "x")
                           for i in range(1, 14)],
                "guidance": []}

    def test_correction_fixes_misprinted_total_row(self):
        doc = emit_atoms.build_document([self.qp_atom()], [self.ms_q()],
                                        corrections={3: 13})
        q3 = doc["questions"][0]
        # G1 upgrade: verifiedAgainst records the QP-printed closure path that
        # fired before the correction was applied (additive disclosure key)
        self.assertEqual(q3["markScheme"]["totals"],
                         {"printed": 13, "sum": 13, "verified": True,
                          "verifiedAgainst": "qp-printed"})
        self.assertNotIn("flags", q3)
        self.assertTrue(doc["marksVerified"])

    def test_without_correction_flags_remain(self):
        doc = emit_atoms.build_document([self.qp_atom()], [self.ms_q()])
        q3 = doc["questions"][0]
        # G1 upgrade: the printed QP/MS total conflict stays disclosed, but
        # the point sum (13) closes against the QP printed total (13), so the
        # arithmetic is verified and MS-POINTS-DONT-CLOSE is not raised —
        # this is exactly the 4CH0 1C jan2012 q3 shape (MS prints 'Total 11',
        # cells and QP both say 13)
        self.assertNotIn("MS-POINTS-DONT-CLOSE", q3["flags"])
        self.assertIn("PRINTED-TOTAL-DISCREPANCY-QP-VS-MS", q3["flags"])
        self.assertTrue(doc["marksVerified"])

    def test_sum_closing_to_neither_source_still_fails(self):
        # a genuine arithmetic defect: the points close to no printed source
        # (sum 10 vs printed 11 vs QP 13)
        bad = self.ms_q()
        bad["points"] = [ms_grid_point("M%d" % i, None, None, 1, "x")
                         for i in range(1, 11)]
        doc = emit_atoms.build_document([self.qp_atom()], [bad])
        q3 = doc["questions"][0]
        self.assertIn("MS-POINTS-DONT-CLOSE", q3["flags"])
        self.assertFalse(doc["marksVerified"])

    def test_correction_never_touches_missing_ms(self):
        doc = emit_atoms.build_document([self.qp_atom()], [], corrections={3: 13})
        q3 = doc["questions"][0]
        self.assertIn("MS-QUESTION-MISSING", q3["flags"])
        self.assertIsNone(q3["markScheme"]["totals"]["printed"])


def pages(*texts):
    return [{"page": i + 1, "text": t} for i, t in enumerate(texts)]


class ParseMsLabellessTests(unittest.TestCase):
    def test_2021_style_totals_and_part_rows(self):
        r = parse_ms.parse_pages(pages(
            "  Question\n"
            "                    Answer                    Notes        Marks\n"
            "  number\n"
            "1        (a)   nitrogen            ALLOW N/N2        1\n"
            "\n"
            "         (b)   silicon/Si or phosphorus/P            1\n"
            "\n"
            "         (c)   73                                    1\n"
            "\n"
            "                      Total marks for Question 1 = 3\n"))
        self.assertEqual(len(r["questions"]), 1)
        q = r["questions"][0]
        self.assertEqual(q["total_row"], 3)
        self.assertEqual([(p["part"], p["marks"]) for p in q["points"]],
                         [("a", 1), ("b", 1), ("c", 1)])
        self.assertIn("ALLOW N/N2", q["points"][0]["notes"])
        self.assertTrue(q["arithmetic_ok"])
        self.assertEqual(r["total_rows_found"], 1)

    def test_split_total_2019_style(self):
        r = parse_ms.parse_pages(pages(
            "4 a           M1 (a compound containing the        ALLOW          1\n"
            "              elements/atoms) hydrogen and carbon\n"
            "                                                                           Total\n"
            "                                                                            4\n"))
        self.assertEqual(len(r["questions"]), 1)
        q = r["questions"][0]
        self.assertEqual(q["number"], 4)
        self.assertEqual(q["total_row"], 4)
        self.assertEqual(q["points"][0]["label"], "M1")

    def test_merged_cell_marks_recovery(self):
        r = parse_ms.parse_pages(pages(
            "2   (a)   first answer                                   1\n"
            "          ALLOW anything\n"
            "    (b)   second answer\n"
            "                                                                      Total 3\n"))
        q = r["questions"][0]
        self.assertEqual(q["total_row"], 3)
        self.assertEqual([(p["part"], p["marks"]) for p in q["points"]],
                         [("a", 1), ("b", 2)])
        self.assertTrue(q["arithmetic_ok"])

    def test_note_value_not_scored_point(self):
        r = parse_ms.parse_pages(pages(
            "1   (a)   answer one                                   1\n"
            "          ALLOW\n"
            "          M1 bromide solution\n"
            "                                                                      Total 1\n"))
        q = r["questions"][0]
        self.assertEqual(len(q["points"]), 1)
        self.assertIn("M1 bromide solution", q["points"][0]["notes"])

    def test_bare_part_rows_2014_style(self):
        r = parse_ms.parse_pages(pages(
            "1   a             cross in box C     (neutrons)            1\n"
            "\n"
            "    b   i         6                                         1\n"
            "\n"
            "        ii        14                                        1\n"
            "\n"
            "TOTAL                                                        3\n"))
        q = r["questions"][0]
        self.assertEqual(q["total_row"], 3)
        self.assertEqual([(p["part"], p["sub"], p["marks"]) for p in q["points"]],
                         [("a", None, 1), ("b", "i", 1), ("b", "ii", 1)])
        self.assertTrue(q["arithmetic_ok"])

    def test_roman_sub_inheritance(self):
        r = parse_ms.parse_pages(pages(
            "3 a           M1 white smoke         Accept ring            1\n"
            "  (ii)     A1   shift to right       Allow more ammonia     1\n"))
        q = r["questions"][0]
        self.assertEqual([(p["part"], p["sub"], p["label"]) for p in q["points"]],
                         [("a", None, "M1"), ("a", "ii", "A1")])

    def test_implicit_total_2024_style(self):
        # 4CH1 2024 dialect: 'total for question = N' — no question number in
        # the row; the total belongs to the currently open question.
        r = parse_ms.parse_pages(pages(
            "9   (a)   M1 answer nine one                            1\n"
            "        (b)   M2 answer nine two                            1\n"
            "                      total for question = 2\n"))
        self.assertEqual(len(r["questions"]), 1)
        q = r["questions"][0]
        self.assertEqual(q["number"], 9)
        self.assertEqual(q["total_row"], 2)
        self.assertEqual([(p["part"], p["marks"]) for p in q["points"]],
                         [("a", 1), ("b", 1)])
        self.assertTrue(q["arithmetic_ok"])
        self.assertEqual(r["total_rows_found"], 1)


class GateLayoutTotalTests(unittest.TestCase):
    def test_layout_totals_bare_variant(self):
        # 4CH1 2024 1C/2C MS dialect prints 'Total N' without 'marks';
        # the G1 layout-sequence scanner must see the same rows parse_ms
        # closes questions with (LAYOUT_TOTAL_BARE_RE).
        seq = gates.totals_from_layout([{"text": "Total 7\njunk\n"},
                                        {"text": "Total 9 marks\nTotal 10\n"}])
        self.assertEqual(seq, {1: 7, 2: 9, 3: 10})

    def test_g1_arithmetic_superseded_by_s2(self):
        # merged-marks-cell layout: deterministic layer undercounts points
        # (q2 arithmetic mismatch); a verified S2 run supersedes the check
        # while the raw mismatch stays on record + a review flag is raised.
        ms_parse = {"questions": [
            {"number": 1, "total_row": 5, "arithmetic_ok": True, "pages": {4},
             "points": [{"label": "M1", "marks": 5}]},
            {"number": 2, "total_row": 13, "arithmetic_ok": False, "pages": {5},
             "points": [{"label": "M1", "marks": 7}]}],
            "unclassified": [], "buckets": {"point": 0, "guidance": 0,
                                            "unclassified": 0, "continuation": 0}}
        qp_parse = {"questions": [{"number": 1, "total": 5, "orphan_total": False,
                                   "pages": {2}, "prompt": "p"},
                                  {"number": 2, "total": 13, "orphan_total": False,
                                   "pages": {3}, "prompt": "p"}],
                    "witnesses": [{"value": 18}]}
        eng = {"pdftotext_ms_pages": [{"text": "Total 5\nTotal 13"}]}
        base = dict(probe={}, qp_parse=qp_parse, ms_parse=ms_parse,
                    engine_texts=eng, assets_check={"refs": [], "existing": [],
                                                    "embedded": 0})
        g_fail = gates.run(**base)
        self.assertEqual(g_fail["gates"]["G1"]["verdict"], "FAIL")
        g_ok = gates.run(s2_arithmetic={"verified": True,
                                        "detail": {"perQuestion": {
                                            "2": {"effectiveSum": 13,
                                                  "totalRow": 13}}}}, **base)
        g1 = g_ok["gates"]["G1"]
        self.assertEqual(g1["verdict"], "PASS")
        self.assertEqual(g1["checks"]["ms_point_arithmetic"]["superseded_by"],
                         "s2-validated-run")
        self.assertEqual(g1["checks"]["ms_point_arithmetic"]["mismatch"], [2])
        codes = [f["code"] for f in g_ok["flags"]]
        self.assertIn("DETERMINISTIC-MS-ARITHMETIC-SUPERSEDED-BY-S2", codes)
        # unverified S2 result must NOT supersede
        g_bad = gates.run(s2_arithmetic={"verified": False, "detail": {}}, **base)
        self.assertEqual(g_bad["gates"]["G1"]["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
