#!/usr/bin/env python3
"""Build the REAL-CORPUS inventory for the Content Package v0.1 proof.

Inputs (committed under source/):
  - content-package-export.json  — production teacher-API export (run 34899656801)
  - bundle/{qp,ms}-canonical.json — OCR canonical documents (documentId-bound to prod)
  - revision-note.md             — verbatim canonical revision note
  - SOURCE_PROVENANCE.json       — the durable provenance chain

Outputs (generated/, deterministic):
  - inventory.json — the compiler inventory per the v0.1 contract
  - qp.md / ms.md  — Markdown artifacts rendered deterministically from the
    canonical textBlocks (the original QP.md/MS.md checksums are preserved in
    the inventory provenance block; the rendered artifact checksums are what
    the manifest pins)

Run:  python3 build_inventory.py [--source-dir .] [--out generated]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def render_markdown(canonical: dict) -> str:
    """Deterministic Markdown rendering of a canonical document.

    Rule: textBlocks in stored order; a heading block emits '#'*heading_level
    + ' ' when it carries a level; every block's text is emitted verbatim;
    blocks are joined with a blank line. No normalization, no re-wrapping.
    """
    out = []
    for block in canonical["textBlocks"]:
        text = block.get("text") or ""
        if block.get("role") == "heading" and block.get("heading_level"):
            out.append("#" * int(block["heading_level"]) + " " + text)
        else:
            out.append(text)
    return "\n\n".join(out) + "\n"


def build(source_dir: Path, out_dir: Path) -> dict:
    export = json.loads((source_dir / "content-package-export.json").read_text(encoding="utf-8"))
    qp_canonical = json.loads((source_dir / "bundle/qp-canonical.json").read_text(encoding="utf-8"))
    ms_canonical = json.loads((source_dir / "bundle/ms-canonical.json").read_text(encoding="utf-8"))
    prov = json.loads((source_dir / "SOURCE_PROVENANCE.json").read_text(encoding="utf-8"))
    note_bytes = (source_dir / "revision-note.md").read_bytes()

    pos = export["positiveCase"]
    review = pos["review"]
    header = review["paper"]
    paper_item = pos["papersListItem"]
    versions = review["versions"]

    if header["validationState"] != "VALIDATED":
        fail(f"paper {header['id']} is {header['validationState']}, not learner-servable")

    # ── rendered Markdown artifacts + their checksums ────────────────────
    qp_md = render_markdown(qp_canonical)
    ms_md = render_markdown(ms_canonical)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "qp.md").write_text(qp_md, encoding="utf-8")
    (out_dir / "ms.md").write_text(ms_md, encoding="utf-8")

    # canonical identity must bind to the production paper (link 2 ↔ link 3)
    chain = {1: None, 2: None, 3: None}
    for link in prov["provenanceChain"]:
        chain[link["link"]] = link
    if chain[2]["identity"]["questionPaperDocumentId"] != paper_item["questionPaperDocumentId"]:
        fail("QP documentId does not bind the production paper")
    if chain[2]["identity"]["markSchemeDocumentId"] != paper_item["markSchemeDocumentId"]:
        fail("MS documentId does not bind the production paper")
    if qp_canonical["documentId"] != chain[2]["identity"]["questionPaperDocumentId"]:
        fail("qp-canonical.json documentId drifted from the provenance ledger")
    if ms_canonical["documentId"] != chain[2]["identity"]["markSchemeDocumentId"]:
        fail("ms-canonical.json documentId drifted from the provenance ledger")

    # ── questions / parts / mark points from the VALIDATED review records ──
    questions = []
    for ordinal, v in enumerate(versions, start=1):
        if v["validationState"] != "VALIDATED":
            fail(f"version {v['versionId']} is {v['validationState']}")
        scheme_state = v.get("schemeState")
        scheme_id = v.get("schemeId")
        if not scheme_id or scheme_state != "VALIDATED":
            fail(f"version {v['versionId']} has no VALIDATED mark scheme (marking contract)")
        parts = []
        for p_ordinal, p in enumerate(v.get("parts") or [], start=1):
            parts.append({
                "id": p["id"],
                "anchor": p.get("label") or f"P{p_ordinal}",
                "ordinal": p_ordinal,
                "text": p.get("prompt") or "",
                "status": v["validationState"],  # inherited from the owning version
            })
        # mark points at question level with their production part linkage:
        # ref "2-a" → part anchor "a"; ref "1" (no dash) → question-level point
        # (null question_part_id in the production mark_points table)
        mark_points = []
        for mp_ordinal, mp in enumerate(v.get("points") or [], start=1):
            ref = mp.get("ref") or f"MP-{mp_ordinal}"
            part_anchor = None
            if "-" in ref:
                part_anchor = ref.split("-", 1)[1]
            mark_points.append({
                "id": mp["id"],
                "anchor": ref,
                "status": scheme_state,  # inherited from the owning scheme
                "text": mp.get("text") or "",
                "marks": mp.get("marks"),
                "partAnchor": part_anchor,
            })
        if not mark_points:
            fail(f"version {v['versionId']} has no mark points (scheme-less)")
        questions.append({
            "id": v["versionId"],
            "questionId": v["questionId"],
            "ordinal": ordinal,
            "anchor": v.get("externalRef") or f"Q{ordinal}",
            "externalRef": v.get("externalRef"),
            "stem": v.get("stem") or "",
            "marks": v.get("marks"),
            "commandWord": v.get("commandWord"),
            "type": v.get("type"),
            "status": v["validationState"],
            "markSchemeId": scheme_id,
            "parts": parts,
            "markPoints": mark_points,
        })

    # ── revision note (verbatim canonical content) ───────────────────────
    note_sha = sha256_bytes(note_bytes)
    note_provenance = {
        "id": "prov-sme-igcse-chemistry-1-3-2-calculate-relative-atomic-mass",
        "sourceType": "WEB_IMPORT",
        "sourceUri": "https://www.savemyexams.com/igcse/chemistry/edexcel/19/revision-notes/"
                     "1-principles-of-chemistry/1-3-atomic-structure/"
                     "1-3-2-calculate-relative-atomic-mass/",
        "sourceSha256": note_sha,
        "parser": "scripts/c10_map_notes.py",
        "parserVersion": "operator-validated 2026-09-11 (c10/c12 promotion records)",
        "importedAt": "2026-09-10T16:41:21+06:00",
    }

    inventory = {
        "schemaVersion": "0.1",
        "provenanceChain": prov["provenanceChain"],
        "revisionNote": {
            "id": "rn-relative-atomic-mass",
            "resourceId": "res-igcse-chemistry-relative-atomic-mass",
            "version": 1,
            "title": "Relative atomic mass",
            "status": "VALIDATED",
            "subject": "chemistry",
            "qualification": "international-gcse",
            "curriculumVersion": "4CH1-2017",
            "contentPath": "source/revision-note.md",
            "provenance": note_provenance,
            "specificationPoints": [
                {
                    "id": "4CH1-1.17",
                    "specificationId": "4CH1-2017",
                    "externalRef": "1.17",
                    "title": "be able to calculate the relative atomic mass of an element "
                             "Ar from isotopic abundances",
                    "mappingStatus": "VALIDATED",
                },
                {
                    "id": "4CH1-1.16",
                    "specificationId": "4CH1-2017",
                    "externalRef": "1.16",
                    "title": "know what is meant by the terms atomic number, mass number, "
                             "isotopes and relative atomic mass",
                    "mappingStatus": "VALIDATED",
                },
            ],
        },
        "paper": {
            "id": header["id"],
            "qualification": "international-gcse",
            "subject": "chemistry",
            "session": header.get("sessionLabel"),
            "status": header["validationState"],
            "questionPaperPath": "generated/qp.md",
            "markSchemePath": "generated/ms.md",
            "questionPaperSha256": sha256_bytes(qp_md.encode("utf-8")),
            "markSchemeSha256": sha256_bytes(ms_md.encode("utf-8")),
            "markSchemes": [
                {
                    "id": f"mscheme-{v['schemeId']}",
                    "questionId": v["versionId"],
                    "sourceSchemeId": v["schemeId"],
                    "status": v["schemeState"],
                }
                for v in versions
            ],
            "questions": questions,
            "canonicalIdentity": {
                "questionPaperDocumentId": paper_item["questionPaperDocumentId"],
                "markSchemeDocumentId": paper_item["markSchemeDocumentId"],
                "questionPaperCanonicalSourceSha256":
                    chain[2]["identity"]["questionPaperCanonicalSourceSha256"],
                "markSchemeCanonicalSourceSha256":
                    chain[2]["identity"]["markSchemeCanonicalSourceSha256"],
                "engine": chain[2]["identity"]["engine"],
                "engineVersion": chain[2]["identity"]["engineVersion"],
                "sourcePdfSha256": chain[1]["identity"]["questionPaperSha256"],
                "sourcePdfMsSha256": chain[1]["identity"]["markSchemeSha256"],
                "sourcePdfBinding": chain[1]["status"],
            },
        },
    }

    (out_dir.parent / "inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return inventory


def fail(msg: str):
    print(f"FAIL {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent / "source")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "generated")
    args = ap.parse_args()
    inv = build(args.source_dir, args.out)
    q = inv["paper"]["questions"]
    print(json.dumps({
        "status": "BUILT",
        "paperId": inv["paper"]["id"],
        "questions": len(q),
        "parts": sum(len(x["parts"]) for x in q),
        "markPoints": sum(len(p["markPoints"]) for x in q for p in x["parts"]),
        "noteSha256": inv["revisionNote"]["provenance"]["sourceSha256"][:16],
        "qpSha256": inv["paper"]["questionPaperSha256"][:16],
        "msSha256": inv["paper"]["markSchemeSha256"][:16],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
