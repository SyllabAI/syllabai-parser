"""Pair detection + pairing-proposal generation for corpus_ops intake (T-C16).

The heuristics are best-effort convenience; the operator confirm step is the actual
pairing authority (design §11 — a high match score never bypasses a confirm). Exam
identity is NEVER inferred from document content (Past-Papers AGENT.md rule 2:
"Never infer or silently repair ambiguous paper/session identity").

Proposals mutate nothing. Session names come from the operator mapping CSV when
given, else provisional UNIDENTIFIED-%03d folders fixed later by `rename`.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from manifest import now_utc, sha256_file

QP_TOKENS = ("question paper", "questionpaper", "qp")
MS_TOKENS = ("mark scheme", "markscheme", "ms")
UNIDENTIFIED_PREFIX = "UNIDENTIFIED"
SIMILARITY_THRESHOLD = 0.85


@dataclass
class ProposedPair:
    qp_file: str
    ms_file: str | None
    similarity: float
    session_name: str  # mapped name or provisional UNIDENTIFIED-###


@dataclass
class PairingProposal:
    raw_folder: str
    generated_at_utc: str
    pairs: list[ProposedPair] = field(default_factory=list)
    unpaired: list[dict] = field(default_factory=list)  # {file, kind, reason}
    dropped_duplicates: list[str] = field(default_factory=list)  # dup filenames
    duplicate_of: dict[str, str] = field(default_factory=dict)  # dup -> kept file


def normalize(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", " ", stem).strip()


def classify(name: str) -> str | None:
    n = normalize(name)
    # Longest, most explicit tokens first so 'ms' inside 'marks scheme' can't misfire.
    for token in ("question paper", "questionpaper", "mark scheme", "markscheme"):
        if token in n:
            return "QP" if token.startswith("quest") else "MS"
    if re.search(r"\bqp\b", n):
        return "QP"
    if re.search(r"\bms\b", n):
        return "MS"
    return None


def similarity_key(name: str) -> str:
    """Normalized name with the doc-type token removed — the pairing similarity basis."""
    n = normalize(name)
    for token in ("question paper", "questionpaper", "mark scheme", "markscheme", "qp", "ms"):
        n = re.sub(rf"(^| ){re.escape(token)}( |$)", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def read_mapping(path: Path) -> dict[str, str]:
    """CSV with header `filename,session` — the operator's authoritative session names."""
    mapping: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or {"filename", "session"} - set(reader.fieldnames):
            raise ValueError("mapping CSV must have header: filename,session")
        for row in reader:
            fn = (row.get("filename") or "").strip()
            sn = (row.get("session") or "").strip()
            if fn and sn:
                mapping[fn] = sn
    return mapping


def propose(raw_folder: Path, mapping: dict[str, str] | None = None) -> PairingProposal:
    """Scan a raw conversion-output folder and emit a pairing proposal. Read-only."""
    if not raw_folder.is_dir():
        raise NotADirectoryError(f"raw folder not found: {raw_folder}")
    mapping = mapping or {}

    md_files = sorted(p.name for p in raw_folder.glob("*.md") if p.is_file())

    # Duplicate documents are recorded, never silently ignored (design §4 step 7).
    hashes: dict[str, str] = {}
    dropped: list[str] = []
    duplicate_of: dict[str, str] = {}
    for name in md_files:
        digest = sha256_file(raw_folder / name)
        if digest in hashes:
            dropped.append(name)
            duplicate_of[name] = hashes[digest]
        else:
            hashes[digest] = name
    unique_files = [n for n in md_files if n not in duplicate_of]

    qps = [n for n in unique_files if classify(n) == "QP"]
    mss = [n for n in unique_files if classify(n) == "MS"]

    pairs: list[ProposedPair] = []
    used_ms: set[str] = set()
    provisional_i = 0

    for qp in qps:
        qp_key = similarity_key(qp)
        best, best_ratio = None, 0.0
        for ms in mss:
            if ms in used_ms:
                continue
            ratio = 1.0 if similarity_key(ms) == qp_key else _ratio(qp_key, similarity_key(ms))
            if ratio > best_ratio:
                best, best_ratio = ms, ratio
        paired = best if best is not None and best_ratio >= SIMILARITY_THRESHOLD else None
        if paired:
            used_ms.add(paired)
        if qp in mapping:
            session = mapping[qp]
        elif paired and paired in mapping:
            session = mapping[paired]
        else:
            provisional_i += 1
            session = f"{UNIDENTIFIED_PREFIX}-{provisional_i:03d}"
        pairs.append(ProposedPair(qp_file=qp, ms_file=paired, similarity=round(best_ratio, 4),
                                  session_name=session))

    unpaired = [
        {"file": ms, "kind": "MS", "reason": "no QP candidate above threshold"}
        for ms in mss if ms not in used_ms
    ] + [
        {"file": n, "kind": "UNCLASSIFIED", "reason": "filename carries no QP/MS token"}
        for n in unique_files if classify(n) is None
    ]

    return PairingProposal(
        raw_folder=str(raw_folder),
        generated_at_utc=now_utc(),
        pairs=pairs,
        unpaired=unpaired,
        dropped_duplicates=dropped,
        duplicate_of=duplicate_of,
    )


def _ratio(a: str, b: str) -> float:
    import difflib

    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(a=a, b=b).ratio()
