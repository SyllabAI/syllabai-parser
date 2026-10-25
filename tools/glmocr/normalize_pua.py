"""T-MIG-141 Phase E intake law — Python reference implementation (spec §7).

``normalize_pua(text, table)`` is the SINGLE Python home of the PUA /
control-char normalization map, name-aligned with the OEQ donor's
``normalize_pua``. The canonical table is
``tools/glyph-normalization/table.v1.json`` — no second map anywhere.

Faithful port of the frozen Phase-B driver semantics
(``tools/glyph-normalization/phase_b_apply.py`` ``normalize_factory``, parser
@ 935bbd0): byte-exact replay of the bank patch of record (run-005, 2,949
rows). Cross-language conformance against the Java consumer
(``com.syllabai.parser.structure.glmocr.PuaNormalizer``) is enforced by the
glyph leg of ``conformance.py`` — 16/16 glyph fixture classes must stay green
or CI fails on drift (spec §7 conformance law).

Ordering law (spec §3.5, table ``ordering_law``): a single left-to-right
pass; sequence rules matched FIRST (longest sequence wins), then 1:1 single
entries; no re-scanning of replaced spans. Unobserved sequence lengths and
unmapped PUA codepoints pass through UNCHANGED — the born-clean census sees
them and the intake gate fails the batch (fail-closed, never silent serve).

Born-clean law (spec §7): a batch whose post-intake census still holds
PUA/C0 outside the table's mapped set fails the batch gate -> review, never
silent serve. Canary of record: ``C-intake-zero-pua`` — every real intake
batch must census PUA=0 post-normalization.

Run: python3 tools/glmocr/normalize_pua.py --help   (CLI for lanes/CI)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TABLE = REPO_ROOT / "tools" / "glyph-normalization" / "table.v1.json"

INTAKE_CANARY = "C-intake-zero-pua"

PUA_LO, PUA_HI = 0xE000, 0xF8FF


class TableError(Exception):
    """Canonical table missing, malformed, or sha-pinned drift."""


def load_table(path: str | Path | None = None, sha256: str | None = None) -> dict:
    """Load the canonical table; optionally pin its sha256 (fail-closed)."""
    p = Path(path) if path else DEFAULT_TABLE
    raw = p.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if sha256 and got != sha256:
        raise TableError(f"table sha256 drift: got {got}, pin {sha256}")
    try:
        table = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # malformed JSON fails closed
        raise TableError(f"table parse failed: {exc}") from exc
    entries = table.get("entries")
    seqs = table.get("sequence_rules")
    if not isinstance(entries, list) or not entries:
        raise TableError("table has no entries")
    if not isinstance(seqs, list):
        raise TableError("table has no sequence_rules list")
    for e in entries:
        if not isinstance(e.get("from"), str) or not e["from"].startswith("U+"):
            raise TableError(f"bad entry 'from': {e.get('from')!r}")
        to = e.get("to")
        if to is not None and to != "DROP" and not (isinstance(to, str) and to.startswith("U+")):
            raise TableError(f"bad entry 'to': {to!r}")
    for s in seqs:
        if not isinstance(s.get("from"), list) or not s["from"]:
            raise TableError(f"bad sequence rule 'from': {s.get('id')!r}")
        if not isinstance(s.get("to"), str) or not s["to"].startswith("U+"):
            raise TableError(f"bad sequence rule 'to': {s.get('id')!r}")
    return table


class CompiledTable:
    """A table compiled to the frozen-driver matching form (built once)."""

    def __init__(self, table: dict):
        # Ordering law: sequences longest-first, then 1:1 singles.
        self.seqs = sorted(table.get("sequence_rules", []), key=lambda s: -len(s["from"]))
        self.singles = {e["from"]: e for e in table.get("entries", [])}
        self._seq_decoded = []
        for s in self.seqs:
            self._seq_decoded.append(
                (s, [chr(int(cp[2:], 16)) for cp in s["from"]],
                 chr(int(s["to"][2:], 16)), s.get("id", "?")))
        self._single_decoded = {}
        for key, e in self.singles.items():
            to = e.get("to")
            if to in ("DROP", None):
                dec = None
            else:
                dec = chr(int(to[2:], 16))
            self._single_decoded[key] = dec

    # -- core law (byte-exact port of phase_b_apply.normalize_factory) ------

    def normalize(self, text: str) -> str:
        out: list[str] = []
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if PUA_LO <= ord(ch) <= PUA_HI:
                hit = None
                for s, seq_chars, seq_to, _sid in self._seq_decoded:
                    L = len(seq_chars)
                    if text[i:i + L] == "".join(seq_chars):
                        hit = (s, seq_chars, seq_to)
                        break
                if hit:
                    out.append(hit[2])
                    i += len(hit[1])
                    continue
                dec = self._single_decoded.get(f"U+{ord(ch):04X}")
                if dec is None and f"U+{ord(ch):04X}" not in self._single_decoded:
                    out.append(ch)  # unmapped PUA passes through — born-clean sees it
                elif dec is None:
                    pass  # DROP sentinel (or explicit null): delete
                else:
                    out.append(dec)
                i += 1
            elif "\x00" <= ch < "\x20" and ch not in "\t\n\r":
                out.append(" ")  # C0 control char -> single space (spec §3.4)
                i += 1
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    # -- born-clean census ---------------------------------------------------

    def census(self, text: str) -> dict:
        """Artifact census: PUA/C0 instances OUTSIDE the mapped set.

        Run on POST-normalization text this is the born-clean census: any
        nonzero ``unmapped_pua_instances`` fails the intake gate.
        """
        unmapped: dict[str, int] = {}
        c0: dict[str, int] = {}
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            cp = ord(ch)
            if PUA_LO <= cp <= PUA_HI:
                matched = False
                for _s, seq_chars, _to, _sid in self._seq_decoded:
                    L = len(seq_chars)
                    if text[i:i + L] == "".join(seq_chars):
                        i += L
                        matched = True
                        break
                if matched:
                    continue
                key = f"U+{cp:04X}"
                if key in self._single_decoded:
                    dec = self._single_decoded[key]
                    if dec is None:  # DROP class: consumed, not an artifact
                        i += 1
                        continue
                    i += 1
                    continue
                unmapped[key] = unmapped.get(key, 0) + 1
                i += 1
                continue
            if "\x00" <= ch < "\x20" and ch not in "\t\n\r":
                c0[f"U+{cp:04X}"] = c0.get(f"U+{cp:04X}", 0) + 1
            i += 1
        return {
            "unmapped_pua_instances": sum(unmapped.values()),
            "unmapped_pua_distinct": sorted(unmapped),
            "unmapped_pua_counts": dict(sorted(unmapped.items())),
            "c0_outside_mapped_instances": sum(c0.values()),
            "c0_distinct": sorted(c0),
        }

    def idempotence_delta(self, text: str) -> int:
        """normalize(normalize(x)) == normalize(x) — returns 0 when clean."""
        once = self.normalize(text)
        return 0 if once == self.normalize(once) else 1


_CACHE: dict[int, CompiledTable] = {}


def compile_table(table: dict) -> CompiledTable:
    """Compile (and memoize) a canonical table dict."""
    key = id(table)
    if key not in _CACHE:
        _CACHE[key] = CompiledTable(table)
    return _CACHE[key]


def _compiled(table) -> CompiledTable:
    return table if isinstance(table, CompiledTable) else compile_table(table)


def normalize_pua(text: str, table: dict | CompiledTable) -> str:
    """The canonical normalization (spec §7 name-aligned entry point)."""
    return _compiled(table).normalize(text)


def census_artifacts(text: str, table: dict | CompiledTable) -> dict:
    """Born-clean census of text against the canonical table."""
    return _compiled(table).census(text)


def intake_gate(texts, table: dict | CompiledTable) -> dict:
    """Born-clean batch gate (spec §7) — the C-intake-zero-pua canary.

    Every document of a batch must census PUA/C0 artifacts ZERO
    post-normalization. Any nonzero census FAILS the gate (born-clean law:
    review, never silent serve).
    """
    ct = _compiled(table)
    per_doc = []
    failed = []
    for idx, text in enumerate(texts):
        post = ct.census(ct.normalize(text))
        per_doc.append({"index": idx, **post})
        if post["unmapped_pua_instances"] or post["c0_outside_mapped_instances"]:
            failed.append(idx)
    return {
        "canary": INTAKE_CANARY,
        "documents": len(per_doc),
        "ok": not failed,
        "failed_documents": failed,
        "census": per_doc,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="T-MIG-141 Phase E intake law: canonical PUA/C0 normalization "
                    "(table.v1.json is the single map home)")
    ap.add_argument("inputs", nargs="*", help="input files ('-' or none = stdin)")
    ap.add_argument("--table", default=None, help=f"table path (default {DEFAULT_TABLE})")
    ap.add_argument("--sha256", default=None, help="fail closed unless the table sha256 matches")
    ap.add_argument("--census", action="store_true",
                    help="emit the born-clean census JSON instead of normalized text")
    ap.add_argument("--gate", action="store_true",
                    help="run the C-intake-zero-pua batch gate over all inputs; "
                         "exit 1 on any nonzero post-normalization census")
    args = ap.parse_args(argv)

    try:
        table = load_table(args.table, args.sha256)
    except TableError as exc:
        print(f"FAIL-CLOSED {INTAKE_CANARY}: {exc}", file=sys.stderr)
        return 2

    if args.gate:
        texts = [Path(p).read_text(encoding="utf-8") if p != "-" else sys.stdin.read()
                 for p in (args.inputs or ["-"])]
        result = intake_gate(texts, table)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["ok"] else 1

    for p in (args.inputs or ["-"]):
        text = Path(p).read_text(encoding="utf-8") if p != "-" else sys.stdin.read()
        if args.census:
            ct = _compiled(table)
            pre = ct.census(text)
            post = ct.census(ct.normalize(text))
            print(json.dumps({"input": str(p), "census_pre": pre,
                              "census_post": post, "idempotence_delta": ct.idempotence_delta(text)},
                             ensure_ascii=False, indent=1))
        else:
            sys.stdout.write(normalize_pua(text, table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
