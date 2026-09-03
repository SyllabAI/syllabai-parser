package com.syllabai.parser.canonical;

/**
 * Version of the canonical document format (Master Spec §8). Bump on any
 * breaking shape change; additive optional fields bump the minor part.
 * Consumers must refuse documents whose schemaVersion they do not understand.
 */
public final class CanonicalSchema {

    public static final String VERSION = "1.0";

    private CanonicalSchema() {
    }
}
