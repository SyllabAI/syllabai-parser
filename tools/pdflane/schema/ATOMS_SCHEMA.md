# SyllabAI Past-Paper Atom Schema — `syllabai.pastpaper.atoms/1.0`

**Status:** definitive for pdflane output (supersedes the Phase-1/2 atom JSON shape).
**Owner:** pdflane (syllabai-parser). Consumed by: syllabai-web (Exam Questions, Test
Builder, Target Test), syllabai-core read-model (atom-level chunking + chatbot
retrieval), Smart Mark.

## 1. Design rules (non-negotiable)

1. **Only questions and mark schemes.** No engine dumps, no routing, no census, no
   review queues, no harness evidence in the product files. Lane evidence lives in the
   pdflane staging `_meta/` tree, never here.
2. **Identity comes from the folder, not the JSON.** The output is written INSIDE the
   paper directory that holds `qp.pdf`/`ms.pdf`/`manifest.yaml`. The repo path
   `past-papers/<board>/<qualification>/<subject>/<spec>/past-papers/<series>/<VARIANT>/`
   is the identity carrier, so the JSON carries **no** board/qualification/subject/
   series/paper-code fields. Moving or copying a paper directory keeps every file valid.
3. **JSON canonical, markdown derived.** `questions.json` is the single source of truth;
   `qp.md` and `ms.md` are renderings of it (plus, for `qp.md`, the page-aligned
   deterministic base layer). Web and chatbot read the JSON; humans and page-aligned
   chunking read the markdown.
4. **Atom = top-level question.** Parts are embedded. Each atom carries its connected
   mark scheme — QP and MS can never drift apart.
5. **No silent loss.** Every printed content line resolves into a block; any row the
   structurer could not classify surfaces as a `flags` entry or stays in the staging
   review queue. Unclassifiable text degrades to `para` blocks — it is never dropped.
6. **Marks closure is asserted, not assumed.** Point sums, part marks, question totals
   and the paper total are cross-checked at emit time; failures gate the output.
7. **Provenance is recorded at artifact level.** `provenance` ∈
   `pdf-parsed | llm-structured | llm-vision` on atoms and mark schemes. These are the
   lane's classes and are distinct from `ocr.z.ai`.
8. **Determinism.** Identical PDF bytes + code version ⇒ byte-identical output files.

## 2. File layout (inside each paper directory)

```text
<...>/<VARIANT>/            e.g. .../4ch0/past-papers/2012-01/4CH0-1C/
├── qp.pdf                  (existing source)
├── ms.pdf                  (existing source)
├── manifest.yaml           (existing source; SHA-256 identities)
└── parsed/
    ├── questions.json      canonical atoms (this schema)
    ├── qp.md               question paper sidecar (page-marked)
    ├── ms.md               mark scheme sidecar (atom-derived)
    └── assets/             figure crops, referenced relatively
        ├── QP_p04_01.png
        └── MS_p03_01.png
```

`questions.json` reference of any image is a **relative** path (`assets/…`), so the
`parsed/` directory is self-contained and relocatable.

## 3. `questions.json` envelope

```json
{
  "schema": "syllabai.pastpaper.atoms/1.0",
  "source": { "qp": "qp.pdf", "ms": "ms.pdf" },
  "questionCount": 11,
  "totalMarks": 120,
  "marksVerified": true,
  "questions": [ /* atoms, in printed order */ ]
}
```

| field | meaning |
|---|---|
| `schema` | format version; bump on any breaking change |
| `source` | file names only (never identities, never absolute paths) |
| `questionCount` | number of atoms |
| `totalMarks` | sum of atom `marks` |
| `marksVerified` | true iff every atom's mark scheme closes arithmetically and matches the QP total |
| `questions` | atom list |

## 4. Atom (top-level question)

```json
{
  "number": 1,
  "type": "structured",
  "marks": 10,
  "commandWord": null,
  "stem": [ /* blocks */ ],
  "parts": [ /* parts */ ],
  "markScheme": { /* §6 */ },
  "provenance": "pdf-parsed",
  "flags": []
}
```

| field | type | meaning |
|---|---|---|
| `number` | int | printed question number (1-based, unique in paper) |
| `type` | enum | `structured` (has parts) · `mcq` (choices, no parts) · `open` (plain response) |
| `marks` | int | printed total for the question (QP) |
| `commandWord` | string\|null | leading command word when confidently detected; `null` otherwise (forward-compatible, renderer may ignore) |
| `stem` | blocks[] | shared intro before the first part (figures, stimulus text); `[]` allowed |
| `parts` | part[] | `[]` for `open`/`mcq` atoms |
| `markScheme` | object | connected mark scheme (§6); MUST be present |
| `provenance` | class | `pdf-parsed` (born-digital deterministic) · `llm-vision` (scanned/vision lane) |
| `flags` | string[] | only when non-empty; see §10 |

## 5. Blocks (render-ready content vocabulary)

Content is **never** a raw layout dump. Each block is directly renderable.

```json
{ "type": "para", "md": "Use words from the box to complete the sentences." }
```
```json
{ "type": "table", "md": "| Measurement | Mass / g |\n|---|---|\n| Mass of empty crucible | 21.21 |" }
```
```json
{ "type": "image", "src": "assets/QP_p04_01.png", "alt": "separation apparatus", "pages": [4] }
```
```json
{ "type": "choices", "items": [ { "label": "A", "md": "chromatography" },
                                 { "label": "B", "md": "condensation" } ] }
```
```json
{ "type": "answer_lines", "count": 2 }
```

| block | rendering contract |
|---|---|
| `para` | inline markdown: `**bold**`, `*italic*`, `<sub></sub>`, `<sup></sup>`, `→`, `⇌`, unicode chemistry as printed |
| `table` | GitHub-flavoured markdown table string; renderer renders as table |
| `image` | `src` relative to `parsed/`; `alt` from nearby caption text when available; `pages` = source pages in the QP/MS pdf |
| `choices` | option list for MCQ / tick-box ("put a cross in the box") questions; **correct-ness never appears in the QP** — it lives in the mark scheme point |
| `answer_lines` | number of ruled/dotted response lines printed in the QP |

Rules:
- A dotted answer-line row is an `answer_lines` block, not `para` noise.
- Consecutive option rows after a select/MCQ stem become one `choices` block.
- Every other printed line becomes `para` with its text as printed (minus pure
  furniture). Nothing else is invented; the parser never rewrites question text.

## 6. Mark scheme (connected to its atom)

```json
{
  "totals": { "printed": 10, "sum": 10, "verified": true },
  "guidance": [],
  "points": [
    {
      "id": "M1",
      "part": "a",
      "sub": null,
      "marks": 1,
      "md": "beaker",
      "allow": ["phonetic spellings"],
      "reject": [],
      "ignore": [],
      "notes": [],
      "pages": [3]
    }
  ],
  "provenance": "llm-structured"
}
```

| field | meaning |
|---|---|
| `totals.printed` | the "Total N marks" row as printed in the MS (null if absent) |
| `totals.sum` | max awardable marks: Σ point marks with **pool members collapsed to their pool cap** |
| `totals.verified` | `printed == sum` (and matches QP total unless a `flags` entry says otherwise) |
| `guidance` | general MS guidance rows not attached to a specific point |
| `points[].id` | printed label (`M1`, `B1`, `C1`…) when the MS prints one; otherwise the row identity from structuring (`a`, `a-ii`, `a-key`, `c-b1`, `b-alt-m1`…) — repeats across parts by design, scoped by `part`/`sub` |
| `points[].part` / `sub` | which part this point rewards (`sub` null when the part has no sub-numbering) |
| `points[].marks` | marks this point awards; `0` marks an **alternative answer** recorded for completeness, never scored twice |
| `points[].md` | the answer cell as markdown; may be empty for pool points whose answers live in `notes` |
| `points[].pool` | optional `{ "rule": "any-N-for-1-each" }` on pool points (N = `marks`) |
| `points[].allow` | Accept/Allow variants — full credit |
| `points[].reject` | Reject / Do not accept — zero credit |
| `points[].ignore` | Ignore — neither rewarded nor penalised |
| `points[].notes` | any other guidance, and for pool points the candidate answers (1 mark each) |
| `points[].pages` | source pages in `ms.pdf` |
| `provenance` | `llm-structured` (agent structuring over deterministic text) · `pdf-parsed` (deterministic grid parse fallback) · `llm-vision` |

Classification is prefix-based and lossless: the original note text is preserved verbatim
inside the resulting category. Prefixes not in the table stay in `notes`.

**Pools** ("any N for 1 mark each" grids) appear as an optional `pools` array on the mark
scheme, one entry per printed pool:

```json
{ "part": "b-i", "labels": ["M1", "M2", "M3", "M4", "M5", "M6"],
  "cap": 2, "reason": "line 278 'Any two for 1 each'" }
```

`labels` reference `points[].id` within the pool's part (letter scope; `b-i` scopes to
letter `b`, sub `i`); `cap` is the maximum awardable. Pool-aware sums are what
`totals.sum` and the validation gates use — a naive sum over all points overcounts.

## 7. Part

```json
{
  "id": "1a-i",
  "label": "a",
  "sub": "i",
  "type": "open",
  "marks": 1,
  "commandWord": null,
  "prompt": [ /* blocks */ ],
  "choices": [ /* only for type mcq */ ],
  "answerLines": 1,
  "pages": [4]
}
```

| field | meaning |
|---|---|
| `id` | `<number><label>` (+ `-<sub>` when sub-numbered); unique within the paper |
| `label` | printed part letter (`a`, `b`, …) |
| `sub` | roman sub-number (`i`, `ii`, …) or null |
| `type` | `open` · `mcq` (part carries `choices`) |
| `marks` | printed marks for the part when the QP prints them, else the MS point sum for the part; mismatch ⇒ atom flag `PART-MARKS-MISMATCH` |
| `prompt` | blocks for this part |
| `answerLines` | convenience duplicate of trailing `answer_lines` block count (renderer shortcut) |
| `pages` | source pages in `qp.pdf` |

**Parent parts.** When a printed part letter owns sub-parts — `(a) …` with `(i)`, `(ii)` —
the flat `parts` array holds the parent (`sub: null`) followed by its leaves. The parent
is a container: its `marks` equal the sum of its leaf marks, and marks-closure arithmetic
(Q-total checks, letter-level compares) counts **leaves only** so nothing double-counts.

## 8. Retrieval contract (chatbot)

- Chatbots are subject-scoped; the subject, series and paper come from the **folder
  path** at index time. "give me question no.3 from jan 2019" resolves as:
  folder filter (subject + series) → atom `number == 3`.
- Atom-level chunking (primary): one chunk per atom, rendered from stem + parts + MS
  points; chunk identity = `<repo-relative paper dir>#q<number>`.
- Page-aligned chunking (secondary): `qp.md` keeps `<!-- PAGE n -->` markers; MS
  retrieval is atom-level (the atom is the natural MS unit).
- The renderer consumes `questions.json` directly; feature records (tests, embeddings,
  attempts) reference atoms by `paperDir + question number` / part `id` — never by
  copying content (QUESTION_CONTENT_RENDERING.md canonical-reference rule).

## 9. Validation gates (emit-time, enforced by `validate_atoms.py`)

- **V1 schema** — every file validates against `schema/atoms.schema.json`.
- **V2 marks closure** — per atom: pool-collapsed point sum vs `totals.printed` (when
  printed; a carried `PRINTED-TOTAL-DISCREPANCY-QP-VS-MS` or `MS-POINTS-DONT-CLOSE`
  flag marks the deficit instead of failing); leaf part sums vs atom `marks` (flag-
  tolerated); Σ atom `marks` == envelope `totalMarks`.
- **V3 label census** — every MS point maps to a printed QP part letter; every QP part
  letter has ≥ 1 MS point (flag-tolerant); question numbers unique and ordered.
- **V4 assets** — every `image.src` exists under `parsed/assets/`; every asset file is
  referenced from ≥ 1 block (front-matter crops are pruned back to staging).
- **V5 round-trip** — `ms.md` regenerates byte-identically from `questions.json`;
  `qp.md` is the deterministic base layer (page-marked).

Failures block the emit (exit non-zero) and write the deficit into the staging review
queue — never a silent pass.

## 10. Flags (source & structuring deficits, carried honestly)

An atom carries `flags` only when something in the printed source or the structuring
does not fully close. Flags are the lane's no-silent-loss contract at product level:

| flag | meaning |
|---|---|
| `QP-TOTAL-MISSING` | no printed total row for the question in the QP |
| `MS-QUESTION-MISSING` | no mark scheme content found for this question number |
| `PRINTED-TOTAL-DISCREPANCY-QP-VS-MS` | QP printed total ≠ MS printed total row (e.g. MS misprint) |
| `MS-POINTS-DONT-CLOSE` | MS point sum (pool-collapsed) ≠ MS printed total row |
| `PART-MARKS-MISMATCH` | a part's marks disagree with its MS point sum at letter level |
| `QP-STEM-MARKS-MARKER` | marks marker printed before any part could absorb it |
| `MS-PART-NO-POINTS` | a QP part letter has no MS points under it |
| `MS-POINT-UNKNOWN-PART` | an MS point targets a part letter the QP does not print |

`marksVerified: false` at the envelope means at least one atom carries a closure-affecting
flag — the corpus defect is visible to every consumer without opening staging logs.
