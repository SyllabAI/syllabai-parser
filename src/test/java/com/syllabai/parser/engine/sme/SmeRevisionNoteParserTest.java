package com.syllabai.parser.engine.sme;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.canonical.FigureElement;
import com.syllabai.parser.canonical.TableElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.engine.ParseFailureException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * T-C06 notes ingestion adapter contract: deterministic parse, the
 * cross-language identity vector (Python reference recorded at the adapter's
 * introduction), verbatim body posture, sidecar pairing guard.
 */
class SmeRevisionNoteParserTest {

    private static final Instant FIXED = Instant.parse("2026-09-18T00:00:00Z");

    /** Mirrors the real scraper shape (front matter + body flow incl. math, HTML sub/sup, figures, table). */
    private static final String SAMPLE = """
            ---
            note_id: "rn_TestNote0001"
            title: "Test Note - Bonding"
            source: https://www.savemyexams.com/ial-chemistry/test-note
            path: 1-test-section/1-1-test-topic/1-1-1-test-note
            updated_at: "2026-07-02T08:19:37.036Z"
            spec_point_ids: ["spcpt_TEST0000000001", "spcpt_TEST0000000002"]
            spec_point_codes: []
            guided_study: false
            ---

            # Test Note - Bonding

            ## Test Note - Bonding

            > **Spec point** \u2014 `spcpt_TEST0000000001`

            - **Ionic** bonding involves electron transfer
            - Alkanes have formula C<sub>n</sub>H<sub>2n+2</sub>

            #### A Deep Heading

            Inline math stays verbatim: $H_{2}O$ plus \\times signs.

            ![Diagram of lattice](../../../assets/test-lattice-1.png)

            ![Remote figure](https://cdn.example.com/remote.png)

            > **Spec point** \u2014 `spcpt_TEST0000000002`

            ## Reactions

            | Element | State |
            | --- | --- |
            | Na | solid |

            > A plain blockquote line
            """;

    private static final String SIDECAR = """
            {
              "schema": "syllabai.sme-revision-note/1.0",
              "note_id": "rn_TestNote0001",
              "course_slug": "ial-chemistry-17",
              "is_ai_assisted": false,
              "titles": {"section": "1. Test Section", "topic": "Test Topic",
                         "subtopic": "Test Note - Bonding"},
              "authors": [{"id": "athr_1", "name": "Richard Boole", "role": "Curriculum Expert"}],
              "reviewers": [{"id": "athr_2", "name": "Caroline Carroll", "role": "Reviewer"}],
              "stats": {"blocks": 12, "figures": 2, "equations": 1},
              "equations": [{"latex": "\\\\rightleftharpoons", "mathml": "<math/>"}]
            }
            """;

    private final SmeRevisionNoteParser parser = new SmeRevisionNoteParser();

    private CanonicalDocument parseSample() {
        return parser.parseWithExtractedAt(
                SAMPLE.getBytes(StandardCharsets.UTF_8), "notes/1-test-section/1-1-test-topic/1-1-1-test-note.md",
                FIXED);
    }

    @Test
    @DisplayName("parsing the same bytes twice yields byte-identical canonical JSON")
    void parsesDeterministically() {
        byte[] source = SAMPLE.getBytes(StandardCharsets.UTF_8);
        CanonicalDocument first = parser.parseWithExtractedAt(source, "corpus/sample.md", FIXED);
        CanonicalDocument second = parser.parseWithExtractedAt(source, "corpus/sample.md", FIXED);
        assertThat(CanonicalJson.write(first)).isEqualTo(CanonicalJson.write(second));
    }

    @Test
    @DisplayName("identity vector matches the Python reference implementation")
    void identityMatchesPythonReference() {
        CanonicalDocument doc = parseSample();
        // Python reference (sha256 of the exact SAMPLE bytes -> CanonicalIdentity formula),
        // computed at adapter introduction and pinned here as the cross-language check.
        assertThat(doc.source().checksum())
                .isEqualTo("b9de2f66b7ac781c0e70cc0222031fa61e6feccd8847c95749f67c0be46a1153");
        assertThat(doc.documentId()).isEqualTo("bff110cf-17e0-5352-b4a0-b2c718dceb16");
    }

    @Test
    @DisplayName("front matter is absorbed into provenance, source.uri is the provider URL")
    void frontMatterBecomesProvenance() {
        CanonicalDocument doc = parseSample();
        assertThat(doc.source().uri())
                .isEqualTo("https://www.savemyexams.com/ial-chemistry/test-note");
        assertThat(doc.source().fileName())
                .isEqualTo("1-1-1-test-note.md");
        assertThat(doc.provenance().engine()).isEqualTo("sme-revision-note");
        assertThat(doc.provenance().engineVersion()).isEqualTo("1.0.0");
        Object noteId = doc.provenance().extractionParams().get("noteId");
        assertThat(noteId).isEqualTo("rn_TestNote0001");
        assertThat(doc.provenance().extractionParams().get("notePath"))
                .isEqualTo("1-test-section/1-1-test-topic/1-1-1-test-note");
        assertThat(doc.provenance().extractionParams().get("guidedStudy")).isEqualTo(false);
        assertThat((java.util.List<String>) doc.provenance().extractionParams().get("specPointIds"))
                .containsExactly("spcpt_TEST0000000001", "spcpt_TEST0000000002");
        assertThat((java.util.List<String>) doc.provenance().extractionParams().get("specPointCodes"))
                .isEmpty();
        assertThat(doc.provenance().extractionParams().get("notationNormalization"))
                .isEqualTo("verbatim-v1-no-notation-rewrites");
        assertThat(doc.provenance().extractionParams().get("specPointMarkerCount")).isEqualTo(2);
    }

    @Test
    @DisplayName("body flow decomposes deterministically with verbatim inline markup")
    void decomposesBodyFlowVerbatim() {
        CanonicalDocument doc = parseSample();
        assertThat(doc.textBlocks()).hasSize(10);
        assertThat(doc.figures()).hasSize(2);
        assertThat(doc.tables()).hasSize(1);
        assertThat(doc.equations()).isEmpty();

        TextBlockElement h1 = doc.textBlocks().get(0);
        assertThat(h1.role()).isEqualTo(TextRole.HEADING);
        assertThat(h1.headingLevel()).isEqualTo(1);
        assertThat(h1.text()).isEqualTo("Test Note - Bonding");

        TextBlockElement quote = doc.textBlocks().get(2);
        assertThat(quote.role()).isEqualTo(TextRole.PARAGRAPH);
        assertThat(quote.text())
                .isEqualTo("**Spec point** \u2014 `spcpt_TEST0000000001`");

        TextBlockElement list = doc.textBlocks().get(4);
        assertThat(list.role()).isEqualTo(TextRole.LIST_ITEM);
        assertThat(list.text())
                .isEqualTo("Alkanes have formula C<sub>n</sub>H<sub>2n+2</sub>");

        TextBlockElement math = doc.textBlocks().get(6);
        assertThat(math.text())
                .isEqualTo("Inline math stays verbatim: $H_{2}O$ plus \\times signs.");
        assertThat(doc.provenance().extractionParams().get("inlineMathCount")).isEqualTo(1);

        FigureElement lattice = doc.figures().get(0);
        assertThat(lattice.text())
                .isEqualTo("../../../assets/test-lattice-1.png");
        assertThat(lattice.sourceName()).isEqualTo("test-lattice-1.png");
        assertThat(lattice.format()).isEqualTo("png");
        assertThat(lattice.alt()).isEqualTo("Diagram of lattice");
        FigureElement remote = doc.figures().get(1);
        assertThat(remote.text()).isEqualTo("https://cdn.example.com/remote.png");

        TableElement table = doc.tables().get(0);
        assertThat(table.rowCount()).isEqualTo(2);
        assertThat(table.columnCount()).isEqualTo(2);
        assertThat(table.rows().get(1)).containsExactly("Na", "solid");
    }

    @Test
    @DisplayName("element ids and reading orders are sequential across all element types")
    void idsAndOrdersAreSequential() {
        CanonicalDocument doc = parseSample();
        var ordered = doc.elementsInReadingOrder();
        assertThat(ordered).hasSize(13);
        for (int i = 0; i < ordered.size(); i++) {
            assertThat(ordered.get(i).elementId())
                    .isEqualTo(String.format("e%06d", i));
            assertThat(ordered.get(i).readingOrder()).isEqualTo(i);
        }
        // textBlocks alone are NOT contiguous: figures/tables interleave (e000007/e000008/e000011)
        assertThat(doc.textBlocks()).hasSize(10);
        assertThat(doc.textBlocks().get(7).elementId()).isEqualTo("e000009");
        assertThat(doc.textBlocks().get(8).elementId()).isEqualTo("e000010");
    }

    @Test
    @DisplayName("every heading opens a section and all element types attach")
    void sectionsAttachAllElementTypes() {
        CanonicalDocument doc = parseSample();
        assertThat(doc.sections()).hasSize(4);
        assertThat(doc.sections().get(0).title()).isEqualTo("Test Note - Bonding");
        assertThat(doc.sections().get(0).level()).isEqualTo(1);
        assertThat(doc.sections().get(2).title()).isEqualTo("A Deep Heading");
        assertThat(doc.sections().get(2).level()).isEqualTo(4);
        // figures live inside section 3
        assertThat(doc.sections().get(2).elementIds())
                .contains("e000007", "e000008");
        assertThat(doc.sections().get(3).elementIds())
                .contains("e000011"); // the table
    }

    @Test
    @DisplayName("sidecar enriches provenance without touching identity or content")
    void sidecarEnrichesProvenance() {
        CanonicalDocument doc = parser.parseWithSidecar(
                SAMPLE.getBytes(StandardCharsets.UTF_8), "notes/sample.md",
                SIDECAR.getBytes(StandardCharsets.UTF_8), FIXED);
        assertThat(doc.provenance().extractionParams().get("courseSlug"))
                .isEqualTo("ial-chemistry-17");
        assertThat(doc.provenance().extractionParams().get("sidecarSectionTitle"))
                .isEqualTo("1. Test Section");
        assertThat((java.util.List<String>) doc.provenance().extractionParams().get("sidecarAuthors"))
                .containsExactly("Richard Boole");
        assertThat(doc.provenance().extractionParams().get("sidecarEquationCount")).isEqualTo(1);
        // identity and content unchanged vs the plain parse
        CanonicalDocument plain = parseSample();
        assertThat(doc.documentId()).isEqualTo(plain.documentId());
        assertThat(doc.textBlocks()).isEqualTo(plain.textBlocks());
    }

    @Test
    @DisplayName("sidecar note_id mismatch fails closed (wrong-file pairing guard)")
    void sidecarPairingGuard() {
        String mismatched = SIDECAR.replace("rn_TestNote0001", "rn_OtherNote9999");
        assertThatThrownBy(() -> parser.parseWithSidecar(
                SAMPLE.getBytes(StandardCharsets.UTF_8), "sample.md",
                mismatched.getBytes(StandardCharsets.UTF_8), FIXED))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("does not match");
        String wrongSchema = SIDECAR.replace("syllabai.sme-revision-note/1.0",
                "syllabai.sme-revision-note/9.9");
        assertThatThrownBy(() -> parser.parseWithSidecar(
                SAMPLE.getBytes(StandardCharsets.UTF_8), "sample.md",
                wrongSchema.getBytes(StandardCharsets.UTF_8), FIXED))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("schema");
    }

    @Test
    @DisplayName("fail-closed: missing keys, bad note id, unclosed front matter")
    void failsClosed() {
        String missingKey = SAMPLE.replace("updated_at: \"2026-07-02T08:19:37.036Z\"\n", "");
        assertThatThrownBy(() -> parser.parseWithExtractedAt(
                missingKey.getBytes(StandardCharsets.UTF_8), "m.md", FIXED))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("updated_at");
        String badId = SAMPLE.replace("rn_TestNote0001", "not-a-valid-id");
        assertThatThrownBy(() -> parser.parseWithExtractedAt(
                badId.getBytes(StandardCharsets.UTF_8), "m.md", FIXED))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("note_id format");
        String unclosed = SAMPLE.substring(0, SAMPLE.indexOf("guided_study"));
        assertThatThrownBy(() -> parser.parseWithExtractedAt(
                unclosed.getBytes(StandardCharsets.UTF_8), "m.md", FIXED))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("'---'");
        assertThatThrownBy(() -> parser.parseWithExtractedAt(
                "no front matter here".getBytes(StandardCharsets.UTF_8), "m.md", FIXED))
                .isInstanceOf(ParseFailureException.class)
                .hasMessageContaining("front matter missing");
    }

    @Test
    @DisplayName("mime support is markdown-only")
    void supportsMarkdownOnly() {
        assertThat(parser.supports("text/markdown")).isTrue();
        assertThat(parser.supports("text/x-markdown")).isTrue();
        assertThat(parser.supports("application/pdf")).isFalse();
        assertThat(parser.engineName()).isEqualTo("sme-revision-note");
    }
}
