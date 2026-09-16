# Corpus Operations (`tools/corpus_ops/`)

Stage A/A′ corpus acquisition & organization tooling — T-C16 in the master workbook.
Design: `SyllabAI/syllabai/CORPUS_OPS_TOOLING_DESIGN.md` (ratified 2026-09-17, §12).
Sibling of `tools/ocr_batch/` (same output convention, different entry point: ocr_batch
works **from PDFs at OCR time**, corpus_ops works **on already-converted markdown,
retroactively, any time**).

```text
raw GLM-OCR markdown (signed-URL image refs, ~1 week to expiry)
        │
        ▼
corpus_ops intake ── pair proposal (read-only) ── operator confirm ──┐
        │  same-second concurrent download · MIME sniff · dimensions  │
        ▼                                                             ▼
<corpus-root>/<paper>/<year>-<Mon>[-R]/QP.md + MS.md + assets/  +  MANIFEST.json (v1.1)
        │
        ├─ operator deletes unwanted crops (CSV or assets/_deleted/ staging)
        ▼
corpus_ops scrub ── whole-island reference removal · checksum recompute · orphan ledger
        │
        ├─ Stage B clean-and-verify (T-C17) produces clean/ + clean-report.json
        ▼
corpus_ops verify ··· clean_diff.py (gate G3) ··· GlmOcrPairCli → T-C02 ingestion
```

## Commands

```bash
# 1) pair proposal — READ-ONLY, mutates nothing; exam identity is never inferred
python3 tools/corpus_ops/corpus_ops.py intake <raw-folder> -o <corpus-root> \
    --paper "paper 1" --mapping sessions.csv          # sessions.csv: filename,session

# 2) confirmed intake — downloads every referenced image BEFORE expiry, organizes
python3 tools/corpus_ops/corpus_ops.py intake <raw-folder> -o <corpus-root> \
    --paper "paper 1" --mapping sessions.csv --confirm pairing-proposal.json

# 3) post-operator-deletion scrub (CSV or staging; both fail-closed)
python3 tools/corpus_ops/corpus_ops.py scrub <corpus-root> \
    --paper "paper 1" --deletions deletions.csv       # session,asset_filename[,operator_note]
python3 tools/corpus_ops/corpus_ops.py scrub <corpus-root> --from-staging

# 4) read-only agreement checks (exit 1 on any FAIL-class finding)
python3 tools/corpus_ops/corpus_ops.py verify <corpus-root> --paper "paper 1"

# 5) fix provisional UNIDENTIFIED-* sessions (proposal/confirm, like intake)
python3 tools/corpus_ops/corpus_ops.py rename <corpus-root> --mapping renames.csv
```

`--dry-run` exists for every mutating command and prints the exact planned mutation
set. Exit codes: `0` green · `1` FAIL-class finding · `2` usage error.

## Stage B gate G3

```bash
python3 tools/corpus_ops/clean_diff.py \
    --qp-raw raw/qp-draft.json --qp-clean clean/qp-draft.json \
    --ms-raw raw/ms-draft.json --ms-clean clean/ms-draft.json \
    --json-out clean/gate-G3.json
```

Machine-checkable subset of T-C17 §9 G3: question count ≤, shared
`(number, part_label, marks)` identical, MS mark-point count ≤, no new warning classes
except `boilerplate-removed`, `paperTotalConflict` false-or-unchanged. Element ids are
deliberately not compared (they shift by construction). The "explainable line-by-line"
requirement stays human-audited (T-C17 §13).

## Honesty rules baked in (do not weaken)

- Pair detection is convenience; **the operator confirm is the pairing authority**.
  Exam/session identity is never inferred from document content (Past-Papers
  `AGENT.md` rule 2).
- Download failures are **recorded, never retried silently into success** — attempts,
  error classes and timestamps land in `MANIFEST.download_failures[]`; an unavailable
  image keeps its URL reference in the markdown (the T-C02 honesty pattern).
- Asset filename collisions hard-FAIL unless the bytes are sha256-identical (then one
  deduped asset). No silent overwrites, ever.
- Scrub removal is whole-line island removal of the verified single-line form
  `<div style='text-align: center;'><img src='assets/crop_…' …/></div>`; a reference
  found outside a pure island line aborts the batch rather than being partially edited.
- Orphan detection after scrubbing: any remaining reference with neither a file nor a
  removal record is a hard FAIL with the full ledger.
- Removed images keep their **original URLs** in the `ops_log[]` entry — provenance
  survives deletion (the 2026-09-11 `operator_cleanup` precedent).

## MANIFEST v1.1 (additive)

Legacy `paper 1/MANIFEST.json` keys are canonical and preserved. v1.1 adds
`schema_version`, `ops_log[]`, `clean{}`, per-image `mime`/`width_px`/`height_px`,
per-document `size`. The writer is deterministic (same inputs → byte-identical file,
modulo the epoch, which is pinnable via `CORPUS_OPS_EPOCH_UTC` under tests).

## Tests

```bash
python3 tools/corpus_ops/test_corpus_ops.py
```

Mocked HTTP + fixture tree, no network, no keys: intake happy path, failure recording,
collision/dedupe rules, whole-island scrub with adjacent-table/fence safety, double-scrub
+ idempotent replay, staging mode, orphan hard-FAIL, verify checks, rename
proposal/confirm, legacy manifest round-trip, clean_diff accept/reject matrix, manifest
determinism. Rollout gate (owner-held): dogfood on the next ocr.z.ai conversion batch
**before** it touches `Past-Papers`; replay the historical `paper 1/` manifest records
as the integration oracle.
