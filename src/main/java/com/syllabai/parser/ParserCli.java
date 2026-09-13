package com.syllabai.parser;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.engine.opendataloader.OpenDataLoaderParser;
import com.syllabai.parser.structure.EdexcelSyllabusOutlineExtractor;
import com.syllabai.parser.structure.PastPaperStructureExtractor;
import com.syllabai.parser.structure.SyllabusStructureExtractor;
import com.syllabai.parser.structure.dto.CurriculumDraft;
import com.syllabai.parser.structure.dto.PastPaperDraft;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

/**
 * Content-operations workbench entry point (offline; not part of any
 * deployed runtime). Two modes:
 *
 * <pre>
 *   syllabai QP &lt;pdf&gt; &lt;out-dir&gt; [MS-pdf] [--paper board|qual|subject|unit|session|code]
 *   syllabai SYLLABUS &lt;pdf&gt; &lt;out-dir&gt; --curriculum board|qual|code|title|subjectCode|subjectName
 *                          [--extractor outline|heuristic]
 * </pre>
 *
 * Writes canonical document JSON plus the matching ingestion draft JSON for
 * syllabai-core's ingestion API. SYLLABUS default extractor: outline (deterministic
 * Edexcel-numbered patterns, T-010); heuristic keeps the generic level-based v0.
 */
public final class ParserCli {

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("""
                    usage:
                      syllabai QP <pdf> <out-dir> [ms-pdf] [--paper board|qualification|subject|unit|session|code]
                      syllabai SYLLABUS <pdf> <out-dir> --curriculum board|qualification|code|title|subjectCode|subjectName
                    """);
            System.exit(2);
        }
        String mode = args[0].toUpperCase(Locale.ROOT);
        Path pdf = Path.of(args[1]);
        Path outDir = Path.of(args[2]);
        OpenDataLoaderParser parser = new OpenDataLoaderParser();

        switch (mode) {
            case "QP" -> {
                Path msPdf = args.length > 3 && !args[3].isBlank()
                        && !args[3].startsWith("--") ? Path.of(args[3]) : null;
                String board = "Edexcel";
                String qualification = "IGCSE";
                String subject = "Chemistry";
                String unit = "";
                String session = "";
                String code = "";
                for (int i = 3; i < args.length; i++) {
                    // P-12: unknown flags used to be silently ignored (a typo'd
                    // --extractor silently ran the default) — fail loud now.
                    if (args[i].startsWith("--paper")) {
                        String value = flagValue(args[i], "--paper".length());
                        if (value.isBlank()) {
                            System.err.println("--paper requires a board|qualification|subject|"
                                    + "unit|session|code value");
                            System.exit(2);
                        }
                        String[] parts = value.split("\\|");
                        if (parts.length > 0) board = parts[0];
                        if (parts.length > 1) qualification = parts[1];
                        if (parts.length > 2) subject = parts[2];
                        if (parts.length > 3) unit = parts[3];
                        if (parts.length > 4) session = parts[4];
                        if (parts.length > 5) code = parts[5];
                    } else if (args[i].startsWith("--")) {
                        System.err.println("unknown flag: " + args[i]);
                        System.exit(2);
                    }
                }
                CanonicalDocument qp = parser.parse(Files.readAllBytes(pdf), pdf.getFileName().toString());
                CanonicalJson.write(qp, outDir.resolve("canonical-qp.json"));
                CanonicalDocument ms = msPdf == null ? null
                        : parser.parse(Files.readAllBytes(msPdf), msPdf.getFileName().toString());
                if (ms != null) {
                    CanonicalJson.write(ms, outDir.resolve("canonical-ms.json"));
                }
                PastPaperDraft draft = new PastPaperStructureExtractor()
                        .extract(qp, ms, board, qualification, subject, unit, session, code);
                Files.writeString(outDir.resolve("past-paper-draft.json"),
                        CanonicalJson.mapper().writeValueAsString(draft), StandardCharsets.UTF_8);
                System.out.println("questions: " + draft.questions().size()
                        + (draft.markScheme() == null ? "" : "; mark points: "
                        + draft.markScheme().points().size()));
            }
            case "SYLLABUS" -> {
                String board = "Edexcel";
                String qualification = "IAL";
                String code = "";
                String title = "";
                String subjectCode = "";
                String subjectName = "";
                String extractor = "outline";
                for (int i = 3; i < args.length; i++) {
                    if (args[i].startsWith("--curriculum")) {
                        String value = flagValue(args[i], "--curriculum".length());
                        if (value.isBlank()) {
                            System.err.println("--curriculum requires a board|qualification|"
                                    + "code|title|subjectCode|subjectName value");
                            System.exit(2);
                        }
                        String[] parts = value.split("\\|");
                        if (parts.length > 0) board = parts[0];
                        if (parts.length > 1) qualification = parts[1];
                        if (parts.length > 2) code = parts[2];
                        if (parts.length > 3) title = parts[3];
                        if (parts.length > 4) subjectCode = parts[4];
                        if (parts.length > 5) subjectName = parts[5];
                    } else if (args[i].startsWith("--extractor=")) {
                        extractor = args[i].substring("--extractor=".length());
                    } else if (args[i].startsWith("--")) {
                        // P-12: a space-form --extractor outline used to be ignored
                        // silently, running the default extractor
                        System.err.println("unknown flag: " + args[i]
                                + " (--extractor requires the = form)");
                        System.exit(2);
                    }
                }
                CanonicalDocument syllabus = parser.parse(Files.readAllBytes(pdf),
                        pdf.getFileName().toString());
                CanonicalJson.write(syllabus, outDir.resolve("canonical-syllabus.json"));
                CurriculumDraft draft = switch (extractor) {
                    case "heuristic" -> new SyllabusStructureExtractor()
                            .extract(syllabus, board, qualification, code, title,
                                    subjectCode, subjectName);
                    case "outline" -> new EdexcelSyllabusOutlineExtractor()
                            .extract(syllabus, board, qualification, code, title,
                                    subjectCode, subjectName);
                    default -> throw new IllegalArgumentException(
                            "unknown extractor: " + extractor + " (outline|heuristic)");
                };
                Files.writeString(outDir.resolve("curriculum-draft.json"),
                        CanonicalJson.mapper().writeValueAsString(draft), StandardCharsets.UTF_8);
                System.out.println("units: " + draft.units().size() + "; topics: "
                        + draft.units().stream().mapToInt(u -> u.topics().size()).sum()
                        + " (extractor: " + extractor + ")");
            }
            default -> {
                System.err.println("unknown mode: " + args[0]);
                System.exit(2);
            }
        }
    }

    /** flag value, tolerating an '=' separator ("--curriculum=X" == "--curriculumX") */
    private static String flagValue(String arg, int flagLength) {
        String rest = arg.substring(flagLength);
        return rest.startsWith("=") ? rest.substring(1) : rest;
    }

    private ParserCli() {
    }
}
