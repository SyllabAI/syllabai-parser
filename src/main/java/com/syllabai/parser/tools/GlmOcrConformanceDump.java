package com.syllabai.parser.tools;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.glmocr.GlmOcrMarkSchemeExtractor;
import com.syllabai.parser.structure.glmocr.GlmOcrQuestionExtractor;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;

/**
 * Cross-language conformance dump CLI (Session 9). Reads a GLM-OCR Markdown
 * file and prints JSON to stdout for one of three modes:
 *
 * <pre>
 *   doc — canonical document (extractedAt pinned to the epoch for byte-stable comparison)
 *   qp  — question-paper draft
 *   ms  — mark-scheme draft
 * </pre>
 *
 * The Python reference implementation ({@code tools/glmocr/}) produces the
 * same structures; {@code tools/glmocr/conformance.py} diffs them.
 */
public final class GlmOcrConformanceDump {

    private static final Instant EPOCH = Instant.parse("1970-01-01T00:00:00Z");

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: GlmOcrConformanceDump <markdown-file> <doc|qp|ms>");
            System.exit(2);
        }
        byte[] source = Files.readAllBytes(Path.of(args[0]));
        String mode = args[1];
        String uri = "corpus/" + Path.of(args[0]).getFileName();

        GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
        String json;
        switch (mode) {
            case "doc" -> {
                CanonicalDocument document = parser.parseWithFixedIdentity(source, uri, EPOCH);
                json = CanonicalJson.write(document);
            }
            case "qp" -> {
                CanonicalDocument document = parser.parseWithFixedIdentity(source, uri, EPOCH);
                GlmOcrPaperDraft draft = new GlmOcrQuestionExtractor().extract(document);
                json = new ObjectMapper().writeValueAsString(draft);
            }
            case "ms" -> {
                CanonicalDocument document = parser.parseWithFixedIdentity(source, uri, EPOCH);
                GlmOcrMarkSchemeDraft draft = new GlmOcrMarkSchemeExtractor().extract(document);
                json = new ObjectMapper().writeValueAsString(draft);
            }
            default -> {
                System.err.println("unknown mode: " + mode);
                System.exit(2);
                return;
            }
        }
        System.out.println(json);
    }

    private GlmOcrConformanceDump() {
    }
}
