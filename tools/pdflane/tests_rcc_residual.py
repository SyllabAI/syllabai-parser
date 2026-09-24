"""G1.3 RC-C letter-level residual fixture tests.

Every fixture replicates a layout shape observed in the downloaded corpus
(SyllabAI/Past-Papers) and pinned during the Task-40 RC-C drill
(workspace/rcc1_drill.json): 154 PART-MARKS-MISMATCH questions across 60
papers, dominated by MS-side misattribution (marks-cell bleeds, phantom
deferred points, lost empty-body opener rows, furniture-skipped MCQ
continuation pages). Evidence slugs are cited per test.
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


def _marks_col_line(left, marks, col=60):
    """Layout line with a marks digit ending exactly at column `col` (1-based
    end position), i.e. the digit occupies [col-1, col)."""
    body = left.rstrip()
    pad = col - 1 - len(body) - 1
    return body + " " * max(pad, 2) + marks


class OldSpecMarksCellBleed(unittest.TestCase):
    """4CH0 1C Jun 2012 q6(c)(i): accept-column text '12' poisoned a tail-less
    M-row (marks=12) and the merged cell '1' on the 'mass of isotopes'
    continuation spawned a phantom P2 ('on a scale where') instead of
    filling M2. True grid: M1=1, M2=1 (QP prints (c)(i)=2)."""

    def test_accept_text_digit_is_not_marks_and_merged_cell_fills_m2(self):
        lines = [
            " Question",
            "                                Expected Answer         Accept         Reject         Marks",
            " number",
            "6 (a)         M1 both protons = 6" + " " * 46 + "1",
            "              M2 C-13 has 7 and C-14 has 8 (neutrons)" + " " * 38 + "1",
            " (b)          same electronic configuration(s)     different number of     1",
            " (c)    (i)   M1 the average / mean mass of an atom  average/mean of:" + " " * 12 + "1",
            "              element)                               atomic masses /",
            "                                                     mass numbers /",
            _marks_col_line("                                                     mass of isotopes", "1", 60),
            "                                                     on a scale where",
            "                                    th",
            "              M2 compared to / relative to (1/12) the  carbon-12 has a mass of",
            "              (of an atom) of carbon-12" + " " * 14 + "12",
            "                                                     / compared with the",
            "                                                     mass of carbon-12",
            "              OR                                     which is 12",
            "                                                                                  Total 8",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 6][0]
        ci = [p for p in q["points"] if p["part"] == "c" and p["sub"] == "i"]
        self.assertEqual(len(ci), 2, "exactly M1+M2, no phantom point")
        self.assertEqual([p["marks"] for p in ci], [1, 1])
        self.assertNotIn(12, [p["marks"] for p in q["points"]],
                         "accept-text '12' must never become a marks cell")
        for p in q["points"]:
            self.assertNotIn("on a scale where", " ".join(p["text"]),
                             "the wrapped stem line must not become a point text")


class OldSpecDeferredSpawnPreserved(unittest.TestCase):
    """4CH0 2C Jan 2012 q1(b)(ii): 'proton number / 1' + 'with different
    masses' — the second marks cell of a two-mark block with NO labeled row
    in the lookahead window keeps the legacy deferred-point spawn."""

    def test_proton_number_deferred_point_survives(self):
        lines = [
            " Question",
            "                                Expected Answer         Accept         Reject         Marks",
            " number",
            "1 (a)" + " " * 80 + "4",
            "                Proton   Neutron   Electron",
            " 1 mark for each correct answer",
            " (b)   (i)    Protons AND electrons = 1        one" + " " * 24 + "1",
            "              neutrons = 2                     two" + " " * 24 + "1",
            " (b)   (ii)   atoms of the same element        atoms with same     1",
            "                                               number of protons /",
            _marks_col_line("                                               proton number", "1", 78),
            "              with different masses",
            "              Ignore references to electrons   with different mass",
            "                                               numbers / different",
            "                                                                                  Total 8",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 1][0]
        bii = [p for p in q["points"] if p["part"] == "b" and p["sub"] == "ii"]
        self.assertEqual(len(bii), 2, "deferred point + opener row both kept")
        self.assertEqual([p["marks"] for p in bii], [1, 1])


class NewSpecOpenerMarksRows(unittest.TestCase):
    """4CH1 1C Jan 2020 q4 / Jun 2021 q7: sub-part openers whose printed
    marks sit on the opener line with an empty answer body (a table or
    step rows follow). Previously unmatched -> whole sub-parts lost."""

    def test_qps_opener_with_marks_opens_aggregate(self):
        # '4 (a) (i)    3' + formula table below
        lines = [
            " Question",
            "                                Answer                Notes            Marks",
            " number",
            "4 (a) (i)" + " " * 52 + "3",
            "                 S2-   MgS   Al2S3   (NH4)2S",
            "                 1 mark for each correct formula",
            _marks_col_line("        (ii)   ammonium nitrate", "1", 60),
            "  (b)   (i)    M1 electrostatic (force of) attraction" + " " * 8 + "2",
            "               M2 between oppositely charged ions",
            "        (ii)" + " " * 52 + "3",
            "               M1 correct electron arrangement of both sodium ions",
            "               M2 correct electron arrangement of the oxide ion",
            "               M3 correct charges on all ions",
            "                                                                 Total 9",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 4][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("a", "i")], 3, "empty-body opener carries its marks")
        self.assertEqual(got[("a", "ii")], 1)
        self.assertEqual(got[("b", "i")], 2)
        self.assertEqual(got[("b", "ii")], 3)
        self.assertEqual(q["sum_points"], 9)
        self.assertTrue(q["arithmetic_ok"])

    def test_qn_solo_sub_row_with_content_and_marks(self):
        # '7   (ii)   • substitute ... 2' — question number + solo sub-part
        # + bullet content + marks cell (4CH1 1C Jun 2021 q7(b)(ii) p16)
        lines = [
            " Question",
            "                                Answer                Notes            Marks",
            " number",
            "7 (a) (i)     magnesium chloride + hydrogen    ACCEPT in either order" + " " * 4 + "1",
            "  (b)   (i)" + " " * 54 + "2",
            "                  temperature of the acid at the start    22.4",
            "                  highest temperature reached in oC       43.2",
            "7        (ii)      •   substitute correct values into Q = mcΔT"
            "    Correct answer of 2184" + " " * 4 + "2",
            "                  M1 Q = 25 x 4.2 x 20.8",
            "                  M2 2184 (J)",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 7][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("a", "i")], 1)
        self.assertEqual(got[("b", "i")], 2, "empty-body (b)(i) opener kept")
        self.assertEqual(got[("b", "ii")], 2, "qn + solo sub + content row kept")
        bi_ii = [p for p in q["points"] if p["part"] == "b"]
        self.assertEqual(sum(p["marks"] for p in bi_ii), 4, "letter b closes")

    def test_solo_sub_marks_at_answer_column_is_not_claimed(self):
        # '(ii)   3' with the digit at the ANSWER column (no established
        # marks column anywhere near) — an answer value, not a marks cell:
        # must keep the legacy handling (unscored/demoted), never marks=3.
        lines = [
            " Question",
            "                                Answer                Notes            Marks",
            " number",
            "2 (a)   (i)    some answer text" + " " * 32 + "1",
            "        (ii)   3",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 2][0]
        aii = [p for p in q["points"] if p["part"] == "a" and p["sub"] == "ii"
               and p["marks"] is not None]
        self.assertEqual(aii, [], "left-column digit must not score as marks")


class MCQContinuationPage(unittest.TestCase):
    """4CH1 1C Jun 2021 q6(b)(ii) p13: a page carrying only the MCQ answer
    row '(ii)  D yellow  1' + incorrect-option notes has no [MA] token, no
    total row and no grid header — it must NOT be skipped as furniture."""

    TEXT = ("(ii)   D yellow                                                  1\n"
            "\n"
            "       A is incorrect as sodium ions do not give a green flame\n"
            "       B is incorrect as sodium ions do not give a lilac flame\n")

    def test_mcq_answer_only_page_is_grid_content(self):
        self.assertTrue(parse_ms.is_grid_page(self.TEXT))

    def test_prose_page_without_marks_tail_stays_furniture(self):
        self.assertFalse(parse_ms.is_grid_page(
            "see section (ii) of the specification for details\n"))

    def test_mcq_answer_row_parses_after_page_recovery(self):
        p1 = (" Question\n"
              "                                Answer                Notes            Marks\n"
              " number\n"
              "6 (b)   (i)    An explanation linking two points" + " " * 4 + "2\n")
        r = parse_ms.parse_pages([pg(1, p1), pg(2, self.TEXT)])
        q = r["questions"][0]
        bii = [p for p in q["points"] if p["part"] == "b" and p["sub"] == "ii"]
        self.assertEqual(len(bii), 1)
        self.assertEqual(bii[0]["marks"], 1)
        self.assertIn("D yellow", bii[0]["text"])


if __name__ == "__main__":
    unittest.main()


class BareLetterNoTailRows(unittest.TestCase):
    """4CH0 1C Jan 2015 q1(c): a columnar bare-letter row with NO same-line
    marks cell ('c   isotopes' with the 3-mark cell on a wrapped line below)
    used to be dropped entirely — the cell was then claimed by the PREVIOUS
    letter's block as a phantom further-answer row (b-iii(3))."""

    TEXT = (" Question\n"
            "         Answer                          Notes        Marks\n"
            "number\n"
            "1 a                                                      1\n"
            "   b   i     A (an electron)                             1\n"
            "       ii    B (a neutron)                               1\n"
            "       iii   B (electrons and protons)                   1\n"
            "   c         isotopes\n"
            "             atomic numbers                              3\n"
            "             mass numbers\n"
            "                                                 Total 7 marks\n")

    def test_columnar_bare_row_opens_point_and_wrapped_cell_fills(self):
        r = parse_ms.parse_pages([pg(1, self.TEXT)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("a", None)], 1)
        self.assertEqual(got[("b", "iii")], 1, "b-iii keeps its own 1 mark")
        self.assertEqual(got[("c", None)], 3, "c opens and recovers its cell")
        self.assertEqual(q["sum_points"], 7)
        self.assertTrue(q["arithmetic_ok"])

    def test_prose_single_space_rows_stay_excluded(self):
        text = (" Question\n"
                "         Answer                          Notes        Marks\n"
                "number\n"
                "2 a    M1 some answer text                              1\n"
                "       a bit of prose wrapping the answer cell\n"
                "                                                Total 1 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        # the prose line must NOT open a phantom part row
        parts = {p["part"] for p in q["points"]}
        self.assertEqual(parts, {"a"}, f"only part a, got {parts}")


class DeferredCellStopsAtBlockBoundary(unittest.TestCase):
    """4CH0 1C Jun 2012 q4(d): the second mark cell ('ferric fluoride /
    FeF3   1') sits on a notes-column continuation line; the '(e)' block
    opener follows before any labeled row — the cell belongs to (d)'s own
    block (deferred spawn), never redirected across the boundary."""

    def test_second_d_point_survives(self):
        lines = [
            " Question",
            "                              Expected Answer       Accept       Reject       Marks",
            " number",
            "4 (d)      (fluorine reacts) vigorously / instantly /   the quickest   fluorine   1",
            "           violently / very quickly",
            "           IGNORE references to electron transfer",
            "                                              ferric fluoride / FeF3   1",
            "           (to form) iron(III) fluoride",
            "  (e)      M1 colourless (IGNORE clear)                 no colour      decolour   1",
            "           M2 orange / yellow /brown                    any colours    any other  1",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = r["questions"][0]
        d_pts = [p for p in q["points"] if p["part"] == "d"]
        self.assertEqual(len(d_pts), 2, "both (d) rows kept")
        self.assertEqual([p["marks"] for p in d_pts], [1, 1])
        e_pts = [p for p in q["points"] if p["part"] == "e"]
        self.assertEqual([p["marks"] for p in e_pts], [1, 1])


class Round3Col0BareOpeners(unittest.TestCase):
    """G1.3-r3: column-0 bare part openers.

    (1) Banner form — 'f   In part (f):' at the left margin with NO marks
        cell (4CH0 1C Jun 2015 q8 p21): a structural opener only; the scored
        rows below carry their own cells. Previously PART_BARE_RE demanded
        1-8 leading spaces, so the whole f block scored under e.
    (2) Scored form — 'd   i   silica ... 1' at the left margin (same paper
        q4-area p14): a real point with its own tail cell."""

    BANNER = (" Question\n"
              "         Answer                       Notes        Marks\n"
              "number\n"
              "8 e   (i)   UV (light)                               1\n"
              "       (ii)  bromomethane                            1\n"
              "f                                    In part (f):\n"
              "     i    M1   0.18 x 25 / 1000                      2\n"
              "     ii   0.0045                                     1\n"
              "                                             Total 6 marks\n")

    SCORED = (" Question\n"
              "         Answer                       Notes        Marks\n"
              "number\n"
              "4 c   i     aluminosilicates                         1\n"
              "d   i    silica / silicon dioxide / SiO2   Accept zeolites   1\n"
              "    ii    measured surface area                    1\n"
              "                                             Total 4 marks\n")

    def test_banner_row_is_structural_opener(self):
        r = parse_ms.parse_pages([pg(1, self.BANNER)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("f", "i")], 2, "f.i scored under f, not e")
        self.assertEqual(got[("f", "ii")], 1)
        self.assertNotIn(("e", "i"), {}, "no phantom re-labels")

    def test_col0_scored_row_creates_point(self):
        r = parse_ms.parse_pages([pg(1, self.SCORED)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("d", "i")], 1, "col-0 'd i' scored row kept")
        self.assertEqual(got[("d", "ii")], 1)
        self.assertEqual(got[("c", "i")], 1)


class Round3SoloOpeners(unittest.TestCase):
    """G1.3-r3: bare part letter ALONE ('b' solo, 4CH1 1C Jun 2019 q9(b)
    p13 — qn column empty on the page continuation) and paren part letter
    ALONE without a qn ('   (c)', 4CH0 1C Jan 2018 q12(c) p18)."""

    B_SOLO = (" Question\n"
              "         Answer                       Notes        Marks\n"
              "number\n"
              "9 a      M1 C 8.05 / 12                                   2\n"
              "   b\n"
              "          ACCEPT any combination of dots                 2\n"
              "          M1 all four bonding pairs correct\n"
              "                                             Total 6 marks\n")

    PAREN_SOLO = (" Question\n"
                  "         Answer                       Notes        Marks\n"
                  "number\n"
                  "12 (a) (i)   low AND because forward reaction is exo    1\n"
                  "  (b)      (the catalyst) increases both rates          1\n"
                  "  (c)\n"
                  "      (i)   M1 profile curve completed                  2\n"
                  "                                             Total 4 marks\n")

    def test_bare_letter_solo_opens_aggregate(self):
        r = parse_ms.parse_pages([pg(1, self.B_SOLO)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertIn(("b", None), got, "b aggregate opened")
        self.assertEqual(got[("a", None)], 2)
        self.assertLessEqual(q["sum_points"], 6, "no double-count")

    def test_paren_solo_without_qn_opens_block(self):
        r = parse_ms.parse_pages([pg(1, self.PAREN_SOLO)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("c", "i")], 2, "(c)(i) scored under c, not b")
        self.assertEqual(got[("b", None)], 1)


class Round3QnRomanSub(unittest.TestCase):
    """G1.3-r3: qn + bare roman sub lead with an EMPTY part column
    ('5   iv   oxygen / O2   1', 4CH0 1C Jun 2013 q5(a) p10 continuation)."""

    TEXT = (" Question\n"
            "         Answer                       Notes        Marks\n"
            "number\n"
            "5 a   i     haematite                                   1\n"
            "      ii    Al2O3                                       1\n"
            "      iii   carbon / C                                  1\n"
            "5     iv    oxygen / O2            Accept O             1\n"
            "            production of heat     DEP on oxygen        1\n"
            "                                             Total 5 marks\n")

    def test_qn_sub_lead_scores_under_open_part(self):
        r = parse_ms.parse_pages([pg(1, self.TEXT)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("a", "iv")], 1, "'5 iv' scored as a-iv")
        self.assertEqual(got[("a", "iii")], 1)
        self.assertEqual(q["sum_points"], 5)


class Round3CompactPartSub(unittest.TestCase):
    """G1.3-r3: compact part+sub opener with no space — '(c)(i) (Iron (III)
    oxide) loses oxygen   1' (4CH1 1CR Jan 2020 q11(c)(i) p18)."""

    TEXT = (" Question\n"
            "         Answer                       Notes        Marks\n"
            "number\n"
            "11 (a)   equation                                        2\n"
            "   (b) (i)   M1 Mass copper                              4\n"
            "       (c)(i)   (Iron (III) oxide) loses oxygen          1\n"
            "       (ii)  Carbon monoxide is poisonous                1\n"
            "                                             Total 8 marks\n")

    def test_compact_opener_splits_letter(self):
        r = parse_ms.parse_pages([pg(1, self.TEXT)])
        q = r["questions"][0]
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("c", "i")], 1, "(c)(i) under c")
        self.assertEqual(got[("c", "ii")], 1, "(c)(ii) under c")
        self.assertEqual(got[("b", "i")], 4)


class Round3ArabicOptions(unittest.TestCase):
    """G1.3-r3: parenthesized ARABIC option leads ('(2)'-'(5)', 4CH0 1C Jun
    2013 q8(b)) — scored under the open part with sub=None (the atoms schema
    types sub as roman only); the tail-less wrapped option recovers its cell
    via the end-of-parse resolution."""

    TEXT = (" Question\n"
            "         Answer                       Notes        Marks\n"
            "number\n"
            "8 (b)      (2)   time / how long                              1\n"
            "           (3)   number of chips                            1\n"
            "           (4)   volume of gas                              1\n"
            "           (5)   percentage\n"
            "                 concentration          Ignore volume        1\n"
            "                                             Total 4 marks\n")

    def test_arabic_options_scored_under_open_part(self):
        r = parse_ms.parse_pages([pg(1, self.TEXT)])
        q = r["questions"][0]
        b = [p for p in q["points"] if p["part"] == "b"]
        self.assertEqual(len(b), 4, f"four option rows, got {len(b)}")
        self.assertEqual(sum(p["marks"] or 0 for p in b), 4)
        for p in b:
            self.assertIsNone(p["sub"], "arabic option leads never become roman subs")


class Round3LoneCellBackwardFill(unittest.TestCase):
    """G1.3-r3: the lone-cell backward fill no longer demands an EMPTY
    point — 'M2 - 0.006' + lone '1' (4CH0 2C Jan 2013 q7(a)(i)): the second
    marks cell of the sub-part fills the tail-less M2 row above it."""

    TEXT = (" Question\n"
            "         Answer                       Notes        Marks\n"
            "number\n"
            "7 (a) (i)  M1 -                One mark for (144/24)=6    1\n"
            "           M2 -   0.006\n"
            "                                                      1\n"
            "      (ii) 0.006                                       1\n"
            "                                             Total 3 marks\n")

    def test_lone_cell_fills_text_bearing_m2(self):
        r = parse_ms.parse_pages([pg(1, self.TEXT)])
        q = r["questions"][0]
        ai = [p for p in q["points"] if (p["part"], p["sub"]) == ("a", "i")]
        self.assertEqual(sum(p["marks"] or 0 for p in ai), 2,
                         "M1 + recovered lone cell (two a-i rows)")
        self.assertEqual(len(ai), 2)
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("a", "ii")], 1)
        self.assertEqual(q["sum_points"], 3)
