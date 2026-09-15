"""Per-sitting atomizer: QP.md + MS.md -> one self-contained paper.json (OCR-Q4).

Consumes the reference extractors as a read-only consumer and assembles the
atomic Question/QuestionPart units the product modules need (Target Test,
Test Builder, Smart Mark): every part carries its **inherited stem context**
(question stem + parent-part lead-in) so it renders self-contained, plus its
matched mark-scheme entry (answer text, mark points, guidance) when one exists.

Design honesty (Master Spec §7 / reconciliation D4-D6):

- everything exported is a **draft**: ``reviewRequired: true`` and the
  extractors' confidence values are passed through, never inflated;
- extraction output is **verbatim** — no text is rewritten, normalized or
  repaired; ``renderedPrompt`` is a concatenation of verbatim slices only;
- QP/MS pairing is explicit: parts without a mark-scheme entry are exported
  with ``markScheme: null`` plus an ``atomizeWarnings`` line, and MS entries
  with no QP counterpart are listed under ``unmatched.msEntries`` — gaps are
  reported, never silently merged or dropped;
- the output is deterministic (sorted keys, stable ordering): identical
  inputs produce byte-identical JSON, so the artifact is diff-able and
  committable.

Label domains: QP draft part labels are ``a``, ``a-i`` (dash-separated,
extractor convention); MS entry labels are printed forms like ``1(a)(i)`` /
``3(b)`` / ``*14``. ``_ms_suffix`` normalizes both sides.

Additive tooling (polyglot policy ADR-011): no canonical-contract change, no
conformance impact on the doc/qp/ms stages. The Java mirror of this export
shape exists since 2026-09-15: com.syllabai.parser.structure.dto.GlmOcrPaperExport
+ GlmOcrPaperAtomizer + GlmOcrAtomizeDump, and cross-language equality of the
export is enforced by the `atomize` stage of tools/glmocr/conformance.py
(same semantic diff as the doc/qp/ms stages).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct execution: python3 tools/glmocr/atomize.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.glmocr"

from . import ENGINE_NAME, ENGINE_VERSION
from .canonical import GlmOcrMarkdownParser
from .markscheme_extractor import GlmOcrMarkSchemeExtractor
from .question_extractor import GlmOcrQuestionExtractor

TOOL_NAME = "glmocr-atomize"
EXPORT_SCHEMA_VERSION = "1.0"


def ms_suffix(entry_label: str, number) -> str:
    """"(a)(i)" for label "1(a)(i)"; "" for label "1" or "*14"."""
    label = (entry_label or "").lstrip("*").strip()
    if number is None:
        return ""
    prefix = str(number)
    if not label.startswith(prefix):
        return ""
    return label[len(prefix):].strip()


def qp_suffix(part_label: str) -> str:
    """QP draft label "a-i" -> "(a)(i)"; "a" -> "(a)"."""
    tokens = [t for t in (part_label or "").split("-") if t]
    return "".join("(" + t + ")" for t in tokens)


def stem_chain(part_label: str):
    """["a", "i"] for "a-i"; ["a"] for "a"."""
    return [t for t in (part_label or "").split("-") if t]


def _group_entries_by_number(ms_draft):
    grouped = {}
    for entry in ms_draft.get("entries", []):
        grouped.setdefault(entry["number"], []).append(entry)
    return grouped


def _index_entries_by_suffix(entries):
    return {ms_suffix(e.get("label"), e.get("number")): e for e in entries}


def _assemble_prompt(stem: str, parent_text: str, own_text: str) -> str:
    pieces = [stem.strip(), parent_text.strip(), own_text.strip()]
    return "\n\n".join(p for p in pieces if p)


def _ms_view(entry):
    if entry is None:
        return None
    return {
        "label": entry.get("label"),
        "answerText": entry.get("answerText"),
        "markPoints": entry.get("markPoints") or [],
        "guidance": entry.get("guidance") or [],
        "marks": entry.get("marks"),
        "confidence": entry.get("confidence"),
    }


def _export_question(q, entries_for_number, warnings):
    parts = q.get("parts") or []
    by_suffix = _index_entries_by_suffix(entries_for_number)
    text_of = {p["label"]: p["text"] for p in parts}

    consumed, exported_parts = set(), []
    for part in parts:
        chain = stem_chain(part["label"])
        parent_label = "-".join(chain[:-1])
        parent_text = text_of.get(parent_label, "") if parent_label else ""
        suffix = qp_suffix(part["label"])
        entry = by_suffix.get(suffix)
        if entry is not None:
            consumed.add(entry["entryId"])
        else:
            warnings.append("Q%s part %s: no mark-scheme entry for suffix %r"
                            % (q.get("number"), part["label"], suffix))
        exported_parts.append({
            "partId": part.get("partId"),
            "label": part.get("label"),
            "msLabel": suffix,
            "text": part.get("text"),
            "renderedPrompt": _assemble_prompt(q.get("stem") or "",
                                               parent_text, part.get("text") or ""),
            "marks": part.get("marks"),
            "qwc": part.get("qwc"),
            "figures": part.get("figures") or [],
            "answerPrompts": part.get("answerPrompts") or [],
            "confidence": part.get("confidence"),
            "markScheme": _ms_view(entry),
        })

    question_level = None
    if not parts:
        entry = by_suffix.get("")
        if entry is not None:
            consumed.add(entry["entryId"])
            question_level = _ms_view(entry)

    return {
        "questionId": q.get("questionId"),
        "number": q.get("number"),
        "numberingStyle": q.get("numberingStyle"),
        "section": q.get("section"),
        "stem": q.get("stem"),
        "mcq": q.get("mcq"),
        "options": q.get("options") or [],
        "qwc": q.get("qwc"),
        "figures": q.get("figures") or [],
        "tableElementIds": q.get("tableElementIds") or [],
        "marks": q.get("marks"),
        "marksKnown": q.get("marksKnown"),
        "confidence": q.get("confidence"),
        "markScheme": question_level,
        "parts": exported_parts,
    }, consumed


def atomize(qp_bytes: bytes, ms_bytes: bytes, qp_uri: str, ms_uri: str) -> dict:
    qp_doc = GlmOcrMarkdownParser().parse(qp_bytes, qp_uri)
    ms_doc = GlmOcrMarkdownParser().parse(ms_bytes, ms_uri)
    return atomize_parsed(qp_doc, ms_doc, qp_uri, ms_uri)


def atomize_parsed(qp_doc: dict, ms_doc: dict, qp_uri: str, ms_uri: str) -> dict:
    """Atomize pre-parsed canonical documents (conformance path: fixed identity)."""
    qp_draft = GlmOcrQuestionExtractor().extract(qp_doc)
    ms_draft = GlmOcrMarkSchemeExtractor().extract(ms_doc)

    warnings = []
    grouped = _group_entries_by_number(ms_draft)
    consumed_ids, questions = set(), []
    for q in qp_draft.get("questions", []):
        entries = grouped.get(q["number"], [])
        exported, consumed = _export_question(q, entries, warnings)
        consumed_ids |= consumed
        questions.append(exported)

    unmatched = [e.get("label") for e in ms_draft.get("entries", [])
                 if e.get("entryId") not in consumed_ids]
    for label in unmatched:
        warnings.append("mark-scheme entry %s has no question-paper counterpart" % label)

    totals = {int(k): v for k, v in (qp_draft.get("questionTotals") or {}).items()}
    paper_total = qp_draft.get("paperTotal")
    if paper_total is not None and totals and sum(totals.values()) != paper_total:
        warnings.append(
            "sum of question totals (%d) conflicts with paper total (%s)"
            % (sum(totals.values()), paper_total))

    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "reviewRequired": True,
        "engine": {"name": ENGINE_NAME, "version": ENGINE_VERSION},
        "source": {
            "qp": {"uri": qp_uri, "documentId": qp_doc.get("documentId"),
                   "checksum": (qp_doc.get("source") or {}).get("checksum")},
            "ms": {"uri": ms_uri, "documentId": ms_doc.get("documentId"),
                   "checksum": (ms_doc.get("source") or {}).get("checksum")},
        },
        "paper": qp_draft.get("paper") or {},
        "questions": questions,
        "totals": {
            "questionTotals": {str(k): totals[k] for k in sorted(totals)},
            "paperTotal": paper_total,
            "sumOfQuestionTotals": sum(totals.values()) if totals else None,
        },
        "unmatched": {"msEntries": unmatched},
        "warnings": {
            "qp": qp_draft.get("warnings", []),
            "ms": ms_draft.get("warnings", []),
            "atomize": warnings,
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="atomize.py",
        description="Atomize a GLM-OCR QP/MS markdown pair into per-sitting paper.json.")
    ap.add_argument("qp", metavar="QP.md")
    ap.add_argument("ms", metavar="MS.md")
    ap.add_argument("-o", "--out", metavar="FILE", help="write JSON here (default: stdout)")
    ap.add_argument("--compact", action="store_true", help="single-line JSON output")
    args = ap.parse_args(argv)

    qp_path, ms_path = Path(args.qp), Path(args.ms)
    export = atomize(qp_path.read_bytes(), ms_path.read_bytes(),
                     qp_path.name, ms_path.name)
    text = json.dumps(export, sort_keys=True,
                      indent=None if args.compact else 2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
