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

from pdflane import gates as gates_mod
from pdflane import parse_ms, parse_qp, probe as probe_mod
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
    ap.add_argument("--out", required=True, help="parsed/ output dir")
    ap.add_argument("--slug", required=True, help="paper slug for atomIds")
    ap.add_argument("--reference", help="optional printed-truth JSON for benchmark gates")
    ap.add_argument("--qualification", default="")
    ap.add_argument("--board", default="Edexcel")
    ap.add_argument("--subject", default="")
    ap.add_argument("--paper-code", default="")
    ap.add_argument("--session", default="")
    args = ap.parse_args()

    out = args.out
    meta = os.path.join(out, "_meta")
    qdir = os.path.join(out, "questions")
    assets = os.path.join(out, "assets")
    for d in (meta, qdir, assets, os.path.join(meta, "pdftotext"),
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
            escalations.append({"unit": kind, "code": "SCANNED-PDF-NO-VISION-LANE-IN-PHASE-1",
                                "taxonomy": "EXTERNAL-PROVIDER-LIMIT",
                                "detail": "vision lane lands in Phase 2; paper not parseable deterministically"})

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
    qp_parse = parse_qp.parse_blocks(qp_blocks)
    ms_parse = parse_ms.parse_pages(ms_pages)

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
                      reference)

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

    # ---- packaging ----
    with open(os.path.join(out, "qp.md"), "w", encoding="utf-8") as f:
        f.write(open(pm_qp["md"], encoding="utf-8").read())
    with open(os.path.join(out, "ms.md"), "w", encoding="utf-8") as f:
        f.write(clean_layout_md(ms_pages))

    paper_identity = {"board": args.board, "qualification": args.qualification,
                      "subject": args.subject, "paperCode": args.paper_code,
                      "session": args.session, "slug": args.slug}
    ms_by_num = {q["number"]: q for q in ms_parse["questions"]}
    cross_engine = g["gates"]["G1"]["checks"]["cross_engine_totals"]["odl_match"]
    for q in qp_parse["questions"]:
        if q.get("orphan_total"):
            continue
        msq = ms_by_num.get(q["number"])
        flags = []
        if q["total"] is None:
            flags.append("QP-TOTAL-MISSING")
        if msq is None:
            flags.append("MS-QUESTION-MISSING")
        arith = bool(msq and msq["arithmetic_ok"])
        if msq and msq["total_row"] is not None and q["total"] is not None \
                and msq["total_row"] != q["total"]:
            flags.append("PRINTED-TOTAL-DISCREPANCY-QP-VS-MS")
        atom = {
            "atomId": "%s-q%02d" % (args.slug, q["number"]),
            "paper": paper_identity,
            "number": q["number"],
            "marks": {"total": q["total"], "msTotalRow": msq["total_row"] if msq else None,
                      "arithmeticVerified": arith},
            "prompt": {"text": q["prompt"], "pages": q["pages"], "provenance": "pdf-parsed"},
            "commandWord": None,
            "figures": [dict(fg, ref="assets/" + os.path.basename(fg["asset"])) for fg in q["figures"]],
            "markScheme": ({"points": msq["points"], "totalRow": msq["total_row"],
                            "pages": msq["pages"], "reconciled": arith,
                            "provenance": "pdf-parsed"} if msq else None),
            "confidence": "HIGH" if (not flags and arith and cross_engine) else "MEDIUM",
            "flags": flags,
            "provenance": {"lane": "pdflane-v%s-deterministic" % __import__("pdflane").__version__,
                           "engines": ["pdftotext-layout", "pymupdf-blocks", "opendataloader"]},
        }
        with open(os.path.join(qdir, "q%02d.json" % q["number"]), "w", encoding="utf-8") as f:
            json.dump(atom, f, indent=1, ensure_ascii=False)

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
        "paper": paper_identity,
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
    slim = lambda d: {k: v for k, v in d.items() if k not in ("pages",)}
    paper_json["inputs"]["QP"]["probe"] = slim(paper_json["inputs"]["QP"]["probe"])
    paper_json["inputs"]["MS"]["probe"] = slim(paper_json["inputs"]["MS"]["probe"])
    with open(os.path.join(out, "paper.json"), "w", encoding="utf-8") as f:
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
                      "flags": g["flags"], "escalations": len(escalations),
                      "review_queue": len(review)}, indent=1))
    return 0 if g["overall"] != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
