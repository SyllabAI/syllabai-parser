# Exam-calendar dataset (T-C79, ADR-035)

The **imported reference calendar** for Pearson Edexcel international
qualifications — the curriculum-import lane the operator's D1 ruling named
("curriculum import i guess…", trace 1a10493e233cb521). This directory
holds the dataset artifact; the fail-closed importer that consumes it lives
in `syllabai-core` (`ExamSeriesImportService`, the curriculum-ingestion
package), and the schema lands there as Flyway V62.

## Files

- `exam-series-2026-2027.dataset.json` — the dataset in the import-DTO
  shape: one board, one retrieval stamp, five published sittings, every row
  carrying its `sourceUrl` citation. `subjectsAvailable` is carried on the
  October 2026 IAL row as the measured demonstration of the
  per-sitting-coverage fact (7 subjects vs 49 on the summer IGCSE).

## Provenance (all rows CORE_MEASURED)

Every date below was measured from **official Pearson documents** fetched
live on **2026-10-04** under the operator's own directive ("Search the web
yourself and find the dates", trace 1a10626076367841):

| Fact | Source document |
|---|---|
| Exam windows (first/last paper) | Per-series **final timetables** (PDF/XLSX) — `qualifications.pearson.com/en/support/support-topics/exams/exam-timetables.html` |
| Entry deadlines + results dates | **Key Dates Table International 2026-2027** (XLSX, Entries & information manual) — row receipts recorded per series in the dataset (`keyDateReceipts`) |

The retrieval receipts: the timetables' "All papers" sheets carry the real
exam date in column A (column B is a constant series-start artifact — the
parser that produced these rows keyed on column A and the extremes were
row-verified against real paper codes); the key-dates table rows were read
directly.

## Validation contract (fail-closed, enforced by the core importer)

1. every row carries an `https` `sourceUrl` — **no citation, no row**;
2. `entryDeadline <= windowStart` and `resultsDate >= windowEnd` — a real
   calendar satisfies both, a violation is a transcription error;
3. `windowEnd >= windowStart` (schema CHECK backs it);
4. qualification vocabulary frozen in the importer
   (`INTERNATIONAL_GCSE`, `IAL`) — widening is a code change with tests;
5. identical re-import is a no-op; a corrected calendar moves the measured
   fields **with** the newer citation (logged);
6. **no invented rows** — the not-yet-published November 2027 / 2028
   sittings are deliberately absent; estimated rows may only enter when a
   window is announced without a published timetable, and render with "≈"
   downstream.

## Consumers

- core: `V62__exam_series_calendar.sql` (schema) +
  `V63__exam_series_seed_pearson_2026_2027.sql` (the same five rows as a
  seed migration, the V6/V7 reference-data precedent) +
  `ExamSeriesFlowIT` (pins the seed == citation set);
- hub: the add-course picker + the countdown chip (core PR hub#34).
