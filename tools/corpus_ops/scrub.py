"""Grammar-aware, subtractive reference-removal engine for corpus_ops scrub (T-C16).

Verified corpus reality (ratified design §5): the image reference IS the single-line
center-div island
    <div style='text-align: center;'><img src='assets/crop_1_<ts>.png' alt='OCR图片'/></div>
so island removal is whole-line removal. A scrub that would need to edit *within*
such a line has mis-matched and must fail instead — never a partial edit.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ISLAND_RE = re.compile(
    r"^<div[^>]*>\s*<img\s+[^>]*?src=(?P<q>['\"])(?P<src>[^'\"]+)(?P=q)[^>]*/?>\s*</div>\s*$",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s'\")<>]+")


@dataclass
class Deletion:
    session: str
    asset_filename: str
    operator_note: str = ""


@dataclass
class ScrubPlan:
    deletions: list[Deletion] = field(default_factory=list)
    reference_removals: dict[str, list[str]] = field(default_factory=dict)  # file -> lines desc
    batch_id: str = ""


@dataclass
class ScrubError(Exception):
    """Fail-closed error carrying the operator-facing ledger."""

    message: str
    ledger: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover
        if self.ledger:
            return self.message + "\n" + "\n".join(self.ledger)
        return self.message


def read_deletions_csv(path: Path) -> list[Deletion]:
    out: list[Deletion] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"session", "asset_filename"}
        if not reader.fieldnames or required - set(reader.fieldnames):
            raise ScrubError("deletions CSV must have header: session,asset_filename[,operator_note]")
        for row in reader:
            s = (row.get("session") or "").strip()
            f = (row.get("asset_filename") or "").strip()
            if not s or not f:
                raise ScrubError(f"deletion row missing session/asset_filename: {row!r}")
            out.append(Deletion(session=s, asset_filename=f,
                                operator_note=(row.get("operator_note") or "").strip()))
    if not out:
        raise ScrubError("deletions CSV is empty — refuse to run a no-op scrub batch")
    return out


def collect_staged(paper_dir: Path) -> list[Deletion]:
    """The staging convention: the operator moved unwanted files into
    <session>/assets/_deleted/; scrub collects them as deletion records."""
    out: list[Deletion] = []
    for session_dir in sorted(p for p in paper_dir.iterdir() if p.is_dir()):
        staged = session_dir / "assets" / "_deleted"
        if not staged.is_dir():
            continue
        for f in sorted(staged.iterdir()):
            if f.is_file():
                out.append(Deletion(session=session_dir.name, asset_filename=f.name))
    if not out:
        raise ScrubError("no staged deletions found under any <session>/assets/_deleted/")
    return out


def batch_id_for(deletions: list[Deletion]) -> str:
    import hashlib

    canonical = "\n".join(
        f"{d.session}\x1f{d.asset_filename}" for d in sorted(deletions, key=lambda x: (x.session, x.asset_filename))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def is_pure_island_line(line: str) -> bool:
    return bool(ISLAND_RE.match(line.strip()))


def find_asset_refs(text: str) -> list[dict]:
    """Every image reference in a markdown document, island-shaped or not."""
    refs: list[dict] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = ISLAND_RE.match(line.strip())
        if m:
            refs.append({"line_no": i, "src": m.group("src"), "island": True, "line": line})
            continue
        for match in re.finditer(
            r"(?:!\[[^\]]*\]\((?P<md>[^)\s]+)\))|(?:<img\s+[^>]*?src=(?P<q>['\"])(?P<img>[^'\"]+)(?P=q))",
            line,
        ):
            src = match.group("md") or match.group("img")
            refs.append({"line_no": i, "src": src, "island": False, "line": line})
    return refs


def remove_references(
    text: str, *, saved_as: str, original_url: str | None, doc_name: str
) -> tuple[str, int, list[str]]:
    """Remove every reference to the asset. Subtractive, whole-line, fail-closed.

    Match rule (design §5): exact relative-path match (`assets/<saved_as>`) with
    original-URL fallback for pre-rewrite files. Returns (new_text, removed_count,
    problems) — problems non-empty means a reference exists in a NON-island line and
    the caller must abort the whole batch (no partial edits, ever).
    """
    targets = {f"assets/{saved_as}"}
    if original_url:
        targets.add(original_url)
    removed = 0
    problems: list[str] = []
    out_lines: list[str] = []
    for i, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.rstrip("\r\n")
        src = None
        m = ISLAND_RE.match(stripped.strip())
        if m:
            src = m.group("src")
        else:
            for ref in find_asset_refs(stripped):
                if ref["src"] in targets:
                    src = None
                    problems.append(
                        f"{doc_name}:{i}: reference to {ref['src']} found OUTSIDE a pure "
                        f"image-island line — refusing partial in-line edit (ratified design §5)"
                    )
                    break
        if src is not None and src in targets:
            removed += 1
            continue  # whole-line removal — the island dies, nothing else is touched
        out_lines.append(line)
    return "".join(out_lines), removed, problems


def orphan_scan(md_by_session: dict[str, dict[str, str]],
                manifest: dict,
                prior_removed_urls: dict[str, set[str]]) -> list[str]:
    """Post-scrub honesty pass (design §5 step 3): any remaining image reference with
    neither a file on disk nor a removal record is a hard FAIL with the full ledger."""
    ledger: list[str] = []
    for session, docs in sorted(md_by_session.items()):
        removed_urls = prior_removed_urls.get(session, set()) | _ops_removed(manifest, session)
        images = manifest.get("sessions", {}).get(session, {}).get("images", {})
        saved_on_disk = {v.get("saved_as") for v in images.values()}
        for doc_name, text in sorted(docs.items()):
            for ref in find_asset_refs(text):
                src = ref["src"]
                if src.startswith("http://") or src.startswith("https://"):
                    if src not in removed_urls:
                        ledger.append(
                            f"{session}/{doc_name}:{ref['line_no']}: remote ref {src} has no "
                            f"file and no removal record (never downloaded, never scrubbed)"
                        )
                else:
                    name = src.rsplit("/", 1)[-1]
                    if name not in saved_on_disk and src not in removed_urls:
                        ledger.append(
                            f"{session}/{doc_name}:{ref['line_no']}: local ref {src} has no "
                            f"manifest file and no removal record"
                        )
    return ledger


def _ops_removed(manifest: dict, session: str) -> set[str]:
    from manifest import removed_urls_for_session

    return removed_urls_for_session(manifest, session)
