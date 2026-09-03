package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * An extracted figure/image reference. The canonical document stores the
 * reference (format, source name, alternative text) — never the image bytes;
 * the source PDF/object storage remains the byte-level truth.
 */
public record FigureElement(
        @JsonProperty("element_id") String elementId,
        @JsonProperty("element_type") ElementType elementType,
        @JsonProperty("page_number") int pageNumber,
        @JsonProperty("bounding_box") BoundingBox boundingBox,
        @JsonProperty("text") String text,
        @JsonProperty("reading_order") int readingOrder,
        @JsonProperty("confidence") Double confidence,
        @JsonProperty("format") String format,
        @JsonProperty("source_name") String sourceName,
        @JsonProperty("alt") String alt,
        @JsonProperty("source_engine") String sourceEngine,
        @JsonProperty("source_engine_version") String sourceEngineVersion)
        implements DocumentElement {

    public FigureElement(String elementId, int pageNumber, BoundingBox boundingBox,
                         int readingOrder, Double confidence, String format, String sourceName,
                         String alt, String sourceEngine, String sourceEngineVersion) {
        this(elementId, ElementType.FIGURE, pageNumber, boundingBox, alt, readingOrder,
                confidence, format, sourceName, alt, sourceEngine, sourceEngineVersion);
    }
}
