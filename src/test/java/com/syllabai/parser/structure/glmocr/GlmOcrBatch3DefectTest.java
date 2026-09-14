package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkSchemeEntry;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.QuestionDraft;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * T-C04 Batch-3 defect-class regression (session 66). Three extraction
 * defects found by the Batch-3 review, each fixed conservatively:
 *
 * <p><b>D1 — QP OCR-damaged part label</b> ({@code b)} closing paren only,
 * 2022-Jan-R 1(b) / 2024-Jun-R 11(d) shape): the part is recovered only when
 * its letter continues the established part sequence; a first-part guess or a
 * sequence mismatch stays plain text.</p>
 *
 * <p><b>D2 — MS table-start continuation rows</b> (2019-Jan 5(d)(iii)/(iv)
 * shape): a question's mark-scheme table split in two; the second table's
 * first rows are bare {@code (iii)}/{@code (iv)} labels. The carried
 * question/letter context of the previous table associates them. No context
 * anywhere → still conservative (orphan warning, no invented entry).</p>
 *
 * <p><b>D3 — marks-cell arithmetic</b>: a multi-line all-integer marks cell
 * ({@code 1\n1}) is the stacked per-line marks of a rowspan'd answer → sum
 * (guards: 2–3 lines, sum ≤ 12; graph-axis/data shapes stay null); and a
 * single-cell bare-integer row is a rowspan continuation's marks column —
 * never a question-level label (2011-Jun q1 "Total 8 marks" reconciliation,
 * previously a stray entry {@code 1} with 1 mark).</p>
 */
class GlmOcrBatch3DefectTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
    private final GlmOcrMarkSchemeExtractor msExtractor = new GlmOcrMarkSchemeExtractor();
    private final GlmOcrQuestionExtractor qpExtractor = new GlmOcrQuestionExtractor();

    private static final String TBL_HEAD = "<table border=\"1\">"
            + "<tr><td>Question number</td><td>Answer</td><td>Notes</td><td>Marks</td></tr>";

    private GlmOcrMarkSchemeDraft ms(String... tables) {
        StringBuilder md = new StringBuilder();
        for (String t : tables) {
            md.append(TBL_HEAD).append(t).append("</table>\n");
        }
        CanonicalDocument doc = parser.parse(md.toString().getBytes(StandardCharsets.UTF_8),
                "corpus/synthetic-batch3-ms");
        return msExtractor.extract(doc);
    }

    private List<String> labels(GlmOcrMarkSchemeDraft draft) {
        return draft.entries().stream().map(MarkSchemeEntry::label).toList();
    }

    // ── D2: table-start continuation rows ─────────────────────────────────────

    @Test
    @DisplayName("D2: table split mid-question — second table's (iii)/(iv) recovered (2019-Jan q5)")
    void tableStartContinuationRecovered() {
        GlmOcrMarkSchemeDraft draft = ms(
                // table 1: q5 through 5(d)(ii)
                "<tr><td>5(a)</td><td>alkali</td><td></td><td>1</td></tr>"
                + "<tr><td>(b)</td><td>M1 indicatorM2 pH</td><td>ALLOW</td><td>2</td></tr>"
                + "<tr><td>(c)(i)</td><td>to dry the gas</td><td></td><td>1</td></tr>"
                + "<tr><td>(d)(i)</td><td>sulfurous acid</td><td></td><td>1</td></tr>"
                + "<tr><td>(ii)</td><td>red/pink</td><td></td><td>1</td></tr>",
                // table 2: continues 5(d) — the printed layout split
                "<tr><td>(iii)</td><td>H+</td><td>ACCEPT H3O+</td><td>1</td></tr>"
                + "<tr><td>(iv)</td><td>orange</td><td>ALLOW yellow</td><td>1</td></tr>");

        assertThat(labels(draft)).containsExactly(
                "5(a)", "5(b)", "5(c)(i)", "5(d)(i)", "5(d)(ii)", "5(d)(iii)", "5(d)(iv)");
        MarkSchemeEntry iii = draft.entries().get(5);
        MarkSchemeEntry iv = draft.entries().get(6);
        assertThat(iii.answerText()).isEqualTo("H+");
        assertThat(iii.marks()).isEqualTo(1);
        assertThat(iii.marksCellSource()).isEqualTo("table-start continuation row");
        assertThat(iv.answerText()).isEqualTo("orange");
        assertThat(iv.marks()).isEqualTo(1);
        assertThat(iv.marksCellSource()).isEqualTo("continuation label row");
    }

    @Test
    @DisplayName("D2: letter-bearing table-start continuation (2011-Jun 10(f) shape)")
    void tableStartLetterContinuation() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>10(e)</td><td>filter</td><td>ALLOW decant</td><td>1</td></tr>",
                "<tr><td>(f)</td><td>NaNO2</td><td>Award mark if 138 seen</td><td>1</td></tr>");

        assertThat(labels(draft)).containsExactly("10(e)", "10(f)");
        assertThat(draft.entries().get(1).marksCellSource())
                .isEqualTo("table-start continuation row");
    }

    @Test
    @DisplayName("D2 conservative: bare roman with no context anywhere — no invented entry")
    void tableStartNoContextStaysConservative() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>(iii)</td><td>H+</td><td>ACCEPT</td><td>1</td></tr>");

        assertThat(labels(draft)).isEmpty();
        assertThat(draft.warnings()).anySatisfy(
                w -> assertThat(w).contains("orphan row"));
    }

    // ── D3a: multi-line marks cells ────────────────────────────────────────────

    @Test
    @DisplayName("D3a: stacked per-line marks '1\\n1' → entry marks 2 (2011-Jun 1(c)(ii))")
    void stackedMarksSummed() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>1(a)</td><td>electron(s)</td><td></td><td>1</td></tr>"
                + "<tr><td>(c)(i)</td><td>protons and electrons</td><td></td><td>1</td></tr>"
                + "<tr><td>(ii)</td><td>protons\nneutrons</td><td></td><td>1\n1</td></tr>"
                + "<tr><td>(d)(i)</td><td>12</td><td></td><td>1</td></tr>");

        MarkSchemeEntry cii = draft.entries().get(2);
        assertThat(cii.label()).isEqualTo("1(c)(ii)");
        assertThat(cii.marks()).isEqualTo(2);
        assertThat(cii.marksCellSource()).isEqualTo("continuation label row");
        // full-question arithmetic reconciles: 1+1+2+1 = 5 across the shown rows
    }

    @Test
    @DisplayName("D3a: three stacked lines summed; guards keep data cells out")
    void stackedMarksGuards() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>2(a)</td><td>three point answer</td><td></td><td>1\n1\n1</td></tr>"
                + "<tr><td>(b)</td><td>graph axes data</td><td></td>"
                + "<td>30\n25\n20\n0\n10\n20\n30\n40</td></tr>"
                + "<tr><td>(c)</td><td>sum too big</td><td></td><td>11\n11\n1</td></tr>");

        assertThat(draft.entries().get(0).marks()).isEqualTo(3);   // 3 stacked lines
        assertThat(draft.entries().get(1).marks()).isNull();       // 8 lines — data, not marks
        assertThat(draft.entries().get(2).marks()).isNull();       // sum 23 — out of range
    }

    // ── D3b: single-cell bare-integer rows ────────────────────────────────────

    @Test
    @DisplayName("D3b: trailing '<tr><td>1</td></tr>' never becomes a stray question-level entry")
    void singleCellMarksRowNeverALabel() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>11(a)</td><td>breaking bonds absorbs energy</td><td></td><td>1</td></tr>"
                + "<tr><td>(b)(i)</td><td>from white to blue</td><td>Reject colourless</td>"
                + "<td>1</td></tr>"
                + "<tr><td>Ignore qualifiers</td><td>1</td></tr>"
                + "<tr><td>1</td></tr>");

        assertThat(labels(draft)).containsExactly("11(a)", "11(b)(i)");
        // no stray "1" entry with its own marks — the printed 1 is delivered
        // to the open entry (marks already set → ambiguity warning, skipped)
        assertThat(draft.warnings()).anySatisfy(
                w -> assertThat(w).contains("integer cell").contains("skipped"));
    }

    @Test
    @DisplayName("D3b: single-cell marks row delivered when the open entry is unmarked")
    void singleCellMarksDelivered() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>3(a)</td><td>answer text</td><td>note</td><td></td></tr>"
                + "<tr><td>2</td></tr>");

        MarkSchemeEntry a = draft.entries().get(0);
        assertThat(a.label()).isEqualTo("3(a)");
        assertThat(a.marks()).isEqualTo(2);
        assertThat(a.marksCellSource()).isEqualTo("rowspan continuation row");
    }

    // ── D3c: bare in-table Total rows ─────────────────────────────────────────

    @Test
    @DisplayName("D3c: bare 'Total | 9' row recorded as the question total, never as part marks")
    void bareTotalRowRecordedAsTotalNotMarks() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>3(c)</td><td>copper sulfate completely reacted</td><td></td>"
                + "<td></td><td>1</td></tr>"
                + "<tr><td>(d)</td><td>M1 smaller with magnesium\nM2 fewer moles</td>"
                + "<td></td><td></td><td>1\n1</td></tr>"
                + "<tr><td></td><td></td><td></td><td>Total</td><td>9</td></tr>");

        assertThat(labels(draft)).containsExactly("3(c)", "3(d)");
        // the stacked cell is 3(d)'s marks; the printed 9 is question 3's TOTAL
        assertThat(draft.entries().get(1).marks()).isEqualTo(2);
        assertThat(draft.questionTotals()).containsEntry("3", 9);
    }

    @Test
    @DisplayName("D3c: bare Total row cannot deliver marks even when the entry is unmarked")
    void bareTotalRowNeverDeliversMarks() {
        GlmOcrMarkSchemeDraft draft = ms(
                "<tr><td>4(a)</td><td>answer</td><td></td><td></td><td></td></tr>"
                + "<tr><td></td><td></td><td>Total</td><td>7</td></tr>");

        assertThat(draft.entries().get(0).marks()).isNull();
        assertThat(draft.questionTotals()).containsEntry("4", 7);
    }

    // ── D1: QP OCR-damaged part labels ────────────────────────────────────────

    private GlmOcrPaperDraft qp(String body) {
        CanonicalDocument doc = parser.parse(
                body.getBytes(StandardCharsets.UTF_8), "corpus/synthetic-batch3-qp");
        return qpExtractor.extract(doc);
    }

    @Test
    @DisplayName("D1: 'b)' closing-paren-only part recovered when it continues the sequence")
    void tolerantPartLabelRecovered() {
        GlmOcrPaperDraft draft = qp(
                "1 This question is about acids.\n"
                + "(a) Which of these is the colour of litmus in an acidic solution?\n"
                + "A blue\nB orange\nC red\nD yellow\n"
                + "b) Which of these is the pH value of a neutral solution?\n"
                + "A 0\nB 4\nC 7\nD 14\n"
                + "(c) Which of these describes a solution with a pH value of 9?\n");

        QuestionDraft q1 = draft.questions().get(0);
        assertThat(q1.parts()).extracting(p -> p.label())
                .containsExactly("a", "b", "c");
        assertThat(q1.parts().get(1).text())
                .startsWith("Which of these is the pH value of a neutral solution?");
        assertThat(draft.warnings()).anySatisfy(
                w -> assertThat(w).contains("OCR-damaged part label \"b)\""));
    }

    @Test
    @DisplayName("D1 conservative: first-part guess and sequence mismatch both rejected")
    void tolerantPartLabelGuards() {
        GlmOcrPaperDraft first = qp(
                "1 State two observations.\n"
                + "b) Not the first part of anything.\n");
        assertThat(first.questions().get(0).parts()).isEmpty();
        assertThat(first.warnings())
                .noneMatch(w -> w.contains("OCR-damaged part label"));

        GlmOcrPaperDraft mismatch = qp(
                "1 Explain the following.\n"
                + "(a) first part\n"
                + "d) sequence mismatch — previous letter is a\n");
        // 'd' does not follow 'a' → stays plain text attached to part (a)
        assertThat(mismatch.questions().get(0).parts())
                .extracting(p -> p.label()).containsExactly("a");
        assertThat(mismatch.warnings())
                .noneMatch(w -> w.contains("OCR-damaged part label"));
    }
}
