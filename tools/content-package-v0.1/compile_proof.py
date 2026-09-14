#!/usr/bin/env python3
"""Bounded Content Package v0.1 compiler/reconstruction proof harness."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sqlite3, sys
from pathlib import Path

COMPILER_VERSION = "content-package-v0.1-proof-1"
SCHEMA_VERSION = "0.1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fail(msg: str):
    raise ValueError(msg)


def require(d, key, context):
    value = d.get(key)
    if value in (None, "", []):
        fail(f"{context}: missing required field {key}")
    return value


def validate_inventory(inv: dict, root: Path):
    require(inv, "schemaVersion", "inventory")
    if inv["schemaVersion"] != SCHEMA_VERSION:
        fail(f"inventory: unsupported schemaVersion {inv['schemaVersion']}")
    rn = require(inv, "revisionNote", "inventory")
    paper = require(inv, "paper", "inventory")
    for key in ("id", "resourceId", "version", "title", "status", "provenance", "contentPath"):
        require(rn, key, "revisionNote")
    require(rn["provenance"], "sourceSha256", "revisionNote.provenance")
    require(rn["provenance"], "id", "revisionNote.provenance")
    if rn["status"] != "VALIDATED":
        fail(f"revisionNote: learner-serving proof requires VALIDATED, got {rn['status']}")
    rn_path = root / rn["contentPath"]
    if not rn_path.is_file():
        fail(f"revisionNote: contentPath does not exist: {rn_path}")
    if sha256(rn_path) != rn["provenance"]["sourceSha256"]:
        fail("revisionNote: provenance sourceSha256 does not match content")

    for key in ("id", "status", "questionPaperPath", "markSchemePath", "questionPaperSha256", "markSchemeSha256", "markSchemeId", "questions"):
        require(paper, key, "paper")
    if paper["status"] != "VALIDATED":
        fail(f"paper: learner-serving proof requires VALIDATED, got {paper['status']}")
    qp = root / paper["questionPaperPath"]
    ms = root / paper["markSchemePath"]
    if not qp.is_file() or not ms.is_file():
        fail("paper: QP/MS source file missing")
    if sha256(qp) != paper["questionPaperSha256"]:
        fail("paper: questionPaperSha256 mismatch")
    if sha256(ms) != paper["markSchemeSha256"]:
        fail("paper: markSchemeSha256 mismatch")
    seen_q, seen_parts, seen_marks = set(), set(), set()
    for q in paper["questions"]:
        for key in ("id", "ordinal", "anchor", "status", "parts"):
            require(q, key, f"question {q.get('id', '?')}")
        if q["id"] in seen_q:
            fail(f"paper: duplicate question id {q['id']}")
        seen_q.add(q["id"])
        if q["status"] != "VALIDATED":
            fail(f"question {q['id']}: status {q['status']} is not learner-serving")
        for p in q["parts"]:
            for key in ("id", "anchor", "ordinal", "text", "status", "markPoints"):
                require(p, key, f"part {p.get('id', '?')}")
            if p["id"] in seen_parts:
                fail(f"paper: duplicate part id {p['id']}")
            seen_parts.add(p["id"])
            if p["status"] != "VALIDATED":
                fail(f"part {p['id']}: status {p['status']} is not learner-serving")
            if not p["markPoints"]:
                fail(f"part {p['id']}: missing mark points")
            for mp in p["markPoints"]:
                for key in ("id", "anchor", "status", "text"):
                    require(mp, key, f"markPoint {mp.get('id', '?')}")
                if mp["id"] in seen_marks:
                    fail(f"paper: duplicate mark point id {mp['id']}")
                seen_marks.add(mp["id"])
                if mp["status"] != "VALIDATED":
                    fail(f"markPoint {mp['id']}: status {mp['status']} is not learner-serving")


def read_schema(repo_root: Path) -> str:
    return (repo_root / "tools/content-package-v0.1/schema.sql").read_text(encoding="utf-8")


def compile_package(repo_root: Path, inventory_path: Path, out_dir: Path):
    root = inventory_path.parent
    inv = load_json(inventory_path)
    validate_inventory(inv, root)
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "content/revision-notes").mkdir(parents=True)
    (out_dir / f"content/papers/{inv['paper']['id']}").mkdir(parents=True)
    (out_dir / "database").mkdir()
    rn, paper = inv["revisionNote"], inv["paper"]
    rn_src, qp_src, ms_src = root / rn["contentPath"], root / paper["questionPaperPath"], root / paper["markSchemePath"]
    rn_dst = out_dir / f"content/revision-notes/{rn['resourceId']}.md"
    qp_dst = out_dir / f"content/papers/{paper['id']}/question-paper.md"
    ms_dst = out_dir / f"content/papers/{paper['id']}/mark-scheme.md"
    shutil.copyfile(rn_src, rn_dst); shutil.copyfile(qp_src, qp_dst); shutil.copyfile(ms_src, ms_dst)
    db = out_dir / "database/content.sqlite"
    con = sqlite3.connect(db)
    try:
        con.executescript(read_schema(repo_root))
        con.execute("INSERT INTO package_metadata VALUES (?,?)", ("packageFormat", "syllabai-content-package"))
        con.execute("INSERT INTO package_metadata VALUES (?,?)", ("packageVersion", "0.1"))
        con.execute("INSERT INTO package_metadata VALUES (?,?)", ("compilerVersion", COMPILER_VERSION))
        con.execute("INSERT INTO package_metadata VALUES (?,?)", ("schemaVersion", SCHEMA_VERSION))
        con.execute("INSERT INTO package_metadata VALUES (?,?)", ("status", "PROOF"))
        con.execute("INSERT INTO resource VALUES (?,?,?,?,?,?,?)", (rn["resourceId"], "REVISION_NOTE", rn["status"], rn.get("subject"), rn.get("qualification"), rn.get("curriculumVersion"), rn["provenance"]["id"]))
        con.execute("INSERT INTO resource_version VALUES (?,?,?,?,?,?,?)", (rn["resourceId"], rn["version"], f"content/revision-notes/{rn['resourceId']}.md", sha256(rn_dst), rn["status"], COMPILER_VERSION, "1970-01-01T00:00:00Z"))
        p = rn["provenance"]
        con.execute("INSERT INTO resource_provenance VALUES (?,?,?,?,?,?,?)", (p["id"], p.get("sourceUri"), p["sourceSha256"], p["sourceType"], p.get("parser"), p.get("parserVersion"), p.get("importedAt")))
        for sp in rn.get("specificationPoints", []):
            con.execute("INSERT INTO specification_point VALUES (?,?,?,?)", (sp["id"], sp["specificationId"], sp.get("externalRef"), sp.get("title")))
        con.execute("INSERT INTO revision_note VALUES (?,?,?,?,?,?,?)", (rn["id"], rn["resourceId"], rn["version"], rn["title"], f"content/revision-notes/{rn['resourceId']}.md", sha256(rn_dst), rn["status"]))
        for sp in rn.get("specificationPoints", []):
            con.execute("INSERT INTO revision_note_specification_point VALUES (?,?,?)", (rn["id"], sp["id"], sp.get("mappingStatus", "VALIDATED")))
        con.execute("INSERT INTO paper VALUES (?,?,?,?,?,?,?)", (paper["id"], paper.get("qualification"), paper.get("subject"), paper.get("session"), paper["status"], paper["questionPaperSha256"], paper["markSchemeSha256"]))
        for q in paper["questions"]:
            con.execute("INSERT INTO paper_question VALUES (?,?,?,?,?)", (q["id"], paper["id"], q["ordinal"], q["anchor"], q["status"]))
            for p in q["parts"]:
                con.execute("INSERT INTO question_part VALUES (?,?,?,?,?,?)", (p["id"], q["id"], p["anchor"], p["ordinal"], p["text"], p["status"]))
        con.execute("INSERT INTO mark_scheme VALUES (?,?,?,?,?)", (paper["markSchemeId"], paper["id"], f"content/papers/{paper['id']}/mark-scheme.md", sha256(ms_dst), paper["status"]))
        for q in paper["questions"]:
            for part in q["parts"]:
                for mp in part["markPoints"]:
                    con.execute("INSERT INTO mark_point VALUES (?,?,?,?,?,?,?)", (mp["id"], paper["markSchemeId"], part["id"], mp["anchor"], mp.get("marks"), mp["text"], mp["status"]))
        con.commit()
    finally:
        con.close()
    artifacts = [{"path": p.relative_to(out_dir).as_posix(), "type": "sqlite_database" if p.name == "content.sqlite" else "markdown", "sha256": sha256(p)} for p in sorted(out_dir.rglob("*")) if p.is_file()]
    manifest = {"packageFormat":"syllabai-content-package","packageVersion":"0.1","scope":"bounded-proof","buildId":"reconstruction-proof","compilerVersion":COMPILER_VERSION,"schemaVersion":SCHEMA_VERSION,"createdAt":"1970-01-01T00:00:00Z","status":"PROOF","artifacts":artifacts}
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def reconstruct(package_dir: Path, expected_path: Path):
    inv = load_json(expected_path); db = package_dir / "database/content.sqlite"
    con = sqlite3.connect(db)
    try:
        rn = con.execute("SELECT revision_note_id,resource_id,version,title,status FROM revision_note").fetchall()
        paper = con.execute("SELECT paper_id,status,question_paper_sha256,mark_scheme_sha256 FROM paper").fetchall()
        mappings = con.execute("SELECT revision_note_id,specification_point_id,mapping_status FROM revision_note_specification_point ORDER BY specification_point_id").fetchall()
        parts = con.execute("SELECT question_part_id,question_id,anchor,ordinal,text,status FROM question_part ORDER BY question_part_id").fetchall()
        mps = con.execute("SELECT mark_point_id,question_part_id,anchor,marks,text,status FROM mark_point ORDER BY mark_point_id").fetchall()
        rn0 = inv["revisionNote"]
        if rn != [(rn0["id"], rn0["resourceId"], rn0["version"], rn0["title"], rn0["status"])]: fail("reconstruction mismatch: revision_note")
        ep = inv["paper"]
        if paper != [(ep["id"], ep["status"], ep["questionPaperSha256"], ep["markSchemeSha256"])] : fail("reconstruction mismatch: paper")
        expected_mappings = sorted((rn0["id"], sp["id"], sp.get("mappingStatus", "VALIDATED")) for sp in rn0.get("specificationPoints", []))
        if mappings != expected_mappings: fail("reconstruction mismatch: SpecificationPoint mappings")
        expected_parts = sorted((p["id"], q["id"], p["anchor"], p["ordinal"], p["text"], p["status"]) for q in ep["questions"] for p in q["parts"])
        if parts != expected_parts: fail("reconstruction mismatch: question parts")
        expected_mps = sorted((m["id"], p["id"], m["anchor"], m.get("marks"), m["text"], m["status"]) for q in ep["questions"] for p in q["parts"] for m in p["markPoints"])
        if mps != expected_mps: fail("reconstruction mismatch: mark points")
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    ap.add_argument("--reconstruct", action="store_true")
    args = ap.parse_args()
    if args.output.exists(): shutil.rmtree(args.output)
    compile_package(args.repo_root, args.inventory, args.output)
    if args.reconstruct: reconstruct(args.output, args.inventory)
    print(json.dumps({"status":"PASS","package":str(args.output),"compilerVersion":COMPILER_VERSION}, sort_keys=True))

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(json.dumps({"status":"FAIL","error":str(exc)}, sort_keys=True), file=sys.stderr); sys.exit(1)
