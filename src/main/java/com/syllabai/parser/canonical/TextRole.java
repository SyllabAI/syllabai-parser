package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Structural role of a text block within the page flow (additive to the
 * Master Spec §8 minimum fields; versioned by the schema version). Engines
 * that detect headings or list structure report it here so the syllabus
 * structuring heuristics can use it without re-parsing.
 */
public enum TextRole {
    @JsonProperty("paragraph") PARAGRAPH("paragraph"),
    @JsonProperty("heading") HEADING("heading"),
    @JsonProperty("list_item") LIST_ITEM("list_item"),
    @JsonProperty("caption") CAPTION("caption");

    private final String jsonValue;

    TextRole(String jsonValue) {
        this.jsonValue = jsonValue;
    }

    public String jsonValue() {
        return jsonValue;
    }
}
