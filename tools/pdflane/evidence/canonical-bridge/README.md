# Canonical bridge evidence — atoms/1.1 → retrieval index (dry run)

**Date:** 2026-09-20 (Asia/Dhaka session). **Tool:** `pdflane.atoms_to_canonical`
(engine `pdflane-atoms/1.1.0`). **Scope:** all chemistry lane products in
`syllabai-pastpapers` (11 papers), full artifacts in the working mirror
`tc17-work/pdflane/canonical-v1/` (not committed — derivable, deterministic).

## What ran

Every `parsed/` product was converted into TWO canonical schema-1.0 documents
(`QUESTION_PAPER` + `MARK_SCHEME`) that core ingests unchanged via
`POST /api/v1/teacher/content/documents`:

- QP: stem + part prompts (text/tables/figures/choices), sections = questions;
  pages marker-aligned against `qp.md` with per-figure exact pages.
- MS: connected mark points (marks + allow/reject/ignore/notes), guidance,
  levels bands, MS figure answers; real per-point pages from the atoms product.

## Results (summary.json)

- 11/11 papers converted; canonical validator mirror green on all 22 documents.
- Identity: source = the original PDFs (sha256 recomputed AND cross-checked
  against every manifest — 11/11 manifests carried both checksums); 22/22
  unique documentIds (UUID-v5 layout, shared `CanonicalIdentity` formula).
- Page alignment: 0 opener fallbacks, 0 inherited blocks corpus-wide — every
  QP block anchored to a real `<!-- PAGE N -->` marker page.
- Chunk preview (core `ChunkingService` mirror, 300/800 tokens): 110 QP +
  124 MS = 234 chunks corpus-wide; deterministic byte-identical re-runs.
- Leakage guard: QP documents carry zero answer content (key-scan + role scan).

## Dedup / coexistence note for the operator

The legacy OCR lane ingested markdown sources (`text/markdown`, checksum of
the .md). This bridge pins identity to the ORIGINAL PDFs
(`application/pdf`) — a different checksum space — so atoms-derived documents
do not dedup-collide with the 172 legacy documents already in production;
both can coexist until the index is curated (T-C07 scoping / embedding
backfill projection decide what is servable).

## Test coverage

`python3 -m pdflane.tests_atoms_canonical` — 23 tests green (identity
lockstep with the audited glmocr mirror, validator rejections, chunk-mirror
equivalence, page alignment, leakage guard, synthetic full round-trip,
manifest-mismatch refusal, determinism, corpus smoke over all 11 products).

## Honest limits

- No Java runtime in this sandbox: validator/chunker behavior is proven by a
  faithful Python mirror + the shared derivation implementation, not by
  executing core. First real ingest (CI or a Maven lane) is the final word.
- `marksVerified` reflects each product's own state (flagged papers remain
  flagged; the bridge does not hide product-level defects).
- Ingestion itself (POST, embeddings, exam_papers/questions rows) remains
  operator-gated; this run is the dry-run evidence for that gate.
