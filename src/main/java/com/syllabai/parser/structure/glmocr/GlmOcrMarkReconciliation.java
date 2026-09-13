package com.syllabai.parser.structure.glmocr;

import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * QP/MS mark reconciliation (Session 9, design rule D6): compares a
 * question-paper draft against its mark-scheme draft and reports findings.
 * Mismatches produce review findings — never a silent merge or "fix".
 *
 * <p>Compares: per-question totals (QP printed totals vs MS totals), paper
 * totals, printed-identity disagreement (session / paper reference printed on
 * BOTH covers — a disagreement is a finding, never silently resolved by picking
 * one side), and (advisory) presence of MS entries for QP questions. Missing
 * totals on either side are reported as gaps, not treated as zero.</p>
 */
public final class GlmOcrMarkReconciliation {

    /**
     * @param questionNumber question the finding is about ("paper" for
     *                       identity-mismatch findings)
     * @param qpMarks        QP-side total (null when the QP side has no value)
     * @param msMarks        MS-side total (null when the MS side has no value)
     * @param severity "match" | "mismatch" | "qp-only" | "ms-only" | "gap"
     *                 | "identity-mismatch", named for where the value EXISTS:
     *                 "qp-only" = the total is present on the QP and missing
     *                 from the MS (qpMarks != null, msMarks == null);
     *                 "ms-only" = the mirror case; "gap" = neither side yields
     *                 a value for a question the QP opened;
     *                 "identity-mismatch" = printed-identity disagreement
     *                 between the covers (T-C04 r2).
     */
    public record Finding(String questionNumber, Integer qpMarks, Integer msMarks,
                          String severity) {
    }

    /**
     * @param findings            per-question comparison in question order
     * @param qpPaperTotal        printed QP paper total (null unknown)
     * @param msPaperTotal        printed MS paper total (null unknown)
     * @param paperTotalConflict  QP and MS paper totals both known and unequal
     * @param mismatchCount       number of mismatch-severity findings
     */
    public record Reconciliation(
            List<Finding> findings,
            Integer qpPaperTotal,
            Integer msPaperTotal,
            boolean paperTotalConflict,
            int mismatchCount) {

        /** True when anything needs human eyes: a totals mismatch, a paper-total
         * conflict, or any one-sided/missing coverage finding ("qp-only",
         * "ms-only", "gap") — one-sided evidence is a coverage gap the operator
         * must see, never silently OK (audit: June carried 4+ one-sided
         * findings while reviewRequired stayed false). */
        public boolean reviewRequired() {
            return mismatchCount > 0 || paperTotalConflict
                    || findings.stream().anyMatch(f -> !f.severity().equals("match"));
        }
    }

    private GlmOcrMarkReconciliation() {
    }

    public static Reconciliation reconcile(GlmOcrPaperDraft qp, GlmOcrMarkSchemeDraft ms) {
        Map<String, Integer> qpTotals = new TreeMap<>(qp.questionTotals());
        Map<String, Integer> msTotals = new TreeMap<>(ms.questionTotals());

        // MS entries by question number (a question may span several entries)
        Map<String, Boolean> msEntryNumbers = new LinkedHashMap<>();
        for (GlmOcrMarkSchemeDraft.MarkSchemeEntry entry : ms.entries()) {
            msEntryNumbers.put(Integer.toString(entry.number()), true);
        }
        Map<String, Boolean> qpQuestionNumbers = new LinkedHashMap<>();
        for (GlmOcrPaperDraft.QuestionDraft question : qp.questions()) {
            qpQuestionNumbers.put(Integer.toString(question.number()), true);
        }

        List<Finding> findings = new ArrayList<>();
        int mismatches = 0;
        for (Map.Entry<String, Integer> e : qpTotals.entrySet()) {
            String number = e.getKey();
            Integer qpMarks = e.getValue();
            Integer msMarks = msTotals.get(number);
            if (msMarks == null) {
                // the value exists only on the QP side → qp-only
                findings.add(new Finding(number, qpMarks, null, "qp-only"));
            } else if (qpMarks.equals(msMarks)) {
                findings.add(new Finding(number, qpMarks, msMarks, "match"));
            } else {
                findings.add(new Finding(number, qpMarks, msMarks, "mismatch"));
                mismatches++;
            }
        }
        for (Map.Entry<String, Integer> e : msTotals.entrySet()) {
            if (!qpTotals.containsKey(e.getKey())) {
                // the value exists only on the MS side → ms-only
                findings.add(new Finding(e.getKey(), null, e.getValue(), "ms-only"));
            }
        }
        // advisory: MS has entries for a question the QP never opened (and vice versa)
        for (String number : qpQuestionNumbers.keySet()) {
            if (!msEntryNumbers.containsKey(number) && !qpTotals.containsKey(number)) {
                // QP question with no printed total and no MS entry — extraction gap
                findings.add(new Finding(number, null, null, "gap"));
            }
        }

        boolean paperConflict = qp.paperTotal() != null && ms.paperTotal() != null
                && !qp.paperTotal().equals(ms.paperTotal());

        // Printed-identity disagreement (T-C04 r2 hardening): the QP cover is the
        // authoritative identity source, but when BOTH covers print a session
        // (or a paper reference) and they disagree, the pair is flagged for
        // review — the disagreement itself is evidence, never silently merged.
        // One-sided identity stays out of scope here: a QP with no printed
        // session is rejected fail-closed by the core identity gate, and an MS
        // cover cannot override the QP by itself (QP-first mapping).
        int identityMismatches = 0;
        GlmOcrPaperDraft.PaperMeta qpMeta = qp.paper();
        GlmOcrPaperDraft.PaperMeta msMeta = ms.paper();
        if (qpMeta != null && msMeta != null) {
            if (qpMeta.session() != null && msMeta.session() != null
                    && !qpMeta.session().equalsIgnoreCase(msMeta.session())) {
                findings.add(new Finding("paper", null, null, "identity-mismatch"));
                identityMismatches++;
            }
            if (qpMeta.paperReference() != null && msMeta.paperReference() != null
                    && !qpMeta.paperReference().equalsIgnoreCase(msMeta.paperReference())) {
                findings.add(new Finding("paper", null, null, "identity-mismatch"));
                identityMismatches++;
            }
        }
        return new Reconciliation(List.copyOf(findings), qp.paperTotal(), ms.paperTotal(),
                paperConflict, mismatches + identityMismatches);
    }
}
