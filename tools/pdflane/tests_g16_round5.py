"""G1.5 round-5 grammar fixture tests (R4-GRID cell attribution + R4-MCQ QP
sub-romans).

Every fixture replicates a layout shape pinned by the round-4 evidence cards
(records bench/evidence/g16-round4-cards-2026-09-25/, workspace cards dump):
the 13 R4-GRID marks-cell displacement cards and the 2 R4-MCQ QP sub-roman
cards (4ch1-1cr-202006:1, 4ch1-1c-202111:1 — periodic-table furniture digit
opens the atom prematurely, '(a)' swallows as body, MCQ sub-romans cascade
into a phantom letter 'i'). Evidence slugs cited per test.
"""
import json
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms, emit_atoms, parse_qp  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


def _cell(left, marks, col=100):
    """Layout line whose marks digit ends exactly at column `col`."""
    body = left.rstrip()
    pad = col - 1 - len(body)
    return body + " " * max(pad, 2) + marks


GRID_HEADER = [
    " Question",
    "                                Expected Answer         Accept         Reject         Marks",
    " number",
]


class OpenerAttachedLoneCellForward(unittest.TestCase):
    """4ch1-1c-202406:4 — (c)'s block cell '5' prints ABOVE the solo '(c)'
    opener (vertically centered merged cell). Backward fill stole it into the
    open b.ii M1 point (b 2->7, c 5->0). The lone-cell forward decision with
    the opener-block own-cell scan hands it to '(c)'."""

    def test_lone_cell_above_cellless_opener_forwards(self):
        lines = GRID_HEADER + [
            "4 (a)   (i)   24" + " " * 62 + "1",
            "        (ii)  M1 12 x 8 + 1 x 10 + 14 x 4 + 16 x 2" + " " * 29 + "2",
            "              M2 194",
            "  (b)  (i)    (simple) distillation" + " " * 43 + "1",
            _cell("        (ii)  A description that refers to two of the following", "2", 78),
            "              M1 (the condenser/X) cools the (ethanol) vapour",
            "              M2 so it condenses OR forms liquid (ethanol)",
            _cell("", "5", 78),
            "  (c)         M1 calcium bromide is a giant (ionic) lattice",
            "              M2 with many/strong electrostatic attractions",
            "              M3 caffeine has a simple molecular structure",
            "              M4 caffeine has weak intermolecular forces",
            "              M5 more energy is needed to break the attractions",
            "                                                                                        Total 12",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 4][0]
        b = sum(p["marks"] for p in q["points"] if p["part"] == "b" and p["marks"])
        c = sum(p["marks"] for p in q["points"] if p["part"] == "c" and p["marks"])
        self.assertEqual(b, 3, "b keeps its own 1+2; the '5' must not bleed back")
        self.assertEqual(c, 5, "the '5' is (c)'s opener-attached block cell")


class OwnCellGuardProtectsBackwardFill(unittest.TestCase):
    """r3 protection (G1.3-r3 evidence): a lone cell directly under a tail-less
    M2 row whose FOLLOWING opener block carries its own cell must still
    back-fill the open point — the forward decision must not fire."""

    def test_lone_cell_before_opener_with_own_cell_backfills(self):
        lines = GRID_HEADER + [
            _cell("7 (a)  (i)   M1 - n(Na) = 0.006 mol", "1", 78),
            "       (ii)  M2 - n(H2) = 1/2 x M1",
            _cell("", "1", 78),
            _cell("       (iii) M3 - vol. H2 = 24000 x M2", "1", 78),
            _cell("", "8", 78),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 7][0]
        aii = [p for p in q["points"] if p["part"] == "a" and p["sub"] == "ii"
               and p["marks"]]
        self.assertTrue(aii, "the lone cell fills the tail-less M2 row")
        self.assertEqual(aii[0]["marks"], 1)


class BareDigitQuestionTotal(unittest.TestCase):
    """4ch1-1c-202111:1 — the question total prints as a BARE right-column
    digit (black-box total). The lone '5' after (b) M2 was captured as a
    5-mark b point (b 2->7). When the digit equals the open question's
    running point sum and the next content is a new question header, it IS
    the total row."""

    def test_bare_total_digit_closes_question(self):
        lines = GRID_HEADER + [
            _cell("1 (a) (i)   A", "1", 78),
            _cell("      (ii)  C", "1", 78),
            _cell("      (iii) B", "1", 78),
            _cell(" (b)        M1 two different elements", "2", 78),
            _cell("", "5", 78),
            _cell("2   (a) (i)  fluorine has the fewest number of shells", "1", 78),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q1 = [x for x in r["questions"] if x["number"] == 1][0]
        b = sum(p["marks"] for p in q1["points"] if p["part"] == "b" and p["marks"])
        self.assertEqual(q1["total_row"], 5, "the bare digit is the total row")
        self.assertEqual(b, 2, "no phantom 5-mark b point")

    def test_same_sum_cell_before_part_opener_is_not_total(self):
        # 4ch1-2c-202001:2 — running sum equals the lone '1', but the next
        # content opens a further PART of the same question: marks cell, not
        # total. It must forward to the (b) opener.
        lines = GRID_HEADER + [
            _cell("2 (a)        fractional distillation", "1", 78),
            _cell("", "1", 78),
            _cell(" (b)        aircraft fuel/jet fuel/paraffin", "1", 78),
            _cell("", "11", 78),
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 2][0]
        a = sum(p["marks"] for p in q["points"] if p["part"] == "a" and p["marks"])
        b = sum(p["marks"] for p in q["points"] if p["part"] == "b" and p["marks"])
        self.assertEqual(a, 1)
        self.assertEqual(b, 1, "the lone '1' belongs to the (b) opener")


class RedirectedCellStepMaterialization(unittest.TestCase):
    """4ch0-1c-201401:11 — (d)'s M3 cell rides a deep note row two lines above
    the tail-less M3 row; the redirect hands it via pending, but the M3 row
    was then absorbed as an unscored STEP (its opener point was
    _from_deferred) and the pending expired: the end-of-parse merged-cell
    recovery filled b's guidance point instead (b 2->3, d 3->2). The step
    absorption now materializes the pending cell as the row's own point."""

    def test_pending_cell_becomes_deferred_point_at_step_row(self):
        lines = GRID_HEADER + [
            "11 (a)      oxidised AND gain of oxygen" + " " * 39 + "1",
            "  (b)      M1 more reactive than titanium" + " " * 37 + "1",
            "           M2 has displaced titanium" + " " * 41 + "1",
            "           M2 dep on M1",
            "  (c)      different/lower boiling point" + " " * 37 + "1",
            "  (d)      M1 high strength-to-weight ratio" + " " * 34 + "1",
            _cell("                                            high strength-to-weight ratio /", "1", 78),
            "           M2 (hip replacements) - non-toxic",
            _cell("                                                              not corrosive", "1", 78),
            "           M3 (propellers) - corrosion resistant",
            "                                                                                        Total 7",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 11][0]
        b = sum(p["marks"] for p in q["points"] if p["part"] == "b" and p["marks"])
        d = sum(p["marks"] for p in q["points"] if p["part"] == "d" and p["marks"])
        self.assertEqual(b, 2, "the recovery must not poison b's guidance row")
        self.assertEqual(d, 3, "M3's redirected cell materializes under d")


class GuidanceInterleavedScoredRow(unittest.TestCase):
    """4ch0-1c-201501:8 — 'M2 can be awarded' guidance inside the (f)(i)
    block orphans cur_point (the guidance guard resets it), so the following
    scored row 'by bacteria / microbes ... Ignore naturally / enzymes  1'
    sank into the guidance-continuation branch and f.i lost its second mark."""

    def test_scored_row_after_guidance_keeps_its_cell(self):
        lines = GRID_HEADER + [
            "8  f   i (polymer) breaks down / decomposes" + " " * 34 + "1",
            "                                                    Do not penalise compound",
            "                                                    If reference to not breaking down etc, only",
            "                                                    M2 can be awarded",
            "        by bacteria / microbes / microorganisms     Ignore naturally / enzymes" + " " * 2 + "1",
            "       ii  inert / unreactive / OWTTE" + " " * 41 + "1",
            "                                                                                        Total 10",
        ]
        r = parse_ms.parse_pages([pg(1, "\n".join(lines))])
        q = [x for x in r["questions"] if x["number"] == 8][0]
        fi = sum(p["marks"] for p in q["points"]
                 if p["part"] == "f" and p["sub"] == "i" and p["marks"])
        fii = sum(p["marks"] for p in q["points"]
                  if p["part"] == "f" and p["sub"] == "ii" and p["marks"])
        self.assertEqual(fi, 2, "the M2 row after the guidance keeps its cell")
        self.assertEqual(fii, 1)


class SoloOpenerShapeRecognition(unittest.TestCase):
    """G1.3-r3 solo opener forms must be visible to the lookahead helpers —
    '(c)' alone opens a part aggregate (4ch0-1c-2018 q12(c) precedent) and
    every block-boundary scan must see it (202406 q3/q4 '4'/'5' above a solo
    '(c)')."""

    def test_solo_forms_are_opener_shaped(self):
        for st in ["(c)", "   (d)", "b"]:
            self.assertTrue(parse_ms._is_opener_shaped(st), st)

    def test_non_openers_are_rejected(self):
        for st in ["", "by bacteria / microbes", "M2 dep on M1"]:
            # 'M2 dep on M1' IS a label row (LABEL_RE) — excluded here
            if st == "M2 dep on M1":
                continue
            self.assertFalse(parse_ms._is_opener_shaped(st), st)


class QpMcqSubRomanReanchor(unittest.TestCase):
    """4ch1-1cr-202006:1 / 4ch1-1c-202111:1 — the periodic-table inside cover
    carries bare group/period digits; the '1' at y~755 (below the footer band)
    opens atom 1 prematurely. The true '1 (a) ...' opener then absorbs as body
    text, part (a) never opens, and the MCQ sub-romans '(i)/(ii)/(iii)'
    cascade into a phantom letter 'i' (MS a.i/a.ii/a.iii become
    MS-POINT-UNKNOWN-PART). The re-anchor repair re-opens the atom on the
    question-number re-print."""

    @staticmethod
    def _blocks():
        # minimal pymupdf block stream replicating the 202006 layout order
        return [
            {"page": 1, "kind": "text", "text": "Cover page", "y0": 100.0},
            {"page": 2, "kind": "text", "text": "The Periodic Table of the Elements", "y0": 236.5},
            {"page": 2, "kind": "text", "text": "7", "y0": 103.8},
            {"page": 2, "kind": "text", "text": "1", "y0": 755.1},
            {"page": 2, "kind": "text", "text": "2", "y0": 798.0},
            {"page": 3, "kind": "text", "text": "Answer ALL questions.", "y0": 59.5},
            {"page": 3, "kind": "text",
             "text": "1\t (a)\t The box gives some methods used in the separation of mixtures.",
             "y0": 87.7},
            {"page": 3, "kind": "text",
             "text": "(i)\t Identify the method used to obtain pure water from sea water.",
             "y0": 213.1},
            {"page": 3, "kind": "text", "text": "(1)", "y0": 226.6},
            {"page": 3, "kind": "text",
             "text": "(ii)\t Identify the method used to separate the dyes in a food colouring.",
             "y0": 283.4},
            {"page": 3, "kind": "text", "text": "(1)", "y0": 297.0},
            {"page": 3, "kind": "text",
             "text": "(iii)\tIdentify the method used to obtain ethanol from a mixture",
             "y0": 353.7},
            {"page": 3, "kind": "text", "text": "(1)", "y0": 381.3},
            {"page": 4, "kind": "text",
             "text": "Total for Question 1 = 3 marks", "y0": 700.0},
        ]

    def test_reanchor_opens_part_a_with_sub_romans(self):
        atoms = emit_atoms.build_qp_atoms(self._blocks())
        q1 = [a for a in atoms if a["number"] == 1][0]
        letters = [(p["label"], p.get("sub")) for p in q1["parts"]]
        self.assertIn(("a", None), letters, "part (a) opens from the re-print")
        self.assertIn(("a", "i"), letters)
        self.assertIn(("a", "ii"), letters)
        self.assertIn(("a", "iii"), letters)
        self.assertNotIn(("i", None), letters, "no phantom letter 'i'")

    def test_crosscheck_parity_holds(self):
        atoms = emit_atoms.build_qp_atoms(self._blocks())
        qp_parse = parse_qp.parse_blocks(self._blocks())
        emit_atoms.crosscheck_qp(atoms, qp_parse)  # must not raise


if __name__ == "__main__":
    unittest.main()
