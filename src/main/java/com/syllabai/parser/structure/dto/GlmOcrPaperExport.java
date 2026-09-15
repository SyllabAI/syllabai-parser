package com.syllabai.parser.structure.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.GuidanceLine;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkPoint;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.FigureRef;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.McqOption;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PaperMeta;
import java.util.List;
import java.util.Map;

/**
 * Java mirror of the per-sitting atomizer's export shape (OCR-Q4,
 * {@code tools/glmocr/atomize.py}; {@code schemaVersion: "1.0"},
 * {@code tool: "glmocr-atomize"}).
 *
 * <p>The export is the atomic Question/QuestionPart unit set the product
 * modules need (Target Test, Test Builder, Smart Mark): every part carries
 * its <strong>inherited stem context</strong> (question stem + parent-part
 * lead-in) so it renders self-contained, plus its matched mark-scheme entry
 * when one exists. The Python tool is the behavioral reference; this record
 * family mirrors its field names, nullability and ordering so
 * {@code tools/glmocr/conformance.py} can diff both implementations
 * field-by-field (the {@code atomize} stage).</p>
 *
 * <p>Design honesty (Master Spec §7 / reconciliation D4-D6), mirrored
 * verbatim from the Python tool: everything exported is a draft
 * ({@code reviewRequired: true}); confidence values pass through, never
 * inflated; {@code renderedPrompt} is a concatenation of verbatim slices
 * only; gaps are reported ({@code markScheme: null} +
 * {@code warnings.atomize} lines, {@code unmatched.msEntries}), never
 * silently merged or dropped. Nulls are serialized explicitly — unlike the
 * draft DTOs there is no NON_NULL elision, because the reference output
 * always carries every key.</p>
 *
 * @param schemaVersion  export schema version ("1.0")
 * @param tool           producing tool ("glmocr-atomize")
 * @param reviewRequired always true — the export is a draft, never validated
 * @param engine         extraction engine identity (name + version)
 * @param source         QP/MS provenance: uri, documentId, checksum
 * @param paper          QP paper identity (same shape as the QP draft meta)
 * @param questions      atomic questions in QP draft order
 * @param totals         numerically sorted question totals + paper total +
 *                       their sum (null when no totals)
 * @param unmatched      mark-scheme entries with no QP counterpart (labels,
 *                       draft order)
 * @param warnings       defect/gap evidence: QP draft, MS draft, atomize
 */
public record GlmOcrPaperExport(
        @JsonProperty("schemaVersion") String schemaVersion,
        @JsonProperty("tool") String tool,
        @JsonProperty("reviewRequired") boolean reviewRequired,
        @JsonProperty("engine") Engine engine,
        @JsonProperty("source") Source source,
        @JsonProperty("paper") PaperMeta paper,
        @JsonProperty("questions") List<ExportQuestion> questions,
        @JsonProperty("totals") Totals totals,
        @JsonProperty("unmatched") Unmatched unmatched,
        @JsonProperty("warnings") Warnings warnings) {

    public static final String EXPORT_SCHEMA_VERSION = "1.0";
    public static final String TOOL_NAME = "glmocr-atomize";

    public GlmOcrPaperExport {
        questions = questions == null ? List.of() : List.copyOf(questions);
    }

    /** Extraction engine identity (same strings as the canonical provenance). */
    public record Engine(
            @JsonProperty("name") String name,
            @JsonProperty("version") String version) {
    }

    /** One paired source document's provenance. */
    public record SourceDoc(
            @JsonProperty("uri") String uri,
            @JsonProperty("documentId") String documentId,
            @JsonProperty("checksum") String checksum) {
    }

    /** QP + MS provenance pair. */
    public record Source(
            @JsonProperty("qp") SourceDoc qp,
            @JsonProperty("ms") SourceDoc ms) {
    }

    /**
     * Mark-scheme view bound to a question or part (Python {@code _ms_view}):
     * only the fields a marking product needs; the full entry stays in the
     * MS draft bundle.
     *
     * @param marks      null when the entry carries no marks cell
     * @param confidence passes through, never inflated
     */
    public record MarkSchemeView(
            @JsonProperty("label") String label,
            @JsonProperty("answerText") String answerText,
            @JsonProperty("markPoints") List<MarkPoint> markPoints,
            @JsonProperty("guidance") List<GuidanceLine> guidance,
            @JsonProperty("marks") Integer marks,
            @JsonProperty("confidence") double confidence) {
    }

    /**
     * One self-contained question part.
     *
     * @param msLabel        printed-suffix form ("(a)(i)") used for pairing
     * @param renderedPrompt question stem + parent-part lead-in + own text,
     *                       verbatim slices joined with blank lines
     * @param markScheme     null when no mark-scheme entry matched — reported,
     *                       never guessed
     */
    public record ExportPart(
            @JsonProperty("partId") String partId,
            @JsonProperty("label") String label,
            @JsonProperty("msLabel") String msLabel,
            @JsonProperty("text") String text,
            @JsonProperty("renderedPrompt") String renderedPrompt,
            @JsonProperty("marks") Integer marks,
            @JsonProperty("qwc") boolean qwc,
            @JsonProperty("figures") List<FigureRef> figures,
            @JsonProperty("answerPrompts") List<String> answerPrompts,
            @JsonProperty("confidence") double confidence,
            @JsonProperty("markScheme") MarkSchemeView markScheme) {
    }

    /**
     * One atomic question. The question-level {@code markScheme} binds only
     * for partless (typically MCQ) questions via the bare-number entry.
     */
    public record ExportQuestion(
            @JsonProperty("questionId") String questionId,
            @JsonProperty("number") int number,
            @JsonProperty("numberingStyle") String numberingStyle,
            @JsonProperty("section") String section,
            @JsonProperty("stem") String stem,
            @JsonProperty("mcq") boolean mcq,
            @JsonProperty("options") List<McqOption> options,
            @JsonProperty("qwc") boolean qwc,
            @JsonProperty("figures") List<FigureRef> figures,
            @JsonProperty("tableElementIds") List<String> tableElementIds,
            @JsonProperty("marks") int marks,
            @JsonProperty("marksKnown") boolean marksKnown,
            @JsonProperty("confidence") double confidence,
            @JsonProperty("markScheme") MarkSchemeView markScheme,
            @JsonProperty("parts") List<ExportPart> parts) {
    }

    /**
     * Totals block: {@code questionTotals} keys sorted numerically (the QP
     * draft order is draft-internal), {@code sumOfQuestionTotals} null when
     * no totals exist.
     */
    public record Totals(
            @JsonProperty("questionTotals") Map<String, Integer> questionTotals,
            @JsonProperty("paperTotal") Integer paperTotal,
            @JsonProperty("sumOfQuestionTotals") Integer sumOfQuestionTotals) {
    }

    /** Mark-scheme entries with no QP counterpart (labels, draft order). */
    public record Unmatched(
            @JsonProperty("msEntries") List<String> msEntries) {
    }

    /** QP-draft, MS-draft and atomize-pairing warning lines, verbatim. */
    public record Warnings(
            @JsonProperty("qp") List<String> qp,
            @JsonProperty("ms") List<String> ms,
            @JsonProperty("atomize") List<String> atomize) {
    }
}
