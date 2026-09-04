# GLM-OCR Real-Corpus Syntax Report

**Date:** 2026-09-05 (Session 8)
**Source of truth:** direct inspection of all 6 files in
`Past-Papers/GLM-markdown-sample/` (3 QP/MS pairs, Pearson Edexcel IAL Physics
WPH11) plus a programmatic census (`scripts` workspace, rerunnable).
**Rule:** this report records the corpus *as it is*. OCR defects are documented,
never silently "fixed" downstream; the adapter must preserve or flag, not repair.

---

## 1. Corpus inventory

| File | Kind | Identity | Marks | Questions |
|---|---|---|---|---|
| June 2025 (IAL) QP | QP | WPH11/01, Summer 2025, P78753A | 80 | 20 (10 MCQ + 10 structured) |
| June 2025 (IAL) MS | MS | WPH11_01_2506_MS | 80 | answers for Q1–20 |
| October 2025 - Unit 1 QP | QP | WPH11/01, October 2025, P78831A | 80 | 19 detected by census |
| October 2025 - Unit 1 MS | MS | WPH11_01_2510_MS | 80 | answers for Q1–20 |
| October 2025 - Unit 1A QP | QP | WPH11/**01A** (answer-book variant), P87440A | **120** | 19 |
| October 2025 - Unit 1A MS | MS | WPH11_01A_2510_MS | 120 | answers for Q1–19 |

Census totals: 226 image references (74+74+77+1+0+0), 59 HTML tables
(2 QP tables, 57 MS tables), 240+ inline math spans, 24 display-math blocks
(all in the June QP formula appendix).

## 2. Image reference syntax (all six files)

*Every* image is emitted as raw HTML, never Markdown `![](...)`:

```html
<div style='text-align: center;'><img src='URL' alt='OCR图片'/></div>
```

URL anatomy (single-quoted attribute, URL-encoded path):

```
https://maas-watermark-prod-new.cn-wlcb.ufileos.com/ocr%2Fcrop%2F<32-hex-session>%2Fcrop_<n>_<epoch-millis>.png
    ?UCloudPublicKey=TOKEN_<uuid>&Signature=<urlenc-base64>&Expires=<epoch-seconds>
```

- `crop_<n>` restarts per page/region: `crop_1`, `crop_2`, `crop_3`, … appear
  repeatedly; the **globally unique** key is the full path
  (`session-id + crop_n + millis`), not the crop number alone.
- `alt` is the constant Chinese string `OCR图片` — no semantic alt text.
- All observed `Expires` values = 2026-04-07 (≈1 week after the 2026-03-31/04-01
  export). **Every URL is now dead (HTTP 401, verified 2026-09-05).**
- The QP cover page, MCQ answer boxes, "lined answer space" graphics and
  blank-page artefacts are referenced through the *same* syntax as semantic
  diagrams/graphs — the reference stream alone cannot classify them.
- No local files, no relative paths, no base64 data URIs occur anywhere.

Orphaned crops (different OCR session, no Markdown counterpart):
`IAL/Edexcel/Physics/Unit 4/ocr_crop_20260709013610e74b664078f24ba5_crop_<n>_<millis>.png`
× 10 — real PNG binaries, naming identical in shape to the URL path segments.

## 3. Question-paper Markdown syntax

### 3.1 Front matter (three different encodings across three QPs)

| QP | Encoding |
|---|---|
| June 2025 | **image only** — cover page is a crop image; instructions follow as headings |
| October Unit 1 | image cover + `## Instructions` / `## Information` / `## Advice` headings with `-` bullets |
| October Unit 1A | **HTML table** cover: `<table><tr><td colspan="2">…Paper reference WPH11/01A…` then `Turn over` |

QP identity therefore must be read from *content* (paper-reference lines,
"Mark Scheme (Results)", log numbers) — never from the front-matter shape.

### 3.2 Headings

`## Instructions:` / `## Instructions`, `## Information:`, `## Advice`,
`## SECTION A`, `## SECTION B`, `## Answer ALL questions.`,
`## Answer ALL questions in the spaces provided.`,
`## BLANK PAGE`, `## List of data, formulae and relationships`.

One OCR artefact: a `(Total for Question 8 = 1 mark)` line was promoted to a
`##` heading in the June QP (census heading list) — total lines can appear as
plain text, centered divs **or** headings.

### 3.3 Question numbering (TWO styles — both real)

- June 2025 QP: `1: A cube of volume V…` — **number + colon** (20 occurrences)
- October QPs: `1 Which of the following…` — **number + space** (19 occurrences)
- Asterisk QWC marker: `*(c) Diagram 1 shows…` (June Q18) and `*14` in the 1A MS.

A parser must accept `^(\*?)(\d{1,2})(:|\s)\s*…` and record which style matched.
The existing `PastPaperStructureExtractor.QUESTION_START` regex
(`[.\s]` after the number) **misses the colon style** — GLM-OCR needs its own
segmenter.

### 3.4 MCQ block syntax

- Option lines: `A …`, `B …`, `C …`, `D …` plain lines, sometimes carrying
  LaTeX (`A $ \frac{t}{2} $`), sometimes Unicode (`A V×W`, `A F=Wcosθ`).
- Defects observed:
  - option letters lost (October 1A Q2: options C/D became `$$ 2. 0 \mathrm {N m} ^ {- 1} $$` / `$$ 5 0 … $$` display-math blocks);
  - reading-order corruption (October Unit 1 QP Q3: option `B` printed before `A`);
  - option letters detached from figure rows (four graph images followed by
    bare `A`, `B`, `C`, `D` lines);
  - answer-box glyph as LaTeX (`$ \textcircled{x} $`).
- MCQ grid questions: options embedded in an HTML `<table border="1">` with
  row labels A–D (same table syntax as §3.6).

### 3.5 Parts, subparts, marks

- Letter parts: `(a) …`, `(b) …`; QWC-marked: `*(c) …`
- Roman subparts: `(b)(i) …`, `(b)(ii) …` (October 1A QP/MS go three levels:
  `17(a)(ii)`, `19(b)(iii)`).
- Per-part marks, June style — centered div block:
  `<div align="center">\n\n(6) \n\n</div>` after the part text.
- Per-question totals: `(Total for Question 1 = 1 mark)` / `(Total for
  Question 13 = 3 marks)` (with spaces), also `TOTAL FOR SECTION B=70 MARKS
  TOTAL FOR PAPER=80 MARKS` (glued, no spaces).
- Answer prompts: `Increase in elastic strain energy =`, `Mass of one sphere =`
  (trailing `=`, no value).
- Given data lines: `density of steel $ = 7.8\times10^{3}\mathrm{kg}\mathrm{m}^{-3} $`.

### 3.6 Tables

`<table border="1"><tr><td>…</td>…</tr></table>` — one line per table, no
header/row separation, no `th` in QPs. Cell text may contain LaTeX and newlines.
`colspan` used in the 1A cover table.

### 3.7 Formula appendix (June QP only)

`## List of data, formulae and relationships` followed by name/description
lines and `$$\n<formula>\n$$` display blocks, e.g.
`$$\ng = 9. 8 1 \mathrm {m s} ^ {- 2}\n$$`. Section labels can be glued
(`Unit1`, `Mechanics`) and formula labels detached (the word `Density` appears
*after* its formula block).

## 4. Mark-scheme Markdown syntax

### 4.1 Cover/boilerplate (three variants)

- June: plain-text lines (`Pearson Edexcel` / `Mark Scheme (Results)` /
  `Summer 2025` / identity line) + one cover image.
- October Unit 1: `<div align="center">\n\n# Mark Scheme (Results)\n\n</div>`
  (H1 inside a div).
- October Unit 1A: `Pearson` + `## Mark Scheme (Results)` (H2).

All three then repeat the same boilerplate: `## Edexcel and BTEC Qualifications`,
`## Pearson: helping people progress, everywhere`, `## General Marking Guidance`
(or unheaded bullet list), `Question Paper Log Number …`, `Publications(s) Code
…`, copyright `$ \textcircled{c} $ Pearson Education Ltd …`. June additionally
carries the numbered note sections `## 1. Mark scheme format` …
`## 5. Quality of Written Expression` with list items rendered `1. 1`, `1. 2`
(OCR splits "1.1" into "1. 1").

Metadata worth extracting: log number (`P78753A`), publication code
(`WPH11_01_2506_MS`), session, paper reference.

### 4.2 Answer tables (the core MS syntax)

- **MCQ tables** (Q1–10): 3 columns `Question Number | Answer | Mark`, one row
  per question. Cell content:
  `The only correct answer is D(W)` followed by per-distractor lines
  `A is not correct because …`, `B is not correct because …`.
- **Structured tables** (Q11+): 4 columns
  `Question Number | Acceptable Answer | Additional Guidance | Mark`.
- Row identity: `<td rowspan="N">14</td>` for multi-mark-point questions
  (rowspan up to 14 observed); part refs inside cells: `15(a)`, `19(b)(i)`,
  `17(b)(ii)`, QWC rows as `*14`.
- **In-table totals** (October MS): a final row `<td>Total for question 16</td>
  <td></td><td>8</td>` inside the answer table.
  **Standalone totals** (June/1A MS): `(Total for Question 14=6 marks)` lines
  between tables (note: no spaces around `=`, lowercase `question` in the
  October in-table variant).
- **IC (indicative-content) tables** for asterisk questions: separate
  `<table class="table table-bordered">` **with** `<thead>/<tbody>` and `<th>`
  cells — two shapes observed: `IC points | IC mark | Max linkage mark |
  Max final mark` (1A) and a 3/4-column variant (June). In the 1A MS the IC
  table is *nested inside* the Answer cell of the `*14` row, including the
  structure-levels table ("Answer shows a coherent and logical structure …").
- Multi-line cells: answers, guidance and example calculations are newline-
  separated inside one `<td>`; `MarkPoint` markers `(1)` occur **inline**
  (`Use of $v^{2}=u^{2}+2a\Delta s$ (1)`) or in a **separate narrow column**
  (1A `15(a)(i)` rows have `(1)` in their own `<td>`).

### 4.3 Marking semantics vocabulary (all real occurrences)

| Marker | Example | Meaning |
|---|---|---|
| `(N)` | `Efficiency=0.28 (1)` | one mark point worth N marks |
| `Or` / `OR` lines | `Or In a closed system (dependent on MP1)` | alternative acceptable answer |
| `Any two from` | `17(b)(ii) Any two from • …` (bullet `•` list) | selective credit: 2 marks from ≥3 candidates |
| `Allow …` | `Allow a tolerance of $ \pm \frac{1}{2} $ a small square` | accept-variant guidance |
| `Ignore …` | `Ignore references to heating` | do-not-penalize guidance |
| `(dependent on MP1)` / `MP3 dependent on MP1 or MP2` | | conditional mark points |
| `[ecf from(b)(i)]` / `ecf from12(a)` | | error-carried-forward credit |
| `(credit correct equivalent physics …)` | | equivalence credit note |
| `Example calculation` / `Example diagram` | in Guidance cells | exemplification, not mark points |
| `MP1/MP2/MP3` numbering | | mark-point identifiers used by dependency notes |

## 5. OCR defect catalogue (do NOT "fix" silently — preserve or flag)

1. **Spaced digits inside LaTeX**: `1 5 0 0 0^{2}`, `9. 8 1`, `0. 8 5`.
2. **Letter-spaced `\mathrm` words**: `\mathrm {e f f i c i e n c y}`,
   `\mathrm {u s e f u l e n e r g y o u t p u t}`.
3. **LaTeX without `$` delimiters glued into plain text** (MS cells):
   `Use ofs=ut+\frac{1}{2}at^{2}witha=0`, `New length=0.45m-3.55\times10^{-3}m`.
4. **Stray/unbalanced `$`**: `Terminal velocity=13.0m/s^{-1}$`.
5. **Unicode math without LaTeX**: `m=1.1×10-2kg`, `W=mg` (loses superscripts:
   `10-2` = 10⁻²).
6. **Mangled units**: `0.31mS-2`, `37.1(m/s-1)`, `2700(Nm$^{-1}$)`.
7. **HTML entities**: `&gt;`, `&lt;`, `&#x27;` (apostrophe), inside cells and
   even inside math (`$291m&lt;200m$`).
8. **Glued words in cells** (space loss): `allow1mark`, `0.30kgif correct
   reasoning shown`, `(allow370Nto390N)`, `gradient ofg/2`.
9. **Reading-order corruption**: option B printed before option A
   (October Unit 1 QP Q3).
10. **Missing option letters**: October 1A Q2 C/D rendered as `$$…$$` blocks.
11. **Inconsistent question-number style across files**: `1:` vs `1 `.
12. **Inconsistent totals placement**: standalone lines vs in-table rows;
    `=` spacing differs (`Question 11=3` vs `Question 1 = 1`).
13. **Total lines promoted to headings**: June QP has
    `## (Total for Question 8 = 1 mark)`.
14. **Lost superscripts**: `tan-1(0.765)`, `4/3π(7.0×10-3m)3`.
15. **Formula labels detached/reordered** in the appendix (`Density` after the
    formula; `E = σ/ε where` split across blocks).
16. **Cover/front-matter shape variance** (image vs HTML table vs text) across
    papers of the same board/subject.
17. **Page furniture mixed into the figure stream** (answer boxes, covers,
    blank-page crops indistinguishable from semantic figures).
18. **Chinese alt text** `OCR图片` on every image.
19. **QWC asterisk placement variance**: `*(c)` in QP part labels vs `*14`
    at question level in MS tables.
20. **`Turn over` / `## BLANK PAGE` page-break substitutes** — no reliable
    page-boundary markers exist (page associations are NOT recoverable from
    this representation).

## 6. Consequences for the GLM-OCR adapter

1. Parse line-oriented: plain Markdown lines, `##` headings, raw HTML islands
   (`<table>`, `<div align="center">`, the image `<div>`), `$$` blocks.
2. Emit figures with the **full URL path as the stable source name** (the only
   durable identity), mark all of them `unavailable` (dead signed URLs) until a
   re-export lands; classify none as semantic on the reference stream alone.
3. Page association: source has none — do not invent pages; record
   `pageCount=1` with an explicit provenance param
   (`pageBoundaries: none-in-source`).
4. Determinism: derive `documentId` from the SHA-256 of the source bytes
   (content-derived UUID), keep element ids positional (`e%06d`) like the
   OpenDataLoader adapter; `extractedAt` stays a provenance fact (the
   determinism test pins it via the fixed-identity entry point).
5. Question segmentation must accept both numbering styles and the
   heading-promoted total artefact; MCQ option/letter/figure association is
   best-effort and flagged `reviewRequired` (boilerplate spillover lesson
   from T-011 still applies).
6. MS extraction is table-first: 3/4-column answer tables, rowspan question
   identity, both total styles, IC tables, and the §4.3 semantics vocabulary
   mapped onto MarkPoint metadata (alternatives, conditions, allow/ignore,
   ecf, selective credit).
7. Every defect class in §5 that the adapter *normalizes* (e.g. entity
   decoding for `&gt;`) must be recorded in provenance params; anything
   ambiguous stays in raw text form.
