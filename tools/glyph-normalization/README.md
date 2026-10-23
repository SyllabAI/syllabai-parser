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

## run-004 (2026-10-24) — operator ruling: U+F0CF resolved, register EMPTY

- **Ruling of record (trace 1a169e3fdeaecd11)**: `U+F0CF → U+2209` (NOT AN ELEMENT OF),
  map class. Table now: **84 entries, 5 sequence rules; pending register EMPTY**.
- **Decisive evidence (300dpi, both MuPDF and poppler)**: the glyph renders as a visible
  element-of-with-slash in the Answer column of the 4MA1 JUN 2025 1FR (p15) / 1HR (p8)
  marks grids, each row `… ∉ … 1 B1` — a markable **set-notation answer**, sibling to the
  landed family F0C6=∅, F0C7=∩, F0C8=∪, F0D0=∠ (same SymbolMT plane; F0CE=∈ has zero bank
  instances). Grayscale tight-box ink min=0, mean ~219 (≈ empty-set control ~218).
- **Operator's offered option set refuted**: map-as-space (blanks a markable answer),
  Phase-C re-parse (disproportionate — text layer repairable in place; ADR-037 authorship
  risk for zero gain), leave (rests on the overturned no-ink premise).
- **run-002b "no-ink @300dpi" verdict = probe crop-placement artifact** (both renderers
  draw the glyph at the correct pdftotext bbox); disclosed, unreconstructible; the
  run-002b register note ("spacer or unattributable arc") is OVERTURNED.
- **Full-bank re-simulation vs the ruled table (zero DB writes)**: residual PUA = **ZERO**
  (wired-bank coverage **25,399/25,399, 100%**); G-B 0 violations; G-D 2,949/2,949 rows
  artifact-free; G-C EXACT (subs 20,033 = run-003 pin 20,031 + F0CF 2, drop 5,146, seq
  15/30/1/7/2, ctl 2,000, len_delta −5,311); idempotence green; C9 id-set sha256 and the
  200-row control group identical to the run-003 pins (bank undrifted).
- Evidence: `crops-run004-f0cf/` (tight/band/gridblock renders both papers + poppler
  cross-render + probe JSON). Receipt: syllabai-v2 `.syllabai/receipts/T-MIG-141/run-004/`.

## run-005 — Phase-B real-write driver of record (`phase_b_apply.py`)

The operator's "Go" (trace `1a169fc63e946759`) fired the Phase-B real write via the
CI gate. This directory now carries the **frozen deterministic driver** mandated by
spec §4.2 (no LLM, ADR-037):

- **`phase_b_apply.py`** (sha256 `b0697399dbd733afcbc669cb768233e8c88aa1c12cf43c56a39b9809399512f0`,
  pinned in the v2 workflow) — modes `verify` (read-only pre-gates + in-memory
  simulation) and `apply` (ONE transaction per paper-batch with per-batch
  post-gates before commit; fail-closed restore from before-images on any gate
  failure, spec §4.3).
- **Pins inside the driver (all hard-fail)**: table sha256 `1fdd4b4a…2094a` (this
  repo @ `d9c1511`), C9 id-set sha `4014404b…c037`, before-images uncompressed sha
  `9d9d84c6…84e3b` + the run-003 `.gz` artifact sha `a542c75e…4aafb`, control-group
  file sha `a05652a9…300d`, embed pre-state `{2: 2949 / no_vec 273}`, G-C accounting
  EXACT (subs 20,033 / F0CF 2, drop 5,146, seq 15/30/1/7/2 = 220 chars, ctl 2,000,
  len_delta −5,311, insertions 0), idempotence 0.
- **Lane-side verify preflight (2026-10-24, zero writes, t0_readonly)**: ALL GREEN —
  scope 2,949 rows, C9 pin-exact, before-images pin-exact, control group identical,
  G-C simulation EXACT. Receipt: lane scratch `run005-verify/verify-receipt.json`.
- **Runner of record**: syllabai-v2 `.github/workflows/t-mig-141-phase-b.yml` —
  job 1 COW-branch proof (apply + full post-gates + DROP + 404-verify, `if: always()`),
  job 2 prod-apply behind `needs: cow-proof` green. Patch law: `content` ← mapped
  text, `embed_rev` ← 1 stale marker (vectors KEPT serving; Phase D restores 2),
  `content_tsv` GENERATED ALWAYS auto-refresh asserted post-write.
