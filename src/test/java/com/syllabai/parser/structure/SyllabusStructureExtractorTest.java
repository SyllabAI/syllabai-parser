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

class SyllabusStructureExtractorTest {

    @Test
    @DisplayName("headings become units/topics; codes are deterministic; status SUGGESTED")
    void extractsHierarchy() {
        CanonicalDocument syllabus = syllabus(
                new SectionInfo("s001", "Unit 1: Principles of chemistry", 1, 1, List.of("e000001")),
                new SectionInfo("s002", "Topic 1: Formulae", 2, 1, List.of()),
                new SectionInfo("s003", "Topic 2: Atomic structure", 2, 1, List.of()),
                new SectionInfo("s004", "Unit 2: Applications", 1, 2, List.of()));

        CurriculumDraft draft = new SyllabusStructureExtractor()
                .extract(syllabus, "Edexcel", "IAL", "WCH11",
                        "Edexcel IAL Chemistry", "CH", "Chemistry");

        assertThat(draft.units()).hasSize(2);
        assertThat(draft.units().get(0).code()).isEqualTo("U1");
        assertThat(draft.units().get(0).title()).isEqualTo("Unit 1: Principles of chemistry");
        assertThat(draft.units().get(0).topics())
                .extracting(T -> T.code())
                .containsExactly("U1-T1", "U1-T2");
        assertThat(draft.units().get(0).topics())
                .extracting(T -> T.title())
                .containsExactly("Topic 1: Formulae", "Topic 2: Atomic structure");
        assertThat(draft.units().get(1).code()).isEqualTo("U2");
        assertThat(draft.units().get(1).topics()).isEmpty();

        assertThat(draft.provenance().sourceDocumentId()).isEqualTo(syllabus.documentId());
        assertThat(draft.provenance().sourceChecksum()).isEqualTo(syllabus.source().checksum());
        assertThat(draft.provenance().validationStatus()).isEqualTo("SUGGESTED");
        assertThat(draft.provenance().extractionMethod())
                .isEqualTo(SyllabusStructureExtractor.EXTRACTION_METHOD);
        assertThat(draft.provenance().engine()).isEqualTo("synthetic");
    }

    @Test
    @DisplayName("level-3 headings become subtopics of the previous topic")
    void subtopics() {
        CanonicalDocument syllabus = syllabus(
                new SectionInfo("s001", "Unit 1: Principles", 1, 1, List.of()),
                new SectionInfo("s002", "Topic 1: Formulae", 2, 1, List.of()),
                new SectionInfo("s003", "Ionic compounds", 3, 1, List.of()),
                new SectionInfo("s004", "Covalent compounds", 3, 1, List.of()));

        CurriculumDraft draft = new SyllabusStructureExtractor()
                .extract(syllabus, "Edexcel", "IAL", "WCH11",
                        "Edexcel IAL Chemistry", "CH", "Chemistry");

        assertThat(draft.units().get(0).topics().get(0).subtopics())
                .extracting(T -> T.title())
                .containsExactly("Ionic compounds", "Covalent compounds");
    }

    private CanonicalDocument syllabus(SectionInfo... sections) {
        List<TextBlockElement> blocks = List.of(
                new TextBlockElement("e000001", 1, null, "Unit 1: Principles of chemistry", 0,
                        1.0, TextRole.HEADING, 1, "synthetic", "1"),
                new TextBlockElement("e000002", 1, null, "This unit covers the basics.", 1,
                        1.0, TextRole.PARAGRAPH, null, "synthetic", "1"));
        return new CanonicalDocument("synthetic-syllabus-1", CanonicalSchema.VERSION, 1,
                new SourceInfo("test://syllabus.pdf", "b".repeat(64), "SHA-256",
                        "application/pdf", "syllabus.pdf"),
                1, List.of(new PageInfo(1)), List.of(sections), blocks, List.of(), List.of(),
                List.of(),
                new ExtractionProvenance("synthetic", "1", Instant.EPOCH, Map.of(),
                        "syllabai-parser", CanonicalSchema.VERSION));
    }
}
