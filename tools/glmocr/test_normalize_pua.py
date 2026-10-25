"""Tests for the T-MIG-141 Phase E intake law reference impl
(tools/glmocr/normalize_pua.py).

Layers:

1. unit tests over synthetic strings — singles, sequence rules
   (longest-first, unobserved lengths fail-closed), DROP class, C0
   space-fallback, unmapped-PUA pass-through, idempotence, born-clean census;
2. equivalence test against the FROZEN Phase-B driver of record
   (tools/glyph-normalization/phase_b_apply.py ``normalize_factory``) over a
   deterministic fuzz battery on the REAL canonical table — the intake law
   must replay the bank patch byte-exactly;
3. table pin test — the real table.v1.json shape (84 entries + 5 sequence
   rules) and the sha256 pin of record (1fdd4b4a...).

Run: python3 tools/glmocr/test_normalize_pua.py -v   (no network, no key)
"""

from __future__ import annotations

import hashlib
import importlib.util
import random
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent.parent
sys.path.insert(0, str(TOOLS))

import normalize_pua as npu  # noqa: E402

TABLE_PATH = REPO_ROOT / "tools" / "glyph-normalization" / "table.v1.json"
TABLE_SHA256_OF_RECORD = "1fdd4b4a"  # first 8 of the run-005 driver pin


def _load_real_table():
    return npu.load_table(TABLE_PATH)


def _load_frozen_factory():
    spec = importlib.util.spec_from_file_location(
        "t141_phase_b_apply", REPO_ROOT / "tools" / "glyph-normalization" / "phase_b_apply.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    table = mod.load_table(str(TABLE_PATH))
    return mod.normalize_factory(table)[0]


class TestTableShape(unittest.TestCase):
    def test_real_table_loads_and_pins(self):
        raw = TABLE_PATH.read_bytes()
        self.assertTrue(hashlib.sha256(raw).hexdigest().startswith(TABLE_SHA256_OF_RECORD))
        table = _load_real_table()
        self.assertEqual(len(table["entries"]), 84)
        self.assertEqual(len(table["sequence_rules"]), 5)

    def test_sha_pin_fail_closed(self):
        with self.assertRaises(npu.TableError):
            npu.load_table(TABLE_PATH, sha256="0" * 64)

    def test_malformed_table_fails_closed(self):
        bad = REPO_ROOT / "scratch" / "nonexistent-table.json"
        with self.assertRaises(Exception):
            npu.load_table(bad)


class TestSingles(unittest.TestCase):
    def test_every_mapped_single_translates(self):
        table = _load_real_table()
        ct = npu.compile_table(table)
        for e in table["entries"]:
            if e.get("to") in ("DROP", None):
                continue
            src = chr(int(e["from"][2:], 16))
            want = chr(int(e["to"][2:], 16))
            self.assertEqual(ct.normalize(f"x{src}y"), f"x{want}y",
                             f"{e['from']} -> {e['to']}")

    def test_drop_class_deletes(self):
        ct = npu.compile_table(_load_real_table())
        self.assertEqual(ct.normalize("a\uF0A2b"), "ab")  # F0A2 answer-line furniture

    def test_unmapped_pua_passes_through(self):
        ct = npu.compile_table(_load_real_table())
        # U+F0FF is not in the table and not in any sequence rule
        self.assertNotIn("U+F0FF", ct.singles)
        self.assertEqual(ct.normalize("\uF0FF"), "\uF0FF")
        census = ct.census("\uF0FF")
        self.assertEqual(census["unmapped_pua_instances"], 1)

    def test_ctl_space_fallback_and_whitespace_trio(self):
        ct = npu.compile_table(_load_real_table())
        self.assertEqual(ct.normalize("a\x03b\x1fc"), "a b c")
        self.assertEqual(ct.normalize("a\tb\nc\rd"), "a\tb\nc\rd")


class TestSequences(unittest.TestCase):
    def test_all_five_sequence_rules(self):
        ct = npu.compile_table(_load_real_table())
        cases = {
            "SEQ-A1": ("\uF075\uF075\uF075\uF072", "\u2192"),
            "SEQ-A2": ("\uF075\uF075\uF075\uF075", "\u2192"),
            "SEQ-A3": ("\uF075" * 8, "\u2192"),
            "SEQ-B4": ("\uF067" * 4, "\u2192"),
            "SEQ-B5": ("\uF067\uF067", "\u2192"),
        }
        for sid, (src, want) in cases.items():
            self.assertEqual(ct.normalize(src), want, sid)

    def test_unobserved_run_length_fail_closed(self):
        ct = npu.compile_table(_load_real_table())
        # F075 x5: SEQ-A2 consumes 4, the 5th shaft has no rule and no single
        # -> passes through; the born-clean census sees exactly 1 artifact
        out = ct.normalize("\uF075" * 5)
        self.assertEqual(out, "\u2192\uF075")
        self.assertEqual(ct.census(out)["unmapped_pua_instances"], 1)

    def test_longest_sequence_wins(self):
        ct = npu.compile_table(_load_real_table())
        # F067 x4 must match SEQ-B4 (len 4) before B5 (len 2) twice
        self.assertEqual(ct.normalize("\uF067" * 4), "\u2192")

    def test_end_of_string_partial_run_no_crash(self):
        ct = npu.compile_table(_load_real_table())
        # a run head at the exact end of the string must not crash and must
        # not match a longer rule than the available text: F075 x3 matches NO
        # rule (SEQ-A1 needs the F072 head, A2 needs 4 shafts, A3 needs 8)
        # -> all three pass through fail-closed
        out = ct.normalize("\uF075\uF075\uF075")
        self.assertEqual(out, "\uF075\uF075\uF075")
        self.assertEqual(ct.census(out)["unmapped_pua_instances"], 3)


class TestBornCleanGate(unittest.TestCase):
    def test_gate_passes_on_mapped_text(self):
        table = _load_real_table()
        res = npu.intake_gate(["84 \uF02D 69 \uF0B4 2 = \uF075\uF075\uF075\uF075"], table)
        self.assertTrue(res["ok"])
        self.assertEqual(res["canary"], "C-intake-zero-pua")

    def test_gate_fails_on_unmapped_artifact(self):
        table = _load_real_table()
        res = npu.intake_gate(["clean", "dirty \uF0FF tail"], table)
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed_documents"], [1])
        self.assertEqual(
            res["census"][1]["unmapped_pua_distinct"], ["U+F0FF"])

    def test_canary_name_pinned(self):
        self.assertEqual(npu.INTAKE_CANARY, "C-intake-zero-pua")


class TestFrozenDriverEquivalence(unittest.TestCase):
    def test_byte_equivalence_on_fuzz_battery(self):
        """normalize_pua must replay the frozen Phase-B driver byte-exactly.

        Comparison law: frozen(s + "Z") == reference(s) + "Z" for plain-ASCII
        sentinel "Z". The sentinel cannot complete any sequence rule (every
        rule element is PUA) and prevents the frozen driver's IndexError on
        strings that end mid-run — the one crash class where the frozen
        driver is undefined and the reference impl is defined (slice match).
        """
        table = _load_real_table()
        ct = npu.compile_table(table)
        frozen = _load_frozen_factory()
        rng = random.Random(141141)  # deterministic battery
        pool = ["\uF02D", "\uF0B4", "\uF0A2", "\uF075", "\uF072", "\uF067",
                "\uF084", "\uF0B1", "\uF0CF", "\uF0E6", "\uF0F8", "\uF8EB",
                "\uF0FC", "\x03", "\x1f", "\t", "\n", "\r", "a", "9", " ",
                "=", "(", "\u03c0", "\u2192", "\u0338"]
        boundary_crashes = 0
        for trial in range(400):
            n = rng.randint(0, 60)
            s = "".join(rng.choice(pool) for _ in range(n))
            try:
                frozen(s)  # raw probe: is the frozen driver even defined on s?
            except IndexError:
                boundary_crashes += 1  # frozen driver undefined: ends mid-run
            want = frozen(s + "Z")  # sentinel form: always defined
            got = ct.normalize(s) + "Z"
            self.assertEqual(got, want, f"trial {trial}: {s!r}")
        # the battery must actually exercise the boundary crash class
        self.assertGreater(boundary_crashes, 0)

    def test_frozen_boundary_indexerror_documented(self):
        """The frozen driver IndexErrors on an end-of-string partial run;
        the reference impl is defined there (fail-closed pass-through)."""
        frozen = _load_frozen_factory()
        ct = npu.compile_table(_load_real_table())
        s = "\uF075\uF075\uF075"  # SEQ-A1 needs the F072 head at index 3
        with self.assertRaises(IndexError):
            frozen(s)
        self.assertEqual(ct.normalize(s), "\uF075\uF075\uF075")
        self.assertEqual(ct.census(ct.normalize(s))["unmapped_pua_instances"], 3)

    def test_bank_sample_replay(self):
        """A real run-002b context string replays to the live bank bytes."""
        ct = npu.compile_table(_load_real_table())
        # "(ii) ... <F0CF> ... 1 B1" carrier-row shape (run-004 ruling):
        self.assertEqual(ct.normalize("(ii) \uF0CF 1 B1"), "(ii) \u2209 1 B1")


class TestIdempotence(unittest.TestCase):
    def test_idempotent_on_mixed_input(self):
        ct = npu.compile_table(_load_real_table())
        s = "y = \uF070(\uF075\uF075\uF075\uF075x + 4) for 0.25 \uF084 x \uF085 8 \uF0A2 *P68726A0328*"
        self.assertEqual(ct.idempotence_delta(s), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
