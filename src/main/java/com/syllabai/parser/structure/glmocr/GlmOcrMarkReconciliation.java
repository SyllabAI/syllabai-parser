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
 * totals, and (advisory) presence of MS entries for QP questions. Missing
 * totals on either side are reported as gaps, not treated as zero.</p>
 */
public final class GlmOcrMarkReconciliation {

    /**
     * @param severity "match" | "mismatch" | "qp-only" | "ms-only" | "gap"
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

        /** True when any mismatch or paper-total conflict exists → review required. */
        public boolean reviewRequired() {
            return mismatchCount > 0 || paperTotalConflict;
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
                findings.add(new Finding(number, qpMarks, null, "ms-only"));
            } else if (qpMarks.equals(msMarks)) {
                findings.add(new Finding(number, qpMarks, msMarks, "match"));
            } else {
                findings.add(new Finding(number, qpMarks, msMarks, "mismatch"));
                mismatches++;
            }
        }
        for (Map.Entry<String, Integer> e : msTotals.entrySet()) {
            if (!qpTotals.containsKey(e.getKey())) {
                findings.add(new Finding(e.getKey(), null, e.getValue(), "qp-only"));
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
        return new Reconciliation(List.copyOf(findings), qp.paperTotal(), ms.paperTotal(),
                paperConflict, mismatches);
    }
}
