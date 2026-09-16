"""corpus_ops — Corpus Acquisition & Organization Tooling (Stage A/A′), T-C16.

Commands:
    intake   retro image rescue from already-converted markdown + pair organization
             into the Past-Papers per-session layout (operator-confirmed pairing;
             exam identity never inferred from content — Past-Papers AGENT.md rule 2)
    scrub    deletion-manifest-driven reference removal (grammar-aware, subtractive,
             fail-closed, post-pass orphan detection)
    verify   read-only manifest<->filesystem agreement checks
    rename   provisional UNIDENTIFIED-* sessions fixed via proposal/confirm

Design: SyllabAI/syllabai `CORPUS_OPS_TOOLING_DESIGN.md` (ratified 2026-09-17, §12).
Exit codes: 0 all gates green · 1 any FAIL-class finding · 2 usage error.
Deterministic, stdlib-only, Python 3.10+. `--dry-run` exists for every mutating
command and prints the exact planned mutation set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import downloader  # noqa: E402
import manifest as mf  # noqa: E402
import pairing  # noqa: E402
import scrub as scrub_mod  # noqa: E402

ISLAND_SRC_RE = re.compile(
    r"<img\s+[^>]*?src=(?P<q>['\"])(?P<src>[^'\"]+)(?P=q)", re.IGNORECASE
)
MD_IMG_RE = re.compile(r"!\[[^\]]*\]\((?P<src>[^)\s]+)\)")

# Test seam: a fake transport injected by test_corpus_ops.py (never set in production).
_opener_override = None


# ------------------------------------------------------------------ helpers

def _fail(msg: str, code: int = 1) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return code


def _crop_filename_from_url(url: str) -> str:
    """Original OCR crop filename from the URL path (e.g. crop_1_1789041656774.png)."""
    path = urllib.parse.urlsplit(url).path
    name = Path(urllib.parse.unquote(path)).name
    if not name:
        raise ValueError(f"cannot derive a filename from URL: {url}")
    return name


def extract_image_urls(text: str) -> list[str]:
    """Every remote image URL referenced by a markdown document (islands first-class,
    plain markdown image syntax second)."""
    urls: list[str] = []
    for m in ISLAND_SRC_RE.finditer(text):
        src = m.group("src")
        if src.startswith("http://") or src.startswith("https://"):
            urls.append(src)
    for m in MD_IMG_RE.finditer(text):
        src = m.group("src")
        if src.startswith("http://") or src.startswith("https://"):
            urls.append(src)
    return list(dict.fromkeys(urls))


def rewrite_urls(text: str, url_to_local: dict[str, str]) -> tuple[str, int]:
    """Rewrite remote image URLs to local relative assets/ paths (design §4 step 5)."""
    count = 0
    def _sub_island(m):
        nonlocal count
        local = url_to_local.get(m.group("src"))
        if local:
            count += 1
            return m.group(0).replace(m.group("src"), local)
        return m.group(0)
    def _sub_md(m):
        nonlocal count
        local = url_to_local.get(m.group("src"))
        if local:
            count += 1
            return m.group(0).replace(m.group("src"), local)
        return m.group(0)
    text = ISLAND_SRC_RE.sub(_sub_island, text)
    text = MD_IMG_RE.sub(_sub_md, text)
    return text, count


# ------------------------------------------------------------------ intake

def cmd_intake(args: argparse.Namespace) -> int:
    raw_folder = Path(args.raw_folder)
    corpus_root = Path(args.out)
    paper_dir = corpus_root / args.paper
    mapping = pairing.read_mapping(Path(args.mapping)) if args.mapping else {}

    proposal = pairing.propose(raw_folder, mapping)
    proposal_path = Path(args.out_proposal or "pairing-proposal.json")

    if not args.confirm:
        proposal_path.write_text(
            json.dumps({
                "raw_folder": proposal.raw_folder,
                "generated_at_utc": proposal.generated_at_utc,
                "pairs": [p.__dict__ for p in proposal.pairs],
                "unpaired": proposal.unpaired,
                "dropped_duplicates": proposal.dropped_duplicates,
                "duplicate_of": proposal.duplicate_of,
            }, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"pairing proposal written: {proposal_path} "
              f"({len(proposal.pairs)} pairs, {len(proposal.unpaired)} unpaired, "
              f"{len(proposal.dropped_duplicates)} duplicates) — nothing mutated; "
              f"re-run with --confirm {proposal_path.name}")
        return 0

    # ---- confirmed run -------------------------------------------------------
    with open(args.confirm, "r", encoding="utf-8") as fh:
        confirmed = json.load(fh)
    if confirmed.get("raw_folder") != str(raw_folder):
        return _fail(f"proposal was generated for {confirmed.get('raw_folder')!r}, "
                     f"not {str(raw_folder)!r}")

    planned = []
    for p in confirmed["pairs"]:
        planned.append(f"create session {p['session_name']!r} <- {p['qp_file']}"
                       f" + {p['ms_file'] or '(no MS)'}")
    if args.dry_run:
        print("DRY RUN — planned mutations:")
        for line in planned:
            print(f"  {line}")
        return 0

    existing = mf.load_manifest(paper_dir)
    m = mf.ensure_v11(existing) if existing else mf.new_manifest(args.paper)
    if existing:
        m["generated_at_utc"] = mf.now_utc()

    intake_detail = {"sessions": [], "download_failures": 0}
    duplicate_of = confirmed.get("duplicate_of", {})

    for p in confirmed["pairs"]:
        session = p["session_name"]
        if session in m["sessions"]:
            return _fail(f"session {session!r} already exists in the manifest — "
                         f"refusing to overwrite (fail-closed)")
        session_dir = paper_dir / session
        assets_dir = session_dir / "assets"
        if session_dir.exists():
            return _fail(f"session folder already exists on disk: {session_dir}")

        qp_text = (raw_folder / p["qp_file"]).read_text(encoding="utf-8")
        ms_text = (raw_folder / p["ms_file"]).read_text(encoding="utf-8") if p["ms_file"] else None

        urls = extract_image_urls(qp_text) + (extract_image_urls(ms_text) if ms_text else [])
        urls = list(dict.fromkeys(urls))

        results = downloader.download_all(
            urls, opener=_opener_override, concurrency=args.concurrency,
            per_host_min_interval=args.per_host_interval,
            timeout=args.timeout, max_attempts=args.retries,
            backoff_seconds=args.backoff,
        )

        # collision rule (design §4 step 6, ratified): identical bytes -> one asset;
        # different bytes under one filename -> hard FAIL, never a silent overwrite.
        saved_by_url: dict[str, str] = {}
        saved_hashes: dict[str, str] = {}
        collisions: list[str] = []
        for url, res in results.items():
            if not res.ok:
                continue  # failure recorded below; reference keeps its URL (honest)
            fname = _crop_filename_from_url(url)
            digest = mf.sha256_bytes(res.data)
            prior = saved_hashes.get(fname)
            if prior is not None:
                if prior == digest:
                    saved_by_url[url] = fname  # dedupe: identical bytes, one asset
                    continue
                collisions.append(f"{fname}: two distinct payloads ({url} vs prior)")
                continue
            saved_hashes[fname] = digest
            saved_by_url[url] = fname

        if collisions:
            for c in collisions:
                print(f"FAIL: asset filename collision — {c}", file=sys.stderr)
            return 1

        if not args.dry_run:
            assets_dir.mkdir(parents=True, exist_ok=True)

        images: dict[str, dict] = {}
        referenced_by: dict[str, set[str]] = {}
        for url, fname in saved_by_url.items():
            res = results[url]
            target = assets_dir / fname
            target.write_bytes(res.data)
            w, h = res.dimensions if res.dimensions else (None, None)
            images[url] = {
                "saved_as": fname,
                "bytes": len(res.data),
                "format": res.mime.split("/")[-1] if "/" in res.mime else res.mime,
                "mime": res.mime,
                "width_px": w,
                "height_px": h,
                "sha256": mf.sha256_bytes(res.data),
            }
        for url in images:
            if url in extract_image_urls(qp_text):
                referenced_by.setdefault(url, set()).add("QP.md")
            if ms_text and url in extract_image_urls(ms_text):
                referenced_by.setdefault(url, set()).add("MS.md")
        for url, refs in referenced_by.items():
            images[url]["referenced_by"] = sorted(refs)

        url_to_local = {url: f"assets/{img['saved_as']}" for url, img in images.items()}
        qp_new, n_qp = rewrite_urls(qp_text, url_to_local)
        ms_new, n_ms = (rewrite_urls(ms_text, url_to_local) if ms_text is not None else (None, 0))

        qp_path = session_dir / "QP.md"
        qp_path.write_text(qp_new, encoding="utf-8")
        docs = {
            "QP": {
                "original_name": p["qp_file"],
                "path": "QP.md",
                "sha256": mf.sha256_file(qp_path),
                "size": qp_path.stat().st_size,
            }
        }
        if ms_new is not None:
            ms_path = session_dir / "MS.md"
            ms_path.write_text(ms_new, encoding="utf-8")
            docs["MS"] = {
                "original_name": p["ms_file"],
                "path": "MS.md",
                "sha256": mf.sha256_file(ms_path),
                "size": ms_path.stat().st_size,
            }

        failures = [
            res.to_failure_record(session, mf.now_utc())
            for res in results.values() if not res.ok
        ]
        m["download_failures"].extend(failures)
        intake_detail["download_failures"] += len(failures)

        m["sessions"][session] = {
            "documents": docs,
            "image_count": len(images),
            "images": images,
        }
        intake_detail["sessions"].append(
            {"session": session, "images_downloaded": len(images),
             "references_rewritten": n_qp + n_ms, "download_failures": len(failures)}
        )

    for dup in confirmed.get("dropped_duplicates", []):
        if dup not in m["dropped_duplicates"]:
            m["dropped_duplicates"].append(dup)

    m["ops_log"].append(mf.new_ops_entry(
        "intake",
        f"intake from {proposal.raw_folder}: {len(intake_detail['sessions'])} sessions, "
        f"{sum(s['images_downloaded'] for s in intake_detail['sessions'])} images, "
        f"{intake_detail['download_failures']} recorded download failures",
        per_session={s["session"]: s for s in intake_detail["sessions"]},
        tool="corpus_ops intake",
    ))
    mf.dump_manifest(m, paper_dir)
    print(f"intake complete: {len(intake_detail['sessions'])} sessions under {paper_dir} "
          f"({intake_detail['download_failures']} recorded failures, "
          f"{len(m['dropped_duplicates'])} duplicate documents on record)")
    return 0


# ------------------------------------------------------------------ scrub

def cmd_scrub(args: argparse.Namespace) -> int:
    paper_dir = Path(args.corpus_root) / args.paper
    m = mf.load_manifest(paper_dir)
    if m is None:
        return _fail(f"no MANIFEST.json under {paper_dir} — scrub refuses to operate "
                     f"without the manifest (fail-closed)")
    m = mf.ensure_v11(m)

    if args.deletions and args.from_staging:
        return _fail("usage error: --deletions and --from-staging are mutually exclusive", 2)
    if args.deletions:
        deletions = scrub_mod.read_deletions_csv(Path(args.deletions))
    elif args.from_staging:
        deletions = scrub_mod.collect_staged(paper_dir)
    else:
        return _fail("usage error: scrub needs --deletions CSV or --from-staging", 2)

    batch_id = scrub_mod.batch_id_for(deletions)
    prior_batches = {e.get("batch_id") for e in m.get("ops_log", [])}
    if batch_id in prior_batches and not args.idempotent:
        return _fail(f"batch {batch_id} was already applied (ops_log) — pass --idempotent "
                     f"to replay a recorded batch")

    # resolve every deletion BEFORE touching anything (fail-closed, all-or-nothing)
    resolutions: list[tuple[scrub_mod.Deletion, Path, str | None]] = []
    errors: list[str] = []
    for d in deletions:
        asset = paper_dir / d.session / "assets" / d.asset_filename
        staged = paper_dir / d.session / "assets" / "_deleted" / d.asset_filename
        if not asset.exists():
            if staged.exists():
                asset = staged  # staging convention: the operator already moved it
            elif args.idempotent and batch_id in prior_batches:
                continue  # recorded replay — already-scrubbed entries are expected
            else:
                errors.append(f"{d.session}/{d.asset_filename}: file already gone (double-scrub?)")
                continue
        original_url = None
        for url, img in m.get("sessions", {}).get(d.session, {}).get("images", {}).items():
            if img.get("saved_as") == d.asset_filename:
                original_url = url
                break
        resolutions.append((d, asset, original_url))
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"DRY RUN — batch {batch_id}: {len(resolutions)} removals")
        for d, _, url in resolutions:
            print(f"  {d.session}/{d.asset_filename} (url: {'yes' if url else 'unknown'})")
        return 0

    # compute ALL reference edits in memory first — an abort leaves zero writes behind
    session_docs: dict[str, dict[str, str]] = {}
    for d, _, _ in resolutions:
        if d.session in session_docs:
            continue
        session_dir = paper_dir / d.session
        session_docs[d.session] = {
            doc_name: (session_dir / doc_name).read_text(encoding="utf-8")
            for doc_name in ("QP.md", "MS.md") if (session_dir / doc_name).exists()
        }
    planned_writes: dict[tuple[str, str], str] = {}
    for d, _, original_url in resolutions:
        for doc_name, text in session_docs.get(d.session, {}).items():
            new_text, removed, problems = scrub_mod.remove_references(
                text, saved_as=d.asset_filename, original_url=original_url, doc_name=doc_name
            )
            if problems:
                for pr in problems:
                    print(f"FAIL: {pr}", file=sys.stderr)
                return 1
            planned_writes[(d.session, doc_name)] = new_text
            session_docs[d.session][doc_name] = new_text

    removed_urls_by_session: dict[str, list[str]] = {}
    for (session, doc_name), new_text in planned_writes.items():
        (paper_dir / session / doc_name).write_text(new_text, encoding="utf-8")
    for d, asset, original_url in resolutions:
        asset.unlink()  # the bytes are intentionally gone; the URL survives in ops_log
        if original_url:
            removed_urls_by_session.setdefault(d.session, []).append(original_url)

    # recompute checksums + image_count; nothing else in the manifest is touched
    for d, _, _ in resolutions:
        sess = m.get("sessions", {}).get(d.session)
        if not sess:
            continue
        m["sessions"][d.session]["images"] = {
            url: img for url, img in sess.get("images", {}).items()
            if img.get("saved_as") != d.asset_filename
        }
        m["sessions"][d.session]["image_count"] = len(m["sessions"][d.session]["images"])
        for half, doc in sess.get("documents", {}).items():
            p = paper_dir / d.session / f"{half}.md"
            if p.exists():
                doc["sha256"] = mf.sha256_file(p)
                doc["size"] = p.stat().st_size

    # orphan detection AFTER scrubbing (design §5 step 3) — hard FAIL with ledger
    md_by_session: dict[str, dict[str, str]] = {}
    for session in m.get("sessions", {}):
        docs = {}
        for doc_name in ("QP.md", "MS.md"):
            p = paper_dir / session / doc_name
            if p.exists():
                docs[doc_name] = p.read_text(encoding="utf-8")
        if docs:
            md_by_session[session] = docs
    from manifest import removed_urls_for_session

    prior_removed = {
        session: removed_urls_for_session(m, session)
        for session in m.get("sessions", {})
    }
    for d, _, url in resolutions:
        if url:
            prior_removed.setdefault(d.session, set()).add(url)
    ledger = scrub_mod.orphan_scan(md_by_session, m, prior_removed)
    if ledger:
        for line in ledger:
            print(f"FAIL (orphan): {line}", file=sys.stderr)
        return 1

    m["ops_log"].append(mf.new_ops_entry(
        "reference-scrub",
        f"scrub batch {batch_id}: {len(resolutions)} assets removed, references scrubbed "
        f"whole-island, checksums recomputed, orphan scan clean",
        batch_id=batch_id,
        per_session={
            s: {"removed_count": len(v), "removed_urls": v}
            for s, v in sorted(removed_urls_by_session.items())
        },
        operator_notes={d.asset_filename: d.operator_note
                        for d, _, _ in resolutions if d.operator_note},
        tool="corpus_ops scrub",
    ))
    mf.dump_manifest(m, paper_dir)
    print(f"scrub complete: batch {batch_id}, {len(resolutions)} assets removed, "
          f"orphan scan clean")
    return 0


# ------------------------------------------------------------------ verify

def cmd_verify(args: argparse.Namespace) -> int:
    paper_dir = Path(args.corpus_root) / args.paper
    m = mf.load_manifest(paper_dir)
    if m is None:
        return _fail(f"no MANIFEST.json under {paper_dir}")
    findings: list[dict] = []

    def add(level: str, check: str, detail: str, session: str | None = None) -> None:
        findings.append({"level": level, "check": check, "session": session, "detail": detail})

    sessions = m.get("sessions", {})
    for session, sess in sorted(sessions.items()):
        session_dir = paper_dir / session
        docs = sess.get("documents", {})
        # pair completeness (§6)
        for half in ("QP", "MS"):
            if half not in docs:
                add("FAIL", "pair-completeness", f"{half} missing", session)
        # manifest <-> filesystem agreement (§6)
        saved = set()
        for url, img in sess.get("images", {}).items():
            fname = img.get("saved_as")
            saved.add(fname)
            f = session_dir / "assets" / str(fname)
            if not f.exists():
                add("FAIL", "asset-exists", f"{fname} missing (ref {url[:80]}…)", session)
            elif mf.sha256_file(f) != img.get("sha256"):
                add("FAIL", "asset-checksum", f"{fname} sha256 mismatch", session)
            if img.get("mime") and fname:
                ext_ok = str(fname).lower().endswith(
                    "." + img["mime"].split("/")[-1].replace("jpeg", "jpg"))
                if not ext_ok:
                    add("WARN", "mime-vs-extension",
                        f"{fname} claims {img['mime']}", session)
            if img.get("mime") == "application/octet-stream":
                add("FAIL", "mime-sniff", f"{fname} is not a recognized image", session)
        on_disk = {p.name for p in (session_dir / "assets").glob("*") if p.is_file()} \
            if (session_dir / "assets").is_dir() else set()
        strays = on_disk - saved
        allowlist = set(sess.get("extra_assets_allowlist", []))
        for stray in sorted(strays - allowlist):
            add("FAIL", "asset-stray", f"unreferenced asset {stray}", session)
        # provisional identities (§6)
        if session.startswith(pairing.UNIDENTIFIED_PREFIX):
            add("WARN", "provisional-identity", "session still UNIDENTIFIED-*", session)

    # clean-readiness (§6): clean/ subtrees have valid reports; raw checksums agree
    for session, report_ref in sorted(m.get("clean", {}).items()):
        report_path = paper_dir / session / report_ref.get("report_ref", "clean/clean-report.json")
        if not report_path.exists():
            add("FAIL", "clean-report", f"{report_ref.get('report_ref')} missing", session)
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        sess = sessions.get(session, {})
        for half in ("QP", "MS"):
            clean_p = paper_dir / session / "clean" / f"{half}.md"
            if not clean_p.exists():
                add("FAIL", "clean-readiness", f"clean/{half}.md missing", session)
                continue
            if mf.sha256_file(clean_p) != report.get("clean", {}).get(f"{half.lower()}_sha256"):
                add("FAIL", "clean-checksum", f"clean/{half}.md != report", session)
            if mf.sha256_file(paper_dir / session / f"{half}.md") != \
                    report.get("raw", {}).get(f"{half.lower()}_sha256"):
                add("FAIL", "clean-raw-anchor", f"raw {half}.md drifted since the report", session)
            if sess.get("documents", {}).get(half, {}).get("sha256") and \
                    report.get("raw", {}).get(f"{half.lower()}_sha256") and \
                    sess["documents"][half]["sha256"] != report["raw"][f"{half.lower()}_sha256"]:
                add("FAIL", "clean-manifest-anchor",
                    f"report raw {half} sha != manifest", session)

    if args.json:
        print(json.dumps({"paper_dir": str(paper_dir), "findings": findings}, indent=1,
                         ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f['level']:4} {f['check']:24} {f['session'] or '-':16} {f['detail']}")
        fails = sum(1 for f in findings if f["level"] == "FAIL")
        warns = sum(1 for f in findings if f["level"] == "WARN")
        print(f"verify: {fails} FAIL, {warns} WARN, "
              f"{len(findings) - fails - warns} informational")
    return 1 if any(f["level"] == "FAIL" for f in findings) else 0


# ------------------------------------------------------------------ rename

def cmd_rename(args: argparse.Namespace) -> int:
    paper_dir = Path(args.corpus_root) / args.paper
    m = mf.load_manifest(paper_dir)
    if m is None:
        return _fail(f"no MANIFEST.json under {paper_dir}")
    m = mf.ensure_v11(m)
    with open(args.mapping, "r", encoding="utf-8-sig", newline="") as fh:
        import csv as _csv

        reader = _csv.DictReader(fh)
        required = {"from_session", "to_session"}
        if not reader.fieldnames or required - set(reader.fieldnames):
            return _fail("usage error: rename mapping CSV must have header "
                         "from_session,to_session", 2)
        renames = [((r.get("from_session") or "").strip(),
                    (r.get("to_session") or "").strip())
                   for r in reader]
    renames = [(a, b) for a, b in renames if a and b]

    proposals = []
    for src, dst in renames:
        if not src.startswith(pairing.UNIDENTIFIED_PREFIX):
            return _fail(f"rename only applies to provisional {pairing.UNIDENTIFIED_PREFIX}-* "
                         f"sessions; {src!r} is not provisional (fail-closed)")
        if src not in m.get("sessions", {}):
            return _fail(f"unknown session {src!r} in manifest")
        if (paper_dir / dst).exists() or dst in m.get("sessions", {}):
            return _fail(f"target session {dst!r} already exists")
        proposals.append((src, dst))

    if args.dry_run:
        print("DRY RUN — planned renames:")
        for src, dst in proposals:
            print(f"  {src} -> {dst}")
        return 0

    if args.confirm:
        with open(args.confirm, "r", encoding="utf-8") as fh:
            confirmed = json.load(fh)
        pairs = [(c["from_session"], c["to_session"]) for c in confirmed["renames"]]
        if set(pairs) != set(proposals):
            return _fail("confirmation does not match the current proposal")
    else:
        out = {"renames": [{"from_session": s, "to_session": d} for s, d in proposals]}
        Path(args.out_proposal or "rename-proposal.json").write_text(
            json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print("rename proposal written — re-run with --confirm <file> to execute")
        return 0

    new_sessions: dict = {}
    src_to_dst = dict(proposals)
    for key, val in m["sessions"].items():
        dst = src_to_dst.get(key)
        new_sessions[dst if dst else key] = val
    m["sessions"] = new_sessions
    for src, dst in proposals:
        (paper_dir / src).rename(paper_dir / dst)
    m["ops_log"].append(mf.new_ops_entry(
        "rename",
        f"renamed {len(proposals)} provisional session(s) after identity confirmation",
        renames=[{"from": s, "to": d} for s, d in proposals],
        tool="corpus_ops rename",
    ))
    mf.dump_manifest(m, paper_dir)
    print(f"rename complete: {len(proposals)} session(s)")
    return 0


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="corpus_ops", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("intake", help="retro image rescue + pair organization")
    p.add_argument("raw_folder")
    p.add_argument("-o", "--out", required=True, help="corpus root (e.g. Past-Papers/)")
    p.add_argument("--paper", default="paper 1")
    p.add_argument("--mapping", help="CSV header filename,session (operator-authoritative)")
    p.add_argument("--confirm", help="pairing-proposal.json from the read-only first run")
    p.add_argument("--out-proposal", help="where to write the proposal (default CWD)")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--per-host-interval", type=float, default=0.0)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--backoff", type=float, default=1.0)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_intake)

    p = sub.add_parser("scrub", help="deletion-driven reference removal (fail-closed)")
    p.add_argument("corpus_root")
    p.add_argument("--paper", default="paper 1")
    p.add_argument("--deletions", help="CSV header session,asset_filename[,operator_note]")
    p.add_argument("--from-staging", action="store_true",
                   help="collect <session>/assets/_deleted/ staged files")
    p.add_argument("--idempotent", action="store_true",
                   help="replay a batch id already recorded in ops_log")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_scrub)

    p = sub.add_parser("verify", help="read-only manifest<->filesystem agreement")
    p.add_argument("corpus_root")
    p.add_argument("--paper", default="paper 1")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("rename", help="fix provisional UNIDENTIFIED-* sessions")
    p.add_argument("corpus_root")
    p.add_argument("--paper", default="paper 1")
    p.add_argument("--mapping", help="CSV header from_session,to_session")
    p.add_argument("--confirm", help="rename-proposal.json from the first run")
    p.add_argument("--out-proposal")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_rename)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except scrub_mod.ScrubError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
