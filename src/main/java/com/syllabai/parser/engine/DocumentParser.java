package com.syllabai.parser.engine;

import com.syllabai.parser.canonical.CanonicalDocument;

/**
 * Language-neutral parser contract (Master Spec §27). Implementations are
 * adapters around one extraction engine; the canonical document is the only
 * currency crossing this boundary, so engines can be added, replaced, or
 * routed per document without touching consumers.
 */
public interface DocumentParser {

    /** Engine identity for provenance, e.g. "opendataloader-pdf". */
    String engineName();

    /** Exact engine version for provenance (§19 reproducibility). */
    String engineVersion();

    /** Whether this parser can handle the given MIME type. */
    boolean supports(String mimeType);

    /**
     * Extract the source bytes into a canonical document.
     *
     * @param source     exact document bytes
     * @param sourceUri  provenance URI (R2 key, URL or corpus path)
     * @return the canonical document (validated: schema, ids, reading order)
     * @throws ParseFailureException the engine could not process the bytes
     */
    CanonicalDocument parse(byte[] source, String sourceUri);
}
