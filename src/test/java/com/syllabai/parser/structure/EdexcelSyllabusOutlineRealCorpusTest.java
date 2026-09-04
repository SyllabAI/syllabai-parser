package com.syllabai.parser.structure;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.structure.dto.CurriculumDraft;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Real-corpus verification (T-010): the extractor against the committed
 * Edexcel IAL Chemistry 2018 specification canonical document
 * (corpus/ial-chemistry-2018-spec, parsed from Pearson's published PDF).
 * Pins the structure the whole KG seed depends on — 6 units, 20 topics,
 * 15 lettered subtopics — so silent regressions in extraction fail here,
 * not in production curriculum ingestion.
 */
class EdexcelSyllabusOutlineRealCorpusTest {

    private static final Path FIXTURE =
            Path.of("corpus/ial-chemistry-2018-spec/canonical-syllabus.json");

    @Test
    @DisplayName("the real IAL Chemistry spec yields 6 units / 20 topics / 15 subtopics, all SUGGESTED with provenance")
    void extractsRealSpecOutline() {
        org.junit.jupiter.api.Assumptions.assumeTrue(Files.exists(FIXTURE),
                "corpus fixture not checked out — run ParserCli SYLLABUS to regenerate");
        CanonicalDocument spec = CanonicalJson.read(FIXTURE);

        CurriculumDraft draft = new EdexcelSyllabusOutlineExtractor()
                .extract(spec, "Edexcel", "IAL", "IAL-CHEM-2018",
                        "Edexcel International Advanced Level Chemistry", "CH", "Chemistry");

        assertThat(draft.schemaVersion()).isEqualTo("1.1");
        assertThat(draft.provenance().extractionMethod())
                .isEqualTo(EdexcelSyllabusOutlineExtractor.EXTRACTION_METHOD);
        assertThat(draft.provenance().validationStatus()).isEqualTo("SUGGESTED");
        assertThat(draft.provenance().sourceChecksum()).isNotBlank();

        assertThat(draft.units()).hasSize(6);
        assertThat(draft.units()).extracting(U -> U.code())
                .containsExactly("U1", "U2", "U3", "U4", "U5", "U6");
        // every unit cites its spec section + page
        assertThat(draft.units()).allSatisfy(u -> {
            assertThat(u.sourceSectionId()).isNotBlank();
            assertThat(u.pageNumber()).isPositive();
            assertThat(u.confidence()).isEqualTo(0.95);
        });

        int topics = draft.units().stream().mapToInt(u -> u.topics().size()).sum();
        int subtopics = draft.units().stream()
                .flatMap(u -> u.topics().stream())
                .mapToInt(t -> t.subtopics().size()).sum();
        assertThat(topics).isEqualTo(20);
        assertThat(subtopics).isEqualTo(15);

        // spot-check known structure: U1 Topic 1 is the mole topic the pilot seeds build on
        CurriculumDraft.TopicDraft topic1 = draft.units().get(0).topics().get(0);
        assertThat(topic1.code()).isEqualTo("U1-T1");
        assertThat(topic1.title()).isEqualTo("Formulae, Equations and Amount of Substance");
        assertThat(topic1.sourceElementIds()).isNotEmpty();

        // practical units legitimately have no topics — the spec prints none
        assertThat(draft.units().get(2).topics()).isEmpty();   // U3
        assertThat(draft.units().get(5).topics()).isEmpty();   // U6

        // subtopic letters under T3: C, D (A/B are body text, not headings)
        assertThat(draft.units().get(0).topics().get(2).subtopics())
                .extracting(s -> s.code())
                .containsExactly("U1-T3-C", "U1-T3-D");
    }
}
