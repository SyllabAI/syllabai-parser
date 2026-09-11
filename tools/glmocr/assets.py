"""Local image-asset enrichment for question-paper drafts (reference port).

Mirrors the Java wiring of ``GlmOcrImageAssets`` (Session 9 image-reality
rules): a figure reference whose {@code src} resolves to a real file under
the corpus assets directory is upgraded from the failure state
``unavailable-signed-url`` to ``available`` with content-derived identity —
``img:<sha256>``, sniffed MIME (magic bytes), container dimensions, and an
explicit extension/content mismatch flag. References that do not resolve are
left untouched (their bytes are genuinely gone).

This is OPT-IN enrichment: the default extraction path never touches
filesystems, so clean-input draft bytes stay identical to the pre-hardening
engine. Only new fields are added, and only when an asset resolves — the
Java side serializes them with per-field NON_NULL so unenriched drafts are
byte-identical across both implementations.
"""

from __future__ import annotations

import struct
from pathlib import Path

AVAILABILITY_AVAILABLE = "available"


def sniff_mime(b: bytes):
    """Magic-byte MIME sniffing — identical decisions to the Java twin."""
    if b is None or len(b) < 12:
        return None
    if (b[0] == 0x89 and b[1:4] == b"PNG"
            and b[4] == 0x0D and b[5] == 0x0A and b[6] == 0x1A and b[7] == 0x0A):
        return "image/png"
    if b[0] == 0xFF and b[1] == 0xD8 and b[2] == 0xFF:
        return "image/jpeg"
    if b[0:4] == b"GIF8":
        return "image/gif"
    if b[0:2] == b"BM":
        return "image/bmp"
    if b[0:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None


def dimensions(b: bytes, mime):
    """[width, height] from the container header; [-1, -1] when unknown."""
    if b is None or mime is None:
        return -1, -1
    if mime == "image/png":
        if len(b) < 24:
            return -1, -1
        return struct.unpack(">ii", b[16:24])
    if mime == "image/jpeg":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            marker = b[i + 1]
            sof = 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC)
            if sof:
                height, width = struct.unpack(">HH", b[i + 5:i + 9])
                return width, height
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            segment_length = struct.unpack(">H", b[i + 2:i + 4])[0]
            if segment_length <= 0:
                break
            i += 2 + segment_length
        return -1, -1
    if mime == "image/gif":
        if len(b) < 10:
            return -1, -1
        width, height = struct.unpack("<HH", b[6:10])
        return width, height
    if mime == "image/bmp":
        if len(b) < 26:
            return -1, -1
        width, height = struct.unpack("<ii", b[18:26])
        return width, abs(height)
    return -1, -1


def declared_format(source_name):
    if not source_name or "." not in source_name:
        return None
    return source_name[source_name.rfind(".") + 1:]


def _format_mismatch(sniffed, declared):
    return (sniffed is not None and declared is not None
            and sniffed != "image/" + declared.lower())


def resolve_asset(ref, assets_dir: Path):
    """Return an enriched copy of a figure reference, or the original dict
    untouched when the referenced file does not exist under assets_dir.

    Containment: a candidate is only considered when it stays inside
    ``assets_dir`` — reference URLs are corpus data, not trusted input, so a
    ``src`` like ``../../secrets.png`` (or an absolute path) never makes the
    resolver read outside the declared assets root; such references simply
    keep their failure state (identical decisions to the Java twin).
    """
    url = ref.get("url")
    if not url:
        return ref
    from urllib.parse import unquote, urlsplit
    try:
        path = urlsplit(url).path or url
        path = unquote(path)
    except ValueError:
        path = url
    root = assets_dir.resolve()
    candidates = []
    if not path.startswith("/"):
        candidates.append(assets_dir / path)
    name = path.replace("\\", "/").split("/")[-1]
    if name and (assets_dir / name) not in candidates:
        candidates.append(assets_dir / name)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                continue
            if not resolved.is_file():
                continue
            data = resolved.read_bytes()
        except OSError:
            continue
        sha256_hex = __import__("hashlib").sha256(data).hexdigest()
        sniffed = sniff_mime(data)
        declared = declared_format(ref.get("sourceName") or name)
        width, height = dimensions(data, sniffed)
        enriched = dict(ref)
        enriched["assetId"] = "img:" + sha256_hex
        enriched["sha256"] = sha256_hex
        enriched["mimeType"] = sniffed
        enriched["width"] = width if width >= 0 else None
        enriched["height"] = height if height >= 0 else None
        enriched["formatMismatch"] = _format_mismatch(sniffed, declared)
        enriched["availability"] = AVAILABILITY_AVAILABLE
        return enriched
    return ref


def enrich_paper_draft(draft: dict, assets_dir: Path) -> dict:
    """Walk every figure reference of a QP draft (question level, part level,
    front matter) and upgrade the ones that resolve locally."""
    enriched_total = 0

    def walk(refs):
        nonlocal enriched_total
        out = []
        for ref in refs:
            resolved = resolve_asset(ref, assets_dir)
            if resolved is not ref:
                enriched_total += 1
            out.append(resolved)
        return out

    questions = []
    for question in draft.get("questions", []):
        q = dict(question)
        q["figures"] = walk(q.get("figures", []))
        parts = []
        for part in q.get("parts", []):
            p = dict(part)
            p["figures"] = walk(p.get("figures", []))
            parts.append(p)
        q["parts"] = parts
        questions.append(q)
    draft = dict(draft)
    draft["questions"] = questions
    draft["frontMatterFigures"] = walk(draft.get("frontMatterFigures", []))
    draft["assetsResolved"] = enriched_total
    return draft
