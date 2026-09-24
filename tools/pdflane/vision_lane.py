"""pdflane vision lane (Phase 3) — FAILSAFE_PLAN §2 S0/§4.

Capabilities:
1. MIXED/SCANNED page workflow — deterministic page rasterization, then agent
   (LLM-vision) classification/transcription recorded as structured reports.
   Provenance class `llm-vision`. Everything vision-derived is review-queued by
   default ("never silently OCR'd").
2. Figure analysis — deterministic figure-crop extraction + agent classification
   (stimulus vs figure-carried content). Mark-scheme figures may CARRY answer
   content (completed diagrams/graphs); those are flagged `carries_answer=true`.
3. Deterministic scaffolding: report schema validation, k-run canonical compare,
   SHA256SUMS freeze. Judgments live in frozen artifacts, never in code.

Agent anti-role is unchanged: for born-digital text the agent never transcribes;
vision is targeted at raster content the deterministic layer cannot read.
Same-session k-run caveat applies (plan §9).
"""
import argparse
import hashlib
import json
import os

import fitz

VISION_SCHEMA_VERSION = 1
MIN_FIGURE_AREA_FRAC = 0.004

PAGE_ROLES = ("data-sheet", "cover", "photo-page", "instruction-page",
              "answer-grid", "content", "blank")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- rendering

def render_page(pdf_path, page, dpi=130, out_dir="."):
    """Deterministic page rasterization. Returns provenance-complete record."""
    doc = fitz.open(pdf_path)
    pix = doc[page - 1].get_pixmap(dpi=dpi)
    name = "%s_p%02d.png" % (os.path.splitext(os.path.basename(pdf_path))[0].upper(), page)
    path = os.path.join(out_dir, name)
    pix.save(path)
    doc.close()
    return {"png": path, "sha256": sha256_file(path), "dpi": dpi,
            "width": pix.width, "height": pix.height}


def extract_figure_crops(pdf_path, out_dir, min_area_frac=MIN_FIGURE_AREA_FRAC):
    """Deterministic figure-crop extraction (rect-anchored, 140 dpi)."""
    doc = fitz.open(pdf_path)
    crops = []
    n = 0
    for page in doc:
        for img in page.get_images(full=True):
            try:
                rects = page.get_image_rects(img[0])
            except Exception:
                continue
            for r in rects:
                frac = (r.width * r.height) / (page.rect.width * page.rect.height)
                if frac < min_area_frac:
                    continue
                clip = fitz.Rect(r.x0 - 3, r.y0 - 3, r.x1 + 3, r.y1 + 3) & page.rect
                pix = page.get_pixmap(dpi=140, clip=clip)
                n += 1
                path = os.path.join(out_dir, "%s_p%02d_%02d.png" % (
                    os.path.splitext(os.path.basename(pdf_path))[0].upper(),
                    page.number + 1, n))
                pix.save(path)
                crops.append({"page": page.number + 1, "png": path,
                              "sha256": sha256_file(path),
                              "area_frac": round(frac, 4)})
    doc.close()
    return crops


# ----------------------------------------------------------- report schemas

def validate_page_report(rep):
    """Deterministic schema check for a page vision report."""
    errs = []
    for k in ("doc", "page", "role", "has_question_content", "description",
              "provenance", "review_required"):
        if k not in rep:
            errs.append("missing:" + k)
    if rep.get("role") not in PAGE_ROLES:
        errs.append("role not in " + "|".join(PAGE_ROLES))
    if rep.get("provenance") != "llm-vision":
        errs.append("provenance must be llm-vision")
    if rep.get("has_question_content") and not rep.get("transcription_ref") \
            and not rep.get("content_note"):
        errs.append("question-content page needs transcription_ref or content_note")
    if not str(rep.get("description", "")).strip():
        errs.append("empty description")
    return errs


def validate_figure_report(rep):
    errs = []
    for k in ("png", "sha256", "doc", "page", "kind", "carries_answer",
              "description", "provenance"):
        if k not in rep:
            errs.append("missing:" + k)
    if rep.get("provenance") != "llm-vision":
        errs.append("provenance must be llm-vision")
    if rep.get("carries_answer") and rep.get("doc_kind") == "MS" \
            and not rep.get("answer_note"):
        errs.append("MS figure carrying answer needs answer_note")
    if not str(rep.get("description", "")).strip():
        errs.append("empty description")
    return errs


# ------------------------------------------------------------- k-run / freeze

def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1)


def k_run_compare(reports_a, reports_b):
    """Canonical compare of two vision runs; returns stability verdict."""
    if len(reports_a) != len(reports_b):
        return {"stable": False, "reason": "run length mismatch",
                "n": [len(reports_a), len(reports_b)]}
    diffs = []
    for a, b in zip(reports_a, reports_b):
        if canonical(a) != canonical(b):
            diffs.append({"doc": a.get("doc"), "page": a.get("page"),
                          "png": a.get("png", a.get("role", ""))})
    return {"stable": not diffs, "diffs": diffs, "n": len(reports_a)}


def freeze(out_dir, artifacts):
    """Write frozen artifacts + SHA256SUMS. Refuses nothing here; caller
    decides on instability. Returns list of relative paths."""
    lines = []
    for rel in artifacts:
        p = os.path.join(out_dir, rel)
        lines.append("%s  %s" % (sha256_file(p), rel.replace(os.sep, "/")))
    sums = os.path.join(out_dir, "SHA256SUMS")
    with open(sums, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return sorted(artifacts) + ["SHA256SUMS"]


# --------------------------------------------------------- atom attachment

def attach_figure_descriptions(parsed_dir, figure_reports):
    """Patch atoms' figures[] with vision descriptions (idempotent).

    Matches by asset basename: atom figure ref 'assets/XYZ.png' <-> report png.
    Writes atoms back only where a description was added. Returns counts.
    """
    qdir = os.path.join(parsed_dir, "questions")
    if not os.path.isdir(qdir):
        return {"atoms_patched": 0, "figures_patched": 0, "reason": "no questions dir"}
    desc = {}
    for r in figure_reports:
        base = os.path.basename(r["png"])
        desc[base] = {"role": r["kind"], "description": r["description"],
                      "carriesAnswer": r.get("carries_answer", False),
                      "provenance": "llm-vision"}
    patched = figures = 0
    for fn in sorted(os.listdir(qdir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(qdir, fn)
        with open(path, encoding="utf-8") as f:
            atom = json.load(f)
        changed = False
        for fg in atom.get("figures") or []:
            ref_base = os.path.basename(fg.get("ref", "").replace("\\", "/"))
            hit = None
            if ref_base in desc:
                hit = desc[ref_base]
            else:  # suffix match: <doc-prefix>_QP_pNN_MM.png <-> QP_pNN_MM.png
                for k in desc:
                    if k.endswith(ref_base):
                        hit = desc[k]
                        break
            if hit and "vision" not in fg:
                fg["vision"] = hit
                changed = True
                figures += 1
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(atom, f, indent=1, ensure_ascii=False)
            patched += 1
    return {"atoms_patched": patched, "figures_patched": figures}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", nargs=3, metavar=("PDF", "PAGE", "OUTDIR"))
    ap.add_argument("--crops", nargs=2, metavar=("PDF", "OUTDIR"))
    ap.add_argument("--validate-page", help="page-report JSON to validate")
    ap.add_argument("--validate-figure", help="figure-report JSON to validate")
    ap.add_argument("--compare", nargs=2, metavar=("RUN1", "RUN2"))
    ap.add_argument("--attach", nargs=2, metavar=("PARSED_DIR", "FIGREPORT"))
    args = ap.parse_args()

    if args.render:
        print(json.dumps(render_page(args.render[0], int(args.render[1]),
                                     out_dir=args.render[2]), indent=1))
    elif args.crops:
        for c in extract_figure_crops(args.crops[0], args.crops[1]):
            print(json.dumps(c))
    elif args.validate_page:
        errs = validate_page_report(json.load(open(args.validate_page, encoding="utf-8")))
        print(json.dumps({"ok": not errs, "errors": errs}))
    elif args.validate_figure:
        errs = validate_figure_report(json.load(open(args.validate_figure, encoding="utf-8")))
        print(json.dumps({"ok": not errs, "errors": errs}))
    elif args.compare:
        a = json.load(open(args.compare[0], encoding="utf-8"))
        b = json.load(open(args.compare[1], encoding="utf-8"))
        print(json.dumps(k_run_compare(a, b), indent=1))
    elif args.attach:
        reps = json.load(open(args.attach[1], encoding="utf-8"))
        print(json.dumps(attach_figure_descriptions(args.attach[0], reps), indent=1))


if __name__ == "__main__":
    main()
