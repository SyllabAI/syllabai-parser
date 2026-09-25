"""G1.7 totals-variant fixture tests (rw-11 re-gate grammar round).

Every fixture replicates a layout shape observed in the 15 corrected 4CH1
C-papers (workspace/pp_verify/reparse/, F10 repair corpus) that left G1
marks-integrity FAILING on parser a881b3b:

  - Jan-2021/Jan-2022 grids print the question total as a BARE '6 marks'
    line at the table end — no 'Total' word (1C/2C Jan 2021, 1C/2C Jan 2022;
    every question of those papers lost its total row).
  - Jan-2022 grids print the implicit total WITH a trailing 'marks' word
    ('Total for question = 9 marks', 1C Jan 2022 p3) which
    TOTAL_IMPLICIT_RE's bare-digit form never matched.
  - The bare line shape is otherwise IDENTICAL to a wrapped guidance phrase
    ('... without working scores' / '5 marks' in the note column, 1C Jan
    2022 q11(b) p15) — the dual guard (header-anchored marks column OR
    page-tail position) must reject the note wrap.
  - Jan-2020 grids print answer-table digits ('number of the group that   2'
    — group number 2, column 59) that the first-acceptance marks-column
    establishment poisoned into point marks (q2 parsed sum 13 vs printed 8);
    the header-anchored floor rejects them.
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms, gates  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


HEADER = [
    " Question",
    "                                    Answer                                 Notes           Marks",
    " number",
]
# 'Marks' token column in HEADER (0-based):
MARKS_COL = HEADER[1].index("Marks")
FLOOR_OK = MARKS_COL - parse_ms.MARKS_COL_SLACK  # leftmost accepted digit col


def at(col, text):
    """Layout line whose first character sits at 0-based column `col`."""
    return " " * col + text


class BareMarksOnlyTotalRow(unittest.TestCase):
    """4ch1-1c-202101 p3 tail: the question total prints as a bare '6 marks'
    line — the LAST content line of the page, no 'Total' word. Closes the
    open question by sequence."""

    def test_bare_marks_line_closes_question(self):
        lines = HEADER + [
            "1 (a)                                                         Award 1 mark for each      3",
            "                      Start                      End          correct row",
            "                      solid                     liquid",
            "                      solid                       gas         ALLOW gas to solid for",
            at(FLOOR_OK, "   (b)      A description that refers to any three of the") + "  3",
            "            following points",
            "            M1 irregular /random arrangement (of particles)",
            "            M2 large gaps between them /far apart /widely     ALLOW spread out",
            "            M3 random movement / move freely",
            "            M4 move (very) quickly                            IGNORE references to",
            at(FLOOR_OK, "kinetic energy"),
            at(MARKS_COL - 2, "6 marks"),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 1][0]
        self.assertEqual(q["total_row"], 6, "bare '6 marks' closes the question")
        self.assertEqual(q["sum_points"], 6, "3 + 3 per-part cells")
        self.assertTrue(q["arithmetic_ok"])

    def test_bare_marks_line_at_marks_column_mid_page(self):
        # not the page's last line (furniture blank + PMT follow) but at the
        # header-anchored marks column — accepted via the column guard
        # (genuine: table ends mid-page, next table starts after blanks)
        lines = HEADER + [
            "1 (a)     M1 answer one" + " " * (MARKS_COL - 25) + "1",
            "          M2 answer two" + " " * (MARKS_COL - 26) + "1",
            at(MARKS_COL - 2, "2 marks"),
            "",
            "",
            "PMT",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 1][0]
        self.assertEqual(q["total_row"], 2, "column-anchored bare total accepted")


class NoteWrapIsNotTotal(unittest.TestCase):
    """4ch1-1c-202201 q11(b) p15: '... without working scores' / '5 marks' is
    a wrapped guidance phrase in the NOTE column. It fails BOTH guards (note
    column is left of the header-anchored marks floor; the line is not the
    page's last content) — it must never close the question. The genuine
    implicit total 'Total for question = 12 marks' further down the page
    closes it instead."""

    def test_scores_wrap_does_not_close_question(self):
        lines = HEADER + [
            "11 (a) (i)      M1 add anhydrous copper sulfate" + " " * 10 + "ALLOW add white               2",
            "                M5 Volume H2O 5.6 cm3                                Must be 1dp",
            at(69, "ALLOW M4 to 1dp"),
            at(69, "Correct answer of 5.6"),
            at(69, "cm3 to 1dp with or"),
            at(69, "without working scores"),
            at(69, "5 marks"),
            "   (c)   (i)    1.7                                                  ALLOW 2 or more               1",
            at(0, "Total for question = 12 marks"),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 11][0]
        self.assertEqual(q["total_row"], 12, "implicit total closes; the wrap must not")
        self.assertNotIn(
            5, [p["marks"] for p in q["points"]],
            "the note-wrap '5 marks' must not become a 5-mark point")


class ImplicitTotalWithMarksSuffix(unittest.TestCase):
    """4ch1-1c-202201 p3: 'Total for question = 9 marks' — the trailing
    'marks' word made TOTAL_IMPLICIT_RE (bare-digit form) miss every Jan-2022
    total row; all questions lost closure (missing [1..11] except the two
    bare-digit pages)."""

    def test_implicit_total_with_marks_suffix(self):
        lines = HEADER + [
            "1 (a)    M1 answer" + " " * (MARKS_COL - 19) + "2",
            at(0, "Total for question = 9 marks"),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 1][0]
        self.assertEqual(q["total_row"], 9)

    def test_implicit_total_bare_digit_still_matches(self):
        # 4ch1-1c-202301 p3: 'Total for question = 6' (no marks word) — the
        # pre-existing TOTAL_IMPLICIT_RE shape must keep working
        lines = HEADER + [
            "1 (a)    M1 answer" + " " * (MARKS_COL - 19) + "2",
            at(0, "Total for question = 6"),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 1][0]
        self.assertEqual(q["total_row"], 6)


class HeaderFloorRejectsAnswerDigits(unittest.TestCase):
    """4ch1-1c-202001 q2 p4: the answer table prints 'number of the group
    that   2' (group number 2) and 'number of the period that   3' at column
    ~59; the first-acceptance marks-column establishment poisoned these into
    point marks (q2 parsed sum 13 vs printed 8). The header-anchored floor
    rejects them; the real merged cell '5' at the marks column fills 2(a),
    and (b)'s cell '3' completes the question: 5 + 3 = 8."""

    def test_answer_table_digits_are_not_marks(self):
        lines = HEADER + [
            "2 (a)",
            at(16, "name of the part of the atom            nucleus"),
            at(16, "number of protons in this                  12"),
            at(16, "atom"),
            at(16, "number of the group that                   2"),
            at(16, "contains this element"),
            at(16, "number of the period that                  3"),
            at(16, "contains this element") + " " * (MARKS_COL - 37) + "5",
            at(16, "charge on the ion formed from              2+"),
            at(16, "this atom                                          ACCEPT +2 / Mg2+"),
            "  (b)           calculate sum of mass numbers multiplied by",
            "                     percentage abundances",
            at(12, "M1 (24 x 79.2) + (25 x 10.8) OR 2431.6     REJECT wrong working"),
            at(12, "M2 2431.6 divided by 100 OR 24.316") + " " * (MARKS_COL - 47) + "3",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 2][0]
        marks = [p["marks"] for p in q["points"]]
        self.assertNotIn(
            2, marks,
            "answer-table digit '2' (group number) must never become marks")
        self.assertEqual(q["total_row"], None,
                         "no total row in this fixture slice")
        self.assertEqual(sorted(m for m in marks if m), [3, 5],
                         "merged cell 5 fills (a); (b)'s cell is 3")


class LayoutScannerMirrorsParse(unittest.TestCase):
    """gates.totals_from_layout must see the same total rows the parser
    closes questions with — the base-layer witness previously scanned only
    'Total N [marks]' and went EMPTY on the 2020-11..2023 grids."""

    def test_implicit_sequence(self):
        # 4ch1-1c-202301: 'Total for question = N' / '= N marks' only
        text = "\n".join(HEADER + [
            "1 (a)    answer" + " " * (MARKS_COL - 16) + "6",
            at(0, "Total for question = 6"),
            "2 (a)    answer" + " " * (MARKS_COL - 16) + "7",
            at(0, "Total for question = 7 marks"),
        ])
        self.assertEqual(gates.totals_from_layout([pg(1, text)]), {1: 6, 2: 7})

    def test_split_total(self):
        # 4ch1-1c-202001 p11: 'Total' alone, value on the next line
        text = "\n".join(HEADER + [
            "2 (b)    M1 working" + " " * (MARKS_COL - 19) + "3",
            at(69, "Total"),
            at(71, "12"),
            at(0, " Question"),
        ])
        self.assertEqual(gates.totals_from_layout([pg(1, text)]), {1: 12})
        # (the '3' tail is a marks cell — the scanner counts total rows only)

    def test_bare_marks_page_tail_and_column(self):
        # page-tail guard: last content line of the page (no header on a
        # sparse continuation page, total squeezed left — 4ch1-1c-202101 p9)
        text = "\n".join([
            "PMT",
            "M8 solution turns brown",
            "with potassium iodide",
            at(31, "9 marks"),
        ])
        self.assertEqual(gates.totals_from_layout([pg(1, text)]), {1: 9})
        # column guard: mid-page at the marks column (header page)
        text2 = "\n".join(HEADER + [
            "3 (a)    M1 working" + " " * (MARKS_COL - 19) + "4",
            at(MARKS_COL - 2, "10 marks"),
            "",
            "PMT",
        ])
        self.assertEqual(gates.totals_from_layout([pg(1, text2)]), {1: 10})
        # (the M1 row's '4' is a marks CELL, not a total row — never counted)

    def test_note_wrap_rejected_by_scanner(self):
        # the note-column wrap fails both guards — never a total
        lines = HEADER + [
            "11 (a) (i)      M1 add anhydrous copper sulfate" + " " * 10 + "ALLOW add white               2",
            at(69, "without working scores"),
            at(69, "5 marks"),
            "   (c)   (i)    1.7                                                  ALLOW 2 or more               1",
            at(0, "Total for question = 12 marks"),
        ]
        self.assertEqual(gates.totals_from_layout([pg(1, "\n".join(lines))]),
                         {1: 12})

    def test_numbered_total_variant(self):
        # 4ch1-2c-202011 (Nov-2020 COVID): 'Total for Q1 = 5' — the value
        # carries its own question number
        text = "\n".join(HEADER + [
            "1 (a)    answer" + " " * (MARKS_COL - 16) + "5",
            at(0, "Total for Q1 = 5"),
            at(0, "Total for Q2 = 7"),
        ])
        self.assertEqual(gates.totals_from_layout([pg(1, text)]), {1: 5, 2: 7})

    def test_explicit_total_still_scanned(self):
        # 4ch1-1c-201906/202001 'Total 6' / 202206 'Total 10' shapes unchanged
        text = "\n".join(HEADER + [
            "1 (a)    M1 answer" + " " * (MARKS_COL - 19) + "6",
            at(86, "Total 6"),
            "2 (a)    M1 answer" + " " * (MARKS_COL - 16) + "8",
            at(86, "Total 8 marks"),
        ])
        self.assertEqual(gates.totals_from_layout([pg(1, text)]), {1: 6, 2: 8})


class SqueezedScanOpenerShapes(unittest.TestCase):
    """4ch1-1c-201906 (the corpus's one degraded-text-layer paper — pdftotext
    squeezed the question/part/sub column gaps): compact no-space openers
    '10ai     M1 ...' / 'bi      (C5H12 ...', deep-indented sub openers
    ('         ii   A description ... 2', 9-12 spaces), column-0 continuation
    sub openers ('iii   An explanation ... 3' on a page-turn), and the solo
    sub opener whose only content is its merged marks cell ('   ii
    <blank-filled>   2'). Together these carried q10 (sum 5 vs 7) and q11
    (sum 6 vs 9) into ms_point_arithmetic FAIL."""

    HEADER_2019 = [
        "Question                       Answer                           Notes              Marks",
        "number",
    ]

    def _q10_page(self):
        return [
            "                                                                                           PMT",
            "Question                       Answer                           Notes              Marks",
            "number",
            "  10ai     M1 (compounds/molecules) with the same       ACCEPT same number          2",
            "              molecular formula                         and same type of",
            "                                                        atoms",
            "           M2 but with different structural/displayed   ACCEPT different",
            "           formula                                      structures",
            "   ii                                                                               2",
            "           M1 correct carbon skeleton",
            "           M2 all hydrogen atoms and all bonds shown",
            "   bi      (C5H12 + Br2) C5H11Br + HBr                  deduct 1 mark if cases      2",
            "   ii      substitution                                                             1",
            "                                                                           Total    7",
        ]

    def test_q10_compact_openers_close_arithmetic(self):
        r = parse_ms.parse_pages([pg(1, "\n".join(self._q10_page()))])
        q = [x for x in r["questions"] if x["number"] == 10][0]
        self.assertEqual(q["total_row"], 7)
        self.assertEqual(q["sum_points"], 7,
                         "a(i) 2 + a(ii) 2 + b(i) 2 + b(ii) 1")
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("a", "i")], 2, "QPART_COMPACT '10ai' opens a(i)")
        self.assertEqual(got[("a", "ii")], 2,
                         "solo 'ii' with a lone cell carries the merged cell")
        self.assertEqual(got[("b", "i")], 2, "PART_COMPACT 'bi' opens b(i)")
        self.assertEqual(got[("b", "ii")], 1)

    def test_deep_and_col0_sub_openers(self):
        # q11: '         ii   ...  2' (9-space sub opener, p15) and the
        # page-turned col-0 'iii   ...  3' (p16) — both must open sub blocks
        p15 = "\n".join(self.HEADER_2019 + [
            "11   a             calculate moles of methane                               2",
            "     b   i    An explanation that links together the following",
            "              M1 the water vapour/steam condenses                           2",
            "         ii   A description that links together the following two                           2",
        ])
        p16 = "\n".join([
            "PMT",
            "iii   An explanation that links together the following                         3",
            "      three points:",
            "      M1 the limewater turns milky                       ACCEPT cloudy",
            "                                                                       Total   9",
        ])
        r = parse_ms.parse_pages([pg(15, p15), pg(16, p16)])
        q = [x for x in r["questions"] if x["number"] == 11][0]
        self.assertEqual(q["total_row"], 9)
        self.assertEqual(q["sum_points"], 9, "a 2 + b(i) 2 + b(ii) 2 + b(iii) 3")
        got = {(p["part"], p["sub"]): p["marks"] for p in q["points"]}
        self.assertEqual(got[("b", "ii")], 2, "SUB_DEEP 'ii' opener")
        self.assertEqual(got[("b", "iii")], 3, "SUB_COL0 'iii' continuation opener")

    def test_solo_sub_digit_rest_is_cell_not_body(self):
        # the lone digit on the 'ii' opener row is the merged cell — it must
        # never become the point's body text
        r = parse_ms.parse_pages([pg(1, "\n".join(self._q10_page()))])
        q = [x for x in r["questions"] if x["number"] == 10][0]
        aii = [p for p in q["points"] if p["part"] == "a" and p["sub"] == "ii"]
        self.assertEqual(len(aii), 1)
        self.assertEqual(aii[0]["marks"], 2)
        self.assertEqual(" ".join(aii[0]["text"]).strip(), "",
                         "the cell digit must not leak into the point body")


if __name__ == "__main__":
    unittest.main()
