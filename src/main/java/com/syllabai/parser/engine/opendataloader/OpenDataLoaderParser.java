package com.syllabai.parser.engine.opendataloader;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.syllabai.parser.canonical.BoundingBox;
import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalSchema;
import com.syllabai.parser.canonical.CanonicalValidator;
import com.syllabai.parser.canonical.Checksums;
import com.syllabai.parser.canonical.EquationElement;
import com.syllabai.parser.canonical.ExtractionProvenance;
import com.syllabai.parser.canonical.FigureElement;
import com.syllabai.parser.canonical.PageInfo;
import com.syllabai.parser.canonical.SectionInfo;
import com.syllabai.parser.canonical.SourceInfo;
import com.syllabai.parser.canonical.TableElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.engine.DocumentParser;
import com.syllabai.parser.engine.ParseFailureException;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.opendataloader.pdf.api.Config;
import org.opendataloader.pdf.api.OpenDataLoaderPDF;

/**
 * T-009: in-process adapter for <strong>opendataloader-pdf</strong>
 * (Apache-2.0, {@code org.opendataloader:opendataloader-pdf-core}), the
 * Wave-1 text-PDF engine (Master Spec §27). Fast (Java-only) mode: no OCR,
 * no hybrid backend, no network. XY-Cut++ reading order. Page boundaries,
 * per-element bounding boxes and heading structure are retained; engine
 * version is resolved from the classpath and recorded in provenance.
 *
 * <p>The engine API is file-in/file-out, so {@link #parse(byte[], String)}
 * stages the bytes in a private temp directory and reads back the generated
 * JSON ({@code input.pdf} → {@code input.json}) before mapping it to the
 * canonical model. Nothing is written outside the temp dir, which is removed
 * afterwards — no production dependency on any local filesystem.</p>
 */
public final class OpenDataLoaderParser implements DocumentParser {

    public static final String ENGINE_NAME = "opendataloader-pdf";

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String PDF_MIME = "application/pdf";

    @Override
    public String engineName() {
        return ENGINE_NAME;
    }

    @Override
    public String engineVersion() {
        return OpenDataLoaderEngineVersion.resolve();
    }

    @Override
    public boolean supports(String mimeType) {
        return PDF_MIME.equalsIgnoreCase(mimeType);
    }

    @Override
    public CanonicalDocument parse(byte[] source, String sourceUri) {
        Path tempDir = null;
        try {
            tempDir = Files.createTempDirectory("syllabai-odl-");
            Path pdfPath = tempDir.resolve("input.pdf");
            Files.write(pdfPath, source);

            Config config = new Config();
            config.setOutputFolder(tempDir.toString());
            config.setGenerateJSON(true);
            config.setGenerateMarkdown(false);
            config.setGenerateText(false);
            config.setGenerateHtml(false);
            config.setReadingOrder(Config.READING_ORDER_XYCUT);
            OpenDataLoaderPDF.processFile(pdfPath.toString(), config);

            Path jsonPath = tempDir.resolve("input.json");
            if (!Files.exists(jsonPath)) {
                throw new ParseFailureException(ENGINE_NAME,
                        "engine produced no JSON output for " + sourceUri, null);
            }
            JsonNode root = JSON.readTree(Files.newInputStream(jsonPath));

            CanonicalDocument document = map(root, source, sourceUri);
            CanonicalValidator.validate(document);
            return document;
        } catch (IOException | RuntimeException e) {
            throw new ParseFailureException(ENGINE_NAME, e.getMessage(), e);
        } finally {
            if (tempDir != null) {
                cleanup(tempDir);
            }
        }
    }

    // ── opendataloader JSON → canonical model ─────────────────────────────────

    private CanonicalDocument map(JsonNode root, byte[] source, String sourceUri) {
        String engineVersion = engineVersion();
        String fileName = root.path("file name").asText(null);
        int pageCount = root.path("number of pages").asInt(0);
        if (pageCount < 1) {
            throw new ParseFailureException(ENGINE_NAME,
                    "engine reported no pages for " + sourceUri, null);
        }

        List<PageInfo> pages = new ArrayList<>();
        for (int p = 1; p <= pageCount; p++) {
            pages.add(new PageInfo(p));
        }

        List<TextBlockElement> textBlocks = new ArrayList<>();
        List<TableElement> tables = new ArrayList<>();
        List<FigureElement> figures = new ArrayList<>();
        List<EquationElement> equations = new ArrayList<>();
        List<String> skippedTypes = new ArrayList<>();

        ReadingOrder order = new ReadingOrder();
        walk(root.path("kids"), order, textBlocks, tables, figures, equations,
                skippedTypes, engineVersion);

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("mode", "fast");
        params.put("readingOrder", "xycut");
        params.put("includeHeaderFooter", false);
        if (!skippedTypes.isEmpty()) {
            params.put("skippedChunkTypes", String.join(", ", skippedTypes));
        }

        CanonicalDocument document = CanonicalDocument.of(
                new SourceInfo(sourceUri, Checksums.sha256Hex(source), "SHA-256",
                        PDF_MIME, fileName),
                pageCount, pages,
                sectionsFromHeadings(textBlocks),
                textBlocks, tables, figures, equations,
                new ExtractionProvenance(ENGINE_NAME, engineVersion, Instant.now(),
                        params, ExtractionProvenance.APPLICATION, CanonicalSchema.VERSION));
        return document;
    }

    /** Depth-first walk of chunk trees; children live under "kids" or "list items". */
    private void walk(JsonNode chunks, ReadingOrder order,
                      List<TextBlockElement> textBlocks, List<TableElement> tables,
                      List<FigureElement> figures, List<EquationElement> equations,
                      List<String> skippedTypes, String engineVersion) {
        if (chunks == null || !chunks.isArray()) {
            return;
        }
        for (JsonNode chunk : chunks) {
            String type = chunk.path("type").asText("");
            switch (type) {
                case "heading", "paragraph", "line", "text block", "list item",
                     "toc item", "caption" -> textBlocks.add(textBlock(chunk, order, engineVersion));
                case "table" -> {
                    tables.add(table(chunk, order, engineVersion));
                    walk(chunk.path("kids"), order, textBlocks, tables, figures,
                            equations, skippedTypes, engineVersion);
                }
                case "image" -> figures.add(figure(chunk, order, engineVersion));
                case "formula" -> equations.add(equation(chunk, order, engineVersion));
                case "list", "toc" -> walk(children(chunk), order, textBlocks, tables,
                        figures, equations, skippedTypes, engineVersion);
                default -> {
                    if (!type.isBlank() && !type.equals("font")) {
                        skippedTypes.add(type);
                    }
                    walk(chunk.path("kids"), order, textBlocks, tables, figures,
                            equations, skippedTypes, engineVersion);
                }
            }
        }
    }

    private JsonNode children(JsonNode chunk) {
        JsonNode kids = chunk.path("kids");
        JsonNode listItems = chunk.path("list items");
        if (listItems.isArray() && !listItems.isEmpty()) {
            return listItems;
        }
        return kids;
    }

    private TextBlockElement textBlock(JsonNode chunk, ReadingOrder order,
                                        String engineVersion) {
        String type = chunk.path("type").asText("");
        TextRole role = switch (type) {
            case "heading" -> TextRole.HEADING;
            case "list item" -> TextRole.LIST_ITEM;
            case "caption" -> TextRole.CAPTION;
            default -> TextRole.PARAGRAPH;
        };
        Integer headingLevel = chunk.hasNonNull("heading level")
                ? chunk.get("heading level").asInt() : null;
        return new TextBlockElement(
                order.nextId(), chunk.path("page number").asInt(1),
                boundingBox(chunk), chunk.path("content").asText(null),
                order.next(), confidence(chunk), role, headingLevel,
                ENGINE_NAME, engineVersion);
    }

    private TableElement table(JsonNode chunk, ReadingOrder order, String engineVersion) {
        List<List<String>> rows = new ArrayList<>();
        for (JsonNode row : chunk.path("rows")) {
            List<String> cells = new ArrayList<>();
            for (JsonNode cell : row.path("cells")) {
                cells.add(cellText(cell));
            }
            rows.add(cells);
        }
        return new TableElement(order.nextId(), chunk.path("page number").asInt(1),
                boundingBox(chunk), order.next(), confidence(chunk), rows,
                ENGINE_NAME, engineVersion);
    }

    /** Cell text is nested: cell → kids → paragraphs/lines carrying "content". */
    private String cellText(JsonNode cell) {
        StringBuilder sb = new StringBuilder();
        collectContent(cell.path("kids"), sb);
        return sb.toString().strip();
    }

    private void collectContent(JsonNode chunks, StringBuilder sb) {
        if (chunks == null || !chunks.isArray()) {
            return;
        }
        for (JsonNode chunk : chunks) {
            JsonNode content = chunk.get("content");
            if (content != null && !content.isNull() && !content.asText().isBlank()) {
                if (sb.length() > 0) {
                    sb.append(' ');
                }
                sb.append(content.asText().strip());
            }
            collectContent(chunk.path("kids"), sb);
        }
    }

    private FigureElement figure(JsonNode chunk, ReadingOrder order, String engineVersion) {
        String alt = chunk.hasNonNull("description") ? chunk.get("description").asText()
                : (chunk.hasNonNull("alt") ? chunk.get("alt").asText() : null);
        return new FigureElement(order.nextId(), chunk.path("page number").asInt(1),
                boundingBox(chunk), order.next(), confidence(chunk),
                chunk.path("format").asText(null), chunk.path("source").asText(null),
                alt, ENGINE_NAME, engineVersion);
    }

    private EquationElement equation(JsonNode chunk, ReadingOrder order,
                                      String engineVersion) {
        String content = chunk.path("content").asText(null);
        return new EquationElement(order.nextId(), chunk.path("page number").asInt(1),
                boundingBox(chunk), content, order.next(), confidence(chunk), content,
                ENGINE_NAME, engineVersion);
    }

    /** Bounding boxes are [x1, y1, x2, y2] in PDF points; absent → null. */
    private BoundingBox boundingBox(JsonNode chunk) {
        JsonNode box = chunk.get("bounding box");
        if (box == null || !box.isArray() || box.size() < 4) {
            return null;
        }
        double x1 = box.get(0).asDouble();
        double y1 = box.get(1).asDouble();
        double x2 = box.get(2).asDouble();
        double y2 = box.get(3).asDouble();
        return BoundingBox.fromCorners(x1, y1, x2, y2);
    }

    /** Digital-text extraction is exact; hybrid engines may report ai_score. */
    private Double confidence(JsonNode chunk) {
        JsonNode score = chunk.get("ai_score");
        if (score != null && score.isNumber()) {
            return score.asDouble();
        }
        return 1.0;
    }

    private List<SectionInfo> sectionsFromHeadings(List<TextBlockElement> textBlocks) {
        List<SectionInfo> sections = new ArrayList<>();
        int sectionCounter = 0;
        SectionBuilder current = null;
        for (TextBlockElement block : textBlocks) {
            boolean isHeading = block.role() == TextRole.HEADING;
            if (isHeading) {
                if (current != null) {
                    sections.add(current.build());
                }
                current = new SectionBuilder("s" + String.format("%03d", ++sectionCounter),
                        block.text(), block.headingLevel() == null ? 1 : block.headingLevel(),
                        block.pageNumber());
            } else if (current != null) {
                current.add(block.elementId());
            }
        }
        if (current != null) {
            sections.add(current.build());
        }
        return sections;
    }

    private static final class SectionBuilder {
        private final String sectionId;
        private final String title;
        private final int level;
        private final int pageNumber;
        private final List<String> elementIds = new ArrayList<>();

        SectionBuilder(String sectionId, String title, int level, int pageNumber) {
            this.sectionId = sectionId;
            this.title = title;
            this.level = level;
            this.pageNumber = pageNumber;
        }

        void add(String elementId) {
            elementIds.add(elementId);
        }

        SectionInfo build() {
            return new SectionInfo(sectionId, title, level, pageNumber, List.copyOf(elementIds));
        }
    }

    private static final class ReadingOrder {
        private int next = 0;

        int next() {
            return next++;
        }

        String nextId() {
            return "e" + String.format("%06d", next);
        }
    }

    private void cleanup(Path tempDir) {
        try (var stream = Files.walk(tempDir)) {
            stream.sorted(java.util.Comparator.reverseOrder())
                    .forEach(p -> {
                        try {
                            Files.delete(p);
                        } catch (IOException ignored) {
                            // best-effort temp cleanup
                        }
                    });
        } catch (IOException ignored) {
            // best-effort temp cleanup
        }
    }

    /** Deterministic ids for tests and tooling that need reproducible documents. */
    public CanonicalDocument parseWithFixedIdentity(byte[] source, String sourceUri,
                                                    UUID documentId, Instant extractedAt) {
        CanonicalDocument parsed = parse(source, sourceUri);
        return new CanonicalDocument(documentId.toString(), parsed.schemaVersion(),
                parsed.version(), parsed.source(), parsed.pageCount(), parsed.pages(),
                parsed.sections(), parsed.textBlocks(), parsed.tables(), parsed.figures(),
                parsed.equations(),
                new ExtractionProvenance(parsed.provenance().engine(),
                        parsed.provenance().engineVersion(), extractedAt,
                        parsed.provenance().extractionParams(),
                        parsed.provenance().application(), parsed.provenance().schemaVersion()));
    }
}
