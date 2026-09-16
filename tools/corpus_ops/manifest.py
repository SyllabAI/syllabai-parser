"""Deterministic MANIFEST.json reader/writer for corpus_ops (T-C16, schema v1.1).

Legacy compatibility contract (verified against `Past-Papers/paper 1/MANIFEST.json`,
2026-09-11…13 cycle): top-level keys
    paper, generated_at_utc, structure, notes, dropped_duplicates,
    download_failures, sessions, operator_cleanup, structural_repair,
    operator_cleanup_2
are canonical and never renamed or reshaped. `sessions` was ALWAYS a keyed object:
    session_id -> {documents: {MS|QP: {original_name, path, sha256}},
                   image_count, images: {url -> {saved_as, bytes, format, sha256,
                                                 referenced_by[]}}}
v1.1 adds additively: schema_version, ops_log[], clean{}, per-image
mime/width_px/height_px, per-document size. Nothing legacy is dropped on write.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

SCHEMA_VERSION = "1.1"
EPOCH_ENV = "CORPUS_OPS_EPOCH_UTC"  # test-only pin, mirrors the glmocr epoch trick

LEGACY_STRUCTURE = "<session>/QP.md + MS.md + assets/ ; sessions = exam sitting"

OPS_KINDS = (
    "intake",
    "image-cleanup",
    "structural-repair",
    "rename",
    "reference-scrub",
)


def now_utc() -> str:
    """Wall-clock UTC; pinned by CORPUS_OPS_EPOCH_UTC under tests for determinism."""
    pinned = os.environ.get(EPOCH_ENV)
    if pinned:
        return pinned
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: os.PathLike | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path(paper_dir: Path) -> Path:
    return paper_dir / "MANIFEST.json"


def load_manifest(paper_dir: Path) -> dict | None:
    """Load a paper manifest. Accepts legacy (no schema_version) and v1.1 files."""
    p = manifest_path(paper_dir)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def new_manifest(paper: str, notes: list[str] | None = None) -> dict:
    """A fresh v1.1 manifest with the legacy key set intact."""
    return {
        "paper": paper,
        "generated_at_utc": now_utc(),
        "structure": LEGACY_STRUCTURE,
        "notes": notes if notes is not None else [],
        "dropped_duplicates": [],
        "download_failures": [],
        "sessions": {},
        "schema_version": SCHEMA_VERSION,
        "ops_log": [],
        "clean": {},
    }


def ensure_v11(manifest: dict) -> dict:
    """Additively upgrade a loaded manifest to v1.1 (never touches legacy keys)."""
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    manifest.setdefault("ops_log", [])
    manifest.setdefault("clean", {})
    manifest.setdefault("dropped_duplicates", [])
    manifest.setdefault("download_failures", [])
    manifest.setdefault("sessions", {})
    return manifest


def is_legacy(manifest: dict) -> bool:
    return "schema_version" not in manifest


def new_ops_entry(kind: str, description: str, **detail) -> dict:
    if kind not in OPS_KINDS:
        raise ValueError(f"unknown ops_log kind: {kind!r}")
    entry = {"kind": kind, "date_utc": now_utc(), "description": description}
    entry.update(detail)
    return entry


def removed_urls_for_session(manifest: dict, session: str) -> set[str]:
    """Every URL proven removed for a session across legacy operator_cleanup* blocks
    and the general ops_log — the honesty ledger orphan detection is checked against."""
    removed: set[str] = set()
    for key in ("operator_cleanup", "operator_cleanup_2"):
        block = manifest.get(key)
        if isinstance(block, dict):
            for url in block.get("removed_images", {}).get(session, []):
                removed.add(url)
    for entry in manifest.get("ops_log", []):
        detail = entry.get("per_session", {}).get(session, {})
        if isinstance(detail, dict):
            removed.update(detail.get("removed_urls", []))
    return removed


def dump_manifest(manifest: dict, paper_dir: Path) -> Path:
    """Deterministic writer: insertion-ordered, indent=1 (legacy formatting), UTF-8.

    Same inputs (+pinned epoch) -> byte-identical output; enforced by test.
    """
    paper_dir.mkdir(parents=True, exist_ok=True)
    p = manifest_path(paper_dir)
    text = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    p.write_text(text, encoding="utf-8")
    return p
