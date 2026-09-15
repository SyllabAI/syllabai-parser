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
    @DisplayName("June 2025 pair: every shared question total agrees; gaps force review")
    void junePairMatches() throws IOException {
        Reconciliation june = reconcile("june-2025-wph11-01-qp.md", "june-2025-wph11-01-ms.md");
        assertThat(count(june, "match")).isGreaterThanOrEqualTo(7);
        assertThat(june.mismatchCount()).isZero();
        assertThat(june.paperTotalConflict()).isFalse();
        assertThat(june.qpPaperTotal()).isEqualTo(80);
        assertThat(june.msPaperTotal()).isEqualTo(80);
        // severity labels are named for where the value EXISTS (the audit found
        // them inverted): "qp-only" = MS genuinely lacks 17's total; "ms-only" =
        // QP lacks 12/15 — honest one-sided evidence
        assertThat(count(june, "qp-only")).isGreaterThanOrEqualTo(3);
        assertThat(count(june, "ms-only")).isGreaterThanOrEqualTo(1);
        // one-sided coverage gaps force review (audit: 4+ such findings while
        // reviewRequired stayed false)
        assertThat(june.reviewRequired()).isTrue();
    }

    @Test
    @DisplayName("severity always agrees with which side carries the value")
    void severityLabelsAreSelfConsistent() throws IOException {
        for (Reconciliation r : List.of(
                reconcile("june-2025-wph11-01-qp.md", "june-2025-wph11-01-ms.md"),
                reconcile("october-2025-wph11-01-qp.md", "october-2025-wph11-01-ms.md"),
                reconcile("october-2025-wph11-01a-qp.md", "october-2025-wph11-01a-ms.md"))) {
            for (Finding f : r.findings()) {
                switch (f.severity()) {
                    case "qp-only" -> {
                        assertThat(f.qpMarks()).as("qp-only needs a QP value: %s", f).isNotNull();
                        assertThat(f.msMarks()).as("qp-only must lack an MS value: %s", f).isNull();
                    }
                    case "ms-only" -> {
                        assertThat(f.msMarks()).as("ms-only needs an MS value: %s", f).isNotNull();
                        assertThat(f.qpMarks()).as("ms-only must lack a QP value: %s", f).isNull();
                    }
                    case "gap" -> {
                        assertThat(f.qpMarks()).as("gap carries no QP value: %s", f).isNull();
                        assertThat(f.msMarks()).as("gap carries no MS value: %s", f).isNull();
                    }
                    case "match", "mismatch" -> {
                        assertThat(f.qpMarks()).as("%s needs both values: %s", f.severity(), f).isNotNull();
                        assertThat(f.msMarks()).as("%s needs both values: %s", f.severity(), f).isNotNull();
                    }
                    default -> throw new AssertionError("unknown severity: " + f.severity());
                }
            }
        }
    }

    @Test
    @DisplayName("October 2025 pair: all shared totals agree")
    void octoberPairMatches() throws IOException {
        Reconciliation october = reconcile("october-2025-wph11-01-qp.md",
                "october-2025-wph11-01-ms.md");
        assertThat(count(october, "match")).isGreaterThanOrEqualTo(8);
        assertThat(october.mismatchCount()).isZero();
        assertThat(october.paperTotalConflict()).isFalse();
        // one-sided totals exist on this pair too → review (fail-closed)
        assertThat(october.reviewRequired()).isTrue();
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
                List.of(), Map.of("1", 4), 4, null, null, List.of());
        Reconciliation r = GlmOcrMarkReconciliation.reconcile(qp, ms);
        assertThat(r.mismatchCount()).isEqualTo(1);
        Finding finding = r.findings().get(0);
        assertThat(finding.severity()).isEqualTo("mismatch");
        assertThat(finding.qpMarks()).isEqualTo(3);
        assertThat(finding.msMarks()).isEqualTo(4);
        assertThat(r.reviewRequired()).isTrue();
    }

    // ── printed-identity disagreement (T-C04 r2 hardening, directive 2026-09-13) ──

    private static GlmOcrPaperDraft.PaperMeta meta(String reference, String session) {
        return new GlmOcrPaperDraft.PaperMeta("Edexcel", "IGCSE", "Chemistry",
                reference, null, null, session, null, null, "test-doc");
    }

    private static GlmOcrPaperDraft qpWith(GlmOcrPaperDraft.PaperMeta paper) {
        return new GlmOcrPaperDraft("1.0", "test", false, paper,
                List.of(), Map.of("1", 3), 3, Map.of(), List.of(), List.of());
    }

    private static GlmOcrMarkSchemeDraft msWith(GlmOcrPaperDraft.PaperMeta paper) {
        return new GlmOcrMarkSchemeDraft("1.0", "test", false, paper,
                List.of(), Map.of("1", 3), 3, null, null, List.of());
    }

    @Test
    @DisplayName("QP vs MS session disagreement is an identity-mismatch finding, never merged")
    void sessionDisagreementIsFlagged() {
        // the 2016-Jan duplicate shape: QP prints January 2015 while the paired
        // MS cover names January 2016 — the disagreement itself must surface
        Reconciliation r = GlmOcrMarkReconciliation.reconcile(
                qpWith(meta("4CH0/1C", "January 2015")),
                msWith(meta("4CH0/1C", "January 2016")));

        assertThat(r.findings()).anySatisfy(f -> {
            assertThat(f.severity()).isEqualTo("identity-mismatch");
            assertThat(f.questionNumber()).isEqualTo("paper");
        });
        assertThat(r.mismatchCount()).isEqualTo(1);
        assertThat(r.reviewRequired()).isTrue();
        // QP-first: the reconciliation never rewrites either side
        assertThat(qpWith(meta("4CH0/1C", "January 2015")).paper().session())
                .isEqualTo("January 2015");
    }

    @Test
    @DisplayName("QP vs MS paper-reference disagreement is flagged; one-sided identity is not")
    void referenceDisagreementIsFlaggedOneSidedIsNot() {
        Reconciliation referenceConflict = GlmOcrMarkReconciliation.reconcile(
                qpWith(meta("4CH0/1C", "January 2016")),
                msWith(meta("4CH1/1C", "January 2016")));
        assertThat(referenceConflict.mismatchCount()).isEqualTo(1);
        assertThat(referenceConflict.reviewRequired()).isTrue();

        // one-sided identity (e.g. expired image QP cover) stays out of scope:
        // the core session gate handles that shape fail-closed
        Reconciliation oneSided = GlmOcrMarkReconciliation.reconcile(
                qpWith(meta(null, null)),
                msWith(meta("4CH0/1C", "January 2016")));
        assertThat(oneSided.mismatchCount()).isZero();
        assertThat(oneSided.reviewRequired()).isFalse();
    }

    @Test
    @DisplayName("agreeing printed identity produces no identity findings")
    void agreeingIdentityStaysClean() {
        Reconciliation r = GlmOcrMarkReconciliation.reconcile(
                qpWith(meta("4CH0/1C", "June 2011")),
                msWith(meta("4ch0/1c", "June 2011"))); // case-insensitive print

        assertThat(r.findings()).noneSatisfy(f ->
                assertThat(f.severity()).isEqualTo("identity-mismatch"));
        assertThat(r.mismatchCount()).isZero();
        assertThat(r.reviewRequired()).isFalse();
    }
}
