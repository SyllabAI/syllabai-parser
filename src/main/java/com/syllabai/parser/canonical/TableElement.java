package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * An extracted table. Cell text only — visual structure beyond the row/column
 * grid (spans, headers) is not represented in v1.0 of the canonical format.
 */
public record TableElement(
        @JsonProperty("element_id") String elementId,
        @JsonProperty("element_type") ElementType elementType,
        @JsonProperty("page_number") int pageNumber,
        @JsonProperty("bounding_box") BoundingBox boundingBox,
        @JsonProperty("text") String text,
        @JsonProperty("reading_order") int readingOrder,
        @JsonProperty("confidence") Double confidence,
        @JsonProperty("rows") List<List<String>> rows,
        @JsonProperty("row_count") Integer rowCount,
        @JsonProperty("column_count") Integer columnCount,
        @JsonProperty("source_engine") String sourceEngine,
        @JsonProperty("source_engine_version") String sourceEngineVersion)
        implements DocumentElement {

    public TableElement(String elementId, int pageNumber, BoundingBox boundingBox,
                        int readingOrder, Double confidence, List<List<String>> rows,
                        String sourceEngine, String sourceEngineVersion) {
        this(elementId, ElementType.TABLE, pageNumber, boundingBox, joinRows(rows),
                readingOrder, confidence, rows == null ? List.of() : rows,
                rows == null ? 0 : rows.size(),
                rows == null || rows.isEmpty() ? 0 : rows.get(0).size(),
                sourceEngine, sourceEngineVersion);
    }

    private static String joinRows(List<List<String>> rows) {
        if (rows == null || rows.isEmpty()) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        for (List<String> row : rows) {
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append(String.join(" | ", row));
        }
        return sb.toString();
    }
}
