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

## 5. Session-66 amendment — batch-3 defect classes (2026-09-14)

Four row-shape extensions, each driven by a defect class measured by the
T-C04 Batch-3 review and pinned by
`GlmOcrBatch3DefectTest` (11 tests). All §2 invariants hold; the amendment
*strengthens* invariant 2 (totals can no longer leak into entry marks).

| # | Row shape | Contract behavior |
|---|-----------|-------------------|
| 9 | **Table-start continuation row** — a table whose first content row is a bare sub-part label (`(iii)`, `(b)(i)`, `(d)`) | Opens a sub-part entry of the **carried** question/letter context (`lastQuestionNumber`/`lastPartLetter` persist across `closeEntry` at table end). Provenance: `marksCellSource = "table-start continuation row"`. Still no invention: bare romans need an established letter; a new question always opens with its own full label row, so the carried context names the same printed question (2019-Jan 5(d)(iii)/(iv) table split). Corpus impact: 177 entries. |
| 10 | **Stacked marks cell** `1\n1` / `1\n1\n1` (multi-line, every line a bare integer, last non-empty cell of the row) | The printed per-line marks of a rowspan'd answer, stacked by the OCR into one cell → the entry's marks are the **sum**. Guards: 2–3 lines, sum ≤ 12; anything else (graph-axis data, reading values) stays `null` (2011-Jun 1(c)(ii) `"1\n1"` → 2, reconciling the printed "Total 8 marks"). Corpus impact: 63 cells. |
| 11 | **Single-cell bare-integer row** `1` | A rowspan continuation's marks column rendered alone → delivered to the open entry per shape 7 semantics (marks-null entries receive it; already-marked entries keep the legacy ambiguity warning). **Never** a question-level label row — the 2011-Jun q11-tail stray entry `q1`/"1"/1-mark shape is a defect, not a label. Corpus impact: 5 rows. |
| 12 | **Bare in-table total row** `… \| Total \| 9` (a non-last cell exactly `Total`, last cell a bare integer) | Recorded as the **current question's total** (`recordTotal`, placement `"in-table bare-total row"`), never as the open entry's marks. Closes the mis-attribution window where a question total was delivered to the last sub-part as rowspan marks (2013-Jun-2C 3(d)/7(c)(ii) "9-mark" defect; both are 2-mark sub-parts under 9-mark questions). Corpus impact: 132 rows recorded as totals. |

QP-side companion (this commit, `GlmOcrQuestionExtractor`): an OCR-damaged
part label with closing paren only (`b)` — 2022-Jan-R 1(b), 2024-Jun-R 11(d))
is recovered **only when the letter continues the established part sequence**
(never a first part, never a sequence mismatch), with a loud warning. The
double-damaged `b)i)` form (2020-Jun-R) stays conservative by design.

Measured corpus impact vs `408b8fb`: 312 entries recovered, 586 marks moved
into entries, 2 QP parts recovered, 63→60 ms-drafts changed (18+3 unchanged
incl. both frozen Specimen papers), canonical layer 0-diff, deterministic
byte-identity on re-extraction.
