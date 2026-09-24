"""Regression: printed question total rows inside the page-footer band.

Old-spec layouts (e.g. 4CH0 Jan-2016 1C Q3/Q9/Q10 at y0 792-801) sit the
"(Total for Question N = X marks)" row inside the page-footer band. A total
row is QUESTION furniture, never PAGE furniture — both walks must honor it
there instead of skipping it (previously: atom never sealed, walk desynced,
emit_atoms raised EmitError "unexpected total row").

Run:  python3 -m pdflane.tests_footer_total_rows
"""
import unittest

from pdflane import emit_atoms, parse_qp


def blk(text, page, y0, kind="text"):
    return {"page": page, "kind": kind, "text": text, "y0": y0}


STREAM = [
    blk("1 (a) Name the gas.", 1, 100.0),
    blk("(Total for Question 1 = 8 marks)", 1, 800.0),  # footer band
    blk("2 (a) Explain the trend.", 2, 120.0),
    blk("(Total for Question 2 = 5 marks)", 2, 300.0),  # normal band
]


class FooterBandTotalRows(unittest.TestCase):
    def test_parse_qp_seals_footer_band_total(self):
        out = parse_qp.parse_blocks(STREAM)
        qs = [q for q in out["questions"] if not q.get("orphan_total")]
        self.assertEqual([q["number"] for q in qs], [1, 2])
        self.assertEqual([q["total"] for q in qs], [8, 5])

    def test_build_qp_atoms_seals_footer_band_total(self):
        atoms = emit_atoms.build_qp_atoms(STREAM)
        self.assertEqual([a["number"] for a in atoms], [1, 2])
        self.assertEqual([a["total"] for a in atoms], [8, 5])

    def test_crosscheck_agrees(self):
        atoms = emit_atoms.build_qp_atoms(STREAM)
        parsed = parse_qp.parse_blocks(STREAM)
        emit_atoms.crosscheck_qp(atoms, parsed)  # must not raise

    def test_page_number_still_skipped_in_footer_band(self):
        out = parse_qp.parse_blocks(
            STREAM + [blk("Turn over", 2, 801.0), blk("14", 2, 810.0)])
        qs = [q for q in out["questions"] if not q.get("orphan_total")]
        self.assertEqual([q["number"] for q in qs], [1, 2])
        self.assertNotIn("14", [b["text"] for b in out.get("blocks", [])] or
                         [q.get("prompt", []) for q in qs][0])


if __name__ == "__main__":
    unittest.main()
