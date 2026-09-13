#!/usr/bin/env python3
"""GLM-OCR batch automation for SyllabAI — PDF QP/MS -> markdown + image assets.

This tool automates the ONE step the parser pipeline deliberately treats as an
external input: producing GLM-OCR markdown (with image assets saved at export
time) from the official PDF question papers / mark schemes.

    PDF (QP/MS) -> GLM-OCR -> <stem>.md + assets/crop_*.png + manifest.json
                                        |
                                        v
            existing pipeline (unchanged): GlmOcrMarkdownParser
                                        -> canonical -> QP/MS drafts

Two backends, same output conventions:

  api      POST {api-url} with model "glm-ocr" (the endpoint the ocr.z.ai
           website fronts). The service runs the full layout pipeline and
           returns markdown + crop-image URLs. Default endpoint:
           https://api.z.ai/api/paas/v4/layout_parsing
           (mainland: https://open.bigmodel.cn/api/paas/v4/layout_parsing)

  ollama   local Ollama (https://ollama.ai) running the glm-ocr model
           (default tag glm-ocr:latest). Native /api/generate endpoint with
           per-page rasterized images and the documented document-parsing
           prompt ("Text Recognition:"). Model-only inference: NO layout
           stage, so no figure crops — the manifest records that honestly.

Design rules inherited from the parser repo:

  * Markdown bytes are saved exactly as received (byte-faithful); the
    downstream documentId is SHA-256(checksum + engine + engineVersion), so
    this tool never reflows, renormalizes or rewraps content.
  * Images are downloaded THE SAME SECOND they are referenced. Signed crop
    URLs expire (the current GLM-markdown-sample corpus lost every image to
    expiry); saving at export time is the documented mandatory lesson.
  * Fail loud: an empty/garbage OCR result for a paper fails that paper (and
    the run) with a clear error — nothing is silently fabricated.
  * Honesty sidecars: manifest.json maps every markdown image reference to a
    local asset (or records why it could not be fetched); provenance.json
    records engine, model, endpoint, request id, token usage and timings.
    Secrets are never written to disk.

The manually-OCRed website workflow remains fully supported and unchanged;
this tool is additive content-operations tooling.

Requires Python 3.10+, stdlib only for the api backend.
pypdfium2 is required only for: ollama backend with PDF inputs (local page
rasterization) and API page-count checks / >100-page chunking.
    pip install pypdfium2
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path

TOOL_NAME = "syllabai-parser ocr-batch"
TOOL_VERSION = "1.0.0"

DEFAULT_API_URL = "https://api.z.ai/api/paas/v4/layout_parsing"
DEFAULT_MODEL_API = "glm-ocr"
DEFAULT_MODEL_OLLAMA = "glm-ocr:latest"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
OCR_PROMPT = "Text Recognition:"  # documented document-parsing prompt (HF model card)

MAX_API_FILE_BYTES = 50 * 1024 * 1024       # API limit: PDF <= 50 MB
MAX_API_IMAGE_BYTES = 10 * 1024 * 1024      # API limit: image <= 10 MB
MAX_API_PAGES = 100                          # API limit: 100 pages per request

# Match the official SDK's vision token budget (glmocr/config.py):
# max_pixels = 14 * 14 * 4 * 1280 = 1,003,520 pixels per page image.
SDK_MAX_PIXELS = 14 * 14 * 4 * 1280
SDK_MIN_PIXELS = 112 * 112

DEFAULT_DPI = 200.0            # official SDK default pdf_dpi
DEFAULT_NUM_CTX = 8192         # HF reports: Ollama default 4096 can truncate output
DEFAULT_NUM_PREDICT = 8192

ENV_KEY_NAMES = ("ZAI_API_KEY", "ZHIPU_API_KEY", "GLMOCR_API_KEY")

IMG_TAG_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*['\"]([^'\"]+)['\"]", re.I)
MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)[^)]*\)")
BARE_IMG_RE = re.compile(
    r"https?://[^\s\"'<>)]+?\.(?:png|jpe?g|gif|webp|bmp)(?:\?[^\s\"'<>)]*)?", re.I)

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)


class PaperError(Exception):
    """Per-paper failure (fail-loud, recorded in manifest + summary)."""


def warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# bytes / image helpers
# --------------------------------------------------------------------------- #

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_mime(data: bytes) -> str:
    for magic, mime in MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def image_dims(data: bytes) -> tuple[int, int]:
    """Container-header dimensions (-1, -1 when unknown). Mirrors the intent of
    GlmOcrImageAssets: dims come from the bytes, never from the extension."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) > 24:
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    if data.startswith(b"\xff\xd8\xff"):
        i, n = 2, len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return (int.from_bytes(data[i + 7:i + 9], "big"),
                        int.from_bytes(data[i + 5:i + 7], "big"))
            i += 2 + seg_len
    return -1, -1


def png_encode_rgb(width: int, height: int, rgb: bytes) -> bytes:
    """Minimal deterministic PNG encoder (stdlib zlib), color type 2 (RGB)."""
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def bgr_to_rgb(buf: bytearray) -> bytearray:
    """C-speed channel swap via slice assignment (pdfium renders BGR)."""
    raw = bytes(buf)
    buf[0::3], buf[2::3] = raw[2::3], raw[0::3]
    return buf


# --------------------------------------------------------------------------- #
# PDF rasterization (pypdfium2, optional)
# --------------------------------------------------------------------------- #

def _require_pdfium():
    try:
        import pypdfium2 as pdfium
        return pdfium
    except ImportError as exc:
        raise PaperError(
            "pypdfium2 is required for this operation (local PDF page "
            "rasterization). Install it with:  pip install pypdfium2"
        ) from exc


def pdf_page_count(pdf_path: Path) -> int:
    pdfium = _require_pdfium()
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def render_page_png(pdf_path: Path, page_index: int, dpi: float,
                    max_pixels: int) -> bytes:
    """Rasterize one page (0-indexed) to PNG bytes under the vision pixel budget.

    The scale is capped so width*height <= max_pixels (SDK parity:
    max_pixels = 14*14*4*1280); a floor keeps tiny pages from being blown up.
    """
    pdfium = _require_pdfium()
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        w_pts, h_pts = page.get_size()
        scale = dpi / 72.0
        pixels = (w_pts * scale) * (h_pts * scale)
        if pixels > max_pixels and pixels > 0:
            scale *= (max_pixels / pixels) ** 0.5
        # pdfium rounds the bitmap size to integers, which can land a hair
        # above the budget — verify and step down once if needed
        for _ in range(3):
            bitmap = page.render(scale=scale)
            width, height = bitmap.width, bitmap.height
            if width * height <= max_pixels:
                break
            bitmap.close() if hasattr(bitmap, "close") else None
            scale *= (max_pixels / (width * height)) ** 0.5 * 0.9999
        else:
            raise PaperError("cannot fit page under the pixel budget")
        raw = ctypes.string_at(bitmap.buffer, bitmap.stride * height)
        mode = bitmap.mode
        if mode == "BGR":
            buf = bytearray(raw)
            rgb = bytes(bgr_to_rgb(buf))
        elif mode in ("BGRX", "BGRA"):
            # fast path for 4-byte layouts: pick B, G, R lanes
            b = raw[0::4]; g = raw[1::4]; r = raw[2::4]
            buf = bytearray(len(r) * 3)
            buf[0::3] = r; buf[1::3] = g; buf[2::3] = b
            rgb = bytes(buf)
        elif mode == "RGB":
            rgb = raw
        else:
            raise PaperError(
                f"unsupported pdfium bitmap mode {mode!r} — file a bug with "
                "the pypdfium2 version in use")
        return png_encode_rgb(width, height, rgb)
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    backend: str = "api"
    api_url: str = DEFAULT_API_URL
    api_key: str = ""
    api_key_source: str = "none"
    model: str = DEFAULT_MODEL_API
    ollama_url: str = DEFAULT_OLLAMA_URL
    num_ctx: int = DEFAULT_NUM_CTX
    dpi: float = DEFAULT_DPI
    max_pixels: int = SDK_MAX_PIXELS
    start_page: int | None = None          # 1-indexed inclusive, api backend
    end_page: int | None = None
    return_crop_images: bool = True
    retries: int = 5
    retry_base_seconds: float = 1.5
    retry_max_seconds: float = 60.0
    request_timeout: float = 600.0
    image_timeout: float = 90.0
    user_id: str = "syllabai-parser-ocr-batch"
    keep_remote_urls: bool = False         # True -> skip image downloads
    out_dir: Path = Path("ocr-out")
    verbose: bool = False

    def redacted(self) -> dict:
        """Config snapshot safe for provenance.json (never contains the key)."""
        return {
            "backend": self.backend,
            "apiUrl": self.api_url if self.backend == "api" else None,
            "apiKeySource": self.api_key_source,
            "model": self.model,
            "ollamaUrl": self.ollama_url if self.backend == "ollama" else None,
            "numCtx": self.num_ctx if self.backend == "ollama" else None,
            "dpi": self.dpi if self.backend == "ollama" else None,
            "maxPixels": self.max_pixels if self.backend == "ollama" else None,
            "startPage": self.start_page,
            "endPage": self.end_page,
            "returnCropImages": self.return_crop_images,
            "retries": self.retries,
            "requestTimeoutSeconds": self.request_timeout,
            "userId": self.user_id,
            "imageDownloadsSkipped": self.keep_remote_urls,
            "tool": f"{TOOL_NAME} {TOOL_VERSION}",
        }


def resolve_api_key(cli_value: str) -> tuple[str, str]:
    if cli_value:
        return cli_value, "--api-key (discouraged; prefer the env var)"
    for name in ENV_KEY_NAMES:
        value = os.environ.get(name)
        if value:
            return value, name
    raise PaperError(
        "no API key found. Set one of the environment variables "
        + ", ".join(ENV_KEY_NAMES)
        + " (get a key at https://open.bigmodel.cn or https://z.ai) "
        "or pass --api-key."
    )


# --------------------------------------------------------------------------- #
# HTTP plumbing
# --------------------------------------------------------------------------- #

_SSL_CTX = ssl.create_default_context()


def http_post_json(url: str, payload: dict, headers: dict, timeout: float,
                   cfg: Config) -> dict:
    """POST JSON with exponential backoff on retryable statuses."""
    body = json.dumps(payload).encode("utf-8")
    total = max(1, cfg.retries)
    last = "unknown error"
    for attempt in range(total):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            preview = ""
            try:
                preview = exc.read(500).decode("utf-8", "replace")
            except Exception:
                pass
            last = f"HTTP {exc.code}: {preview}"
            if exc.code in RETRY_STATUS and attempt < total - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                sleep_s = _backoff_seconds(cfg, attempt, retry_after)
                warn(f"HTTP {exc.code} (attempt {attempt + 1}/{total}), "
                     f"retrying in {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue
            raise PaperError(last) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"network error: {exc}"
            if attempt < total - 1:
                sleep_s = _backoff_seconds(cfg, attempt, None)
                warn(f"{last} (attempt {attempt + 1}/{total}), retrying in {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue
            raise PaperError(last) from exc
    raise PaperError(f"request failed after {total} attempts: {last}")


def _backoff_seconds(cfg: Config, attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), cfg.retry_max_seconds)
        except ValueError:
            pass
    return min(cfg.retry_base_seconds * (2 ** attempt), cfg.retry_max_seconds)


def http_get_bytes(url: str, timeout: float, attempts: int = 3) -> tuple[bytes, str]:
    last = "unknown error"
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": f"{TOOL_NAME}/{TOOL_VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code in (403, 404, 410):
                raise
            time.sleep(min(1.5 * (2 ** attempt), 20))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"network error: {exc}"
            time.sleep(min(1.5 * (2 ** attempt), 20))
    raise PaperError(f"image download failed after {attempts} attempts: {last} ({url})")


# --------------------------------------------------------------------------- #
# backend: Z.ai / Zhipu MaaS layout_parsing API
# --------------------------------------------------------------------------- #

@dataclass
class BackendResult:
    markdown: str
    page_markdowns: list[str] | None    # per-page pieces when the backend ran
                                        # page-by-page or a list response
    engine_name: str
    engine_variant: str
    response_meta: dict                 # provenance-safe response metadata
    crop_urls: list[str]
    warnings: list[str] = field(default_factory=list)


def _md_from_response(resp: dict) -> tuple[str, list[str]]:
    """Extract markdown from md_results (string or list), fail loud."""
    md = resp.get("md_results")
    if md is None:
        raise PaperError(
            "response has no md_results — endpoint/model mismatch? "
            f"response keys: {sorted(resp.keys())}")
    if isinstance(md, str):
        text = md
        pages = []
    elif isinstance(md, list):
        pieces = [str(p) for p in md]
        text = "\n\n".join(pieces)
        pages = pieces
    else:
        raise PaperError(f"md_results has unexpected type {type(md).__name__}")
    if not text.strip():
        raise PaperError(
            "md_results is empty — the service returned no content "
            "(check the input file; do not retry blindly)")
    return text, pages


def _extract_crop_urls(resp: dict, markdown: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        u = u.strip().strip("<>").strip()
        if u.startswith("http") and u not in seen:
            seen.add(u)
            urls.append(u)

    for m in IMG_TAG_RE.finditer(markdown):
        add(m.group(1))
    for m in MD_IMG_RE.finditer(markdown):
        add(m.group(1))
    for m in BARE_IMG_RE.finditer(markdown):
        add(m.group(0))
    # layout_details can carry crop URLs beyond the markdown (best-effort,
    # JSON-serialized scan keeps it shape-agnostic)
    try:
        blob = json.dumps(resp.get("layout_details") or "")
        for m in BARE_IMG_RE.finditer(blob):
            add(m.group(0).replace("\\/", "/"))
    except (TypeError, ValueError):
        pass
    return urls


def run_api_backend(pdf_path: Path, cfg: Config) -> BackendResult:
    """Send the PDF (or page chunks) to the layout_parsing endpoint."""
    data = pdf_path.read_bytes()
    if len(data) > MAX_API_FILE_BYTES:
        raise PaperError(
            f"PDF is {len(data) / 1e6:.1f} MB; the API accepts at most "
            f"{MAX_API_FILE_BYTES // (1024 * 1024)} MB (limit is the "
            "service's, not a tool choice)")

    # page plan: chunks of <=100 pages (API max). Needs pypdfium2 for the
    # count; without it, send whole file and let the service enforce limits.
    pages_total: int | None
    try:
        pages_total = pdf_page_count(pdf_path)
    except PaperError:
        pages_total = None

    ranges: list[tuple[int, int]] = []
    if pages_total is None:
        ranges.append((cfg.start_page, cfg.end_page))
    else:
        start = max(1, cfg.start_page or 1)
        end = min(pages_total, cfg.end_page or pages_total)
        if start > end:
            raise PaperError(f"page range {start}..{end} is empty "
                             f"(PDF has {pages_total} pages)")
        for chunk_start in range(start, end + 1, MAX_API_PAGES):
            ranges.append((chunk_start, min(chunk_start + MAX_API_PAGES - 1, end)))

    pieces: list[str] = []
    all_page_pieces: list[str] = []
    crop_urls: list[str] = []
    warnings: list[str] = []
    metas: list[dict] = []
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg.api_key}"}
    file_digest = sha256_hex(data)[:12]

    for (a, b) in ranges:
        payload: dict = {"model": cfg.model, "file": _pdf_data_uri(data)}
        if a is not None:
            payload["start_page_id"] = a
        if b is not None:
            payload["end_page_id"] = b
        if cfg.return_crop_images:
            payload["return_crop_images"] = True
        payload["request_id"] = _request_id(pdf_path, file_digest, a, b)
        payload["user_id"] = cfg.user_id

        resp = http_post_json(cfg.api_url, payload, headers,
                              cfg.request_timeout, cfg)
        text, page_pieces = _md_from_response(resp)
        pieces.append(text)
        if page_pieces:
            all_page_pieces.extend(page_pieces)
        crop_urls.extend(_extract_crop_urls(resp, text))
        metas.append(_api_meta(resp))

    markdown = "\n\n".join(p for p in pieces if p is not None)
    if not markdown.strip():
        raise PaperError("all page chunks returned empty markdown")

    if pages_total is not None and pages_total > MAX_API_PAGES:
        warnings.append(
            f"PDF has {pages_total} pages; processed as "
            f"{len(ranges)} chunks of <= {MAX_API_PAGES} pages")
    meta = metas[0] if metas else {}
    if len(metas) > 1:
        meta["chunkCount"] = len(metas)
        meta["chunkRequestIds"] = [m.get("requestId") for m in metas]

    return BackendResult(
        markdown=markdown,
        page_markdowns=all_page_pieces or None,
        engine_name="glm-ocr",
        engine_variant="layout-parsing-api",
        response_meta=meta,
        crop_urls=crop_urls,
        warnings=warnings,
    )


def _pdf_data_uri(data: bytes) -> str:
    return "data:application/pdf;base64," + base64.b64encode(data).decode("ascii")


def _request_id(pdf_path: Path, file_digest: str,
                start: int | None, end: int | None) -> str:
    """Deterministic per (file content, page range) — safe for tracing."""
    tag = f"p{start}-{end}" if start is not None else "all"
    return f"ocrbatch-{pdf_path.stem[:40].rstrip('.')}-{file_digest}-{tag}"


def _api_meta(resp: dict) -> dict:
    usage = resp.get("usage") or {}
    return {
        "responseId": resp.get("id"),
        "created": resp.get("created"),
        "model": resp.get("model"),
        "requestId": resp.get("request_id"),
        "usage": {
            "promptTokens": usage.get("prompt_tokens"),
            "completionTokens": usage.get("completion_tokens"),
            "totalTokens": usage.get("total_tokens"),
        } if usage else None,
        "dataInfo": resp.get("data_info"),
    }


# --------------------------------------------------------------------------- #
# backend: local Ollama (native /api/generate)
# --------------------------------------------------------------------------- #

def run_ollama_backend(pdf_path: Path, cfg: Config) -> BackendResult:
    """Rasterize pages locally, then OCR each page via Ollama's native
    /api/generate (recommended over the OpenAI-compatible endpoint for
    vision — see the official ollama-deploy guide). Model-only inference:
    there is no layout stage, so figure crops are NOT produced."""
    suffix = pdf_path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        raise PaperError(
            "ollama backend expects PDFs (it rasterizes per page); for a "
            "single image use the api backend or ollama directly")

    pages_total = pdf_page_count(pdf_path)
    if pages_total == 0:
        raise PaperError("PDF has zero pages")

    headers = {"Content-Type": "application/json"}
    pieces: list[str] = []
    warnings: list[str] = [
        "ollama route is model-only (no PP-DocLayoutV3 layout stage): no "
        "figure crops are produced; figures appear only if the model "
        "transcribes them as text"]
    for page_index in range(pages_total):
        png = render_page_png(pdf_path, page_index, cfg.dpi, cfg.max_pixels)
        if len(png) > MAX_API_IMAGE_BYTES:
            warnings.append(
                f"page {page_index + 1} renders to {len(png)} bytes "
                "(over the 10 MB image budget) — lower --dpi")
        payload = {
            "model": cfg.model,
            "prompt": OCR_PROMPT,
            "images": [base64.b64encode(png).decode("ascii")],
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_ctx": cfg.num_ctx,
                "num_predict": DEFAULT_NUM_PREDICT,
            },
        }
        resp = http_post_json(cfg.ollama_url.rstrip("/") + "/api/generate",
                              payload, headers, cfg.request_timeout, cfg)
        if "error" in resp:
            raise PaperError(f"ollama error on page {page_index + 1}: "
                             f"{resp['error']}")
        text = resp.get("response")
        if text is None:
            raise PaperError(
                f"ollama response missing 'response' field on page "
                f"{page_index + 1} — keys: {sorted(resp.keys())}")
        if not text.strip():
            raise PaperError(
                f"page {page_index + 1} returned EMPTY output. Known cause: "
                "context too small for a dense page — raise --num-ctx "
                "(e.g. 8192 or higher; model supports 128K)")
        pieces.append(text)

    markdown = "\n\n".join(pieces)
    meta = {
        "ollamaModel": cfg.model,
        "prompt": OCR_PROMPT,
        "pages": pages_total,
        "endpoint": "/api/generate (native)",
    }
    return BackendResult(markdown=markdown, page_markdowns=pieces,
                         engine_name="glm-ocr", engine_variant="ollama-generate",
                         response_meta=meta, crop_urls=[], warnings=warnings)


# --------------------------------------------------------------------------- #
# image assets — downloaded at export time (the mandatory lesson)
# --------------------------------------------------------------------------- #

def _safe_remote_name(url: str, index: int, content_type: str) -> str:
    """Derive the local asset name from the URL path (website convention:
    crop_<n>_<millis>.png). Falls back to a deterministic synthetic name."""
    from urllib.parse import unquote, urlsplit
    path = unquote(urlsplit(url).path)
    name = Path(path).name or ""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not name or name in (".", ".."):
        ext = _ext_for_mime(content_type)
        name = f"crop_{index + 1}{ext}"
    return name


def _ext_for_mime(content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
            "image/webp": ".webp"}.get(ct, ".bin")


def download_assets(crop_urls: list[str], assets_dir: Path,
                    cfg: Config) -> tuple[list[dict], list[dict]]:
    """Fetch every referenced crop image NOW. Returns (assets, unfetched).

    Signed crop URLs expire (~1 week in the audited corpus); a re-export that
    does not save images at export time loses them forever. This is the
    documented adapter-reconciliation lesson #1 implemented in code.
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict] = []
    unfetched: list[dict] = []
    used_names: set[str] = set()
    for index, url in enumerate(crop_urls):
        base = _safe_remote_name(url, index, "")
        name = base
        collision = 1
        while name in used_names:
            stem, dot, ext = base.rpartition(".")
            name = f"p{index + 1}_{stem or base}{dot or ''}{ext if dot else ''}"
            collision += 1
            if collision > 5:
                name = f"crop_{index + 1}{_ext_for_mime('')}"
                break
        used_names.add(name)
        target = assets_dir / name
        try:
            blob, content_type = http_get_bytes(url, cfg.image_timeout)
            if not blob:
                raise PaperError("empty body")
            target.write_bytes(blob)
            width, height = image_dims(blob)
            assets.append({
                "url": url,
                "localPath": f"assets/{name}",
                "sha256": sha256_hex(blob),
                "bytes": len(blob),
                "sniffedMime": sniff_mime(blob),
                "contentType": content_type,
                "width": width,
                "height": height,
            })
        except Exception as exc:  # noqa: BLE001 — recorded, never fatal
            unfetched.append({"url": url, "reason": str(exc)})
            warn(f"could not fetch {url}: {exc}")
    return assets, unfetched


# --------------------------------------------------------------------------- #
# per-paper orchestration + outputs
# --------------------------------------------------------------------------- #

def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                               sort_keys=False) + "\n", encoding="utf-8")


def process_paper(pdf_path: Path, cfg: Config) -> tuple[bool, dict]:
    """OCR one PDF into <out>/<stem>/. Returns (ok, summary-row)."""
    started = time.time()
    stem = pdf_path.stem
    out_dir = cfg.out_dir / stem
    timings: dict = {}

    row = {"file": str(pdf_path), "status": "FAILED", "outDir": str(out_dir)}
    try:
        data = pdf_path.read_bytes()
        source_sha = sha256_hex(data)

        # ---- OCR ----------------------------------------------------------
        t0 = time.time()
        if cfg.backend == "api":
            result = run_api_backend(pdf_path, cfg)
        else:
            result = run_ollama_backend(pdf_path, cfg)
        timings["ocrSeconds"] = round(time.time() - t0, 2)

        # ---- outputs ------------------------------------------------------
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{stem}.md"
        md_path.write_text(result.markdown, encoding="utf-8", newline="")

        pages_dir = None
        if result.page_markdowns and len(result.page_markdowns) > 1:
            pages_dir = out_dir / "pages"
            pages_dir.mkdir(exist_ok=True)
            for i, piece in enumerate(result.page_markdowns):
                (pages_dir / f"page_{i + 1:03d}.md").write_text(
                    piece, encoding="utf-8", newline="")

        assets: list[dict] = []
        unfetched: list[dict] = []
        if result.crop_urls and not cfg.keep_remote_urls:
            t1 = time.time()
            assets, unfetched = download_assets(
                result.crop_urls, out_dir / "assets", cfg)
            timings["assetDownloadSeconds"] = round(time.time() - t1, 2)
        elif result.crop_urls and cfg.keep_remote_urls:
            unfetched = [{"url": u, "reason": "downloads skipped (--keep-urls)"}
                         for u in result.crop_urls]

        md_bytes = md_path.read_bytes()
        manifest = {
            "manifestVersion": 1,
            "tool": f"{TOOL_NAME} {TOOL_VERSION}",
            "generatedAt": _utc_now(),
            "backend": cfg.backend,
            "engine": {
                "name": result.engine_name,
                "variant": result.engine_variant,
                "model": cfg.model,
            },
            "source": {
                "fileName": pdf_path.name,
                "sha256": source_sha,
                "bytes": len(data),
            },
            "markdown": {
                "fileName": md_path.name,
                "sha256": sha256_hex(md_bytes),
                "bytes": len(md_bytes),
                "origin": ("md_results-as-received" if cfg.backend == "api"
                           else "ollama /api/generate per-page, joined"),
                "pageCount": (len(result.page_markdowns)
                              if result.page_markdowns else 1),
                "pagesDir": "pages/" if pages_dir else None,
            },
            "assets": assets,
            "unfetchedAssets": unfetched,
            "warnings": result.warnings,
            "timings": timings,
            "note": ("markdown bytes are saved exactly as received; the "
                     "parser derives documentId from SHA-256(bytes)+engine+"
                     "engineVersion, so this file is the identity anchor"),
        }
        _write_json(out_dir / "manifest.json", manifest)

        provenance = {
            "provenanceVersion": 1,
            "tool": f"{TOOL_NAME} {TOOL_VERSION}",
            "generatedAt": _utc_now(),
            "config": cfg.redacted(),
            "response": result.response_meta,
            "timings": timings,
            "note": ("API key material is never written to disk; "
                     "apiKeySource names the env var or flag used"),
        }
        _write_json(out_dir / "provenance.json", provenance)

        row.update({
            "status": "OK",
            "pages": manifest["markdown"]["pageCount"],
            "assets": len(assets),
            "unfetched": len(unfetched),
            "mdBytes": len(md_bytes),
            "seconds": round(time.time() - started, 2),
        })
        if result.warnings:
            row["warnings"] = len(result.warnings)
        return True, row

    except Exception as exc:  # noqa: BLE001 — fail-loud per paper, keep going
        row.update({
            "status": "FAILED",
            "error": str(exc),
            "seconds": round(time.time() - started, 2),
        })
        # write a failure provenance so the run leaves durable evidence
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            _write_json(out_dir / "provenance.json", {
                "provenanceVersion": 1,
                "tool": f"{TOOL_NAME} {TOOL_VERSION}",
                "generatedAt": _utc_now(),
                "config": cfg.redacted(),
                "status": "FAILED",
                "error": str(exc),
            })
        except OSError:
            pass
        return False, row


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- #
# input collection
# --------------------------------------------------------------------------- #

def collect_inputs(raw_inputs: list[str]) -> list[Path]:
    """Files and/or directories -> sorted, de-duplicated PDF list."""
    pdfs: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            found = sorted(p for p in path.rglob("*")
                           if p.is_file() and p.suffix.lower() == ".pdf"
                           and not p.name.startswith("~$"))
            if not found:
                warn(f"no PDFs under {path}")
            pdfs.extend(found)
        elif path.is_file() and path.suffix.lower() == ".pdf":
            pdfs.append(path)
        else:
            raise PaperError(f"input not found or not a PDF: {raw}")
    out: list[Path] = []
    for p in pdfs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def print_summary(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    for r in rows:
        if r["status"] == "OK":
            print(f"OK      {Path(r['file']).name}  ->  {r['outDir']}")
            print(f"        pages={r.get('pages')} assets={r.get('assets')} "
                  f"unfetched={r.get('unfetched')} mdBytes={r.get('mdBytes')} "
                  f"({r.get('seconds')}s)")
        else:
            print(f"FAILED  {Path(r['file']).name}")
            print(f"        {r.get('error')}")
    print("=" * 78)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ocr_batch.py",
        description="Automate PDF QP/MS -> GLM-OCR markdown + image assets "
                    "(api backend = ocr.z.ai engine, ollama backend = local "
                    "model). The manually-OCRed website workflow stays "
                    "valid; this tool is additive.",
        epilog="examples:\n"
               "  export ZAI_API_KEY=sk-...\n"
               "  python3 ocr_batch.py paper.pdf -o out/                    # api\n"
               "  python3 ocr_batch.py papers/ -o out/ --backend ollama     # local\n"
               "  python3 ocr_batch.py paper.pdf -o out/ --start-page 1 --end-page 4\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+",
                   help="PDF files and/or directories containing PDFs")
    p.add_argument("-o", "--out", default="ocr-out", metavar="DIR",
                   help="output root (default: ./ocr-out)")
    p.add_argument("--backend", choices=("api", "ollama"), default="api",
                   help="api = Z.ai/Zhipu layout_parsing endpoint (default); "
                        "ollama = local Ollama glm-ocr")
    p.add_argument("--api-url", default=DEFAULT_API_URL, metavar="URL",
                   help=f"default: {DEFAULT_API_URL}")
    p.add_argument("--api-key", default="", metavar="KEY",
                   help="API key (prefer the env var; never written to disk)")
    p.add_argument("--model", default=None, metavar="NAME",
                   help=f"api default: {DEFAULT_MODEL_API}; "
                        f"ollama default: {DEFAULT_MODEL_OLLAMA}")
    p.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, metavar="URL",
                   help=f"default: {DEFAULT_OLLAMA_URL}")
    p.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX, metavar="N",
                   help="ollama context window (default 8192; raise if a "
                        "dense page returns empty output)")
    p.add_argument("--dpi", type=float, default=DEFAULT_DPI, metavar="N",
                   help="ollama rasterization DPI (default 200, SDK parity)")
    p.add_argument("--start-page", type=int, default=None, metavar="N",
                   help="1-indexed first page (api backend)")
    p.add_argument("--end-page", type=int, default=None, metavar="N",
                   help="1-indexed last page (api backend)")
    p.add_argument("--no-crop-images", action="store_true",
                   help="api backend: do not request crop images")
    p.add_argument("--keep-urls", action="store_true",
                   help="do NOT download crop images (discouraged: URLs expire)")
    p.add_argument("--retries", type=int, default=5, metavar="N",
                   help="per-request retry attempts (default 5)")
    p.add_argument("--timeout", type=float, default=600.0, metavar="S",
                   help="per-request timeout seconds (default 600)")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="process at most N PDFs (smoke tests)")
    p.add_argument("--dry-run", action="store_true",
                   help="list the PDFs that would be processed and exit")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        inputs = collect_inputs(args.inputs)
    except PaperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.limit is not None:
        inputs = inputs[:max(0, args.limit)]
    if not inputs:
        print("error: no input PDFs", file=sys.stderr)
        return 2

    cfg = Config(
        backend=args.backend,
        api_url=args.api_url,
        model=args.model or (DEFAULT_MODEL_API if args.backend == "api"
                             else DEFAULT_MODEL_OLLAMA),
        ollama_url=args.ollama_url,
        num_ctx=args.num_ctx,
        dpi=args.dpi,
        start_page=args.start_page,
        end_page=args.end_page,
        return_crop_images=not args.no_crop_images,
        retries=args.retries,
        request_timeout=args.timeout,
        keep_remote_urls=args.keep_urls,
        out_dir=Path(args.out).expanduser().resolve(),
        verbose=args.verbose,
    )

    if args.dry_run:
        print(f"dry run — {len(inputs)} PDF(s) would be processed "
              f"with backend={cfg.backend} into {cfg.out_dir}:")
        for p in inputs:
            print(f"  {p}")
        return 0

    if cfg.backend == "api":
        try:
            cfg.api_key, cfg.api_key_source = resolve_api_key(args.api_key)
        except PaperError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    print(f"{TOOL_NAME} {TOOL_VERSION}: {len(inputs)} PDF(s), "
          f"backend={cfg.backend}, out={cfg.out_dir}")

    rows: list[dict] = []
    failures = 0
    for index, pdf in enumerate(inputs, 1):
        print(f"[{index}/{len(inputs)}] {pdf.name}")
        ok, row = process_paper(pdf, cfg)
        rows.append(row)
        if ok:
            print(f"    ok  pages={row.get('pages')} assets={row.get('assets')}"
                  f" unfetched={row.get('unfetched')} ({row.get('seconds')}s)")
        else:
            failures += 1
            print(f"    FAILED: {row.get('error')}", file=sys.stderr)

    print_summary(rows)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())




