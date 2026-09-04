package com.syllabai.parser.structure.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * Ingestion draft for a syllabus/specification document (T-010 input):
 * canonical document → curriculum hierarchy → (in syllabai-core) curriculum tables
 * + knowledge-graph seed. v1.1 adds per-node provenance (source element ids, page,
 * extraction confidence) so every KG node derived from a draft can cite the exact
 * spec element it came from (Master Spec §7/§17); drafts are always SUGGESTED and
 * never silently validated.
 *
 * @param schemaVersion draft schema version ("1.1")
 * @param board         e.g. "Edexcel"
 * @param qualification e.g. "IAL"
 * @param code          curriculum code, e.g. "IAL-CHEM-2018"
 * @param title         curriculum title
 * @param subject       subject code + name
 * @param units         unit → topics hierarchy
 * @param provenance    source linkage + extraction method
 */
public record CurriculumDraft(
        @JsonProperty("schemaVersion") String schemaVersion,
        @JsonProperty("board") String board,
        @JsonProperty("qualification") String qualification,
        @JsonProperty("code") String code,
        @JsonProperty("title") String title,
        @JsonProperty("subject") SubjectDraft subject,
        @JsonProperty("units") List<UnitDraft> units,
        @JsonProperty("provenance") DraftProvenance provenance) {

    public static final String SCHEMA_VERSION = "1.1";

    /**
     * @param code subject code, e.g. "CH" — must be unique in a curriculum
     * @param name subject display name
     */
    public record SubjectDraft(
            @JsonProperty("code") String code,
            @JsonProperty("name") String name) {
    }

    /**
     * @param code      unit code, e.g. "U1"
     * @param title     unit title (cleaned heading text)
     * @param topics    topics of the unit
     * @param sourceSectionId  canonical section the heading opened (stable §17 citation;
     *                   complete even when the section owns no further elements)
     * @param sourceElementIds canonical elements the section owns (§17 provenance)
     * @param pageNumber 1-based spec page of the heading (null when unknown)
     * @param confidence extraction confidence 0..1 (1.0 = human-authored; lower for
     *                   pattern/heuristic extraction — documented per method)
     */
    public record UnitDraft(
            @JsonProperty("code") String code,
            @JsonProperty("title") String title,
            @JsonProperty("topics") List<TopicDraft> topics,
            @JsonProperty("sourceSectionId") String sourceSectionId,
            @JsonProperty("sourceElementIds") List<String> sourceElementIds,
            @JsonProperty("pageNumber") Integer pageNumber,
            @JsonProperty("confidence") double confidence) {
    }

    /**
     * @param code      topic code, e.g. "U1-T1" (hierarchical) or subtopic "U1-T3-C"
     * @param title     topic title (trimmed section heading)
     * @param subtopics nested subtopics (empty when the spec has none at this level)
     * @param sourceSectionId  canonical section the heading opened (stable §17 citation)
     * @param sourceElementIds canonical elements the section owns
     * @param pageNumber 1-based spec page of the heading (null when unknown)
     * @param confidence extraction confidence 0..1
     */
    public record TopicDraft(
            @JsonProperty("code") String code,
            @JsonProperty("title") String title,
            @JsonProperty("subtopics") List<TopicDraft> subtopics,
            @JsonProperty("sourceSectionId") String sourceSectionId,
            @JsonProperty("sourceElementIds") List<String> sourceElementIds,
            @JsonProperty("pageNumber") Integer pageNumber,
            @JsonProperty("confidence") double confidence) {
    }

    /**
     * @param sourceDocumentId canonical documentId of the syllabus
     * @param sourceChecksum   its checksum (verbatim provenance, §19)
     * @param engine           extraction engine
     * @param engineVersion    extraction engine version
     * @param extractionMethod e.g. "edexcel-numbered-outline-v1" / "heading-heuristic-v0"
     * @param validationStatus always "SUGGESTED" from the parser
     */
    public record DraftProvenance(
            @JsonProperty("sourceDocumentId") String sourceDocumentId,
            @JsonProperty("sourceChecksum") String sourceChecksum,
            @JsonProperty("engine") String engine,
            @JsonProperty("engineVersion") String engineVersion,
            @JsonProperty("extractionMethod") String extractionMethod,
            @JsonProperty("validationStatus") String validationStatus) {
    }
}
