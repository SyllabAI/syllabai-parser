package com.syllabai.parser.engine.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.TableElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Bounded-block hardening (T-C03 parser patch, 2026-09). An unterminated
 * block opener must never swallow the rest of the document: the scan stops
 * at structural boundaries, the salvage path keeps every complete row, the
 * swallowed span re-parses as normal flow, and the pathology is counted in
 * provenance. Clean input must be byte-identical to the pre-hardening
 * engine — including closed-but-empty tables and the absence of the new
 * provenance counters.
 */
class GlmOcrMarkdownParserBoundednessTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();

    private CanonicalDocument parse(String markdown) {
        return parser.parseWithFixedIdentity(
                markdown.getBytes(StandardCharsets.UTF_8), "corpus/sample.md",
                java.time.Instant.EPOCH);
    }

    private static List<String> paragraphs(CanonicalDocument doc) {
        return doc.textBlocks().stream()
                .filter(b -> b.role() == TextRole.PARAGRAPH)
                .map(TextBlockElement::text)
                .toList();
    }

    @Test
    @DisplayName("unterminated <table>: complete rows salvaged, partial rows re-parsed")
    void unterminatedTableSalvagedAtStructuralLine() {
        CanonicalDocument doc = parse("""
                1 First question stem
                <table border="1"><tr><td>A</td><td>B</td></tr>
                <tr><td>C</td><td>D</td></tr>
                partial row no closer

                2 Second question stem
                """);
        assertThat(doc.tables()).hasSize(1);
        TableElement table = doc.tables().get(0);
        assertThat(table.rows()).containsExactly(List.of("A", "B"), List.of("C", "D"));
        // the partial row and the next question survive as flow
        assertThat(paragraphs(doc)).contains("partial row no closer", "2 Second question stem");
        assertThat(doc.provenance().extractionParams().get("unterminatedTableBlocks"))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("orphan $$ fence: opener dropped, swallowed span re-parsed, counter recorded")
    void orphanMathFenceDropped() {
        CanonicalDocument doc = parse("""
                1 First question stem
                $$
                \\mathrm{H_{2}O}
                (a) structural line inside the orphan span
                2 \\mathrm{NaCl} + more

                2 Second question stem
                $$
                x = y
                $$
                """);
        // the lines the old scanner would have eaten as one bogus equation
        assertThat(paragraphs(doc)).contains(
                "\\mathrm{H_{2}O}",
                "(a) structural line inside the orphan span",
                "2 \\mathrm{NaCl} + more",
                "2 Second question stem");
        // the genuinely closed equation still parses
        assertThat(doc.equations()).hasSize(1);
        assertThat(doc.equations().get(0).latex()).isEqualTo("x = y");
        assertThat(doc.provenance().extractionParams().get("orphanMathFences")).isEqualTo(1);
    }

    @Test
    @DisplayName("unclosed <div align=center>: opener dropped at nested center-open, span re-parsed")
    void unclosedCenterDivDropped() {
        CanonicalDocument doc = parse("""
                <div align="center">
                (i) orphan label
                <div align="center">
                1 First question stem
                """);
        assertThat(paragraphs(doc)).contains("(i) orphan label", "1 First question stem");
        assertThat(doc.textBlocks().stream().filter(b -> b.role() == TextRole.HEADING)).isEmpty();
        assertThat(doc.provenance().extractionParams().get("unclosedCenterDivs")).isEqualTo(2);
        // no HTML leaks into the text flow
        assertThat(paragraphs(doc)).noneMatch(t -> t.contains("</div>") || t.contains("<div"));
    }

    @Test
    @DisplayName("closed div containing a heading is legitimate corpus shape: unchanged")
    void closedDivContainingHeadingUnchanged() {
        CanonicalDocument doc = parse("""
                <div align="center">
                # Mark Scheme (Results)
                </div>
                Summer 2018
                """);
        assertThat(doc.textBlocks().stream().filter(b -> b.role() == TextRole.HEADING)
                .map(TextBlockElement::text)).containsExactly("Mark Scheme (Results)");
        assertThat(paragraphs(doc)).containsExactly("Summer 2018");
        assertThat(doc.provenance().extractionParams()).doesNotContainKey("unclosedCenterDivs");
    }

    @Test
    @DisplayName("stray </div> left by a dropped orphan opener is skipped, not leaked")
    void strayCloserSkipped() {
        CanonicalDocument doc = parse("""
                <div align="center">
                (i) label one
                <div align="center">
                (ii) label two
                </div>
                </div>
                1 First question stem
                """);
        assertThat(paragraphs(doc)).containsExactly(
                "(i) label one", "(ii) label two", "1 First question stem");
        assertThat(doc.provenance().extractionParams().get("unclosedCenterDivs")).isEqualTo(1);
    }

    @Test
    @DisplayName("clean input: no hardening counters, element stream unchanged")
    void cleanInputHasNoCountersAndIdenticalElements() {
        CanonicalDocument doc = parse("""
                # Title

                1 First question stem
                <table><tr><td>A</td><td>B</td></tr></table>

                $$x = y$$

                <div align="center">
                (i)
                </div>
                """);
        var params = doc.provenance().extractionParams();
        assertThat(params).doesNotContainKeys(
                "unterminatedTableBlocks", "orphanMathFences", "unclosedCenterDivs");
        assertThat(doc.tables()).hasSize(1);
        assertThat(doc.equations()).hasSize(1);
        // ids are positional over the whole stream, exactly as before hardening
        assertThat(doc.tables().get(0).elementId()).isEqualTo("e000002");
        assertThat(doc.equations().get(0).elementId()).isEqualTo("e000003");
        assertThat(doc.textBlocks().stream().filter(b -> b.role() == TextRole.PARAGRAPH)
                .map(b -> b.elementId() + "=" + b.text()))
                .containsExactly("e000001=1 First question stem", "e000004=(i)");
    }

    @Test
    @DisplayName("closed-but-empty table still emits an element (rows empty, text null)")
    void closedEmptyTableUnchanged() {
        CanonicalDocument doc = parse("""
                1 First question stem
                <table></table>
                (a) part text
                """);
        assertThat(doc.tables()).hasSize(1);
        assertThat(doc.tables().get(0).rows()).isEmpty();
        assertThat(doc.tables().get(0).elementId()).isEqualTo("e000001");
    }

    @Test
    @DisplayName("unterminated table at EOF: last complete row kept, opener counter set")
    void unterminatedTableAtEof() {
        CanonicalDocument doc = parse("1 First question stem\n"
                + "<table><tr><td>A</td><td>B</td></tr>\n<tr><td>C</td>");
        assertThat(doc.tables()).hasSize(1);
        assertThat(doc.tables().get(0).rows()).containsExactly(List.of("A", "B"));
        assertThat(paragraphs(doc)).contains("1 First question stem");
        assertThat(doc.provenance().extractionParams().get("unterminatedTableBlocks"))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("unterminated table with zero complete rows: opener dropped, nothing emitted")
    void unterminatedTableWithoutRowsDropped() {
        CanonicalDocument doc = parse("""
                1 First question stem
                <table border="1">
                garbage that never becomes a row
                2 Second question stem
                """);
        assertThat(doc.tables()).isEmpty();
        assertThat(paragraphs(doc)).contains(
                "1 First question stem",
                "garbage that never becomes a row",
                "2 Second question stem");
        assertThat(doc.provenance().extractionParams().get("unterminatedTableBlocks"))
                .isEqualTo(1);
    }
}
