"""corpus_ops test suite (T-C16 §9) — mocked HTTP + fixture tree, no network, no keys.

Run: python3 tools/corpus_ops/test_corpus_ops.py
Mirrors the ocr_batch testing discipline (mocked IO, offline, deterministic).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clean_diff  # noqa: E402
import corpus_ops  # noqa: E402
import downloader  # noqa: E402
import manifest as mf  # noqa: E402
import pairing  # noqa: E402
import scrub as scrub_mod  # noqa: E402

EPOCH = "2026-09-17T00:00:00Z"


# ------------------------------------------------------------------ helpers

def png_bytes(w: int = 4, h: int = 3) -> bytes:
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def jpeg_bytes(w: int = 6, h: int = 2) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + sof + b"\xff\xd9"


class FakeOpener:
    """Offline opener: URL -> bytes | ('403', msg) | ('timeout', msg)."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    def open(self, req, timeout=None):  # noqa: ARG002 — signature-compatible
        url = req.full_url if hasattr(req, "full_url") else req
        self.calls.append(url)
        resp = self.responses[url]
        if isinstance(resp, tuple):
            code, msg = resp
            raise urllib.error.HTTPError(url, code, msg, {}, io.BytesIO(b""))
        return io.BytesIO(resp)


def island(fname: str) -> str:
    return f"<div style='text-align: center;'><img src='{fname}' alt='OCR图片'/></div>"


def write_deletions_csv(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    lines = ["session,asset_filename,operator_note"]
    for session, fname, note in rows:
        lines.append(f"{session},{fname},{note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_mapping_csv(path: Path, rows: list[tuple[str, str]]) -> Path:
    lines = ["filename,session"]
    for fn, session in rows:
        lines.append(f"{fn},{session}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class CorpusOpsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="corpus_ops_test_"))
        os.environ[mf.EPOCH_ENV] = EPOCH
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(os.environ.pop, mf.EPOCH_ENV, None)

    def make_raw(self, files: dict[str, str]) -> Path:
        raw = self.tmp / "raw"
        raw.mkdir(exist_ok=True)
        for name, text in files.items():
            (raw / name).write_text(text, encoding="utf-8")
        return raw

    def run_intake_proposal(self, raw: Path, mapping: Path | None = None) -> Path:
        proposal = self.tmp / "proposal.json"
        argv = ["intake", str(raw), "-o", str(self.tmp / "corpus"), "--out-proposal", str(proposal)]
        if mapping:
            argv += ["--mapping", str(mapping)]
        rc = corpus_ops.main(argv)
        self.assertEqual(rc, 0)
        return proposal

    def run_intake_confirm(self, raw: Path, proposal: Path, mapping: Path | None = None,
                           opener: FakeOpener | None = None) -> int:
        argv = ["intake", str(raw), "-o", str(self.tmp / "corpus"), "--confirm", str(proposal)]
        if mapping:
            argv += ["--mapping", str(mapping)]
        corpus_ops._opener_override = opener  # tests inject the fake transport
        try:
            return corpus_ops.main(argv)
        finally:
            corpus_ops._opener_override = None


# ------------------------------------------------------------------ pairing

class PairingTests(CorpusOpsTestBase):
    def test_classify_tokens(self):
        self.assertEqual(pairing.classify("January 2012 QP - Paper 1C.md"), "QP")
        self.assertEqual(pairing.classify("January 2012 MS - Paper 1C.md"), "MS")
        self.assertEqual(pairing.classify("June 2019 Question Paper 2.md"), "QP")
        self.assertEqual(pairing.classify("June 2019 Mark Scheme 2.md"), "MS")
        self.assertIsNone(pairing.classify("formula sheet.md"))

    def test_proposal_is_read_only_and_deterministic_names(self):
        raw = self.make_raw({
            "January 2012 QP - Paper 1C.md": "# QP\n" + island("https://h/crop_1_1.png"),
            "January 2012 MS - Paper 1C.md": "# MS\n",
            "loose page.md": "orphan",
        })
        before = sorted(p.name for p in raw.iterdir())
        proposal = self.run_intake_proposal(raw)
        self.assertEqual(sorted(p.name for p in raw.iterdir()), before)  # nothing mutated
        data = json.loads(proposal.read_text())
        self.assertEqual(len(data["pairs"]), 1)
        self.assertEqual(data["pairs"][0]["session_name"], "UNIDENTIFIED-001")
        self.assertEqual(data["pairs"][0]["similarity"], 1.0)
        self.assertEqual(data["unpaired"][0]["file"], "loose page.md")

    def test_mapping_is_authoritative_for_session_names(self):
        raw = self.make_raw({
            "January 2012 QP.md": "# QP",
            "January 2012 MS.md": "# MS",
        })
        mapping = write_mapping_csv(self.tmp / "m.csv", [("January 2012 QP.md", "2012-Jan")])
        data = json.loads(self.run_intake_proposal(raw, mapping).read_text())
        self.assertEqual(data["pairs"][0]["session_name"], "2012-Jan")

    def test_duplicates_recorded_not_ignored(self):
        raw = self.make_raw({"A QP.md": "# same", "B QP.md": "# same"})
        data = json.loads(self.run_intake_proposal(raw).read_text())
        self.assertEqual(data["dropped_duplicates"], ["B QP.md"])
        self.assertEqual(data["duplicate_of"]["B QP.md"], "A QP.md")


# ------------------------------------------------------------------ intake

class IntakeTests(CorpusOpsTestBase):
    def build_fixture(self):
        url_png = "https://host.example/crop_1_111.png"
        url_jpg = "https://host.example/crop_1_222.jpeg"
        qp = "# Physics\n" + island(url_png) + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        ms = "# MS\n" + island(url_jpg)
        raw = self.make_raw({
            "January 2012 QP - Paper 1C.md": qp,
            "January 2012 MS - Paper 1C.md": ms,
        })
        mapping = write_mapping_csv(self.tmp / "m.csv", [
            ("January 2012 QP - Paper 1C.md", "2012-Jan")])
        opener = FakeOpener({url_png: png_bytes(), url_jpg: jpeg_bytes()})
        return raw, mapping, opener, url_png, url_jpg

    def test_intake_happy_path_layout_and_manifest(self):
        raw, mapping, opener, url_png, url_jpg = self.build_fixture()
        proposal = self.run_intake_proposal(raw, mapping)
        self.assertEqual(self.run_intake_confirm(raw, proposal, mapping, opener), 0)
        session = self.tmp / "corpus" / "paper 1" / "2012-Jan"
        self.assertTrue((session / "QP.md").exists())
        self.assertTrue((session / "MS.md").exists())
        self.assertTrue((session / "assets" / "crop_1_111.png").exists())
        qp_text = (session / "QP.md").read_text(encoding="utf-8")
        self.assertIn("assets/crop_1_111.png", qp_text)
        self.assertNotIn("https://", qp_text)  # reference rewritten
        m = mf.load_manifest(self.tmp / "corpus" / "paper 1")
        self.assertEqual(m["schema_version"], "1.1")
        sess = m["sessions"]["2012-Jan"]
        self.assertEqual(sess["image_count"], 2)
        self.assertEqual(sess["documents"]["QP"]["original_name"], "January 2012 QP - Paper 1C.md")
        img = sess["images"][url_png]
        self.assertEqual(img["mime"], "image/png")
        self.assertEqual((img["width_px"], img["height_px"]), (4, 3))
        self.assertEqual(img["referenced_by"], ["QP.md"])
        self.assertEqual(sess["images"][url_jpg]["referenced_by"], ["MS.md"])
        self.assertIn("ops_log", m)
        self.assertEqual(m["ops_log"][-1]["kind"], "intake")
        # deterministic manifest: same input re-dumped byte-identical
        text1 = (self.tmp / "corpus" / "paper 1" / "MANIFEST.json").read_text()
        mf.dump_manifest(m, self.tmp / "corpus" / "paper 1")
        self.assertEqual((self.tmp / "corpus" / "paper 1" / "MANIFEST.json").read_text(), text1)

    def test_download_failure_recorded_and_reference_kept(self):
        url_ok = "https://host.example/crop_1_1.png"
        url_dead = "https://host.example/crop_1_2.png"
        raw = self.make_raw({
            "January 2012 QP.md": island(url_ok) + "\n" + island(url_dead),
            "January 2012 MS.md": "x",
        })
        opener = FakeOpener({url_ok: png_bytes(), url_dead: ("403", "expired")})
        proposal = self.run_intake_proposal(raw)
        self.assertEqual(self.run_intake_confirm(raw, proposal, None, opener), 0)
        session = self.tmp / "corpus" / "paper 1" / "UNIDENTIFIED-001"
        qp_text = (session / "QP.md").read_text(encoding="utf-8")
        self.assertIn("assets/crop_1_1.png", qp_text)
        self.assertIn(url_dead, qp_text)  # honest: unavailable keeps its URL reference
        m = mf.load_manifest(self.tmp / "corpus" / "paper 1")
        self.assertEqual(len(m["download_failures"]), 1)
        rec = m["download_failures"][0]
        self.assertEqual(rec["error_class"], "http-403")
        self.assertGreaterEqual(rec["attempt_count"], 1)

    def test_collision_different_bytes_same_filename_fails(self):
        u1 = "https://a.example/crop_1_1.png"
        u2 = "https://b.example/crop_1_1.png"
        raw = self.make_raw({
            "January 2012 QP.md": island(u1) + "\n" + island(u2),
            "January 2012 MS.md": "x",
        })
        opener = FakeOpener({u1: png_bytes(4, 3), u2: png_bytes(9, 9)})
        proposal = self.run_intake_proposal(raw)
        self.assertEqual(self.run_intake_confirm(raw, proposal, None, opener), 1)
        self.assertFalse((self.tmp / "corpus" / "paper 1" / "UNIDENTIFIED-001").exists())

    def test_identical_bytes_same_filename_dedupe(self):
        u1 = "https://a.example/crop_1_1.png"
        u2 = "https://b.example/crop_1_1.png"
        raw = self.make_raw({
            "January 2012 QP.md": island(u1) + "\n" + island(u2),
            "January 2012 MS.md": "x",
        })
        opener = FakeOpener({u1: png_bytes(), u2: png_bytes()})
        proposal = self.run_intake_proposal(raw)
        self.assertEqual(self.run_intake_confirm(raw, proposal, None, opener), 0)
        assets = list((self.tmp / "corpus" / "paper 1" / "UNIDENTIFIED-001" / "assets").iterdir())
        self.assertEqual(len(assets), 1)

    def test_existing_session_refuses_overwrite(self):
        raw, mapping, opener, _, _ = self.build_fixture()
        proposal = self.run_intake_proposal(raw, mapping)
        self.assertEqual(self.run_intake_confirm(raw, proposal, mapping, opener), 0)
        self.assertEqual(self.run_intake_confirm(raw, proposal, mapping, opener), 1)


# ------------------------------------------------------------------ scrub

class ScrubTests(CorpusOpsTestBase):
    def build_after_intake(self, staged: bool = False):
        url1 = "https://host.example/crop_1_111.png"
        url2 = "https://host.example/crop_1_222.png"
        qp = island(url1) + "\n\n| t | b |\n|---|---|\n| 1 | 2 |\n\n$$\nx^2\n$$\n" + island(url2)
        raw = self.make_raw({"January 2012 QP.md": qp, "January 2012 MS.md": "answer: 42"})
        opener = FakeOpener({url1: png_bytes(), url2: png_bytes(8, 8)})
        proposal = self.run_intake_proposal(raw)
        self.assertEqual(self.run_intake_confirm(raw, proposal, None, opener), 0)
        paper_dir = self.tmp / "corpus" / "paper 1"
        session_dir = paper_dir / "UNIDENTIFIED-001"
        if staged:
            deleted = session_dir / "assets" / "_deleted"
            deleted.mkdir()
        return paper_dir, session_dir, url1, url2

    def test_scrub_removes_whole_island_only(self):
        paper_dir, session_dir, url1, _ = self.build_after_intake()
        qp_before = (session_dir / "QP.md").read_text(encoding="utf-8")
        self.assertIn("| 1 | 2 |", qp_before)
        self.assertIn("$$", qp_before)
        csv_path = write_deletions_csv(self.tmp / "del.csv",
                                       [("UNIDENTIFIED-001", "crop_1_111.png", "page furniture")])
        rc = corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--deletions", str(csv_path)])
        self.assertEqual(rc, 0)
        qp_after = (session_dir / "QP.md").read_text(encoding="utf-8")
        self.assertNotIn("crop_1_111", qp_after)          # island gone, whole line
        self.assertIn("assets/crop_1_222.png", qp_after)  # untouched
        self.assertIn("| 1 | 2 |", qp_after)              # adjacent table untouched
        self.assertIn("$$\nx^2\n$$", qp_after)            # adjacent fence untouched
        self.assertFalse((session_dir / "assets" / "crop_1_111.png").exists())
        m = mf.load_manifest(paper_dir)
        entry = m["ops_log"][-1]
        self.assertEqual(entry["kind"], "reference-scrub")
        # provenance survives deletion: the removed image's original URL is in the entry
        self.assertEqual(entry["per_session"]["UNIDENTIFIED-001"]["removed_urls"], [url1])
        self.assertEqual(m["sessions"]["UNIDENTIFIED-001"]["image_count"], 1)
        # checksum honestly recomputed: matches the file on disk
        self.assertEqual(m["sessions"]["UNIDENTIFIED-001"]["documents"]["QP"]["sha256"],
                         mf.sha256_file(session_dir / "QP.md"))

    def test_scrub_dry_run_touches_nothing(self):
        paper_dir, session_dir, _, _ = self.build_after_intake()
        before = (session_dir / "QP.md").read_bytes()
        csv_path = self.tmp / "del.csv"
        csv_path.write_text("session,asset_filename,operator_note\n"
                            "UNIDENTIFIED-001,crop_1_111.png,note\n", encoding="utf-8")
        rc = corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--deletions",
                              str(csv_path), "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual((session_dir / "QP.md").read_bytes(), before)
        self.assertTrue((session_dir / "assets" / "crop_1_111.png").exists())

    def test_double_scrub_is_error_and_idempotent_replay_works(self):
        paper_dir, _, _, _ = self.build_after_intake()
        csv_path = self.tmp / "del.csv"
        csv_path.write_text("session,asset_filename,operator_note\n"
                            "UNIDENTIFIED-001,crop_1_111.png,note\n", encoding="utf-8")
        self.assertEqual(corpus_ops.main(["scrub", str(self.tmp / "corpus"),
                                          "--deletions", str(csv_path)]), 0)
        self.assertEqual(corpus_ops.main(["scrub", str(self.tmp / "corpus"),
                                          "--deletions", str(csv_path)]), 1)
        self.assertEqual(corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--deletions",
                                          str(csv_path), "--idempotent"]), 0)

    def test_from_staging_equivalent(self):
        paper_dir, session_dir, _, _ = self.build_after_intake(staged=True)
        shutil.move(str(session_dir / "assets" / "crop_1_111.png"),
                    str(session_dir / "assets" / "_deleted" / "crop_1_111.png"))
        rc = corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--from-staging"])
        self.assertEqual(rc, 0)
        self.assertNotIn("crop_1_111", (session_dir / "QP.md").read_text(encoding="utf-8"))

    def test_orphan_reference_hard_fails(self):
        # A reference with no file and no removal record must FAIL the batch loudly.
        url_ghost = "https://ghost.example/crop_9_999.png"
        paper_dir, session_dir, _, _ = self.build_after_intake()
        qp = (session_dir / "QP.md").read_text(encoding="utf-8")
        (session_dir / "QP.md").write_text(qp + "\n" + island(url_ghost), encoding="utf-8")
        csv_path = self.tmp / "del.csv"
        csv_path.write_text("session,asset_filename,operator_note\n"
                            "UNIDENTIFIED-001,crop_1_111.png,note\n", encoding="utf-8")
        rc = corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--deletions", str(csv_path)])
        self.assertEqual(rc, 1)

    def test_reference_outside_island_refuses_partial_edit(self):
        # A GRAMMATICAL reference outside a pure island line (mid-line markdown image)
        # must abort the batch — removing it would need a within-line edit.
        paper_dir, session_dir, _, _ = self.build_after_intake()
        qp = (session_dir / "QP.md").read_text(encoding="utf-8")
        (session_dir / "QP.md").write_text(
            qp + "\nsee ![](assets/crop_1_222.png) inline\n", encoding="utf-8")
        csv_path = self.tmp / "del.csv"
        csv_path.write_text("session,asset_filename,operator_note\n"
                            "UNIDENTIFIED-001,crop_1_222.png,note\n", encoding="utf-8")
        rc = corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--deletions", str(csv_path)])
        self.assertEqual(rc, 1)
        # nothing was written: the island and the file both survive the aborted batch
        self.assertIn("assets/crop_1_222.png", (session_dir / "QP.md").read_text(encoding="utf-8"))

    def test_bare_prose_mention_is_not_a_grammatical_reference(self):
        # Scrub is grammar-scoped: a bare path in prose is not an image reference —
        # neither abort nor edit; provenance for the removal lives in ops_log.
        paper_dir, session_dir, _, _ = self.build_after_intake()
        qp = (session_dir / "QP.md").read_text(encoding="utf-8")
        (session_dir / "QP.md").write_text(
            qp + "\nsee assets/crop_1_222.png inline\n", encoding="utf-8")
        csv_path = self.tmp / "del2.csv"
        csv_path.write_text("session,asset_filename,operator_note\n"
                            "UNIDENTIFIED-001,crop_1_222.png,note\n", encoding="utf-8")
        rc = corpus_ops.main(["scrub", str(self.tmp / "corpus"), "--deletions", str(csv_path)])
        self.assertEqual(rc, 0)


# ------------------------------------------------------------------ verify + rename

class VerifyRenameTests(CorpusOpsTestBase):
    def build_after_intake(self):
        url1 = "https://host.example/crop_1_111.png"
        raw = self.make_raw({"January 2012 QP.md": island(url1), "January 2012 MS.md": "x"})
        opener = FakeOpener({url1: png_bytes()})
        proposal = self.run_intake_proposal(raw)
        self.assertEqual(self.run_intake_confirm(raw, proposal, None, opener), 0)
        return self.tmp / "corpus" / "paper 1"

    def test_verify_green_after_intake(self):
        paper_dir = self.build_after_intake()
        rc = corpus_ops.main(["verify", str(self.tmp / "corpus")])
        self.assertEqual(rc, 0)

    def test_verify_fails_on_stray_asset(self):
        paper_dir = self.build_after_intake()
        session = next(p for p in paper_dir.iterdir() if p.is_dir())
        (session / "assets" / "stray.png").write_bytes(png_bytes())
        rc = corpus_ops.main(["verify", str(self.tmp / "corpus")])
        self.assertEqual(rc, 1)

    def test_verify_fails_on_missing_document_file_on_disk(self):
        # T-C17 negative-control finding: a manifest-listed half whose file was
        # deleted from disk must FAIL pair-completeness (fail-closed), not pass.
        paper_dir = self.build_after_intake()
        session = next(p for p in paper_dir.iterdir() if p.is_dir())
        (session / "MS.md").unlink()
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = corpus_ops.main(["verify", str(self.tmp / "corpus"), "--json"])
        self.assertEqual(rc, 1)
        findings = json.loads(buf.getvalue())["findings"]
        self.assertTrue(any(f["level"] == "FAIL" and f["check"] == "pair-completeness"
                            and "missing on disk" in f["detail"] for f in findings))

    def test_verify_fails_on_document_checksum_drift(self):
        # Manifest <-> filesystem agreement covers the documents themselves:
        # editing QP.md without refreshing the manifest sha256 must FAIL.
        paper_dir = self.build_after_intake()
        session = next(p for p in paper_dir.iterdir() if p.is_dir())
        with open(session / "QP.md", "a", encoding="utf-8") as fh:
            fh.write("drift\n")
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = corpus_ops.main(["verify", str(self.tmp / "corpus"), "--json"])
        self.assertEqual(rc, 1)
        findings = json.loads(buf.getvalue())["findings"]
        self.assertTrue(any(f["level"] == "FAIL" and f["check"] == "document-checksum"
                            for f in findings))

    def test_verify_warns_on_unidentified(self):
        self.build_after_intake()
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            corpus_ops.main(["verify", str(self.tmp / "corpus"), "--json"])
        findings = json.loads(buf.getvalue())["findings"]
        self.assertTrue(any(f["level"] == "WARN" and f["check"] == "provisional-identity"
                            for f in findings))

    def test_rename_proposal_confirm_and_ops_log(self):
        paper_dir = self.build_after_intake()
        mapping = self.tmp / "r.csv"
        mapping.write_text("from_session,to_session\n"
                           f"{pairing.UNIDENTIFIED_PREFIX}-001,2012-Jan\n", encoding="utf-8")
        proposal = self.tmp / "rename.json"
        rc = corpus_ops.main(["rename", str(self.tmp / "corpus"), "--mapping", str(mapping),
                              "--out-proposal", str(proposal)])
        self.assertEqual(rc, 0)
        self.assertFalse((paper_dir / "2012-Jan").exists())
        rc = corpus_ops.main(["rename", str(self.tmp / "corpus"), "--mapping", str(mapping),
                              "--confirm", str(proposal)])
        self.assertEqual(rc, 0)
        self.assertTrue((paper_dir / "2012-Jan" / "QP.md").exists())
        m = mf.load_manifest(paper_dir)
        self.assertIn("2012-Jan", m["sessions"])
        self.assertNotIn(f"{pairing.UNIDENTIFIED_PREFIX}-001", m["sessions"])
        self.assertEqual(m["ops_log"][-1]["kind"], "rename")
        rc = corpus_ops.main(["verify", str(self.tmp / "corpus")])
        self.assertEqual(rc, 0)

    def test_rename_refuses_non_provisional(self):
        paper_dir = self.build_after_intake()
        mapping = self.tmp / "r.csv"
        mapping.write_text("from_session,to_session\nSome-Real,Other\n", encoding="utf-8")
        rc = corpus_ops.main(["rename", str(self.tmp / "corpus"), "--mapping", str(mapping),
                              "--dry-run"])
        self.assertEqual(rc, 1)


# ------------------------------------------------------------------ legacy compat

class LegacyManifestTests(CorpusOpsTestBase):
    def test_legacy_shape_round_trips_additively(self):
        paper_dir = self.tmp / "paper 1"
        legacy = {
            "paper": "paper 1",
            "generated_at_utc": "2026-09-11T05:45:05Z",
            "structure": mf.LEGACY_STRUCTURE,
            "notes": ["x"],
            "dropped_duplicates": ["dup.md"],
            "download_failures": [],
            "sessions": {
                "2012-Jan": {
                    "documents": {"QP": {"original_name": "a.md", "path": "QP.md",
                                         "sha256": "a" * 64}},
                    "image_count": 1,
                    "images": {"https://h/1.png": {"saved_as": "1.png", "bytes": 10,
                                                   "format": "png", "sha256": "b" * 64,
                                                   "referenced_by": ["QP.md"]}},
                }
            },
            "operator_cleanup": {"date_utc": "2026-09-11 11:32:07 UTC",
                                 "description": "d", "removed_image_count": 1,
                                 "removed_images": {"2012-Jan": ["https://h/2.png"]}},
        }
        mf.dump_manifest(legacy, paper_dir)
        m = mf.ensure_v11(mf.load_manifest(paper_dir))
        self.assertEqual(m["sessions"]["2012-Jan"]["documents"]["QP"]["sha256"], "a" * 64)
        self.assertEqual(mf.removed_urls_for_session(m, "2012-Jan"), {"https://h/2.png"})
        mf.dump_manifest(m, paper_dir)
        reread = json.loads((paper_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(reread["operator_cleanup"]["removed_image_count"], 1)
        self.assertEqual(reread["schema_version"], "1.1")

    def test_scrub_orphan_honors_legacy_removals(self):
        text = island("https://h/2.png")
        manifest = {"sessions": {"2012-Jan": {"images": {}}},
                    "operator_cleanup": {"removed_images": {"2012-Jan": ["https://h/2.png"]}}}
        ledger = scrub_mod.orphan_scan({"2012-Jan": {"QP.md": text}}, manifest, {})
        self.assertEqual(ledger, [])


# ------------------------------------------------------------------ clean_diff (G3)

def qp_draft(questions: list[dict], warnings: list[str] | None = None,
             conflict=None) -> dict:
    return {"schemaVersion": "1.0", "questions": questions,
            "warnings": warnings or [], "paperTotalConflict": conflict}


def q(number: str, marks: int | None = 3, parts: list[dict] | None = None) -> dict:
    if parts is None:
        return {"number": number, "marks": marks, "parts": []}
    return {"number": number, "marks": marks, "parts": parts}


def part(label: str, marks: int | None = 2) -> dict:
    return {"label": label, "marks": marks}


class CleanDiffTests(unittest.TestCase):
    def test_spillover_removal_passes(self):
        raw = qp_draft([q("1"), q("2"), q("3"), q("BOGUS-27")])
        clean = qp_draft([q("1"), q("2"), q("3")])
        report = clean_diff.run_gate(raw, clean)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["counts"]["questions_clean"], 3)

    def test_real_mark_change_rejected(self):
        raw = qp_draft([q("1", parts=[part("a", 2), part("b", 3)])])
        clean = qp_draft([q("1", parts=[part("a", 2), part("b", 4)])])
        report = clean_diff.run_gate(raw, clean)
        self.assertEqual(report["result"], "FAIL")
        g32 = next(c for c in report["checks"] if c["id"] == "G3.2")
        self.assertEqual(g32["status"], "FAIL")

    def test_shared_mark_identity_with_removal_passes(self):
        raw = qp_draft([q("1", parts=[part("a", 2), part("b", 3)]),
                        q("PHANTOM", parts=[part("a", 5)])])
        clean = qp_draft([q("1", parts=[part("a", 2), part("b", 3)])])
        self.assertEqual(clean_diff.run_gate(raw, clean)["result"], "PASS")

    def test_question_count_increase_rejected(self):
        self.assertEqual(clean_diff.run_gate(qp_draft([q("1")]),
                                             qp_draft([q("1"), q("2")]))["result"], "FAIL")

    def test_mark_point_count_increase_rejected(self):
        ms_raw = {"entries": [{"markPoints": [{"m": 1}, {"m": 1}]}]}
        ms_clean = {"entries": [{"markPoints": [{"m": 1}, {"m": 1}, {"m": 1}]}]}
        report = clean_diff.run_gate(qp_draft([q("1")]), qp_draft([q("1")]), ms_raw, ms_clean)
        self.assertEqual(next(c for c in report["checks"]
                              if c["id"] == "G3.3")["status"], "FAIL")

    def test_new_warning_class_rejected_but_boilerplate_removed_allowed(self):
        raw = qp_draft([q("1")], warnings=["2(a): bare integer cell skipped"])
        clean_new_class = qp_draft([q("1")], warnings=["2(a): bare integer cell skipped",
                                                       "X: something new"])
        self.assertEqual(clean_diff.run_gate(raw, clean_new_class)["result"], "FAIL")
        clean_ok = qp_draft([q("1")], warnings=["2(a): bare integer cell skipped",
                                                "boilerplate-removed: cover-page lines 1-58"])
        self.assertEqual(clean_diff.run_gate(raw, clean_ok)["result"], "PASS")

    def test_paper_total_conflict_rules(self):
        self.assertEqual(clean_diff.run_gate(qp_draft([q("1")], conflict=True),
                                             qp_draft([q("1")], conflict=True))["result"], "PASS")
        self.assertEqual(clean_diff.run_gate(qp_draft([q("1")]),
                                             qp_draft([q("1")], conflict=True))["result"], "FAIL")
        self.assertEqual(clean_diff.run_gate(qp_draft([q("1")], conflict=True),
                                             qp_draft([q("1")]))["result"], "PASS")


# ------------------------------------------------------------------ units

class UnitTests(unittest.TestCase):
    def test_mime_sniffing_by_bytes(self):
        self.assertEqual(downloader.sniff_mime(png_bytes()), "image/png")
        self.assertEqual(downloader.sniff_mime(jpeg_bytes()), "image/jpeg")
        self.assertEqual(downloader.sniff_mime(b"not an image"), "application/octet-stream")

    def test_dimensions(self):
        self.assertEqual(downloader.png_dimensions(png_bytes(7, 5)), (7, 5))
        self.assertEqual(downloader.jpeg_dimensions(jpeg_bytes(6, 2)), (6, 2))

    def test_island_regex_matches_real_corpus_shape(self):
        line = island("assets/crop_1_1789041656774.png")
        self.assertTrue(scrub_mod.is_pure_island_line(line))
        self.assertFalse(scrub_mod.is_pure_island_line("text " + line))
        m = scrub_mod.ISLAND_RE.match(line.strip())
        self.assertEqual(m.group("src"), "assets/crop_1_1789041656774.png")

    def test_warning_class_extraction(self):
        self.assertEqual(clean_diff.warning_class("2(a): bare integer cell skipped"),
                         "2(a)")
        self.assertEqual(clean_diff.warning_class("boilerplate-removed: cover"),
                         "boilerplate-removed")

    def test_batch_id_deterministic(self):
        a = scrub_mod.Deletion("s", "f.png", "n1")
        b = scrub_mod.Deletion("s", "f.png", "different note")
        self.assertEqual(scrub_mod.batch_id_for([a]), scrub_mod.batch_id_for([b]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
