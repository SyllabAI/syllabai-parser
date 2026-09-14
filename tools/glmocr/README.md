# GLM-OCR Python reference implementation

Executable behavioral reference for the Java production parser in this
repository (`com.syllabai.parser.engine.glmocr` / `structure.glmocr`).

**Origin note (Session 9, 2026-09-05):** an earlier session report described
a `tools/glmocr/` reference implementation, but workspace forensics (reflog,
`git fsck --unreachable`, untracked-file census) showed it never existed —
only the Java files were present uncommitted. This package was written now,
as a faithful port of the verified Java implementation, so cross-language
conformance (§12 of the Session 9 plan) could be established.

## Layout

| File | Java twin |
|------|-----------|
| `canonical.py` | `CanonicalIdentity` + `GlmOcrMarkdownParser` |
| `question_extractor.py` | `GlmOcrQuestionExtractor` |
| `markscheme_extractor.py` | `GlmOcrMarkSchemeExtractor` |
| `__main__.py` | `GlmOcrConformanceDump` CLI (same modes, epoch-pinned identity) |
| `conformance.py` | the harness below |

## CLI

```
python -m glmocr <markdown-file> <doc|qp|ms>
```

Prints the canonical document (`doc`), question-paper draft (`qp`) or
mark-scheme draft (`ms`) as JSON. `extractedAt` is pinned to the epoch for
byte-stable comparison, mirroring the Java dump CLI.

## Cross-language conformance

```
# after mvn -o test (compiles target/classes)
python3 tools/glmocr/conformance.py
```

Runs all six real-corpus fixtures (3 QP/MS pairs) through **both**
implementations in all modes and compares every field: document structure,
ids, question numbers, parts, marks, QWC markers, MarkScheme entries,
MarkPoints, image references, warnings (validation findings) and provenance.

Status: **FULL CONFORMANCE** — Java production and Python reference agree on
every field of every fixture in every mode (16/16 file-mode combinations).
The `conformance` job in `.github/workflows/ci.yml` keeps it enforced.

## Change protocol

This reference and the Java implementation must move **together**: any
behavioral change on one side must be ported to the other and re-verified
with `conformance.py`. The Java side remains the production implementation;
this package is the reference, never the runtime.

## Additive tooling (OCR-Q4, read-only consumers of the extractors)

Two standalone tools build **on top of** the reference without touching it
(no conformance impact, no canonical-contract change, no Java twin):

| File | Purpose |
|------|---------|
| `health.py` | Zero-network **corpus health gate**: per-question part-mark sums vs printed totals, QP↔MS total agreement, question↔entry mapping, paper-total consistency, offline asset integrity (manifest/assets-dir aware; signed URLs with no local copy are `knownUnavailable`, never fetched). Deterministic JSON report + human summary; exit 1 on FAIL-class findings. |
| `atomize.py` | **Per-sitting atomizer**: QP.md + MS.md → one self-contained `paper.json`. Every part carries its inherited stem context (question stem + parent-part lead-in, verbatim slices only) and its matched mark-scheme entry. Everything stays `reviewRequired` drafts; unmatched parts/entries are reported, never guessed. Byte-identical output for identical inputs. |

```bash
# health gate: one pair, or a whole directory tree (auto-pairs by filename)
python3 tools/glmocr/health.py <QP.md> <MS.md>
python3 tools/glmocr/health.py --dir "IAL/Edexcel/Physics/Unit 4"

# atomize: one sitting -> paper.json
python3 tools/glmocr/atomize.py <QP.md> <MS.md> -o paper.json

# tests (40 total, no network, no key)
python3 tools/glmocr/test_health.py -v
python3 tools/glmocr/test_atomize.py -v
```

Both tools run in CI as part of the `ocr-batch` workflow's `tool-tests` job.
The Java mirror of the atomizer's export shape is future work — until then
the export schema lives in the `glmocr-atomize` tool namespace, deliberately
outside the canonical contract.
