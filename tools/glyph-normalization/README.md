# glyph-normalization — the canonical map home (T-MIG-141 Phase A)

`table.v1.json` is the SINGLE home of the PUA/control-char normalization map for the
SyllabAI parsing plane. Every future OCR / extraction batch normalizes at intake
through this table (Phase E intake law, SPEC-T-MIG-141 §7); the Neon `document_chunks`
bank patch (Phase B) consumes the same table — no second map anywhere.

## Provenance

- Task: **T-MIG-141** (syllabai-v2 `.syllabai/tasks/T-MIG-141-glyph-normalization.yaml`,
  spec `docs/SPEC-T-MIG-141-GLYPH-NORMALIZATION.md` @ syllabai-v2).
- Built 2026-10-23 by lane r7a (operator order trace 1a1686907a2d0855, claim run-001).
- Donor base: `syllabai-resources` Official-ExamQuestion `PUA_MAP`
  (`scripts/official_examq_extract.py`, resources main `1ef9d5b8`, converter sha
  `b114f47a`) — imported per spec §3.1 precedence 1. The donor repo is **not** an
  edit surface (one-way provenance).
- Census of record: wired exam-paper plane = 2,765 chunks / 25,399 PUA instances /
  85 distinct codepoints, sha256 `5c18c01e15e918cb36a8609a2c2ae6dbdb806ad3a5738822299c3c070c8c63d2`
  (syllabai-v2 receipt `run-001-claim-census-reverify.json`).

## Evidence standard (F48 transposed, spec §3.3)

An entry lands only with: rendered proof @150 dpi (CROP-REVIEW pattern), census
match, canary pin, and (at Phase-B dry-run) the wrong-map disproof probe. Evidence
artifacts for v1: `evidence/T-MIG-141/sheets/sheet{1,2,5,6,7}.png` (labeled
adjudication contact sheets) + `evidence/T-MIG-141/crops/<CP>_representative.png`
(one render crop per codepoint). Every mapped char is what the printed page shows.

## v1 shape

- 61 entries: 18 OEQ-base re-verified by our renders, 25 newly evidenced (Symbol
  law confirmed: π θ ω μ Σ ≥ ≤ ≠ ∝ ∅ ∩ ∪ ∠ ∞ ⇒ ◊ { } [ ] ( ) < > = + − × ÷ ± °),
  12 bracket-piece entries landed via the deterministic positional law (x-column
  clustering + y-order votes: F0E6/E7/E8 = big-paren left top/ext/bottom →
  U+239B/239C/239D, F0F6/F7/F8 = right → U+239E/239F/23A0, F0E9/EA/EB = big-bracket
  left → U+23A1/23A2/23A3, F0F9/FA/FB = right → U+23A4/23A5/23A6), 1 drop class
  (F0A2 answer-line furniture, C7-exception disclosed), 7 OEQ-donor entries with
  our-render corroboration pending run-002.
- `pending_register`: 20 codepoints / 796 instances NOT mapped (fail-closed —
  unmapped PUA is never silently served). Biggest classes: the composed
  long-arrow runs (F026/F067/F072/F075 — shaft+head glyph runs; F072 also carries
  an OEQ Delta conflict to adjudicate) and the suspected big-brace family
  (F8EB/F8EC/F8ED + F8F6/F8F7/F8F8, exact L/R count pairing).

## Consumers (Phase E wiring — later phases)

- Python reference impl `normalize_pua(text, table)` (tools/glmocr/), consumed by
  tools/ocr_batch/ at intake.
- Java consumer (GlmOcrPaperAtomizer path) reads the same JSON — no second map.
- Conformance: each table class gets a fixture pair in the py/java conformance
  harness; born-clean law: a batch whose post-intake census holds PUA outside the
  mapped set fails the batch gate.

## run-002b (2026-10-24) — pending register resolved + v1 hole closed

- **22 new single entries + 5 `sequence_rules`** (composed over-arrow runs, ordering law
  §3.5: sequences longest-first before singles). Table now: 83 entries, 5 sequence rules.
- **Register 21 items → 22 resolutions**: 18 mapped (render-evidenced), F072 split
  (SEQ-A1 head in 4MA1 runs vs standalone U+2206 in 4CH1 — OEQ-Delta conflict dissolved),
  F0A6 closed-zero, **U+F0CF re-carried fail-closed** (no-ink glyph, 2 inst, not nameable
  at the F48 standard).
- **V1 hole disclosed**: the v1 register listed 774 unmapped instances; the true unmapped
  set was 1,691. The census-match law (spec §3.3) found **917 further instances in 5 CPs
  (F084 520 / F0B1 392 / F033 2 / F050 1 / F0CF 2) with NO entry and NO register item**.
  915 now mapped; F0CF fail-closed.
- **F084 spec-sqrt hypothesis OVERTURNED**: 520/520 inequality placements prove `≤`
  (complementary pair with F085=`≥`); the radical is vector-drawn (no text-layer char).
- **Post-state**: wired-bank PUA coverage 25,397/25,399 (99.99%); residual = U+F0CF ×2.
- Evidence: `sheets/sheetB1..B5*.png` + `crops-run002b/` (75 crops @150dpi) +
  `run002b/` (contexts, run patterns, render manifest, probes, validation).
- Sequence-rule consumption EXACT: SEQ-A1 ×15, SEQ-A2 ×30, SEQ-A3 ×1, SEQ-B4 ×7, SEQ-B5 ×2;
  C7 deletion disclosure: 165 chars collapsed across 55 runs + drop class 5,146.
