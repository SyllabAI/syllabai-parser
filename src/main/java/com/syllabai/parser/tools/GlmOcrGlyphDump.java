package com.syllabai.parser.tools;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.syllabai.parser.structure.glmocr.PuaNormalizer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * T-MIG-141 Phase E glyph-conformance dump CLI. Reads the canonical table
 * (arg 0) and an input text (arg 1), runs the normalization + the born-clean
 * census, and prints JSON to stdout:
 *
 * <pre>
 * { "normalized": "...", "censusPre": {...}, "censusPost": {...},
 *   "idempotenceDelta": 0, "tableSha256": "...", "canary": "C-intake-zero-pua" }
 * </pre>
 *
 * The Python reference ({@code tools/glmocr/normalize_pua.py}) produces the
 * same fields; the glyph leg of {@code tools/glmocr/conformance.py} diffs
 * them byte-exactly across the 16 glyph fixture classes.
 */
public final class GlmOcrGlyphDump {

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: GlmOcrGlyphDump <table.v1.json> <input-file>");
            System.exit(2);
        }
        PuaNormalizer normalizer = PuaNormalizer.load(Path.of(args[0]));
        String text = Files.readString(Path.of(args[1]), StandardCharsets.UTF_8);

        Map<String, Object> censusPre = normalizer.census(text);
        String normalized = normalizer.normalize(text);
        Map<String, Object> censusPost = normalizer.census(normalized);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("normalized", normalized);
        out.put("censusPre", censusPre);
        out.put("censusPost", censusPost);
        out.put("idempotenceDelta", normalizer.idempotenceDelta(text));
        out.put("tableSha256", normalizer.tableSha256());
        out.put("canary", normalizer.canary());
        System.out.println(new ObjectMapper().writeValueAsString(out));
    }

    private GlmOcrGlyphDump() {
    }
}
