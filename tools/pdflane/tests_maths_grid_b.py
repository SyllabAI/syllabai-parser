"""Maths-B legacy dialect-B (2018-06, 7-column) tests.

Fixture lines are copied verbatim from the pdftotext -layout output of
SyllabAI/syllabai-pastpapers
past-papers/pearson-edexcel/international-gcse/mathematics-b/4mb1/past-papers/
2018-06/4MB1-01/ms.pdf and 2018-06/4MB1-02/ms.pdf (provenance sha256 pinned in
the paper manifests). Laws anchored by the PyMuPDF word-coordinate study
(scripts/b2_dialect_b_study.py): Mark codes print per row in the Mark column;
Notes-column code mentions are never awards; the question total is the max
digit in the Sub-Total/Total band across the question's rows.
"""
from pdflane import parse_ms_maths_b as b

HDR = ("Question                    Working   Answer             "
       "Notes            Mark   Sub-    Total")


def pages(*texts):
    return [{"page": i + 1, "text": t} for i, t in enumerate(texts)]


def q_by_num(r, n):
    return [q for q in r["questions"] if q["number"] == n][0]


def test_detects_dialect_b():
    assert b.detects_dialect_b(pages(HDR + "\n 1   3, 8, 13   B2\n"))
    # dialect A does not route here
    assert not b.detects_dialect_b(pages(
        "Question   Working   Answer   Mark   Notes\n 1   x   B1\n"))


def test_q1_b2_per_row_award():
    r = b.parse_pages(pages(
        HDR + "\n"
        " 1                                     3, 8, 13    -1 for every error or   B2              2\n"
        "                                                   omission\n"
        " 2                                                       180 + 54          M1              2\n"
        "                                       234                               A1\n"))
    q1 = q_by_num(r, 1)
    assert q1["total_row"] == 2
    assert q1["arithmetic_ok"] is True
    assert [p["marks"] for p in q1["points"]] == [2]
    q2 = q_by_num(r, 2)
    assert q2["total_row"] == 2
    assert [p["marks"] for p in q2["points"]] == [1, 1]
    assert r["unclassified"] == []


def test_notes_codes_are_not_awards():
    """'M1 for ...' / 'SC B1B0' live in the Notes column — never scored;
    q3's printed total is 2 (the second M1 is an alternative statement)."""
    r = b.parse_pages(pages(
        HDR + "\n"
        " 3          (75 − 69)                                                      M1              2\n"
        "                     ×100                                ± ( 75 − 69 )\n"
        "              75                                  M1 for\n"
        "                                                                    75\n"
        "                                         8                                A1\n"
        " 4                                     A(−3,8)    B1 for each coordinate   B2              2\n"
        "                                                 SC B1B0 for (1, −2 )\n"))
    q3 = q_by_num(r, 3)
    assert [p["marks"] for p in q3["points"]] == [1, 1]
    assert q3["total_row"] == 2 and q3["arithmetic_ok"] is True
    q4 = q_by_num(r, 4)
    assert [p["marks"] for p in q4["points"]] == [2]
    assert q4["arithmetic_ok"] is True
    assert all("SC" not in p["text"] for p in q4["points"])


def test_part_rows_and_glued_opener():
    """4MB1-02 q1: glued '1(a)' opener; part rows; the Total column prints
    part totals 2/3 then the question total 7 — max wins."""
    r = b.parse_pages(pages(
        HDR + "\n"
        " 1(a)    Full method to find total                                     M1              2\n"
        "                                       3750                           A1              2\n"
        " 1(b)    Stalls: 1800 Dress Circle: 1350                               B1\n"
        "                                                                      M1\n"
        "                                       $169,350                       A1              3\n"
        " 1(c)                                  175000 − ''169350''            M1\n"
        "                                       376                            A1          2 7\n"))
    q1 = q_by_num(r, 1)
    assert q1["total_row"] == 7
    assert sum(p["marks"] for p in q1["points"]) == 7
    # M1+A1 (a) + B1+M1+A1 (b) + M1+A1 (c) = 7 == printed total 7
    assert q1["arithmetic_ok"] is True
    assert [p["part"] for p in q1["points"]] == ["a", "a", "b", "b", "b", "c", "c"]


def test_dep_annotation_scores_once():
    """'(dep on M2) or for an M1' is Notes text; the Mark-column M1 scores."""
    r = b.parse_pages(pages(
        HDR + "\n"
        " 2       AC = 13     Correct method to find                            M1              5\n"
        "                    (dep on M2) or for an M1\n"
        "                    Or p = 30, q = 35                                  A1\n"))
    q2 = q_by_num(r, 2)
    assert [p["marks"] for p in q2["points"]] == [1, 1]
    assert q2["arithmetic_ok"] is False  # 2 scored vs printed 5 — honest flag
