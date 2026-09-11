package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.GuidanceLine;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkPoint;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkSchemeEntry;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import java.io.IOException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Real-corpus GLM-OCR mark-scheme extraction (Session 9): table-first
 * entries, MarkPoints with marking vocabulary, both total placements, IC
 * tables in both shapes, QWC asterisk labels, and honest warnings. All
 * assertions hand-verified against the source Markdown.
 */
class GlmOcrMarkSchemeExtractorTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
    private final GlmOcrMarkSchemeExtractor extractor = new GlmOcrMarkSchemeExtractor();

    GlmOcrMarkSchemeDraft ms(String name) throws IOException {
        CanonicalDocument document = parser.parse(
                GlmOcrQuestionExtractorTest.fixture(name), "corpus/" + name);
        return extractor.extract(document);
    }

    MarkSchemeEntry entry(GlmOcrMarkSchemeDraft draft, String label) {
        return draft.entries().stream()
                .filter(e -> e.label().equals(label))
                .findFirst().orElseThrow(() -> new AssertionError("no entry " + label));
    }

    @Test
    @DisplayName("June 2025 MS: MCQ options, mark points, guidance kinds, combined total line")
    void june2025MarkScheme() throws IOException {
        GlmOcrMarkSchemeDraft june = ms("june-2025-wph11-01-ms.md");

        assertThat(june.paper().board()).isEqualTo("Edexcel");
        assertThat(june.paper().qualification()).isEqualTo("IAL");
        assertThat(june.paper().logNumber()).isEqualTo("P78753A");
        assertThat(june.paper().publicationCode()).isEqualTo("WPH11_01_2506_MS");
        assertThat(june.paper().session()).isEqualTo("Summer 2025");
        assertThat(june.paper().canonicalDocumentId()).isNotBlank();
        assertThat(june.paperTotal()).isEqualTo(80); // from the combined line

        assertThat(june.entries()).hasSize(31);
        assertThat(june.questionTotals()).containsEntry("11", 3)
                .containsEntry("12", 5)
                .containsEntry("20", 15) // glued "(Total for Question 20 =15 marks) TOTAL FOR PAPER=80 MARKS"
                .doesNotContainKeys("17"); // genuinely absent in the source (audited)

        // MCQ answers survive as structured options
        assertThat(entry(june, "1").mcq()).isTrue();
        assertThat(entry(june, "1").correctOption()).isEqualTo("D");
        assertThat(entry(june, "10").correctOption()).isEqualTo("A");

        // mark points split on "(N)" markers, dependent/ecf vocabulary preserved
        MarkSchemeEntry q13 = entry(june, "13");
        assertThat(q13.markPoints()).hasSize(3);
        assertThat(q13.markPoints().get(0).marks()).isEqualTo(1);
        assertThat(q13.markPoints().get(1).marks()).isEqualTo(1);

        // guidance classification: allow / ignore / example-calculation
        MarkSchemeEntry q12a = entry(june, "12(a)");
        assertThat(q12a.guidance()).extracting(GuidanceLine::kind).contains("allow");
        assertThat(q13.guidance()).extracting(GuidanceLine::kind)
                .contains("example-calculation");

        // QWC question 18 has an IC table in the June long-header shape
        assertThat(june.icTable()).isNotNull();
        assertThat(june.icTable().location()).isEqualTo("standalone");
        assertThat(june.icTable().rows()).hasSize(5);
        assertThat(june.icTable().rows().get(0)).containsExactly("6", "4", "", "2");

        assertThat(june.reviewRequired()).isTrue();
        // the June MS's single centered image (an expired-signature OCR
        // watermark crop) is now SURFACED at draft level instead of being
        // silently dropped — hardening round 2, corpus-true regression
        assertThat(june.figureRefs()).hasSize(1);
        assertThat(june.figureRefs().get(0).availability())
                .isEqualTo("unavailable-signed-url");
        assertThat(june.warnings()).containsExactly(
                "1 figure reference(s) in the mark-scheme markdown are not "
                        + "represented in the structured entries; preserved in figureRefs");
    }

    @Test
    @DisplayName("October 2025 MS: in-table totals, rowspan-deferred marks, Any-two-from, ecf")
    void october2025MarkScheme() throws IOException {
        GlmOcrMarkSchemeDraft october = ms("october-2025-wph11-01-ms.md");

        assertThat(october.entries()).hasSize(33);
        // in-table total rows (October placement) — includes "Total for question12" glued form
        assertThat(october.questionTotals()).containsEntry("11", 2)
                .containsEntry("12", 4)
                .containsEntry("17", 11)
                .containsEntry("20", 10);

        // Q11: marks deferred to a rowspan continuation row
        MarkSchemeEntry q11 = entry(october, "11");
        assertThat(q11.marks()).isEqualTo(2);
        assertThat(q11.marksCellSource()).isEqualTo("rowspan continuation row");
        assertThat(q11.guidance()).extracting(GuidanceLine::kind)
                .contains("example-calculation");

        // Q13(a): answer cell without (N) markers stays whole — no invented points
        MarkSchemeEntry q13a = entry(october, "13(a)");
        assertThat(q13a.markPoints()).isEmpty();
        assertThat(q13a.marks()).isEqualTo(2);
        assertThat(q13a.answerText()).contains("human reaction time");

        // Q14(a): dependent-on-MP + Or alternatives
        MarkSchemeEntry q14a = entry(october, "14(a)");
        MarkPoint mp1 = q14a.markPoints().get(0);
        assertThat(mp1.dependentOn()).isEmpty();
        assertThat(q14a.markPoints()).hasSize(2);
        MarkPoint mp2 = q14a.markPoints().get(1);
        assertThat(mp2.dependentOn()).contains("MP1");
        assertThat(mp2.alternatives()).isNotEmpty();
        assertThat(mp2.alternatives().get(0)).contains("closed system");

        // Q17(b)(ii): "Any two from" group flag
        MarkSchemeEntry q17bii = entry(october, "17(b)(ii)");
        assertThat(q17bii.markPoints()).isNotEmpty();
        assertThat(q17bii.markPoints().stream().anyMatch(MarkPoint::anyTwoFrom)).isTrue();
        assertThat(q17bii.guidance()).extracting(GuidanceLine::kind).contains("ignore");

        // Q19(b)(ii): ecf marker
        MarkSchemeEntry q19bii = entry(october, "19(b)(ii)");
        assertThat(q19bii.markPoints().stream().anyMatch(MarkPoint::ecf)).isTrue();

        // standalone IC table in the October <th>-header shape
        assertThat(october.icTable()).isNotNull();
        assertThat(october.icTable().location()).isEqualTo("standalone");
        assertThat(october.icTable().rows().get(1)).containsExactly("5", "3", "2", "5");

        // rubric ambiguity warning is honest evidence, not a failure
        assertThat(october.warnings())
                .anySatisfy(w -> assertThat(w).contains("bare integer cell"));
    }

    @Test
    @DisplayName("October 2025 1A MS: embedded IC table, *14 QWC label, paper-total conflict source")
    void october2025Variant1AMarkScheme() throws IOException {
        GlmOcrMarkSchemeDraft variant = ms("october-2025-wph11-01a-ms.md");

        assertThat(variant.entries()).hasSize(33);
        assertThat(variant.paper().paperReference()).isEqualTo("WPH11/01A");
        assertThat(variant.paper().logNumber()).isEqualTo("P87440A");
        // the 1A MS prints 120 while its own question totals sum to 80 —
        // a genuine corpus conflict; the draft records it, never resolves it
        assertThat(variant.paperTotal()).isEqualTo(120);
        assertThat(variant.questionTotals()).containsEntry("19", 12).containsEntry("11", 5);

        // *14 QWC question: asterisk label → qwc flag, embedded IC table
        MarkSchemeEntry q14 = entry(variant, "*14");
        assertThat(q14.qwc()).isTrue();
        assertThat(variant.icTable()).isNotNull();
        assertThat(variant.icTable().location()).isEqualTo("embedded");
        assertThat(variant.icTable().rows()).hasSize(7);

        // guidance "MP2 dependent on MP1" is classified as dependent
        MarkSchemeEntry q16b = entry(variant, "16(b)");
        assertThat(q16b.guidance()).extracting(GuidanceLine::kind).contains("dependent");
        assertThat(q16b.markPoints()).isNotEmpty();
    }

    @Test
    @DisplayName("determinism: extracting the same mark scheme twice yields identical drafts")
    void extractionIsDeterministic() throws IOException {
        GlmOcrMarkSchemeDraft first = ms("october-2025-wph11-01a-ms.md");
        GlmOcrMarkSchemeDraft second = ms("october-2025-wph11-01a-ms.md");
        assertThat(second).isEqualTo(first);
        assertThat(second.entries())
                .extracting(MarkSchemeEntry::entryId)
                .containsExactlyElementsOf(first.entries().stream()
                        .map(MarkSchemeEntry::entryId).toList());
    }

    @Test
    @DisplayName("markPoint splitting: glued markers, non-digit parens, empty segments")
    void markPointSplitting() {
        // glued "plank(1)" markers and non-marker parens
        java.util.List<MarkPoint> glued = GlmOcrMarkSchemeExtractor.markPoints(
                "Triangle of correct shape drawn, with at least two sides labelled(1)"
                        + "Vector triangle drawn with arrows(1)Magnitude of resultant"
                        + " force=380N(allow370Nto390N)(1)");
        assertThat(glued).hasSize(3);
        assertThat(glued.get(0).marks()).isEqualTo(1);
        assertThat(glued.get(1).text()).isEqualTo("Vector triangle drawn with arrows");
        assertThat(glued.get(2).text()).contains("380N");

        // (0.5-0.4) is not a marker — no false split
        java.util.List<MarkPoint> decimal = GlmOcrMarkSchemeExtractor.markPoints(
                "Use of $\\\\frac{(0.5-0.4)\\\\times9.81}{0.5+0.4}$");
        assertThat(decimal).isEmpty(); // no markers → whole cell, never guessed

        // standalone "(1)" separators split Any-two-from bullets into points; the
        // group header carries the anyTwoFrom flag; the marks cell stays authority
        java.util.List<MarkPoint> separators = GlmOcrMarkSchemeExtractor.markPoints(
                "Any two from\n(1)\n• The bubble may not be spherical\n(1)");
        assertThat(separators).hasSize(2);
        assertThat(separators.get(0).anyTwoFrom()).isTrue();
    }

    @Test
    @DisplayName("MS figure blocks: surfaced as draft-level figureRefs + visibility warning")
    void markSchemeFiguresAreSurfaced() throws IOException {
        GlmOcrMarkSchemeDraft draft = ms("figure-ms-ms.md");

        // header figure (before the table) AND worked-answer figure (after it)
        assertThat(draft.figureRefs()).hasSize(2);
        GlmOcrPaperDraft.FigureRef header = draft.figureRefs().get(0);
        assertThat(header.url()).isEqualTo("assets/crop_ms_header.png");
        assertThat(header.elementId()).isNotBlank();
        assertThat(header.availability()).isEqualTo("unavailable-signed-url");
        GlmOcrPaperDraft.FigureRef graph = draft.figureRefs().get(1);
        assertThat(graph.url()).isEqualTo("assets/crop_ms_graph.png");

        // the structured entries still carry the marks; figures stay unassigned
        assertThat(entry(draft, "1").marks()).isEqualTo(2);
        assertThat(draft.warnings()).anyMatch(w -> w.equals(
                "2 figure reference(s) in the mark-scheme markdown are not "
                        + "represented in the structured entries; preserved in figureRefs"));
    }

    @Test
    @DisplayName("figure-free MS: figureRefs stays null and is omitted from the JSON bytes")
    void figureFreeMarkSchemeStaysByteIdentical() throws IOException {
        GlmOcrMarkSchemeDraft draft = ms("pathological-ms.md");

        assertThat(draft.figureRefs()).isNull();
        GlmOcrMarkSchemeDraft reparsed = CanonicalJson.mapper().readValue(
                CanonicalJson.mapper().writeValueAsString(draft), GlmOcrMarkSchemeDraft.class);
        assertThat(reparsed.figureRefs()).isNull();
        assertThat(CanonicalJson.mapper().writeValueAsString(draft))
                .doesNotContain("figureRefs");
    }
}
