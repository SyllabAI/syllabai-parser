"""pdflane orchestrator — parses one paper (QP.pdf + MS.pdf) into the
parsed/ output tree (FAILSAFE_PLAN §3.2), gates it, and writes the review
queue for anything unresolved. Phase 1: deterministic only.

Usage:
  python3 -m pdflane.run_paper --qp QP.pdf --ms MS.pdf --out <parsed-dir> \
      --slug 4ch0-1c-2012jan [--reference truth.json] [identity args]

Determinism: no timestamps in outputs; identical inputs + code produce
byte-identical parsed/ trees (S0-S1 invariant).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess

from pdflane import emit_atoms, gates as gates_mod
from pdflane import parse_ms, parse_qp, probe as probe_mod
from pdflane import s2_structurer, validate_atoms
from pdflane.extract_opendataloader import extract as odl_extract
from pdflane.extract_pdftotext import extract as pdftotext_extract
from pdflane.extract_pymupdf import extract as pymupdf_extract


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def tool_versions():
    import fitz
    try:
        pv = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True).stderr.splitlines()[0]
    except Exception:
        pv = "unknown"
    return {"pymupdf": getattr(fitz, "__version__", None) or (fitz.version[0] if hasattr(fitz, "version") else "unknown"),
            "pdftotext": pv,
            "opendataloader_cli": os.path.basename(odl_extract.__globals__["CLI_JAR"])}


def clean_layout_md(pages):
    """Cleaned page-marked markdown from the layout base layer (MS primary)."""
    lines = []
    for p in pages:
        lines.append("<!-- PAGE %d -->" % p["page"])
        for raw in p["text"].splitlines():
            ln = parse_ms.clean_line(raw)
            if ln is not None and ln.strip():
                st = ln.strip()
                m = parse_ms.TOTAL_RE.match(st)
                lines.append("**%s**" % st if m else st)
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qp", required=True)
    ap.add_argument("--ms", required=True)
    ap.add_argument("--out", required=True, help="parsed/ output dir (product files only)")
    ap.add_argument("--slug", required=True, help="paper slug (staging keys only; never emitted)")
    ap.add_argument("--meta-dir", help="staging dir for _meta lane evidence "
                                       "(default: <out>/_meta)")
    ap.add_argument("--s2-run", help="S2 accepted-run JSON (llm-structured mark scheme)")
    ap.add_argument("--s2-units", help="S2 units JSON (line->page map)")
    ap.add_argument("--corrections",
                    help="operator-authorized printed-error corrections JSON: "
                         "{questionTotalRows: {<qnum>: <corrected total>}, reason: str}")
    ap.add_argument("--source-qp", default="qp.pdf",
                    help="source file name recorded in questions.json")
    ap.add_argument("--source-ms", default="ms.pdf",
                    help="source file name recorded in questions.json")
    ap.add_argument("--reference", help="optional printed-truth JSON for benchmark gates")
    ap.add_argument("--qualification", default="")
    ap.add_argument("--board", default="Edexcel")
    ap.add_argument("--subject", default="")
    ap.add_argument("--paper-code", default="")
    ap.add_argument("--session", default="")
    args = ap.parse_args()

    out = args.out
    meta = args.meta_dir or os.path.join(out, "_meta")
    assets = os.path.join(out, "assets")
    for d in (meta, assets, os.path.join(meta, "pdftotext"),
              os.path.join(meta, "pymupdf"), os.path.join(meta, "opendataloader")):
        os.makedirs(d, exist_ok=True)

    reference = None
    if args.reference:
        with open(args.reference, encoding="utf-8") as f:
            reference = json.load(f)

    # ---- S0 probe / routing ----
    pr = probe_mod.probe_both(args.qp, args.ms)
    escalations, review = [], []
    for kind, p in pr.items():
        if p["verdict"] == "SCANNED":
            escalations.append({"unit": kind, "code": "SCANNED-PDF-NO-VISION-LANE-WIRED",
                                "taxonomy": "EXTERNAL-PROVIDER-LIMIT",
                                "detail": "vision lane available (pdflane.vision_lane); "
                                          "auto-wiring into run_paper pending"})

    # ---- S1 extraction (per-engine outputs kept separate) ----
    base_qp = pdftotext_extract(args.qp, os.path.join(meta, "pdftotext"), "QP")
    base_ms = pdftotext_extract(args.ms, os.path.join(meta, "pdftotext"), "MS")
    pm_qp = pymupdf_extract(args.qp, os.path.join(meta, "pymupdf", "QP"), "QP")
    pm_ms = pymupdf_extract(args.ms, os.path.join(meta, "pymupdf", "MS"), "MS")
    try:
        odl_qp = odl_extract(args.qp, os.path.join(meta, "opendataloader", "QP"), "QP")
        odl_ms = odl_extract(args.ms, os.path.join(meta, "opendataloader", "MS"), "MS")
    except Exception as e:  # second opinion is optional, its absence is recorded
        odl_qp = odl_ms = None
        escalations.append({"unit": "BOTH", "code": "ODL-SECOND-OPINION-UNAVAILABLE",
                            "taxonomy": "HARNESS-DEFECT", "detail": str(e)})

    # ---- deterministic structuring ----
    ms_pages = parse_ms.load_pages(base_ms["pages_json"])
    qp_blocks = parse_qp.load_blocks(pm_qp["blocks"])
    # margin-furniture strips (edge-clipped raster page furniture) never enter
    # the product stream; their crops are pruned from assets/ as unreferenced
    kept_blocks, furniture_dropped = [], []
    for b in qp_blocks:
        if b.get("kind") == "image" and emit_atoms.is_furniture_image(b.get("bbox")):
            furniture_dropped.append(b)
        else:
            kept_blocks.append(b)
    qp_blocks = kept_blocks
    for b in furniture_dropped:
        review.append({"code": "QP-IMAGE-FURNITURE-DROPPED",
                       "taxonomy": "SOURCE-DISCREPANCY",
                       "detail": {"page": b.get("page"),
                                  "bbox": b.get("bbox"),
                                  "asset": b.get("text", "")}})
    qp_parse = parse_qp.parse_blocks(qp_blocks)
    ms_parse = parse_ms.parse_pages(ms_pages)

    corrections = None
    corrections_reason = None
    if args.corrections:
        with open(args.corrections, encoding="utf-8") as f:
            cdata = json.load(f)
        corrections = {int(k): int(v)
                       for k, v in (cdata.get("questionTotalRows") or {}).items()}
        corrections_reason = cdata.get("reason", "")

    # ---- S2 accepted run (loaded before the gates: a validated S2 run is the
    # designed lane for merged-marks-cell MS layouts and supersedes the
    # deterministic point-arithmetic check in G1 — see gates.run docstring) ----
    s2_by_num = {}
    if args.s2_run:
        with open(args.s2_run, encoding="utf-8") as f:
            s2_run = json.load(f)
        for s2q in s2_run.get("questions", []):
            s2_by_num[s2q["number"]] = s2q
    s2_arithmetic = None
    if s2_by_num:
        per_q, ok_all = {}, True
        for qn in sorted(s2_by_num):
            s2q = s2_by_num[qn]
            es = s2_structurer.effective_sum(s2q)
            per_q[qn] = {"effectiveSum": es, "totalRow": s2q.get("totalRow")}
            ok_all = ok_all and (s2q.get("totalRow") is not None and es == s2q["totalRow"])
        s2_arithmetic = {"verified": ok_all, "detail": {"perQuestion": per_q}}

    # ---- gates ----
    eng_texts = {
        "pymupdf_qp_md": open(pm_qp["md"], encoding="utf-8").read(),
        "pdftotext_ms_pages": ms_pages,
        "odl_qp_md": open(odl_qp["md"], encoding="utf-8").read() if odl_qp else "",
        "odl_ms_md": open(odl_ms["md"], encoding="utf-8").read() if odl_ms else "",
    }
    # copy pymupdf figure crops into parsed/assets
    asset_refs = []
    for src_dir in (pm_qp["assets_dir"], pm_ms["assets_dir"]):
        for fn in sorted(os.listdir(src_dir)):
            shutil.copyfile(os.path.join(src_dir, fn), os.path.join(assets, fn))
            asset_refs.append("assets/" + fn)
    embedded = len(pm_qp["assets"]) + len(pm_ms["assets"])
    g = gates_mod.run(pr, qp_parse, ms_parse, eng_texts,
                      {"refs": asset_refs,
                       "existing": sorted("assets/" + f for f in os.listdir(assets)),
                       "embedded": embedded},
                      reference, s2_arithmetic=s2_arithmetic)

    # review queue + escalations from gate outcomes
    for fl in g["flags"]:
        review.append({"code": fl["code"], "taxonomy": fl["taxonomy"], "detail": fl["detail"]})
    # content-page rows the parsers could not classify -> review queue
    for u in ms_parse["unclassified"]:
        if u["page"] >= 3:
            review.append({"code": "MS-UNCLASSIFIED-ROW", "taxonomy": "HARNESS-DEFECT",
                           "detail": u})
    for gate_name, gv in g["gates"].items():
        if gv["verdict"] == "FAIL":
            escalations.append({"unit": gate_name, "code": "GATE-FAIL",
                                "taxonomy": "HARNESS-DEFECT",
                                "detail": {k: v for k, v in gv.items() if k != "verdict"}})

    # ---- packaging (v2: syllabai.pastpaper.atoms/1.1) ----
    # (s2_by_num was loaded before the gates for the arithmetic-supersede check)
    line_page = None
    if args.s2_units:
        with open(args.s2_units, encoding="utf-8") as f:
            s2_units = json.load(f)
        line_page = {l["n"]: l["page"] for l in s2_units.get("lines", [])}
    for q in ms_parse["questions"]:
        q["_s2"] = s2_by_num.get(q["number"])

    v2_atoms = emit_atoms.build_qp_atoms(qp_blocks)
    emit_atoms.crosscheck_qp(v2_atoms, qp_parse)  # hard equivalence gate
    doc = emit_atoms.build_document(v2_atoms, ms_parse["questions"], line_page,
                                    source_qp=args.source_qp, source_ms=args.source_ms,
                                    s2_by_num=s2_by_num, corrections=corrections)

    with open(os.path.join(out, "questions.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out, "qp.md"), "w", encoding="utf-8") as f:
        f.write(open(pm_qp["md"], encoding="utf-8").read())
    with open(os.path.join(out, "ms.md"), "w", encoding="utf-8") as f:
        f.write(emit_atoms.render_ms_md(doc))

    # prune front-matter crops no atom references (they remain in _meta staging)
    referenced = set()

    def _collect(blocks):
        for b in blocks:
            if b["type"] == "image":
                referenced.add(b["src"].split("/", 1)[1])
    for q in doc["questions"]:
        _collect(q["stem"])
        for p in q["parts"]:
            _collect(p["prompt"])
        msq = q["markScheme"]
        for im in msq.get("images", []):
            referenced.add(im["src"].split("/", 1)[1])
        for pt in msq["points"]:
            if pt.get("image"):
                referenced.add(pt["image"]["src"].split("/", 1)[1])
    for fn in sorted(os.listdir(assets)):
        if fn not in referenced:
            os.remove(os.path.join(assets, fn))
            review.append({"code": "FRONT-MATTER-ASSET-PRUNED",
                           "taxonomy": "HARNESS-DEFECT",
                           "detail": "assets/%s not referenced by any atom" % fn})

    # V1-V4 gates on the final product set
    failures = validate_atoms.validate_document(doc, assets)
    if failures:
        for f in failures:
            review.append({"code": "V2-VALIDATION", "taxonomy": "HARNESS-DEFECT",
                           "detail": f})
        escalate_v2 = True
    else:
        escalate_v2 = False

    def relativize(d):
        """Make engine-output records location-independent (byte-determinism)."""
        out_d = {}
        for k, v in (d or {}).items():
            if isinstance(v, str) and (v.startswith("/") or v.startswith(".")):
                out_d[k] = os.path.relpath(v, out) if os.path.isabs(v) else v
            else:
                out_d[k] = v
        return out_d

    paper_json = {
        "slug": args.slug,
        "inputs": {"QP": {"sha256": sha256_file(args.qp), "probe": pr["QP"]},
                   "MS": {"sha256": sha256_file(args.ms), "probe": pr["MS"]}},
        "routing": {k: v["route"] for k, v in pr.items()},
        "engines": tool_versions(),
        "engine_outputs": {"pymupdf": {"qp": relativize(pm_qp), "ms": relativize(pm_ms)},
                           "pdftotext": {"qp": relativize(base_qp), "ms": relativize(base_ms)},
                           "opendataloader": {"qp": relativize(odl_qp), "ms": relativize(odl_ms)}},
        "gates": {"overall": g["overall"], "failed": g["failed_gates"],
                  "detail": {k: v["verdict"] for k, v in g["gates"].items()}},
        "census": {"qp_questions": len([q for q in qp_parse["questions"] if not q.get("orphan_total")]),
                   "qp_sum_totals": sum(q["total"] for q in qp_parse["questions"] if q["total"]),
                   "qp_witnesses": qp_parse["witnesses"],
                   "ms_questions": len(ms_parse["questions"]),
                   "ms_point_labels": ms_parse["label_count"],
                   "ms_label_buckets": ms_parse["buckets"],
                   "ms_total_rows": ms_parse["total_rows_found"]},
        "escalations": escalations,
        "reviewQueue": review,
        "provenance": {"lane": "pdflane deterministic phase-1",
                       "provenance_classes": ["pdf-parsed"]},
    }
    if corrections:
        paper_json["corrections"] = {"applied": {str(k): v for k, v in corrections.items()},
                                     "reason": corrections_reason,
                                     "authorized": "operator 2026-09-19"}
    slim = lambda d: {k: v for k, v in d.items() if k not in ("pages",)}
    paper_json["inputs"]["QP"]["probe"] = slim(paper_json["inputs"]["QP"]["probe"])
    paper_json["inputs"]["MS"]["probe"] = slim(paper_json["inputs"]["MS"]["probe"])
    with open(os.path.join(meta, "paper.json"), "w", encoding="utf-8") as f:
        json.dump(paper_json, f, indent=1, ensure_ascii=False)

    with open(os.path.join(meta, "escalations.jsonl"), "w", encoding="utf-8") as f:
        for e in escalations:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(meta, "review-queue.jsonl"), "w", encoding="utf-8") as f:
        for r in review:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(meta, "extraction.json"), "w", encoding="utf-8") as f:
        json.dump({"engine_output_digests": {
            "pymupdf_qp_md": sha256_text(open(pm_qp["md"], encoding="utf-8").read()),
            "pymupdf_ms_md": sha256_text(open(pm_ms["md"], encoding="utf-8").read()),
            "pdftotext_qp_md": sha256_text(open(base_qp["md"], encoding="utf-8").read()),
            "pdftotext_ms_md": sha256_text(open(base_ms["md"], encoding="utf-8").read()),
            "odl_qp_md": sha256_text(eng_texts["odl_qp_md"]) if odl_qp else None,
            "odl_ms_md": sha256_text(eng_texts["odl_ms_md"]) if odl_ms else None,
        }, "reference_used": bool(reference)}, f, indent=1)

    print(json.dumps({"overall": g["overall"], "failed_gates": g["failed_gates"],
                      "gates": {k: v["verdict"] for k, v in g["gates"].items()},
                      "census": paper_json["census"],
                      "v2": {"schema": doc["schema"], "questionCount": doc["questionCount"],
                             "totalMarks": doc["totalMarks"],
                             "marksVerified": doc["marksVerified"],
                             "validation": "PASS" if not failures else failures,
                             "flagged": [q["number"] for q in doc["questions"]
                                         if q.get("flags")]},
                      "flags": g["flags"], "escalations": len(escalations),
                      "review_queue": len(review)}, indent=1))
    return 0 if not escalate_v2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
