package com.syllabai.parser.engine.opendataloader;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.canonical.DocumentElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.engine.ParseFailureException;
import com.syllabai.parser.structure.PastPaperStructureExtractor;
import com.syllabai.parser.structure.dto.PastPaperDraft;
import java.io.IOException;
import java.util.List;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.font.Standard14Fonts;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * T-009 acceptance: the real opendataloader-pdf engine, in-process, on a PDF
 * generated deterministically in-test (PDFBox, test scope). Pins the whole
 * chain — bytes → engine → JSON → canonical document → structure draft —
 * without committing binary fixtures to git.
 */
class OpenDataLoaderParserTest {

    private static final List<String> QP_LINES = List.of(
            "1 A student heats copper(II) carbonate in a test tube.",
            "(a) State the colour change of the solid. (1)",
            "(b) Name the gas produced. (1)",
            "(Total for Question 1 = 2 marks)",
            "2 Copper is extracted from its ore by heating with carbon.",
            "State the type of reaction involved. (1)");

    private final OpenDataLoaderParser parser = new OpenDataLoaderParser();

    @Test
    @DisplayName("parses a generated PDF into a valid canonical document with provenance")
    void parsesGeneratedPdf() throws IOException {
        byte[] pdf = questionPaperPdf();

        CanonicalDocument document = parser.parse(pdf, "fixtures/generated-qp.pdf");

        assertThat(document.schemaVersion()).isEqualTo("1.0");
        assertThat(document.pageCount()).isEqualTo(1);
        assertThat(document.source().mimeType()).isEqualTo("application/pdf");
        assertThat(document.source().checksum()).hasSize(64);
        assertThat(document.provenance().engine()).isEqualTo("opendataloader-pdf");
        assertThat(document.provenance().engineVersion())
                .isNotEqualTo(OpenDataLoaderEngineVersion.FALLBACK);
        assertThat(document.provenance().extractionParams())
                .containsEntry("mode", "fast")
                .containsEntry("readingOrder", "xycut");

        assertThat(document.textBlocks()).isNotEmpty();
        assertThat(document.textBlocks())
                .extracting(TextBlockElement::text)
                .anySatisfy(text -> assertThat(text).startsWith("1 A student heats"));
    }

    @Test
    @DisplayName("text blocks carry page numbers, ids, reading order and confidence")
    void elementContract() throws IOException {
        CanonicalDocument document = parser.parse(questionPaperPdf(), "fixtures/generated-qp.pdf");

        List<DocumentElement> elements = document.elementsInReadingOrder();
        assertThat(elements).isNotEmpty();
        for (int i = 0; i < elements.size(); i++) {
            DocumentElement element = elements.get(i);
            assertThat(element.elementId()).startsWith("e");
            assertThat(element.pageNumber()).isEqualTo(1);
            assertThat(element.readingOrder()).isEqualTo(i);
            assertThat(element.confidence()).isNotNull();
            assertThat(element.sourceEngine()).isEqualTo("opendataloader-pdf");
            assertThat(element.sourceEngineVersion()).isNotBlank();
        }
    }

    @Test
    @DisplayName("the full chain works: PDF → canonical → question/parts draft")
    void fullChainToDraft() throws IOException {
        CanonicalDocument document = parser.parse(questionPaperPdf(), "fixtures/generated-qp.pdf");

        PastPaperDraft draft = new PastPaperStructureExtractor()
                .extract(document, null, "Edexcel", "IGCSE", "Chemistry",
                        "Paper 1C", "June 2016", "4CH0/1C");

        assertThat(draft.questions()).isNotEmpty();
        assertThat(draft.questions().get(0).questionNumber()).isEqualTo("1");
        assertThat(draft.questions().get(0).parts()).hasSize(2);
        assertThat(draft.questions().get(0).marks()).isEqualTo(2);
        assertThat(draft.questions().get(0).parts().get(0).commandWord()).isEqualTo("state");
        assertThat(draft.reviewRequired()).isTrue();
        assertThat(draft.questions())
                .allSatisfy(q -> assertThat(q.confidence()).isLessThan(1.0));
    }

    @Test
    @DisplayName("canonical JSON round-trips an engine-produced document")
    void roundTripEngineOutput() throws IOException {
        CanonicalDocument document = parser.parse(questionPaperPdf(), "fixtures/generated-qp.pdf");
        CanonicalDocument reparsed = CanonicalJson.read(CanonicalJson.write(document));
        assertThat(reparsed).isEqualTo(document);
    }

    @Test
    @DisplayName("garbage bytes fail loudly instead of producing an empty document")
    void rejectsGarbage() {
        assertThatThrownBy(() -> parser.parse("not a pdf".getBytes(), "fixtures/garbage.bin"))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("opendataloader-pdf");
    }

    @Test
    @DisplayName("determinism regression: same PDF bytes twice yield identical document identity")
    void parsesDeterministically() throws IOException {
        byte[] pdf = questionPaperPdf();

        CanonicalDocument first = parser.parse(pdf, "fixtures/generated-qp.pdf");
        CanonicalDocument second = parser.parse(pdf, "fixtures/generated-qp.pdf");

        // CanonicalDocument.of used to mint UUID.randomUUID(); identity is now
        // derived from source checksum + engine + engine version (Session 9).
        assertThat(second.documentId()).isEqualTo(first.documentId());
        List<DocumentElement> a = first.elementsInReadingOrder();
        List<DocumentElement> b = second.elementsInReadingOrder();
        assertThat(b).hasSameSizeAs(a);
        for (int i = 0; i < a.size(); i++) {
            assertThat(b.get(i).elementId()).isEqualTo(a.get(i).elementId());
        }
    }

    @Test
    @DisplayName("engine name/version identity is stable")
    void identity() {
        assertThat(parser.engineName()).isEqualTo("opendataloader-pdf");
        assertThat(parser.engineVersion()).isNotBlank();
        assertThat(parser.supports("application/pdf")).isTrue();
        assertThat(parser.supports("image/png")).isFalse();
    }

    // ── deterministic Edexcel-style question paper via PDFBox ────────────────

    private byte[] questionPaperPdf() throws IOException {
        try (PDDocument pdf = new PDDocument()) {
            PDPage page = new PDPage(PDRectangle.A4);
            pdf.addPage(page);
            try (PDPageContentStream stream = new PDPageContentStream(pdf, page)) {
                stream.beginText();
                stream.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA), 11);
                stream.newLineAtOffset(72, 770);
                for (String line : QP_LINES) {
                    stream.newLineAtOffset(0, -18);
                    stream.showText(line);
                }
                stream.endText();
            }
            return java.nio.file.Files.readAllBytes(writeTemp(pdf));
        }
    }

    private java.nio.file.Path writeTemp(PDDocument pdf) throws IOException {
        java.nio.file.Path temp = java.nio.file.Files.createTempFile("syllabai-fixture", ".pdf");
        pdf.save(temp.toFile());
        return temp;
    }

    /** The engine classifies roles (heading/list item/paragraph) — reported for all blocks. */
    @Test
    @DisplayName("every text block reports a non-null structural role")
    void rolesReported() throws IOException {
        CanonicalDocument document = parser.parse(questionPaperPdf(), "fixtures/generated-qp.pdf");
        assertThat(document.textBlocks()).isNotEmpty();
        assertThat(document.textBlocks())
                .allSatisfy(block -> assertThat(block.role()).isNotNull());
    }
}
