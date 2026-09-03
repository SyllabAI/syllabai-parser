package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.UUID;

/**
 * The canonical, repository-independent normalized document (Master Spec §8).
 * Shape is frozen by the schema version: {@code textBlocks}, {@code tables},
 * {@code figures}, {@code equations} arrays whose members all carry the §8
 * element core. Field naming follows the spec exactly — snake_case element
 * fields, camelCase document-level fields.
 *
 * @param documentId     random UUID identifying this canonical document
 * @param schemaVersion  canonical schema version ("1.0")
 * @param version        document revision (starts at 1; re-ingestion bumps)
 * @param source         origin + checksum
 * @param pageCount      number of source pages
 * @param pages          per-page info (dimensions optional)
 * @param sections       heading-derived sections (heuristic v0)
 * @param textBlocks     paragraphs, headings, list items, captions
 * @param tables         extracted tables
 * @param figures        figure references
 * @param equations      formula elements
 * @param provenance     engine + version + params + timestamp
 */
public record CanonicalDocument(
        @JsonProperty("documentId") String documentId,
        @JsonProperty("schemaVersion") String schemaVersion,
        @JsonProperty("version") int version,
        @JsonProperty("source") SourceInfo source,
        @JsonProperty("pageCount") int pageCount,
        @JsonProperty("pages") List<PageInfo> pages,
        @JsonProperty("sections") List<SectionInfo> sections,
        @JsonProperty("textBlocks") List<TextBlockElement> textBlocks,
        @JsonProperty("tables") List<TableElement> tables,
        @JsonProperty("figures") List<FigureElement> figures,
        @JsonProperty("equations") List<EquationElement> equations,
        @JsonProperty("provenance") ExtractionProvenance provenance) {

    public CanonicalDocument {
        pages = pages == null ? List.of() : List.copyOf(pages);
        sections = sections == null ? List.of() : List.copyOf(sections);
        textBlocks = textBlocks == null ? List.of() : List.copyOf(textBlocks);
        tables = tables == null ? List.of() : List.copyOf(tables);
        figures = figures == null ? List.of() : List.copyOf(figures);
        equations = equations == null ? List.of() : List.copyOf(equations);
    }

    public static CanonicalDocument of(SourceInfo source, int pageCount,
                                       List<PageInfo> pages, List<SectionInfo> sections,
                                       List<TextBlockElement> textBlocks, List<TableElement> tables,
                                       List<FigureElement> figures, List<EquationElement> equations,
                                       ExtractionProvenance provenance) {
        return new CanonicalDocument(UUID.randomUUID().toString(), CanonicalSchema.VERSION,
                1, source, pageCount, pages, sections, textBlocks, tables, figures,
                equations, provenance);
    }

    /** All elements in reading order (stable across containers). */
    public List<DocumentElement> elementsInReadingOrder() {
        List<DocumentElement> all = new java.util.ArrayList<>(textBlocks);
        all.addAll(tables);
        all.addAll(figures);
        all.addAll(equations);
        all.sort(java.util.Comparator.comparingInt(DocumentElement::readingOrder));
        return List.copyOf(all);
    }
}
