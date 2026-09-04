package com.syllabai.parser.structure.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PaperMeta;
import java.util.List;
import java.util.Map;

/**
 * GLM-OCR mark-scheme draft (Session 9). Everything extracted by
 * {@code GlmOcrMarkSchemeExtractor} is a <strong>draft</strong>:
 * {@code reviewRequired=true}, confidence &lt; 1.0 (Master Spec §7).
 *
 * <p>Structure is table-first, per the real-corpus syntax report: Edexcel
 * mark schemes live in HTML tables whose rows are question / question-part
 * entries ({@code 11}, {@code 13(a)}, {@code *14}), with marks cells that
 * may be {@code rowspan}-deferred, in-table {@code Total for question N}
 * rows (October export) or standalone {@code (Total for Question N=X marks)}
 * lines (June/1A export), and an Indicative-Content (IC) table either
 * standalone or embedded inside the QWC question. The marking-semantics
 * vocabulary (Allow / Ignore / dependent-on-MP / ecf / Or / Any-two-from /
 * Example calculation) survives as structured metadata, never flattened to
 * plain text.</p>
 *
 * @param schemaVersion    draft schema version ("1.0")
 * @param extractionMethod extractor identity ("glm-ocr-ms-v1")
 * @param reviewRequired   always true for v0 drafts
 * @param paper            content-derived identity (paper ref, log number,
 *                         publication code, session) for QP/MS pairing
 * @param entries          question / question-part rows in document order
 * @param questionTotals   "N" → total marks from both total placements
 * @param paperTotal       TOTAL FOR PAPER from the MS (may conflict with
 *                         the QP — reconciliation flags it, never merges)
 * @param icTable          indicative-content table (null when absent)
 * @param warnings         defect evidence; nothing is silently repaired
 */
public record GlmOcrMarkSchemeDraft(
        @JsonProperty("schemaVersion") String schemaVersion,
        @JsonProperty("extractionMethod") String extractionMethod,
        @JsonProperty("reviewRequired") boolean reviewRequired,
        @JsonProperty("paper") PaperMeta paper,
        @JsonProperty("entries") List<MarkSchemeEntry> entries,
        @JsonProperty("questionTotals") Map<String, Integer> questionTotals,
        @JsonProperty("paperTotal") Integer paperTotal,
        @JsonProperty("icTable") IcTable icTable,
        @JsonProperty("warnings") List<String> warnings) {

    public static final String SCHEMA_VERSION = "1.0";

    public GlmOcrMarkSchemeDraft {
        entries = entries == null ? List.of() : List.copyOf(entries);
        questionTotals = questionTotals == null ? Map.of() : Map.copyOf(questionTotals);
        warnings = warnings == null ? List.of() : List.copyOf(warnings);
    }

    /**
     * One mark-scheme row: a question or question-part.
     *
     * @param entryId      deterministic id ("ms-&lt;docShort&gt;-q13a")
     * @param label        printed label ("11", "13(a)", "14")
     * @param number       question number
     * @param qwc          true when printed with a leading asterisk ("*14")
     * @param mcq          true when the answer cell names a single option
     * @param correctOption the option letter for MCQ rows, else null
     * @param answerText   full answer-cell text (raw apart from entity
     *                     decoding; multi-line preserved)
     * @param markPoints   marking points split on "(N)" markers
     * @param guidance     classified Additional-Guidance lines
     * @param marks        printed Mark cell; null when rowspan-deferred or
     *                     absent (never guessed)
     * @param marksCellSource where the marks value came from
     * @param confidence   extraction confidence (always &lt; 1.0)
     */
    public record MarkSchemeEntry(
            @JsonProperty("entryId") String entryId,
            @JsonProperty("label") String label,
            @JsonProperty("number") int number,
            @JsonProperty("qwc") boolean qwc,
            @JsonProperty("mcq") boolean mcq,
            @JsonProperty("correctOption") String correctOption,
            @JsonProperty("answerText") String answerText,
            @JsonProperty("markPoints") List<MarkPoint> markPoints,
            @JsonProperty("guidance") List<GuidanceLine> guidance,
            @JsonProperty("marks") Integer marks,
            @JsonProperty("marksCellSource") String marksCellSource,
            @JsonProperty("confidence") double confidence) {

        public MarkSchemeEntry {
            markPoints = markPoints == null ? List.of() : List.copyOf(markPoints);
            guidance = guidance == null ? List.of() : List.copyOf(guidance);
        }
    }

    /**
     * One marking point (an "(N)"-terminated segment of the answer cell).
     *
     * @param ordinal     MP ordinal in cell order (1 = MP1)
     * @param text        marking-point text, markers stripped
     * @param marks       mark value from the "(N)" marker (null when the
     *                    segment carries no marker)
     * @param dependentOn MP references from "dependent on MPn" clauses
     * @param ecf         error-carried-forward mention
     * @param alternatives "Or" alternative segments (same credit)
     * @param anyTwoFrom  "Any two from" group marker
     * @param reject      "Do not accept" / "insufficient" note present
     * @param rawText     the unsplit segment, preserved verbatim
     */
    public record MarkPoint(
            @JsonProperty("ordinal") int ordinal,
            @JsonProperty("text") String text,
            @JsonProperty("marks") Integer marks,
            @JsonProperty("dependentOn") List<String> dependentOn,
            @JsonProperty("ecf") boolean ecf,
            @JsonProperty("alternatives") List<String> alternatives,
            @JsonProperty("anyTwoFrom") boolean anyTwoFrom,
            @JsonProperty("reject") boolean reject,
            @JsonProperty("rawText") String rawText) {

        public MarkPoint {
            dependentOn = dependentOn == null ? List.of() : List.copyOf(dependentOn);
            alternatives = alternatives == null ? List.of() : List.copyOf(alternatives);
        }
    }

    /**
     * One Additional-Guidance line, classified by leading keyword.
     *
     * @param kind allow | ignore | example-calculation | example-diagram | ecf
     *             | dependent | note
     * @param text the line as printed (glued OCR words preserved)
     */
    public record GuidanceLine(
            @JsonProperty("kind") String kind,
            @JsonProperty("text") String text) {
    }

    /**
     * Indicative-content table (QWC questions): IC points → IC mark → max
     * linkage mark → max final mark.
     *
     * @param rows     numeric rows, e.g. ["6","4","2","6"]
     * @param location "standalone" or "embedded"
     */
    public record IcTable(
            @JsonProperty("rows") List<List<String>> rows,
            @JsonProperty("location") String location) {

        public IcTable {
            rows = rows == null ? List.of() : List.copyOf(rows);
        }
    }
}
