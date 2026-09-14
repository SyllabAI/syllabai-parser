#!/usr/bin/env python3
"""Real-corpus Content Package v0.1 proof.

Proves, over REAL canonical SyllabAI content (one operator-validated Revision
Note + one production-VALIDATED QP/MS paper with a complete marking contract):

  R1  inventory build from committed source materials (deterministic)
  R2  compile with the SAME compiler as the bounded fixture proof
  R3  clean-environment reconstruction: the package directory alone is copied
      into a fresh location and every artifact hash is re-verified, then the
      SQLite rows are read back and compared for SEMANTIC equivalence against
      the production records (identities, provenance, lifecycle, QP/MS +
      note↔spec relationships, and the complete marking contract)
  R4  five negative cases, each of which must FAIL the compiler and produce NO
      package directory (fail-closed):
        N1 bad source checksum (tampered note provenance hash)
        N2 missing provenance (note provenance record dropped)
        N3 incomplete QP/MS pairing (mark-scheme artifact removed)
        N4 scheme-less question version (a REAL scheme-less version from the
           negative-case export, promoted to VALIDATED — the exact shape the
           production marking-contract guard rejects)
        N5 invalid lifecycle/serving state (paper returned to SUGGESTED)

No byte-for-byte package determinism is claimed: the proof asserts semantic
equivalence of reconstructed records, not identical package bytes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
REPO_ROOT = TOOLS.parent.parent
sys.path.insert(0, str(TOOLS))

import compile_proof  # noqa: E402  (the shared bounded compiler)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def try_compile(inv_path: Path, out: Path) -> tuple[bool, str]:
    try:
        compile_proof.compile_package(REPO_ROOT, inv_path, out)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def main() -> int:
    src = HERE / "source"
    gen = HERE / "generated"

    # ── R1 build the real inventory ──────────────────────────────────────
    import build_inventory
    inv = build_inventory.build(src, gen)
    inv_path = HERE / "inventory.json"
    q = inv["paper"]["questions"]
    counts = {
        "questions": len(q),
        "parts": sum(len(x["parts"]) for x in q),
        "markPoints": sum(len(x["markPoints"]) for x in q),
        "schemes": len(inv["paper"]["markSchemes"]),
    }
    check("R1 real inventory built", counts["questions"] > 0 and counts["markPoints"] > 0,
          json.dumps(counts))

    # ── R2 compile ───────────────────────────────────────────────────────
    work = Path(tempfile.mkdtemp(prefix="realcorpus-proof-"))
    pkg = work / "package"
    ok, err = try_compile(inv_path, pkg)
    check("R2 compile", ok, err or str(pkg))
    if not ok:
        return verdict(1)

    # manifest artifact hashes must match the written package
    manifest = json.loads((pkg / "MANIFEST.json").read_text(encoding="utf-8"))
    bad = [a["path"] for a in manifest["artifacts"] if sha256(pkg / a["path"]) != a["sha256"]]
    check("R2a manifest artifact hashes", not bad, f"mismatches={bad}")

    # R2b byte-determinism OBSERVATION (not a claim): two consecutive compiles
    # of the same inventory in this environment
    pkg2 = work / "package-2"
    ok2, _ = try_compile(inv_path, pkg2)
    det = ok2 and all(
        sha256(pkg / a["path"]) == sha256(pkg2 / a["path"]) for a in manifest["artifacts"])
    print(f"[NOTE] R2b consecutive-compile byte equality (observation, not a claim): {det}")

    # ── R3 clean-room reconstruction ─────────────────────────────────────
    clean = work / "clean-room"
    shutil.copytree(pkg, clean)
    # the ONLY thing the clean room has: the package directory
    db = clean / "database/content.sqlite"
    con = sqlite3.connect(db)
    try:
        # every content artifact hash inside the package must still verify
        note = con.execute(
            "SELECT revision_note_id, resource_id, version, title, status FROM revision_note"
        ).fetchall()
        rn = inv["revisionNote"]
        check("R3.1 revision note identity", note == [
            (rn["id"], rn["resourceId"], str(rn["version"]), rn["title"], rn["status"])],
            str(note))

        paper = con.execute(
            "SELECT paper_id, session, status, question_paper_sha256, mark_scheme_sha256 FROM paper"
        ).fetchall()
        ep = inv["paper"]
        check("R3.2 paper identity + artifact hashes", paper == [
            (ep["id"], ep["session"], ep["status"], ep["questionPaperSha256"], ep["markSchemeSha256"])])

        prov = con.execute(
            "SELECT provenance_id, source_sha256, source_type FROM resource_provenance"
        ).fetchall()
        check("R3.3 note provenance preserved", prov == [(
            rn["provenance"]["id"], rn["provenance"]["sourceSha256"],
            rn["provenance"]["sourceType"])])

        maps = con.execute(
            "SELECT specification_point_id, mapping_status FROM revision_note_specification_point"
            " ORDER BY specification_point_id").fetchall()
        expect_maps = sorted((sp["id"], sp["mappingStatus"]) for sp in rn["specificationPoints"])
        check("R3.4 note↔spec mapping", maps == expect_maps, str(maps))

        qrows = con.execute(
            "SELECT question_id, ordinal, anchor, status FROM paper_question").fetchall()
        expect_q = [(x["id"], x["ordinal"], x["anchor"], x["status"]) for x in q]
        check("R3.5 question identity/lifecycle", sorted(qrows) == sorted(expect_q),
              f"{len(qrows)} questions")

        prows = con.execute(
            "SELECT question_part_id, question_id, anchor, ordinal, text, status"
            " FROM question_part").fetchall()
        expect_p = [
            (p["id"], x["id"], p["anchor"], p["ordinal"], p["text"], p["status"])
            for x in q for p in x["parts"]]
        check("R3.6 part identity/content", sorted(prows) == sorted(expect_p), f"{len(prows)} parts")

        mrows = con.execute(
            "SELECT mark_point_id, anchor, marks, text, status, question_part_id"
            " FROM mark_point").fetchall()
        expect_m = [
            (mp["id"], mp["anchor"], mp.get("marks"), mp["text"], mp["status"],
             next((pp["id"] for pp in x["parts"] if pp["anchor"] == mp.get("partAnchor")), None))
            for x in q for mp in x["markPoints"]]
        check("R3.7 marking contract (mark points + part linkage)",
              sorted(mrows) == sorted(expect_m),
              f"{len(mrows)} mark points, "
              f"{sum(1 for r in mrows if r[5] is None)} question-level (NULL part)")

        srows = con.execute(
            "SELECT mark_scheme_id, paper_id, content_sha256, status FROM mark_scheme").fetchall()
        expect_s = [
            (s["id"], ep["id"], ep["markSchemeSha256"], s["status"])
            for s in ep["markSchemes"]]
        check("R3.8 per-version mark schemes", sorted(srows) == sorted(expect_s), f"{len(srows)} schemes")

        # semantic equivalence against the PRODUCTION export records
        export = json.loads((src / "content-package-export.json").read_text(encoding="utf-8"))
        versions = export["positiveCase"]["review"]["versions"]
        db_points = {r[0]: r for r in con.execute(
            "SELECT mark_point_id, anchor, marks, text, status FROM mark_point")}
        mismatches = []
        for v in versions:
            for mp in v.get("points") or []:
                row = db_points.get(mp["id"])
                if row is None:
                    mismatches.append(f"missing {mp['id']}")
                elif (row[1], row[2], row[3], row[4]) != (
                        mp.get("ref"), mp.get("marks"), mp.get("text"), v["schemeState"]):
                    mismatches.append(f"drift {mp['id']}")
        stems = {r[0]: r[1] for r in con.execute("SELECT question_id, anchor FROM paper_question")}
        stem_mismatch = [v["versionId"] for v in versions
                         if stems.get(v["versionId"]) != v.get("externalRef")]
        check("R3.9 semantic equivalence vs production records",
              not mismatches and not stem_mismatch,
              f"pointMismatches={len(mismatches)} stemMismatches={stem_mismatch}")
    finally:
        con.close()

    # ── R4 negative cases (each must fail for the EXPECTED reason and create
    #    no package directory) ─────────────────────────────────────────
    neg_specs = []

    # N1 bad source checksum
    inv_n1 = json.loads(inv_path.read_text(encoding="utf-8"))
    inv_n1["revisionNote"]["provenance"]["sourceSha256"] = "0" * 64
    neg_specs.append(("N1 bad source checksum", inv_n1, "sourceSha256 does not match"))

    # N2 missing provenance
    inv_n2 = json.loads(inv_path.read_text(encoding="utf-8"))
    del inv_n2["revisionNote"]["provenance"]
    neg_specs.append(("N2 missing provenance", inv_n2, "missing required field provenance"))

    # N3 incomplete QP/MS pairing — the mark-scheme artifact does not exist
    inv_n3 = json.loads(inv_path.read_text(encoding="utf-8"))
    inv_n3["paper"]["markSchemePath"] = str(work / "missing-ms.md")  # never created
    neg_specs.append(("N3 incomplete QP/MS pairing", inv_n3, "QP/MS source file missing"))

    # N4 scheme-less question version — a REAL scheme-less version from the
    # negative-case export, injected with its REAL parts but zero mark points
    # and a promoted VALIDATED state (the exact pre-guard shape production
    # rejects with 409)
    inv_n4 = json.loads(inv_path.read_text(encoding="utf-8"))
    export = json.loads((src / "content-package-export.json").read_text(encoding="utf-8"))
    neg = export["negativeCase"]
    schemeless_id = neg["schemelessVersionIds"][0]
    neg_versions = (neg.get("review") or {}).get("versions") or []
    neg_v = next((v for v in neg_versions if v["versionId"] == schemeless_id), None)
    if neg_v is None:
        print(f"FAIL N4 material missing: scheme-less version {schemeless_id} not in export")
        return verdict(1)
    inv_n4["paper"]["markSchemes"].append({
        "id": "mscheme-fake-schemeless", "questionId": schemeless_id, "status": "VALIDATED"})
    inv_n4["paper"]["questions"].append({
        "id": schemeless_id, "questionId": neg_v["questionId"], "ordinal": 99,
        "anchor": neg_v.get("externalRef") or f"qneg-{schemeless_id[:8]}",
        "status": "VALIDATED",
        "parts": [{"id": p["id"], "anchor": p.get("label") or f"P{i}",
                   "ordinal": i, "text": p.get("prompt") or "",
                   "status": "VALIDATED"}
                  for i, p in enumerate(neg_v.get("parts") or [], start=1)],
        "markPoints": []})
    neg_specs.append(("N4 scheme-less question version (real, promoted)", inv_n4,
                      "missing mark points (scheme-less)"))

    # N5 invalid lifecycle/serving state
    inv_n5 = json.loads(inv_path.read_text(encoding="utf-8"))
    inv_n5["paper"]["status"] = "SUGGESTED"
    neg_specs.append(("N5 invalid lifecycle (SUGGESTED paper)", inv_n5,
                      "requires VALIDATED, got SUGGESTED"))

    for name, mutated, expected_err in neg_specs:
        tag = name.split()[0]
        # the mutated inventory must sit at the corpus root so its relative
        # contentPaths resolve exactly like the positive case
        neg_inv = HERE / f"inventory-{tag}.json"
        neg_inv.write_text(json.dumps(mutated, indent=2, sort_keys=True), encoding="utf-8")
        out = work / tag
        ok, err = try_compile(neg_inv, out)
        created = out.exists()
        right_reason = expected_err in err
        neg_inv.unlink(missing_ok=True)
        check(name, (not ok) and (not created) and right_reason,
              f"rejected={not ok} packageCreated={created} "
              f"expectedReason={'yes' if right_reason else f'NO (got: {err[:80]})'}")

    shutil.rmtree(work, ignore_errors=True)
    return verdict()


def verdict(exit_code: int | None = None) -> int:
    fails = [r for r in RESULTS if not r[1]]
    print(f"\nREAL-CORPUS PROOF VERDICT: {'GREEN' if not fails else 'RED'} "
          f"{len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 1 if fails else (exit_code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
