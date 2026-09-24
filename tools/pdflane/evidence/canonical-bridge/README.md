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

## Addendum — engine 1.1.1: retrieval headers (2026-09-20, same session)

Adopted the retrieval-header recommendation from the operator's parallel
design review: the first text-bearing element of every question section now
carries a deterministic paper-context prefix derived from manifest.yaml —
`[International GCSE Chemistry 4CH1 | June 2024 | Paper 1C | Question 7]`
(MS: `... | Mark scheme]`) — so embeddings themselves carry
subject/session/paper/question signal. Coverage: 99/99 questions across the
corpus (0 skipped). Chunk preview now 118 QP + 130 MS = 248 chunks (packing
shifts with header tokens); all 22 documentIds re-derived under engine
1.1.1 (version is part of the identity material) and remain 22/22 unique.

Known limit: chunks that start mid-question inherit no header — guaranteed
header-per-chunk is a core-side projection (ChunkingService + sections);
recommended follow-up to coordinate with the core lane.

## Addendum — engine 1.2.0: the corpus-v2 bridge release (2026-09-20, retrieval lane)

The 1.1.1 text-prefix header is **superseded by structure** in the single
release the corpus-v2 ingest was waiting for (one release = one clean
embed_rev=2 ingest — no wasteful embed_rev=3 re-supersession):

1. **Doc-level `retrieval` block** (`{subjectTitle, subjectCode, series,
   year, paperCode, label, unit, specCodes}`) derived deterministically from
   manifest.yaml. `series` is canonicalized to JAN/JUN/NOV (Summer→JUN;
   unrecognized stays null — never a raw label, plan §12 #7). `subjectCode`
   resolves into core's subjects table at ingest (a present-but-unresolvable
   code fails LOUD there); the documented 4CH0→4CH1 alias maps pre-2016
   papers onto the pilot subject while `paperCode` keeps the vintage
   (`4CH0/1C` — production exam_papers format). `specCodes` stays null by
   design: spec tagging is the taxonomy lane's join on `paperDir#qN`, never
   baked into documents.
2. **Per-element `group_key`** (`q1`, `q2`, …) on every element of every
   question section — core R2 treats a group-key change as a HARD chunk
   boundary (no chunk crosses an atom), stamps `atom_number`, and projects a
   per-chunk header (`4CH1/1C Paper 1C JUN 2024 Q3 pp.4-5`; MS: `MS Q3`) from
   the metadata columns onto EVERY chunk. The chunk preview mirror implements
   the same boundary rule (legacy no-group-key shapes pack unchanged).
3. **G3 render-level furniture exclusion**: known Edexcel boilerplate ("DO
   NOT WRITE IN THIS AREA", "Answer ALL questions.", cross-in-box instruction
   paragraphs, "Total for Question N = X marks" stem echoes) is classified at
   RENDER time (whole-block conservative matching) and excluded from the
   canonical documents with per-doc counters in extractionParams. Parse-level
   products are NEVER touched — atoms stay complete, "Total for Question N"
   rows remain G1 witnesses, and column-bleed-glued fragments survive.
4. **G4 figure alt-text**: an empty-alt figure pulls the nearest same-question
   `Figure/Graph/Diagram N` caption deterministically; every figure WITH an
   alt emits an adjacent `role="figure_alt"` text block `[figure: <alt>]` so
   the chunker (which packs text blocks, not figure elements) carries visual
   signal into the embeddings. No caption + no alt ⇒ honest empty.

Engine version is identity material: all 22 documentIds re-derive under
1.2.0 (the new docs cannot collide with the 1.1.1 dry-run id space). The
v1.1.1 prefix is REMOVED in the same commit that adds the structured
replacement — embeddings must not double-carry the same signal now that core
stamps every chunk from metadata.

Test coverage: `python3 -m pdflane.tests_atoms_canonical` — 42 tests green
(25 pre-existing incl. the round-trip now asserting retrieval/group_key, plus
17 new: retrieval-meta derivation matrix + alias + validator-mirror
rejections, group-key boundary packing, furniture render exclusion with
product-file-untouched proof, figure alt resolution). The 11-product corpus
smoke re-runs green wherever the pastpapers checkout is present.
