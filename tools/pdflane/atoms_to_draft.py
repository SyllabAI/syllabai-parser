"""atoms/1.1 -> past-paper-draft.json/1.0 converter (G8 bank backfill, A1).

Bridges pdflane atom products (tools/pdflane/schema/ATOMS_SCHEMA.md) into the
core bank ingestion contract (syllabai-core PastPaperDraftDto, schema 1.0) so
the bank can be superseded per-paper from the deterministic engine WITHOUT any
core change (A1 decision, scope Task 37/38).

Fidelity rules (recorded, no silent loss):

- blocks -> markdown text: para/table verbatim, image as ![alt](src),
  choices as "L. text" lines, answer_lines dropped (rendering furniture,
  not content).
- parts: label = "<letter>" or "<letter>-<sub>" (sub-numbered leaves), so
  mark-point refs "N-<label>" resolve through core's resolvePart exactly.
- mark points: questionRef = "<q>" or "<q>-<label>"; per-question order is
  the printed order within the atom.
- marks=0 points are ALTERNATIVE answers (atoms §6: never scored twice).
  Core clamps point marks with Math.max(marks, 1), so emitting them as
  separate rows would INFLATE the awardable sum. They are merged into the
  first primary point of the same (part, sub) group as acceptance entries
  ("Alternative: ..."). If the group has no primary, the first alternative
  is promoted (marks=1) and the rest merge into it.
- pools: member points keep their printed marks (1 each); the FIRST member
  of each pool carries a text prefix "[any <cap> for 1 each] " so the cap is
  teacher-visible. Known limitation: the flat draft-1.0 cannot express the
  cap structurally — a naive sum over pool members overcounts; the
  authoritative awardable totals remain the QP-side question/part marks.
- levels-based marking: one synthetic point per atom, marks = maxMarks, text
  = rendered band table, indicative content as acceptance entries (keeps the
  naive sum equal to the printed total).
- allow/reject/ignore/notes -> acceptance list ("Reject: ...", "Ignore: ...",
  "Note: ..."); atom guidance rows merge into the question's first point
  acceptance ("Guidance: ..."); mcq correct labels become
  "Correct answer: X".
- confidence: 1.0 for every row — the deterministic engine carries no
  per-row confidence estimate; honesty is carried by reviewRequired=true
  (everything lands SUGGESTED, nothing serves without teacher validation)
  and by marksVerified gating at the drive level, not by a made-up number.
- extractionMethod: "pdflane-atoms-draft-v1" (<=120 chars, stored verbatim
  in the bank for provenance queries).

Determinism: pure function of (envelope, identity); no clocks, no randomness.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"
EXTRACTION_METHOD = "pdflane-atoms-draft-v1"


def render_blocks(blocks: Optional[List[Dict[str, Any]]]) -> str:
    """Render an atoms block list to the draft's plain markdown prompt text."""
    if not blocks:
        return ""
    out: List[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "para":
            out.append(b.get("md", ""))
        elif t == "table":
            out.append(b.get("md", ""))
        elif t == "image":
            alt = b.get("alt") or "figure"
            out.append(f"![{alt}]({b.get('src', '')})")
        elif t == "choices":
            for item in b.get("items", []):
                out.append(f"{item.get('label', '')}. {item.get('md', '')}")
        elif t == "answer_lines":
            continue  # rendering furniture — never content
        else:  # unknown future block type: keep its md/text if any (no silent loss)
            out.append(b.get("md") or b.get("text") or "")
    return "\n".join(x for x in out if x)


def _part_label(part: Dict[str, Any]) -> str:
    label = part.get("label") or ""
    sub = part.get("sub")
    return f"{label}-{sub}" if sub else label


def _prefixed(entries: List[str], prefix: str) -> List[str]:
    return [f"{prefix}: {e}" for e in entries if e]


def _point_text(point: Dict[str, Any]) -> str:
    md = (point.get("md") or "").strip()
    notes = [n for n in point.get("notes", []) if n]
    if md:
        return md
    if notes:
        return "; ".join(notes)
    return ""


def _pool_scopes(ms: Dict[str, Any]) -> Dict[tuple, Dict[str, Any]]:
    """Map (part_letter, sub, point_id) -> pool, honouring the pool's letter/sub
    scope (atoms §6: pool labels are scoped — point IDs repeat across parts)."""
    scopes: Dict[tuple, Dict[str, Any]] = {}
    for pool in ms.get("pools", []) or []:
        raw = pool.get("part") or ""
        bits = raw.split("-")
        letter = bits[0] if bits else None
        sub = bits[1] if len(bits) > 1 else None
        for lbl in pool.get("labels", []):
            scopes[(letter, sub, lbl)] = pool
    return scopes


def _convert_atom_points(atom: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten one atom's mark scheme into draft points (questionRef relative)."""
    ms = atom["markScheme"]
    qn = str(atom["number"])
    if ms.get("style") == "levels" and ms.get("levels"):
        return [_levels_point(qn, ms["levels"])]
    points = ms.get("points", [])
    scopes = _pool_scopes(ms)

    # first primary (marks>0) per (part, sub) group; groups where an alternative
    # has been promoted count as primary-having for merging later alternatives
    primary_seen: Dict[tuple, bool] = {}
    for p in points:
        key = (p.get("part"), p.get("sub"))
        if p.get("marks", 0) > 0 and key not in primary_seen:
            primary_seen[key] = True

    out: List[Dict[str, Any]] = []
    carried_alt: Dict[tuple, List[str]] = {}
    for p in points:
        key = (p.get("part"), p.get("sub"))
        marks = p.get("marks", 0)
        text = _point_text(p)
        pool = scopes.get((p.get("part"), p.get("sub"), p.get("id")))
        if pool is not None and pool.get("labels", [None])[0] == p.get("id"):
            text = f"[any {pool.get('cap')} for 1 each] {text}".strip()
        acceptance: List[str] = []
        acceptance += _prefixed(p.get("allow", []), "Allow")
        acceptance += _prefixed(p.get("reject", []), "Reject")
        acceptance += _prefixed(p.get("ignore", []), "Ignore")
        # pool candidates living in notes when md is empty
        if pool is not None and not (p.get("md") or "").strip():
            acceptance += [f"Note: {n}" for n in p.get("notes", []) if n]
        correct = _mcq_correct(atom, p)
        if correct:
            acceptance.append(f"Correct answer: {correct}")
        if marks == 0:
            # alternative answer (atoms §6: recorded, never scored twice). Core
            # clamps point marks to >=1, so a separate row would inflate the sum.
            text = f"[alternative answer] {text}".strip() if text else "[alternative answer]"
            if key in primary_seen:
                carried_alt.setdefault(key, []).append(f"Alternative: {text}")
                continue
            # no primary in this group: promote the FIRST alternative, merge the rest
            primary_seen[key] = True
            out.append({
                "questionRef": _question_ref(qn, p),
                "order": len(out) + 1,
                "text": text,
                "marks": 1,
                "acceptance": acceptance,
                "confidence": 1.0,
                "_key": key,
            })
            continue
        out.append({
            "questionRef": _question_ref(qn, p),
            "order": len(out) + 1,
            "text": text,
            "marks": max(marks, 1),
            "acceptance": acceptance,
            "confidence": 1.0,
            "_key": key,
        })
    # attach carried alternatives to the FIRST emitted row of their group
    for row in out:
        alts = carried_alt.pop(row["_key"], None)
        if alts:
            row["acceptance"] = row["acceptance"] + alts
    for row in out:
        row.pop("_key", None)
    # atom-level guidance -> first point's acceptance (draft-1.0 has no guidance slot)
    guidance = ms.get("guidance", []) or []
    if guidance and out:
        out[0]["acceptance"] = _prefixed([_g(g) for g in guidance], "Guidance") + out[0]["acceptance"]
    return out


def _question_ref(qn: str, point: Dict[str, Any]) -> str:
    part = point.get("part")
    if part is None:
        return qn
    label = part if not point.get("sub") else f"{part}-{point.get('sub')}"
    return f"{qn}-{label}"


def _g(g: Any) -> str:
    return g if isinstance(g, str) else json.dumps(g, ensure_ascii=False)


def _mcq_correct(atom: Dict[str, Any], point: Dict[str, Any]) -> Optional[str]:
    """Correct choice labels from mcq parts, matched by part/sub of the point."""
    for part in atom.get("parts", []):
        if part.get("type") == "mcq" and part.get("correct"):
            if part.get("label") == point.get("part") and part.get("sub") == point.get("sub"):
                return ", ".join(part["correct"])
    return None


def _levels_point(qn: str, levels: Dict[str, Any]) -> Dict[str, Any]:
    bands = levels.get("bands", [])
    text = "Levels-based marking: " + " | ".join(
        f"Level {b.get('level')} ({b.get('markRange', {}).get('min')}-{b.get('markRange', {}).get('max')}): "
        f"{b.get('descriptor', '')}" for b in bands)
    acceptance = [f"Indicative content: {c}" for c in levels.get("indicativeContent", []) if c]
    acceptance += [f"Note: {n}" for n in levels.get("notes", []) if n]
    return {"questionRef": qn, "order": 1, "text": text,
            "marks": levels.get("maxMarks", 0), "acceptance": acceptance,
            "confidence": 1.0}


def convert(envelope: Dict[str, Any], paper_dir: str, identity: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an atoms envelope into a past-paper-draft.json/1.0 dict.

    paper_dir: repo-relative paper directory (identity carrier, atoms §2) —
        used verbatim in question externalRefs.
    identity: {board, qualification, subject, unit, sessionLabel, paperCode,
        questionPaperDocumentId, markSchemeDocumentId}.
    """
    questions_out: List[Dict[str, Any]] = []
    ms_points: List[Dict[str, Any]] = []
    for atom in envelope.get("questions", []):
        qn = str(atom["number"])
        pages = _atom_pages(atom)
        parts_out = []
        for p in atom.get("parts", []):
            parts_out.append({
                "label": _part_label(p),
                "prompt": render_blocks(p.get("prompt")),
                "commandWord": p.get("commandWord"),
                "marks": p.get("marks", 0),
                "confidence": 1.0,
            })
        questions_out.append({
            "externalRef": f"{paper_dir}#q{atom['number']}",
            "questionNumber": qn,
            "prompt": render_blocks(atom.get("stem")),
            "commandWord": atom.get("commandWord"),
            "marks": atom.get("marks", 0),
            "questionType": str(atom.get("type", "structured")).upper(),
            "pageNumber": pages,
            "confidence": 1.0,
            "parts": parts_out,
        })
        ms_points.extend(_convert_atom_points(atom))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "paper": {
            "board": identity.get("board"),
            "qualification": identity.get("qualification"),
            "subject": identity.get("subject"),
            "unit": identity.get("unit"),
            "sessionLabel": identity.get("sessionLabel"),
            "paperCode": identity.get("paperCode"),
            "questionPaperDocumentId": identity.get("questionPaperDocumentId"),
            "markSchemeDocumentId": identity.get("markSchemeDocumentId"),
        },
        "questions": questions_out,
        "markScheme": {
            "version": "1",
            "sourceDocumentId": identity.get("markSchemeDocumentId"),
            "points": ms_points,
        },
        "extractionMethod": EXTRACTION_METHOD,
        "reviewRequired": True,
    }


def _atom_pages(atom: Dict[str, Any]) -> int:
    pages: List[int] = []
    for p in atom.get("parts", []):
        pages.extend(p.get("pages", []) or [])
    for b in atom.get("stem", []) or []:
        if isinstance(b, dict) and b.get("pages"):
            pages.extend(b["pages"])
    return min(pages) if pages else 1
