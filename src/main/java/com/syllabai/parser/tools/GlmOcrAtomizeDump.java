package com.syllabai.parser.tools;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrPaperExport;
import com.syllabai.parser.structure.glmocr.GlmOcrPaperAtomizer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;

/**
 * Cross-language conformance dump for the atomizer's export shape (OCR-Q4).
 * Reads a QP/MS markdown pair, runs the Java production atomizer, and prints
 * the {@code paper.json} export JSON to stdout:
 *
 * <pre>
 *   java -cp ... com.syllabai.parser.tools.GlmOcrAtomizeDump &lt;qp.md&gt; &lt;ms.md&gt;
 * </pre>
 *
 * <p>Both documents are parsed with the epoch-fixed identity (same
 * convention as {@link GlmOcrConformanceDump}) so the comparison against the
 * Python reference ({@code tools/glmocr/conformance.py}, atomize stage) is
 * byte-stable. The export itself only carries content-derived provenance
 * (documentId, checksum), so it is identity-independent.</p>
 */
public final class GlmOcrAtomizeDump {

    private static final Instant EPOCH = Instant.parse("1970-01-01T00:00:00Z");

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: GlmOcrAtomizeDump <qp.md> <ms.md>");
            System.exit(2);
        }
        Path qpFile = Path.of(args[0]);
        Path msFile = Path.of(args[1]);
        String qpUri = "corpus/" + qpFile.getFileName();
        String msUri = "corpus/" + msFile.getFileName();

        GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
        CanonicalDocument qpDoc = parser.parseWithFixedIdentity(
                Files.readAllBytes(qpFile), qpUri, EPOCH);
        CanonicalDocument msDoc = parser.parseWithFixedIdentity(
                Files.readAllBytes(msFile), msUri, EPOCH);

        GlmOcrPaperExport export =
                new GlmOcrPaperAtomizer().atomize(qpDoc, msDoc, qpUri, msUri);
        System.out.println(new ObjectMapper().writeValueAsString(export));
    }

    private GlmOcrAtomizeDump() {
    }
}
