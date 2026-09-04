package com.syllabai.parser.structure.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * GLM-OCR question-paper draft (Session 8). Everything extracted by
 * {@code GlmOcrQuestionExtractor} is a <strong>draft</strong>: confidence
 * &lt; 1.0, {@code reviewRequired=true} (Master Spec §7 — algorithmic
 * suggestions stay distinguishable from validated structure).
 *
 * <p>Unlike the generic {@code PastPaperDraft}, this draft carries the
 * GLM-OCR-specific facts the syntax report demands: MCQ options, per-question
 * and per-part <em>unavailable</em> figure references, per-part marks blocks,
 * answer prompts, and extraction warnings (defect evidence, never silently
 * repaired).</p>
 *
 * @param schemaVersion   draft schema version ("1.0")
 * @param extractionMethod extractor identity ("glm-ocr-qp-v1")
 * @param reviewRequired  always true for v0 drafts
 * @param paper           identity derived from content (paper reference etc.)
 * @param questions       extracted questions in document order
 * @param questionTotals  "Total for Question N = X marks" per question number
 * @param paperTotal      TOTAL FOR PAPER marks (or "total mark for this paper" line)
 * @param sectionTotals   SECTION → marks (e.g. "A" → 10, "B" → 70)
 * @param frontMatterFigures figures before the first question (covers, boxes)
 * @param warnings        defect/warning evidence lines
 */
public record GlmOcrPaperDraft(
        @JsonProperty("schemaVersion") String schemaVersion,
        @JsonProperty("extractionMethod") String extractionMethod,
        @JsonProperty("reviewRequired") boolean reviewRequired,
        @JsonProperty("paper") PaperMeta paper,
        @JsonProperty("questions") List<QuestionDraft> questions,
        @JsonProperty("questionTotals") Map<String, Integer> questionTotals,
        @JsonProperty("paperTotal") Integer paperTotal,
        @JsonProperty("sectionTotals") Map<String, Integer> sectionTotals,
        @JsonProperty("frontMatterFigures") List<FigureRef> frontMatterFigures,
        @JsonProperty("warnings") List<String> warnings) {

    public static final String SCHEMA_VERSION = "1.0";

    public GlmOcrPaperDraft {
        questions = questions == null ? List.of() : List.copyOf(questions);
        questionTotals = questionTotals == null ? Map.of() : Map.copyOf(questionTotals);
        sectionTotals = sectionTotals == null ? Map.of() : Map.copyOf(sectionTotals);
        frontMatterFigures = frontMatterFigures == null
                ? List.of() : List.copyOf(frontMatterFigures);
        warnings = warnings == null ? List.of() : List.copyOf(warnings);
    }

    /** Paper identity derived from document content, never from file names. */
    public record PaperMeta(
            @JsonProperty("board") String board,
            @JsonProperty("qualification") String qualification,
            @JsonProperty("subject") String subject,
            @JsonProperty("paperReference") String paperReference,
            @JsonProperty("logNumber") String logNumber,
            @JsonProperty("publicationCode") String publicationCode,
            @JsonProperty("session") String session,
            @JsonProperty("examDate") String examDate,
            @JsonProperty("duration") String duration,
            @JsonProperty("canonicalDocumentId") String canonicalDocumentId) {
    }

    /**
     * One extracted question.
     *
     * @param questionId     deterministic id ("q01-<docShort>")
     * @param number         question number from the paper
     * @param numberingStyle "colon" (June style "1:") or "space" ("1 ") or null
     * @param section        SECTION letter active when the question started
     * @param stem           stem text (mark-free)
     * @param mcq            true iff a complete A–D option set was validated
     * @param options        MCQ options (empty when not MCQ)
     * @param parts          letter/roman parts
     * @param figures        figure refs attached to the question (stem level)
     * @param tableElementIds canonical tables embedded in the question
     * @param marks           best-known marks (part sum, else paper total)
     * @param marksKnown      whether marks are exact (all parts carried marks)
     * @param qwc             asterisk (quality of written communication) marker
     * @param answerPrompts   answer-space prompts ending in "=" (stem level)
     * @param confidence      extraction confidence (always &lt; 1.0)
     */
    public record QuestionDraft(
            @JsonProperty("questionId") String questionId,
            @JsonProperty("number") int number,
            @JsonProperty("numberingStyle") String numberingStyle,
            @JsonProperty("section") String section,
            @JsonProperty("stem") String stem,
            @JsonProperty("mcq") boolean mcq,
            @JsonProperty("options") List<McqOption> options,
            @JsonProperty("parts") List<PartDraft> parts,
            @JsonProperty("figures") List<FigureRef> figures,
            @JsonProperty("tableElementIds") List<String> tableElementIds,
            @JsonProperty("marks") int marks,
            @JsonProperty("marksKnown") boolean marksKnown,
            @JsonProperty("qwc") boolean qwc,
            @JsonProperty("answerPrompts") List<String> answerPrompts,
            @JsonProperty("confidence") double confidence) {

        public QuestionDraft {
            options = options == null ? List.of() : List.copyOf(options);
            parts = parts == null ? List.of() : List.copyOf(parts);
            figures = figures == null ? List.of() : List.copyOf(figures);
            tableElementIds = tableElementIds == null
                    ? List.of() : List.copyOf(tableElementIds);
            answerPrompts = answerPrompts == null ? List.of() : List.copyOf(answerPrompts);
        }
    }

    /**
     * One letter part (with optional roman subparts as separate entries whose
     * label is "b-i" style).
     */
    public record PartDraft(
            @JsonProperty("partId") String partId,
            @JsonProperty("label") String label,
            @JsonProperty("text") String text,
            @JsonProperty("marks") Integer marks,
            @JsonProperty("qwc") boolean qwc,
            @JsonProperty("figures") List<FigureRef> figures,
            @JsonProperty("answerPrompts") List<String> answerPrompts,
            @JsonProperty("confidence") double confidence) {

        public PartDraft {
            figures = figures == null ? List.of() : List.copyOf(figures);
            answerPrompts = answerPrompts == null ? List.of() : List.copyOf(answerPrompts);
        }
    }

    /** MCQ option; letters may arrive out of order (documented defect #9). */
    public record McqOption(
            @JsonProperty("letter") String letter,
            @JsonProperty("text") String text) {
    }

    /**
     * A figure reference. For the audited corpus the bytes are gone
     * (expired signed URLs), so {@code availability} is
     * "unavailable-signed-url" and {@code sourceName} carries the durable
     * URL-path crop identity.
     */
    public record FigureRef(
            @JsonProperty("elementId") String elementId,
            @JsonProperty("sourceName") String sourceName,
            @JsonProperty("format") String format,
            @JsonProperty("url") String url,
            @JsonProperty("availability") String availability) {
    }
}
