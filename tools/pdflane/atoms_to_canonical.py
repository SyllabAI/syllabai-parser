"""atoms/1.1 → canonical document bridge (retrieval-index adaptation, T-C06 pattern).

Converts one paper's parsed/ product (questions.json per syllabai.pastpaper.atoms/1.1)
into TWO canonical schema-1.0 documents that syllabai-core ingests UNCHANGED through
POST /api/v1/teacher/content/documents (ContentDocumentController → ContentIngestionService
→ deterministic ChunkingService → document_chunks):

  QUESTION_PAPER (qp.canonical.json) — stem + part prompts: text blocks, tables,
      figures, choice lists; sections = one per question. Never carries answers.
  MARK_SCHEME (ms.canonical.json) — the CONNECTED mark scheme: per-point elements
      with marks + allow/reject/ignore/notes, per-question guidance and levels
      bands, MS figure answers; real per-point pages from the atoms product.

Identity & dedup semantics (Master Spec §8/§19):
  source = the ORIGINAL PDFs (qp.pdf / ms.pdf, application/pdf, sha256 recomputed
  here and cross-checked against manifest.yaml). The legacy OCR lane ingested
  markdown sources (text/markdown, checksum of the .md) — a different checksum
  space — so atoms-derived documents never dedup-collide with legacy documents
  for the same paper; both can coexist until the operator curates the index.

documentId mirrors Java CanonicalIdentity byte-exactly by REUSING the audited
glmocr port (glmocr.canonical.content_document_id) — one Python derivation
implementation, zero drift risk.

Leakage policy (hard rule, tested):
  The QUESTION_PAPER document never contains `correct` labels, mark-scheme
  points, or any answer content. Answers live only in the MARK_SCHEME document
  (kind-scoped retrieval: kind MARK_SCHEME is gated away from learner surfaces
  by core's deterministic answer-leakage policy).

Page provenance:
  QP — image blocks carry exact pages (bbox.page / pages); every other block is
  aligned to qp.md `<!-- PAGE N -->` markers by sequential bidirectional
  containment search with a forward cursor, falling back to the owning
  question's opener page (counted honestly in extractionParams).
  MS — per-point `pages` from the atoms product (real).

Chunk preview:
  simulate_chunks() is a faithful port of core ChunkingService (target 300 /
  max 800 tokens, ceil(chars/4) estimate, whole-block packing, oversized block
  = own chunk) so a dry run can prove chunk counts and page spans WITHOUT a
  Java runtime. Core's chunker remains the authority at ingest time.

Retrieval metadata (v1.2.0 — the corpus-v2 bridge release):
  v1.1.1 carried paper context as a text prefix on the first text-bearing
  element of each question ("[... | Question 7]"); workable, but text
  pollution, and it only covered chunks that start on that element. v1.2.0
  supersedes it with the plan §4.1.1 design, coordinated with the core lane
  (R2: ChunkHeaderBuilder + V33 metadata columns, live in production ingest
  since 47d56ad/81144e8):
    1. Doc-level `retrieval` block {subjectTitle, subjectCode, series, year,
       paperCode, label, unit, specCodes} derived deterministically from
       manifest.yaml. series is canonicalized to JAN/JUN/NOV ("Summer"→JUN);
       an unrecognized series stays null — a raw label as a filter is a lie
       waiting for a year-range query (plan §12 anti-pattern 7). subjectCode
       resolves into core's subjects table at ingest — a present-but-
       unresolvable code fails LOUD there, by design; the documented 4CH0→4CH1
       alias maps pre-2016 papers onto the pilot subject.
    2. Per-element `group_key` ("q1", "q2", ...) on every element of every
       question section — core treats a group-key change as a HARD chunk
       boundary (no chunk crosses an atom), stamps atom_number from it, and
       projects a per-chunk header ("4CH1/1C Paper 1C JUN 2024 Q3 pp.4-5";
       MS: "MS Q3") from the metadata columns onto EVERY chunk.
  The v1.1.1 text prefix is removed in the same release that adds the
  structured replacement — one release = one clean embed_rev=2 ingest of the
  11 bridge papers (no double-carrying of the same signal in chunk text).

Render-level furniture exclusion (G3, parser-lane analysis §4):
  Known Edexcel boilerplate ("DO NOT WRITE IN THIS AREA", "Answer ALL
  questions.", the cross-in-box instruction paragraphs, "Total for Question
  N = X marks" stem echoes) is classified deterministically at RENDER time
  and excluded from the canonical retrieval render, with per-doc counts in
  extractionParams. Parse-level products are NEVER touched — the atoms
  product stays complete, "Total for Question N" rows remain G1 marks-
  integrity witnesses, and classification stays conservative (whole-block
  matches only): column-bleed-glued fragments survive rather than risk
  eating real content. Losslessness lives in the product file; the canonical
  document is a retrieval render by definition (same policy as the QP leak
  guard).

Figure alt-text (G4, parser-lane analysis §4):
  A figure whose atoms alt is empty pulls a deterministic caption from the
  nearest same-question "Figure/Graph/Diagram N" text block when one exists;
  every figure WITH an alt emits an adjacent role="figure_alt" text block
  "[figure: <alt>]" so the chunker packs figure signal into embeddings
  (core's chunker packs text blocks, not figure elements). No caption and no
  alt ⇒ nothing fabricated — honest empty.

Determinism: no timestamps, no randomness, stable element ids — identical
inputs + code produce byte-identical canonical JSON (S0–S1 invariant).

Usage:
  python3 -m pdflane.atoms_to_canonical --paper-dir <paper-dir> --out <outdir>
  python3 -m pdflane.atoms_to_canonical --corpus <chemistry-root> --out <outdir>
"""
import argparse
import hashlib
import json
import os
import re
import sys

from glmocr.canonical import content_document_id

ENGINE_NAME = "pdflane-atoms"
# 1.2.0: the corpus-v2 bridge release (plan §4.1.1 / §6) — doc-level retrieval
# metadata + per-element group_key (hard atom boundaries, core-stamped per-chunk
# headers) replace the 1.1.1 text-prefix headers; render-level furniture
# exclusion (G3); figure alt-text with [figure: ...] inline render (G4).
# Engine version is part of the identity material, so documentIds re-derive
# (the new docs cannot collide with the 1.1.1 dry-run id space).
ENGINE_VERSION = "1.2.0"
SCHEMA_VERSION = "1.0"
APPLICATION = "syllabai-parser"
PDF_MIME = "application/pdf"

PAGE_MARK = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")

CHUNK_TARGET_TOKENS = 300
CHUNK_MAX_TOKENS = 800

# ── retrieval metadata (v1.2.0) ──────────────────────────────────────────────

# The pilot subject register carries ONE IGCSE Chemistry subject (code 4CH1,
# verified against production `subjects` at release time). Pre-2016 paper
# folders are 4CH0 (retired spec code); they map onto the same pilot subject
# so the subject branch of the serving scope can ever serve them. Documented,
# deterministic, tiny on purpose — anything else is emitted as-is and a
# present-but-unresolvable code fails LOUD at core ingestion (plan-fail-closed).
SUBJECT_CODE_ALIASES = {"4CH0": "4CH1"}

_MONTH_SERIES = {"1": "JAN", "01": "JAN", "6": "JUN", "06": "JUN",
                 "11": "NOV"}
_SERIES_WORDS = (("january", "JAN"), ("june", "JUN"), ("summer", "JUN"),
                 ("november", "NOV"))

# G3: whole-block furniture classification (render-level only — the atoms
# product is never rewritten). Exact list = the parser-lane analysis §4 G3
# findings on real product output (4ch1-1c-2024jun Q1 et al). Conservative by
# design: a block qualifies only when its WHOLE normalized text matches, so
# column-bleed-glued fragments survive rather than risk eating content.
_FURNITURE_EXACT = {
    "do not write in this area",
    "answer all questions.",
    "answer all questions",
    "turn over",
    "blank page",
    "pmt",
}
_FURNITURE_PREFIXES = (
    "do not write in this area",
    "some questions must be answered with a cross in a box",
    "if you change your mind, put a line through the box",
)
# "Total for Question N = X marks" echoes in stems: excluded from the RETRIEVAL
# render with their own counter, but never touched at parse level — the rows
# are G1 arithmetic witnesses in the atoms product.
_FURNITURE_TOTAL_ROW = re.compile(
    r"^total for question \d+\b.*\bmarks?\s*\.?$", re.IGNORECASE)

# G4: deterministic figure-caption shape (same-question nearest-block pull).
_FIGURE_CAPTION = re.compile(
    r"^(figure|fig\.?|graph|diagram|chart)\s*\d*\b", re.IGNORECASE)


def _resolve_figure_alt(figure_el, q_paras, order):
    """G4: fill an empty figure alt from the nearest same-question caption.

    q_paras = [(emission_order, normalized_text)] of the question's kept para
    blocks; order = the figure's own emission order. Returns the caption used
    ("" when none found — nothing fabricated). Mutates figure_el["alt"].
    """
    if figure_el.get("alt"):
        return figure_el["alt"]
    best, best_dist = None, None
    for o, cap in q_paras:
        if not _FIGURE_CAPTION.match(cap):
            continue
        d = abs(o - order)
        if best is None or d < best_dist:
            best, best_dist = cap, d
    if best:
        figure_el["alt"] = best
    return best or ""


def _norm(s):
    """Whitespace-collapsed comparison form for alignment search."""
    return re.sub(r"\s+", " ", s or "").strip()


def classify_furniture(text):
    """Render-level furniture classification for a candidate text block.

    Returns None (keep), "furniture" (boilerplate), or "total_row" (the
    "Total for Question N" witness echo). Whole-block conservative matching
    only; empty/whitespace text is never furniture.
    """
    if text is None:
        return None
    n = _norm(text).lower().rstrip(".")
    if not n:
        return None
    if n in _FURNITURE_EXACT or n.rstrip(".") in _FURNITURE_EXACT:
        return "furniture"
    for p in _FURNITURE_PREFIXES:
        if n.startswith(p):
            return "furniture"
    if _FURNITURE_TOTAL_ROW.match(n):
        return "total_row"
    return None


def canonical_series(printed, normalized):
    """(series, year) from manifest series fields — JAN/JUN/NOV or None.

    A raw label like "Summer 2019" as a filter is a lie waiting for a
    year-range query (plan §12 #7): unrecognized series stays None, year is
    still emitted when derivable. "Summer" canonicalizes to JUN.
    """
    series = None
    for cand in (printed or "", normalized or ""):
        low = cand.lower()
        for word, val in _SERIES_WORDS:
            if word in low:
                series = val
                break
        if series:
            break
        m = re.search(r"(^|-)(\d{4})-(\d{1,2})(-|$)", cand)
        if m and m.group(3) in _MONTH_SERIES:
            series = _MONTH_SERIES[m.group(3)]
            break
        m = re.search(r"(^|-)(\d{1,2})-(\d{4})(-|$)", cand)
        if m and m.group(2) in _MONTH_SERIES:
            series = _MONTH_SERIES[m.group(2)]
            break
    year = None
    for cand in (printed or "", normalized or ""):
        m = re.search(r"\b(19\d{2}|20\d{2})\b", cand)
        if m:
            year = int(m.group(1))
            break
        m = re.match(r"^(\d{4})-(\d{1,2})$", cand.strip())
        if m:
            year = int(m.group(1))
            break
    return series, year


def _parse_manifest(paper_dir):
    """Shared manifest.yaml scan → (vals dict) — identity + retrieval metadata."""
    path = os.path.join(paper_dir, "manifest.yaml")
    vals = {}
    top = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip(" "))
                stripped = line.strip()
                if indent == 0:
                    m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", stripped)
                    if not m:
                        top = None
                        continue
                    top, rest = m.group(1), m.group(2)
                    if rest:
                        vals[top] = rest  # top-level scalar (e.g. subject)
                    else:
                        vals[top] = {}
                elif indent == 2 and isinstance(vals.get(top), dict):
                    m = re.match(r"^([\w-]+):\s*(.*)$", stripped)
                    if m:
                        vals[top][m.group(1)] = m.group(2)
    except OSError:
        pass
    return vals


def load_retrieval_meta(paper_dir):
    """Doc-level retrieval identity from manifest.yaml (v1.2.0 contract).

    Mirrors core CanonicalDocumentDto.RetrievalMeta exactly: subjectTitle,
    subjectCode (alias-normalized), series (JAN/JUN/NOV or None), year,
    paperCode, label, unit, specCodes. Returns None when the manifest carries
    no identity at all — core treats a missing retrieval block as legacy-
    tolerant, so absence stays honest (never fabricated).
    """
    vals = _parse_manifest(paper_dir)
    if not vals:
        return None
    qual = vals.get("qualification") or {}
    series = vals.get("series") or {}
    paper = vals.get("paper") or {}
    subject = vals.get("subject") or ""

    printed = (series.get("printed") or series.get("normalized") or "")
    printed = printed.split(";")[0].strip()
    norm_series, year = canonical_series(printed, series.get("normalized") or "")

    # subjectCode: spec/unit code, alias-normalized (4CH0→4CH1 pilot mapping).
    code = None
    pid_parts = (vals.get("paper_id") or "").split(":")
    if paper.get("unit_code"):
        code = str(paper["unit_code"]).split("/")[0].strip()
    elif len(pid_parts) >= 4:
        code = pid_parts[3].strip()
    if code:
        code = SUBJECT_CODE_ALIASES.get(code.upper(), code.upper())

    # paperCode: full unit reference in the production exam_papers format
    # ("4CH1/1C"); label: "Paper 1C".
    paper_code = paper.get("official_reference") or None
    variant = paper.get("paper_number_variant") or None
    if not paper_code and code and variant:
        paper_code = f"{code}/{variant}"
    label = f"Paper {variant}" if variant else None

    subject_title = " ".join(x for x in
                             (qual.get("name"), subject.title() if subject else None)
                             if x) or None

    if not any((subject_title, code, norm_series, year, paper_code, label)):
        return None
    return {
        "subjectTitle": subject_title,
        "subjectCode": code,
        "series": norm_series,
        "year": year,
        "paperCode": paper_code,
        "label": label,
        "unit": None,      # papers span the whole spec — no unit split (honest null)
        "specCodes": None,  # spec tagging is the taxonomy lane's join on paperDir#qN — never baked into docs
    }


# ── helpers ───────────────────────────────────────────────────────────────────


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_atoms(paper_dir):
    path = os.path.join(paper_dir, "parsed", "questions.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_manifest_checksums(paper_dir):
    """material path → sha256 from manifest.yaml (best effort, None when absent)."""
    path = os.path.join(paper_dir, "manifest.yaml")
    out = {}
    if not os.path.exists(path):
        return out
    current = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*-\s*type:\s*(\S+)", line)
            if m:
                current = m.group(1)
                continue
            m = re.match(r"^\s*path:\s*(\S+)", line)
            if m and current:
                out["_path:" + current] = m.group(1)
                continue
            m = re.match(r"^\s*sha256:\s*([0-9a-f]{64})", line)
            if m and current:
                out[current] = m.group(1)
                current = None
    return out


def load_manifest_identity(paper_dir):
    """Paper identity for retrieval headers from manifest.yaml.

    Returns e.g. 'International GCSE Chemistry 4CH1 | June 2024 | Paper 1C'
    (deterministic; falls back to paper_id fragments when fields are absent;
    the doubled 'June 2011; June 2011' printed values in older manifests
    normalize to the first part).
    """
    vals = _parse_manifest(paper_dir)

    qual = vals.get("qualification") or {}
    series = vals.get("series") or {}
    paper = vals.get("paper") or {}
    subject = vals.get("subject") or ""
    unit = paper.get("unit_code")
    paper_ref = paper.get("paper_number_variant")
    if not paper_ref and paper.get("official_reference"):
        paper_ref = paper["official_reference"].split("/")[-1]
    printed = (series.get("printed") or series.get("normalized") or "")
    printed = printed.split(";")[0].strip()

    if not (qual.get("name") and subject):
        # deterministic fallback: parse paper_id fragments
        # paper_id = board : qualification-family : subject : spec-folder :
        #            series : paper-reference
        pid = vals.get("paper_id") or ""
        parts = pid.split(":")
        if len(parts) >= 6:
            qual["name"] = qual.get("name") or parts[1].replace("-", " ").title()
            subject = subject or parts[2]
            printed = printed or parts[4]
            unit = unit or parts[5].split("/")[0]
            paper_ref = paper_ref or parts[5].split("/")[-1]

    bits = []
    head = " ".join(x for x in (qual.get("name"),
                                subject.title() if subject else None) if x)
    if unit:
        head = (head + " " + unit).strip()
    if head:
        bits.append(head)
    if printed:
        bits.append(printed)
    if paper_ref:
        bits.append(f"Paper {paper_ref}")
    return " | ".join(bits)


def qp_md_pages(paper_dir):
    """qp.md → (page_count, [(line_index, page)]) — page per line via markers."""
    path = os.path.join(paper_dir, "parsed", "qp.md")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    per_line = []
    page = 1
    for line in lines:
        m = PAGE_MARK.match(line.strip())
        if m:
            page = int(m.group(1))
        per_line.append(page)
    return max(per_line) if per_line else 1, lines, per_line


# ── element factories (exact CanonicalDocumentDto field sets, snake_case) ────


def _engine_fields():
    return {"source_engine": ENGINE_NAME, "source_engine_version": ENGINE_VERSION}


class _Elements:
    """Ordered element accumulator with the shared e{idx:06d} id space."""

    def __init__(self):
        self.text_blocks = []
        self.tables = []
        self.figures = []
        self.equations = []
        self._n = 0

    def _next_id(self):
        idx = self._n
        self._n += 1
        return idx

    def add_text(self, text, page, role="paragraph", heading_level=None, bbox=None,
                 group_key=None):
        idx = self._next_id()
        self.text_blocks.append({
            "element_id": f"e{idx:06d}", "element_type": "text_block",
            "page_number": page, "bounding_box": bbox, "text": text,
            "reading_order": idx, "confidence": 1.0, "role": role,
            "heading_level": heading_level, **_engine_fields(),
            "group_key": group_key,
        })
        return self.text_blocks[-1]

    def add_table(self, md, page, bbox=None, group_key=None):
        idx = self._next_id()
        rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
                for ln in md.split("\n")
                if ln.strip().startswith("|") and not re.match(r"^\|[\s:|-]+\|$", ln.strip())]
        self.tables.append({
            "element_id": f"e{idx:06d}", "element_type": "table",
            "page_number": page, "bounding_box": bbox, "text": md,
            "reading_order": idx, "confidence": 1.0, "rows": rows,
            "row_count": len(rows),
            "column_count": len(rows[0]) if rows else 0, **_engine_fields(),
            "group_key": group_key,
        })
        return self.tables[-1]

    def add_figure(self, src, page, alt="", bbox=None, group_key=None):
        idx = self._next_id()
        fmt = src[src.rfind(".") + 1:] if "." in src else None
        self.figures.append({
            "element_id": f"e{idx:06d}", "element_type": "figure",
            "page_number": page, "bounding_box": bbox, "text": src,
            "reading_order": idx, "confidence": 1.0, "format": fmt,
            "source_name": src, "alt": alt or "", **_engine_fields(),
            "group_key": group_key,
        })
        return self.figures[-1]

    def all(self):
        return self.text_blocks + self.tables + self.figures + self.equations


def _bbox_from_atoms(block):
    bbox = block.get("bbox")
    if not bbox:
        return None
    return {
        "x": bbox.get("x0"), "y": bbox.get("y0"),
        "width": (bbox["x1"] - bbox["x0"]) if bbox.get("x1") is not None
                 and bbox.get("x0") is not None else None,
        "height": (bbox["y1"] - bbox["y0"]) if bbox.get("y1") is not None
                  and bbox.get("y0") is not None else None,
        "unit": bbox.get("units"),
    }


def _choices_text(items):
    return "\n".join(f"{it.get('label', '')} {it.get('md', '')}".strip()
                     for it in items)


# ── QP page alignment ─────────────────────────────────────────────────────────


class _PageAligner:
    """Sequential bidirectional-containment alignment of block text to qp.md pages.

    For each block, searches from a forward cursor for the first qp.md line whose
    normalized text contains the block's normalized search line or vice versa.
    Never searches backwards, so repeated furniture lines ("DO NOT WRITE IN
    THIS AREA") cannot drag a block to an earlier page. Blocks that do not
    align inherit the owning question's opener page (counted in `inherited`).
    """

    def __init__(self, lines, per_line):
        self._norm_lines = [(i, _norm(ln)) for i, ln in enumerate(lines)]
        self._norm_lines = [(i, t) for i, t in self._norm_lines if t]
        self.per_line = per_line
        self.cursor = 0
        self.aligned = 0
        self.inherited = 0

    def _find(self, key, start):
        k = _norm(key)
        if not k:
            return None
        for i, t in self._norm_lines:
            if i < start:
                continue
            if k in t or t in k:
                return i
        return None

    def question_page(self, key, fallback):
        """Anchor a question by its opener line; returns (page, found)."""
        idx = self._find(key, 0)
        if idx is None:
            return fallback, False
        return self.per_line[idx], True

    def block_page(self, search_line, fallback_page):
        idx = self._find(search_line, self.cursor)
        if idx is None:
            self.inherited += 1
            return fallback_page
        self.cursor = idx + 1
        self.aligned += 1
        return self.per_line[idx]


def _block_search_line(block):
    t = block.get("type")
    if t == "para":
        return (block.get("md") or "").split("\n")[0]
    if t == "table":
        for ln in (block.get("md") or "").split("\n"):
            if ln.strip() and not re.match(r"^\|[\s:|-]+\|$", ln.strip()):
                return ln
        return None
    if t == "image":
        return None  # images carry exact pages already
    if t == "choices":
        items = block.get("items") or []
        return f"{items[0].get('label', '')} {items[0].get('md', '')}".strip() if items else None
    return None  # answer_lines and unknown types inherit


# ── document builders ─────────────────────────────────────────────────────────


def _source_block(paper_dir, filename, manifest_checksums, mat_key):
    path = os.path.join(paper_dir, filename)
    checksum = sha256_file(path)
    expected = manifest_checksums.get(mat_key)
    if expected and expected != checksum:
        raise ValueError(
            f"{filename} sha256 {checksum} != manifest {expected} — refusing to mint identity")
    return {
        "uri": os.path.join(os.path.basename(paper_dir), filename),
        "checksum": checksum, "checksumAlgorithm": "SHA-256",
        "mimeType": PDF_MIME, "fileName": filename,
    }


def _document(source, page_count, sections, elements, params, retrieval=None):
    els = elements.all()
    doc = {
        "documentId": content_document_id(source["checksum"], ENGINE_NAME, ENGINE_VERSION),
        "schemaVersion": SCHEMA_VERSION,
        "version": 1,
        "source": source,
        "pageCount": page_count,
        "pages": [{"pageNumber": n, "width": None, "height": None}
                  for n in range(1, page_count + 1)],
        "sections": sections,
        "textBlocks": elements.text_blocks,
        "tables": elements.tables,
        "figures": elements.figures,
        "equations": elements.equations,
        "provenance": {
            "engine": ENGINE_NAME, "engineVersion": ENGINE_VERSION,
            "extractedAt": None, "extractionParams": params,
            "application": APPLICATION, "schemaVersion": SCHEMA_VERSION,
        },
    }
    if retrieval is not None:
        # core CanonicalDocumentDto.RetrievalMeta — legacy-tolerant when absent
        doc["retrieval"] = retrieval
    return doc


def _iter_qp_blocks(question):
    """Reading-order block stream: stem, question-level choices, part prompts."""
    for b in question.get("stem") or []:
        yield "stem", b
    if question.get("choices"):
        yield "stem", {"type": "choices", "items": question["choices"]}
    for part in question.get("parts") or []:
        for b in part.get("prompt") or []:
            yield f"part:{part.get('id', '')}", b
        if part.get("choices"):
            yield f"part:{part.get('id', '')}", {
                "type": "choices", "items": part["choices"]}


def build_qp_document(paper_dir, atoms=None, qp_pages=None, manifest_checksums=None):
    atoms = atoms or load_atoms(paper_dir)
    marker_count, lines, per_line = qp_pages or qp_md_pages(paper_dir)
    manifest_checksums = (manifest_checksums if manifest_checksums is not None
                          else load_manifest_checksums(paper_dir))
    retrieval = load_retrieval_meta(paper_dir)
    # pageCount honesty: markers should cover the QP, but figure pages are
    # authoritative for their own page — raise pageCount if figures exceed it
    figure_pages = []
    for q in atoms["questions"]:
        for _s, b in _iter_qp_blocks(q):
            if b.get("type") == "image":
                p = (b.get("bbox") or {}).get("page")
                if p is None and b.get("pages"):
                    p = b["pages"][0]
                if p:
                    figure_pages.append(p)
    page_count = max([marker_count] + figure_pages)
    aligner = _PageAligner(lines, per_line)
    els = _Elements()
    sections = []
    stats = {"questions": len(atoms["questions"]), "openerAnchors": 0,
             "openerFallbacks": 0, "blockAligned": 0, "blockInherited": 0,
             "furnitureExcluded": 0, "furnitureTotalRowsExcluded": 0,
             "figureAltFilled": 0, "figureAltBlocks": 0}

    for q in atoms["questions"]:
        blocks = list(_iter_qp_blocks(q))
        first = next((b for _, b in blocks if b.get("type") == "para"), None)
        opener_key = (first or {}).get("md", "").split("\n")[0]
        fallback_page, found = aligner.question_page(opener_key, 1)
        stats["openerAnchors" if found else "openerFallbacks"] += 1
        q_page = fallback_page
        group = f"q{int(q['number'])}"
        q_elems = []
        q_paras = []  # (emission_order, text) — G4 caption-pull candidates
        for order, (_scope, block) in enumerate(blocks):
            t = block.get("type")
            page = None
            if t == "image":
                page = (block.get("bbox") or {}).get("page")
                if page is None:
                    pages = block.get("pages") or []
                    page = pages[0] if pages else None
            if page is None:
                search = _block_search_line(block)
                page = (aligner.block_page(search, q_page)
                        if search else q_page)
            page = max(1, page)
            if t == "para":
                text = block.get("md")
                kind = classify_furniture(text)
                if kind:
                    stats["furnitureExcluded" if kind == "furniture"
                          else "furnitureTotalRowsExcluded"] += 1
                    continue
                el = els.add_text(text, page, group_key=group)
                if text:
                    q_paras.append((order, _norm(text)))
            elif t == "table":
                # tables are never furniture: a "Total" row inside a real
                # table is content (conservative whole-block policy)
                el = els.add_table(block.get("md") or "", page,
                                   _bbox_from_atoms(block), group_key=group)
            elif t == "image":
                el = els.add_figure(block.get("src") or "", page,
                                    block.get("alt") or "",
                                    _bbox_from_atoms(block), group_key=group)
                if _resolve_figure_alt(el, q_paras, order):
                    stats["figureAltFilled"] += 1
                if el["alt"]:
                    # G4: the chunker packs text blocks, not figure elements —
                    # an adjacent [figure: alt] block carries the visual signal
                    # into the embeddings
                    alt_el = els.add_text(f"[figure: {el['alt']}]", page,
                                          role="figure_alt", group_key=group)
                    q_elems.append(alt_el["element_id"])
                    stats["figureAltBlocks"] += 1
            elif t == "choices":
                text = _choices_text(block.get("items") or [])
                kind = classify_furniture(text)
                if kind:
                    stats["furnitureExcluded" if kind == "furniture"
                          else "furnitureTotalRowsExcluded"] += 1
                    continue
                el = els.add_text(text, page, role="choices", group_key=group)
            elif t == "answer_lines":
                el = els.add_text(None, page, role="answer_lines", group_key=group)
            else:  # unknown future block type: keep provenance, no text
                el = els.add_text(block.get("md"), page, group_key=group)
            q_elems.append(el["element_id"])
        sections.append({
            "sectionId": f"q{int(q['number']):02d}",
            "title": f"Question {q['number']} ({q.get('marks', 0)} marks)",
            "level": 1, "pageNumber": q_page, "elementIds": q_elems,
        })
    stats["blockAligned"] = aligner.aligned
    stats["blockInherited"] = aligner.inherited
    stats["qpMarkerPageCount"] = marker_count
    stats["qpFigurePages"] = len(figure_pages)
    stats["qpPageCountBasis"] = ("markers" if page_count == marker_count
                                 else "max(markers, figure pages)")
    doc = _document(
        _source_block(paper_dir, "qp.pdf", manifest_checksums, "question-paper"),
        page_count, sections, els, {
            "upstreamProduct": "syllabai.pastpaper.atoms/1.1",
            "pageAlignment": "qp-md-markers", **stats,
        }, retrieval=retrieval)
    return doc


def _point_text(qnum, pt):
    marks = pt.get("marks", 0)
    lines = [f"Q{qnum} {pt.get('id', '')} ({marks} mark"
             f"{'s' if marks != 1 else ''}): {pt.get('md', '')}"]
    for key, label in (("allow", "allow"), ("reject", "reject"),
                       ("ignore", "ignore")):
        vals = pt.get(key) or []
        if vals:
            lines.append(f"{label}: " + "; ".join(vals))
    for note in pt.get("notes") or []:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def build_ms_document(paper_dir, atoms=None, manifest_checksums=None):
    atoms = atoms or load_atoms(paper_dir)
    manifest_checksums = (manifest_checksums if manifest_checksums is not None
                          else load_manifest_checksums(paper_dir))
    retrieval = load_retrieval_meta(paper_dir)
    els = _Elements()
    sections = []
    max_page = 1

    for q in atoms["questions"]:
        ms = q.get("markScheme") or {}
        points = ms.get("points") or []
        pages = [p for pt in points for p in (pt.get("pages") or [])]
        q_page = min(pages) if pages else 1
        max_page = max([max_page] + pages)
        group = f"q{int(q['number'])}"
        q_elems = []
        heading_el = els.add_text(
            f"Mark scheme for Question {q['number']}", q_page,
            role="heading", heading_level=2, group_key=group)
        q_elems.append(heading_el["element_id"])
        totals = ms.get("totals") or {}
        if totals.get("printed") is not None:
            el = els.add_text(
                f"Question {q['number']} printed total: {totals['printed']} marks"
                + ("" if totals.get("verified") else " (verification FAILED)"),
                q_page, role="paragraph", group_key=group)
            q_elems.append(el["element_id"])
        for band in ms.get("levels") or []:
            rng = band.get("markRange") or {}
            el = els.add_text(
                f"Level {band.get('level')} ({rng.get('min')}-{rng.get('max')} marks): "
                f"{band.get('descriptor', '')}", q_page, role="levels_band",
                group_key=group)
            q_elems.append(el["element_id"])
        for g in ms.get("guidance") or []:
            el = els.add_text(f"Q{q['number']} guidance: {g}", q_page,
                              group_key=group)
            q_elems.append(el["element_id"])
        for pt in points:
            pt_pages = pt.get("pages") or [q_page]
            pt_page = max(1, min(pt_pages[0], max_page))
            el = els.add_text(_point_text(q["number"], pt), pt_page,
                              role="mark_point", group_key=group)
            q_elems.append(el["element_id"])
            img = pt.get("image")
            if img and img.get("src"):
                fpage = (img.get("pages") or [pt_page])[0]
                max_page = max(max_page, fpage)
                el = els.add_figure(img["src"], fpage, img.get("alt") or "",
                                    group_key=group)
                q_elems.append(el["element_id"])
                if (img.get("alt") or "").strip():
                    alt_el = els.add_text(f"[figure: {img['alt']}]", fpage,
                                          role="figure_alt", group_key=group)
                    q_elems.append(alt_el["element_id"])
        for img in ms.get("images") or []:
            if img.get("src"):
                fpage = (img.get("pages") or [q_page])[0]
                max_page = max(max_page, fpage)
                el = els.add_figure(img["src"], fpage, img.get("alt") or "",
                                    group_key=group)
                q_elems.append(el["element_id"])
                if (img.get("alt") or "").strip():
                    alt_el = els.add_text(f"[figure: {img['alt']}]", fpage,
                                          role="figure_alt", group_key=group)
                    q_elems.append(alt_el["element_id"])
        sections.append({
            "sectionId": f"q{int(q['number']):02d}",
            "title": f"Question {q['number']} mark scheme",
            "level": 1, "pageNumber": q_page, "elementIds": q_elems,
        })

    doc = _document(
        _source_block(paper_dir, "ms.pdf", manifest_checksums, "mark-scheme"),
        max_page, sections, els, {
            "upstreamProduct": "syllabai.pastpaper.atoms/1.1",
            "pointPagesSource": "atoms ms points",
        }, retrieval=retrieval)
    return doc


# ── core mirrors (validator + chunker) — dry-run without a Java runtime ──────


def validate_canonical(doc):
    """Mirror of core CanonicalDocumentValidator (same violations, same order)."""
    v = []

    def blank(s):
        return s is None or (isinstance(s, str) and s.strip() == "")

    if doc.get("schemaVersion") != "1.0":
        v.append('schemaVersion must be "1.0"')
    if blank(doc.get("documentId")):
        v.append("documentId is required")
    if not isinstance(doc.get("version"), int) or doc["version"] < 1:
        v.append("version must be >= 1")
    src = doc.get("source")
    if not src:
        v.append("source is required")
    else:
        for k in ("uri", "checksum", "mimeType"):
            if blank(src.get(k)):
                v.append(f"source.{k} is required")
    if not isinstance(doc.get("pageCount"), int) or doc["pageCount"] < 1:
        v.append("pageCount must be >= 1")
    prov = doc.get("provenance")
    if not prov:
        v.append("provenance is required")
    else:
        if blank(prov.get("engine")):
            v.append("provenance.engine is required")
        if blank(prov.get("engineVersion")):
            v.append("provenance.engineVersion is required")
        if not blank(doc.get("documentId")) and src and not blank(src.get("checksum")):
            derived = content_document_id(src["checksum"], prov["engine"],
                                          prov["engineVersion"])
            if derived != doc["documentId"]:
                v.append(f"documentId derivation drift (expected {derived})")
    # retrieval identity (Embedding v2, plan §4.2/§8.1) — mirror of core
    # CanonicalDocumentValidator: optional as a whole, but a series that IS
    # present must be the canonical enum and the year plausible.
    ret = doc.get("retrieval")
    if ret is not None:
        s = ret.get("series")
        if s is not None and str(s).strip() != "" and str(s).strip() not in (
                "JAN", "JUN", "NOV"):
            v.append(f'retrieval.series must be JAN, JUN or NOV (was {s!r}) — '
                     'canonicalize "Summer"→JUN, "October/November"→NOV before ingest')
        y = ret.get("year")
        if y is not None and not (1950 <= int(y) <= 2100):
            v.append(f"retrieval.year must be a plausible exam year (was {y})")
    seen = set()
    for family, els in (("textBlock", doc.get("textBlocks")),
                        ("table", doc.get("tables")),
                        ("equation", doc.get("equations")),
                        ("figure", doc.get("figures"))):
        for e in els or []:
            label = f"{family} {e.get('element_id') if e else None}"
            if not e:
                v.append(f"{family} null element")
                continue
            if blank(e.get("element_id")):
                v.append(f"{family} without element_id")
            elif e["element_id"] in seen:
                v.append(f"duplicate element_id {e['element_id']}")
            else:
                seen.add(e["element_id"])
            if blank(e.get("element_type")):
                v.append(f"{label}: element_type is required")
            pn = e.get("page_number")
            if pn is None:
                v.append(f"{label}: page_number is required")
            elif pn < 1 or pn > doc["pageCount"]:
                v.append(f"{label}: page_number {pn} outside 1..{doc['pageCount']}")
            ro = e.get("reading_order")
            if ro is None or ro < 0:
                v.append(f"{label}: reading_order must be >= 0")
            conf = e.get("confidence")
            if conf is not None and not (0.0 <= conf <= 1.0):
                v.append(f"{label}: confidence outside 0..1")
            if blank(e.get("source_engine")):
                v.append(f"{label}: source_engine is required")
            if blank(e.get("source_engine_version")):
                v.append(f"{label}: source_engine_version is required")
    for s in doc.get("sections") or []:
        if not s or blank(s.get("sectionId")):
            v.append("section without sectionId")
        else:
            for ref in s.get("elementIds") or []:
                if ref not in seen:
                    v.append(f"section {s['sectionId']} references unknown element {ref}")
    return v


def simulate_chunks(doc, target=CHUNK_TARGET_TOKENS, max_tokens=CHUNK_MAX_TOKENS):
    """Faithful port of core ChunkingService.chunk (deterministic packing).

    v1.2.0 contract parity: a group_key change between consecutive blocks is a
    HARD chunk boundary (no chunk crosses an atom) exactly as core R2 ships it;
    blocks without a group_key (legacy shape) never introduce a boundary.
    """
    cands = []
    for e in doc.get("textBlocks") or []:
        if e and e.get("text") and e["text"].strip():
            cands.append((e["element_id"], e["page_number"], e["reading_order"],
                          e["text"].strip(), e.get("group_key")))
    for e in doc.get("tables") or []:
        if e and e.get("text") and e["text"].strip():
            cands.append((e["element_id"], e["page_number"], e["reading_order"],
                          e["text"].strip(), e.get("group_key")))
    for e in doc.get("equations") or []:
        if e:
            text = (e.get("text") or "").strip() or (e.get("latex") or "").strip()
            if text:
                cands.append((e["element_id"], e["page_number"],
                              e["reading_order"], text, e.get("group_key")))
    cands.sort(key=lambda c: (c[1], c[2], c[0]))

    def estimate(t):
        return max(1, (len(t) + 3) // 4)

    chunks, current, tokens = [], [], 0
    prev_group = None
    for eid, page, _ro, text, group in cands:
        t = estimate(text)
        boundary = (prev_group is not None and group is not None
                    and group != prev_group)
        if boundary and current:
            chunks.append((current, tokens))
            current, tokens = [], 0
        if t > max_tokens:
            if current:
                chunks.append((current, tokens))
                current, tokens = [], 0
            chunks.append(([(eid, page, text)], t))
            prev_group = group
            continue
        if tokens + t > target and current:
            chunks.append((current, tokens))
            current, tokens = [], 0
        current.append((eid, page, text))
        tokens += t
        prev_group = group
    if current:
        chunks.append((current, tokens))

    out = []
    for i, (blocks, tok) in enumerate(chunks):
        content = "\n".join(b[2] for b in blocks)
        out.append({
            "chunkIndex": i,
            "content": content,
            "contentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "pageStart": min(b[1] for b in blocks),
            "pageEnd": max(b[1] for b in blocks),
            "elementIds": [b[0] for b in blocks],
            "tokenEstimate": max(1, tok),
        })
    return out


# ── leakage guard ─────────────────────────────────────────────────────────────


def assert_no_leakage(qp_doc):
    """QP canonical JSON must never carry answer content (hard rule)."""
    blob = json.dumps(qp_doc)
    forbidden = ('"correct"', '"markScheme"', '"allow"', '"reject"')
    hits = [f for f in forbidden if f in blob]
    if hits:
        raise ValueError(f"QP document leakage: {hits}")
    for e in qp_doc.get("textBlocks") or []:
        role = e.get("role") or ""
        if role in ("mark_point", "levels_band", "guidance"):
            raise ValueError(f"QP document carries MS-role element: {role}")


# ── CLI ───────────────────────────────────────────────────────────────────────


def convert_paper(paper_dir, out_dir):
    atoms = load_atoms(paper_dir)
    manifest_checksums = load_manifest_checksums(paper_dir)
    qp_doc = build_qp_document(paper_dir, atoms=atoms,
                               manifest_checksums=manifest_checksums)
    ms_doc = build_ms_document(paper_dir, atoms=atoms,
                               manifest_checksums=manifest_checksums)
    assert_no_leakage(qp_doc)
    problems = validate_canonical(qp_doc) + validate_canonical(ms_doc)
    if problems:
        raise ValueError(f"{paper_dir}: canonical validation failed: {problems}")
    qp_chunks = simulate_chunks(qp_doc)
    ms_chunks = simulate_chunks(ms_doc)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "qp.canonical.json"), "w", encoding="utf-8") as f:
        json.dump(qp_doc, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "ms.canonical.json"), "w", encoding="utf-8") as f:
        json.dump(ms_doc, f, ensure_ascii=False, indent=1)
    preview = {
        "note": "mirror of core ChunkingService (300/800 tokens) — core is the "
                "authority at ingest; this preview proves chunk/page behavior",
        "targetTokens": CHUNK_TARGET_TOKENS, "maxTokens": CHUNK_MAX_TOKENS,
        "qp": {"chunkCount": len(qp_chunks), "chunks": qp_chunks},
        "ms": {"chunkCount": len(ms_chunks), "chunks": ms_chunks},
    }
    with open(os.path.join(out_dir, "chunks_preview.json"), "w", encoding="utf-8") as f:
        json.dump(preview, f, ensure_ascii=False, indent=1)

    def doc_summary(doc, chunks):
        return {
            "documentId": doc["documentId"],
            "checksum": doc["source"]["checksum"],
            "source": doc["source"]["fileName"],
            "pageCount": doc["pageCount"],
            "totalElements": len(doc["textBlocks"]) + len(doc["tables"])
                             + len(doc["figures"]) + len(doc["equations"]),
            "textElements": len(doc["textBlocks"]) + len(doc["tables"])
                            + len(doc["equations"]),
            "sections": len(doc["sections"]),
            "chunks": len(chunks),
            "retrieval": doc.get("retrieval"),
            "extractionParams": doc["provenance"]["extractionParams"],
        }

    summary = {
        "paperDir": os.path.basename(os.path.normpath(paper_dir)),
        "schema": atoms["schema"],
        "questionCount": atoms["questionCount"],
        "totalMarks": atoms["totalMarks"],
        "marksVerified": atoms["marksVerified"],
        "engine": f"{ENGINE_NAME}/{ENGINE_VERSION}",
        "qp": doc_summary(qp_doc, qp_chunks),
        "ms": doc_summary(ms_doc, ms_chunks),
    }
    with open(os.path.join(out_dir, "paper_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return summary


def find_products(corpus_root):
    """All paper dirs under a corpus root that carry a parsed/questions.json."""
    out = []
    for dirpath, dirnames, filenames in os.walk(corpus_root):
        if "questions.json" in filenames and "parsed" in os.path.basename(dirpath):
            out.append(os.path.dirname(dirpath))
            dirnames[:] = []
    return sorted(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--paper-dir", help="one paper folder (contains manifest.yaml + parsed/)")
    ap.add_argument("--corpus", help="corpus root — convert every parsed/ product under it")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args(argv)
    if bool(args.paper_dir) == bool(args.corpus):
        ap.error("exactly one of --paper-dir / --corpus is required")

    if args.paper_dir:
        slug = os.path.basename(os.path.normpath(args.paper_dir))
        summary = convert_paper(args.paper_dir, args.out)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0

    summaries = []
    for paper_dir in find_products(args.corpus):
        rel = os.path.relpath(paper_dir, args.corpus)
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", rel)
        out_dir = os.path.join(args.out, slug)
        s = convert_paper(paper_dir, out_dir)
        s["corpusRelPath"] = rel
        summaries.append(s)
        print(f"OK {rel}: qp {s['qp']['chunks']} chunks / "
              f"ms {s['ms']['chunks']} chunks", file=sys.stderr)
    corpus_summary = {"converted": len(summaries), "papers": summaries}
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(corpus_summary, f, ensure_ascii=False, indent=1)
    print(f"converted {len(summaries)} papers -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
