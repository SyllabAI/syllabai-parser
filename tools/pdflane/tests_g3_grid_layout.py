"""G3 grid-layout lane fixture tests (G3.1 column-0 scored leads with
below-printed lone cells; G3.3 cell-less part-block residual recovery).

Every fixture replicates a layout shape observed in the downloaded corpus
(SyllabAI/Past-Papers) during the 2026-10-02 G3 lane; evidence page
provenance is cited per test. Companion to the G2 pack (tests_g2_grid_layout).
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


HEADER = ("                                        Answer   Notes   Marks\n"
          "number                                                                       \n")

# 4CH0 1CR Jun 2016 q10 pages 19-20 real layout (trimmed, evidence-pinned):
# the a(ii) block's marks cells are never printed (fraction-stack layout,
# coordinate-verified: the page's marks column holds ONLY a(i)'s '3'), and
# q10(b)'s cell prints as a lone line below its column-0 lead.
P19 = """                                                        PMT

Question
                                 Answer                                            Notes                        Marks
number


10 a   i    M1 n(Na2S2O3) = 0.300 × 20     OR 0.006(0) mol                       3
                               1000
            (= n(SO2))

            M2   Mr of SO2 = 32 + (2 x16) OR 64

            M3   mass of SO2 = (0.006 × 64) = 0.38 (g)         Mark CQ throughout
                                                               Accept any number of sig fig

       ii   M1   mass of SO2 in 1 dm3 = 0.38(4) × 1000         M1 CQ on M3 in ai
                                           50
                                      = 7.6(8) (g)             Accept any number of sig fig

            M2   this is less than 100 so no SO2 will escape   If candidate value for M1 is greater than 100,

            OR

            M1     volume of solvent is 50cm3 which would      If answers based on volume of solvent = 20cm3
            dissolve
                     (100/20) = 5(g)
            M2     0.384(g) is less than 5(g) so no SO2        0.384(g) is less than 2(g) so no SO2 would
            would escape                                       escape worth 1 mark
"""

P20 = """

b        as the (hydrochloric) acid/HCl is added             Allow (immediately) after (all) the acid/HCl
                                                             added
                                                                                                    1
                                                             Ignore when the solutions are mixed
"""


class G31Column0ScoredLeads(unittest.TestCase):
    """A column-0 part lead carrying answer content whose marks cell prints
    as a lone line BELOW it is a scored row, not a prose banner.
    Evidence: 4CH0 1CR Jun 2016 q10(b) p20."""

    def test_col0_lead_with_lone_cell_below_scores(self):
        # question context first (the real b row continues Q10 from p19)
        pre = ("10   a         A    (the crystal dissolves)                 1\n")
        r = parse_ms.parse_pages([pg(1, HEADER + pre + P20)])
        q10 = r["questions"][0]
        b_pts = [p for p in q10["points"] if p.get("part") == "b"]
        self.assertEqual(len(b_pts), 1)
        pt = b_pts[0]
        self.assertIsNone(pt["sub"])
        self.assertEqual(pt["marks"], 1)
        self.assertEqual(pt["text"],
                         "as the (hydrochloric) acid/HCl is added")

    def test_col0_lead_without_lone_cell_stays_banner(self):
        # prose banner class ('f   In part (f):', 4CH0 1C Jun 2015 q8 p21):
        # no lone cell before the next labeled row -> structural only
        text = (HEADER +
                "8   a         A    (the crystal dissolves)                 1\n"
                "f   In part (f):                                      \n"
                "    i   some answer text                          1\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q8 = r["questions"][0]
        self.assertEqual(sum(p["marks"] or 0 for p in q8["points"]), 2)
        self.assertTrue(all(p.get("marks") is not None for p in q8["points"]))


class G33CelllessBlockResidual(unittest.TestCase):
    """A part block whose marks cell was never printed recovers
    total - resolved_sum on its opener when it is the ONLY cell-less block
    and the residual equals the block's main-route row count.
    Evidence: 4CH0 1CR Jun 2016 q10(a)(ii) pages 19-20 (marks column
    coordinate-verified empty for the whole a(ii) block)."""

    def _run(self, tots):
        return parse_ms.parse_pages([pg(1, HEADER + P19), pg(2, P20)],
                                    qp_totals=tots)

    def test_residual_recovers_two_marks_on_opener(self):
        # resolved: a(i) 3 + b 1 = 4; QP total 6 -> diff 2 == main route (M1+M2)
        r = self._run({10: 6})
        q10 = next(q for q in r["questions"] if q["number"] == 10)
        a_ii = [p for p in q10["points"]
                if p.get("part") == "a" and p.get("sub") == "ii"]
        self.assertEqual(len(a_ii), 1, "OR-route rows must not spawn points")
        self.assertEqual(a_ii[0]["marks"], 2)
        self.assertEqual(a_ii[0]["text"],
                         "mass of SO2 in 1 dm3 = 0.38(4) × 1000")
        self.assertEqual(sum(p["marks"] or 0 for p in q10["points"]), 6)

    def test_residual_gate_refuses_wrong_count(self):
        # diff 3 != main-route count 2 -> fail-closed (legacy demotion)
        r = self._run({10: 7})
        q10 = next(q for q in r["questions"] if q["number"] == 10)
        a_ii = [p for p in q10["points"]
                if p.get("part") == "a" and p.get("sub") == "ii"]
        self.assertEqual(len(a_ii), 0)
        self.assertEqual(sum(p["marks"] or 0 for p in q10["points"]), 4)

    def test_residual_gate_refuses_without_total(self):
        r = self._run(None)
        q10 = next(q for q in r["questions"] if q["number"] == 10)
        a_ii = [p for p in q10["points"]
                if p.get("part") == "a" and p.get("sub") == "ii"]
        self.assertEqual(len(a_ii), 0)
        self.assertEqual(sum(p["marks"] or 0 for p in q10["points"]), 4)

    def test_or_route_rows_never_double_count(self):
        # the OR alternative's own M1/M2 label rows are alternatives for the
        # same marks: with the recovery they sit as demoted notes, never as
        # additional scored points
        r = self._run({10: 6})
        q10 = next(q for q in r["questions"] if q["number"] == 10)
        labels = [p["label"] for p in q10["points"]
                  if p.get("part") == "a" and p.get("sub") == "ii"]
        self.assertEqual(labels, ["M1"])
        # the OR route's own M1 row is demoted (never a scored point); the
        # M2 count includes a(i)'s step row (same shape, different block)
        demoted = q10.get("demoted_points") or []
        self.assertEqual(demoted.count("M1"), 1)


if __name__ == "__main__":
    unittest.main()
