package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Where the processed document came from and how to verify it is the same
 * bytes (Master Spec §8 "source", §19 reproducibility).
 *
 * @param uri               source locator (R2 key, URL, or corpus-relative path)
 * @param checksum          hex digest of the exact processed bytes
 * @param checksumAlgorithm digest algorithm, e.g. "SHA-256"
 * @param mimeType          e.g. application/pdf
 * @param fileName          original file name when known (informational)
 */
public record SourceInfo(
        @JsonProperty("uri") String uri,
        @JsonProperty("checksum") String checksum,
        @JsonProperty("checksumAlgorithm") String checksumAlgorithm,
        @JsonProperty("mimeType") String mimeType,
        @JsonProperty("fileName") String fileName) {
}
