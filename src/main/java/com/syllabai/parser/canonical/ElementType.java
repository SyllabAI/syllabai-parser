package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Element type discriminant (Master Spec §8). Values are serialized as
 * {@code text_block}, {@code table}, {@code figure}, {@code equation}.
 */
public enum ElementType {
    @JsonProperty("text_block") TEXT_BLOCK("text_block"),
    @JsonProperty("table") TABLE("table"),
    @JsonProperty("figure") FIGURE("figure"),
    @JsonProperty("equation") EQUATION("equation");

    private final String jsonValue;

    ElementType(String jsonValue) {
        this.jsonValue = jsonValue;
    }

    public String jsonValue() {
        return jsonValue;
    }
}
