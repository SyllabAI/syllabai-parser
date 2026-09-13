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
    public static final String ENGINE_VERSION = "1.2.0"; // 1.2.0: full-Unicode entities (P-9), $$ span decomposition (P-11)

    private static final String MARKDOWN_MIME = "text/markdown";

    private static final Pattern HEADING = Pattern.compile("^(#{1,6})\\s+(.+?)\\s*$");
    private static final Pattern LIST_ITEM = Pattern.compile("^[-*]\\s+(.+)$");
    private static final Pattern IMAGE_LINE = Pattern.compile(
            "^<div[^>]*>\\s*<img\\s+src='([^']+)'(?:\\s+alt='([^']*)')?\\s*/>\\s*</div>\\s*$");
    private static final Pattern CENTER_OPEN = Pattern.compile("^<div\\s+align=[\"']center[\"']>\\s*$");
    private static final Pattern CENTER_CLOSE = Pattern.compile("^</div>\\s*$");
    private static final Pattern DISPLAY_MATH_OPEN = Pattern.compile("^\\$\\$\\s*$");
    private static final Pattern MATH_SPAN = Pattern.compile("\\$\\$(.+?)\\$\\$");
    private static final Pattern TR_TAG = Pattern.compile("<tr[^>]*>(.*?)</tr>", Pattern.DOTALL);
    private static final Pattern CELL_TAG = Pattern.compile("<t[dh][^>]*>(.*?)</t[dh]>", Pattern.DOTALL);
    private static final Pattern ANY_TAG = Pattern.compile("<[^>]+>");
    private static final Pattern BR_TAG = Pattern.compile("<br\\s*/?>", Pattern.CASE_INSENSITIVE);
    private static final Pattern ENTITY = Pattern.compile(
            "&#x([0-9a-fA-F]+);|&#(\\d+);|&gt;|&lt;|&amp;|&quot;|&apos;");

    // ── bounded-block hardening (structural-boundary predicates) ───────────────
    //
    // An unterminated block opener (<table> without </table>, a $$ fence whose
    // closer was lost, a <div align=center> without </div>) must not swallow
    // the rest of the document. The scan stops at lines that can only be
    // block-EXTERNAL content; the opener is counted in provenance and the
    // swallowed span re-parses as normal flow. Predicates mirror the corpus
    // repair heuristics validated against the 82-session IGCSE chemistry
    // corpus (unterminated table ate q1..9 in 2013-Jan; orphan $$ fences ate
    // q3-5/q7-10 in 2016-Jun-R before the corpus-side repair).
    private static final Pattern CELL_HTML = Pattern.compile("<t[dhr]\\b|</t[dhr]>");
    private static final Pattern EQ_OPS = Pattern.compile(
            "[+=]|\\\\rightarrow|\\\\quad|\\\\mathrm|\\\\%");
    private static final Pattern PART_LABEL = Pattern.compile("^\\([a-h]\\)\\s");
    private static final Pattern ROMAN_LABEL = Pattern.compile("^\\([ivx]+\\)\\s");
    private static final Pattern QUESTION_STEM = Pattern.compile("^\\d{1,2}\\s+[A-Za-z]{3,}");
    private static final Pattern TOTAL_LINE = Pattern.compile(
            "^\\(?\\s*Total for (Question|question|paper)", Pattern.CASE_INSENSITIVE);

    /** Certain block-external content: headings, div/img wrappers, tables. */
    static boolean decisive(String s) {
        return s != null && !s.isEmpty()
                && (s.startsWith("#") || s.startsWith("<div")
                || s.startsWith("<table") || s.contains("<img"));
    }

    /** Boundary usable inside MATH spans (equations never look like stems). */
    static boolean structural(String s) {
        if (s == null || s.isEmpty() || CELL_HTML.matcher(s).find()) {
            return false;
        }
        if (decisive(s)) {
            return true;
        }
        if (EQ_OPS.matcher(s).find()) {
            return false;
        }
        return PART_LABEL.matcher(s).find() || ROMAN_LABEL.matcher(s).find()
                || QUESTION_STEM.matcher(s).matches() || TOTAL_LINE.matcher(s).find();
    }

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
        int unterminatedTables = 0;
        int orphanMathFences = 0;
        int unclosedDivs = 0;
        int greedyMathLines = 0;
        int pendingOrphanDivs = 0;

        int i = 0;
        while (i < lines.length) {
            String raw = lines[i];
            String line = raw.endsWith("\r") ? raw.substring(0, raw.length() - 1) : raw;
            String stripped = line.strip();

            if (stripped.isEmpty()) {
                i++;
                continue;
            }

            // a standalone </div> reaching top level closes a dropped orphan
            // div opener; skip it instead of leaking HTML into the text flow
            if (pendingOrphanDivs > 0 && CENTER_CLOSE.matcher(stripped).matches()) {
                pendingOrphanDivs--;
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
                // bounded scan: closer line, or a decisive structural line
                // (heading / div / img / new table) re-parsed as flow, or EOF
                int end = lines.length;
                boolean closed = false;
                int j = i;
                while (j < lines.length) {
                    String s2 = lines[j].strip();
                    if (s2.contains("</table>")) {
                        closed = true;
                        end = j + 1;
                        break;
                    }
                    if (j > i && decisive(s2)) {
                        end = j;
                        break;
                    }
                    j++;
                }
                List<String> htmlLines = new ArrayList<>();
                for (int k = i; k < end; k++) {
                    htmlLines.add(lines[k].strip());
                }
                if (closed) {
                    i = end;
                } else {
                    unterminatedTables++;
                    // keep the last COMPLETE row; trailing partial rows
                    // re-parse as normal flow instead of vanishing into a
                    // bogus table that eats the remaining questions
                    int lastRow = -1;
                    for (int k = i; k < end; k++) {
                        if (lines[k].strip().contains("</tr>")) {
                            lastRow = k;
                        }
                    }
                    if (lastRow >= 0) {
                        htmlLines = new ArrayList<>();
                        for (int k = i; k <= lastRow; k++) {
                            htmlLines.add(lines[k].strip());
                        }
                        i = lastRow + 1;
                    } else {
                        htmlLines = List.of(); // opener with zero rows: nothing to salvage
                        i = i + 1;
                    }
                }
                if (!htmlLines.isEmpty()) {
                    // closed-but-empty tables still emit an element (rows []),
                    // exactly as before; only a dropped unsalvageable opener
                    // (no closer, no complete row) emits nothing
                    GlmOcrMarkdownParser.ParsedTable table =
                            parseHtmlTable(String.join("\n", htmlLines));
                    entityDecodes += table.entityDecodes();
                    tables.add(new TableElement(nextId(textBlocks, tables, figures, equations),
                            1, null, nextOrder(textBlocks, tables, figures, equations), 1.0,
                            table.rows(), ENGINE_NAME, ENGINE_VERSION));
                }
                continue;
            }

            if (CENTER_OPEN.matcher(stripped).matches()) {
                // bounded scan: standalone </div>, a NESTED center opener (a
                // genuinely ambiguous pairing the old scanner mis-consumed),
                // or EOF. Headings / tables / img wrappers are legitimate
                // INNER content of center blocks in this corpus (e.g.
                // "<div align=center># Mark Scheme (Results)</div>") and must
                // not terminate the scan.
                int end = lines.length;
                boolean closed = false;
                int j = i + 1;
                while (j < lines.length) {
                    String s2 = lines[j].strip();
                    if (CENTER_CLOSE.matcher(s2).matches()) {
                        closed = true;
                        end = j;
                        break;
                    }
                    if (CENTER_OPEN.matcher(s2).matches()) {
                        end = j;
                        break;
                    }
                    j++;
                }
                if (!closed) {
                    unclosedDivs++;
                    pendingOrphanDivs++;
                    i = i + 1; // opener dropped; inner lines re-parse as flow
                    continue;
                }
                List<String> inner = new ArrayList<>();
                for (int k = i + 1; k < end; k++) {
                    String innerLine = lines[k].strip();
                    if (!innerLine.isEmpty()) {
                        inner.add(innerLine);
                    }
                }
                i = end + 1; // consume </div>
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
                // bounded scan: the closing $$ line, or a structural line that
                // cannot be equation content, or EOF. An orphan opener is
                // dropped and its span re-parses as normal flow — the old
                // unbounded scan paired it with the NEXT block's opener and
                // swallowed everything between.
                int end = lines.length;
                boolean closed = false;
                int j = i + 1;
                while (j < lines.length) {
                    String s2 = lines[j].strip();
                    if (DISPLAY_MATH_OPEN.matcher(s2).matches()) {
                        closed = true;
                        end = j;
                        break;
                    }
                    if (structural(s2)) {
                        end = j;
                        break;
                    }
                    j++;
                }
                if (!closed) {
                    orphanMathFences++;
                    i = i + 1; // orphan opener dropped; span re-parses as flow
                    continue;
                }
                StringBuilder latex = new StringBuilder();
                for (int k = i + 1; k < end; k++) {
                    latex.append(lines[k].stripTrailing()).append('\n');
                }
                i = end + 1; // closing $$
                equations.add(new EquationElement(
                        nextId(textBlocks, tables, figures, equations), 1, null,
                        latex.toString().stripTrailing(),
                        nextOrder(textBlocks, tables, figures, equations), 1.0,
                        latex.toString().stripTrailing(), ENGINE_NAME, ENGINE_VERSION));
                continue;
            }

            // P-11: a line classified as inline display math must be FULLY covered
            // by lazy $$..$$ spans (whitespace between them allowed) — one equation
            // per span, in order. The old greedy ^\$\$(.+)\$\$$ capture swallowed
            // multiple spans AND the prose between them into one equation whose
            // latex contained literal '$$' markers; such mixed lines now fall
            // through to paragraph flow (raw line preserved for teacher review)
            // and are counted in provenance.
            java.util.List<int[]> mathSpans = mathSpanBounds(stripped);
            if (!mathSpans.isEmpty() && fullyCoveredBySpans(stripped, mathSpans)) {
                for (int[] span : mathSpans) {
                    String content = stripped.substring(span[2], span[3]).strip();
                    equations.add(new EquationElement(
                            nextId(textBlocks, tables, figures, equations), 1, null,
                            content,
                            nextOrder(textBlocks, tables, figures, equations), 1.0,
                            content, ENGINE_NAME, ENGINE_VERSION));
                }
                i++;
                continue;
            }
            if (!mathSpans.isEmpty()) {
                greedyMathLines++;
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
        // honesty counters — present ONLY when non-zero so that clean-input
        // provenance maps stay byte-identical to the pre-hardening engine
        if (unterminatedTables > 0) {
            params.put("unterminatedTableBlocks", unterminatedTables);
        }
        if (orphanMathFences > 0) {
            params.put("orphanMathFences", orphanMathFences);
        }
        if (unclosedDivs > 0) {
            params.put("unclosedCenterDivs", unclosedDivs);
        }
        if (greedyMathLines > 0) {
            params.put("greedyMathLines", greedyMathLines);
        }

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

    /**
     * Strips inner tags, decodes entities, trims outer whitespace, keeps inner
     * newlines. {@code <br>} variants become newlines FIRST — they ARE printed
     * line breaks in the original (e.g. "Paper Reference<br>KCH0/1C 4CH0/1C");
     * dropping them glues separate printed lines into one token soup ("…1C4CH0/1C…")
     * that then defeats every line-based identity regex downstream.
     */
    private static String cleanCell(String rawCell) {
        String brs = BR_TAG.matcher(rawCell).replaceAll("\n");
        String noTags = ANY_TAG.matcher(brs).replaceAll("");
        String decoded = decodeEntities(noTags);
        return decoded.strip();
    }

    /**
     * All non-overlapping lazy {@code $$..$$} spans on a line, outermost-first:
     * {@code {matchStart, matchEnd, contentStart, contentEnd}}. Mirrors the
     * Python reference's {@code _math_spans} exactly (conformance contract).
     */
    private static java.util.List<int[]> mathSpanBounds(String line) {
        Matcher m = MATH_SPAN.matcher(line);
        java.util.List<int[]> spans = new java.util.ArrayList<>();
        while (m.find()) {
            spans.add(new int[]{m.start(), m.end(), m.start(1), m.end(1)});
        }
        return spans;
    }

    /**
     * True when the line is only whitespace outside the matched {@code $$..$$}
     * spans (delimiter-to-delimiter). A line mixing math spans with prose is
     * NOT display math (P-11) and re-parses as paragraph flow.
     */
    private static boolean fullyCoveredBySpans(String line, java.util.List<int[]> spans) {
        int prev = 0;
        for (int[] span : spans) {
            if (!line.substring(prev, span[0]).isBlank()) {
                return false;
            }
            prev = span[1];
        }
        return line.substring(prev).isBlank();
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
                replacement = decodeCodePoint(Integer.parseInt(m.group(1), 16), m.group());
            } else if (m.group(2) != null) {
                replacement = decodeCodePoint(Integer.parseInt(m.group(2)), m.group());
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

    /**
     * P-9: numeric entities decode across the FULL Unicode range — astral
     * plane code points (&#x1D400; and friends) previously truncated to the
     * low 16 bits, producing lone surrogates. Surrogate-range and out-of-range
     * code points stay as the literal entity: a deterministic fail-safe
     * mirrored byte-for-byte in the Python reference.
     */
    private static String decodeCodePoint(int codePoint, String literal) {
        if (codePoint >= 0 && codePoint <= Character.MAX_CODE_POINT
                && !(codePoint >= Character.MIN_SURROGATE && codePoint <= Character.MAX_SURROGATE)) {
            return new String(Character.toChars(codePoint));
        }
        return literal;
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
