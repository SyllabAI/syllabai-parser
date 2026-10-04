"""G5 grid-layout lane fixture tests — the Total-row-conflict rule (the
T-C80 Lane-B recorded-NOT-fixed route-hint finding).

Print archaeology (first-hand, checksum-pinned corpus 7e027cad, manifest
sha256 verified): the T-C80 'route hint' framing was re-adjudicated — BOTH
`Route 1:   4` lines are REAL merged block cells (4CH0 2C Jun 2017 q5(c)
= 4 marks with the block footer `Total 15`; 4CH0 2C Jan 2017 q6(b) = 4
marks with NO Total row until q6's footer after 6(c)). The June-2017
over-sum mint (19 vs 15) is the standalone `Alternative Method` full-page
divider on p16 re-presenting q5(b)(ii) with the SAME printed cell 4.

G5 therefore: (1) tags points minted after a standalone 'Alternative
Method' divider line, and (2) demotes them ONLY at the question's Total
row when the over-sum is EXACTLY their marks sum and each tagged point
has exactly one earlier untagged twin (same part/sub, same marks) —
fail-closed on every gate. Fixtures replicate the REAL pages verbatim
(pdftotext -layout; PMT watermark kept for geometry). Companion to the
G2/G3/G4 packs.
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


JUN_HEADER = ("                                        Answer                    "
              "Notes                    Marks\nnumber                       \n")

# --- 4CH0/2C June 2017, print pin 6204523f... (corpus 7e027cad) -----------

JUN_P14 = JUN_HEADER + \
    ' Question\n' \
    '                                  Answer                                                Notes                 Marks\n' \
    ' number\n' \
    '5 (a)   (i)    CH3OH + O2 → CO + 2 H2O                         ACCEPT multiples and fractions                   2\n' \
    '\n' \
    '               M1 all formulae correct\n' \
    '               M2 correctly balanced\n' \
    '                                                               M2 DEP on M1\n' \
    '\n' \
    '        (ii)   thermal energy/heat (energy) lost to the        ACCEPT lost to atmosphere/beaker/thermometer     1\n' \
    '               surroundings/environment\n' \
    '                                                               ACCEPT evaporation of water/methanol\n'

JUN_P15 = JUN_HEADER + \
    '    Question                        Answer                                              Notes                    Marks\n' \
    '    number\n' \
    '5    (b)   (i)    M1 (Q =) 125 × 4.2 × 36                                                                          2\n' \
    '\n' \
    '                  M2 = 18 900 (J) /19 000 (J)                  ACCEPT answer in kJ if unit included\n' \
    '                                                               Correct final answer with no working scores 2\n' \
    '\n' \
    '           (ii)   M1 mass[CH3OH] = 84.7 – 83.2 OR 1.5 (g)                                                          4\n' \
    '\n' \
    '                  M2 n[CH3OH] = 1.5 ÷ 32 OR 0.046875 (mol)     ACCEPT any number of sig fig except 1, eg 0.047\n' \
    '\n' \
    '                  M4 ∆H = – 400 (kJ/mol)                       ACCEPT any number of sig fig, eg 403, 403.2\n' \
    '                                                               Correct final answer with no working scores 4\n'

JUN_P16 = JUN_HEADER + \
    'Alternative Method\n' \
    '\n' \
    ' Question                        Answer                                               Notes                 Marks\n' \
    ' number\n' \
    '\n' \
    ' 5   (b) (ii)   M1 mass[CH3OH] = 84.7 – 83.2 OR 1.5 (g)                                                       4\n' \
    '\n' \
    '                M2 18 900 ÷ 1.5 OR 12 600 OR 18 900 ÷ M1 ACCEPT any number of sig fig except 1, eg 0.047\n' \
    '\n' \
    '                M4 ∆H = – 400 (kJ/mol)                      ACCEPT M2 from (b)(i) ÷ M2 from (b)(ii)\n' \
    '                                                            Correct final answer with no working scores 4\n'

JUN_P17 = JUN_HEADER + \
    '    Question                       Answer                                          Notes                           Marks\n' \
    '    number\n' \
    '\n' \
    '5    (b)   (iii)   M1 oxygen/other reactant missing from                                                             2\n' \
    '                      methanol\n' \
    '\n' \
    '                   M2 product level / carbon dioxide and     ACCEPT product level should be below reactant level\n' \
    '                      water above reactant level\n'

JUN_P18 = JUN_HEADER + \
    'Question\n' \
    '                                    Answer                                               Notes                         Marks\n' \
    'number\n' \
    '5  (c)     Route 1:                                                                                                      4\n' \
    '\n' \
    '           M1 Σ(bonds broken) = (412 × 3) + 360 + 463 + (496 × 1.5)\n' \
    '\n' \
    '              OR 2803 (kJ/mol)\n' \
    '\n' \
    '           M2 Σ(bonds made)= (743 x 2) + (463 x 4)\n' \
    '\n' \
    '               OR 3338 (kJ/mol)                                       IGNORE negative sign\n' \
    '\n' \
    '           Route 2:\n' \
    '\n' \
    '           M1 Σ(bonds broken) = (412 × 3) + 360 + (496 × 1.5)\n' \
    '\n' \
    '               OR 2340 (kJ/mol)\n' \
    '\n' \
    '           M2 Σ(bonds made) = (743 x 2) + (463 x 3)\n' \
    '\n' \
    '               OR 2875 (kJ/mol)                                       IGNORE negative sign\n' \
    '\n' \
    '           M3 Correct calculation of difference between M1 and M2     IGNORE sign\n' \
    '\n' \
    '           M4 If M2 > M1 final answer must be negative                Expected final answer is -535\n' \
    '                                                                      Correct final answer with no working scores 4\n' \
    '                                                                                                               Total    15\n'

# --- 4CH0/2C January 2017, print pin d4690be6... (corpus 7e027cad) --------

JAN_P10 = JUN_HEADER + \
    'Question\n' \
    '                                 Answer                                 Notes               Marks\n' \
    ' number\n' \
    '6 (a) (i)     (to provide the) zymase/enzyme (that acts      ALLOW (to act as a) catalyst     1\n' \
    '              as a catalyst)                                 ALLOW to increase the rate\n' \
    '\n' \
    '      (ii)    (turns) milky / cloudy / turbid (then clear)                                    1\n' \
    '\n' \
    '      (iii)   30 ºC                                          ACCEPT any temperature,          1\n'

JAN_P11 = JUN_HEADER + \
    'Question\n' \
    '                                Answer                              Notes             Marks\n' \
    'number\n' \
    '  (b)      Route 1:                                                                    4\n' \
    '\n' \
    '           M1 Σ(bonds broken) =\n' \
    '\n' \
    '                348 + (5 x 412) + 360 + 463 + (3 x 496)\n' \
    '           OR\n' \
    '                4719 (kJ/mol)\n' \
    '\n' \
    '           M2 Σ(bonds made) = (4 x 743) + (6 x 463)\n' \
    '\n' \
    '           Route 2:\n' \
    '\n' \
    '           M1 Σ(bonds broken) =\n' \
    '\n' \
    '                348 + (5 x 412) + 360 + (3 x 496)\n' \
    '\n' \
    '           M2 Σ(bonds made) = (4 x 743) + (5 x 463)\n' \
    '\n' \
    '           M3 4719 – 5750 (kJ/mol) / M1 – M2\n' \
    '\n' \
    '           M4 ‒ 1031 (kJ/mol)                             Sign required\n' \
    '                                                          Correct answer with no\n' \
    '                                                          working scores 4\n'


class G5TotalRowConflict(unittest.TestCase):
    """G5: the Total-row-conflict rule on the verbatim June-2017 pages."""

    def test_reprint_demoted_and_route_cell_kept(self):
        # Evidence: Jun 2017 q5 — the p16 Alternative-Method reprint of
        # (b)(ii) carries the same printed cell 4; raw sum 19 vs printed
        # Total 15 (== QP). The demotion fires; the REAL (c) route cell 4
        # and the main (b)(ii) 4 survive; q5 closes at 15.
        r = parse_ms.parse_pages([pg(14, JUN_P14), pg(15, JUN_P15),
                                  pg(16, JUN_P16), pg(17, JUN_P17), pg(18, JUN_P18)])
        q5 = [q for q in r["questions"] if q["number"] == 5][0]
        self.assertEqual(q5["sum_points"], 15)
        self.assertEqual(q5["total_row"], 15)
        c_cell = [p for p in q5["points"]
                  if p.get("part") == "c" and p.get("marks") == 4]
        self.assertTrue(c_cell, "the REAL 5(c) Route-1 cell was demoted")
        b_mains = [p for p in q5["points"]
                   if p.get("part") == "b" and p.get("sub") == "ii"]
        self.assertEqual(len(b_mains), 1, "reprint survived as a point")
        receipt = q5.get("_total_row_conflict")
        self.assertIsNotNone(receipt, "no conflict receipt recorded")
        self.assertEqual(receipt["total_row"], 15)
        self.assertEqual(receipt["raw_sum"], 19)
        self.assertEqual(receipt["demoted"],
                         [{"label": "M1", "part": "b", "sub": "ii",
                           "marks": 4, "page": 16}])

    def test_demoted_text_preserved_in_guidance(self):
        # Zero-loss: the reprint's rows survive as question guidance.
        r = parse_ms.parse_pages([pg(14, JUN_P14), pg(15, JUN_P15),
                                  pg(16, JUN_P16), pg(17, JUN_P17), pg(18, JUN_P18)])
        q5 = [q for q in r["questions"] if q["number"] == 5][0]
        blob = " ".join(g["text"] for g in q5["guidance"])
        self.assertIn("alternative-method reprint", blob)
        self.assertIn("mass[CH3OH]", blob)

    def test_divider_recorded_in_unclassified_trail(self):
        # Accounting: the divider line keeps its own unclassified reason.
        r = parse_ms.parse_pages([pg(14, JUN_P14), pg(15, JUN_P15),
                                  pg(16, JUN_P16), pg(17, JUN_P17), pg(18, JUN_P18)])
        reasons = [u["reason"] for u in r["unclassified"]]
        self.assertIn("alternative-method-page-divider", reasons)

    def test_no_reprint_no_demotion(self):
        # Fail-closed baseline: with the Alternative-Method page ABSENT the
        # fixture sums to exactly the printed 15 (the artifact NEEDS the
        # reprint — nothing is demoted, no receipt exists).
        r = parse_ms.parse_pages([pg(14, JUN_P14), pg(15, JUN_P15),
                                  pg(17, JUN_P17), pg(18, JUN_P18)])
        q5 = [q for q in r["questions"] if q["number"] == 5][0]
        self.assertEqual(q5["sum_points"], 15)
        self.assertEqual(q5["total_row"], 15)
        self.assertIsNone(q5.get("_total_row_conflict"))
        self.assertTrue(q5["arithmetic_ok"])


class G5RouteCellWithoutTotalRow(unittest.TestCase):
    """G5 negative case (the T-C80 Jan-2017 6(b) proof): no Total row in
    the block — the `Route 1:   4` cell is REAL and must survive."""

    def test_jan2017_6b_route_cell_real(self):
        # Evidence: Jan 2017 q6(b) — `Route 1:   4` prints the block's
        # merged cell (QP 13 = 4 + 9); no Total row in the block.
        r = parse_ms.parse_pages([pg(10, JAN_P10), pg(11, JAN_P11)])
        q6 = [q for q in r["questions"] if q["number"] == 6][0]
        b_cell = [p for p in q6["points"]
                  if p.get("part") == "b" and p.get("marks") == 4]
        self.assertTrue(b_cell, "Jan-2017 6(b) Route-1 cell lost")
        self.assertIsNone(q6.get("_total_row_conflict"))

    def test_jan2017_full_question_closes_at_13(self):
        # Full-question control: q6 closes at the printed 13 with the
        # b-cell counted (a 3 + b 4 + c 6).
        c_page = JUN_HEADER + (
            "Question\n"
            "                                   Answer                              Notes                 Marks\n"
            " number\n"
            "6 (c) (i)     M1 32                                                                            2\n"
            "\n"
            "      (ii)    M1 & M2 Any two from:                                                            2\n"
            "\n"
            "      (iii)   Any two from:                                                                    2\n"
            "                                                                                     Total    13\n")
        r = parse_ms.parse_pages([pg(10, JAN_P10), pg(11, JAN_P11),
                                  pg(12, c_page)])
        q6 = [q for q in r["questions"] if q["number"] == 6][0]
        self.assertEqual(q6["sum_points"], 13)
        self.assertEqual(q6["total_row"], 13)


class G5FailClosedGates(unittest.TestCase):
    """G5: every reconciliation gate aborts the demotion fail-closed."""

    def _run(self, pages):
        r = parse_ms.parse_pages(pages)
        return [q for q in r["questions"] if q["number"] == 5][0]

    def base_pages(self, reprint_cell, main_cell="4"):
        # cell column 104 — right of the header-anchored marks floor (the
        # real prints carry cells at ~110 with the header at ~105)
        pad = " " * 60
        main = JUN_HEADER + (
            "5    (b)   (i)    M1 (Q =) 125 × 4.2 × 36" + pad + "%s\n"
            % main_cell)
        divider = JUN_HEADER + (
            "Alternative Method\n"
            "\n"
            " Question                        Answer                    Marks\n"
            " number\n"
            "\n"
            " 5   (b) (ii)   M1 mass[CH3OH] = 84.7 – 83.2 OR 1.5 (g)" + pad + "%s\n"
            % reprint_cell)
        closer = JUN_HEADER + (
            "5  (c)     Route 1:" + pad + "4\n"
            "" + pad + "Total    15\n")
        return [pg(15, main), pg(16, divider), pg(18, closer)]

    def test_oversum_not_explained_by_reprint_is_inert(self):
        # Gate (a): the reprint cell (3) does not explain the over-sum
        # (raw 4+3+4 = 11 vs Total 15 is UNDER — and any non-exact
        # attribution must not demote).
        q5 = self._run(self.base_pages("3"))
        self.assertIsNone(q5.get("_total_row_conflict"))
        self.assertEqual(len(q5["points"]), 3)  # main + reprint + (c) cell

    def test_reprint_without_twin_is_inert(self):
        # Gate (b): the reprint re-presents part (d)(ii) which the question never
        # printed before — no twin, no demotion.
        pad = " " * 60
        divider = JUN_HEADER + (
            "Alternative Method\n"
            "\n"
            " Question                        Answer                    Marks\n"
            " number\n"
            "\n"
            " 5   (d) (ii)   M1 mass[CH3OH] = 84.7 – 83.2 OR 1.5 (g)" + pad + "2\n")
        closer = JUN_HEADER + (
            "5  (c)     Route 1:" + pad + "4\n"
            "" + pad + "Total    15\n")
        main = JUN_HEADER + (
            "5    (b)   (i)    M1 (Q =) 125 × 4.2 × 36" + pad + "9\n")
        q5 = self._run([pg(15, main), pg(16, divider), pg(18, closer)])
        self.assertIsNone(q5.get("_total_row_conflict"))
        x_pts = [p for p in q5["points"] if p.get("part") == "d"]
        self.assertEqual(len(x_pts), 1, "untagged-guard demotion fired")

    def test_twin_marks_mismatch_is_inert(self):
        # Gate (b): the twin exists but its printed cell differs — no
        # demotion (ambiguous attribution).
        q5 = self._run(self.base_pages("4", main_cell="6"))
        self.assertIsNone(q5.get("_total_row_conflict"))
        b_pts = [p for p in q5["points"] if p.get("part") == "b"]
        self.assertEqual(len(b_pts), 2, "mismatch-twin demotion fired")


if __name__ == "__main__":
    unittest.main()
