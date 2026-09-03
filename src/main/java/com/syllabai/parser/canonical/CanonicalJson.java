package com.syllabai.parser.canonical;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Deterministic JSON codec for the canonical document format. Serialization
 * order follows record declaration order, so re-serializing a parsed document
 * reproduces byte-identical JSON apart from the inherently variable fields
 * (documentId, extractedAt) — the round-trip property the tests pin down.
 */
public final class CanonicalJson {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .enable(SerializationFeature.INDENT_OUTPUT);

    private CanonicalJson() {
    }

    public static String write(CanonicalDocument document) {
        try {
            return MAPPER.writeValueAsString(document);
        } catch (IOException e) {
            throw new UncheckedIOException("canonical document serialization failed", e);
        }
    }

    public static void write(CanonicalDocument document, Path file) {
        try {
            Files.createDirectories(file.getParent());
            Files.writeString(file, write(document), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException("canonical document write failed: " + file, e);
        }
    }

    public static CanonicalDocument read(String json) {
        try {
            return MAPPER.readValue(json, CanonicalDocument.class);
        } catch (IOException e) {
            throw new UncheckedIOException("canonical document parse failed", e);
        }
    }

    public static CanonicalDocument read(Path file) {
        try {
            return read(Files.readString(file, StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new UncheckedIOException("canonical document read failed: " + file, e);
        }
    }

    /** The shared mapper, exposed for structure-draft codecs to stay consistent. */
    public static ObjectMapper mapper() {
        return MAPPER;
    }
}
