"""clean_diff.py — Stage B acceptance gate G3 (T-C17 §9), implemented per T-C16.

Machine-checkable subset of the protocol's G3, over extraction DRAFT bundles
(`qp-draft.json` / `ms-draft.json` from `GlmOcrPairCli`, or any producer with the
same schema — verified shapes: QP `questions[]` with `parts[{label, marks}]`,
`mcq`/`options`, top-level `warnings[]`; MS `entries[]` with `markPoints[]`,
top-level `warnings[]`):

  G3.1  clean question count <= raw question count (spillover removal is the point);
  G3.2  every (number, part_label, marks) present in BOTH drafts carries IDENTICAL
        marks — cleaning may remove phantom entries, never change real ones;
  G3.3  MS mark-point count equal-or-lower;
  G3.4  no new warning classes except the documented `boilerplate-removed`;
  G3.5  paperTotalConflict is false/absent, or unchanged from raw (reviewed conflict).

Element ids and reading order are deliberately NOT compared: drafts carry positional
`e%06d` ids that shift under removal by construction (T-C17 §9). The "explainable
line-by-line" requirement stays human-audited (T-C17 §13) — this gate proves the
invariants, the clean-report operations ledger provides the explainability.

Deterministic, stdlib-only. Exit 0 = all checks pass, 1 = any FAIL, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BOILERPLATE_REMOVED = "boilerplate-removed"


def warning_class(w) -> str:
    """Warning class of a draft warning (plain strings in real bundles)."""
    s = str(w)
    if BOILERPLATE_REMOVED in s:
        return BOILERPLATE_REMOVED
    return s.split(":", 1)[0].strip() if ":" in s else s.strip()


def question_structure(qp_draft: dict) -> dict[str, str | None]:
    """(number, part_label) -> marks for one QP draft. Parts carry labels; questions
    without parts contribute (number, None) with the question-level marks."""
    structure: dict[str, str | None] = {}
    for q in qp_draft.get("questions", []):
        number = str(q.get("number"))
        parts = q.get("parts") or []
        if parts:
            for p in parts:
                structure[(number, str(p.get("label")))] = p.get("marks")
        else:
            structure[(number, None)] = q.get("marks")
    return structure


def mark_point_count(ms_draft: dict | None) -> int:
    if not ms_draft:
        return 0
    total = 0
    for entry in ms_draft.get("entries", []):
        mp = entry.get("markPoints")
        if isinstance(mp, list):
            total += len(mp)
    return total


def run_gate(qp_raw: dict, qp_clean: dict, ms_raw: dict | None = None,
             ms_clean: dict | None = None) -> dict:
    checks: list[dict] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        checks.append({"id": cid, "status": "pass" if ok else "FAIL", "detail": detail})

    # G3.1 — question count strictly lower or equal
    n_raw = len(qp_raw.get("questions", []))
    n_clean = len(qp_clean.get("questions", []))
    add("G3.1", n_clean <= n_raw, f"questions raw={n_raw} clean={n_clean}")

    # G3.2 — shared (number, part_label) identical marks
    raw_struct = question_structure(qp_raw)
    clean_struct = question_structure(qp_clean)
    shared = sorted(set(raw_struct) & set(clean_struct), key=lambda k: (k[0], k[1] or ""))
    mismatches = [
        {"number": n, "part": l, "raw_marks": raw_struct[(n, l)], "clean_marks": clean_struct[(n, l)]}
        for (n, l) in shared if raw_struct[(n, l)] != clean_struct[(n, l)]
    ]
    add("G3.2", not mismatches,
        f"shared entries={len(shared)} mark mismatches={len(mismatches)}"
        + (f" first: {mismatches[0]}" if mismatches else ""))

    # G3.3 — MS mark-point count equal-or-lower
    mp_raw, mp_clean = mark_point_count(ms_raw), mark_point_count(ms_clean)
    add("G3.3", mp_clean <= mp_raw, f"mark points raw={mp_raw} clean={mp_clean}")

    # G3.4 — warning classes: none new except boilerplate-removed
    raw_classes = Counter(warning_class(w) for w in qp_raw.get("warnings", []))
    clean_classes = Counter(warning_class(w) for w in qp_clean.get("warnings", []))
    if ms_raw is not None:
        raw_classes += Counter(warning_class(w) for w in ms_raw.get("warnings", []))
    if ms_clean is not None:
        clean_classes += Counter(warning_class(w) for w in ms_clean.get("warnings", []))
    new_classes = sorted(
        c for c, cnt in clean_classes.items()
        if cnt > raw_classes.get(c, 0) and c != BOILERPLATE_REMOVED
    )
    add("G3.4", not new_classes,
        f"raw classes={dict(raw_classes)} clean classes={dict(clean_classes)}"
        + (f" NEW={new_classes}" if new_classes else ""))

    # G3.5 — paperTotalConflict false/absent or unchanged reviewed conflict
    conflict_raw = qp_raw.get("paperTotalConflict")
    conflict_clean = qp_clean.get("paperTotalConflict")
    ok = (conflict_clean in (None, False)) or (conflict_clean == conflict_raw)
    add("G3.5", ok, f"raw={conflict_raw!r} clean={conflict_clean!r}")

    return {
        "gate": "G3",
        "result": "PASS" if all(c["status"] == "pass" for c in checks) else "FAIL",
        "counts": {
            "questions_raw": n_raw,
            "questions_clean": n_clean,
            "mark_points_raw": mp_raw,
            "mark_points_clean": mp_clean,
        },
        "checks": checks,
    }


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage B gate G3 — raw-vs-clean draft diff")
    ap.add_argument("--qp-raw", required=True, help="raw QP draft JSON (qp-draft.json)")
    ap.add_argument("--qp-clean", required=True, help="clean QP draft JSON")
    ap.add_argument("--ms-raw", help="raw MS draft JSON (ms-draft.json), optional")
    ap.add_argument("--ms-clean", help="clean MS draft JSON, optional")
    ap.add_argument("--json-out", help="write the gate report JSON here (for clean-report)")
    args = ap.parse_args(argv)

    report = run_gate(
        _load_json(Path(args.qp_raw)),
        _load_json(Path(args.qp_clean)),
        _load_json(Path(args.ms_raw)) if args.ms_raw else None,
        _load_json(Path(args.ms_clean)) if args.ms_clean else None,
    )
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileNotFoundError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        sys.exit(2)
