package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * One page of the source document. Dimensions are optional: engines that do
 * not report page geometry leave them null and downstream code must not
 * depend on them.
 */
public record PageInfo(
        @JsonProperty("pageNumber") int pageNumber,
        @JsonProperty("width") Double width,
        @JsonProperty("height") Double height) {

    public PageInfo(int pageNumber) {
        this(pageNumber, null, null);
    }
}
