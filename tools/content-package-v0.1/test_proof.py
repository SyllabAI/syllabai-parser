#!/usr/bin/env python3
"""Self-contained regression tests for the bounded Content Package proof."""
from __future__ import annotations
import json, shutil, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPILER = HERE / "compile_proof.py"
FIXTURE = HERE / "fixture" / "inventory.json"


def run(inv: Path, out: Path):
    return subprocess.run(
        ["python3", str(COMPILER), str(inv), str(out), "--reconstruct"],
        cwd=HERE.parent.parent,
        text=True,
        capture_output=True,
    )


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        out = td / "package"
        ok = run(FIXTURE, out)
        assert ok.returncode == 0, ok.stderr
        assert (out / "MANIFEST.json").is_file()
        assert (out / "database/content.sqlite").is_file()

        # Lifecycle gate: imported assessment content must not become serving content
        bad = td / "bad-status"
        shutil.copytree(FIXTURE.parent, bad)
        inv = json.loads((bad / "inventory.json").read_text())
        inv["paper"]["status"] = "SUGGESTED"
        (bad / "inventory.json").write_text(json.dumps(inv, indent=2) + "\n")
        result = run(bad / "inventory.json", td / "rejected-status")
        assert result.returncode != 0
        assert "VALIDATED" in result.stderr

        # Provenance gate: byte identity mismatch must fail closed
        bad_hash = td / "bad-hash"
        shutil.copytree(FIXTURE.parent, bad_hash)
        inv = json.loads((bad_hash / "inventory.json").read_text())
        inv["revisionNote"]["provenance"]["sourceSha256"] = "0" * 64
        (bad_hash / "inventory.json").write_text(json.dumps(inv, indent=2) + "\n")
        result = run(bad_hash / "inventory.json", td / "rejected-hash")
        assert result.returncode != 0
        assert "sourceSha256" in result.stderr

        # Relationship gate: a question part without mark points is invalid
        bad_rel = td / "bad-relationship"
        shutil.copytree(FIXTURE.parent, bad_rel)
        inv = json.loads((bad_rel / "inventory.json").read_text())
        inv["paper"]["questions"][0]["parts"][0]["markPoints"] = []
        (bad_rel / "inventory.json").write_text(json.dumps(inv, indent=2) + "\n")
        result = run(bad_rel / "inventory.json", td / "rejected-relationship")
        assert result.returncode != 0
        assert "missing mark points" in result.stderr

    print("PASS: bounded Content Package v0.1 proof and negative gates")


if __name__ == "__main__":
    main()
