"""G1.2 grammar pack fixture tests (RC-A..RC-F).

Every fixture replicates a layout shape observed in the downloaded corpus
(SyllabAI/Past-Papers) and pinned in the mark-closure taxonomy
(workspace/mc_taxonomy.json, Task 38). Evidence slugs are cited per test.
"""
import sys
import unittest

sys.path.insert(0, ".")

from pdflane import parse_ms, emit_atoms  # noqa: E402


def pg(n, text):
    return {"page": n, "text": text}


class RCAPageSkip(unittest.TestCase):
    """2012+ table-grid header pages must NOT be skipped as furniture."""

    def test_expected_answer_accept_reject_marks_header_is_grid_page(self):
        # 4CH0 2C Jan 2012 p3 — the whole q1 grid was dropped (sum 1 vs 10)
        text = ("                                              PMT\n"
                "\n"
                " Question\n"
                "                                Expected Answer         Accept         Reject         Marks\n"
                " number\n"
                "1 (a)\n")
        self.assertTrue(parse_ms.is_grid_page(text))

    def test_answer_accept_reject_marks_header_is_grid_page(self):
        # 4CH0 2C Jan 2012 p9/p12 header variant
        text = ("                                Answer       Accept       Reject       Marks\n"
                " number\n")
        self.assertTrue(parse_ms.is_grid_page(text))

    def test_prose_answer_marks_line_is_not_grid_evidence(self):
        text = ("Answer all questions. Some questions must be answered with a cross in\n"
                "a box . If you change your mind about an answer put a line through the\n")
        self.assertFalse(parse_ms.is_grid_page(text))


class RCAOpenerOnlyRows(unittest.TestCase):
    """Opener-only rows + backward lone marks cell (4CH0 2C Jan 2012 q1)."""

    def test_solo_opener_and_lone_cell_capture_part_marks(self):
        text = ("                                              PMT\n"
                "\n"
                " Question\n"
                "                                Expected Answer         Accept         Reject         Marks\n"
                " number\n"
                "1 (a)\n"
                "                                                                                                    4\n"
                "                  Proton   Neutron   Electron\n"
                "1 mark for each correct answer\n"
                "  (b)   (i)    Protons AND electrons = 1          one                                       1\n"
                "               neutrons = 2                        two                                      1\n"
                "                                                                                          Total     6\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        self.assertEqual(q["number"], 1)
        a_pt = [p for p in q["points"] if p["part"] == "a"]
        self.assertEqual(len(a_pt), 1, "solo opener must open part (a)")
        self.assertEqual(a_pt[0]["marks"], 4, "lone cell fills the aggregate opener")
        self.assertEqual(q["total_row"], 6)
        bi = [p for p in q["points"] if p["part"] == "b"]
        self.assertEqual([p["marks"] for p in bi], [1, 1])
        self.assertEqual(q["sum_points"], 6)
        self.assertTrue(q["arithmetic_ok"])

    def test_zero_space_a_i_sub_is_parsed(self):
        # 4CH0 2C Jan 2012 p9: '5 (a)(i)  (damp / moist) litmus paper ... 1'
        text = ("                                Answer       Accept       Reject       Marks\n"
                " number\n"
                "5 (a)(i)    (damp / moist) litmus paper                                                 1\n"
                "                                                                                   Total 7\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        self.assertEqual(len(q["points"]), 1)
        self.assertEqual((q["points"][0]["part"], q["points"][0]["sub"]), ("a", "i"))
        self.assertEqual(q["points"][0]["marks"], 1)


class RCBMarksColumnDiscipline(unittest.TestCase):
    """Fraction-table tails far left of the marks column are data, not marks."""

    def test_fraction_row_tail_never_becomes_marks(self):
        # 4CH0 1C June 2011 p8: '1  1  3' under M2's OR spawned a phantom +3
        text = ("                              Answer                    Notes               Marks\n"
                " number\n"
                "5   (c)   M1      Award 0 for whole question if                            1\n"
                "          M2   0.1    0.1   0.3                                            1\n"
                "               OR\n"
                "                1       1   3\n"
                "          M3      Consequential on M2                                      1\n"
                "                                                                Total 10 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        synth = [p for p in q["points"] if p["marks"] == 3]
        self.assertEqual(synth, [], "fraction tail spawned a phantom +3 point")
        self.assertEqual(q["sum_points"], 3)
        self.assertEqual(q["total_row"], 10)  # deficit disclosed via DONT-CLOSE,
        # not silently balanced

    def test_displaced_notes_region_cell_opens_deferred_point(self):
        # 4CH0 2C Jan 2012 q1 (b)(ii): 'proton number / 1' + 'with different
        # masses' — the second 1-mark cell sits in the notes region
        text = ("                                Expected Answer         Accept         Reject         Marks\n"
                " number\n"
                "6 (a)   gasoline is used as a fuel                                        2\n"
                "  (b)   (i)    ions not fixed                              one                        1\n"
                "        (ii)   atoms of the same element                   atoms with same            1\n"
                "                                                           proton number /            1\n"
                "              with different masses\n"
                "                                                                                   Total     5\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        ii = [p for p in q["points"] if p["part"] == "b" and p["sub"] == "ii"]
        self.assertEqual(len(ii), 2, "displaced second cell must open point (ii)#2")
        self.assertEqual(sum(p["marks"] for p in ii), 2)
        self.assertEqual(ii[1]["text"], "with different masses")
        self.assertEqual(q["sum_points"], 5)
        self.assertTrue(q["arithmetic_ok"])

    def test_note_led_point_text_moves_to_notes(self):
        # 4CH0 1C June 2011 q5 (b)(i): answer column empty at the marks row,
        # the Ignore-note supplied the "text"
        text = ("                              Answer                    Notes               Marks\n"
                " number\n"
                "7 (a)      a correct use                                     one                    1\n"
                "  (b)   (i)                                    Ignore \"electrons cannot      1\n"
                "               ions fixed/cannot move/not      move (when solid)\"\n"
                "                                                                Total 2 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        pt = next(p for p in q["points"] if p["part"] == "b")
        self.assertEqual(pt["marks"], 1)
        text_final = pt["text"] if isinstance(pt["text"], str) else " ".join(pt["text"])
        self.assertFalse(parse_ms.NOTE_KW_START_RE.match(text_final or ""),
                         "note-led chunks must move out of the text slot")
        self.assertTrue(any("Ignore" in n for n in pt["notes"]))
        self.assertTrue(any("ions fixed" in n for n in pt["notes"]))


class RCDDoesNotClaimRomanSubs(unittest.TestCase):
    """'(v)' is a roman sub-part opener, not a part letter."""

    def test_paren_v_with_open_part_is_sub(self):
        # 4CH1 1C June 2024 q2 (a)(v): landed as part='v'/sub=None before
        text = ("  Question\n"
                "                     Answer                    Notes              Marks\n"
                "  number\n"
                "2   (a)    (i)     most reactive Q                                        1\n"
                "           (v)     explosive/dangerous/violent/unsafe  IGNORE volatile   1\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        subs = [(p["part"], p["sub"]) for p in q["points"]]
        self.assertIn(("a", "v"), subs, "(v) must attach as sub of part a")
        self.assertNotIn(("v", None), subs)

    def test_paren_v_without_part_context_stays_part(self):
        # degenerate page (whole-question loss): preserve the legacy fallback
        text = ("  Question\n"
                "                     Answer                    Notes              Marks\n"
                "  number\n"
                "2   (v)     some answer text                                            1\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        self.assertEqual((q["points"][0]["part"], q["points"][0]["sub"]), ("v", None))


class RCELoneCellAboveOpener(unittest.TestCase):
    """Displaced merged cell ABOVE the opener fills that opener's point."""

    def test_lone_cell_deferred_to_next_opener(self):
        # 4CH1 2C June 2021 q3 (a)(iii): '2' printed above '(iii) M1 ...'
        text = ("                                      Answer                    Notes                Marks\n"
                " number\n"
                "3 (a) (i)       fractionating column/ tower      ALLOW fraction(al) column     1\n"
                "        (ii)    fuel for ships                                                 1\n"
                "                                                                               2\n"
                "        (iii)   M1 fraction A refinery gases\n"
                "                M2 fraction F bitumen\n"
                "  (b)   (i)     CnH2n + 2                          ALLOW x in place of n       1\n"
                "                                                                    Total 10\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        iii = [p for p in q["points"] if p["sub"] == "iii"]
        self.assertEqual(len(iii), 1)
        self.assertEqual(iii[0]["marks"], 2, "lone cell above the opener fills it")
        self.assertEqual(q["sum_points"], 5)


class RCEmitOrphanTotals(unittest.TestCase):
    """RC-F: total rows whose question never opened are orphans, not aborts."""

    def _blocks(self, lines):
        return [{"page": 1, "kind": "text", "text": t, "y0": 100.0} for t in lines]

    def test_unexpected_total_row_becomes_orphan_stub(self):
        # 4CH1 1C June 2019: rasterized opener page -> total with no opener
        blocks = self._blocks([
            "(Total for Question 1 = 4 marks)",
            "2   The diagram shows part of the Periodic Table",
            "some content of question 2",
            "(Total for Question 2 = 4 marks)",
        ])
        atoms = emit_atoms.build_qp_atoms(blocks)
        real = [a for a in atoms if not a.get("orphan_total")]
        orphans = [a for a in atoms if a.get("orphan_total")]
        self.assertEqual([a["number"] for a in real], [2])
        self.assertEqual(real[0]["total"], 4)
        self.assertEqual([(o["number"], o["total"]) for o in orphans], [(1, 4)])

    def test_orphan_events_match_parse_qp(self):
        blocks = self._blocks([
            "(Total for Question 1 = 4 marks)",
            "2   content",
            "(Total for Question 2 = 4 marks)",
        ])
        atoms = emit_atoms.build_qp_atoms(blocks)
        parsed = parse_qp_safe(blocks)
        emit_atoms.crosscheck_qp(atoms, parsed)  # must not raise


def parse_qp_safe(blocks):
    from pdflane import parse_qp
    return parse_qp.parse_blocks(blocks)


class RCCStandaloneSubOpeners(unittest.TestCase):
    """RC-C: '(ii)' alone on a line opens the sub-part (4CH0 1C Jun 2011 q2)."""

    def test_standalone_ii_opens_sub_part(self):
        lines = [
            {"page": 1, "kind": "text", "text": "1\t Classify each substance.", "y0": 80.0},
            {"page": 1, "kind": "text", "text": "X", "y0": 85.0},
            {"page": 1, "kind": "text", "text": "(1)", "y0": 90.0},
            {"page": 1, "kind": "text", "text": "(Total for Question 1 = 1 mark)", "y0": 95.0},
            {"page": 1, "kind": "text", "text": "2\t (a)\tClassify each diagram.", "y0": 100.0},
            {"page": 1, "kind": "text", "text": "(i)", "y0": 120.0},
            {"page": 1, "kind": "text", "text": "He", "y0": 130.0},
            {"page": 1, "kind": "text", "text": "(1)", "y0": 140.0},
            {"page": 1, "kind": "text", "text": "(ii)", "y0": 150.0},
            {"page": 1, "kind": "text", "text": "O", "y0": 160.0},
            {"page": 1, "kind": "text", "text": "(1)", "y0": 170.0},
            {"page": 1, "kind": "text", "text": "(iii)", "y0": 180.0},
            {"page": 1, "kind": "text", "text": "O O", "y0": 190.0},
            {"page": 1, "kind": "text", "text": "(1)", "y0": 200.0},
            {"page": 1, "kind": "text", "text": "(Total for Question 2 = 3 marks)", "y0": 210.0},
        ]
        atoms = emit_atoms.build_qp_atoms(lines)
        a2 = next(a for a in atoms if a["number"] == 2)
        subs = [(p["label"], p.get("sub"), p["marks"])
                for p in a2["parts"] if p.get("sub") is not None]
        self.assertEqual(subs, [("a", "i", 1), ("a", "ii", 1), ("a", "iii", 1)])


if __name__ == "__main__":
    unittest.main()
