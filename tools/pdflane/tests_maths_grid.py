"""Maths-B grid dialect tests — page-verbatim fixtures from 4MB1-01 2024-06.

Every fixture line is copied verbatim from the pdftotext -layout output of
SyllabAI/syllabai-pastpapers
past-papers/pearson-edexcel/international-gcse/mathematics-b/4mb1/past-papers/2024-06/4MB1-01/ms.pdf
(provenance sha256 pinned in the paper's manifest.yaml). The laws under test
were derived from the PyMuPDF word-coordinate study of pages 6/8 (q1/q4) and
the corpus dialect census (60x dialect A, 6x dialect B).
"""
import json
import os
import tempfile

from pdflane import parse_ms_maths as m

HDR = "Question                        Working   Answer   Mark                        Notes"


def pages(*texts):
    return [{"page": i + 1, "text": t} for i, t in enumerate(texts)]


def q_by_num(r, n):
    return [q for q in r["questions"] if q["number"] == n][0]


def test_detects_dialect_a():
    assert m.detects_dialect(pages(HDR + "\n 1    (a)   7400   2   B1 accept 7.4 10\n"
                                       "                                                              Total 2 marks\n"))
    # dialect B does NOT route here
    assert not m.detects_dialect(pages(
        "Question        Working        Answer        Notes        Mark        Sub-\nTotal\n"))


def test_q1_merged_cell_spans_parts():
    """The Mark cell '2' is merged across (a)+(b): B1+B1 close it, not the
    part boundary (proven on page 6: one cell '2' over both part rows)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        " 1    (a)                                  7400     2     B1 accept 7.4 10 and 7.400 103\n"
        "      (b)                                 0.04            B1 accept 4 10-2\n"
        "                                                                Total 2 marks\n"))
    q = q_by_num(r, 1)
    assert q["total_row"] == 2
    assert q["arithmetic_ok"] is True
    assert [(p["part"], p["marks"]) for p in q["points"]] == [("a", 1), ("b", 1)]
    assert r["unclassified"] == []


def test_q2_m1_a1_codes_carry_row_marks():
    r = m.parse_pages(pages(
        HDR + "\n"
        " 2                                                  2     M1 for fully correct substitution of x = 7\n"
        "            -12.5                                   A1 oe we can ISW incorrect attempt to simplify\n"
        "                                                                Total 2 marks\n"))
    q = q_by_num(r, 2)
    assert q["total_row"] == 2 and q["arithmetic_ok"] is True
    assert sum(p["marks"] for p in q["points"]) == 2
    assert q["points"][0]["text"].startswith("for fully correct substitution")


def test_dep_reference_is_not_a_second_point():
    """'M1 dependent on 1st M1 for ...' = ONE mark (q16 row verbatim)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        " 16         15 14                                  4\n"
        "                                                            M1 for both improper fractions correct.\n"
        "                                                    M1 dependent on 1st M1 for correct method to\n"
        "                                                            multiply\n"
        "                                                                Total 2 marks\n"))
    q = q_by_num(r, 16)
    assert sum(p["marks"] for p in q["points"]) == 2
    assert len(q["points"]) == 2
    assert "dependent on 1st" in q["points"][1]["text"]


def test_parenthesised_split_award_note_is_not_a_point():
    """'(B1 for an expression in the form ...)' is the B2's split note (q7)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        " 7    (a)                                         2   B2 fully correct\n"
        "                                                    (B1 for an expression in the form ma 10p with 2 of m,\n"
        "                                                                Total 2 marks\n"))
    q = q_by_num(r, 7)
    assert [(p["marks"]) for p in q["points"]] == [2]
    assert q["points"][0]["text"].startswith("fully correct")


def test_sc_codes_are_not_scored():
    """'SC B1 for awrt 3.6 ...' is a special-case award, outside the total (q19)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        " 19                                                            2                  M1 for 3 oe\n"
        "                                                    cas                  2.25                 A1 oe\n"
        "                                                    SC B1 for awrt 3.6 or 16\n"
        "                                                                Total 2 marks\n"))
    q = q_by_num(r, 19)
    assert sum(p["marks"] for p in q["points"]) == 2
    assert all("awrt 3.6" not in p["text"] for p in q["points"])


def test_alt_route_codes_are_reprints():
    """The 'Alt' block repeats the main route's codes; never re-scored (q18).

    Round 2, order-faithful to page 17 of 4MB1-01 2024-06: the Alt section's
    FIRST mark row prints its code on the row's first line while the 'Alt'
    token prints on the vertically-centred line below — the section-restart
    lookahead (L4) must arm the Alt route BEFORE that row's codes are seen.
    The main route (M1 + M1dep + M1 + A1) closes at 4; nothing from the Alt
    section adds to it.
    """
    r = m.parse_pages(pages(
        HDR + "\n"
        " 18               x - 54                            4     M1 setting up a correct equation in x\n"
        "                                                            M1 dep on M1 for a correct method to collect the x\n"
        "                                                            M1 for correct substitution to find n\n"
        "                                                            A1\n"
        " 18                  90 ( 2n - 4 )                  4     M1 for forming a pair of simultaneous equations in x\n"
        "Alt              2x =\n"
        "                                                            M1 for a correct method to substitute to eliminate one\n"
        "                                                                Total 4 marks\n"))
    q = q_by_num(r, 18)
    assert q["total_row"] == 4
    assert sum(p["marks"] for p in q["points"]) == 4
    assert all("simultaneous" not in p["text"] for p in q["points"])
    assert any("ALT-ROUTE-CODE-SKIPPED" in u.get("text", "") for u in r["unclassified"])


def test_sequential_law_kills_working_math_openers():
    """A working line starting with the expected number ('3 - 2 7 2') must not
    open question 3 (proven: working math sits far right of col-0)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        " 2                                                  2     M1 for substitution\n"
        "                                             3 - 2 7 2\n"
        "                                                 5 7\n"
        "                                                                Total 2 marks\n"))
    assert [q["number"] for q in r["questions"]] == [2]
    assert r["buckets"]["continuation"] >= 2


def test_decimal_answer_is_not_a_mark_cell():
    """'0.04' must not tokenize as mark cell 4 (decimal-lookaround law)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        " 1    (b)                                 0.04            B1 accept 4 10-2\n"
        "                                                                Total 1 marks\n"))
    q = q_by_num(r, 1)
    assert q["arithmetic_ok"] is True


def test_dialect_b_pages_route_to_review():
    """2018-06 legacy 7-column layout: detected, honestly unclassified."""
    r = m.parse_pages(pages(
        "Question        Working        Answer        Notes        Mark        Sub-\nTotal        \n"
        " 1                              3, 8, 13        -1 for every error        B2        2        2\n"
        "                                                                Total 2 marks\n"))
    assert any("DIALECT-B-UNSUPPORTED" in u.get("text", "")
               for u in r["unclassified"])
    assert r["questions"] == []


def test_bare_question_number_opens():
    """Vertical centering prints a bare '17' on its own line (page 16)."""
    r = m.parse_pages(pages(
        HDR + "\n"
        "17\n"
        "                                    3.53             A1 awrt 3.5\n"
        "                                                                Total 3 marks\n"))
    assert [q["number"] for q in r["questions"]] == [17]


def test_output_contract_matches_parse_ms():
    """The maths parser's envelope keys are the parse_ms contract."""
    r = m.parse_pages(pages(HDR + "\n 1    (a)   7400   2   B1 accept\n"
                                "                                        Total 2 marks\n"))
    for k in ("questions", "label_count", "total_rows_found", "witnesses",
              "unclassified", "buckets", "raw_label_count"):
        assert k in r
    q = r["questions"][0]
    for k in ("number", "total_row", "total_row_page", "points", "guidance",
              "pages", "capped_groups", "arithmetic_ok"):
        assert k in q
    pt = q["points"][0]
    for k in ("label", "part", "sub", "marks", "text", "notes", "page"):
        assert k in pt


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("%d/%d PASS" % (len(fns), len(fns)))
