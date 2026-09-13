package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkSchemeEntry;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * T-C04 repair regression: continuation-label rows and two-level label rows
 * in Edexcel mark-scheme tables.
 *
 * <p>Defect (found in T-C04 Batch-2): rows whose first cell is a bare
 * sub-part label — {@code (ii)}, {@code (iii)}, {@code (b)(i)}, {@code (c)},
 * {@code (d)} — or whose sub-part label sits in the second cell
 * ({@code 7 | (a)(i)}) never matched the question-number label pattern, so
 * they fell into the rowspan-continuation path: the answer text became
 * guidance of the previous entry and the marks cell was dropped with a
 * "bare integer cell skipped" warning. The committed MS.md sources contain
 * those rows; the canonical document retains them; only the draft layer
 * lost them.</p>
 *
 * <p>Coverage required by the repair directive:
 * (1) continuation rows {@code (ii)}/{@code (iii)};
 * (2) rows without repeated question-number prefixes ({@code (b)(i)},
 * {@code (c)}, {@code (d)});
 * (3) multi-part mark schemes;
 * (4) rows with equation/formula content;
 * (5) ordinary non-continuation rows (behavior unchanged);
 * (6) tables with multiple question groups;
 * (7) the real Specimen 2017 material (clean corpus anchor — frozen).</p>
 */
class GlmOcrMarkSchemeContinuationTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
    private final GlmOcrMarkSchemeExtractor extractor = new GlmOcrMarkSchemeExtractor();

    private static final String HEAD = "<table border=\"1\">"
            + "<tr><td>Question number</td><td>Answer</td><td>Notes</td><td>Marks</td></tr>";

    /** real-corpus fixture (2020 Jan-R 2C q2 row shapes, content minimized) */
    private GlmOcrMarkSchemeDraft extract(String body) {
        CanonicalDocument doc = parser.parse(
                (HEAD + body + "</table>").getBytes(StandardCharsets.UTF_8), "corpus/synthetic-ms");
        return extractor.extract(doc);
    }

    private List<String> labels(GlmOcrMarkSchemeDraft draft) {
        return draft.entries().stream().map(MarkSchemeEntry::label).toList();
    }

    @Test
    @DisplayName("continuation rows (ii)/(iii): retained, ordered, marks preserved (B01 shape)")
    void continuationRomanRows() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>2(a)</td><td>M1 below the dyesM2 pencil line</td><td>ACCEPT</td><td>2</td></tr>"
                + "<tr><td>2(b)(i)</td><td>conclusions about the colouring</td><td>ALLOW</td><td>3</td></tr>"
                + "<tr><td>(ii)</td><td>M1 distance 9.5(cm)M2 Rf expressionM3 evaluation</td>"
                + "<td>ALLOW tolerance</td><td>3</td></tr>"
                + "<tr><td>(iii)</td><td>(dye A) is not soluble in water</td><td>ALLOW solvent</td><td>1</td></tr>");

        assertThat(labels(draft)).containsExactly("2(a)", "2(b)(i)", "2(b)(ii)", "2(b)(iii)");
        MarkSchemeEntry ii = draft.entries().get(2);
        MarkSchemeEntry iii = draft.entries().get(3);
        assertThat(ii.marks()).isEqualTo(3);
        assertThat(iii.marks()).isEqualTo(1);
        assertThat(ii.marksCellSource()).isEqualTo("continuation label row");
        // text preserved verbatim
        assertThat(ii.answerText()).isEqualTo("M1 distance 9.5(cm)M2 Rf expressionM3 evaluation");
        assertThat(iii.answerText()).isEqualTo("(dye A) is not soluble in water");
        // guidance preserved on the continuation entries
        assertThat(ii.guidance()).extracting(g -> g.kind()).contains("allow");
        // nothing dropped, no ambiguity warnings
        assertThat(draft.warnings()).isEmpty();
    }

    @Test
    @DisplayName("letter-bearing continuation rows (b)(i)/(b)(ii)/(c): compound labels (B06 shape)")
    void continuationLetterRows() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>3(a)</td><td>alkanes</td><td></td><td>1</td></tr>"
                + "<tr><td>(b)(i)</td><td>boiling point difference</td><td>ALLOW</td><td>1</td></tr>"
                + "<tr><td>(b)(ii)</td><td>bitumen aeroplane fuel</td><td></td><td>3</td></tr>"
                + "<tr><td>(c)</td><td>M1 impurity sulfurM2 oxidised</td><td>IGNORE</td><td>3</td></tr>"
                + "<tr><td>3(d)(i)</td><td>cracking</td><td></td><td>1</td></tr>"
                + "<tr><td>(ii)</td><td>M1 catalyst silica</td><td>ALLOW alumina</td><td>2</td></tr>"
                + "<tr><td>(iii)</td><td>C13H28 to C8H18 chain</td><td></td><td>1</td></tr>");

        assertThat(labels(draft)).containsExactly(
                "3(a)", "3(b)(i)", "3(b)(ii)", "3(c)", "3(d)(i)", "3(d)(ii)", "3(d)(iii)");
        // ordering: document order preserved; marks preserved
        assertThat(draft.entries().stream().map(MarkSchemeEntry::marks))
                .containsExactly(1, 1, 3, 3, 1, 2, 1);
        // the roman continuation after 3(d)(i) resolved to (d), not the earlier (c)
        assertThat(draft.entries().get(5).label()).isEqualTo("3(d)(ii)");
        assertThat(draft.entries().get(5).answerText()).isEqualTo("M1 catalyst silica");
        assertThat(draft.warnings()).isEmpty();
    }

    @Test
    @DisplayName("two-level label rows: 7 | (a)(i) and spaced 'a (i)' — compound labels, answer at cell 2")
    void twoLevelLabelRows() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>7</td><td>(a)(i)</td><td>reversible reaction</td><td>IGNORE equilibrium</td><td>1</td></tr>"
                + "<tr><td>(ii)</td><td>increases the rate</td><td>REJECT yield</td><td>1</td></tr>"
                + "<tr><td>(b)</td><td>(ii)</td><td>M1 yield decreases</td><td>IGNORE rate</td><td>2</td></tr>"
                + "<tr><td>8</td><td>a (i)</td><td>M1 Mg2+</td><td></td><td>2</td></tr>");

        // two-level row: 7 + (a)(i) compound label; the answer is cell 2, NOT the label cell
        assertThat(labels(draft)).containsExactly("7(a)(i)", "7(a)(ii)", "8(a)(i)");
        assertThat(draft.entries().get(0).answerText()).isEqualTo("reversible reaction");
        assertThat(draft.entries().get(0).marks()).isEqualTo(1);
        assertThat(draft.entries().get(0).marksCellSource()).isEqualTo("two-level label row");
        // spaced sub-label "a (i)" canonicalized to (a)(i)
        assertThat(draft.entries().get(2).label()).isEqualTo("8(a)(i)");
        assertThat(draft.entries().get(2).answerText()).isEqualTo("M1 Mg2+");
        // (b)|(ii) two-level GROUP row stays on the continuation path (conservative:
        // its semantics are ambiguous in the source — no invented entries)
        assertThat(draft.entries().stream().noneMatch(e -> e.label().equals("7(b)(i)"))).isTrue();
    }

    @Test
    @DisplayName("equation content on continuation rows: preserved verbatim (2021 Jan q3 shape)")
    void equationContinuationRows() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>3(a)(i)</td><td>M1 dissolvingM2 diffusion</td><td>either order</td><td>2</td></tr>"
                + "<tr><td>(b)(i)</td><td>explanation any two pointsM1 crystals dissolve faster</td>"
                + "<td>ALLOW energy</td><td>2</td></tr>"
                + "<tr><td>(c)(i)(ii)</td><td>3/three 2+/+2</td><td>ALLOW Pb2+</td><td>11</td></tr>"
                + "<tr><td>(d)</td><td>Pb(NO3)2(aq)+2KI(aq)→PbI2(s)+2KNO3(aq)</td>"
                + "<td>ALLOW multiples</td><td>1</td></tr>");

        assertThat(labels(draft)).containsExactly("3(a)(i)", "3(b)(i)", "3(d)");
        MarkSchemeEntry d = draft.entries().get(2);
        assertThat(d.answerText()).isEqualTo("Pb(NO3)2(aq)+2KI(aq)→PbI2(s)+2KNO3(aq)");
        assertThat(d.marks()).isEqualTo(1);
        // (c)(i)(ii) — a letter + TWO roman groups — is not a single continuation
        // label: it stays on the conservative continuation path (documented),
        // never guessed into entries
        assertThat(labels(draft)).doesNotContain("3(c)(i)(ii)");
    }

    @Test
    @DisplayName("ordinary rows unchanged: label rows, rowspan continuations, totals, MCQ")
    void ordinaryRowsUnchanged() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>1</td><td>B The only correct answer is B because it is a compound</td><td></td><td>1</td></tr>"
                + "<tr><td>2(a)</td><td>M1 layers of atomsM2 electrostatic forces</td><td>ALLOW</td><td>2</td></tr>"
                + "<tr><td>M3 delocalised electrons</td><td>IGNORE metallic</td><td></td></tr>"
                + "<tr><td>Total for question 2</td><td></td><td></td><td>4</td></tr>"
                + "<tr><td>3</td><td>M1 rowspan-deferred answer</td><td></td><td></td></tr>"
                + "<tr><td>M2 later row carries the marks</td><td>IGNORE</td><td></td><td>2</td></tr>");

        // label rows open entries exactly as before the repair
        assertThat(labels(draft)).containsExactly("1", "2(a)", "3");
        // MCQ detection on ordinary rows still works
        assertThat(draft.entries().get(0).mcq()).isTrue();
        assertThat(draft.entries().get(0).correctOption()).isEqualTo("B");
        // rowspan continuation content still lands in guidance (3-cell rows —
        // the pre-repair behavior, deliberately unchanged)
        assertThat(draft.entries().get(1).answerText())
                .isEqualTo("M1 layers of atomsM2 electrostatic forces");
        assertThat(draft.entries().get(1).guidance())
                .anyMatch(g -> g.text().contains("M3 delocalised electrons"));
        // in-table total row still recorded
        assertThat(draft.questionTotals()).containsEntry("2", 4);
        // the marks-deferred rowspan path still works (empty marks cell on the
        // label row, integer arriving on a later row)
        assertThat(draft.entries().get(2).marks()).isEqualTo(2);
        assertThat(draft.entries().get(2).marksCellSource()).isEqualTo("rowspan continuation row");
    }

    @Test
    @DisplayName("multiple question groups in one table: letter context never crosses questions")
    void multipleQuestionGroups() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>5(a)</td><td>first group answer</td><td></td><td>1</td></tr>"
                + "<tr><td>(b)</td><td>first group part b</td><td></td><td>2</td></tr>"
                + "<tr><td>6</td><td>second group intro</td><td></td><td>1</td></tr>"
                + "<tr><td>(b)(i)</td><td>second group part b i</td><td></td><td>1</td></tr>"
                + "<tr><td>(ii)</td><td>second group part b ii</td><td></td><td>1</td></tr>"
                + "<tr><td>7(a)(i)</td><td>third group roman</td><td></td><td>2</td></tr>"
                + "<tr><td>(ii)</td><td>third group roman two</td><td></td><td>2</td></tr>");

        assertThat(labels(draft)).containsExactly(
                "5(a)", "5(b)", "6", "6(b)(i)", "6(b)(ii)", "7(a)(i)", "7(a)(ii)");
        // each continuation resolved within its own question's part sequence
        assertThat(draft.entries().get(1).label()).isEqualTo("5(b)");
        assertThat(draft.entries().get(4).label()).isEqualTo("6(b)(ii)");
        assertThat(draft.entries().get(6).label()).isEqualTo("7(a)(ii)");
        assertThat(draft.warnings()).isEmpty();
    }

    @Test
    @DisplayName("bare (ii) with no part-letter context: conservative, stays a continuation")
    void pureRomanWithoutLetterContext() {
        GlmOcrMarkSchemeDraft draft = extract(
                "<tr><td>10</td><td>question-level answer</td><td></td><td>1</td></tr>"
                + "<tr><td>(ii)</td><td>orphan roman row</td><td></td><td>1</td></tr>");

        // no (a)/letter context: the association would be a guess — the row is
        // NOT promoted to an entry (fail-closed), it stays continuation content
        assertThat(labels(draft)).containsExactly("10");
        assertThat(draft.entries().get(0).answerText()).isEqualTo("question-level answer");
        // the row content is not lost: it is preserved as continuation guidance
        assertThat(draft.entries().get(0).guidance())
                .anyMatch(g -> g.text().contains("orphan roman row"));
    }

    @Test
    @DisplayName("determinism: same input twice → identical draft (ids, labels, marks, warnings)")
    void deterministicExtraction() {
        String body =
                "<tr><td>2(b)(i)</td><td>conclusions</td><td></td><td>3</td></tr>"
                + "<tr><td>(ii)</td><td>M1 measured distance</td><td>ALLOW</td><td>3</td></tr>"
                + "<tr><td>7</td><td>(a)(i)</td><td>reversible</td><td>IGNORE</td><td>1</td></tr>";
        GlmOcrMarkSchemeDraft one = extract(body);
        GlmOcrMarkSchemeDraft two = extract(body);
        // same canonical identity → same entryIds; same entries; same warnings
        assertThat(one.entries()).isEqualTo(two.entries());
        assertThat(one.warnings()).isEqualTo(two.warnings());
        assertThat(one.entries().get(1).entryId()).isEqualTo(two.entries().get(1).entryId());
        // provenance unchanged: the extraction method identity is stable
        assertThat(one.extractionMethod()).isEqualTo("glm-ocr-ms-v1");
        assertThat(one.reviewRequired()).isTrue();
    }

    @Test
    @DisplayName("Specimen 2017 real corpus: clean material frozen — entries identical to the campaign archive")
    void specimen2017Frozen() throws IOException {
        CanonicalDocument doc = parser.parse(
                GlmOcrQuestionExtractorTest.fixture("specimen-2017-4ch1-1c-ms.md"),
                "corpus/igcse-chemistry-4ch0-1c-specimen2017/MS.md");
        GlmOcrMarkSchemeDraft draft = extractor.extract(doc);

        // frozen against the T-C04 campaign archive (byte-compared at the corpus
        // level in the repair dossier): the clean paper must not move
        assertThat(draft.entries()).hasSize(63);
        assertThat(draft.warnings()).isEmpty();
        assertThat(draft.paperTotal()).isEqualTo(110);
        assertThat(draft.questionTotals()).containsEntry("2", 7).containsEntry("11", 17);
        assertThat(labels(draft)).containsExactly(
                "1(a)", "1(b)", "1(c)", "1(d)", "1(e)",
                "2(a)(i)", "2(a)(ii)", "2(b)(i)", "2(b)(ii)", "2(b)(iii)",
                "3(a)", "3(b)(i)", "3(b)(ii)", "3(c)",
                "4(a)", "4(b)", "4(c)",
                "5(a)", "5(b)(i)", "5(b)(ii)", "5(b)(iii)",
                "6(a)", "6(a)", "6(b)(i)", "6(b)(ii)", "6(b)(iii)",
                "6(c)", "6(d)", "6(e)",
                "7(a)(i)", "7(a)(ii)", "7(a)(iii)", "7(a)(iv)",
                "7(b)(i)", "7(b)(ii)", "7(c)",
                "8(a)", "8(b)(i)", "8(b)(ii)", "8(c)",
                "9(a)", "9(b)", "9(c)", "9(d)",
                "9(e)(i)", "9(e)(ii)", "9(e)(iii)", "9(e)(iv)", "9(f)(i)", "9(f)(ii)",
                "10(a)", "10(b)", "10(c)(i)", "10(c)(ii)", "10(d)", "10(e)",
                "11(a)", "11(b)(i)", "11(b)(ii)", "11(b)(iii)", "11(c)", "11(d)", "11(e)");
        // marks frozen on a sample of rows (every entry's marks were verified
        // against the archive diff — zero changes on this paper)
        assertThat(draft.entries().stream().map(MarkSchemeEntry::marks).toList())
                .containsExactly(1, 1, 1, 1, 1,
                        2, 2, 1, 1, 1,
                        1, 2, 1, 3,
                        2, 3, 3,
                        2, 2, 2, 2,
                        1, 1, 2, 2, 1,
                        1, 1, 1,
                        1, 1, 3, 1,
                        2, 1, 4,
                        1, 1, 1, 2,
                        5, 3, 1, 1,
                        1, 1, 2, 1, 1, 3,
                        2, 2, 1, 1, 4, 2,
                        4, 2, 1, 1, 3, 3, 3);
    }
}
