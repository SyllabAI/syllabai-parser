"""Corpus health gate for GLM-OCR markdown pairs (OCR-Q4).

A zero-network sanity gate for the GLM-OCR corpus: given one QP/MS pair (or a
directory tree of them), it verifies the invariants the pipeline depends on
and reports anything a human must review. Built on the reference extractors
(``canonical.py`` + ``question_extractor.py`` + ``markscheme_extractor.py``)
as a read-only consumer — it never mutates them and never fetches URLs.

Checks per pair (fail-loud philosophy, Master Spec §7 semantics):

1. ``questionMarkSums`` — per question: sum of extracted part marks vs the
   printed "Total for Question N" line. Conflict = FAIL (a split went wrong
   or the paper itself is inconsistent); unknown part marks = REVIEW.
2. ``qpMsTotals`` — printed question totals must agree between QP and MS.
   Mismatch = FAIL (the audited 1A 80-vs-120 class of defect), missing on
   one side = REVIEW.
3. ``paperMapping`` — every QP question number must have MS entries and vice
   versa. Gaps = REVIEW (never silently merged — reconciliation rule D6).
4. ``paperTotal`` — QP cover total vs MS total vs the sum of question
   totals. Mismatch = FAIL; missing = REVIEW.
5. ``assets`` — markdown figure references vs the local filesystem, purely
   offline: with a manifest.json / assets/ directory present, every expected
   file must exist (missing = FAIL — a local inconsistency); bare signed
   URLs with no local backing are the audited-corpus state and are reported
   as knownUnavailable = REVIEW (honesty: nothing is fetched, nothing faked).

Output: deterministic JSON report (``--json`` or ``-o out.json``) plus a
human-readable summary on stdout. Exit code 1 when any check FAILs, 0
otherwise (REVIEW items do not fail the run unless ``--fail-on-review``).

This tool is additive content-operations tooling (polyglot policy ADR-011):
it does not change the canonical contract, the Java parser, or conformance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .canonical import GlmOcrMarkdownParser
from .markscheme_extractor import GlmOcrMarkSchemeExtractor
from .question_extractor import GlmOcrQuestionExtractor

TOOL_NAME = "glmocr-health"
REPORT_SCHEMA_VERSION = "1.0"

ROLE_TOKENS_QP = re.compile(r"(?:^|[\s_\-])(qp|que|question)(?:[\s_\-]|\b)", re.I)
ROLE_TOKENS_MS = re.compile(r"(?:^|[\s_\-])(ms|msc|answers)(?:[\s_\-]|\b)|mark\s+scheme", re.I)
SIGNED_URL_HOST = re.compile(r"^https?://[^/]*(?:ufileos\.com|maas-watermark)", re.I)

OK, REVIEW, FAIL = "ok", "review", "fail"


# ── pairing (simplified from the batch tool: same token rules) ────────────────

def _role_of(name: str):
    qp = bool(ROLE_TOKENS_QP.search(name))
    ms = bool(ROLE_TOKENS_MS.search(name))
    if qp and not ms:
        return "QP"
    if ms and not qp:
        return "MS"
    return None


def _fingerprint(path: Path, root: Path):
    name = path.stem
    name = ROLE_TOKENS_MS.sub(" ", name)
    name = ROLE_TOKENS_QP.sub(" ", name)
    name = re.sub(r"[\s_\-]+", " ", name).strip().lower()
    return (str(path.parent.relative_to(root)), name)


def find_pairs(root: Path):
    """Auto-pair markdown files under *root*; ambiguous files are skipped loudly."""
    files = sorted(p for p in root.rglob("*.md") if p.is_file())
    by_fp = {}
    for p in files:
        role = _role_of(p.name)
        if role is None:
            continue
        by_fp.setdefault(_fingerprint(p, root), {}).setdefault(role, []).append(p)
    pairs, skipped = [], []
    for fp, roles in sorted(by_fp.items()):
        qp_list, ms_list = roles.get("QP", []), roles.get("MS", [])
        if len(qp_list) == 1 and len(ms_list) == 1:
            pairs.append((qp_list[0], ms_list[0]))
        else:
            for p in qp_list + ms_list:
                skipped.append({
                    "file": str(p),
                    "reason": ("ambiguous: %d QP / %d MS share fingerprint %s — "
                               "pair explicitly: health.py <qp.md> <ms.md>"
                               % (len(qp_list), len(ms_list), "/".join(fp))),
                })
    return pairs, skipped


# ── analysis ──────────────────────────────────────────────────────────────────

def _paper_meta(draft):
    meta = draft.get("paper") or {}
    return {k: meta.get(k) for k in
            ("paperReference", "session", "logNumber", "publicationCode")}


def _check_question_mark_sums(qp_draft):
    findings = []
    for q in qp_draft.get("questions", []):
        number = q.get("number")
        parts = q.get("parts") or []
        known = [p["marks"] for p in parts if p.get("marks") is not None]
        printed = (qp_draft.get("questionTotals") or {}).get(str(number))
        if parts and len(known) == len(parts) and printed is not None:
            if sum(known) != printed:
                findings.append({"question": number, "partSum": sum(known),
                                 "printedTotal": printed, "status": FAIL})
        elif parts and len(known) != len(parts):
            findings.append({"question": number, "partsWithMarks": len(known),
                             "partsTotal": len(parts),
                             "printedTotal": printed, "status": REVIEW,
                             "note": "some part marks unknown"})
    status = FAIL if any(f["status"] == FAIL for f in findings) else (
        REVIEW if findings else OK)
    return {"status": status, "findings": findings}


def _check_qp_ms_totals(qp_draft, ms_draft):
    qp_t = {int(k): v for k, v in (qp_draft.get("questionTotals") or {}).items()}
    ms_t = {int(k): v for k, v in (ms_draft.get("questionTotals") or {}).items()}
    mismatches = [{"question": n, "qp": qp_t[n], "ms": ms_t[n]}
                  for n in sorted(set(qp_t) & set(ms_t)) if qp_t[n] != ms_t[n]]
    missing = sorted(set(qp_t).symmetric_difference(ms_t))
    status = FAIL if mismatches else (REVIEW if missing else OK)
    return {"status": status, "mismatches": mismatches, "missingOnOneSide": missing}


def _check_paper_mapping(qp_draft, ms_draft):
    qp_numbers = {q["number"] for q in qp_draft.get("questions", [])}
    ms_numbers = {e["number"] for e in ms_draft.get("entries", [])}
    unmatched_qp = sorted(qp_numbers - ms_numbers)
    unmatched_ms = sorted(ms_numbers - qp_numbers)
    status = OK if not (unmatched_qp or unmatched_ms) else REVIEW
    return {"status": status, "unmatchedQp": unmatched_qp, "unmatchedMs": unmatched_ms}


def _check_paper_total(qp_draft, ms_draft):
    qp_t = qp_draft.get("paperTotal")
    ms_t = ms_draft.get("paperTotal")
    question_sum = None
    totals = {int(k): v for k, v in (qp_draft.get("questionTotals") or {}).items()}
    if totals:
        question_sum = sum(totals.values())
    mismatches = []
    if qp_t is not None and ms_t is not None and qp_t != ms_t:
        mismatches.append({"qp": qp_t, "ms": ms_t})
    if qp_t is not None and question_sum is not None and qp_t != question_sum:
        mismatches.append({"qp": qp_t, "sumOfQuestionTotals": question_sum})
    status = (FAIL if mismatches else
              REVIEW if (qp_t is None or ms_t is None or question_sum is None) else OK)
    return {"status": status, "qp": qp_t, "ms": ms_t,
            "sumOfQuestionTotals": question_sum, "mismatches": mismatches}


def _collect_asset_refs(document):
    if not document:
        return []
    refs = []
    for el in document.get("figures", []) or []:
        refs.append({"url": el.get("text") or "", "name": el.get("source_name") or ""})
    for section in document.get("sections", []) or []:
        for el in section.get("figures", []) or []:
            refs.append({"url": el.get("text") or "", "name": el.get("source_name") or ""})
    return refs


def _check_assets(md_path: Path, qp_doc, ms_doc):
    md_dir = md_path.parent
    manifest_path = md_dir / "manifest.json"
    assets_dir = md_dir / "assets"
    manifest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": FAIL, "error": "manifest.json unreadable: " + str(exc),
                    "missing": [], "knownUnavailable": 0, "hasManifest": True}

    missing, unavailable = [], 0
    for doc in (qp_doc, ms_doc):
        for ref in _collect_asset_refs(doc):
            name = Path(ref["name"] or Path(ref["url"].split("?")[0]).name).name
            if not name:
                continue
            local = assets_dir / name
            if local.exists():
                continue
            if manifest is not None:
                listed = _manifest_lists(manifest, name)
                if listed:
                    missing.append({"asset": name, "why": "listed in manifest.json but absent on disk"})
                    continue
            if SIGNED_URL_HOST.match(ref["url"]):
                unavailable += 1  # audited-corpus state: signed URL, no local copy
            else:
                unavailable += 1
    status = FAIL if missing else (REVIEW if unavailable else OK)
    out = {"status": status, "missing": missing, "knownUnavailable": unavailable,
           "hasManifest": manifest is not None, "hasAssetsDir": assets_dir.is_dir()}
    if manifest is None:
        out["note"] = ("no manifest.json — md↔asset map unverified "
                       "(gap #9 tooling exists: tools/ocr_batch)")
    return out


def _manifest_lists(manifest, name):
    if isinstance(manifest, dict):
        for key in ("assets", "documents", "files"):
            block = manifest.get(key)
            if isinstance(block, dict) and any(name in str(k) for k in block):
                return True
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, dict) and any(
                            name in str(v) for v in item.values() if isinstance(v, str)):
                        return True
                    if isinstance(item, str) and name in item:
                        return True
        blob = json.dumps(manifest)
        return name in blob
    return False


def analyze_pair(qp_path: Path, ms_path: Path):
    qp_bytes = qp_path.read_bytes()
    ms_bytes = ms_path.read_bytes()
    qp_doc = GlmOcrMarkdownParser().parse(qp_bytes, qp_path.name)
    ms_doc = GlmOcrMarkdownParser().parse(ms_bytes, ms_path.name)
    qp_draft = GlmOcrQuestionExtractor().extract(qp_doc)
    ms_draft = GlmOcrMarkSchemeExtractor().extract(ms_doc)

    checks = {
        "questionMarkSums": _check_question_mark_sums(qp_draft),
        "qpMsTotals": _check_qp_ms_totals(qp_draft, ms_draft),
        "paperMapping": _check_paper_mapping(qp_draft, ms_draft),
        "paperTotal": _check_paper_total(qp_draft, ms_draft),
        "assets": _check_assets(qp_path, qp_doc, ms_doc),
    }
    pair_status = FAIL if any(c["status"] == FAIL for c in checks.values()) else (
        REVIEW if any(c["status"] == REVIEW for c in checks.values()) else OK)
    return {
        "qp": str(qp_path),
        "ms": str(ms_path),
        "paper": _paper_meta(qp_draft),
        "identity": {
            "qpDocumentId": qp_doc.get("documentId"),
            "msDocumentId": ms_doc.get("documentId"),
        },
        "counts": {
            "questions": len(qp_draft.get("questions", [])),
            "msEntries": len(ms_draft.get("entries", [])),
        },
        "checks": checks,
        "status": pair_status,
        "warnings": {"qp": qp_draft.get("warnings", []),
                     "ms": ms_draft.get("warnings", [])},
    }


# ── output ────────────────────────────────────────────────────────────────────

def _print_summary(report):
    for skipped in report.get("skipped", []):
        print("[SKIPPED] %s — %s" % (skipped["file"], skipped["reason"]))
    for pair in report["pairs"]:
        print("[%s] %s" % (pair["status"].upper(), pair["qp"]))
        print("      ms: %s  (%s questions, %s ms entries)"
              % (pair["ms"], pair["counts"]["questions"], pair["counts"]["msEntries"]))
        for name, check in pair["checks"].items():
            if check["status"] != OK:
                print("      %-18s %s" % (name + ":", check["status"].upper()))
                for key in ("findings", "mismatches", "missing", "unmatchedQp",
                            "unmatchedMs", "missingOnOneSide"):
                    if check.get(key):
                        print("        %s: %s" % (key, json.dumps(check[key], sort_keys=True)))
                if check.get("note"):
                    print("        note: %s" % check["note"])
    summary = report["summary"]
    print("pairs: %d  pass: %d  review: %d  fail: %d"
          % (summary["pairs"], summary["pass"], summary["review"], summary["fail"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="health.py",
        description="Zero-network health gate for GLM-OCR QP/MS markdown pairs.")
    ap.add_argument("inputs", nargs="*",
                    help="QP.md MS.md pair, or a directory to auto-pair with --dir")
    ap.add_argument("--dir", dest="dir", metavar="TREE",
                    help="directory tree to scan for QP/MS pairs")
    ap.add_argument("-o", "--out", metavar="FILE", help="write the JSON report here")
    ap.add_argument("--json", action="store_true", help="print the JSON report to stdout")
    ap.add_argument("--fail-on-review", action="store_true",
                    help="exit 1 when any pair has REVIEW findings")
    args = ap.parse_args(argv)

    root = Path(args.dir or ".")
    explicit = args.inputs
    if explicit:
        if len(explicit) != 2:
            ap.error("explicit mode needs exactly two files: QP.md MS.md")
        pairs = [(Path(explicit[0]), Path(explicit[1]))]
        skipped = []
    elif args.dir:
        pairs, skipped = find_pairs(root)
    else:
        ap.error("give a QP/MS pair or --dir TREE")

    report = {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "pairs": [],
        "skipped": skipped,
        "summary": {"pairs": 0, "pass": 0, "review": 0, "fail": 0},
    }
    for qp_path, ms_path in pairs:
        try:
            report["pairs"].append(analyze_pair(qp_path, ms_path))
        except (OSError, ValueError, KeyError) as exc:
            report["pairs"].append({
                "qp": str(qp_path), "ms": str(ms_path), "status": FAIL,
                "error": "unreadable or malformed: " + str(exc),
            })
    for pair in report["pairs"]:
        report["summary"]["pairs"] += 1
        report["summary"][pair["status"]] += 1

    failed = report["summary"]["fail"] > 0 or (
        args.fail_on_review and report["summary"]["review"] > 0)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_summary(report)
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
