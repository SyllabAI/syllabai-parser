package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * A text-bearing block: paragraphs, headings, list items and captions all
 * live in the canonical {@code textBlocks} array, distinguished by
 * {@code role} (additive §8 field, versioned).
 */
public record TextBlockElement(
        @JsonProperty("element_id") String elementId,
        @JsonProperty("element_type") ElementType elementType,
        @JsonProperty("page_number") int pageNumber,
        @JsonProperty("bounding_box") BoundingBox boundingBox,
        @JsonProperty("text") String text,
        @JsonProperty("reading_order") int readingOrder,
        @JsonProperty("confidence") Double confidence,
        @JsonProperty("role") TextRole role,
        @JsonProperty("heading_level") Integer headingLevel,
        @JsonProperty("source_engine") String sourceEngine,
        @JsonProperty("source_engine_version") String sourceEngineVersion)
        implements DocumentElement {

    public TextBlockElement(String elementId, int pageNumber, BoundingBox boundingBox,
                            String text, int readingOrder, Double confidence, TextRole role,
                            Integer headingLevel, String sourceEngine, String sourceEngineVersion) {
        this(elementId, ElementType.TEXT_BLOCK, pageNumber, boundingBox, text,
                readingOrder, confidence, role, headingLevel, sourceEngine, sourceEngineVersion);
    }
}
