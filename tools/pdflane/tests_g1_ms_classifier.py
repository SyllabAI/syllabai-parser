"""G1 upgrade: old-spec MS classifier — deterministic row grammar fixes.

Root causes fixed (all evidenced on 4CH0/1C jan2012 and the G8 corpus flags):
  1. whole-page furniture skip (boilerplate/publications pages, zero labels)
  2. grid header rows ('Answer   Notes   Marks') as furniture
  3. LABEL_RE lookahead: word-initial A/M ('Ask The Expert') never a label
  4. guidance hijack: 'M3  answer text   Do not award M3 ...' keeps the answer
  5. phantom points: deep notes-column wrap ending in a displaced marks-cell
     digit no longer spawns a synthesized alternative point
  6. capped alternative groups ('Any two for 1 each') contribute their cap
  7. part inheritance: label-less rows under 'b i' inherit (b, i)
  8. QP-total recovery + QP-aware arithmetic_ok (parse_pages qp_totals param)
  9. prose notes opening with an M/A token ('M2 can be awarded for use of')
 10. guidance adjacency: wrapped fragment after a guidance row is guidance

Failsafe accounting invariant: every raw [MA]<n> token lands in exactly one
bucket; furniture pages hold none by definition.

Run:  python3 -m pdflane.tests_g1_ms_classifier
"""
import unittest

from pdflane import parse_ms


def pg(n, text):
    return {"page": n, "text": text}


GRID_HEADER = "                                    Answer                Notes                Marks\n" \
              "number\n"


class FurniturePages(unittest.TestCase):
    def test_boilerplate_page_skipped_whole(self):
        boiler = ("Edexcel and BTEC Qualifications\n"
                  "Edexcel and BTEC qualifications come from Pearson, the world's leading\n"
                  "learning company. We provide a wide range of qualifications.\n"
                  "Publications Code UG030278\n"
                  "All the material in this publication is copyright\n")
        grid = ("1 a      M1      beaker           Accept phonetic spellings        1\n"
                "                                                Total 1 marks\n")
        r = parse_ms.parse_pages([pg(1, boiler), pg(2, grid)])
        self.assertEqual(r["buckets"]["furniture_pages"], 1)
        self.assertEqual(r["unclassified"], [])
        self.assertEqual(r["label_count"], 1)

    def test_grid_page_with_labels_never_skipped(self):
        grid = "1 a      M1      beaker           Accept phonetic spellings        1\n"
        r = parse_ms.parse_pages([pg(1, grid)])
        self.assertEqual(r["buckets"]["furniture_pages"], 0)

    def test_label_split_page_never_skipped(self):
        # 4CH0 2012+ style: bare 'M' on the row, its digit on the next line;
        # no complete [MA]<n> token anywhere, but the grid header is present
        text = (GRID_HEADER +
                "7 a     i   M   Chlorine / Cl2            Allow Cl                         1\n"
                "            1                             Accept phonetic spellings\n")
        r = parse_ms.parse_pages([pg(1, text)])
        self.assertEqual(r["buckets"]["furniture_pages"], 0)
        self.assertEqual(r["label_count"], 1)


class HeaderRowsAndLookahead(unittest.TestCase):
    def test_grid_header_row_is_furniture(self):
        text = (GRID_HEADER +
                "1 a      M1      beaker                                            1\n")
        r = parse_ms.parse_pages([pg(1, text)])
        self.assertEqual(r["unclassified"], [])
        self.assertEqual(r["label_count"], 1)

    def test_word_initial_letters_are_not_labels(self):
        text = ("Ask The Expert can be accessed online at the link below\n"
                "Alternatively, you can speak directly to a subject specialist\n"
                "Mark schemes are published annually\n")
        r = parse_ms.parse_pages([pg(1, text)])
        # no header/labels/totals -> whole page is furniture; nothing surfaces
        self.assertEqual(r["buckets"]["furniture_pages"], 1)
        self.assertEqual(r["questions"], [])

    def test_label_lookahead_still_matches_real_labels(self):
        lm = parse_ms.LABEL_RE.match("          M2   water                                   1")
        self.assertIsNotNone(lm)
        self.assertEqual(lm.group("labelbase") + lm.group("labelnum"), "M2")
        self.assertIsNone(parse_ms.LABEL_RE.match("Ammonia is basic"))


class GuidanceHijackGuard(unittest.TestCase):
    def test_labeled_row_with_answer_and_note_keeps_answer(self):
        text = ("1 a      M3   (litmus paper) turns blue   Do not award M3 if dipped       \n"
                "         OR                                       (even if only implied)\n"
                "         white smoke/solid/powder\n"
                "          M1   white precipitate                                      1\n"
                "                                                Total 2 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        self.assertEqual(r["unclassified"], [])
        q = r["questions"][0]
        self.assertEqual(len(q["points"]), 2)
        pt = q["points"][0]
        self.assertEqual(pt["text"], "(litmus paper) turns blue")
        self.assertIn("Do not award M3 if dipped", pt["notes"])
        # OR-row + wrap absorb as notes on the open point
        self.assertTrue(any("even if only implied" in n for n in pt["notes"]))
        self.assertTrue(any("white smoke" in n for n in pt["notes"]))
        self.assertTrue(q["arithmetic_ok"])


class PhantomPointGuard(unittest.TestCase):
    def test_deep_notes_wrap_with_tail_digit_never_spawns_point(self):
        text = ("1 a      M2   test (gas) with litmus   Accept use of indicator        1\n"
                "         litmus (paper)              Accept holding litmus above\n"
                "                                      ammonia in M2                   1\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        synth = [p for p in q["points"] if p["label"].startswith("P")]
        self.assertEqual(synth, [], "displaced-cell wrap spawned a phantom point")
        # both raw label tokens accounted
        self.assertEqual(r["buckets"]["point"], 1)
        pt = q["points"][0]
        self.assertTrue(any("ammonia in M2" in n for n in pt["notes"]))


class CappedAlternativeGroups(unittest.TestCase):
    def test_any_two_for_one_each_closes_to_cap(self):
        text = ("1 a      M1   exothermic                                          1\n"
                "  b  i    M1   volume of solution                                 1\n"
                "          M2   concentration                                      1\n"
                "          M3   amount of metal                                    1\n"
                "          M4   same surface area                                  1\n"
                "                                       Any two for 1 each\n"
                "     ii   M1   18.7                                               1\n"
                "                                                Total 4 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        self.assertEqual(len(q["capped_groups"]), 1)
        g = q["capped_groups"][0]
        self.assertEqual(g["cap"], 2)
        self.assertEqual(g["labels"], ["M1", "M2", "M3", "M4"])
        # 1 (a) + cap 2 (b-i) + 1 (b-ii) = 4 == total row
        self.assertEqual(q["sum_points"], 4)
        self.assertTrue(q["arithmetic_ok"])


class PartInheritance(unittest.TestCase):
    def test_label_less_rows_inherit_open_part_block(self):
        text = ("1 b  i    M1   volume of solution                                 1\n"
                "          M2   concentration                                      1\n"
                "          M3   amount of metal                                    1\n"
                "     ii   M1   18.7                                               1\n"
                "                                                Total 4 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        self.assertEqual([(p["part"], p["sub"]) for p in q["points"]],
                         [("b", "i"), ("b", "i"), ("b", "i"), ("b", "ii")])


class QpTotalRecovery(unittest.TestCase):
    def test_displaced_cell_recovered_against_qp_total(self):
        # MS total row says 3 but the true sum is 4: the fourth cell was
        # displaced onto a notes wrap (pdftotext merged-cell artifact); the
        # QP printed total 4 closes the exactly-one-unresolved point
        text = ("1 a      M1   NH4+                        Award 1 if wrong way          1\n"
                "          M2   Cl-                       Penalise missing charges      1\n"
                "  b  i    M1   (add) NaOH (solution)                                   1\n"
                "          M2   test with litmus                                        \n"
                "                                       ammonia in M2                  1\n"
                "                                                Total 3 marks\n")
        r = parse_ms.parse_pages([pg(1, text)], qp_totals={1: 4})
        q = r["questions"][0]
        self.assertEqual(q["sum_points"], 4)
        self.assertTrue(q["arithmetic_ok"])

    def test_no_qp_totals_keeps_legacy_behaviour(self):
        text = ("1 a      M1   NH4+                                                  1\n"
                "          M2   Cl-                                                  1\n"
                "                                                Total 3 marks\n")
        r = parse_ms.parse_pages([pg(1, text)])
        q = r["questions"][0]
        self.assertFalse(q["arithmetic_ok"])  # cannot close: no recovery source


class ProseNoteGuard(unittest.TestCase):
    def test_prose_opening_with_token_absorbs_and_keeps_chain(self):
        text = ("1 c      M1   1000 / 26.6                                            1\n"
                "          M2   37.6                        Ignore units               1\n"
                "                                       M2 can be awarded for use of\n"
                "                                       another student's result\n")
        r = parse_ms.parse_pages([pg(1, text)])
        # the chain must not break: zero unclassified rows
        self.assertEqual(r["unclassified"], [])
        q = r["questions"][0]
        # guidance-keyworded prose lands in guidance; its wrap follows via
        # adjacency — both text fragments preserved somewhere in the product
        all_guidance = " ".join(g["text"] for g in q["guidance"])
        all_notes = " ".join(n for p in q["points"] for n in p["notes"])
        self.assertIn("can be awarded for use of", all_guidance + all_notes)
        self.assertIn("another student's result", all_guidance + all_notes)


class GuidanceAdjacency(unittest.TestCase):
    def test_wrapped_fragment_after_guidance_row_is_guidance(self):
        text = ("1 a  i    M1   H-O-H with both bonds                Accept 2 dots      1\n"
                "          M2   8 electrons in outer shell          Ignore inner shell 1\n"
                "                                                   M2 dependent on both\n"
                "                                                   attraction and electrons in M1\n")
        r = parse_ms.parse_pages([pg(1, text)])
        self.assertEqual(r["unclassified"], [])
        q = r["questions"][0]
        self.assertTrue(any("attraction and electrons in M1" in g["text"]
                            for g in q["guidance"]))


class Determinism(unittest.TestCase):
    def test_double_parse_identical(self):
        import json
        text = ("1 b  i    M1   volume of solution                                 1\n"
                "          M2   concentration                                      1\n"
                "                                       Any two for 1 each\n"
                "                                                Total 2 marks\n")
        pages = [pg(1, text)]
        a = json.dumps(parse_ms.parse_pages(list(pages)), sort_keys=True)
        b = json.dumps(parse_ms.parse_pages(list(pages)), sort_keys=True)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
