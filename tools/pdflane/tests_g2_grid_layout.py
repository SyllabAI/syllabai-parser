"""G2 grid-layout lane fixture tests (G2.4 bare-row completion, G2.5 furniture
guard extension, G2.6 doubled-letter labels).

Every fixture replicates a layout shape observed in the downloaded corpus
(SyllabAI/Past-Papers) during the 2026-10-02 grid-layout lane; evidence page
provenance is cited per test. Companion to the G1.x packs (tests_g12_*,
tests_g16_round5, tests_g17_totals_variants).
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


HEADER = ("                                        Answer   Notes   Marks\n"
          "number                                                                       \n")


class G24BareLabelCompleteRows(unittest.TestCase):
    """A bare M/A label row that already carries its marks tail AND answer
    body on the SAME line is a complete row, never a split label.
    Evidence: 4CH0 2CR Jun 2016 q1(a)/q3(b); 4CH0 1C Jun 2015 q7(a)/(b)."""

    def test_opener_a_row_with_parenthetical_answer_is_a_point(self):
        # 4CH0 2CR Jun 2016 q1(a) p4 — was silently swallowed by the pending
        # machinery when the next line was not a digit line
        r = parse_ms.parse_pages([pg(1, HEADER +
            "1   a         A    (the crystal dissolves)                 1\n")])
        q1 = r["questions"][0]
        self.assertEqual(len(q1["points"]), 1)
        pt = q1["points"][0]
        self.assertEqual(pt["marks"], 1)
        self.assertEqual(pt["part"], "a")
        self.assertEqual(pt["text"], "(the crystal dissolves)")

    def test_mid_question_a_row_with_parenthetical_answer_is_a_point(self):
        # 4CH0 1C Jun 2015 q7(a)/(b) — '(addition)' / '(a molecule used to
        # make a polymer)' were lost, letter sums 7 vs 9
        r = parse_ms.parse_pages([pg(1, HEADER +
            "7   a        A    (addition)                                                                                 1\n"
            "    b        A    (a molecule used to make a polymer)                                                        1\n")])
        q7 = r["questions"][0]
        self.assertEqual(sum(p["marks"] for p in q7["points"]), 2)
        self.assertEqual(q7["points"][0]["text"], "(addition)")
        self.assertEqual(q7["points"][1]["text"],
                         "(a molecule used to make a polymer)")

    def test_label_split_layout_still_pends_without_same_line_tail(self):
        # the genuine label-split layout (bare 'M' on the row with its text,
        # digit on the NEXT line — 4CH0 2012+ family) must keep the pending
        # path: no same-line tail means the row is NOT complete, and the
        # completion must still land the point with the digit as its marks
        # documented split shape: bare 'M' on the row (4CH0 2012+), its digit
        # on the next; marks recovered against the printed total row
        r = parse_ms.parse_pages([pg(1, HEADER +
            "1   a         M\n"
            "2\n"
            "                                                                 Total 2 marks\n")])
        q1 = r["questions"][0]
        self.assertEqual(q1["total_row"], 2)
        pts = [p for p in q1["points"] if p.get("marks") is not None]
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["marks"], 2)
        self.assertEqual(pts[0]["label"], "M2")


class G25BareContinuationPages(unittest.TestCase):
    """A short continuation page holding ONLY bare column-0 part rows is grid
    content, never furniture.
    Evidence: 4CH0 1C Jun 2015 q11(c) p29; 4CH0 1CR Jun 2016 q10 p20."""

    def test_bare_col0_part_row_page_is_grid_page(self):
        # 4CH0 1C Jun 2015 p29 — whole page was furniture-skipped, q11(c)'s
        # 1-mark row lost (letter sum 10 vs 11)
        text = ("                                                                                                           PMT\n"
                "\n"
                "c   ∆H (value)/enthalpy change is small / smaller   Accept energy in place of enthalpy                 1\n"
                "    / less (than for reactions 1 and 3)             Accept closer to zero\n"
                "    OR                                              Reject ∆H less negative / less exothermic\n")
        self.assertTrue(parse_ms.is_grid_page(text))

    def test_prose_lines_with_single_space_stay_furniture(self):
        # the 'a box . If you change your mind' front-matter prose must NOT
        # flip a page to grid content
        text = ("Answer all questions. Some questions must be answered with a cross in\n"
                "a box . If you change your mind about an answer put a line through the\n")
        self.assertFalse(parse_ms.is_grid_page(text))

    def test_qnless_part_row_parses_after_the_page_flip(self):
        # with the page admitted, the col-0 bare part row scores under the
        # open question (sequential guard: next letter of the open part)
        r = parse_ms.parse_pages([
            pg(1, HEADER +
               "11   b   i    (temperature) high                                                                                      1\n"),
            pg(2, "                                                                                                           PMT\n"
                  "\n"
                  "c   enthalpy change is small / smaller   Accept energy in place of enthalpy                 1\n"),
        ])
        q11 = next(q for q in r["questions"] if q["number"] == 11)
        self.assertEqual(q11["sum_points"], 2)


class G26DoubledLetterLabels(unittest.TestCase):
    """Regional-variant bold rendering duplicates the part letter in the label
    position ('bb' for a bold 'b').
    Evidence: 4CH0 2CR Jun 2016 q1(b) p4 — row was unclassified, q1 sum 2 vs 4."""

    def test_doubled_letter_row_is_a_part_row(self):
        r = parse_ms.parse_pages([pg(1, HEADER +
            "1   a         A    (the crystal dissolves)                 1\n"
            "    bb        A    (it is all blue)                        1\n"
            "    c    i    4                                            1\n"
            "         ii   21                                           1\n")])
        q1 = r["questions"][0]
        self.assertEqual(q1["sum_points"], 4)
        parts = [(p["part"], p["sub"]) for p in q1["points"]]
        self.assertIn(("b", None), parts)

    def test_prose_doubled_letters_untouched(self):
        # mid-line doubled letters with a single following space never match
        r = parse_ms.parse_pages([pg(1, HEADER +
            "1   a         A    the bb code list                       1\n")])
        q1 = r["questions"][0]
        self.assertEqual(len(q1["points"]), 1)
        self.assertIn("bb", q1["points"][0]["text"])


if __name__ == "__main__":
    unittest.main()
