package com.syllabai.parser.structure.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * Ingestion draft for a past-paper + mark-scheme pair (T-011 input). This is
 * heuristic v0 output: every question carries a confidence and the draft is
 * marked {@code reviewRequired} so downstream ingestion persists rows in
 * SUGGESTED validation state — nothing is silently treated as validated.
 *
 * @param schemaVersion   draft schema version ("1.0")
 * @param paper           paper metadata
 * @param questions       extracted questions with parts
 * @param markScheme      extracted mark scheme with mark points (nullable)
 * @param extractionMethod engine + heuristic identity
 * @param reviewRequired  always true in v0 — human validation pending
 */
public record PastPaperDraft(
        @JsonProperty("schemaVersion") String schemaVersion,
        @JsonProperty("paper") PaperMeta paper,
        @JsonProperty("questions") List<QuestionDraft> questions,
        @JsonProperty("markScheme") MarkSchemeDraft markScheme,
        @JsonProperty("extractionMethod") String extractionMethod,
        @JsonProperty("reviewRequired") boolean reviewRequired) {

    public static final String SCHEMA_VERSION = "1.0";

    /**
     * @param board            e.g. "Edexcel"
     * @param qualification    e.g. "IGCSE" or "IAL"
     * @param subject          e.g. "Chemistry"
     * @param unit             unit/paper label, e.g. "Paper 1C"
     * @param sessionLabel     e.g. "January 2012"
     * @param paperCode        exam paper code when known
     * @param questionPaperDocumentId  canonical documentId of the QP
     * @param markSchemeDocumentId     canonical documentId of the MS (nullable)
     */
    public record PaperMeta(
            @JsonProperty("board") String board,
            @JsonProperty("qualification") String qualification,
            @JsonProperty("subject") String subject,
            @JsonProperty("unit") String unit,
            @JsonProperty("sessionLabel") String sessionLabel,
            @JsonProperty("paperCode") String paperCode,
            @JsonProperty("questionPaperDocumentId") String questionPaperDocumentId,
            @JsonProperty("markSchemeDocumentId") String markSchemeDocumentId) {
    }

    /**
     * @param externalRef    stable ref, e.g. "QP-jan2012-1C-q3"
     * @param questionNumber "3"
     * @param prompt         question stem (unsplit v0)
     * @param commandWord    leading command word of the stem (nullable)
     * @param marks          total marks (sum of parts when parts exist)
     * @param questionType   "STRUCTURED" for multi-part, "SHORT_ANSWER" otherwise
     * @param pageNumber     QP page the question starts on
     * @param confidence     extraction confidence 0–1
     * @param parts          extracted parts (may be empty)
     */
    public record QuestionDraft(
            @JsonProperty("externalRef") String externalRef,
            @JsonProperty("questionNumber") String questionNumber,
            @JsonProperty("prompt") String prompt,
            @JsonProperty("commandWord") String commandWord,
            @JsonProperty("marks") int marks,
            @JsonProperty("questionType") String questionType,
            @JsonProperty("pageNumber") int pageNumber,
            @JsonProperty("confidence") double confidence,
            @JsonProperty("parts") List<PartDraft> parts) {
    }

    /**
     * @param label      part label, "a", "b", "a-i", …
     * @param prompt     part text
     * @param commandWord leading command word (nullable)
     * @param marks      part marks (0 when not found)
     * @param confidence extraction confidence 0–1
     */
    public record PartDraft(
            @JsonProperty("label") String label,
            @JsonProperty("prompt") String prompt,
            @JsonProperty("commandWord") String commandWord,
            @JsonProperty("marks") int marks,
            @JsonProperty("confidence") double confidence) {
    }

    /**
     * @param version           mark-scheme version label ("1")
     * @param sourceDocumentId  canonical documentId of the MS
     * @param points            extracted mark points
     */
    public record MarkSchemeDraft(
            @JsonProperty("version") String version,
            @JsonProperty("sourceDocumentId") String sourceDocumentId,
            @JsonProperty("points") List<MarkPointDraft> points) {
    }

    /**
     * @param questionRef  "3" or "3-a" matching the question/part
     * @param order        order within its part
     * @param text         mark-point text
     * @param marks        marks the point awards
     * @param acceptance   v0: empty — deterministic matching criteria are
     *                     authored at validation time, not invented here
     * @param confidence   extraction confidence 0–1
     */
    public record MarkPointDraft(
            @JsonProperty("questionRef") String questionRef,
            @JsonProperty("order") int order,
            @JsonProperty("text") String text,
            @JsonProperty("marks") int marks,
            @JsonProperty("acceptance") List<String> acceptance,
            @JsonProperty("confidence") double confidence) {
    }
}
