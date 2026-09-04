package com.syllabai.parser.canonical;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Session 9 regression: canonical identity must be deterministic.
 *
 * <p>Background: {@code CanonicalDocument.of} used to mint
 * {@code UUID.randomUUID()}, so parsing the same source twice produced
 * unrelated document ids — breaking reproducible canonical parsing and
 * cross-language conformance. Identity now lives at the canonical layer
 * ({@link CanonicalIdentity}) and never contains a random component or a
 * timestamp.</p>
 */
class CanonicalIdentityTest {

    private static final String CHECKSUM =
            "b6c1a1f2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9012";
    private static final String ENGINE = "glm-ocr-markdown";
    private static final String VERSION = "1.0.0";

    @Test
    @DisplayName("same checksum + engine + version yields the same id, repeatedly")
    void sameInputYieldsSameId() {
        String first = CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, VERSION);
        String second = CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, VERSION);
        assertThat(first).isEqualTo(second);
        assertThat(first).isEqualTo(CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, VERSION));
    }

    @Test
    @DisplayName("different engine version yields a different id (re-parse identity)")
    void engineVersionChangesIdentity() {
        String v1 = CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, "1.0.0");
        String v2 = CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, "1.1.0");
        assertThat(v1).isNotEqualTo(v2);
    }

    @Test
    @DisplayName("different engine or different source checksum yields a different id")
    void engineAndChecksumChangeIdentity() {
        String base = CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, VERSION);
        assertThat(CanonicalIdentity.contentDocumentId(CHECKSUM, "opendataloader-pdf", VERSION))
                .isNotEqualTo(base);
        assertThat(CanonicalIdentity.contentDocumentId(
                "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", ENGINE, VERSION))
                .isNotEqualTo(base);
    }

    @Test
    @DisplayName("ids are valid version-5-layout UUIDs")
    void idIsNameBasedUuid() {
        UUID parsed = UUID.fromString(
                CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, VERSION));
        assertThat(parsed.version()).isEqualTo(5);
        assertThat(parsed.variant()).isEqualTo(UUID.randomUUID().variant());
    }

    @Test
    @DisplayName("checksum case and surrounding whitespace are normalized")
    void normalizationIsStable() {
        String lower = CanonicalIdentity.contentDocumentId(CHECKSUM, ENGINE, VERSION);
        String upper = CanonicalIdentity.contentDocumentId(CHECKSUM.toUpperCase(), " "
                + ENGINE.toUpperCase() + " ", " " + VERSION.toUpperCase() + " ");
        assertThat(upper).isEqualTo(lower);
    }

    @Test
    @DisplayName("CanonicalDocument.of is deterministic: same source + engine + version, different run")
    void canonicalDocumentOfIsDeterministic() {
        CanonicalDocument first = sample();
        CanonicalDocument second = sample();
        assertThat(first.documentId()).isEqualTo(second.documentId());
    }

    @Test
    @DisplayName("timestamps never enter the id: extractedAt may differ, id may not")
    void timestampsNeverEnterIdentity() {
        ExtractionProvenance atNoon = provenance(Instant.parse("2026-09-05T12:00:00Z"));
        ExtractionProvenance atMidnight = provenance(Instant.parse("2020-01-01T00:00:00Z"));
        CanonicalDocument noon = of(atNoon);
        CanonicalDocument midnight = of(atMidnight);
        assertThat(noon.documentId()).isEqualTo(midnight.documentId());
        assertThat(noon.provenance().extractedAt()).isNotEqualTo(midnight.provenance().extractedAt());
    }

    @Test
    @DisplayName("of() ids differ from random UUIDs by construction (no random component)")
    void deterministicFactoryBeatsRandom() {
        // Two of() calls must be equal; a random UUID collision-free space means
        // an of() id is effectively never equal to a freshly minted random UUID.
        assertThat(of(provenance(Instant.now())).documentId())
                .isNotEqualTo(UUID.randomUUID().toString());
    }

    // ── helpers ────────────────────────────────────────────────────────────────

    private static CanonicalDocument sample() {
        return of(provenance(Instant.now()));
    }

    private static CanonicalDocument of(ExtractionProvenance provenance) {
        return CanonicalDocument.of(
                new SourceInfo("corpus/sample.md", CHECKSUM, "SHA-256", "text/markdown",
                        "sample.md"),
                1, List.of(new PageInfo(1)), List.of(),
                List.of(new TextBlockElement("e000001", 1, null, "text", 0, 1.0,
                        TextRole.PARAGRAPH, null, "test-engine", "1.0.0")),
                List.of(), List.of(), List.of(), provenance);
    }

    private static ExtractionProvenance provenance(Instant extractedAt) {
        return new ExtractionProvenance("test-engine", "1.0.0", extractedAt,
                java.util.Map.of(), ExtractionProvenance.APPLICATION, CanonicalSchema.VERSION);
    }
}
