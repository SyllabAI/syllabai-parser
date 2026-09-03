package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * A detected document section (derived from heading elements in reading
 * order). v0 heuristic: a heading opens a section at its level; the section
 * owns every element until the next heading of level &le; its own.
 *
 * @param sectionId  stable id, e.g. "s001"
 * @param title      heading text
 * @param level      heading depth (1 = top)
 * @param pageNumber page the heading appears on
 * @param elementIds ordered element ids belonging to this section
 */
public record SectionInfo(
        @JsonProperty("sectionId") String sectionId,
        @JsonProperty("title") String title,
        @JsonProperty("level") int level,
        @JsonProperty("pageNumber") int pageNumber,
        @JsonProperty("elementIds") List<String> elementIds) {
}
