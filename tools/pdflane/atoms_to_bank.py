#!/usr/bin/env python3
"""atoms_to_bank — T-MIG-136 parse lane BAND 3 (bank assembly).

Converts the deterministic pdflane pastpaper.atoms/1.1 products (the band-2
corpus wave, 65/66 papers) into syllabai.sme-exam-questions/1.1 records and
writes the hub bundle questions.json (+ manifest counts) for igcse-maths-b-16.

OF-RECORD DESIGN (receipt parse-4mb1-band3-bank-r0):
  - records are grouped per (session, paper) — the only deterministic,
    non-manufactured grouping that exists in a mixed-topic paper archive;
    the band-1 filing's "topic slugs from the 10 spec sections" grouping
    requires a semantic classifier the zero-LLM lane does not have, so the
    deviation is RECORDED, not silently worked around. specPointCodes ship
    empty (honest) — the 135b shim therefore excludes every question from
    ingest until an anchoring pass lands (residual, operator-keyed).
  - per-part sourcePaper provenance: {date: series.printed, number:
    official_reference, questionNumber: atom number, questionPart: label+sub}.
  - ids are identity-hashed (course|series|paper|question|part), stable
    across future grammar fixes; never derived from parsed content.
  - glyph rendering law: the observed Symbol/Cambria PUA classes map
    deterministically (ASCII-identity, operators, empirically-rendered
    overrides F061->maps-to F084/F085-><=/>= F04A/F071->theta) and the
    structure-piece classes (extensible brackets, vector over-arrows,
    unresolved singletons) DROP with a per-question deterministic formatting
    note; the parser's own F06F law is honoured (dropped).
  - COW-proof: the script's write set is exactly the two maths-b bundle
    paths (fail-closed basename assertion); the archive is read-only.

Usage:
  python3 atoms_to_bank.py --archive-root <4mb1/past-papers dir> \
      --bundle-dir <apps/hub/content/igcse-maths-b-16> [--check]
"""
import argparse
import hashlib
import json
import os
import sys

import yaml

B62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

COURSE = {
    "board": "Pearson Edexcel",
    "level": "IGCSE",
    "subject": "Maths",
    "code": "4MB1",
    "syllabusVersion": "2016",
}
SOURCE = {
    "provider": "Pearson Edexcel past papers — SyllabAI/syllabai-pastpapers archive (deterministic pdflane parse)",
    "license": ("Pearson Edexcel exam material — NOT covered by the SME attestation; "
                "the operator's firing order is the authorization (134c law); "
                "ADR-013 non-commercial pilot posture; no redistribution claims"),
    "pageUrl": None,
}
SCHEMA = "syllabai.sme-exam-questions/1.1"
SECTION = "Past papers"
SECTION_SLUG = "past-papers"
PAPER_TOTAL = 100  # both 4MB1 papers are 100-mark papers (parse gaps disclosed per record)

FURNITURE = {"DO NOT WRITE IN THIS AREA"}

# ── glyph rendering law (empirically grounded, see receipt) ──────────────
GLYPH_MAP = {
    # certain ASCII-identity (Word Symbol fonts render these identically)
    "\uf028": "(", "\uf029": ")", "\uf02b": "+", "\uf02d": "\u2212",
    "\uf03c": "<", "\uf03d": "=", "\uf03e": ">", "\uf05b": "[", "\uf05d": "]",
    # operators / relations (context-certain in the archive)
    "\uf070": "\u03c0", "\uf0d0": "\u2220", "\uf0b1": "\u00b1",
    "\uf0b8": "\u00f7", "\uf0b4": "\u00d7", "\uf0a3": "\u2264",
    "\uf0b3": "\u2265", "\uf0b0": "\u00b0", "\uf0b7": "\u00b7",
    "\uf0bb": "\u2248", "\uf0b9": "\u2260", "\uf0a5": "\u221e",
    "\uf0de": "\u21d2", "\uf0c7": "\u2229", "\uf0c8": "\u222a",
    "\uf0e0": "\u2192", "\uf07b": "{", "\uf07d": "}",
    # empirically rendered overrides (glyph-clip ground truth, see receipt)
    "\uf061": "\u21a6", "\uf084": "\u2264", "\uf085": "\u2265",
    "\uf04a": "\u03b8", "\uf071": "\u03b8", "\uf0a2": "\u2032",
    # greek caps (standard Symbol positions, context-consistent)
    "\uf044": "\u0394", "\uf053": "\u03a3",
    # greek (standard Symbol lower positions; empirically consistent where checked)
    "\uf062": "\u03b2", "\uf063": "\u03b3", "\uf064": "\u03b4",
    "\uf065": "\u03b5", "\uf066": "\u03c6", "\uf067": "\u03b7",
    "\uf068": "\u03b8", "\uf069": "\u03b9", "\uf06a": "\u03ba",
    "\uf06b": "\u03bb", "\uf06c": "\u03bc", "\uf06d": "\u03bd",
    "\uf06e": "\u03be", "\uf073": "\u03c4", "\uf074": "\u03c5",
    "\uf076": "\u03c7", "\uf077": "\u03c8", "\uf078": "\u03c9",
    "\uf07a": "\u03b6", "\uf079": "\u03c8",
}
# dropped classes: extensible-bracket pieces, vector over-arrows (F072/F075
# render as the bar over AP), extended piece clusters, Cambria math pieces,
# unresolved singletons, and the parser's own F06F law.
DROP_GLYPHS = set(
    [chr(c) for c in range(0xF8E6, 0xF8FF)]
    + ["\uf026", "\uf06f", "\uf072", "\uf075",
       "\uf0e6", "\uf0e7", "\uf0e8", "\uf0e9", "\uf0ea", "\uf0eb",
       "\uf0f6", "\uf0f7", "\uf0f8", "\uf0f9", "\uf0fa", "\uf0fb",
       "\uf0ec", "\uf0ed", "\uf0ee", "\uf0ef", "\uf0fd", "\uf0fe",
       "\uf021", "\uf0a4", "\uf0ba", "\uf0bc", "\uf0e5",
       "\uf05c", "\uf0b5", "\uf0fc", "\uf020"]
)
ROMAN = {"i", "ii", "iii", "iv", "v"}

FORMAT_NOTE = ("Formatting note: the source layout uses fraction, matrix or vector "
               "structures that the deterministic text layer flattens; the original "
               "paper PDF is authoritative for the exact layout.")


def b62(n: int) -> str:
    if n == 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, 62)
        out.append(B62_ALPHABET[r])
    return "".join(reversed(out))


def _id_int(identity: str) -> int:
    # first 16 bytes (128 bits) of sha256 — collision-safe, ~22 b62 chars
    return int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32], 16)


def qid(series: str, paper: str, number) -> str:
    return "qstn_" + b62(_id_int(f"4MB1|{series}|{paper}|q{number}"))


def pid(series: str, paper: str, number, index, label, sub) -> str:
    # position-anchored: 6 atom questions carry duplicate (label, sub) pairs
    # (parser label artifacts, filed residual) — the part index disambiguates;
    # disclosed: part ids are position-sensitive until that grammar round lands
    ident = (f"4MB1|{series}|{paper}|q{number}|p{index}:{label}|"
             f"{sub if sub is not None else ''}")
    return "qstnprt_" + b62(_id_int(ident))


def tid(topic_slug: str) -> str:
    a = _id_int(f"4MB1|topic|{topic_slug}")
    b = _id_int(f"4MB1|tqst|{topic_slug}")
    return f"top_{b62(a)}--tqst_{b62(b)}"


def render_text(md):
    """Apply the glyph law to one text fragment. Returns (rendered, dropped_count)."""
    if not md:
        return "", 0
    dropped = 0
    out = []
    for ch in md:
        if ch in DROP_GLYPHS:
            dropped += 1
            continue
        out.append(GLYPH_MAP.get(ch, ch))
    return "".join(out), dropped


def render_blocks(blocks):
    """Render stem/prompt block lists into one md. Returns (md, structure_loss)."""
    parts = []
    loss = False
    for b in blocks or []:
        if b.get("type") == "answer_lines":
            continue
        raw = b.get("md")
        if raw is None:
            continue
        text = raw.strip()
        if not text or text in FURNITURE:
            continue
        rendered, dropped = render_text(text)
        if dropped:
            loss = True
        if rendered.strip():
            parts.append(rendered.strip())
    return "\n\n".join(parts), loss


def point_matches(pt, label, sub):
    """Part-matching law: the part label anchors; a point's clean roman sub
    refines it to that sub, everything else (None or noisy) stays part-level."""
    if pt.get("part") != label:
        return False
    psub = pt.get("sub")
    if psub in ROMAN:
        return psub == sub
    return True


def _point_lines(points, guidance):
    lines = []
    for pt in points or []:
        marks = pt.get("marks")
        body, _ = render_text(pt.get("md") or "")
        seg = f"**{pt.get('id')}** ({marks} mark{'s' if marks != 1 else ''}) {body}".strip()
        extras = []
        for key, word in (("allow", "Allow"), ("reject", "Reject"), ("ignore", "Ignore")):
            vals = []
            for v in pt.get(key) or []:
                t, _ = render_text(str(v))
                if t.strip():
                    vals.append(t.strip())
            if vals:
                extras.append(f"{word}: " + "; ".join(vals))
        for v in pt.get("notes") or []:
            t, _ = render_text(str(v))
            if t.strip():
                extras.append(f"Note: {t.strip()}")
        if extras:
            seg += "\n" + "\n".join("- " + e for e in extras)
        lines.append(seg)
    for g in guidance or []:
        t, _ = render_text(str(g))
        if t.strip():
            lines.append(t.strip())
    return lines


def render_points(points, guidance, label, sub, totals, verified):
    """Render one part's mark scheme deterministically. Returns (md, loss)."""
    sel = [pt for pt in (points or []) if point_matches(pt, label, sub)]
    lines = _point_lines(sel, guidance)
    md = "\n\n".join(lines)
    loss = any(_has_drop((pt.get("md") or "") + "".join(map(str, (pt.get("notes") or []) +
               [x for k in ("allow", "reject", "ignore") for x in (pt.get(k) or [])])))
               for pt in sel) or _has_drop("".join(map(str, guidance or [])))
    if totals and not verified:
        md += (f"\n\n_Parsed mark scheme: printed total {totals.get('printed')}, "
               f"parsed point-sum {totals.get('sum')} — not verified against the "
               f"mark-scheme total (deterministic parse flag). _")
    return md, loss


def render_whole_points(points, guidance, totals, verified):
    """Whole-question mark scheme (unparted questions). Returns (md, loss)."""
    lines = _point_lines(points or [], guidance)
    md = "\n\n".join(lines)
    loss = _has_drop("".join(map(str, guidance or [])) +
                     "".join((pt.get("md") or "") for pt in (points or [])))
    if totals and not verified:
        md += (f"\n\n_Parsed mark scheme: printed total {totals.get('printed')}, "
               f"parsed point-sum {totals.get('sum')} — not verified against the "
               f"mark-scheme total (deterministic parse flag). _")
    return md, loss


def _has_drop(text: str) -> bool:
    return any(ch in DROP_GLYPHS for ch in text)


def paper_label(variant: str) -> str:
    v = variant or ""
    r = v.endswith("R")
    core = v[:-1] if r else v
    n = int(core) if core.isdigit() else core
    label = f"Paper {n}"
    return label + "R" if r else label


def build_question(atom_q, series, printed, paper_ref):
    number = atom_q.get("number")
    marks = atom_q.get("marks")
    ms = atom_q.get("markScheme") or {}
    totals = ms.get("totals") or {}
    verified = bool(totals.get("verified"))
    points = ms.get("points") or []
    guidance = ms.get("guidance") or []

    stem_md, stem_loss = render_blocks(atom_q.get("stem") or [])
    loss_total = stem_loss

    parts_out = []
    atom_parts = atom_q.get("parts") or []
    if atom_parts:
        for i, p in enumerate(atom_parts):
            label = p.get("label")
            sub = p.get("sub")
            prompt_md, pl_loss = render_blocks(p.get("prompt") or [])
            loss_total = loss_total or pl_loss
            segs = [s for s in (stem_md, prompt_md) if s]
            problem_md = "\n\n".join(segs)
            sol_md, sl_loss = render_points(points, guidance, label, sub, totals, verified)
            loss_total = loss_total or sl_loss
            parts_out.append({
                "id": pid(series, paper_ref, number, i, label, sub),
                "order": i,
                "questionType": p.get("type"),
                "marks": p.get("marks"),
                "commandWord": p.get("commandWord"),
                "specPointIds": [],
                "specPointCodes": [],
                "problemMd": problem_md,
                "solutionMd": sol_md,
                "choices": None,
                "sourcePaper": {
                    "date": printed,
                    "number": paper_ref,
                    "questionNumber": number,
                    "questionPart": (label + (sub or "")) if label else None,
                },
            })
    else:
        # unparted question — one synthesized whole-question part (honest:
        # questionPart null; the whole stem is the problem, the whole MS the solution)
        problem_md = stem_md
        if not problem_md:
            hint = atom_q.get("summaryHint")
            if hint:
                problem_md, dl = render_text(str(hint))
                loss_total = loss_total or bool(dl)
        sol_md, sl_loss = render_whole_points(points, guidance, totals, verified)
        loss_total = loss_total or sl_loss
        parts_out.append({
            "id": pid(series, paper_ref, number, 0, "whole", None),
            "order": 0,
            "questionType": atom_q.get("type"),
            "marks": marks,
            "commandWord": atom_q.get("commandWord"),
            "specPointIds": [],
            "specPointCodes": [],
            "problemMd": problem_md,
            "solutionMd": sol_md,
            "choices": None,
            "sourcePaper": {
                "date": printed,
                "number": paper_ref,
                "questionNumber": number,
                "questionPart": None,
            },
        })

    if loss_total:
        for po in parts_out:
            po["problemMd"] = (po["problemMd"] + ("\n\n" if po["problemMd"] else "") +
                               f"_{FORMAT_NOTE}_")

    return {
        "id": qid(series, paper_ref, number),
        "order": (number - 1) if isinstance(number, int) else number,
        "difficulty": None,
        "style": "exam_whole",
        "totalMarks": marks,
        "parts": parts_out,
    }


def slugify_paper(series_norm: str, official_ref: str) -> str:
    return f"{series_norm}-{official_ref.lower().replace('/', '-')}"


def build_record(session_dir: str, paper_dir: str, atom_path: str, manifest_path: str):
    with open(atom_path, "r", encoding="utf-8") as f:
        atom = json.load(f)
    with open(manifest_path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)
    series = y["series"]["normalized"]
    # 4 older manifests lack series.printed — derive deterministically from normalized;
    # one archive manifest carries a doubled 'January 2019; January 2019' (acquisition
    # artifact) — first-segment sanitize, disclosed
    printed = y["series"].get("printed") or ""
    printed = printed.split(";")[0].strip()
    if not printed:
        month_map = {"01": "January", "06": "June", "10": "October", "11": "November"}
        yy, mm = series.split("-")
        printed = f"{month_map.get(mm, mm)} {yy}"
    ref = y["paper"]["official_reference"]
    variant = y["paper"]["paper_number_variant"]
    topic_slug = slugify_paper(series, ref)

    questions = [build_question(q, series, printed, ref) for q in atom.get("questions") or []]

    name = f"{printed} \u00b7 {paper_label(variant)} ({ref})"
    tm = atom.get("totalMarks")
    if atom.get("questionCount") == 0:
        name += " \u00b7 no questions parsed from the text layer (0/100 marks)"
    elif tm != PAPER_TOTAL:
        name += f" \u00b7 partial parse: {tm}/{PAPER_TOTAL} marks"

    record = {
        "topicId": tid(topic_slug),
        "slug": f"{topic_slug}--exam-questions",
        "name": name,
        "setName": None,
        "topicSlug": topic_slug,
        "section": SECTION,
        "sectionSlug": SECTION_SLUG,
        "curriculum": dict(COURSE),
        "source": dict(SOURCE),
        "schema": SCHEMA,
        "relatedNoteIds": [],
        "questions": questions,
    }
    materials = y.get("materials") or []

    def sha_of(mtype):
        return next((m.get("sha256") for m in materials if m.get("type") == mtype), None)

    meta = {
        "session": session_dir,
        "paper": paper_dir,
        "paperId": y["paper_id"],
        "series": series,
        "printed": printed,
        "ref": ref,
        "questionCount": atom.get("questionCount"),
        "totalMarks": tm,
        "marksVerified": atom.get("marksVerified"),
        "sha_qp": sha_of("question-paper"),
        "sha_ms": sha_of("mark-scheme"),
    }
    return record, meta


def iter_product_dirs(archive):
    sessions = sorted(d for d in os.listdir(archive)
                      if os.path.isdir(os.path.join(archive, d)))
    for s in sessions:
        sd = os.path.join(archive, s)
        for pd in sorted(d for d in os.listdir(sd) if os.path.isdir(os.path.join(sd, d))):
            yield s, pd, os.path.join(sd, pd, "parsed", "questions.json"), os.path.join(sd, pd, "manifest.yaml")


def build_all(archive):
    records, metas = [], []
    for s, pd, atom_path, mf_path in iter_product_dirs(archive):
        if not os.path.exists(atom_path):
            metas.append({"session": s, "paper": pd, "product": "ABSENT (fail-closed withhold)"})
            continue
        rec, meta = build_record(s, pd, atom_path, mf_path)
        records.append(rec)
        metas.append(meta)
    return records, metas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-root", required=True)
    ap.add_argument("--bundle-dir", required=True)
    ap.add_argument("--check", action="store_true",
                    help="build and verify but write nothing")
    args = ap.parse_args()

    archive = os.path.realpath(args.archive_root)
    bundle = os.path.realpath(args.bundle_dir)

    # ── COW-proof (fail-closed) ──────────────────────────────────────────
    if os.path.basename(bundle) != "igcse-maths-b-16":
        sys.exit(f"COW-FAIL: bundle dir must be igcse-maths-b-16, got {bundle}")
    out_questions = os.path.join(bundle, "questions.json")
    out_manifest = os.path.join(bundle, "manifest.json")
    if "mathematics-b/4mb1/past-papers" not in archive:
        sys.exit(f"COW-FAIL: archive root must be the 4mb1 past-papers dir: {archive}")

    records, metas = build_all(archive)

    # ── verification battery ─────────────────────────────────────────────
    fails = []
    products = [m for m in metas if "questionCount" in m]
    if len(records) != len(products):
        fails.append(f"record/product count mismatch {len(records)} != {len(products)}")
    qcount = sum(len(r["questions"]) for r in records)
    if qcount != sum(m["questionCount"] or 0 for m in products):
        fails.append("question census mismatch vs atoms")
    for r, m in zip(records, products):
        if len(r["questions"]) != m["questionCount"]:
            fails.append(f"{m['paper']}: question count {len(r['questions'])} != {m['questionCount']}")
        if sum(q["totalMarks"] or 0 for q in r["questions"]) != (m["totalMarks"] or 0):
            fails.append(f"{m['paper']}: marks total mismatch")
    qids = [q["id"] for r in records for q in r["questions"]]
    pids = [p["id"] for r in records for q in r["questions"] for p in q["parts"]]
    if len(set(qids)) != len(qids):
        fails.append("duplicate question ids")
    if len(set(pids)) != len(pids):
        fails.append("duplicate part ids")
    # determinism: rebuild and compare
    records2, _ = build_all(archive)
    b1 = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    b2 = json.dumps(records2, ensure_ascii=False, separators=(",", ":"))
    if b1 != b2:
        fails.append("non-deterministic build (double-run mismatch)")

    census = {
        "products_consumed": len(products),
        "records": len(records),
        "questions": qcount,
        "parts": len(pids),
        "marks": sum(q["totalMarks"] or 0 for r in records for q in r["questions"]),
        "records_partial_parse": [r["name"] for r in records if "partial parse" in r["name"]
                                  or "no questions parsed" in r["name"]],
        "papers_without_product": [m for m in metas if m.get("product", "").startswith("ABSENT")],
        "verification_fails": fails,
    }

    if fails:
        print(json.dumps(census, indent=2))
        sys.exit("VERIFY-FAIL: bank assembly gate held (nothing written)")

    if args.check:
        print(json.dumps(census, indent=2))
        print("CHECK-OK (dry-run, nothing written)")
        return

    # ── write single (COW-proven above) ──────────────────────────────────
    with open(out_questions, "w", encoding="utf-8") as f:
        f.write(b1)
    with open(out_manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["counts"]["questionSets"] = len(records)
    manifest["counts"]["questions"] = qcount
    manifest["counts"]["parts"] = len(pids)
    manifest["counts"]["marks"] = census["marks"]
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))

    print(json.dumps(census, indent=2))
    print(f"WROTE {out_questions} ({len(b1)} bytes) + manifest counts")


if __name__ == "__main__":
    main()
