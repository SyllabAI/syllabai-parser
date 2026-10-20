#!/usr/bin/env python3
"""tests_bank_assembly — T-MIG-136 parse lane BAND 3.

Page-verbatim fixture assertions for atoms_to_bank (the deterministic
atoms -> sme-exam-questions/1.1 assembler). The fixtures read the LIVE
archive products (the band-2 corpus wave) and pin:

  - identity-hash id scheme (stable, content-independent)
  - the glyph rendering law incl. the empirically rendered overrides
  - the furniture filter and the answer_lines omission
  - unparted-question whole-part synthesis
  - per-part sourcePaper provenance (session/paper/qnum/part)
  - unverified-totals disclosure footer
  - the part-matching law (clean roman subs refine; noisy subs stay part-level)
  - COW fail-closed assertions (wrong bundle dir / wrong archive refuse)

Run: python3 -m pytest tools/pdflane/tests_bank_assembly.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import atoms_to_bank as bank  # noqa: E402

ARCHIVE = ("/home/z/my-project/gh_repos/syllabai-pastpapers/past-papers/"
           "pearson-edexcel/international-gcse/mathematics-b/4mb1/past-papers")
PILOT = os.path.join(ARCHIVE, "2024-06", "4MB1-01")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(PILOT), reason="4mb1 archive worktree not present")


def load_atom(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── identity-hash ids ────────────────────────────────────────────────────

def test_ids_are_identity_hashed_and_stable():
    a = bank.qid("2024-06", "4MB1/01", 1)
    b = bank.qid("2024-06", "4MB1/01", 1)
    c = bank.qid("2024-06", "4MB1/01", 2)
    assert a == b and a != c
    assert a.startswith("qstn_") and len(a) - len("qstn_") in (21, 22)


def test_part_ids_are_position_anchored():
    p0 = bank.pid("2024-06", "4MB1/01", 1, 0, "a", None)
    p1 = bank.pid("2024-06", "4MB1/01", 1, 1, "b", None)
    assert p0 != p1
    # duplicate (label, sub) identities (the 2021-01/4MB1-02 q6 class) stay unique
    d0 = bank.pid("2021-01", "4MB1/02", 6, 0, "a", "ii")
    d1 = bank.pid("2021-01", "4MB1/02", 6, 1, "a", "ii")
    assert d0 != d1


# ── glyph law ────────────────────────────────────────────────────────────

def test_glyph_map_operators():
    md, dropped = bank.render_text("x\uf03d \uf02d1")
    assert md == "x= \u22121" and dropped == 0


def test_glyph_map_empirical_overrides():
    # F061 renders the maps-to arrow (glyph-clip ground truth, band-3 receipt)
    md, _ = bank.render_text("f : x \uf061 4 + 3")
    assert "\u21a6" in md
    # F084/F085 are the paired inequalities (2020-01 context: 8 <= 4x <= 18)
    md, _ = bank.render_text("8 \uf084 4x \uf085 18")
    assert md == "8 \u2264 4x \u2265 18"


def test_bracket_pieces_drop_and_flag():
    md, dropped = bank.render_text("\uf0e6 3 \uf0f6 159")
    assert "\uf0e6" not in md and "\uf0f6" not in md and "3" in md and dropped == 2


def test_vector_overarrows_drop():
    # F075/F072 render as the bar over AP (2018-06 legacy font)
    md, dropped = bank.render_text("\uf075AP \uf03d \uf02da")
    assert "\uf075" not in md and "AP" in md and dropped == 1


def test_furniture_and_answer_lines():
    blocks = [
        {"type": "para", "md": "Write 7432 to 2 significant figures."},
        {"type": "answer_lines", "count": 2},
        {"type": "para", "md": "DO NOT WRITE IN THIS AREA"},
    ]
    md, loss = bank.render_blocks(blocks)
    assert md == "Write 7432 to 2 significant figures."
    assert loss is False


# ── whole-question assembly (pilot, page-verbatim) ──────────────────────

@pytest.fixture(scope="module")
def pilot_q1():
    atom = load_atom(os.path.join(PILOT, "parsed", "questions.json"))
    q = atom["questions"][0]
    return bank.build_question(q, "2024-06", "June 2024", "4MB1/01")


def test_pilot_q1_shape(pilot_q1):
    assert pilot_q1["id"] == bank.qid("2024-06", "4MB1/01", 1)
    assert pilot_q1["order"] == 0
    assert pilot_q1["style"] == "exam_whole"
    assert pilot_q1["totalMarks"] == 2
    assert len(pilot_q1["parts"]) == 2


def test_pilot_q1_provenance(pilot_q1):
    p = pilot_q1["parts"][0]
    assert p["sourcePaper"] == {
        "date": "June 2024", "number": "4MB1/01",
        "questionNumber": 1, "questionPart": "a",
    }
    assert p["specPointCodes"] == [] and p["specPointIds"] == []
    assert p["marks"] == 1 and p["commandWord"] == "Write"
    assert p["problemMd"] == "Write 7432 to 2 significant figures."


def test_pilot_q1_solution_carries_marks(pilot_q1):
    sol = pilot_q1["parts"][0]["solutionMd"]
    assert "**P1** (1 mark)" in sol
    assert "not verified" not in sol  # pilot q1 totals ARE verified


# ── unverified footer law ────────────────────────────────────────────────

def test_unverified_footer_rendered():
    md, _ = bank.render_points(
        [{"id": "P1", "part": "a", "sub": None, "marks": 1, "md": "x", "allow": [],
          "reject": [], "ignore": [], "notes": []}],
        [], "a", None, {"printed": 2, "sum": 1}, False)
    assert "not verified against the mark-scheme total" in md


# ── part matching law ────────────────────────────────────────────────────

def test_point_matching_roman_refinement():
    pts = [
        {"id": "P1", "part": "b", "sub": "i", "marks": 1},
        {"id": "P2", "part": "b", "sub": "ii", "marks": 1},
        {"id": "P3", "part": "b", "sub": " 2a + 7b ", "marks": 1},  # noisy sub
    ]
    assert [p["id"] for p in pts if bank.point_matches(p, "b", "i")] == ["P1", "P3"]
    assert [p["id"] for p in pts if bank.point_matches(p, "b", "ii")] == ["P2", "P3"]
    assert [p["id"] for p in pts if bank.point_matches(p, "a", None)] == []


# ── record build (manifest provenance) ──────────────────────────────────

@pytest.fixture(scope="module")
def pilot_record():
    rec, meta = bank.build_record(
        "2024-06", "4MB1-01",
        os.path.join(PILOT, "parsed", "questions.json"),
        os.path.join(PILOT, "manifest.yaml"))
    return rec, meta


def test_pilot_record_identity(pilot_record):
    rec, meta = pilot_record
    assert rec["slug"] == "2024-06-4mb1-01--exam-questions"
    assert rec["topicSlug"] == "2024-06-4mb1-01"
    assert rec["name"] == "June 2024 \u00b7 Paper 1 (4MB1/01)"
    assert rec["schema"] == "syllabai.sme-exam-questions/1.1"
    assert rec["curriculum"]["code"] == "4MB1"
    assert rec["sectionSlug"] == "past-papers"
    assert meta["sha_qp"] and meta["sha_ms"]  # per-paper sha256 pinned


def test_empty_product_name_disclosure():
    # the June 2019 4MB1-02R image-only product class (0 questions) is disclosed
    empty_dir = os.path.join(ARCHIVE, "2019-06", "4MB1-02R")
    if not os.path.exists(os.path.join(empty_dir, "parsed", "questions.json")):
        pytest.skip("empty product not present")
    rec, _ = bank.build_record(
        "2019-06", "4MB1-02R",
        os.path.join(empty_dir, "parsed", "questions.json"),
        os.path.join(empty_dir, "manifest.yaml"))
    assert "no questions parsed from the text layer" in rec["name"]
    assert rec["questions"] == []


# ── COW fail-closed ─────────────────────────────────────────────────────

def test_cow_refuses_wrong_bundle(tmp_path, monkeypatch):
    wrong = tmp_path / "igcse-chemistry-19"
    wrong.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "atoms_to_bank.py",
        "--archive-root", ARCHIVE,
        "--bundle-dir", str(wrong),
    ])
    with pytest.raises(SystemExit, match="COW-FAIL"):
        bank.main()


def test_cow_refuses_wrong_archive(tmp_path, monkeypatch):
    wrong_archive = tmp_path / "past-papers"
    wrong_archive.mkdir()
    bundle = tmp_path / "igcse-maths-b-16"
    bundle.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "atoms_to_bank.py",
        "--archive-root", str(wrong_archive),
        "--bundle-dir", str(bundle),
    ])
    with pytest.raises(SystemExit, match="COW-FAIL"):
        bank.main()
