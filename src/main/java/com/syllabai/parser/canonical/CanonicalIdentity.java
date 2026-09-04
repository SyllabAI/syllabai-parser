package com.syllabai.parser.canonical;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.UUID;

/**
 * Deterministic canonical document identity (Session 9, Master Spec §19).
 *
 * <p>{@code CanonicalDocument.of} used to mint {@code UUID.randomUUID()},
 * which made the canonical pipeline non-reproducible: parsing the same
 * source bytes twice produced two unrelated documents. This class moves
 * identity derivation to the canonical layer so every engine — GLM-OCR
 * Markdown, OpenDataLoader PDF, future adapters — derives ids the same
 * way.</p>
 *
 * <p><strong>Formula</strong> (stable, must match the Python reference
 * implementation in {@code tools/glmocr/} for cross-language
 * conformance):</p>
 *
 * <ol>
 *   <li>identity material: UTF-8 bytes of
 *       {@code "sha256:<checksum>|engine:<engine>|version:<engineVersion>"} —
 *       all three components lowercased and stripped; null treated as "";</li>
 *   <li>{@code documentId = UUID(version-5 layout, first 128 bits of
 *       SHA-256(material))} — version nibble 5, RFC-4122 variant bits,
 *       identical bit layout to a name-based UUID;</li>
 *   <li>no random component and no timestamp ever enters the id
 *       ({@code extractedAt} stays a provenance fact of the run, outside
 *       identity).</li>
 * </ol>
 *
 * <p>Consequences: the same source bytes parsed by the same engine at the
 * same version always yield the same {@code documentId}; re-extraction by a
 * newer engine version intentionally yields a new identity, so consumers can
 * distinguish "same parse" from "re-parse".</p>
 */
public final class CanonicalIdentity {

    private CanonicalIdentity() {
    }

    /**
     * Deterministic document id from the source checksum (hex), engine name
     * and engine version. Same inputs → same id, always.
     */
    public static String contentDocumentId(String sourceChecksumHex, String engine,
                                           String engineVersion) {
        String material = "sha256:" + component(sourceChecksumHex)
                + "|engine:" + component(engine)
                + "|version:" + component(engineVersion);
        byte[] hash = sha256(material.getBytes(StandardCharsets.UTF_8));
        byte[] uuidBytes = new byte[16];
        System.arraycopy(hash, 0, uuidBytes, 0, 16);
        uuidBytes[6] = (byte) ((uuidBytes[6] & 0x0f) | 0x50); // version 5
        uuidBytes[8] = (byte) ((uuidBytes[8] & 0x3f) | 0x80); // RFC 4122 variant
        ByteBuffer buffer = ByteBuffer.wrap(uuidBytes);
        return new UUID(buffer.getLong(), buffer.getLong()).toString();
    }

    /** Convenience: hash the exact source bytes first, then derive the id. */
    public static String contentDocumentId(byte[] sourceBytes, String engine,
                                           String engineVersion) {
        return contentDocumentId(Checksums.sha256Hex(sourceBytes), engine, engineVersion);
    }

    private static String component(String value) {
        return value == null ? "" : value.strip().toLowerCase(java.util.Locale.ROOT);
    }

    private static byte[] sha256(byte[] data) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(data);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
