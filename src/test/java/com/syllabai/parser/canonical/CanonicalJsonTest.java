package com.syllabai.parser.canonical;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Canonical format tests (Master Spec §8): exact spec field names, round-trip
 * fidelity, determinism modulo identity fields, and validator rejections.
 */
class CanonicalJsonTest {

    private static final Instant FIXED = Instant.parse("2026-09-03T00:00:00Z");

    private CanonicalDocument sample() {
        List<TextBlockElement> textBlocks = List.of(
                new TextBlockElement("e000000", 1,
                        new BoundingBox(72, 700, 200, 20), "Formulae and periodic table", 0,
                        1.0, TextRole.HEADING, 1, "opendataloader-pdf", "2.5.7"),
                new TextBlockElement("e000001", 1,
                        new BoundingBox(72, 650, 400, 60),
                        "1 A student heats copper(II) carbonate. (Total for Question 1 = 3 marks)",
                        1, 1.0, TextRole.PARAGRAPH, null, "opendataloader-pdf", "2.5.7"));
        // P-6: documentId is derived, not free-form — synthetic documents mint
        // their id through the identity layer so the validator's derivation
        // check holds.
        String documentId = CanonicalIdentity.contentDocumentId(
                "a".repeat(64), "opendataloader-pdf", "2.5.7");
        return new CanonicalDocument(documentId,
                CanonicalSchema.VERSION, 1,
                new SourceInfo("corpus/IGCSE/Chemistry/Paper 1/Jan 2012 QP.pdf",
                        "a".repeat(64), "SHA-256", "application/pdf", "QP.pdf"),
                1, List.of(new PageInfo(1)),
                List.of(new SectionInfo("s001", "Formulae and periodic table", 1, 1,
                        List.of("e000001"))),
                textBlocks,
                List.of(new TableElement("e000002", 1, null, 2, 1.0,
                        List.of(List.of("A", "B"), List.of("1", "2")),
                        "opendataloader-pdf", "2.5.7")),
                List.of(), List.of(),
                new ExtractionProvenance("opendataloader-pdf", "2.5.7", FIXED,
                        Map.of("mode", "fast"), "syllabai-parser", "1.0"));
    }

    @Test
    @DisplayName("serialization uses the exact Master Spec §8 field names")
    void specFieldNames() {
        String json = CanonicalJson.write(sample());
        assertThat(json).contains("\"documentId\"");
        assertThat(json).contains("\"schemaVersion\"");
        assertThat(json).contains("\"version\" : 1");
        assertThat(json).contains("\"source\"");
        assertThat(json).contains("\"uri\"");
        assertThat(json).contains("\"checksum\"");
        assertThat(json).contains("\"mimeType\"");
        assertThat(json).contains("\"pageCount\"");
        assertThat(json).contains("\"pages\"");
        assertThat(json).contains("\"sections\"");
        assertThat(json).contains("\"textBlocks\"");
        assertThat(json).contains("\"tables\"");
        assertThat(json).contains("\"figures\"");
        assertThat(json).contains("\"equations\"");
        assertThat(json).contains("\"provenance\"");
        assertThat(json).contains("\"element_id\"");
        assertThat(json).contains("\"element_type\" : \"text_block\"");
        assertThat(json).contains("\"element_type\" : \"table\"");
        assertThat(json).contains("\"page_number\"");
        assertThat(json).contains("\"bounding_box\"");
        assertThat(json).contains("\"reading_order\"");
        assertThat(json).contains("\"confidence\"");
        assertThat(json).contains("\"source_engine\"");
        assertThat(json).contains("\"source_engine_version\"");
        assertThat(json).contains("\"engineVersion\" : \"2.5.7\"");
        assertThat(json).contains("\"extractedAt\" : \"2026-09-03T00:00:00Z\"");
    }

    @Test
    @DisplayName("JSON round-trip reproduces the document")
    void roundTrip() {
        CanonicalDocument parsed = CanonicalJson.read(CanonicalJson.write(sample()));
        assertThat(parsed).isEqualTo(sample());
    }

    @Test
    @DisplayName("serialization is deterministic: same document, same bytes")
    void deterministic() {
        assertThat(CanonicalJson.write(sample()))
                .isEqualTo(CanonicalJson.write(sample()));
    }

    @Test
    @DisplayName("elementsInReadingOrder is stable across containers")
    void readingOrderAcrossContainers() {
        CanonicalDocument doc = sample();
        assertThat(doc.elementsInReadingOrder())
                .extracting(DocumentElement::readingOrder)
                .containsExactly(0, 1, 2);
        assertThat(doc.elementsInReadingOrder())
                .extracting(DocumentElement::elementId)
                .containsExactly("e000000", "e000001", "e000002");
    }

    @Test
    @DisplayName("validator accepts a well-formed document")
    void validatesOk() {
        CanonicalValidator.validate(sample());
    }

    @Test
    @DisplayName("validator rejects an unsupported schema version")
    void rejectsUnknownSchema() {
        CanonicalDocument bad = new CanonicalDocument("id", "9.9", 1,
                sample().source(), 1, sample().pages(), List.of(), List.of(), List.of(),
                List.of(), List.of(), sample().provenance());
        assertThatThrownBy(() -> CanonicalValidator.validate(bad))
                .isInstanceOf(CanonicalValidator.ValidationException.class)
                .hasMessageContaining("unsupported schemaVersion");
    }

    @Test
    @DisplayName("validator rejects duplicate element ids")
    void rejectsDuplicateIds() {
        TextBlockElement duplicate = new TextBlockElement("e000000", 1, null, "x", 1,
                1.0, TextRole.PARAGRAPH, null, "opendataloader-pdf", "2.5.7");
        CanonicalDocument bad = new CanonicalDocument(sample().documentId(), "1.0", 1,
                sample().source(), 1, sample().pages(), List.of(),
                List.of(sample().textBlocks().get(0), duplicate), List.of(), List.of(),
                List.of(), sample().provenance());
        assertThatThrownBy(() -> CanonicalValidator.validate(bad))
                .isInstanceOf(CanonicalValidator.ValidationException.class)
                .hasMessageContaining("duplicate element_id");
    }

    @Test
    @DisplayName("checksums: sha256 of known bytes")
    void checksum() {
        assertThat(Checksums.sha256Hex("abc".getBytes()))
                .isEqualTo("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }
}
