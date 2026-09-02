# syllabai-parser

SyllabAI content pipeline — **offline, polyglot document processing** that turns official syllabi, past papers, and mark schemes into the canonical document format and knowledge-graph candidates.

> Part of the SyllabAI project · master pack: [`SyllabAI/syllabai`](https://github.com/SyllabAI/syllabai) · output lands in `syllabai-core`'s knowledge/content modules.

## Polyglot policy (ADR-011)

Java is preferred where the choice is a tie; other languages are welcome where they are clearly better. This repo is the sanctioned home for non-Java code:

| Stage | Engine | Language | License |
|---|---|---|---|
| Text PDF extraction | **opendataloader-pdf** (`org.opendataloader:opendataloader-pdf-core`) — runs in-process inside `syllabai-core`, not here | Java 11+ | Apache-2.0 |
| Scanned PDF OCR/layout | **MinerU**, **Surya** (weights: modified-OpenRAIL — no redistribution) | Python | Apache-2.0 (code) |
| Office docs → Markdown | **anydoc** | Rust CLI | MIT |
| PDF classification/routing | **pdf-inspector** (text vs scan vs mixed) | Rust CLI | MIT |
| KG candidate mining | **Hyper-Extract** / **Graphify** patterns; LLM-assisted structuring | Python | Apache-2.0 |
| Examiner-report misconception mining | NotebookLM/Gemini Notebook (internal, human-curated) | — | — |

## Contract

Input: source PDFs/office docs (from Cloudflare R2 or local). Output: **canonical document JSON** (Master Spec §8) — pages, text blocks with bounding boxes, tables, equations, reading order, confidence, parser+version provenance. No component of SyllabAI's deployed runtime depends on this repo; it is a content-operations workbench.

## License wall (ADR-013)

Only permissive-licensed output may be committed (MIT/Apache-2.0/ISC/ODbL-with-attribution). Pin exact engine versions in the worklog when a corpus is processed.

## Status

Not started. Bootstrap tasks: **T-008–T-011** in the main repo's `TODO.md` (Wave 1).
