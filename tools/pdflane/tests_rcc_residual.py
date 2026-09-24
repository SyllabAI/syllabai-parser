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
