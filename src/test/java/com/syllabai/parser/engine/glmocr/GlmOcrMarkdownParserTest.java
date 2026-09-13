package com.syllabai.parser.engine.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.DocumentElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Session 9 regression: the GLM-OCR Markdown adapter must parse
 * deterministically (same bytes → same documentId, same element ids, same
 * order) and must be honest about pages (pageCount=1,
 * pageBoundaries=none-in-source) and signed-URL figure references.
 *
 * <p>Sample syntax below mirrors the audited real corpus
 * ({@code Past-Papers/GLM-markdown-sample/}): Markdown {@code #} headings,
 * {@code <div style='text-align: center;'><img src='…' alt='OCR图片'/></div>}
 * image lines, plain {@code <div align="center">} blocks for marks/totals,
 * HTML tables, {@code $$} display math, and the entity forms the corpus
 * actually contains ({@code &#x27;}, {@code &gt;}, {@code &lt;}).</p>
 */
class GlmOcrMarkdownParserTest {

    private static final String SAMPLE = """
            # Pearson Edexcel Level 3 GCE

            ## June 2025

            Turn over &#x27;not a boundary&#x27; &gt; test

            1 Define, in words, the term velocity. (1)

            <div align="center">
            *(a) State the SI unit of velocity.
            </div>

            <div style='text-align: center;'><img src='https://maas-watermark-prod-new.cn-wlcb.ufileos.com/ocr%2Fcrop%2F20260401%2Fcrop_1_1774977205806.png?UCloudPublicKey=TOKEN_6df395df-5d8c-4f69-90f8-a4fe46088958&Signature=4lRwKgtA6uw%2B71q0zuG2bOvBlUI%3D&Expires=1775582005' alt='OCR图片'/></div>

            <table>
            <tr><td>Question Number</td><td>Acceptable Answer</td><td>Mark</td></tr>
            <tr><td>1(a)</td><td> metre per second &amp; m&#x27;s⁻¹ </td><td>(1)</td></tr>
            </table>

            $$v = u + at$$
            """;

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();

    @Test
    @DisplayName("parsing the same bytes twice yields identical ids and ordering")
    void parsesDeterministically() {
        byte[] source = SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8);

        CanonicalDocument first = parser.parse(source, "corpus/sample.md");
        CanonicalDocument second = parser.parse(source, "corpus/sample.md");

        assertThat(second.documentId()).isEqualTo(first.documentId());
        assertThat(second.source().checksum()).isEqualTo(first.source().checksum());
        assertThat(elementIds(second)).isEqualTo(elementIds(first));

        List<DocumentElement> a = first.elementsInReadingOrder();
        List<DocumentElement> b = second.elementsInReadingOrder();
        assertThat(b).hasSameSizeAs(a);
        for (int i = 0; i < a.size(); i++) {
            assertThat(b.get(i).elementId()).isEqualTo(a.get(i).elementId());
            assertThat(b.get(i).readingOrder()).isEqualTo(a.get(i).readingOrder());
        }
    }

    @Test
    @DisplayName("parseWithFixedIdentity is byte-reproducible including provenance")
    void fixedIdentityIsReproducible() {
        byte[] source = SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        Instant t1 = Instant.parse("2026-09-05T10:00:00Z");
        Instant t2 = Instant.parse("2026-09-05T10:00:00Z");
        assertThat(parser.parseWithFixedIdentity(source, "corpus/sample.md", t1))
                .isEqualTo(parser.parseWithFixedIdentity(source, "corpus/sample.md", t2));
    }

    @Test
    @DisplayName("no page boundaries in source: pageCount=1 and honesty parameter recorded")
    void pageHonesty() {
        CanonicalDocument document = parser.parse(
                SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8), "corpus/sample.md");
        assertThat(document.pageCount()).isEqualTo(1);
        assertThat(document.pages()).hasSize(1);
        assertThat(document.provenance().extractionParams())
                .containsEntry("pageBoundaries", "none-in-source");
    }

    @Test
    @DisplayName("HTML entities are decoded and the decoding is counted in provenance")
    void entitiesDecodedAndRecorded() {
        CanonicalDocument document = parser.parse(
                SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8), "corpus/sample.md");
        assertThat(document.provenance().extractionParams())
                .containsEntry("normalizedHtmlEntities", true)
                .containsEntry("entityDecodedLines", 2); // stem line + one MS table cell
        String line = document.textBlocks().stream()
                .map(TextBlockElement::text)
                .filter(t -> t.contains("boundary"))
                .findFirst().orElse("");
        assertThat(line).contains("not a boundary' > test");
    }

    @Test
    @DisplayName("image divs become figures preserving the COMPLETE URL, path identity and signed-url count")
    void imageDivsBecomeFigures() {
        CanonicalDocument document = parser.parse(
                SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8), "corpus/sample.md");
        assertThat(document.figures()).hasSize(1);
        assertThat(document.figures().get(0).text())
                .startsWith("https://maas-watermark-prod-new.cn-wlcb.ufileos.com/ocr%2Fcrop%2F")
                .contains("Expires=1775582005"); // full signed URL preserved, not just path
        assertThat(document.figures().get(0).sourceName()).isEqualTo(
                "/ocr/crop/20260401/crop_1_1774977205806.png"); // decoded URL path
        assertThat(document.figures().get(0).format()).isEqualTo("png");
        assertThat(document.figures().get(0).alt()).isEqualTo("OCR图片");
        assertThat(document.provenance().extractionParams())
                .containsEntry("signedUrlFigureRefs", 1);
    }

    @Test
    @DisplayName("HTML tables parse into rows with entities decoded, display math into equations")
    void tablesAndEquations() {
        CanonicalDocument document = parser.parse(
                SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8), "corpus/sample.md");
        assertThat(document.tables()).hasSize(1);
        List<List<String>> rows = document.tables().get(0).rows();
        assertThat(rows).hasSize(2);
        assertThat(rows.get(0)).containsExactly("Question Number", "Acceptable Answer", "Mark");
        assertThat(rows.get(1)).containsExactly("1(a)", "metre per second & m's⁻¹", "(1)");
        assertThat(document.equations()).hasSize(1);
        assertThat(document.equations().get(0).latex()).contains("v = u + at");
    }

    @Test
    @DisplayName("Markdown headings become HEADING blocks with level and role")
    void headingsDetected() {
        CanonicalDocument document = parser.parse(
                SAMPLE.getBytes(java.nio.charset.StandardCharsets.UTF_8), "corpus/sample.md");
        List<TextBlockElement> headings = document.textBlocks().stream()
                .filter(b -> b.role() == TextRole.HEADING)
                .toList();
        assertThat(headings).extracting(TextBlockElement::text)
                .contains("Pearson Edexcel Level 3 GCE", "June 2025");
        assertThat(headings.get(0).headingLevel()).isEqualTo(1);
        assertThat(headings.get(1).headingLevel()).isEqualTo(2);
    }

    @Test
    @DisplayName("engine identity and markdown support")
    void engineIdentity() {
        assertThat(parser.engineName()).isEqualTo("glm-ocr-markdown");
        assertThat(parser.engineVersion()).isEqualTo("1.1.0");
        assertThat(parser.supports("text/markdown")).isTrue();
        assertThat(parser.supports("application/pdf")).isFalse();
    }

    private static List<String> elementIds(CanonicalDocument document) {
        return document.elementsInReadingOrder().stream()
                .map(DocumentElement::elementId)
                .toList();
    }
}
