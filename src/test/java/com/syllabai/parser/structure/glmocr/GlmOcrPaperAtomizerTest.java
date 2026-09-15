package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkSchemeEntry;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.ExportPart;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.MarkSchemeView;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Tests for the Java paper.json atomizer ({@link GlmOcrPaperAtomizer}, the
 * mirror of {@code tools/glmocr/atomize.py} + {@code test_atomize.py}).
 *
 * <p>Pure-function tests pin the label-normalization and pairing rules; the
 * integration tests run the REAL June-2025 WPH11 pair end-to-end and pin the
 * observed shape (2026-09-14, engine 1.2.0): MCQ pairing via the bare-number
 * MS entry, structured-part pairing via "(a)(i)" suffixes, honest unmatched
 * reporting, totals honesty, and determinism. Cross-language equality of the
 * full export is enforced separately by {@code tools/glmocr/conformance.py}
 * (atomize stage).</p>
 */
class GlmOcrPaperAtomizerTest {

    private static final Path RES = Path.of("src/test/resources/glm-ocr");
    private static final Path JUNE_QP = RES.resolve("june-2025-wph11-01-qp.md");
    private static final Path JUNE_MS = RES.resolve("june-2025-wph11-01-ms.md");

    // ── label normalization ─────────────────────────────────────────────────

    @Test
    void msSuffixStripsNumberAndStars() {
        assertThat(GlmOcrPaperAtomizer.msSuffix("1(a)(i)", 1)).isEqualTo("(a)(i)");
        assertThat(GlmOcrPaperAtomizer.msSuffix("12(a)", 12)).isEqualTo("(a)");
        assertThat(GlmOcrPaperAtomizer.msSuffix("1", 1)).isEmpty();
        assertThat(GlmOcrPaperAtomizer.msSuffix("*14", 14)).isEmpty();
        assertThat(GlmOcrPaperAtomizer.msSuffix("*3(c)", 3)).isEqualTo("(c)");
        assertThat(GlmOcrPaperAtomizer.msSuffix("1", null)).isEmpty();
    }

    @Test
    void qpSuffixBuildsPrintedForm() {
        assertThat(GlmOcrPaperAtomizer.qpSuffix("a")).isEqualTo("(a)");
        assertThat(GlmOcrPaperAtomizer.qpSuffix("a-i")).isEqualTo("(a)(i)");
        assertThat(GlmOcrPaperAtomizer.qpSuffix("")).isEmpty();
        assertThat(GlmOcrPaperAtomizer.qpSuffix(null)).isEmpty();
    }

    @Test
    void stemChainSplitsDashLabels() {
        assertThat(GlmOcrPaperAtomizer.stemChain("a-i")).containsExactly("a", "i");
        assertThat(GlmOcrPaperAtomizer.stemChain("b")).containsExactly("b");
    }

    // ── prompt assembly ─────────────────────────────────────────────────────

    @Test
    void inheritanceJoinsVerbatimSlices() {
        assertThat(GlmOcrPaperAtomizer.assemblePrompt("stem", "lead-in", "own"))
                .isEqualTo("stem\n\nlead-in\n\nown");
    }

    @Test
    void emptySlicesAreDropped() {
        assertThat(GlmOcrPaperAtomizer.assemblePrompt("", "", "own")).isEqualTo("own");
        assertThat(GlmOcrPaperAtomizer.assemblePrompt("stem", "", "own"))
                .isEqualTo("stem\n\nown");
    }

    // ── grouping / indexing / ms view ───────────────────────────────────────

    @Test
    void entriesGroupedByNumber() {
        List<MarkSchemeEntry> entries = List.of(
                msEntry("1", 1), msEntry("3(a)", 3), msEntry("3(b)", 3));
        Map<Integer, List<MarkSchemeEntry>> grouped =
                GlmOcrPaperAtomizer.groupEntriesByNumber(entries);
        assertThat(grouped).containsOnlyKeys(1, 3);
        assertThat(grouped.get(3)).hasSize(2);
    }

    @Test
    void suffixIndexAndLookup() {
        MarkSchemeEntry a = msEntry("3(a)", 3);
        MarkSchemeEntry ai = msEntry("3(a)(i)", 3);
        Map<String, MarkSchemeEntry> index =
                GlmOcrPaperAtomizer.indexEntriesBySuffix(List.of(a, ai));
        assertThat(index.get("(a)")).isSameAs(a);
        assertThat(index.get("(a)(i)")).isSameAs(ai);
    }

    @Test
    void msViewIsNullSafe() {
        assertThat(GlmOcrPaperAtomizer.msView(null)).isNull();
        MarkSchemeView view = GlmOcrPaperAtomizer.msView(msEntry("1(a)", 1));
        assertThat(view.label()).isEqualTo("1(a)");
        assertThat(view.answerText()).isEqualTo("ans");
        assertThat(view.marks()).isEqualTo(1);
    }

    private static MarkSchemeEntry msEntry(String label, int number) {
        return new MarkSchemeEntry("ms-x-" + label.replace("(", "").replace(")", ""),
                label, number, false, false, null, "ans", List.of(), List.of(),
                1, null, 0.75);
    }

    // ── real-pair integration (June 2025 WPH11, pinned 2026-09-14) ──────────

    private static GlmOcrPaperExport juneExport() throws Exception {
        return new GlmOcrPaperAtomizer().atomize(
                Files.readAllBytes(JUNE_QP), Files.readAllBytes(JUNE_MS),
                JUNE_QP.getFileName().toString(), JUNE_MS.getFileName().toString());
    }

    @Test
    @DisplayName("top-level honesty: draft status, tool identity, 20 questions")
    void topLevelHonesty() throws Exception {
        GlmOcrPaperExport export = juneExport();
        assertThat(export.reviewRequired()).isTrue();
        assertThat(export.tool()).isEqualTo("glmocr-atomize");
        assertThat(export.schemaVersion()).isEqualTo("1.0");
        assertThat(export.questions()).hasSize(20);
        assertThat(export.engine().name()).isEqualTo("glm-ocr-markdown");
    }

    @Test
    @DisplayName("MCQ pairs with the bare-number MS entry")
    void mcqPairsWithBareNumberEntry() throws Exception {
        GlmOcrPaperExport.ExportQuestion q1 = juneExport().questions().stream()
                .filter(q -> q.number() == 1).findFirst().orElseThrow();
        assertThat(q1.mcq()).isTrue();
        assertThat(q1.markScheme()).isNotNull();
        assertThat(q1.markScheme().label()).isEqualTo("1");
        assertThat(q1.markScheme().answerText()).contains("The only correct answer is");
    }

    @Test
    @DisplayName("structured parts carry inherited stem and mark-scheme")
    void structuredPartsCarryInheritedStemAndMarkScheme() throws Exception {
        GlmOcrPaperExport.ExportQuestion q12 = juneExport().questions().stream()
                .filter(q -> q.number() == 12).findFirst().orElseThrow();
        assertThat(q12.parts()).isNotEmpty();
        for (ExportPart part : q12.parts()) {
            assertThat(part.markScheme()).isNotNull();
            assertThat(part.renderedPrompt()).contains(part.text());
            if (q12.stem() != null && !q12.stem().isEmpty()) {
                assertThat(part.renderedPrompt()).startsWith(q12.stem().strip());
            }
        }
    }

    @Test
    @DisplayName("unmatched parts are reported, not guessed")
    void unmatchedPartsAreReportedNotGuessed() throws Exception {
        List<String> warns = juneExport().warnings().atomize();
        assertThat(warns).anySatisfy(w -> assertThat(w).contains("no mark-scheme entry"));
        for (String w : warns) {
            if (w.contains("no mark-scheme entry")) {
                assertThat(w).contains("no mark-scheme entry for suffix");
            }
        }
    }

    @Test
    @DisplayName("totals block: sum 70 vs paper total 80, reported honestly")
    void totalsBlock() throws Exception {
        GlmOcrPaperExport.Totals totals = juneExport().totals();
        assertThat(totals.sumOfQuestionTotals()).isEqualTo(70);
        assertThat(totals.paperTotal()).isEqualTo(80);
        assertThat(totals.questionTotals()).containsEntry("1", 1).containsKey("20");
    }

    @Test
    @DisplayName("determinism: identical inputs produce identical exports")
    void determinism(@TempDir Path tmp) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        byte[] qp = Files.readAllBytes(JUNE_QP);
        byte[] ms = Files.readAllBytes(JUNE_MS);
        String one = mapper.writeValueAsString(
                new GlmOcrPaperAtomizer().atomize(qp, ms,
                        JUNE_QP.getFileName().toString(), JUNE_MS.getFileName().toString()));
        String two = mapper.writeValueAsString(
                new GlmOcrPaperAtomizer().atomize(qp, ms,
                        JUNE_QP.getFileName().toString(), JUNE_MS.getFileName().toString()));
        assertThat(two).isEqualTo(one);
    }
}
