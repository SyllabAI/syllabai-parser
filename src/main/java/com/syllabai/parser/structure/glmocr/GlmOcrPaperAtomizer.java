package com.syllabai.parser.structure.glmocr;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkSchemeEntry;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PartDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.QuestionDraft;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.Engine;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.ExportPart;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.ExportQuestion;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.MarkSchemeView;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.Source;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.SourceDoc;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.Totals;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.Unmatched;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport.Warnings;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * Java production atomizer (OCR-Q4): QP draft + MS draft &rarr; one
 * self-contained {@link GlmOcrPaperExport} (the {@code paper.json} shape of
 * {@code tools/glmocr/atomize.py}, schema 1.0).
 *
 * <p>Composes the Java production extractors ({@link GlmOcrQuestionExtractor},
 * {@link GlmOcrMarkSchemeExtractor}) and ports the Python pairing logic
 * verbatim: label domains (QP draft labels {@code a}, {@code a-i};
 * MS entry labels {@code 1(a)(i)} / {@code 3(b)} / {@code *14}) are
 * normalized through suffix rules, entries are grouped by question number
 * and indexed by printed suffix, and every part carries its inherited stem
 * context. Gaps are reported, never guessed — a part without a mark-scheme
 * entry exports {@code markScheme: null} plus an atomize warning; MS entries
 * with no QP counterpart land in {@code unmatched.msEntries}.</p>
 *
 * <p>The output is deterministic: identical inputs produce identical exports
 * (content-derived document ids, insertion-ordered collection, numerically
 * sorted totals), so cross-language conformance holds field-for-field
 * ({@code tools/glmocr/conformance.py}, atomize stage).</p>
 */
public final class GlmOcrPaperAtomizer {

    /** One exported question + the MS entry ids it consumed. */
    record QuestionExport(ExportQuestion question, Set<String> consumed) {
    }

    public GlmOcrPaperAtomizer() {
    }

    /** Parses both markdown sources (extraction-time identity) and atomizes. */
    public GlmOcrPaperExport atomize(byte[] qpSource, byte[] msSource,
                                     String qpUri, String msUri) {
        GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
        return atomize(parser.parse(qpSource, qpUri),
                parser.parse(msSource, msUri), qpUri, msUri);
    }

    /** Atomizes pre-parsed canonical documents (conformance path: fixed identity). */
    public GlmOcrPaperExport atomize(CanonicalDocument qpDoc, CanonicalDocument msDoc,
                                     String qpUri, String msUri) {
        GlmOcrPaperDraft qpDraft = new GlmOcrQuestionExtractor().extract(qpDoc);
        GlmOcrMarkSchemeDraft msDraft = new GlmOcrMarkSchemeExtractor().extract(msDoc);

        List<String> warnings = new ArrayList<>();
        Map<Integer, List<MarkSchemeEntry>> grouped =
                groupEntriesByNumber(msDraft.entries());
        Set<String> consumedIds = new LinkedHashSet<>();
        List<ExportQuestion> questions = new ArrayList<>();
        for (QuestionDraft q : qpDraft.questions()) {
            QuestionExport exported =
                    exportQuestion(q, grouped.getOrDefault(q.number(), List.of()), warnings);
            consumedIds.addAll(exported.consumed());
            questions.add(exported.question());
        }

        List<String> unmatched = new ArrayList<>();
        for (MarkSchemeEntry entry : msDraft.entries()) {
            if (!consumedIds.contains(entry.entryId())) {
                unmatched.add(entry.label());
            }
        }
        for (String label : unmatched) {
            warnings.add("mark-scheme entry " + label
                    + " has no question-paper counterpart");
        }

        Map<Integer, Integer> totals = new TreeMap<>();
        for (Map.Entry<String, Integer> e : qpDraft.questionTotals().entrySet()) {
            totals.put(Integer.parseInt(e.getKey().trim()), e.getValue());
        }
        Integer paperTotal = qpDraft.paperTotal();
        Integer sum = totals.isEmpty() ? null
                : totals.values().stream().mapToInt(Integer::intValue).sum();
        if (paperTotal != null && sum != null && sum != paperTotal) {
            warnings.add("sum of question totals (" + sum
                    + ") conflicts with paper total (" + paperTotal + ")");
        }
        Map<String, Integer> orderedTotals = new LinkedHashMap<>();
        for (Map.Entry<Integer, Integer> e : totals.entrySet()) {
            orderedTotals.put(String.valueOf(e.getKey()), e.getValue());
        }

        return new GlmOcrPaperExport(
                GlmOcrPaperExport.EXPORT_SCHEMA_VERSION,
                GlmOcrPaperExport.TOOL_NAME,
                true,
                new Engine(GlmOcrMarkdownParser.ENGINE_NAME,
                        GlmOcrMarkdownParser.ENGINE_VERSION),
                new Source(
                        new SourceDoc(qpUri, qpDoc.documentId(),
                                qpDoc.source() == null ? null : qpDoc.source().checksum()),
                        new SourceDoc(msUri, msDoc.documentId(),
                                msDoc.source() == null ? null : msDoc.source().checksum())),
                qpDraft.paper(),
                questions,
                new Totals(orderedTotals, paperTotal, sum),
                new Unmatched(List.copyOf(unmatched)),
                new Warnings(List.copyOf(qpDraft.warnings()),
                        List.copyOf(msDraft.warnings()), List.copyOf(warnings)));
    }

    // ── label normalization (verbatim port of atomize.py) ────────────────────

    /** "(a)(i)" for label "1(a)(i)"; "" for label "1" or "*14". */
    static String msSuffix(String entryLabel, Integer number) {
        String label = (entryLabel == null ? "" : entryLabel)
                .replaceFirst("^\\*+", "").strip();
        if (number == null) {
            return "";
        }
        String prefix = String.valueOf(number);
        if (!label.startsWith(prefix)) {
            return "";
        }
        return label.substring(prefix.length()).strip();
    }

    /** QP draft label "a-i" &rarr; "(a)(i)"; "a" &rarr; "(a)". */
    static String qpSuffix(String partLabel) {
        StringBuilder out = new StringBuilder();
        for (String token : (partLabel == null ? "" : partLabel).split("-")) {
            if (!token.isEmpty()) {
                out.append('(').append(token).append(')');
            }
        }
        return out.toString();
    }

    /** ["a", "i"] for "a-i"; ["a"] for "a". */
    static List<String> stemChain(String partLabel) {
        List<String> out = new ArrayList<>();
        for (String token : (partLabel == null ? "" : partLabel).split("-")) {
            if (!token.isEmpty()) {
                out.add(token);
            }
        }
        return out;
    }

    /** Verbatim slices joined with blank lines; empty slices dropped. */
    static String assemblePrompt(String stem, String parentText, String ownText) {
        List<String> pieces = new ArrayList<>(3);
        for (String piece : new String[] {stem, parentText, ownText}) {
            if (piece != null && !piece.strip().isEmpty()) {
                pieces.add(piece.strip());
            }
        }
        return String.join("\n\n", pieces);
    }

    /** Python {@code _ms_view}: the marking-relevant fields, null-safe. */
    static MarkSchemeView msView(MarkSchemeEntry entry) {
        if (entry == null) {
            return null;
        }
        return new MarkSchemeView(entry.label(), entry.answerText(),
                entry.markPoints(), entry.guidance(), entry.marks(), entry.confidence());
    }

    /** Entries grouped by question number, draft order preserved. */
    static Map<Integer, List<MarkSchemeEntry>> groupEntriesByNumber(
            List<MarkSchemeEntry> entries) {
        Map<Integer, List<MarkSchemeEntry>> grouped = new LinkedHashMap<>();
        for (MarkSchemeEntry entry : entries) {
            grouped.computeIfAbsent(entry.number(), k -> new ArrayList<>()).add(entry);
        }
        return grouped;
    }

    /** Suffix &rarr; entry; a duplicate suffix keeps the later entry (Python dict). */
    static Map<String, MarkSchemeEntry> indexEntriesBySuffix(
            List<MarkSchemeEntry> entries) {
        Map<String, MarkSchemeEntry> index = new LinkedHashMap<>();
        for (MarkSchemeEntry entry : entries) {
            index.put(msSuffix(entry.label(), entry.number()), entry);
        }
        return index;
    }

    // ── per-question export ──────────────────────────────────────────────────

    private QuestionExport exportQuestion(QuestionDraft q,
                                          List<MarkSchemeEntry> entries,
                                          List<String> warnings) {
        Map<String, MarkSchemeEntry> bySuffix = indexEntriesBySuffix(entries);
        Map<String, String> textOf = new LinkedHashMap<>();
        for (PartDraft p : q.parts()) {
            textOf.put(p.label(), p.text());
        }

        Set<String> consumed = new LinkedHashSet<>();
        List<ExportPart> parts = new ArrayList<>();
        for (PartDraft part : q.parts()) {
            List<String> chain = stemChain(part.label());
            String parentLabel = String.join("-",
                    chain.subList(0, Math.max(chain.size() - 1, 0)));
            String parentText = parentLabel.isEmpty()
                    ? "" : textOf.getOrDefault(parentLabel, "");
            String suffix = qpSuffix(part.label());
            MarkSchemeEntry entry = bySuffix.get(suffix);
            if (entry != null) {
                consumed.add(entry.entryId());
            } else {
                warnings.add("Q" + q.number() + " part " + part.label()
                        + ": no mark-scheme entry for suffix '" + suffix + "'");
            }
            parts.add(new ExportPart(part.partId(), part.label(), suffix, part.text(),
                    assemblePrompt(q.stem(), parentText, part.text()), part.marks(),
                    part.qwc(), part.figures(), part.answerPrompts(), part.confidence(),
                    msView(entry)));
        }

        MarkSchemeView questionLevel = null;
        if (q.parts().isEmpty()) {
            MarkSchemeEntry entry = bySuffix.get("");
            if (entry != null) {
                consumed.add(entry.entryId());
                questionLevel = msView(entry);
            }
        }

        ExportQuestion question = new ExportQuestion(
                q.questionId(), q.number(), q.numberingStyle(), q.section(), q.stem(),
                q.mcq(), q.options(), q.qwc(), q.figures(), q.tableElementIds(),
                q.marks(), q.marksKnown(), q.confidence(), questionLevel,
                List.copyOf(parts));
        return new QuestionExport(question, consumed);
    }
}
