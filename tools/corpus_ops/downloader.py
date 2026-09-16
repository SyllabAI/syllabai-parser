"""Image downloader for corpus_ops intake (T-C16).

Same-second discipline inherited from `tools/ocr_batch`: every image URL referenced
by the markdown is fetched BEFORE the ~1-week signed-URL expiry, concurrently with a
per-host throttle, with retries that are *recorded, never silent* — a retry that
eventually succeeds carries its total attempts and per-attempt errors into the
manifest (the sync-dashboard lesson from syllabai-ops).

stdlib-only (mirrors the ocr_batch `api` backend discipline). The HTTP surface is an
injectable opener so tests run mocked, offline, deterministic.
"""

from __future__ import annotations

import concurrent.futures
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


# ---------------------------------------------------------------- MIME + dimensions

def sniff_mime(data: bytes) -> str:
    """MIME from magic bytes, never from the extension."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no payload
            i += 2
            continue
        if i + 4 > n:
            break
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 <= n:
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(w), int(h)
        i += 2 + seg_len
    return None


def image_dimensions(data: bytes, mime: str) -> tuple[int, int] | None:
    if mime == "image/png":
        return png_dimensions(data)
    if mime == "image/jpeg":
        return jpeg_dimensions(data)
    return None


# ---------------------------------------------------------------- fetch + record

@dataclass
class FetchResult:
    url: str
    ok: bool
    data: bytes = b""
    mime: str = "application/octet-stream"
    dimensions: tuple[int, int] | None = None
    attempts: list[dict] = field(default_factory=list)  # [{error_class, detail}]
    error_class: str | None = None
    detail: str | None = None

    def to_failure_record(self, session: str, timestamp: str) -> dict:
        return {
            "url": self.url,
            "session": session,
            "error_class": self.error_class,
            "detail": self.detail,
            "attempts": list(self.attempts),
            "attempt_count": len(self.attempts),
            "timestamp": timestamp,
        }


def classify_http_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"http-{exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return "timeout"
        return "url-error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "error"


def fetch_one(
    url: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
) -> FetchResult:
    """Fetch one URL with recorded retries. Backoff is honored when > 0 (tests pass 0)."""
    op = opener if opener is not None else urllib.request.build_opener()
    result = FetchResult(url=url, ok=False)
    for attempt in range(1, max_attempts + 1):
        try:
            with op.open(urllib.request.Request(url, method="GET"), timeout=timeout) as resp:
                result.data = resp.read()
            result.mime = sniff_mime(result.data)
            result.dimensions = image_dimensions(result.data, result.mime)
            result.ok = True
            return result
        except Exception as exc:  # noqa: BLE001 — recorded, classified, re-raised nowhere
            result.attempts.append(
                {"error_class": classify_http_error(exc), "detail": str(exc)[:300]}
            )
            if attempt < max_attempts and backoff_seconds > 0:
                time.sleep(backoff_seconds * attempt)
    result.error_class = result.attempts[-1]["error_class"] if result.attempts else "error"
    result.detail = result.attempts[-1]["detail"] if result.attempts else "unknown"
    return result


def download_all(
    urls: list[str],
    *,
    opener: urllib.request.OpenerDirector | None = None,
    concurrency: int = 8,
    per_host_min_interval: float = 0.0,
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
) -> dict[str, FetchResult]:
    """Concurrent fetch (default 8 workers) with per-host throttle.

    Per-host discipline: at most one in-flight request per host, spaced at least
    `per_host_min_interval` seconds apart (the signed-URL hosts are shared buckets).
    """
    if not urls:
        return {}
    host_locks: dict[str, object] = {}
    host_next: dict[str, float] = {}

    def _throttled_fetch(url: str) -> FetchResult:
        host = urllib.request.urlsplit(url).netloc
        if per_host_min_interval > 0:
            import threading

            lock = host_locks.setdefault(host, threading.Lock())
            with lock:
                wait = host_next.get(host, 0.0) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                out = fetch_one(
                    url,
                    opener=opener,
                    timeout=timeout,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                )
                host_next[host] = time.monotonic() + per_host_min_interval
                return out
        return fetch_one(
            url,
            opener=opener,
            timeout=timeout,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )

    ordered = list(dict.fromkeys(urls))  # deterministic, deduped, insertion order
    results: dict[str, FetchResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for url, res in zip(ordered, pool.map(_throttled_fetch, ordered)):
            results[url] = res
    return results
