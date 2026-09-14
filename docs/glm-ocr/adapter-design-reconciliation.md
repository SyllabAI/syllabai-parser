# GLM-OCR Adapter Design — Real-Corpus Reconciliation

**Date:** 2026-09-05 (Session 8)
**Method:** the Session 7 design propositions (preserved in
`GLM_OCR_CONTENT.md` here and `EXAM_CONTENT_ARCHITECTURE.md` in
`SyllabAI/syllabai`; the original `glm-ocr-adapter-design.md` draft was lost
with the prior workspace and is reconstructed from those committed summaries)
are checked one-by-one against the audited corpus
(`docs/glm-ocr/real-corpus-syntax-report.md`, evidence-first).

Verdicts: **CONFIRMED** (real corpus matches), **REVISED** (design assumption
must change), **NOT FOUND** (design expects something the corpus does not
contain), **NEWLY DISCOVERED** (real-corpus fact absent from the design).

---

## 1. Reconciliation table

| # | Session 7 design proposition | Verdict | Real-corpus evidence |
|---|---|---|---|
| 1 | "Question papers and mark schemes were converted to Markdown using Z.ai GLM OCR" | **CONFIRMED** | 6 files, 3 QP/MS pairs, WPH11; export stamps 2026-03-31 |
| 2 | "with the extracted images retained alongside each Markdown file" | **NOT FOUND / REVISED** | `GLM-markdown-sample/` contains **zero image binaries**; images exist only as expiring signed URLs (all dead: HTTP 401, expired 2026-04-07). 10 orphaned `ocr_crop_*.png` exist in `IAL/Edexcel/Physics/Unit 4/` from a *different* (July 2026) OCR session with no Markdown counterpart |
| 3 | "This corpus … should not be discarded or unnecessarily re-OCRed" | **CONFIRMED (qualified)** | Markdown text/structure is rich and usable; but **visual fidelity requires a re-export with images saved** — text-only use needs no re-OCR |
| 4 | Normalize GLM-OCR representation into the canonical document contract | **CONFIRMED (feasible)** | Line-oriented parse + HTML islands + `$$` blocks map cleanly onto TEXT_BLOCK/TABLE/FIGURE/EQUATION (syntax report §6) |
| 5 | Preserve "Markdown/source provenance" | **CONFIRMED (design) + implementable** | Source URI + SHA-256 of the exact markdown bytes; file name carries export timestamp |
| 6 | Preserve "image references and stable asset identities" | **REVISED** | The only durable identity is the **URL path** (`…/ocr%2Fcrop%2F<session>%2Fcrop_<n>_<millis>.png`); SHA-256-of-bytes identity (the Session 7 rule) is **not computable** for this corpus because bytes are gone. Identity rule: SHA-256 of bytes when bytes exist; URL path as `source_name` + `availability=unavailable` when they do not |
| 7 | Preserve "page associations" | **NOT FOUND** | No page markers in the Markdown; `Turn over` / `## BLANK PAGE` are not page boundaries. Adapter must record `pageCount=1` + provenance `pageBoundaries: none-in-source` instead of inventing pages |
| 8 | Preserve "question and question-part boundaries" | **CONFIRMED with two styles** | `1:` (June) vs `1 ` (October) both real; parts `(a)`, `(b)(i)`, three levels in 1A; asterisk QWC `*(c)` / `*14`. Existing generic regexes miss the colon style — dedicated GLM-OCR segmenter required |
| 9 | Preserve "equations" | **CONFIRMED with defects** | Inline `$…$` and `$$` blocks present, but with documented corruption (spaced digits, undelimited LaTeX in cells, stray `$`) — preserve raw, never silently repair |
| 10 | Preserve "tables" | **CONFIRMED** | HTML tables incl. `rowspan`/`colspan`; MS answers are table-first (3/4-col + IC tables) |
| 11 | Preserve "reading order" | **REVISED** | Mostly linear but at least one real corruption (option B before A); reading order is trustworthy only with a `reviewRequired` flag |
| 12 | Preserve "source document/version identifiers" | **CONFIRMED** | Paper refs (WPH11/01, WPH11/01A), log numbers (P78753A…), publication codes (WPH11_01_2506_MS) extractable from content — but cover *shape* varies (image/table/text), so identity must be content-derived |
| 13 | "Automated question boundaries remain drafts until validated" (T-011 spillover lesson) | **CONFIRMED and reinforced** | MS boilerplate + heading-promoted totals + page-furniture figures all leak into the question stream; every extracted structure stays SUGGESTED/reviewRequired |
| 14 | Images are "first-class content … diagrams, graphs, chemical structures, apparatus" | **REVISED (for this corpus)** | The reference stream mixes semantic figures with covers/answer-boxes/blank-page crops and *cannot be classified from the Markdown alone*; first-class pipeline is right, but current corpus can only supply unavailable references |
| 15 | Storage rule: frontend never depends on parser filesystem paths; large binaries in object storage | **CONFIRMED (unchanged)** | Consistent with canonical FigureElement design (references, not bytes) |
| 16 | QP/MS pairing is available for ingestion | **CONFIRMED** | 3 pairs match by content (paper ref, log number, session); no machine-readable manifest exists — pairing must be derived and verified (mismatch → review, never silent fix) |

## 2. NEWLY DISCOVERED facts the design must absorb

1. **Signed-URL image hosting with ~1-week expiry** — any future re-export must
   save images locally at export time; the adapter treats all GLM-markdown-sample
   figures as `unavailable` and never attempts to fetch dead URLs during parse.
2. **`alt='OCR图片'`** — fixed Chinese alt text, zero semantic value; do not
   propagate as accessible alt.
3. **Two question-number syntaxes** (`1:` vs `1 `) *across papers of the same
   board and subject* — the segmenter records which style matched per document.
4. **Mark-scheme totals in two places** (standalone lines vs in-table rows) and
   two spacings (`Question 11=3` vs `Question 1 = 1`).
5. **Marking-semantics vocabulary is richer than designed**: Allow / Ignore /
   dependent-on-MP / ecf / credit / Any-two-from / Or alternatives / `MP1..3`
   identifiers / `Example calculation` exemplars / IC level tables — all real
   and all must survive into MarkPoint metadata, not be flattened to text.
6. **QWC asterisk appears at part level in QPs (`*(c)`) and question level in
   MS tables (`*14`)** — the marker is position-dependent.
7. **A paper variant family exists** (WPH11/01 vs WPH11/01A — 80 vs 120 marks,
   different log numbers) — paper identity must use the *full* paper reference,
   not subject+unit+session alone.
8. **Corpus history**: an earlier 2026-03-19 Markdown batch inside paper
   directories was deleted 2026-08-08; the current sample is a clean re-add.
9. **Orphaned crop assets** (Unit 4, July 2026) share the crop-naming shape —
   a future re-export pipeline should emit a manifest linking Markdown files
   to their image files.
10. **`## BLANK PAGE` / `Turn over`** exist but are not page boundaries.

## 3. Revised adapter design decisions (supersede Session 7 draft)

- **D1 Identity:** `documentId = UUID(correlated to SHA-256(source bytes))`
  (content-derived, deterministic); element ids positional `e%06d`; image
  asset identity = SHA-256(bytes) when available, else URL-path reference with
  `availability: unavailable`.
- **D2 Pages:** no invented pages; `pageCount=1`, provenance param
  `pageBoundaries=none-in-source`; page association restored only when a
  re-export or the source PDF linkage provides it.
- **D3 Segmentation:** GLM-OCR-specific QP segmenter (both number styles,
  MCQ option handling, part marks from centered `(N)` divs, totals from both
  placements); MS extractor is table-first with the §4.3 semantics vocabulary.
- **D4 Honesty:** every OCR defect class from syntax-report §5 is either
  preserved raw or explicitly flagged; normalized entity decoding is recorded
  in provenance `extractionParams.normalizedEntities=true`.
- **D5 Draft status:** all extracted questions/parts/mark points carry
  `reviewRequired=true` and confidence < 1.0 (Master Spec §7), consistent with
  T-011 behavior.
- **D6 Pairing:** QP/MS pairs derived from content identity (paper ref + log
  number + session); a mismatch produces a review/quarantine record, never a
  silent merge (QP/MS matching determinism rule).

## 4. Status of Session 7 artifacts

- `model-capability-registry.json` — lost locally; **never committed** to any
  repository. To be rebuilt in Session 8 as part of the syllabai-core LLM
  capability work (with the `minimax/minimax-m2.7:free` correction).
- `glm-ocr-adapter-design.md` — lost locally; superseded by this document
  plus the syntax report.
- `SyllabAI_Session7_Report.pdf` — lost locally; superseded by the Session 8
  evidence-based report.
- Committed design docs that survive and remain accurate after this audit:
  `SyllabAI/syllabai EXAM_CONTENT_ARCHITECTURE.md` (propositions 4, 5, 13–15
  above), `GLM_OCR_CONTENT.md` (pipeline role + storage rule),
  `syllabai-web/docs/QUESTION_CONTENT_RENDERING.md` (rendering boundary).

## 5. Addendum (2026-09-13): the re-export pipeline now exists

The open items above are no longer hypothetical — `tools/ocr_batch/`
(commits `b285526` + `9968263`, task IDs OCR-Q1/OCR-Q2) implements the
re-export pipeline this document asked for. Status per item:

| Open item | Status |
|---|---|
| NEWLY DISCOVERED #1 — signed-URL expiry, "any future re-export must save images locally at export time" | **Implemented** — the batch tool downloads every referenced crop the same second it is produced (`assets/`, website crop naming); a dead URL is recorded under `unfetchedAssets` and never blocks the text pipeline |
| NEWLY DISCOVERED #9 — "a future re-export pipeline should emit a manifest linking Markdown files to their image files" | **Implemented** — every export writes `manifest.json` (v1 single document / v2 pair) mapping markdown ↔ assets with SHA-256s, dimensions and warnings |
| D2 — page association restored "only when a re-export … provides it" | **Partially restored** — per-page markdown is preserved under `pages/` when produced page-by-page (API page-range chunks, Ollama per-page rasterization); sources without page markers still get the `pageBoundaries: none-in-source` honesty flag |
| D6 / row 16 — pairing "derived and verified, mismatch → review, never silent merge" | **Implemented for extraction-side pairing** — `--pair` derives QP/MS roles from filenames with fingerprint-based directory auto-pairing; ambiguous variant groups are skipped loudly, never guessed (real case: M1/M2 June 2014 variants) |

Honesty note: this addendum does **not** change any verdict above for the
audited `GLM-markdown-sample` corpus — its images were already lost and its
markdown remains as-is (the parser still reports `unavailable-signed-url`
for it). The tool prevents recurrence for future exports; it does not
retroactively fix the old ones.
