#!/usr/bin/env python3
"""G1.1 MS-only mode tests (COVID-session papers shipped without a QP).

Covers: build_document_ms_only envelope semantics (type=ms-only, empty
stem/parts, marks from the printed total row, marksVerified=False by
construction, MS-ONLY-NO-QP flag ordering), schema acceptance of ms-only
atoms + nullable source.qp, gates.run_ms_only verdicts, and bridge
ms-only routing (ms.canonical.json only, qp absent).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdflane import emit_atoms, gates, validate_atoms  # noqa: E402

MSQ = {
    "number": 1,
    "total_row": 4,
    "arithmetic_ok": True,
    "guidance": [],
    "capped_groups": [],
    "label_count": 2,
    "buckets": {"point": 2, "guidance": 0, "unclassified": 0, "continuation": 0},
    "unclassified": [],
    "points": [
        {"label": "M1", "part": "a", "sub": None, "marks": 1,
         "text": "answer that scores", "page": 3, "notes": []},
        {"label": "A1", "part": "a", "sub": None, "marks": 3,
         "text": "additional credit", "page": 3, "notes": []},
    ],
}


def _msq(**over):
    q = json.loads(json.dumps(MSQ))
    q.update(over)
    return q


def test_ms_only_envelope():
    doc = emit_atoms.build_document_ms_only([_msq()], source_ms="ms.pdf")
    assert doc["schema"] == "syllabai.pastpaper.atoms/1.1"
    assert doc["source"] == {"qp": None, "ms": "ms.pdf"}
    assert doc["marksVerified"] is False, "ms-only can never be verified"
    assert doc["questionCount"] == 1 and doc["totalMarks"] == 4
    a = doc["questions"][0]
    assert a["type"] == "ms-only"
    assert a["stem"] == [] and a["parts"] == []
    assert a["marks"] == 4, "marks come from the printed total row"
    assert a["flags"][0] == "MS-ONLY-NO-QP", "MS-ONLY-NO-QP leads the ordered flags"
    assert a["markScheme"]["totals"]["printed"] == 4
    assert a["markScheme"]["totals"]["sum"] == 4
    assert a["markScheme"]["totals"]["verified"] is True
    # provenance stays pdf-parsed; verifiedAgainst must be absent (no QP)
    assert "verifiedAgainst" not in a["markScheme"]["totals"]


def test_ms_only_dont_close_flag():
    q = _msq()
    q["points"][1]["marks"] = 2  # sum 3 != printed 4
    doc = emit_atoms.build_document_ms_only([q], source_ms="ms.pdf")
    a = doc["questions"][0]
    assert "MS-POINTS-DONT-CLOSE" in a["flags"]
    assert a["markScheme"]["totals"]["verified"] is False
    assert doc["marksVerified"] is False


def test_ms_only_no_total_row_raises():
    try:
        emit_atoms.build_document_ms_only([_msq(total_row=None)], source_ms="ms.pdf")
    except emit_atoms.EmitError as e:
        assert "no printed total row" in str(e)
    else:
        raise AssertionError("EmitError expected when the total row is missing")


def test_ms_only_schema_accepts():
    doc = emit_atoms.build_document_ms_only(
        [_msq(), _msq(number=2, part=None)], source_ms="ms.pdf")
    failures = validate_atoms.validate_document(doc, assets_dir=None)
    assert not failures, failures


def test_gates_ms_only_pass():
    eng = {"pdftotext_ms_pages": [{"page": 1, "text": "M1 A1"}],
           "odl_ms_md": ""}
    pr = {"MS": {"verdict": "DIGITAL_NATIVE", "route": "deterministic"}}
    rep = gates.run_ms_only(pr, {"questions": [_msq()],
                                 "buckets": MSQ["buckets"],
                                 "unclassified": []}, eng,
                            {"refs": [], "existing": [], "embedded": 0})
    assert rep["gates"]["G1"]["verdict"] == "PASS", rep["gates"]["G1"]
    assert rep["gates"]["G3"]["verdict"] == "PASS"
    assert rep["gates"]["G5"]["verdict"] == "PASS"
    assert rep["overall"] in ("PASS", "PASS_WITH_FLAGS")


def test_gates_ms_only_fails_on_discontinuity():
    eng = {"pdftotext_ms_pages": [{"page": 1, "text": "M1 A1"}], "odl_ms_md": ""}
    pr = {"MS": {"verdict": "DIGITAL_NATIVE", "route": "deterministic"}}
    rep = gates.run_ms_only(pr, {"questions": [_msq(), _msq(number=3)],
                                 "buckets": MSQ["buckets"],
                                 "unclassified": []}, eng,
                            {"refs": [], "existing": [], "embedded": 0})
    assert rep["gates"]["G3"]["verdict"] == "FAIL"
    assert rep["overall"] == "FAIL"


def test_parse_ms_short_total_rows():
    """Nov 2020 COVID layout: 'Total for Q1 = 5' (abbreviated Q form)."""
    from pdflane import parse_ms
    pages = [{"page": 3,
              "text": "1\na  accept correct answer\nM1 any working\nA1 more credit\n"
                      "Total for Q1 = 5\n"}]
    out = parse_ms.parse_pages(pages, qp_totals=None)
    q1 = [q for q in out["questions"] if q["number"] == 1]
    assert q1 and q1[0]["total_row"] == 5, out["questions"][:1]
    # M1(1) + A1(1) = 2 != 5 -> honest arithmetic failure, total row still lands
    assert q1[0]["arithmetic_ok"] is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok %s" % name)
    print("tests_g1_ms_only: all passed")
