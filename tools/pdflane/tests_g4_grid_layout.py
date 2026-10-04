"""G4 grid-layout lane fixture tests (G4.1 colon-chain tails are data;
G4.2 'allow alternative method' OR-route boundary stops the pending-cell
hand-off).

Fixtures replicate the REAL 4CH0 1CR Jun 2016 q7 pages 12-13 layout
verbatim (pdftotext -layout, PMT watermark line kept for geometry) from
the checksum-pinned corpus print (manifest sha256 cfe40a1b..., print
substrate pin 1f7e8355). Printed QP total for q7 = 12 ('2+1+1+2+1+3+2').
Companion to the G2/G3 packs.
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


HEADER = ("                                        Answer   Notes   Marks\n"
          "number                                                                       \n")

P12 = HEADER + '                                                                                                                      PMT\n\n\n\n\nQuestion\n                             Answer                                              Notes                        Marks\nnumber\n\n7   a      M1   (they/all) contain hydrogen and carbon   Accept H and C\n           (atoms)                                       Accept particles/elements in place of atoms\n                                                         Reject ions/molecules/compounds in place of atoms\n                                                         Reject element instead of they/all\n                                                         Reject H2\n                                                         Reject mixture                                         2\n\n           M2    only                                    Accept words with other meaning (eg solely/\n                                                         exclusively)\n                                                         M2 DEP on reference to hydrogen and carbon even if\n                                                         M1 not awarded\n\n    b      double bond                                   Accept multiple in place of double\n                                                                                                                1\n                                                         Accept contain C=C\n                                                         Ignore references to single bonds\n\n    c      A                                                                                                    1\n\n    d      B and E and F                                 All three correct scores 2 marks\n                                                         Two correct scores 1 mark\n                                                                                                                2\n                                                         If more than three answers given lose one mark for\n                                                         each error eg BCEF scores 1 mark\n\n\n    e      because it has no double bond(s) / has only   Accept because only unsaturated compounds\n           single bonds / is saturated                   decolourise bromine water\n                                                         Accept because only alkenes decolourise bromine\n                                                         water                                                  1\n                                                         Accept because it’s not an alkene\n                                                         Accept because it’s not unsaturated\n                                                         Accept because it’s a (cyclo)alkane\n\x0c'

P13 = HEADER + '                                                                                                               PMT\n\n\n\n\nQuestion\n                                Answer                                               Notes             Marks\nnumber\n\n\n7   f   i    M1 for setting out calculation                    C           H              Br\n                                                             22.2         3.7            74.1\n             If division upside down or division by one or    12           1              80\n             more atomic numbers, then 0/3\n\n\n             M2 for obtaining ratio                          1.85          3.7           0.93\n             Accept any number of sig figs except one\n             Allow 0.92\n\n             M3 for whole number ratio                       2        :     4        :          1\n             M3 DEP on M2\n                                                                                                         3\n             allow alternative method:\n\n             M1 calculation of Mr C2H4Br = 108\n\n             M2 expression for % of each element\n             eg C: 24/108 x100\n\n             M3 evaluation to show these equal\n             22.2%, 3.7%, 74.1%\n\n        ii   M1   ((2×12) + (4×1) + (1×80) =) 108\n\n             M2    (216 ÷ 108 = 2)                                                                       2\n                   (so molecular formula is) C4H8Br2         correct answer with no working scores 2\n\x0c'


class G41ColonChainTail(unittest.TestCase):
    """G4.1: a tail that completes a colon-chain is ratio/table data."""

    def test_ratio_tail_not_a_marks_cell(self):
        # Evidence: 1CR Jun 2016 q7 f(i) prints the ratio '2 : 4 : 1' with
        # the trailing '1' at the marks column — never a 1-mark point.
        r = parse_ms.parse_pages([pg(13, P13)])
        q7 = [q for q in r["questions"] if q["number"] == 7][0]
        ratio_points = [p for p in q7["points"]
                        if "whole number ratio" in " ".join(p["text"])
                        and p.get("marks") == 1]
        self.assertEqual(ratio_points, [],
                         "ratio tail digit captured as a marks cell")

    def test_real_cell_after_colon_prose_still_captures(self):
        # Negative control: a genuine cell after colon-containing prose
        # ('...a 3:1 ratio   2') must still capture.
        page = HEADER + (
            "8   a      gas syringe follows a 3:1 ratio                       2\n"
            "          Total for Question 8 = 2\n")
        r = parse_ms.parse_pages([pg(20, page)])
        q8 = [q for q in r["questions"] if q["number"] == 8][0]
        scored = [p for p in q8["points"] if p.get("marks") == 2]
        self.assertTrue(scored, "real cell lost to the colon-chain guard")


class G42AltMethodBoundary(unittest.TestCase):
    """G4.2: 'allow alternative method' is an OR-route boundary."""

    def test_pending_cell_stays_with_main_route(self):
        # Evidence: 1CR Jun 2016 q7 — the lone '3' prints before
        # 'allow alternative method:'; the alternative's M1 must NOT
        # capture it. Q7 must close at the printed 12 (2+1+1+2+1+3+2).
        r = parse_ms.parse_pages([pg(12, P12), pg(13, P13)])
        q7 = [q for q in r["questions"] if q["number"] == 7][0]
        self.assertEqual(q7["sum_points"], 12)
        alt = [p for p in q7["points"]
               if "calculation of Mr" in " ".join(p["text"])
               and p.get("marks") is not None]
        self.assertEqual(alt, [],
                         "alternative-route row captured the main cell")

    def test_alternative_text_preserved(self):
        # Zero-loss: the alternative route's rows survive as note text.
        r = parse_ms.parse_pages([pg(12, P12), pg(13, P13)])
        q7 = [q for q in r["questions"] if q["number"] == 7][0]
        blob = " ".join(
            " ".join(list(p.get("text") or []) + list(p.get("notes") or []))
            for p in q7["points"])
        self.assertIn("calculation of Mr", blob)

    def test_boundary_with_no_pending_is_inert(self):
        # Fail-closed: the boundary line with NO pending cell changes
        # nothing (the legacy banner/continuation path keeps its shape).
        page = HEADER + (
            "9   a      some answer text here\n"
            "          allow alternative method:\n"
            "      Total for Question 9 = 4\n")
        r = parse_ms.parse_pages([pg(21, page)])
        q9 = [q for q in r["questions"] if q["number"] == 9][0]
        self.assertEqual(q9["sum_points"], 0)


if __name__ == "__main__":
    unittest.main()
