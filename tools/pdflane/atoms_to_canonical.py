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
ENGINE_VERSION = "1.1.0"
SCHEMA_VERSION = "1.0"
APPLICATION = "syllabai-parser"
PDF_MIME = "application/pdf"

PAGE_MARK = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")

CHUNK_TARGET_TOKENS = 300
CHUNK_MAX_TOKENS = 800


# ── helpers ───────────────────────────────────────────────────────────────────


def _norm(s):
    """Whitespace-collapsed comparison form for alignment search."""
    return re.sub(r"\s+", " ", s or "").strip()


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

    def add_text(self, text, page, role="paragraph", heading_level=None, bbox=None):
        idx = self._next_id()
        self.text_blocks.append({
            "element_id": f"e{idx:06d}", "element_type": "text_block",
            "page_number": page, "bounding_box": bbox, "text": text,
            "reading_order": idx, "confidence": 1.0, "role": role,
            "heading_level": heading_level, **_engine_fields(),
        })
        return self.text_blocks[-1]

    def add_table(self, md, page, bbox=None):
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
        })
        return self.tables[-1]

    def add_figure(self, src, page, alt="", bbox=None):
        idx = self._next_id()
        fmt = src[src.rfind(".") + 1:] if "." in src else None
        self.figures.append({
            "element_id": f"e{idx:06d}", "element_type": "figure",
            "page_number": page, "bounding_box": bbox, "text": src,
            "reading_order": idx, "confidence": 1.0, "format": fmt,
            "source_name": src, "alt": alt or "", **_engine_fields(),
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


def _document(source, page_count, sections, elements, params):
    els = elements.all()
    return {
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
             "openerFallbacks": 0, "blockAligned": 0, "blockInherited": 0}

    for q in atoms["questions"]:
        blocks = list(_iter_qp_blocks(q))
        first = next((b for _, b in blocks if b.get("type") == "para"), None)
        opener_key = (first or {}).get("md", "").split("\n")[0]
        fallback_page, found = aligner.question_page(opener_key, 1)
        stats["openerAnchors" if found else "openerFallbacks"] += 1
        q_page = fallback_page
        q_elems = []
        for _scope, block in blocks:
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
                el = els.add_text(block.get("md"), page)
            elif t == "table":
                el = els.add_table(block.get("md") or "", page,
                                   _bbox_from_atoms(block))
            elif t == "image":
                el = els.add_figure(block.get("src") or "", page,
                                    block.get("alt") or "",
                                    _bbox_from_atoms(block))
            elif t == "choices":
                el = els.add_text(_choices_text(block.get("items") or []),
                                  page, role="choices")
            elif t == "answer_lines":
                el = els.add_text(None, page, role="answer_lines")
            else:  # unknown future block type: keep provenance, no text
                el = els.add_text(block.get("md"), page)
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
        })
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
    els = _Elements()
    sections = []
    max_page = 1

    for q in atoms["questions"]:
        ms = q.get("markScheme") or {}
        points = ms.get("points") or []
        pages = [p for pt in points for p in (pt.get("pages") or [])]
        q_page = min(pages) if pages else 1
        max_page = max([max_page] + pages)
        q_elems = []
        header = els.add_text(f"Mark scheme for Question {q['number']}", q_page,
                              role="heading", heading_level=2)
        q_elems.append(header["element_id"])
        totals = ms.get("totals") or {}
        if totals.get("printed") is not None:
            el = els.add_text(
                f"Question {q['number']} printed total: {totals['printed']} marks"
                + ("" if totals.get("verified") else " (verification FAILED)"),
                q_page, role="paragraph")
            q_elems.append(el["element_id"])
        for band in ms.get("levels") or []:
            rng = band.get("markRange") or {}
            el = els.add_text(
                f"Level {band.get('level')} ({rng.get('min')}-{rng.get('max')} marks): "
                f"{band.get('descriptor', '')}", q_page, role="levels_band")
            q_elems.append(el["element_id"])
        for g in ms.get("guidance") or []:
            el = els.add_text(f"Q{q['number']} guidance: {g}", q_page)
            q_elems.append(el["element_id"])
        for pt in points:
            pt_pages = pt.get("pages") or [q_page]
            pt_page = max(1, min(pt_pages[0], max_page))
            el = els.add_text(_point_text(q["number"], pt), pt_page,
                              role="mark_point")
            q_elems.append(el["element_id"])
            img = pt.get("image")
            if img and img.get("src"):
                fpage = (img.get("pages") or [pt_page])[0]
                max_page = max(max_page, fpage)
                el = els.add_figure(img["src"], fpage, img.get("alt") or "")
                q_elems.append(el["element_id"])
        for img in ms.get("images") or []:
            if img.get("src"):
                fpage = (img.get("pages") or [q_page])[0]
                max_page = max(max_page, fpage)
                el = els.add_figure(img["src"], fpage, img.get("alt") or "")
                q_elems.append(el["element_id"])
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
        })
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
    """Faithful port of core ChunkingService.chunk (deterministic packing)."""
    cands = []
    for e in doc.get("textBlocks") or []:
        if e and e.get("text") and e["text"].strip():
            cands.append((e["element_id"], e["page_number"], e["reading_order"],
                          e["text"].strip()))
    for e in doc.get("tables") or []:
        if e and e.get("text") and e["text"].strip():
            cands.append((e["element_id"], e["page_number"], e["reading_order"],
                          e["text"].strip()))
    for e in doc.get("equations") or []:
        if e:
            text = (e.get("text") or "").strip() or (e.get("latex") or "").strip()
            if text:
                cands.append((e["element_id"], e["page_number"],
                              e["reading_order"], text))
    cands.sort(key=lambda c: (c[1], c[2], c[0]))

    def estimate(t):
        return max(1, (len(t) + 3) // 4)

    chunks, current, tokens = [], [], 0
    for eid, page, _ro, text in cands:
        t = estimate(text)
        if t > max_tokens:
            if current:
                chunks.append((current, tokens))
                current, tokens = [], 0
            chunks.append(([(eid, page, text)], t))
            continue
        if tokens + t > target and current:
            chunks.append((current, tokens))
            current, tokens = [], 0
        current.append((eid, page, text))
        tokens += t
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
