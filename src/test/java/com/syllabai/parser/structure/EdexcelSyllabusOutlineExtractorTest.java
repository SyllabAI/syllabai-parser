package com.syllabai.parser.structure;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalSchema;
import com.syllabai.parser.canonical.ExtractionProvenance;
import com.syllabai.parser.canonical.PageInfo;
import com.syllabai.parser.canonical.SectionInfo;
import com.syllabai.parser.canonical.SourceInfo;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.structure.dto.CurriculumDraft;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class EdexcelSyllabusOutlineExtractorTest {

    @Test
    @DisplayName("numbered headings become units/topics/subtopics with deterministic codes + provenance")
    void extractsNumberedOutline() {
        // structure copied from the real WCH spec (font-derived levels are noisy on
        // purpose: units at L6, topics at L7, subtopics at L8)
        CanonicalDocument syllabus = syllabus(
                section("Contents", 7, 2, List.of("e000001")),
                section("About this specification", 7, 3, List.of()),
                section("Unit 1: Structure, Bonding and Introduction to Organic Chemistry", 6, 18,
                        List.of("e000010")),
                section("IAS compulsory unit Externally assessed Unit description", 7, 18, List.of()),
                section("Topic 1: Formulae, Equations and Amount of Substance", 7, 20,
                        List.of("e000011")),
                section("Topic 2: Atomic Structure and the Periodic Table Students will be assessed", 7, 22,
                        List.of("e000012")),
                section("Topic 3: Bonding and Structure", 7, 24, List.of("e000013")),
                section("3C: Shapes of molecules Students will be assessed on their ability to:", 8, 25,
                        List.of("e000014")),
                section("3D: Metallic bonding", 8, 25, List.of("e000015")),
                section("Unit 2: Energetics, Group Chemistry, Halogenoalkanes and Alcohols", 6, 29,
                        List.of("e000016")),
                section("Assessment information", 7, 31, List.of()),
                section("Topic 6: Energetics Students will be assessed on their ability to:", 7, 32,
                        List.of("e000017")),
                section("8C: Inorganic chemistry of Group 7", 8, 37, List.of("e000018")),
                section("Unit 3: Practical Skills in Chemistry I", 6, 43, List.of("e000019")),
                section("Appendices", 7, 83, List.of()));

        CurriculumDraft draft = new EdexcelSyllabusOutlineExtractor()
                .extract(syllabus, "Edexcel", "IAL", "IAL-CHEM-2018",
                        "Edexcel International Advanced Level Chemistry", "CH", "Chemistry");

        assertThat(draft.schemaVersion()).isEqualTo("1.1");
        assertThat(draft.units()).hasSize(3);

        var u1 = draft.units().get(0);
        assertThat(u1.code()).isEqualTo("U1");
        assertThat(u1.title()).isEqualTo("Structure, Bonding and Introduction to Organic Chemistry");
        assertThat(u1.sourceElementIds()).containsExactly("e000010");
        assertThat(u1.pageNumber()).isEqualTo(18);
        assertThat(u1.confidence()).isEqualTo(0.95);
        assertThat(u1.topics()).extracting(T -> T.code())
                .containsExactly("U1-T1", "U1-T2", "U1-T3");

        // trailing assessment noise is stripped from titles
        assertThat(u1.topics().get(1).title()).isEqualTo("Atomic Structure and the Periodic Table");

        // subtopics: 3C/3D under topic 3, letter-suffixed codes
        var topic3 = u1.topics().get(2);
        assertThat(topic3.subtopics()).extracting(T -> T.code())
                .containsExactly("U1-T3-C", "U1-T3-D");
        assertThat(topic3.subtopics().get(0).title()).isEqualTo("Shapes of molecules");
        assertThat(topic3.subtopics().get(0).confidence()).isEqualTo(0.85);

        // unit 2: topic 6 present; stray subtopic "8C" (topic 8 not current) is noise
        var u2 = draft.units().get(1);
        assertThat(u2.topics()).extracting(T -> T.code()).containsExactly("U2-T6");
        assertThat(u2.topics().get(0).title()).isEqualTo("Energetics");
        assertThat(u2.topics().get(0).subtopics()).isEmpty();

        // unit 3 (practical) carries no topics — the spec prints none
        assertThat(draft.units().get(2).topics()).isEmpty();

        // front matter and appendices never become nodes
        assertThat(draft.provenance().extractionMethod())
                .isEqualTo(EdexcelSyllabusOutlineExtractor.EXTRACTION_METHOD);
        assertThat(draft.provenance().validationStatus()).isEqualTo("SUGGESTED");
        assertThat(draft.provenance().sourceDocumentId()).isEqualTo(syllabus.documentId());
        assertThat(draft.provenance().sourceChecksum()).isEqualTo(syllabus.source().checksum());
    }

    @Test
    @DisplayName("duplicate unit/topic numbers (TOC repeats) keep the first match")
    void firstMatchWins() {
        CanonicalDocument syllabus = syllabus(
                section("Unit 1: Structure, Bonding and Introduction to Organic Chemistry 18", 7, 14,
                        List.of("toc")),
                section("Unit 1: Structure, Bonding and Introduction to Organic Chemistry", 6, 18,
                        List.of("real")),
                section("Topic 1: Formulae, Equations and Amount of Substance 20", 7, 15, List.of("toc2")),
                section("Topic 1: Formulae, Equations and Amount of Substance", 7, 20, List.of("real2")));

        CurriculumDraft draft = new EdexcelSyllabusOutlineExtractor()
                .extract(syllabus, "Edexcel", "IAL", "IAL-CHEM-2018",
                        "Edexcel IAL Chemistry", "CH", "Chemistry");

        // TOC lines carry trailing page numbers; they win only by number-dedup here —
        // the documented behavior is deterministic first-match; the title is kept
        // (trailing digits are real content in some topics, e.g. "Groups 1, 2 and 7")
        assertThat(draft.units()).hasSize(1);
        assertThat(draft.units().get(0).sourceElementIds()).containsExactly("toc");
        assertThat(draft.units().get(0).title())
                .isEqualTo("Structure, Bonding and Introduction to Organic Chemistry 18");
        assertThat(draft.units().get(0).topics()).hasSize(1);
    }

    @Test
    @DisplayName("a topic before any unit is dropped — no orphan nodes")
    void topicWithoutUnitDropped() {
        CanonicalDocument syllabus = syllabus(
                section("Topic 1: Formulae, Equations and Amount of Substance", 7, 2, List.of("e1")),
                section("Unit 1: Structure and Bonding", 6, 18, List.of("e2")));

        CurriculumDraft draft = new EdexcelSyllabusOutlineExtractor()
                .extract(syllabus, "Edexcel", "IAL", "IAL-CHEM-2018",
                        "Edexcel IAL Chemistry", "CH", "Chemistry");

        assertThat(draft.units()).hasSize(1);
        assertThat(draft.units().get(0).topics()).isEmpty();
    }

    private SectionInfo section(String title, int level, int page, List<String> elementIds) {
        return new SectionInfo("s" + page + level, title, level, page, elementIds);
    }

    private CanonicalDocument syllabus(SectionInfo... sections) {
        List<TextBlockElement> blocks = List.of(
                new TextBlockElement("e000001", 1, null, "Unit 1", 0,
                        1.0, TextRole.HEADING, 1, "synthetic", "1"));
        return new CanonicalDocument("synthetic-spec-1", CanonicalSchema.VERSION, 1,
                new SourceInfo("test://spec.pdf", "b".repeat(64), "SHA-256",
                        "application/pdf", "spec.pdf"),
                1, List.of(new PageInfo(1)), List.of(sections), blocks, List.of(), List.of(),
                List.of(),
                new ExtractionProvenance("synthetic", "1", Instant.EPOCH, Map.of(),
                        "syllabai-parser", CanonicalSchema.VERSION));
    }
}
