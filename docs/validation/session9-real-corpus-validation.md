# Session 9 Real-Corpus Validation Report — GLM-OCR Java Implementation

**Date:** 2026-09-05 (Session 9, recovery + implementation session)
**Scope:** recovery of uncommitted Session 8/9 work, deterministic canonical
identity, GLM-OCR QP + MS extraction, image-reality handling,
cross-language conformance, CI.
**Toolchain:** Temurin OpenJDK 25.0.4.1, Apache Maven 3.9.16 (offline —
all dependencies resolved from the local repository).
**Corpus:** `Past-Papers/GLM-markdown-sample/` — 6 Markdown files, 3 QP/MS
pairs (WPH11 June 2025, WPH11/01 October 2025, WPH11/01A October 2025),
all image references expired signed URLs (HTTP 401 since 2026-04-07).

---

## 1. Recovery (what existed only in the local workspace)

Forensics on `syllabai-parser`: reflog showed exactly two entries (clone,
one doc commit); `git fsck --no-reflogs --unreachable` — empty; no stashes;
no unpushed commits. The ONLY uncommitted work was three untracked Java
files (1,130 lines): `GlmOcrMarkdownParser`,
`GlmOcrPaperDraft` (DTO), `GlmOcrQuestionExtractor`, plus three empty test
directories. The `tools/glmocr/` Python reference reported by the prior
session **never existed** in any workspace — it was created this session
(origin documented in `tools/glmocr/README.md`).

| Commit | Content |
|--------|---------|
| `8baacbf` | recovered adapter files, compiled as-is before any modification |
| `2f833d1` | canonical identity determinism fix |
| `45f8ea2` | QP/MS extraction + reconciliation + fixtures |
| `7c37993` | image asset handling |
| `9a5da41` | Python reference + conformance harness + CI |

## 2. Deterministic canonical identity (the `UUID.randomUUID()` bug)

`CanonicalDocument.of()` minted random UUIDs, so parsing the same source
twice produced unrelated documents. Fixed at the canonical layer:

- new `CanonicalIdentity.contentDocumentId(checksum, engine, engineVersion)`:
  UUID (version-5 layout) from SHA-256 of
  `sha256:<checksum>|engine:<engine>|version:<engineVersion>` (lowercased,
  stripped) — no random component, no timestamp ever;
  `extractedAt` stays a provenance fact outside identity
- `CanonicalDocument.of()` now derives ids via `CanonicalIdentity` — the
  OpenDataLoader path keeps the same call and becomes deterministic as a
  side effect (its `parseWithFixedIdentity` override still honored);
  regression test pins parse-twice identity for both engines
- the GLM-OCR adapter dropped its private derivation and routes through
  the canonical layer (design rule: never hide identity in an adapter)
- element ids remain positional `e%06d` in reading order

Proof: `CanonicalIdentityTest` (8 tests), ODL determinism regression,
GLM parser parse-twice identity, and the conformance harness (identical
`documentId` across languages on every fixture).

## 3. Question extraction (real corpus)

All assertions below were hand-verified against the source Markdown.

| Paper | Questions | Numbering | paperTotal | Defects surfaced |
|-------|-----------|-----------|------------|------------------|
| June 2025 WPH11/01 | 20 | colon | 80 | Q6 detached MCQ letters → stays non-MCQ with warning; totals for 6/12/15 genuinely absent in source |
| October 2025 WPH11/01 | 20 | space | 80 | `## 15 A student…` heading-promoted number reopened (forward-jump gate + warning); Q18 part-marks sum 2 vs printed total 8 → marksKnown=false + warning |
| October 2025 WPH11/01A | 19 | space | 80 | `*14` question-level QWC asterisk now opens (regex previously lacked it); paper genuinely ends at Q19 |

MCQ validation is in hindsight (complete A–D set, no parts); incomplete
sets fold back into the stem with a warning. Roman subparts parent to the
last letter part (`b-ii`, never `b-i-ii`). Option matching requires
whitespace after the letter, so prose like `Acceleration =` is an answer
prompt, never option "A". Every draft carries `reviewRequired=true` and
confidence < 1.0.

## 4. Mark-scheme extraction (real corpus)

| Paper | Entries | MarkPoints | IC table | Totals placement |
|-------|---------|------------|----------|------------------|
| June 2025 | 31 | 32 | standalone (long-header shape, en-dash ranges) | standalone lines incl. glued `…=15 marks) TOTAL FOR PAPER=80 MARKS` |
| October 2025 | 33 | 31 | standalone (`<th>` header) | in-table rows incl. glued `Total for question12` |
| October 2025 1A | 33 | 53 | embedded inside `*14` | standalone + in-table |

Marking vocabulary survives as structure, never flattened: MP ordinals,
`(N)` marks, `dependent on MPn` refs, `ecf`, `Or` alternatives,
`Any two from` groups, `Do not accept`/`insufficient` notes, guidance
classified allow / ignore / example-calculation / example-diagram / ecf /
dependent / note. Marks cells that are `rowspan`-deferred stay null until
the value arrives on a continuation row (October Q11, source recorded);
marks are never summed or guessed.

**Genuine corpus conflict found and preserved:** the 1A MS prints
`TOTAL FOR PAPER=120 MARKS` while its own question totals (and the QP,
three times) say 80. `GlmOcrMarkReconciliation` reports this as a
paper-total conflict with `reviewRequired=true` — never a silent merge.

## 5. QP/MS mark reconciliation (rule D6)

- June pair: 7+ shared totals, all match; honest gaps (QP-only/MS-only)
  for totals genuinely absent on either side
- October pair: 8 shared totals, all match
- 1A pair: 6+ shared totals match; paper-total conflict 80 vs 120 → review
- synthetic mismatch produces an explicit mismatch finding (unit test)

## 6. Images (reality, not aspiration)

- **Expired signed URLs (the entire current corpus):** figure elements
  carry the COMPLETE original URL (including `Expires=` evidence) in
  `text`, the decoded URL path as `source_name`, the upstream alt
  (`OCR图片`), and `availability=unavailable-signed-url` in drafts. No
  fetch is attempted at parse time; 74/74/77 figure references per QP
  respectively, all expired, all preserved.
  - Session 9 fix: the adapter previously used the FigureElement
    convenience constructor, which silently copied `alt` into `text` and
    dropped the URL — now the full record constructor is used and a
    regression test pins the complete-URL preservation.
- **Valid local assets (future re-exports):** `GlmOcrImageAssets` —
  SHA-256 byte hashing, magic-byte MIME sniffing (PNG/JPEG/GIF/BMP/WEBP),
  container-header dimensions (PNG IHDR, JPEG SOF scan, GIF LE, BMP),
  deterministic `img:<sha256>` identity, source-name matching back to
  figure references, caller-supplied question/part ownership.
  - The JPEG-content-with-`.png`-name regression test is enforced:
    content wins (`image/jpeg`), the mismatch stays visible
    (`formatMismatch=true`), never "fixed".

## 7. Cross-language conformance (§12)

`tools/glmocr/` — Python reference implementation (canonical identity,
Markdown adapter, QP extractor, MS extractor) + `conformance.py` harness
+ Java `GlmOcrConformanceDump` CLI (epoch-pinned identity on both sides).

**Result: FULL CONFORMANCE — 12/12 file-mode combinations** (6 files ×
doc, 3 QPs × qp, 3 MSs × ms): every field compared — document structure,
ids, question numbers, parts, marks, QWC markers, MarkScheme entries,
MarkPoints, image references, warnings, provenance params. Enforced in CI
by the new `conformance` job (Java 25 + Python 3.12).

## 8. Tests and build

- `mvn -o test` (offline, real toolchain): **68 tests, 0 failures, 0
  errors** — baseline before this session was 27
  - CanonicalIdentityTest 8, CanonicalJsonTest 8,
    OpenDataLoaderParserTest 8 (incl. determinism regression),
    GlmOcrMarkdownParserTest 8, GlmOcrQuestionExtractorTest 8,
    GlmOcrMarkSchemeExtractorTest 5, GlmOcrMarkReconciliationTest 4,
    GlmOcrImageAssetsTest 7, structure tests 12
- Conformance: `python3 tools/glmocr/conformance.py` → 12/12 PASS
- Note for local verification: a stale incremental compile produced a
  misleading intermediate result during development; clean builds
  (`rm -rf target`) are used for all recorded results above

## 9. Status

- 🟢 **Verified (CI + local + conformance):** canonical identity
  determinism; GLM-OCR Markdown adapter; QP extraction; MS extraction;
  mark reconciliation; image reference preservation; expired-URL honesty;
  Python/Java conformance; fixtures; CI workflow incl. conformance job
- 🟡 **Implemented, not production-verified:** local-asset image
  pipeline (`GlmOcrImageAssets.fromLocalFile`) — no real local assets
  exist yet (all corpus URLs expired); exercised only with synthetic
  bytes; MS entry marks for `rowspan` continuations rely on documented
  heuristics with warnings
- ⚪ **Deferred (Session 10+):** syllabai-core ingestion bridge
  (T-011-style canonical → persistence → T-013 chunk pipeline), full
  40-batch corpus processing (halted per plan after 3 pairs),
  re-export of images at OCR time, vision-LLM routing for image
  understanding
