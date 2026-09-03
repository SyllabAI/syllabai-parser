package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * An extracted mathematical formula (LaTeX representation when the engine
 * provides one — hybrid OCR engines; null for text-only engines).
 */
public record EquationElement(
        @JsonProperty("element_id") String elementId,
        @JsonProperty("element_type") ElementType elementType,
        @JsonProperty("page_number") int pageNumber,
        @JsonProperty("bounding_box") BoundingBox boundingBox,
        @JsonProperty("text") String text,
        @JsonProperty("reading_order") int readingOrder,
        @JsonProperty("confidence") Double confidence,
        @JsonProperty("latex") String latex,
        @JsonProperty("source_engine") String sourceEngine,
        @JsonProperty("source_engine_version") String sourceEngineVersion)
        implements DocumentElement {

    public EquationElement(String elementId, int pageNumber, BoundingBox boundingBox,
                           String text, int readingOrder, Double confidence, String latex,
                           String sourceEngine, String sourceEngineVersion) {
        this(elementId, ElementType.EQUATION, pageNumber, boundingBox, text, readingOrder,
                confidence, latex, sourceEngine, sourceEngineVersion);
    }
}
