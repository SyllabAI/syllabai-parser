package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.QuestionDraft;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Real-corpus GLM-OCR question extraction (Session 9). All six audited
 * sample files from {@code Past-Papers/GLM-markdown-sample/} are pinned as
 * fixtures; assertions below were verified by hand against the source
 * Markdown (see docs/glm-ocr/real-corpus-syntax-report.md).
 */
class GlmOcrQuestionExtractorTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
    private final GlmOcrQuestionExtractor extractor = new GlmOcrQuestionExtractor();

    static byte[] fixture(String name) throws IOException {
        try (InputStream in = GlmOcrQuestionExtractorTest.class.getResourceAsStream(
                "/glm-ocr/" + name)) {
            assertThat(in).as("fixture " + name).isNotNull();
            return in.readAllBytes();
        }
    }

    GlmOcrPaperDraft qp(String name) throws IOException {
        CanonicalDocument document = parser.parse(fixture(name), "corpus/" + name);
        return extractor.extract(document);
    }

    @Test
    @DisplayName("June 2025 WPH11/01: 20 questions, colon numbering, totals, QWC, MCQ")
    void june2025QuestionPaper() throws IOException {
        GlmOcrPaperDraft june = qp("june-2025-wph11-01-qp.md");

        assertThat(june.questions()).hasSize(20);
        assertThat(june.questions())
                .allSatisfy(q -> assertThat(q.numberingStyle()).isEqualTo("colon"));
        assertThat(june.paperTotal()).isEqualTo(80);
        assertThat(june.sectionTotals()).containsEntry("A", 10).containsEntry("B", 70);
        assertThat(june.questionTotals()).containsEntry("11", 3).containsEntry("13", 3)
                .containsEntry("18", 11).containsEntry("20", 15);
        // June QP genuinely lacks total lines for 6, 12, 15 (audited) — never invented
        assertThat(june.questionTotals()).doesNotContainKeys("6", "12", "15");

        List<QuestionDraft> mcq = june.questions().stream().filter(QuestionDraft::mcq).toList();
        // Q6's option letters are detached from their text (documented defect) —
        // 9 of the first 10 validate as MCQ, Q6 stays a flagged non-MCQ
        assertThat(mcq).hasSize(9);
        assertThat(june.warnings())
                .anySatisfy(w -> assertThat(w).contains("detached option letters"));

        QuestionDraft q18 = june.questions().get(17);
        assertThat(q18.qwc()).isTrue(); // *(c)-style QWC marking in June
        assertThat(q18.marks()).isEqualTo(11);

        QuestionDraft q16 = june.questions().get(15);
        assertThat(q16.parts()).extracting(p -> p.label()).containsExactly("a", "b", "c");
        // June Q16 part marks live only in the MS — QP-side part marks stay null (honest)
        assertThat(q16.parts().get(0).marks()).isNull();
        assertThat(q16.marks()).isEqualTo(7); // from the printed total

        assertThat(june.reviewRequired()).isTrue();
        assertThat(june.questions())
                .allSatisfy(q -> assertThat(q.confidence()).isLessThan(1.0));
    }

    @Test
    @DisplayName("October 2025 WPH11/01: space numbering, parts, roman subparts")
    void october2025QuestionPaper() throws IOException {
        GlmOcrPaperDraft october = qp("october-2025-wph11-01-qp.md");

        // Q15 was OCR-promoted to a Markdown heading ("## 15 A student…") — the
        // extractor reopens it from the heading with a warning; all 20 recovered
        assertThat(october.questions()).hasSize(20);
        assertThat(october.questions())
                .allSatisfy(q -> assertThat(q.numberingStyle()).isEqualTo("space"));
        assertThat(october.paperTotal()).isEqualTo(80);
        assertThat(october.warnings())
                .anySatisfy(w -> assertThat(w).contains("promoted to heading"));

        QuestionDraft q13 = october.questions().stream()
                .filter(q -> q.number() == 13).findFirst().orElseThrow();
        assertThat(q13.parts()).extracting(p -> p.label())
                .contains("a", "b", "b-i", "b-ii");

        // answer prompts ending in '=' are captured, not lost
        QuestionDraft q11 = october.questions().stream()
                .filter(q -> q.number() == 11).findFirst().orElseThrow();
        assertThat(q11.answerPrompts()).anySatisfy(p -> assertThat(p).contains("Acceleration"));
    }

    @Test
    @DisplayName("October 2025 WPH11/01A: variant family, MCQ grid tables")
    void october2025Variant1A() throws IOException {
        GlmOcrPaperDraft variant = qp("october-2025-wph11-01a-qp.md");

        assertThat(variant.paperTotal()).isEqualTo(80);
        // the 1A paper genuinely ends at Q19 (no Q20 in the source) — 19 questions,
        // with *14 opened from its question-level QWC asterisk
        assertThat(variant.questions()).hasSize(19);
        assertThat(variant.questionTotals()).containsEntry("11", 5).containsEntry("19", 12);
        assertThat(variant.questions().stream().filter(QuestionDraft::qwc).count()).isEqualTo(1);

        // the MCQ answer grid is an HTML table; rows A/B/C/D become options
        QuestionDraft mcqGrid = variant.questions().get(0);
        assertThat(mcqGrid.mcq()).isTrue();
        assertThat(mcqGrid.options()).extracting(o -> o.letter()).contains("A", "B", "C", "D");
    }

    @Test
    @DisplayName("expired signed-URL figures are unavailable references preserving URL evidence")
    void figuresAreUnavailableReferences() throws IOException {
        GlmOcrPaperDraft june = qp("june-2025-wph11-01-qp.md");

        assertThat(june.frontMatterFigures()).isNotEmpty(); // cover images before Q1
        assertThat(june.frontMatterFigures())
                .allSatisfy(f -> {
                    assertThat(f.availability()).isEqualTo("unavailable-signed-url");
                    assertThat(f.url()).contains("ufileos.com");
                    assertThat(f.url()).contains("Expires=");
                    assertThat(f.sourceName()).contains("/ocr/crop/");
                });

        int totalFigures = june.questions().stream()
                .mapToInt(q -> q.figures().size()).sum()
                + (int) june.questions().stream().flatMap(q -> q.parts().stream())
                        .mapToLong(p -> p.figures().size()).sum();
        assertThat(totalFigures).isPositive();
        // every figure reference across the paper is marked unavailable — bytes are gone
        List<GlmOcrPaperDraft.FigureRef> all = new java.util.ArrayList<>(june.frontMatterFigures());
        june.questions().forEach(q -> {
            all.addAll(q.figures());
            q.parts().forEach(p -> all.addAll(p.figures()));
        });
        assertThat(all).allSatisfy(f -> assertThat(f.availability())
                .isEqualTo("unavailable-signed-url"));
    }

    @Test
    @DisplayName("determinism: extracting the same paper twice yields identical drafts")
    void extractionIsDeterministic() throws IOException {
        GlmOcrPaperDraft first = qp("october-2025-wph11-01a-qp.md");
        GlmOcrPaperDraft second = qp("october-2025-wph11-01a-qp.md");

        assertThat(second).isEqualTo(first);
        assertThat(second.questions())
                .extracting(GlmOcrPaperDraft.QuestionDraft::questionId)
                .containsExactlyElementsOf(first.questions().stream()
                        .map(GlmOcrPaperDraft.QuestionDraft::questionId).toList());
        assertThat(second.warnings()).isEqualTo(first.warnings());
    }

    @Test
    @DisplayName("QP paper meta stays honestly null when the cover is an expired image")
    void qpMetaHonestWhenCoverIsImage() throws IOException {
        GlmOcrPaperDraft june = qp("june-2025-wph11-01-qp.md");
        // The June QP cover (board, paper ref, date) lives inside the expired
        // cover image; text-derived meta must stay null, never guessed.
        assertThat(june.paper().paperReference()).isNull();
        assertThat(june.paper().logNumber()).isNull();
    }

    @Test
    @DisplayName("same bytes, two parsers: document identity stable across extractors")
    void canonicalIdentityStableAcrossExtractors() throws IOException {
        CanonicalDocument first = parser.parse(fixture("june-2025-wph11-01-qp.md"),
                "corpus/june-2025-wph11-01-qp.md");
        GlmOcrPaperDraft draft = extractor.extract(first);
        assertThat(draft.paper().canonicalDocumentId()).isEqualTo(first.documentId());
        // question ids are derived from the document id — deterministic
        assertThat(draft.questions().get(0).questionId())
                .startsWith("q01-" + first.documentId().substring(0, 8));
    }

    @Test
    @DisplayName("deterministic from synthetic markdown: both numbering styles and marks")
    void syntheticNumberingStyles() throws IOException {
        String markdown = """
                1: A scalar quantity has magnitude only.

                (Total for Question 1 = 1 mark)

                2 A vector quantity has magnitude and direction.

                *(a) State an example of a vector.

                <div align="center">
                (2)
                </div>

                (Total for Question 2 = 3 marks)
                """;
        GlmOcrPaperDraft draft = extractor.extract(parser.parse(
                markdown.getBytes(StandardCharsets.UTF_8), "synthetic.md"));
        assertThat(draft.questions()).hasSize(2);
        assertThat(draft.questions().get(0).numberingStyle()).isEqualTo("colon");
        assertThat(draft.questions().get(1).numberingStyle()).isEqualTo("space");
        assertThat(draft.questions().get(1).qwc()).isTrue();
        assertThat(draft.questions().get(1).parts()).hasSize(1);
        assertThat(draft.questions().get(1).parts().get(0).marks()).isEqualTo(2);
        assertThat(draft.questionTotals()).containsEntry("1", 1).containsEntry("2", 3);
    }

    @Test
    @DisplayName("P-4: a skipped question number merges LOUDLY, with the gap recorded")
    void numberingGapIsLoud() {
        String markdown = """
                1: Stem one.

                3: Stem three.
                """;
        GlmOcrPaperDraft draft = extractor.extract(parser.parse(
                markdown.getBytes(StandardCharsets.UTF_8), "synthetic.md"));
        // fail-safe merge is kept: Q3's line attaches to Q1's body — but loudly
        assertThat(draft.warnings()).containsExactly(
                "question numbering gap: expected Q2, got Q3 (content merges into Q1)");
    }

    @Test
    @DisplayName("P-4: a paper whose first question line is not Q1 warns, drops nothing silently")
    void firstQuestionGapIsLoud() {
        String markdown = """
                2: Orphan stem.
                """;
        GlmOcrPaperDraft draft = extractor.extract(parser.parse(
                markdown.getBytes(StandardCharsets.UTF_8), "synthetic.md"));
        assertThat(draft.questions()).isEmpty();
        assertThat(draft.warnings()).containsExactly(
                "question numbering gap: expected Q1, got Q2 (no current question to merge into)");
    }
}
