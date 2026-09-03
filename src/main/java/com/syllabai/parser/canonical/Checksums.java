package com.syllabai.parser.canonical;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Checksum helpers for source provenance (§19: exact bytes must be verifiable). */
public final class Checksums {

    private Checksums() {
    }

    /** SHA-256 of the given bytes as lowercase hex. */
    public static String sha256Hex(byte[] bytes) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
