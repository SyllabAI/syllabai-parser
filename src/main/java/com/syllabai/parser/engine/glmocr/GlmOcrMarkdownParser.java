package com.syllabai.parser.engine.glmocr;

import com.syllabai.parser.canonical.BoundingBox;
import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalIdentity;
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
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * GLM-OCR Markdown adapter (Session 8, real-corpus syntax report §6).
 *
 * <p>Parses the Markdown emitted by Z.ai GLM OCR for past papers and mark
 * schemes into the canonical document format. The real corpus
 * ({@code Past-Papers/GLM-markdown-sample/}) uses: Markdown headings and
 * paragraphs, raw-HTML image divs (signed expiring URLs), single- and
 * multi-line HTML tables, centered {@code <div align="center">} blocks (per-
 * part marks, option letters, labels), and {@code $$} display-math blocks.
 * Documented OCR defects (spaced digits, undelimited LaTeX in cells, HTML
 * entities, glued words) are preserved as-is; only HTML-entity decoding is
 * normalized and it is recorded in provenance params.</p>
 *
 * <p><strong>Page honesty:</strong> the Markdown carries no page boundaries,
 * so {@code pageCount=1} with provenance {@code pageBoundaries=none-in-source}
 * — pages are never invented.</p>
 *
 * <p><strong>Determinism:</strong> the {@code documentId} is derived at the
 * canonical identity layer ({@link CanonicalIdentity}: SHA-256 of source
 * checksum + engine name + engine version, name-based UUID layout) and
 * element ids are positional ({@code e%06d}) in reading order, so parsing
 * the same bytes twice with the same engine version yields identical ids
 * and ordering. {@code extractedAt} remains a provenance fact of the run;
 * use {@link #parseWithFixedIdentity} for byte-reproducible output.</p>
 */
public final class GlmOcrMarkdownParser implements DocumentParser {

    public static final String ENGINE_NAME = "glm-ocr-markdown";
    public static final String ENGINE_VERSION = "1.0.0";

    private static final String MARKDOWN_MIME = "text/markdown";

    private static final Pattern HEADING = Pattern.compile("^(#{1,6})\\s+(.+?)\\s*$");
    private static final Pattern LIST_ITEM = Pattern.compile("^[-*]\\s+(.+)$");
    private static final Pattern IMAGE_LINE = Pattern.compile(
            "^<div[^>]*>\\s*<img\\s+src='([^']+)'(?:\\s+alt='([^']*)')?\\s*/>\\s*</div>\\s*$");
    private static final Pattern CENTER_OPEN = Pattern.compile("^<div\\s+align=[\"']center[\"']>\\s*$");
    private static final Pattern CENTER_CLOSE = Pattern.compile("^</div>\\s*$");
    private static final Pattern DISPLAY_MATH_OPEN = Pattern.compile("^\\$\\$\\s*$");
    private static final Pattern INLINE_DISPLAY_MATH = Pattern.compile("^\\$\\$(.+)\\$\\$\\s*$");
    private static final Pattern TR_TAG = Pattern.compile("<tr[^>]*>(.*?)</tr>", Pattern.DOTALL);
    private static final Pattern CELL_TAG = Pattern.compile("<t[dh][^>]*>(.*?)</t[dh]>", Pattern.DOTALL);
    private static final Pattern ANY_TAG = Pattern.compile("<[^>]+>");
    private static final Pattern ENTITY = Pattern.compile(
            "&#x([0-9a-fA-F]+);|&#(\\d+);|&gt;|&lt;|&amp;|&quot;|&apos;");

    @Override
    public String engineName() {
        return ENGINE_NAME;
    }

    @Override
    public String engineVersion() {
        return ENGINE_VERSION;
    }

    @Override
    public boolean supports(String mimeType) {
        return MARKDOWN_MIME.equalsIgnoreCase(mimeType)
                || "text/x-markdown".equalsIgnoreCase(mimeType);
    }

    @Override
    public CanonicalDocument parse(byte[] source, String sourceUri) {
        try {
            String text = new String(source, StandardCharsets.UTF_8);
            CanonicalDocument document = build(text, source, sourceUri, Instant.now());
            CanonicalValidator.validate(document);
            return document;
        } catch (RuntimeException e) {
            throw new ParseFailureException(ENGINE_NAME, e.getMessage(), e);
        }
    }
    /** Deterministic-output variant for reproducible pipelines and tests. */
    public CanonicalDocument parseWithFixedIdentity(byte[] source, String sourceUri,
                                                    Instant extractedAt) {
        CanonicalDocument parsed = parse(source, sourceUri);
        return new CanonicalDocument(parsed.documentId(), parsed.schemaVersion(),
                parsed.version(), parsed.source(), parsed.pageCount(), parsed.pages(),
                parsed.sections(), parsed.textBlocks(), parsed.tables(), parsed.figures(),
                parsed.equations(),
                new ExtractionProvenance(parsed.provenance().engine(),
                        parsed.provenance().engineVersion(), extractedAt,
                        parsed.provenance().extractionParams(),
                        parsed.provenance().application(),
                        parsed.provenance().schemaVersion()));
    }

    // ── markdown → canonical model ─────────────────────────────────────────────

    private CanonicalDocument build(String text, byte[] source, String sourceUri,
                                    Instant extractedAt) {
        String[] lines = text.split("\n", -1);

        List<TextBlockElement> textBlocks = new ArrayList<>();
        List<TableElement> tables = new ArrayList<>();
        List<FigureElement> figures = new ArrayList<>();
        List<EquationElement> equations = new ArrayList<>();

        int signedUrlRefs = 0;
        int entityDecodes = 0;

        int i = 0;
        while (i < lines.length) {
            String raw = lines[i];
            String line = raw.endsWith("\r") ? raw.substring(0, raw.length() - 1) : raw;
            String stripped = line.strip();

            if (stripped.isEmpty()) {
                i++;
                continue;
            }

            Matcher image = IMAGE_LINE.matcher(stripped);
            if (image.matches()) {
                String url = image.group(1);
                String alt = image.group(2) == null ? "" : image.group(2);
                figures.add(figure(url, alt, textBlocks, tables, figures, equations));
                if (url.contains("Signature=") && url.contains("Expires=")) {
                    signedUrlRefs++;
                }
                i++;
                continue;
            }

            if (stripped.startsWith("<table")) {
                StringBuilder html = new StringBuilder(stripped);
                while (!stripped.contains("</table>") && i + 1 < lines.length) {
                    i++;
                    stripped = lines[i].strip();
                    html.append('\n').append(stripped);
                }
                GlmOcrMarkdownParser.ParsedTable table = parseHtmlTable(html.toString());
                entityDecodes += table.entityDecodes();
                tables.add(new TableElement(nextId(textBlocks, tables, figures, equations),
                        1, null, nextOrder(textBlocks, tables, figures, equations), 1.0,
                        table.rows(), ENGINE_NAME, ENGINE_VERSION));
                i++;
                continue;
            }

            if (CENTER_OPEN.matcher(stripped).matches()) {
                i++;
                List<String> inner = new ArrayList<>();
                while (i < lines.length && !CENTER_CLOSE.matcher(lines[i].strip()).matches()) {
                    String innerLine = lines[i].strip();
                    if (!innerLine.isEmpty()) {
                        inner.add(innerLine);
                    }
                    i++;
                }
                i++; // consume </div>
                for (String innerLine : inner) {
                    Matcher innerHeading = HEADING.matcher(innerLine);
                    if (innerHeading.matches()) {
                        textBlocks.add(textBlock(innerHeading.group(2), TextRole.HEADING,
                                innerHeading.group(1).length(), textBlocks, tables, figures,
                                equations));
                    } else {
                        textBlocks.add(textBlock(decodeEntities(innerLine), TextRole.PARAGRAPH,
                                null, textBlocks, tables, figures, equations));
                    }
                }
                continue;
            }

            if (DISPLAY_MATH_OPEN.matcher(stripped).matches()) {
                StringBuilder latex = new StringBuilder();
                i++;
                while (i < lines.length && !DISPLAY_MATH_OPEN.matcher(lines[i].strip()).matches()) {
                    latex.append(lines[i].stripTrailing()).append('\n');
                    i++;
                }
                i++; // closing $$
                equations.add(new EquationElement(
                        nextId(textBlocks, tables, figures, equations), 1, null,
                        latex.toString().stripTrailing(),
                        nextOrder(textBlocks, tables, figures, equations), 1.0,
                        latex.toString().stripTrailing(), ENGINE_NAME, ENGINE_VERSION));
                continue;
            }

            Matcher inlineMath = INLINE_DISPLAY_MATH.matcher(stripped);
            if (inlineMath.matches()) {
                equations.add(new EquationElement(
                        nextId(textBlocks, tables, figures, equations), 1, null,
                        inlineMath.group(1).strip(),
                        nextOrder(textBlocks, tables, figures, equations), 1.0,
                        inlineMath.group(1).strip(), ENGINE_NAME, ENGINE_VERSION));
                i++;
                continue;
            }

            Matcher heading = HEADING.matcher(stripped);
            if (heading.matches()) {
                textBlocks.add(textBlock(heading.group(2), TextRole.HEADING,
                        heading.group(1).length(), textBlocks, tables, figures, equations));
                i++;
                continue;
            }

            Matcher listItem = LIST_ITEM.matcher(stripped);
            if (listItem.matches()) {
                textBlocks.add(textBlock(listItem.group(1), TextRole.LIST_ITEM, null,
                        textBlocks, tables, figures, equations));
                i++;
                continue;
            }

            textBlocks.add(textBlock(decodeEntities(stripped), TextRole.PARAGRAPH, null,
                    textBlocks, tables, figures, equations));
            if (ENTITY.matcher(stripped).find()) {
                entityDecodes++;
            }
            i++;
        }

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("upstreamConverter", "zai-glm-ocr");
        params.put("pageBoundaries", "none-in-source");
        params.put("normalizedHtmlEntities", true);
        params.put("entityDecodedLines", entityDecodes);
        params.put("signedUrlFigureRefs", signedUrlRefs);
        params.put("sourceLineCount", lines.length);

        String fileName = sourceUri == null ? null
                : sourceUri.substring(Math.max(sourceUri.lastIndexOf('/'),
                        sourceUri.lastIndexOf('\\')) + 1);

        return CanonicalDocument.of(
                new SourceInfo(sourceUri, Checksums.sha256Hex(source), "SHA-256",
                        MARKDOWN_MIME, fileName),
                1, List.of(new PageInfo(1)),
                sectionsFromHeadings(textBlocks),
                textBlocks, tables, figures, equations,
                new ExtractionProvenance(ENGINE_NAME, ENGINE_VERSION, extractedAt, params,
                        ExtractionProvenance.APPLICATION, CanonicalSchema.VERSION));
    }

    // ── element helpers ────────────────────────────────────────────────────────

    private TextBlockElement textBlock(String text, TextRole role, Integer headingLevel,
                                       List<TextBlockElement> textBlocks,
                                       List<TableElement> tables, List<FigureElement> figures,
                                       List<EquationElement> equations) {
        return new TextBlockElement(nextId(textBlocks, tables, figures, equations), 1, null,
                text, nextOrder(textBlocks, tables, figures, equations), 1.0, role,
                headingLevel, ENGINE_NAME, ENGINE_VERSION);
    }

    /**
     * Figure element: {@code text} preserves the full original URL (the only
     * complete reference), {@code sourceName} is the decoded URL path (the
     * durable crop identity), {@code format} the path extension, {@code alt}
     * the upstream alt text (the constant Chinese "OCR图片").
     */
    private FigureElement figure(String url, String alt, List<TextBlockElement> textBlocks,
                                 List<TableElement> tables, List<FigureElement> figures,
                                 List<EquationElement> equations) {
        String path = urlPath(url);
        String format = path == null ? null
                : path.contains(".") ? path.substring(path.lastIndexOf('.') + 1) : null;
        // Full record constructor: text carries the COMPLETE original URL
        // (the only complete reference for expired signed URLs — Session 9
        // image-reality rule); the convenience constructor would copy alt
        // into text and silently drop the URL.
        return new FigureElement(nextId(textBlocks, tables, figures, equations),
                com.syllabai.parser.canonical.ElementType.FIGURE, 1, null, url,
                nextOrder(textBlocks, tables, figures, equations), 1.0, format, path, alt,
                ENGINE_NAME, ENGINE_VERSION);
    }

    /** Decoded URL path; falls back to the raw string on malformed input. */
    private String urlPath(String url) {
        try {
            java.net.URI uri = java.net.URI.create(url);
            String path = uri.getPath();
            return path == null ? url : path;
        } catch (RuntimeException e) {
            return url;
        }
    }

    private String nextId(List<TextBlockElement> textBlocks, List<TableElement> tables,
                          List<FigureElement> figures, List<EquationElement> equations) {
        return "e" + String.format("%06d",
                textBlocks.size() + tables.size() + figures.size() + equations.size());
    }

    private int nextOrder(List<TextBlockElement> textBlocks, List<TableElement> tables,
                          List<FigureElement> figures, List<EquationElement> equations) {
        return textBlocks.size() + tables.size() + figures.size() + equations.size();
    }

    private List<SectionInfo> sectionsFromHeadings(List<TextBlockElement> textBlocks) {
        List<SectionInfo> sections = new ArrayList<>();
        int sectionCounter = 0;
        SectionBuilder current = null;
        for (TextBlockElement block : textBlocks) {
            if (block.role() == TextRole.HEADING) {
                if (current != null) {
                    sections.add(current.build());
                }
                current = new SectionBuilder("s" + String.format("%03d", ++sectionCounter),
                        block.text(), block.headingLevel() == null ? 1 : block.headingLevel(), 1);
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

    // ── HTML table parsing ─────────────────────────────────────────────────────

    record ParsedTable(List<List<String>> rows, int entityDecodes) {
    }

    /**
     * Flat HTML table parser for the corpus shapes: {@code <tr>/<td>/<th>} with
     * multi-line cell content, rowspan/colspan attributes (spans are recorded
     * in raw HTML but not expanded — v1 canonical tables carry the grid only),
     * and HTML entities decoded deterministically.
     */
    static ParsedTable parseHtmlTable(String html) {
        List<List<String>> rows = new ArrayList<>();
        int decodes = 0;
        Matcher rowMatcher = TR_TAG.matcher(html);
        while (rowMatcher.find()) {
            String rowHtml = rowMatcher.group(1);
            List<String> cells = new ArrayList<>();
            Matcher cellMatcher = CELL_TAG.matcher(rowHtml);
            while (cellMatcher.find()) {
                String cell = cellMatcher.group(1);
                if (ENTITY.matcher(cell).find()) {
                    decodes++;
                }
                cells.add(cleanCell(cell));
            }
            if (!cells.isEmpty()) {
                rows.add(cells);
            }
        }
        return new ParsedTable(rows, decodes);
    }

    /** Strips inner tags, decodes entities, trims outer whitespace, keeps inner newlines. */
    private static String cleanCell(String rawCell) {
        String noTags = ANY_TAG.matcher(rawCell).replaceAll("");
        String decoded = decodeEntities(noTags);
        return decoded.strip();
    }

    /** Deterministic HTML-entity decoding (the one normalization this adapter performs). */
    static String decodeEntities(String text) {
        if (text == null || !text.contains("&")) {
            return text;
        }
        Matcher m = ENTITY.matcher(text);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String replacement;
            if (m.group(1) != null) {
                replacement = String.valueOf((char) Integer.parseInt(m.group(1), 16));
            } else if (m.group(2) != null) {
                replacement = String.valueOf((char) Integer.parseInt(m.group(2)));
            } else {
                replacement = switch (m.group()) {
                    case "&gt;" -> ">";
                    case "&lt;" -> "<";
                    case "&amp;" -> "&";
                    case "&quot;" -> "\"";
                    case "&apos;" -> "'";
                    default -> m.group();
                };
            }
            m.appendReplacement(sb, Matcher.quoteReplacement(replacement));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    // ── deterministic identity ─────────────────────────────────────────────────

    /**
     * Content-derived document id via the canonical identity layer — thin
     * pass-through kept for callers; derivation lives in
     * {@link CanonicalIdentity} (checksum + engine + engine version).
     */
    static String contentDocumentId(byte[] source) {
        return CanonicalIdentity.contentDocumentId(source, ENGINE_NAME, ENGINE_VERSION);
    }
}
