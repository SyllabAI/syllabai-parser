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
INLINE_DISPLAY_MATH = re.compile(r"^\$\$(.+)\$\$\s*$")
TR_TAG = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_TAG = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
ANY_TAG = re.compile(r"<[^>]+>")
ENTITY = re.compile(r"&#x([0-9a-fA-F]+);|&#(\d+);|&gt;|&lt;|&amp;|&quot;|&apos;")

_NAMED_ENTITIES = {"&gt;": ">", "&lt;": "<", "&amp;": "&", "&quot;": '"', "&apos;": "'"}


def decode_entities(text):
    """Deterministic HTML-entity decoding (the one normalization performed)."""
    if text is None or "&" not in text:
        return text

    def repl(match: re.Match) -> str:
        hex_group, dec_group = match.group(1), match.group(2)
        if hex_group is not None:
            return chr(int(hex_group, 16))
        if dec_group is not None:
            return chr(int(dec_group))
        return _NAMED_ENTITIES.get(match.group(0), match.group(0))

    return ENTITY.sub(repl, text)


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
            no_tags = ANY_TAG.sub("", cell)
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
                html = [stripped]
                while "</table>" not in stripped and i + 1 < n:
                    i += 1
                    stripped = lines[i].strip()
                    html.append(stripped)
                rows, decodes = _parse_html_table("\n".join(html))
                entity_decodes += decodes
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
                i += 1
                continue

            if CENTER_OPEN.fullmatch(stripped):
                i += 1
                inner = []
                while i < n and not CENTER_CLOSE.fullmatch(lines[i].strip()):
                    inner_line = lines[i].strip()
                    if inner_line:
                        inner.append(inner_line)
                    i += 1
                i += 1  # consume </div>
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
                latex = []
                i += 1
                while i < n and not DISPLAY_MATH_OPEN.fullmatch(lines[i].strip()):
                    latex.append(lines[i].rstrip() + "\n")
                    i += 1
                i += 1  # closing $$
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

            inline_math = INLINE_DISPLAY_MATH.fullmatch(stripped)
            if inline_math:
                content = inline_math.group(1).strip()
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
