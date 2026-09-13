# syllabai-parser

SyllabAI content pipeline — **offline, polyglot document processing** that turns official syllabi, past papers, and mark schemes into the canonical document format and knowledge-graph/question-bank ingestion drafts.

> Part of the SyllabAI project · master pack: [`SyllabAI/syllabai`](https://github.com/SyllabAI/syllabai) · output lands in `syllabai-core`'s knowledge/content modules.

## Status: T-008 + T-009 + T-010/T-011 parser-side; GLM-OCR Markdown adapter + QP/MS extraction (Session 9)

| Piece | State |
|---|---|
| Canonical document format (Master Spec §8) | ✅ schema 1.0 — sealed element model, provenance, validator, deterministic JSON |
| `DocumentParser` contract (§27) | ✅ engine-agnostic port |
| `OpenDataLoaderParser` (T-009) | ✅ `org.opendataloader:opendataloader-pdf-core:2.5.7` in-process, fast mode, XY-Cut++ reading order, bounding boxes, classpath-resolved engine version |
| QP/MS structural extraction (T-011 parser side) | ✅ v0 regex heuristics — questions, letter/roman parts, marks, command words, mark points (IAL + IGCSE layouts); everything `reviewRequired=true`, confidence < 1.0 |
| Syllabus structuring (T-010) | ✅ `EdexcelSyllabusOutlineExtractor` — deterministic `Unit N:`/`Topic N:`/`NC:` pattern match with title cleanup, per-node provenance (section id, element ids, page, confidence), first-match dedup; draft schema 1.1, always `SUGGESTED`. Generic fallback: v0 heading-heuristic (low confidence 0.5) |
| Real-corpus verification | ✅ Edexcel IAL Chemistry 2018 spec (Pearson, 108 pp): 6 units / 20 topics / 15 subtopics extracted + pinned by tests |
| MinerU / Surya / anydoc / pdf-inspector adapters | ⏳ deferred — behind the same `DocumentParser` port when OCR/hybrid fidelity is needed |
| GLM-OCR Markdown adapter (Session 8/9) | ✅ real-corpus verified — headings, HTML islands (image divs w/ signed URLs, tables incl. rowspan), centered divs, `$$` math, entity decoding recorded in provenance, pageCount=1 honesty, deterministic identity |
| GLM-OCR QP + MS extraction | ✅ both numbering styles (`1:`/`1 `), `*N`/`*(a)` QWC, MCQ hindsight validation, mark points w/ dependent-on/ecf/Or/any-two-from vocabulary, IC tables (3 shapes), both total placements, QP/MS reconciliation (D6: mismatches → review, never silent merges) |
| GLM-OCR image reality | ✅ expired signed URLs preserved (full URL + decoded path + ownership + failure state); local-asset pipeline (`img:<sha256>`, MIME sniffing, dimensions) ready for re-exports |
| Python/Java conformance | ✅ `tools/glmocr/` reference implementation + harness — 16/16 fixture-mode combinations agree field-for-field (4 pairs incl. the pathological pair); enforced in CI |

## Build & test

```bash
mvn verify          # Java 25; 89 unit tests incl. full PDF→canonical→draft chain
                    # + real-spec outline extraction + GLM-OCR QP/MS extraction,
                    # determinism, reconciliation and image-reality tests pinned
                    # against the 6 real GLM-OCR fixtures

# cross-language conformance (after mvn compile)
python3 tools/glmocr/conformance.py   # 16/16 fixture-mode combinations, enforced in CI
```

## Workbench CLI

```bash
# past paper + mark scheme pair → canonical JSON + ingestion draft
java -cp ... com.syllabai.parser.ParserCli QP <qp.pdf> <out-dir> [ms.pdf] \
    --paperEdexcel|IGCSE|Chemistry|Paper 1C|January 2012|4CH0/1C

# syllabus / specification → canonical JSON + curriculum draft
# (--extractor outline is the default; heuristic keeps the generic v0 path)
java -cp ... com.syllabai.parser.ParserCli SYLLABUS <pdf> <out-dir> \
    --curriculumEdexcel|IAL|IAL-CHEM-2018|Edexcel International Advanced Level Chemistry|CHM|Chemistry
```

`corpus/` holds processed real fixtures:
- **igcse-chemistry-4ch0-1c-jan2012** — Edexcel IGCSE Chemistry 4CH0/1C January 2012 QP+MS
  (from [`SyllabAI/Past-Papers`](https://github.com/SyllabAI/Past-Papers)): canonical documents + drafts with full provenance.
- **ial-chemistry-2018-spec** — the published Edexcel IAL Chemistry 2018 specification
  (Pearson, 108 pages): canonical document + curriculum draft (6 units / 20 topics / 15
  subtopics, per-node §17 provenance).

## The contract (canonical document JSON, schema 1.0)

Field names follow Master Spec §8 exactly (`documentId`, `source.uri/checksum/mimeType`, `pages`,
`sections`, `textBlocks`, `tables`, `figures`, `equations`, `provenance`; every element carries
`element_id`, `page_number`, `bounding_box`, `text`, `element_type`, `reading_order`, `confidence`,
`source_engine`, `source_engine_version`). Additive v1.0 fields: `source.checksumAlgorithm`,
`source.fileName`, `role`/`heading_level` on text blocks, `rows` on tables, `latex` on equations.
The JSON is the language-neutral contract — `syllabai-core` maps it with its own DTOs and
validates the same invariants (see `CanonicalValidator`); both repos pin the shape with fixtures.

**Bounding boxes** are PDF points, origin bottom-left, `{x, y, width, height}` (converted from the
engine's corner format). **Confidence** is 1.0 for exact digital-text extraction and the engine's
`ai_score` when hybrid mode reports one.

## Honesty notes (v0 extraction quality)

Verified against the real 4CH0/1C January 2012 pair: 20-question paper → 27 draft questions
(boilerplate spillover), mark scheme → 33 mark points with correct `q-part` refs. Drafts are
**never** treated as validated: `reviewRequired=true`, confidence < 1.0, and downstream
ingestion persists SUGGESTED validation states awaiting human review (Master Spec §7).
Extraction quality improves iteratively in this workbench — it is content-operations, not runtime.

## GLM-OCR Markdown pipeline (Session 8/9)

Real corpus: `SyllabAI/Past-Papers` -> `GLM-markdown-sample/` (6 Markdown files,
3 WPH11 QP/MS pairs; grammar documented in
`docs/glm-ocr/real-corpus-syntax-report.md`, design reconciliation in
`docs/glm-ocr/adapter-design-reconciliation.md`, verification in
`docs/validation/session9-real-corpus-validation.md`).

- `GlmOcrMarkdownParser` — line-oriented Markdown + HTML-island adapter into
  the canonical document; images are **expired signed URLs** in this corpus,
  so figures carry the complete URL, the decoded crop path and
  `availability=unavailable-signed-url` — nothing fetched, nothing faked
- `GlmOcrQuestionExtractor` / `GlmOcrMarkSchemeExtractor` — draft extraction
  (`reviewRequired=true`, confidence < 1.0) with the full marking vocabulary
  preserved as structure; QP/MS mark reconciliation reports conflicts
  (e.g. the audited 1A 80-vs-120 paper-total conflict) instead of merging
- `tools/glmocr/` — Python reference implementation (behavioral twin) +
  `conformance.py`: Java production and Python reference must agree on every
  field of every fixture; CI enforces it
- Identity: `CanonicalIdentity` derives `documentId` from
  SHA-256(checksum + engine + engine version) — deterministic, timestamp-free
  (the `UUID.randomUUID()` bug was fixed at the canonical layer, not hidden
  in the adapter)

## Polyglot policy (ADR-011)

Java is preferred where the choice is a tie; other languages are welcome where they are clearly better. This repo is the sanctioned home for non-Java code:

| Stage | Engine | Language | License |
|---|---|---|---|
| Text PDF extraction | **opendataloader-pdf** (`org.opendataloader:opendataloader-pdf-core`) — runs in-process, fast mode | Java 11+ | Apache-2.0 (NOTICE: Hancom Inc.) |
| Scanned PDF OCR/layout | **MinerU**, **Surya** (weights: modified-OpenRAIL — no redistribution) | Python | Apache-2.0 (code) |
| Office docs → Markdown | **anydoc** | Rust CLI | MIT |
| PDF classification/routing | **pdf-inspector** | Rust CLI | MIT |
| KG candidate mining | **Hyper-Extract** / **Graphify** patterns; LLM-assisted structuring | Python | Apache-2.0 |
| Examiner-report misconception mining | NotebookLM/Gemini Notebook (internal, human-curated) | — | — |

## License wall (ADR-013)

Only permissive-licensed output may be committed (MIT/Apache-2.0/ISC/ODbL-with-attribution). Pin
exact engine versions in the worklog when a corpus is processed. Pinned: opendataloader-pdf-core
**2.5.7** (Apache-2.0, verified on Maven Central via repo1 metadata). No component of SyllabAI's
deployed runtime depends on this repo; it is a content-operations workbench.
