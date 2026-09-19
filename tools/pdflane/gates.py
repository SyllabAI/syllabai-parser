"""Gates G1-G5 — the failsafe core (FAILSAFE_PLAN §4 Stage 3).

Reuses the metrics that caught every recorded OCR failure:
  G1 marks integrity: per-question totals present; sum == paper witness;
     MS total rows present; MS point-sum arithmetic; cross-engine agreement
  G2 label census:   parsed point labels == raw text-layer labels (== ODL)
  G3 structure:      QP count == MS count == continuous numbering
  G4 assets:         every figure ref resolves; extracted == embedded
  G5 schema:         required fields + provenance completeness

Verdicts: PASS | PASS_WITH_FLAGS | FAIL. Printed QP-vs-MS total
discrepancies (e.g. Jan-2012 Q3: QP 13 vs MS 11, recorded N-001) are FLAGS
with review-queue entries, not engine failures — the engine must surface
them, not hide them.
"""
import json
import os
import re

TOTAL_FOR_Q_RE = re.compile(
    r"Total\s+for\s+Question\s*(\d{1,2})\s*(?:=|is)\s*(\d{1,3})\s*marks?", re.I)
LAYOUT_TOTAL_RE = re.compile(r"^\s*Total\s+(\d{1,3})\s+marks?\s*$", re.I)
# 4CH1 2024 'Total N' bare variant (no 'marks' suffix); mirrors
# parse_ms.TOTAL_BARE_RE so the layout-sequence scanner sees the same
# total rows the deterministic parser closes questions with.
LAYOUT_TOTAL_BARE_RE = re.compile(r"^\s*Total\s+(\d{1,3})\s*$")
LAYOUT_LABEL_RE = re.compile(r"\b[MA]\d{1,2}\b")


def totals_from_qp_md(md_text):
    out = {}
    for m in TOTAL_FOR_Q_RE.finditer(md_text):
        out[int(m.group(1))] = int(m.group(2))
    return out


def totals_from_layout(pages):
    """Sequence-resolved total rows from the layout text: in reading order,
    the i-th total row closes question i."""
    vals = []
    for p in pages:
        for line in p["text"].splitlines():
            m = LAYOUT_TOTAL_RE.match(line) or LAYOUT_TOTAL_BARE_RE.match(line)
            if m:
                vals.append(int(m.group(1)))
    return {i + 1: v for i, v in enumerate(vals)}


def labels_in(text):
    return len(LAYOUT_LABEL_RE.findall(text))


def run(probe, qp_parse, ms_parse, engine_texts, assets_check, reference=None,
        s2_arithmetic=None):
    """engine_texts: {"pymupdf_qp_md":..., "pdftotext_ms_pages":[...],
                      "odl_qp_md":..., "odl_ms_md":...}
    assets_check: {"refs": [...], "existing": [...], "embedded": n}
    reference: optional printed truth {"qp_totals": {...}, "paper_total": 120,
               "ms_total_rows": {...}, "ms_labels": 168, "questions": 11}
    s2_arithmetic: optional {"verified": bool, "detail": {...}} — outcome of
               per-question effective-sum vs totalRow checks over a VALIDATED
               S2 accepted run. When verified, the deterministic
               ms_point_arithmetic mismatch (merged-marks-cell layouts the
               line grammar cannot capture — designed path: S2 lane) is
               superseded, but the raw mismatch stays in the check detail and
               a review flag keeps the substitution on record."""
    rep = {"gates": {}, "flags": [], "escalations": []}
    ref = reference or {}

    # ---- G1 marks integrity ----
    g1 = {"checks": {}}
    qp_totals = {q["number"]: q["total"] for q in qp_parse["questions"] if not q.get("orphan_total")}
    missing = [q["number"] for q in qp_parse["questions"] if q["total"] is None]
    g1["checks"]["qp_totals_present"] = {"ok": not missing, "missing": missing}
    s = sum(v for v in qp_totals.values() if v)
    witness_vals = sorted({w["value"] for w in qp_parse["witnesses"]})
    paper_total = ref.get("paper_total")
    g1["checks"]["qp_sum_vs_witness"] = {
        "ok": bool(witness_vals) and s in witness_vals,
        "sum": s, "witnesses": witness_vals}
    ms_totals = {q["number"]: q["total_row"] for q in ms_parse["questions"]}
    ms_missing = [q["number"] for q in ms_parse["questions"] if q["total_row"] is None]
    g1["checks"]["ms_total_rows_present"] = {"ok": not ms_missing, "missing": ms_missing,
                                             "found": len(ms_totals)}
    arith_bad = [q["number"] for q in ms_parse["questions"] if not q["arithmetic_ok"]]
    arith_check = {"ok": not arith_bad, "mismatch": arith_bad}
    if arith_bad and s2_arithmetic and s2_arithmetic.get("verified"):
        arith_check = {"ok": True, "mismatch": arith_bad,
                       "superseded_by": "s2-validated-run",
                       "detail": s2_arithmetic.get("detail", {})}
        rep["flags"].append({"code": "DETERMINISTIC-MS-ARITHMETIC-SUPERSEDED-BY-S2",
                             "taxonomy": "HARNESS-DEFECT",
                             "detail": {"mismatch": arith_bad,
                                        "reason": "merged-marks-cell layout; "
                                                  "deterministic line grammar "
                                                  "undercount superseded by the "
                                                  "validated S2 accepted run "
                                                  "(designed lane)"}})
    g1["checks"]["ms_point_arithmetic"] = arith_check
    # cross-engine agreement on QP totals (blocks parse vs ODL second opinion)
    odl = totals_from_qp_md(engine_texts.get("odl_qp_md") or "")
    agree = (qp_totals == odl) if engine_texts.get("odl_qp_md") else None
    g1["checks"]["cross_engine_totals"] = {"ok": agree is not False, "odl_match": agree,
                                           "odl_totals": odl}
    # MS base-layer agreement: parsed totals == sequence of total rows in raw layout
    layout_totals = totals_from_layout(engine_texts["pdftotext_ms_pages"])
    g1["checks"]["ms_totals_vs_layout_sequence"] = {"ok": ms_totals == layout_totals,
                                                    "layout_sequence": layout_totals}
    # printed QP vs MS discrepancy -> flag (source truth, not engine defect)
    disc = []
    for qn in sorted(set(qp_totals) & set(ms_totals)):
        if qp_totals[qn] != ms_totals[qn]:
            disc.append({"question": qn, "qp_printed": qp_totals[qn],
                         "ms_printed": ms_totals[qn]})
    if disc:
        rep["flags"].append({"code": "PRINTED-QP-MS-TOTAL-DISCREPANCY",
                             "taxonomy": "SOURCE-DISCREPANCY", "detail": disc})
    if ref.get("qp_totals"):
        ref_totals = {int(k): v for k, v in ref["qp_totals"].items()}
        wrong = {q: v for q, v in ref_totals.items() if qp_totals.get(q) != v}
        g1["checks"]["vs_reference"] = {"ok": not wrong, "mismatch": wrong}
    g1["verdict"] = ("PASS" if all(c.get("ok") for c in g1["checks"].values()) else "FAIL")
    rep["gates"]["G1"] = g1

    # ---- G2 label accounting ----
    raw_labels = labels_in("".join(p["text"] for p in engine_texts["pdftotext_ms_pages"]))
    b = ms_parse["buckets"]
    odl_labels = labels_in(engine_texts.get("odl_ms_md") or "")
    g2 = {"raw_layout": raw_labels,
          "parsed_points": b["point"],
          "guidance_labels": b["guidance"],
          "unclassified_labels": b["unclassified"],
          "odl_second_opinion": odl_labels}
    # failsafe accounting: every raw label token lands in exactly one bucket
    g2["accounted"] = raw_labels == (b["point"] + b["guidance"] +
                                     b["unclassified"] + b["continuation"])
    g2["ok"] = g2["accounted"]
    if ref.get("ms_labels_raw"):
        g2["reference"] = ref["ms_labels_raw"]
        g2["ok"] = g2["ok"] and raw_labels == ref["ms_labels_raw"]
    if b["unclassified"]:
        rep["flags"].append({"code": "MS-UNACCOUNTED-CONTENT",
                             "taxonomy": "HARNESS-DEFECT",
                             "detail": {"rows": len(ms_parse["unclassified"]),
                                        "labels": b["unclassified"]}})
    g2["verdict"] = "PASS" if g2["ok"] else "FAIL"
    rep["gates"]["G2"] = g2

    # ---- G3 structure ----
    qpn = [q["number"] for q in qp_parse["questions"] if not q.get("orphan_total")]
    msn = [q["number"] for q in ms_parse["questions"]]
    continuous_qp = qpn == list(range(1, len(qpn) + 1))
    continuous_ms = msn == list(range(1, len(msn) + 1))
    g3 = {"qp_count": len(qpn), "ms_count": len(msn),
          "continuous_qp": continuous_qp, "continuous_ms": continuous_ms,
          "equal_counts": len(qpn) == len(msn)}
    if ref.get("questions"):
        g3["reference"] = ref["questions"]
        g3["equal_counts"] = g3["equal_counts"] and len(qpn) == ref["questions"]
    g3["ok"] = all([continuous_qp, continuous_ms, g3["equal_counts"]])
    g3["verdict"] = "PASS" if g3["ok"] else "FAIL"
    rep["gates"]["G3"] = g3

    # ---- G4 assets ----
    missing_assets = [r for r in assets_check["refs"] if r not in assets_check["existing"]]
    g4 = {"refs": len(assets_check["refs"]),
          "missing_files": missing_assets,
          "extracted": len(assets_check["existing"]),
          "embedded": assets_check["embedded"]}
    g4["ok"] = not missing_assets and g4["extracted"] == g4["embedded"]
    g4["verdict"] = "PASS" if g4["ok"] else "FAIL"
    rep["gates"]["G4"] = g4

    # ---- G5 schema ----
    problems = []
    for q in qp_parse["questions"]:
        if not q["pages"]:
            problems.append("qp q%d empty pages" % q["number"])
        if not q["prompt"]:
            problems.append("qp q%d empty prompt" % q["number"])
    for q in ms_parse["questions"]:
        if not q["points"]:
            problems.append("ms q%d has no mark points" % q["number"])
    g5 = {"problems": problems}
    g5["ok"] = not problems
    g5["verdict"] = "PASS" if g5["ok"] else "FAIL"
    rep["gates"]["G5"] = g5

    fails = [k for k, v in rep["gates"].items() if v["verdict"] == "FAIL"]
    rep["overall"] = "FAIL" if fails else ("PASS_WITH_FLAGS" if rep["flags"] else "PASS")
    rep["failed_gates"] = fails
    return rep


if __name__ == "__main__":
    print("gates.py is a library module; run via pdflane.run_paper")
