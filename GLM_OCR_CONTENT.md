# GLM-OCR Question-Paper Content Pipeline

**Date:** 2026-09-04

SyllabAI has a prepared corpus in which question papers and mark schemes were converted to Markdown using Z.ai GLM OCR, with the extracted images retained alongside each Markdown file.

This corpus is a valuable content-processing input and should not be discarded or unnecessarily re-OCRed.

## Role in the parser

The GLM-OCR representation should be normalized into the existing canonical document contract while retaining the original presentation information needed for faithful question rendering.

```text
GLM-OCR Markdown + extracted assets
                 ↓
        normalization/validation
                 ↓
        Canonical Document Format
                 ↓
       question/mark-scheme drafts
                 ↓
   syllabai-core content + assessment
```

Preserve, where available:

- Markdown/source provenance;
- image references and stable asset identities;
- page associations;
- question and question-part boundaries;
- equations;
- tables;
- reading order;
- source document/version identifiers.

Automated question boundaries remain drafts until validated. The existing T-011 real-corpus verification demonstrated that OCR/parser extraction can produce boilerplate spillover, so source Markdown is not itself semantic validation.

## Visual assets

Extracted images are first-class content. They may contain diagrams, graphs, chemical structures, apparatus, maps, or other information that cannot safely be represented as text alone.

A normalized question part should therefore be capable of referencing visual assets as well as text, equations and tables.

## Downstream consumers

The normalized representation is intended to support:

- Exam Questions;
- Target Test;
- Test Builder;
- Mock Exams;
- notes containing embedded past-paper questions;
- Smart Mark context;
- KA-RAG/tutor evidence;
- future similar-question and adaptive-practice features.

The parser remains a content-operations workbench. It should emit stable, provenance-rich representations rather than owning learner-facing feature behavior.

## Storage rule

Do not make the Next.js frontend depend on parser filesystem paths. The application should receive stable content/asset references through `syllabai-core`; large binaries should ultimately be stored in object storage such as the project's Cloudflare R2 layer.
