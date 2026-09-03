package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.Map;

/**
 * How a canonical document was produced (Master Spec §8 "provenance",
 * §19 reproducibility: parser version must be attributable).
 *
 * @param engine            extraction engine, e.g. "opendataloader-pdf"
 * @param engineVersion     exact engine version, e.g. "2.5.7"
 * @param extractedAt       extraction timestamp
 * @param extractionParams engine options actually used (mode, reading order…)
 * @param application      producing application
 * @param schemaVersion    canonical schema version at write time
 */
public record ExtractionProvenance(
        @JsonProperty("engine") String engine,
        @JsonProperty("engineVersion") String engineVersion,
        @JsonProperty("extractedAt") Instant extractedAt,
        @JsonProperty("extractionParams") Map<String, Object> extractionParams,
        @JsonProperty("application") String application,
        @JsonProperty("schemaVersion") String schemaVersion) {

    public static final String APPLICATION = "syllabai-parser";
}
