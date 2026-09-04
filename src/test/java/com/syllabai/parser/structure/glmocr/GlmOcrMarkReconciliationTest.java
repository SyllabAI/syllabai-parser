package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.glmocr.GlmOcrMarkReconciliation.Finding;
import com.syllabai.parser.structure.glmocr.GlmOcrMarkReconciliation.Reconciliation;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * QP/MS reconciliation across all three real pairs (Session 9, rule D6):
 * agreeing totals reconcile; the audited 1A paper-total conflict (QP 80 vs
 * MS 120) must surface as a review finding, never be merged away.
 */
class GlmOcrMarkReconciliationTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
    private final GlmOcrQuestionExtractor qpExtractor = new GlmOcrQuestionExtractor();
    private final GlmOcrMarkSchemeExtractor msExtractor = new GlmOcrMarkSchemeExtractor();

    private Reconciliation reconcile(String qpFile, String msFile) throws IOException {
        CanonicalDocument qpDoc = parser.parse(
                GlmOcrQuestionExtractorTest.fixture(qpFile), "corpus/" + qpFile);
        CanonicalDocument msDoc = parser.parse(
                GlmOcrQuestionExtractorTest.fixture(msFile), "corpus/" + msFile);
        GlmOcrPaperDraft qp = qpExtractor.extract(qpDoc);
        GlmOcrMarkSchemeDraft ms = msExtractor.extract(msDoc);
        return GlmOcrMarkReconciliation.reconcile(qp, ms);
    }

    private long count(Reconciliation r, String severity) {
        return r.findings().stream().filter(f -> f.severity().equals(severity)).count();
    }

    @Test
    @DisplayName("June 2025 pair: every shared question total agrees; no mismatches")
    void junePairMatches() throws IOException {
        Reconciliation june = reconcile("june-2025-wph11-01-qp.md", "june-2025-wph11-01-ms.md");
        assertThat(count(june, "match")).isGreaterThanOrEqualTo(7);
        assertThat(june.mismatchCount()).isZero();
        assertThat(june.paperTotalConflict()).isFalse();
        assertThat(june.qpPaperTotal()).isEqualTo(80);
        assertThat(june.msPaperTotal()).isEqualTo(80);
        assertThat(june.reviewRequired()).isFalse();
        // QP-only totals: the MS genuinely lacks 17's total; QP lacks 12/15 — honest gaps
        assertThat(count(june, "qp-only")).isGreaterThanOrEqualTo(1);
        assertThat(count(june, "ms-only")).isGreaterThanOrEqualTo(3);
    }

    @Test
    @DisplayName("October 2025 pair: all shared totals agree")
    void octoberPairMatches() throws IOException {
        Reconciliation october = reconcile("october-2025-wph11-01-qp.md",
                "october-2025-wph11-01-ms.md");
        assertThat(count(october, "match")).isGreaterThanOrEqualTo(8);
        assertThat(october.mismatchCount()).isZero();
        assertThat(october.paperTotalConflict()).isFalse();
        assertThat(october.reviewRequired()).isFalse();
    }

    @Test
    @DisplayName("October 2025 1A pair: question totals agree but the paper totals conflict 80 vs 120")
    void variant1APaperTotalConflict() throws IOException {
        Reconciliation variant = reconcile("october-2025-wph11-01a-qp.md",
                "october-2025-wph11-01a-ms.md");
        assertThat(count(variant, "match")).isGreaterThanOrEqualTo(6);
        assertThat(variant.mismatchCount()).isZero();
        // the audited corpus conflict: QP prints 80, MS prints 120 —
        // reported, never merged
        assertThat(variant.paperTotalConflict()).isTrue();
        assertThat(variant.qpPaperTotal()).isEqualTo(80);
        assertThat(variant.msPaperTotal()).isEqualTo(120);
        assertThat(variant.reviewRequired()).isTrue();
    }

    @Test
    @DisplayName("synthetic mismatch produces an explicit review finding")
    void syntheticMismatchIsFlagged() {
        GlmOcrPaperDraft qp = new GlmOcrPaperDraft("1.0", "test", true, null,
                List.of(), Map.of("1", 3), 3, Map.of(), List.of(), List.of());
        GlmOcrMarkSchemeDraft ms = new GlmOcrMarkSchemeDraft("1.0", "test", true, null,
                List.of(), Map.of("1", 4), 4, null, List.of());
        Reconciliation r = GlmOcrMarkReconciliation.reconcile(qp, ms);
        assertThat(r.mismatchCount()).isEqualTo(1);
        Finding finding = r.findings().get(0);
        assertThat(finding.severity()).isEqualTo("mismatch");
        assertThat(finding.qpMarks()).isEqualTo(3);
        assertThat(finding.msMarks()).isEqualTo(4);
        assertThat(r.reviewRequired()).isTrue();
    }
}
