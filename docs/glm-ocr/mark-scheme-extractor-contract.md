# Mark-Scheme Extractor Contract (GlmOcrMarkSchemeExtractor)

Permanent invariant for the GLM-OCR mark-scheme **draft extraction layer**.
Established by the T-C04 continuation-row repair (commit `8949886`,
2026-09-13) and frozen by `GlmOcrMarkSchemeContinuationTest`.

Scope: the transformation *canonical MS document tables → ms-draft entries*.
It sits strictly below campaign ingestion and strictly above the committed
`MS.md` sources, both of which it never modifies. The committed sources and
the canonical document are authoritative; this layer's job is to lose
nothing they contain and to invent nothing they do not.

## 1. Supported row shapes (MUST)

| # | Row shape (cell 0 …) | Contract behavior |
|---|----------------------|-------------------|
| 1 | Label row `11`, `13(a)`, `*14` | Opens an entry (question-level or part-level). Resets the part-letter context — letters never cross questions. |
| 2 | Flat continuation row `(ii)`, `(iii)` | Opens a sub-part entry of the **current** part letter (`lastPartLetter`): `2(b)(i)` → `(ii)` becomes `2(b)(ii)`. Marks come from the row's own trailing integer. |
| 3 | Letter-only label `(c)`, `(d)` | Opens a sub-part entry directly (`16(c)`), sets the new part-letter context. |
| 4 | Nested label `(b)(i)`, `(d)(ii)` | Opens a sub-part entry directly (`3(d)(ii)`). |
| 5 | Two-level label row `7 \| (a)(i)` (question number in cell 0, sub-part in cell 1) | Opens a compound-label entry `7(a)(i)`; the **answer is cell 2**; marks from the row's trailing integer. Spaced form `a (i)` is canonicalized to `(a)(i)`. |
| 6 | Multi-roman sequence `(i)`, `(ii)`, `(iii)` under one letter | Each row opens its own roman-indexed entry continuing the current letter. |
| 7 | Rowspan continuation rows (label and/or marks deferred) | Legacy behavior: content appends to the current entry; a later bare-integer marks cell may attach with `marksCellSource = "rowspan continuation row"`. |
| 8 | Equations inside answer cells | Carried **verbatim** in `answerText` (e.g. `Pb(NO3)2(aq)+2KI(aq)→PbI2(s)+2KNO3(aq)`); no math re-interpretation, no re-hosting into guidance. |

Ordinary rows (headers, totals `Total for Question N`, embedded IC tables,
QWC rubric, MCQ option rows) keep their pre-repair semantics unchanged.

## 2. Invariants (MUST hold for every input)

1. **Never invent parent context.** A bare-roman label with no part-letter
   context is treated as a rowspan continuation (conservative fallback) —
   the association `? → (ii)` is never guessed.
2. **Marks travel with the row that prints them.** An entry's `marks` come
   only from its own row's trailing integer. An empty marks cell stays
   `null` — never inferred from sibling rows, alternative-method rows, or
   table totals.
3. **Letters never cross questions.** `lastPartLetter` resets at every
   question-level label row.
4. **No loss, no invention.** Every answer/guidance string in the draft
   must be present verbatim in a source table cell (containment check);
   nothing may be synthesized.
5. **Deterministic identity.** `entryId = ms-<docId-short>-q<number><part>`
   and label strings are pure functions of the source row; re-extraction
   is byte-identical (canonical `extractedAt` aside).
6. **Row order preserved.** Entries appear in source reading order within a
   question.

## 3. Deliberately conservative — unsupported by design

These ambiguous forms **intentionally remain on the continuation path**
(answers/guidance append to the current entry; marks cells may be skipped
with a loud warning). They are not defects; supporting them would require
guessing:

- **Two-level GROUP rows** — a sub-part label in cell 0 *and* cell 1
  (e.g. `(b)(i) | (ii)`): ambiguous which cell owns the answer.
- **Letter + multi-roman labels** — `(c)(i)(ii)`: a single row scoring two
  roman sub-parts; splitting it would fabricate two entries from one row.
- **Bare-roman rows with no letter context** — see invariant 1.
- **Single-cell `N marks` total-ish rows** — append to the current entry's
  answer text (legacy); too ambiguous to convert into entry marks.
- **Two-level 4-column rows** — never observed in the wild; the two-level
  rule requires ≥5 columns; untested shapes are not guessed.
- **Empty marks cells on equal-credit alternative rows** (e.g. a `METHOD 2`
  row whose marks cell the source leaves blank): stay `null`.

## 4. Regression protection

`src/test/java/com/syllabai/parser/structure/glmocr/GlmOcrMarkSchemeContinuationTest.java`
(9 tests) covers all of §1 classes plus the frozen real Specimen 2017 1C
baseline (63 entries / 0 warnings / 110 total marks). The IAL fixtures in
the same suite contain zero continuation rows, so all pre-existing frozen
assertions also hold. Any change to this extractor must keep that suite
green or consciously amend this contract in the same commit.
