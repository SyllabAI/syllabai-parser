"""G1.2 mark-closure lane regression tests — the five old-spec defect classes
that blocked corpus-wide mark closure (77/83 HOLD-FLAGS at the A1 gate).

Each test pins one defect with a minimal layout-text fixture:
  1. opener-only question line ('3 (a)' alone) — rows were stolen by the
     still-open previous question (4CH0 1C jun2013 q3: 3/12)
  2. digit-only marks-cell lines (4CH0 1C jun2013 q1(a), q3(e)ii/iii)
  3. article-'A' prose false positive (4CH1 1C jun2021 q1(b): 3 marks stranded)
  4. 4CH1 2019+ bare 'N marks' per-question totals (printed=None everywhere)
  5. unbounded merged-cell recovery manufacturing phantom marks (jun2013
     q3(e)iii 'recovered' 8)
"""
from pdflane import parse_ms


def _pages(*texts):
    return [{"page": i + 1, "text": t} for i, t in enumerate(texts)]


def test_opener_only_line_opens_the_question():
    pages = _pages(
        "Question\n number\n"
        "2 (a)      D                                                            1\n"
        "                                                            Total    1\n",
        "Question\n number\n"
        "3 (a)\n"
        "  (b)      M1 (it forms) barium chloride                              1\n"
        "                                                            Total    1\n",
    )
    r = parse_ms.parse_pages(pages)
    qs = {q["number"]: q for q in r["questions"]}
    # the (b) row must land on question 3, not the still-open question 2
    q3 = qs[3]
    assert q3["points"], "q3 never opened: rows stolen by previous question"
    assert q3["points"][0]["part"] == "b"
    assert q3["sum_points"] == q3["total_row"] == 1
    assert qs[2]["sum_points"] == qs[2]["total_row"] == 1


def test_digit_only_marks_cell_fills_provisional_point():
    pages = _pages(
        "Question\n number\n"
        "1 (a)      can easily identify each gas\n"
        "                                                   1\n"
        "                                                            Total    1\n"
    )
    r = parse_ms.parse_pages(pages)
    q1 = r["questions"][0]
    assert q1["points"][0]["marks"] == 1
    assert q1["sum_points"] == q1["total_row"] == 1
    assert not q1.get("demoted_points")


def test_article_a_prose_is_not_a_bare_label():
    pages = _pages(
        "Question\n number\n"
        "1 (a)      A description that refers to any three of            3\n"
        "            the following points\n"
        "                                                            Total    3\n"
    )
    r = parse_ms.parse_pages(pages)
    q1 = r["questions"][0]
    # the row must be a scored (a) point worth 3, not a stranded bare-'A'
    # pending label whose marks never arrive
    assert q1["points"], "marks stranded in a pending label"
    assert sum(p["marks"] for p in q1["points"]) == 3
    assert q1["sum_points"] == q1["total_row"] == 3


def test_bare_n_marks_line_is_a_question_total():
    pages = _pages(
        "Question\n number\n"
        "1 (a)      M1 irregular arrangement                              1\n"
        "\n"
        "                                                            3 marks\n"
    )
    r = parse_ms.parse_pages(pages)
    q1 = r["questions"][0]
    assert q1["total_row"] == 3, "bare 'N marks' total not captured"


def test_note_wrap_n_marks_is_not_a_total():
    pages = _pages(
        "Question\n number\n"
        "1 (a)      M1 working                                            1\n"
        "            Correct answer alone scores\n"
        "            2 marks\n"
        "                                                            Total    1\n"
    )
    r = parse_ms.parse_pages(pages)
    q1 = r["questions"][0]
    # the wrapped '2 marks' fragment follows its note text line — never a total
    assert q1["total_row"] == 1


def test_merged_cell_recovery_is_capped():
    # one unresolved point, diff 8 (> MARKS_CELL_MAX): rows were lost upstream,
    # the recovery must NOT manufacture an 8-mark point
    pages = _pages(
        "Question\n number\n"
        "1 (a)      M1  first point                                        1\n"
        "  (b)      M2  second point\n"
        "                                                            Total    9\n"
    )
    r = parse_ms.parse_pages(pages)
    q1 = r["questions"][0]
    marks = [p["marks"] for p in q1["points"]]
    assert 8 not in marks, "recovery manufactured a phantom 8"
    # the unresolved (b) row is demoted to notes, text preserved
    assert q1.get("demoted_points"), "unresolved row should demote, not guess"


def test_legit_small_recovery_still_works():
    # one unresolved point, diff 2 (<= MARKS_CELL_MAX): the displaced merged
    # cell is fully determined by the total — G1 behaviour preserved
    pages = _pages(
        "Question\n number\n"
        "1 (a)      M1  first point                                        1\n"
        "  (b)      M2  second point\n"
        "                                                            Total    3\n"
    )
    r = parse_ms.parse_pages(pages)
    q1 = r["questions"][0]
    b = [p for p in q1["points"] if p["part"] == "b"][0]
    assert b["marks"] == 2
    assert q1["sum_points"] == q1["total_row"] == 3
