"""Canonical layer port: deterministic identity + Markdown adapter.

Mirrors ``CanonicalIdentity`` and ``GlmOcrMarkdownParser`` from the Java
parser. JSON output shape matches Jackson's serialization of the canonical
records exactly (snake_case element fields, camelCase document fields).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from urllib.parse import unquote, urlsplit

from . import ENGINE_NAME, ENGINE_VERSION

MARKDOWN_MIME = "text/markdown"
SCHEMA_VERSION = "1.0"
APPLICATION = "syllabai-parser"

EPOCH = "1970-01-01T00:00:00Z"


# ── deterministic identity (CanonicalIdentity) ────────────────────────────────


def content_document_id(checksum: str, engine: str, engine_version: str) -> str:
    """UUID (version-5 layout) from SHA-256 of the identity material.

    Same formula as Java ``CanonicalIdentity``:
    ``"sha256:<checksum>|engine:<engine>|version:<engineVersion>"`` — all
    lowercased and stripped; version nibble 5, RFC-4122 variant bits.
    """
    material = (
        "sha256:" + (checksum or "").strip().lower()
        + "|engine:" + (engine or "").strip().lower()
        + "|version:" + (engine_version or "").strip().lower()
    )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    b = bytearray(digest[:16])
    b[6] = (b[6] & 0x0F) | 0x50
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(b)))


# ── patterns (identical to the Java adapter) ──────────────────────────────────

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_ITEM = re.compile(r"^[-*]\s+(.+)$")
IMAGE_LINE = re.compile(
    r"^<div[^>]*>\s*<img\s+src='([^']+)'(?:\s+alt='([^']*)')?\s*/>\s*</div>\s*$")
CENTER_OPEN = re.compile(r"^<div\s+align=[\"']center[\"']>\s*$")
CENTER_CLOSE = re.compile(r"^</div>\s*$")
DISPLAY_MATH_OPEN = re.compile(r"^\$\$\s*$")
MATH_SPAN = re.compile(r"\$\$(.+?)\$\$")
TR_TAG = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_TAG = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
ANY_TAG = re.compile(r"<[^>]+>")
BR_TAG = re.compile(r"<br\s*/?>", re.I)
ENTITY = re.compile(r"&#x([0-9a-fA-F]+);|&#(\d+);|&gt;|&lt;|&amp;|&quot;|&apos;")

# ── bounded-block hardening (structural-boundary predicates) ─────────────────
#
# An unterminated block opener (<table> without </table>, a $$ fence whose
# closer was lost, a <div align=center> without </div>) must not swallow the
# rest of the document: scanning stops at lines that can only be block-
# EXTERNAL content, the opener is reported in provenance, and the swallowed
# span re-parses as normal flow. The predicates mirror the corpus-repair
# heuristics validated against the full 82-session IGCSE chemistry corpus
# (Past-Papers repair pass): decisive markers bound table spans; math spans
# also stop at part labels / question stems / total lines unless the line
# carries equation operators or table-cell markup.

CELL_HTML = re.compile(r"<t[dhr]\b|</t[dhr]>")
EQ_OPS = re.compile(r"[+=]|\\rightarrow|\\quad|\\mathrm|\\%")
PART_LABEL = re.compile(r"^\([a-h]\)\s")
ROMAN_LABEL = re.compile(r"^\([ivx]+\)\s")
QUESTION_STEM = re.compile(r"^\d{1,2}\s+[A-Za-z]{3,}")
TOTAL_LINE = re.compile(r"^\(?\s*Total for (Question|question|paper)", re.I)


def _decisive(s):
    """Certain block-external content: headings, div/img wrappers, tables."""
    return bool(s) and (s.startswith("#") or s.startswith("<div")
                        or s.startswith("<table") or "<img" in s)


def _structural(s):
    """Boundary usable inside MATH spans (equations never look like stems)."""
    if not s or CELL_HTML.search(s):
        return False
    if _decisive(s):
        return True
    if EQ_OPS.search(s):
        return False
    return bool(PART_LABEL.match(s) or ROMAN_LABEL.match(s)
                or QUESTION_STEM.match(s) or TOTAL_LINE.match(s))


# div spans stop only at their own kind of structure: a heading, a table or a
# second center-div opener. <img>/<div style> wrappers are legitimate INNER
# content of center blocks and must not terminate the scan.

_NAMED_ENTITIES = {"&gt;": ">", "&lt;": "<", "&amp;": "&", "&quot;": '"', "&apos;": "'"}


def decode_entities(text):
    """Deterministic HTML-entity decoding (the one normalization performed)."""
    if text is None or "&" not in text:
        return text

    def repl(match: re.Match) -> str:
        hex_group, dec_group = match.group(1), match.group(2)
        if hex_group is not None:
            return _decode_code_point(int(hex_group, 16), match.group(0))
        if dec_group is not None:
            return _decode_code_point(int(dec_group), match.group(0))
        return _NAMED_ENTITIES.get(match.group(0), match.group(0))

    return ENTITY.sub(repl, text)


def _decode_code_point(code_point: int, literal: str) -> str:
    """P-9: numeric entities decode across the FULL Unicode range — astral
    plane code points previously truncated in the Java twin. Surrogate-range
    and out-of-range code points stay as the literal entity: a deterministic
    fail-safe mirrored byte-for-byte by GlmOcrMarkdownParser.decodeCodePoint."""
    if 0 <= code_point <= 0x10FFFF and not (0xD800 <= code_point <= 0xDFFF):
        return chr(code_point)
    return literal


def _math_spans(line: str):
    """All non-overlapping lazy $$..$$ spans on a line, outermost-first:
    (match_start, match_end, content). Mirrors GlmOcrMarkdownParser.mathSpanBounds."""
    return [(m.start(), m.end(), m.group(1)) for m in MATH_SPAN.finditer(line)]


def _fully_covered(line: str, spans) -> bool:
    """True when the line is only whitespace outside the matched $$..$$ spans.
    A line mixing math spans with prose is NOT display math (P-11)."""
    prev = 0
    for start, end, _ in spans:
        if line[prev:start].strip():
            return False
        prev = end
    return not line[prev:].strip()


def _url_path(url: str) -> str:
    """Decoded URL path; falls back to the raw string on malformed input."""
    try:
        path = urlsplit(url).path
        if not path:
            return url
        return unquote(path)
    except ValueError:
        return url


def _parse_html_table(html: str):
    """Flat table parser: rows of cells, tags stripped, entities decoded."""
    rows = []
    decodes = 0
    for row_match in TR_TAG.finditer(html):
        cells = []
        for cell_match in CELL_TAG.finditer(row_match.group(1)):
            cell = cell_match.group(1)
            if ENTITY.search(cell):
                decodes += 1
            # <br> variants become newlines FIRST — they ARE printed line
            # breaks in the original (e.g. "Paper Reference<br>4CH1/1C");
            # dropping them glues separate printed lines into one token soup
            # that then defeats every line-based identity regex downstream
            # (engine 1.1.0, mirrors the Java cleanCell order).
            brs = BR_TAG.sub("\n", cell)
            no_tags = ANY_TAG.sub("", brs)
            cells.append(decode_entities(no_tags).strip())
        if cells:
            rows.append(cells)
    return rows, decodes


# ── the adapter ───────────────────────────────────────────────────────────────


class GlmOcrMarkdownParser:
    """Markdown → canonical document, deterministic (see Java twin)."""

    engine_name = ENGINE_NAME
    engine_version = ENGINE_VERSION

    def supports(self, mime_type: str) -> bool:
        return mime_type == MARKDOWN_MIME or mime_type == "text/x-markdown"

    def parse(self, source: bytes, source_uri: str):
        text = source.decode("utf-8")
        return self._build(text, source, source_uri, extracted_at=None)

    def parse_with_fixed_identity(self, source: bytes, source_uri: str, extracted_at: str):
        return self._build(text=source.decode("utf-8"), source=source,
                           source_uri=source_uri, extracted_at=extracted_at)

    # ── markdown → canonical model ──────────────────────────────────────────

    def _build(self, text: str, source: bytes, source_uri: str, extracted_at):
        lines = text.split("\n")

        text_blocks = []
        tables = []
        figures = []
        equations = []

        signed_url_refs = 0
        entity_decodes = 0
        unterminated_tables = 0
        orphan_math_fences = 0
        unclosed_divs = 0
        greedy_math_lines = 0
        pending_orphan_divs = 0

        def next_index():
            return len(text_blocks) + len(tables) + len(figures) + len(equations)

        i = 0
        n = len(lines)
        while i < n:
            raw = lines[i]
            line = raw[:-1] if raw.endswith("\r") else raw
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            # a standalone </div> reaching top level closes a dropped orphan
            # div opener; skip it instead of leaking HTML into the text flow
            if pending_orphan_divs and CENTER_CLOSE.fullmatch(stripped):
                pending_orphan_divs -= 1
                i += 1
                continue

            image = IMAGE_LINE.fullmatch(stripped)
            if image:
                url = image.group(1)
                alt = image.group(2) if image.group(2) is not None else ""
                path = _url_path(url)
                fmt = None
                if path and "." in path:
                    fmt = path[path.rfind(".") + 1:]
                idx = next_index()
                figures.append({
                    "element_id": f"e{idx:06d}",
                    "element_type": "figure",
                    "page_number": 1,
                    "bounding_box": None,
                    "text": url,  # COMPLETE signed URL preserved
                    "reading_order": idx,
                    "confidence": 1.0,
                    "format": fmt,
                    "source_name": path,
                    "alt": alt,
                    "source_engine": ENGINE_NAME,
                    "source_engine_version": ENGINE_VERSION,
                })
                if "Signature=" in url and "Expires=" in url:
                    signed_url_refs += 1
                i += 1
                continue

            if stripped.startswith("<table"):
                # bounded scan: closer line, or a decisive structural line
                # (heading / div / img / new table) re-parsed as flow, or EOF
                end = n
                closed = False
                j = i
                while j < n:
                    s2 = lines[j].strip()
                    if "</table>" in s2:
                        closed = True
                        end = j + 1
                        break
                    if j > i and _decisive(s2):
                        end = j
                        break
                    j += 1
                html_lines = [lines[k].strip() for k in range(i, end)]
                if closed:
                    i = end
                else:
                    unterminated_tables += 1
                    # keep the last COMPLETE row; trailing partial rows
                    # re-parse as normal flow instead of vanishing into a
                    # bogus table that eats the remaining questions
                    last_row = -1
                    for k in range(i, end):
                        if "</tr>" in lines[k].strip():
                            last_row = k
                    if last_row >= 0:
                        html_lines = [lines[k].strip() for k in range(i, last_row + 1)]
                        i = last_row + 1
                    else:
                        html_lines = []  # opener with zero rows: nothing to salvage
                        i = i + 1
                rows, decodes = _parse_html_table("\n".join(html_lines))
                entity_decodes += decodes
                if html_lines:
                    # closed-but-empty tables still emit an element (text None),
                    # exactly as before; only a dropped unsalvageable opener
                    # (no closer, no complete row) emits nothing
                    idx = next_index()
                    joined = None
                    if rows:
                        joined = "\n".join(" | ".join(row) for row in rows)
                    tables.append({
                        "element_id": f"e{idx:06d}",
                        "element_type": "table",
                        "page_number": 1,
                        "bounding_box": None,
                        "text": joined,
                        "reading_order": idx,
                        "confidence": 1.0,
                        "rows": rows,
                        "row_count": len(rows),
                        "column_count": len(rows[0]) if rows else 0,
                        "source_engine": ENGINE_NAME,
                        "source_engine_version": ENGINE_VERSION,
                    })
                continue

            if CENTER_OPEN.fullmatch(stripped):
                # bounded scan: standalone </div>, a NESTED center opener (a
                # genuinely ambiguous pairing the old scanner mis-consumed),
                # or EOF. Headings / tables / img wrappers are legitimate
                # INNER content of center blocks in this corpus (e.g.
                # "<div align=center># Mark Scheme (Results)</div>") and must
                # not terminate the scan.
                end = n
                closed = False
                j = i + 1
                while j < n:
                    s2 = lines[j].strip()
                    if CENTER_CLOSE.fullmatch(s2):
                        closed = True
                        end = j
                        break
                    if CENTER_OPEN.fullmatch(s2):
                        end = j
                        break
                    j += 1
                if not closed:
                    unclosed_divs += 1
                    pending_orphan_divs += 1
                    i = i + 1  # opener dropped; inner lines re-parse as flow
                    continue
                inner = []
                for k in range(i + 1, end):
                    inner_line = lines[k].strip()
                    if inner_line:
                        inner.append(inner_line)
                i = end + 1  # consume </div>
                for inner_line in inner:
                    inner_heading = HEADING.fullmatch(inner_line)
                    idx = next_index()
                    if inner_heading:
                        text_blocks.append({
                            "element_id": f"e{idx:06d}",
                            "element_type": "text_block",
                            "page_number": 1,
                            "bounding_box": None,
                            "text": inner_heading.group(2),
                            "reading_order": idx,
                            "confidence": 1.0,
                            "role": "heading",
                            "heading_level": len(inner_heading.group(1)),
                            "source_engine": ENGINE_NAME,
                            "source_engine_version": ENGINE_VERSION,
                        })
                    else:
                        text_blocks.append({
                            "element_id": f"e{idx:06d}",
                            "element_type": "text_block",
                            "page_number": 1,
                            "bounding_box": None,
                            "text": decode_entities(inner_line),
                            "reading_order": idx,
                            "confidence": 1.0,
                            "role": "paragraph",
                            "heading_level": None,
                            "source_engine": ENGINE_NAME,
                            "source_engine_version": ENGINE_VERSION,
                        })
                continue

            if DISPLAY_MATH_OPEN.fullmatch(stripped):
                # bounded scan: the closing $$ line, or a structural line that
                # cannot be equation content, or EOF. An orphan opener is
                # dropped and its span re-parses as normal flow — the old
                # unbounded scan paired it with the NEXT block's opener and
                # swallowed everything between (2016-Jun-R lost q3-5/q7-10).
                end = n
                closed = False
                j = i + 1
                while j < n:
                    s2 = lines[j].strip()
                    if DISPLAY_MATH_OPEN.fullmatch(s2):
                        closed = True
                        end = j
                        break
                    if _structural(s2):
                        end = j
                        break
                    j += 1
                if not closed:
                    orphan_math_fences += 1
                    i = i + 1  # orphan opener dropped; span re-parses as flow
                    continue
                latex = [lines[k].rstrip() + "\n" for k in range(i + 1, end)]
                i = end + 1  # closing $$
                joined = "".join(latex).rstrip()
                idx = next_index()
                equations.append({
                    "element_id": f"e{idx:06d}",
                    "element_type": "equation",
                    "page_number": 1,
                    "bounding_box": None,
                    "text": joined,
                    "reading_order": idx,
                    "confidence": 1.0,
                    "latex": joined,
                    "source_engine": ENGINE_NAME,
                    "source_engine_version": ENGINE_VERSION,
                })
                continue

            # P-11: a line classified as inline display math must be FULLY covered
            # by lazy $$..$$ spans (whitespace between them allowed) — one equation
            # per span, in order. The old greedy ^\$\$(.+)\$\$$ capture swallowed
            # multiple spans AND the prose between them into one equation whose
            # latex contained literal '$$' markers; such mixed lines now fall
            # through to paragraph flow (raw line preserved for teacher review)
            # and are counted in provenance. Mirrors GlmOcrMarkdownParser exactly.
            spans = _math_spans(stripped)
            if spans and _fully_covered(stripped, spans):
                for _, _, span_content in spans:
                    content = span_content.strip()
                    idx = next_index()
                    equations.append({
                        "element_id": f"e{idx:06d}",
                        "element_type": "equation",
                        "page_number": 1,
                        "bounding_box": None,
                        "text": content,
                        "reading_order": idx,
                        "confidence": 1.0,
                        "latex": content,
                        "source_engine": ENGINE_NAME,
                        "source_engine_version": ENGINE_VERSION,
                    })
                i += 1
                continue
            if spans:
                greedy_math_lines += 1

            heading = HEADING.fullmatch(stripped)
            if heading:
                idx = next_index()
                text_blocks.append({
                    "element_id": f"e{idx:06d}",
                    "element_type": "text_block",
                    "page_number": 1,
                    "bounding_box": None,
                    "text": heading.group(2),
                    "reading_order": idx,
                    "confidence": 1.0,
                    "role": "heading",
                    "heading_level": len(heading.group(1)),
                    "source_engine": ENGINE_NAME,
                    "source_engine_version": ENGINE_VERSION,
                })
                i += 1
                continue

            list_item = LIST_ITEM.fullmatch(stripped)
            if list_item:
                idx = next_index()
                text_blocks.append({
                    "element_id": f"e{idx:06d}",
                    "element_type": "text_block",
                    "page_number": 1,
                    "bounding_box": None,
                    "text": list_item.group(1),
                    "reading_order": idx,
                    "confidence": 1.0,
                    "role": "list_item",
                    "heading_level": None,
                    "source_engine": ENGINE_NAME,
                    "source_engine_version": ENGINE_VERSION,
                })
                i += 1
                continue

            idx = next_index()
            text_blocks.append({
                "element_id": f"e{idx:06d}",
                "element_type": "text_block",
                "page_number": 1,
                "bounding_box": None,
                "text": decode_entities(stripped),
                "reading_order": idx,
                "confidence": 1.0,
                "role": "paragraph",
                "heading_level": None,
                "source_engine": ENGINE_NAME,
                "source_engine_version": ENGINE_VERSION,
            })
            if ENTITY.search(stripped):
                entity_decodes += 1
            i += 1

        params = {
            "upstreamConverter": "zai-glm-ocr",
            "pageBoundaries": "none-in-source",
            "normalizedHtmlEntities": True,
            "entityDecodedLines": entity_decodes,
            "signedUrlFigureRefs": signed_url_refs,
            "sourceLineCount": len(lines),
        }
        # honesty counters — present ONLY when non-zero so that clean-input
        # provenance maps stay byte-identical to the pre-hardening engine
        if unterminated_tables:
            params["unterminatedTableBlocks"] = unterminated_tables
        if orphan_math_fences:
            params["orphanMathFences"] = orphan_math_fences
        if unclosed_divs:
            params["unclosedCenterDivs"] = unclosed_divs
        if greedy_math_lines:
            params["greedyMathLines"] = greedy_math_lines

        file_name = None
        if source_uri is not None:
            file_name = source_uri.replace("\\", "/").split("/")[-1]

        checksum = hashlib.sha256(source).hexdigest()

        return {
            "documentId": content_document_id(checksum, ENGINE_NAME, ENGINE_VERSION),
            "schemaVersion": SCHEMA_VERSION,
            "version": 1,
            "source": {
                "uri": source_uri,
                "checksum": checksum,
                "checksumAlgorithm": "SHA-256",
                "mimeType": MARKDOWN_MIME,
                "fileName": file_name,
            },
            "pageCount": 1,
            "pages": [{"pageNumber": 1, "width": None, "height": None}],
            "sections": _sections_from_headings(text_blocks),
            "textBlocks": text_blocks,
            "tables": tables,
            "figures": figures,
            "equations": equations,
            "provenance": {
                "engine": ENGINE_NAME,
                "engineVersion": ENGINE_VERSION,
                "extractedAt": extracted_at,
                "extractionParams": params,
                "application": APPLICATION,
                "schemaVersion": SCHEMA_VERSION,
            },
        }


def _sections_from_headings(text_blocks):
    sections = []
    counter = 0
    current = None
    for block in text_blocks:
        if block["role"] == "heading":
            if current is not None:
                sections.append(current)
            counter += 1
            current = {
                "sectionId": f"s{counter:03d}",
                "title": block["text"],
                "level": block["heading_level"] if block["heading_level"] else 1,
                "pageNumber": 1,
                "elementIds": [],
            }
        elif current is not None:
            current["elementIds"].append(block["element_id"])
    if current is not None:
        sections.append(current)
    return sections


def elements_in_reading_order(document):
    """All elements sorted by reading order (mirrors elementsInReadingOrder)."""
    all_elements = (
        list(document["textBlocks"])
        + list(document["tables"])
        + list(document["figures"])
        + list(document["equations"])
    )
    all_elements.sort(key=lambda element: element["reading_order"])
    return all_elements
