package com.syllabai.parser.engine.sme;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalSchema;
import com.syllabai.parser.canonical.CanonicalValidator;
import com.syllabai.parser.canonical.Checksums;
import com.syllabai.parser.canonical.EquationElement;
import com.syllabai.parser.canonical.ElementType;
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
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * T-C06 notes ingestion adapter: Save My Exams revision-note pages (the
 * operator's scraper schema {@code syllabai.sme-revision-note/1.0}) →
 * canonical schema 1.0. Source of truth is the note's Markdown file (YAML
 * front matter + body); the sidecar JSON enriches provenance only and never
 * touches identity or content.
 *
 * <p>House rules honored (see {@code GlmOcrMarkdownParser} for the pattern):
 * deterministic output (same bytes → same ids, same order), pages are honest
 * ({@code pageCount=1}, {@code pageBoundaries=none-in-source}), figures carry
 * the FULL original reference in {@code text} (expired/remote URLs stay
 * reconstructable), and identity is the canonical derivation
 * ({@link CanonicalIdentity}: SHA-256 of the note file + engine + version).</p>
 *
 * <p><strong>Verbatim posture (v1, recorded per note in provenance):</strong>
 * structural Markdown line markers ({@code #}, {@code >}, {@code - / *},
 * image syntax) are decoded into canonical element structure; ALL inline
 * markup is preserved byte-exact — {@code **bold**}, backticks,
 * {@code <sub>/<sup>} HTML, and provider inline LaTeX ({@code $...$}) are
 * never rewritten. The registered "LaTeX→HTML sub/sup normalization" T-C06
 * step is NOT applied inside math fences (it would corrupt provider LaTeX);
 * a notation-normalization map is operator-ratified work, not an adapter
 * decision. Counter: {@code inlineMathCount}.</p>
 *
 * <p><strong>Fail-closed contract</strong> (collected, one rejection lists
 * all): front matter present and closed, all 8 scraper keys present, valid
 * {@code rn_} id, valid ISO-8601 {@code updated_at}; sidecar (when given)
 * schema {@code syllabai.sme-revision-note/1.0} and matching {@code note_id}
 * (wrong-file pairing guard).</p>
 */
public final class SmeRevisionNoteParser implements DocumentParser {

    public static final String ENGINE_NAME = "sme-revision-note";
    /** 1.0.0: initial adapter (T-C06 notes ingestion kickoff, ial-chemistry-17 tranche). */
    public static final String ENGINE_VERSION = "1.0.0";

    private static final String MARKDOWN_MIME = "text/markdown";
    private static final String SIDECAR_SCHEMA = "syllabai.sme-revision-note/1.0";
    private static final Pattern FRONT_OPEN = Pattern.compile("^---\\s*$");
    private static final Pattern HEADING = Pattern.compile("^(#{1,6})\\s+(.+?)\\s*$");
    private static final Pattern QUOTE = Pattern.compile("^>\\s?(.*)$");
    private static final Pattern LIST_ITEM = Pattern.compile("^[-*]\\s+(.+)$");
    private static final Pattern IMAGE = Pattern.compile("^!\\[([^\\]]*)\\]\\(([^)\\s]+)\\)\\s*$");
    private static final Pattern TABLE_ROW = Pattern.compile("^\\|.*\\|\\s*$");
    private static final Pattern TABLE_SEP = Pattern.compile("^\\|(\\s*:?-{3,}:?\\s*\\|)+\\s*$");
    private static final Pattern NOTE_ID = Pattern.compile("^rn_[A-Za-z0-9]+$");
    private static final List<String> REQUIRED_KEYS = List.of(
            "note_id", "title", "source", "path", "updated_at",
            "spec_point_ids", "spec_point_codes", "guided_study");

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
        return parseWithExtractedAt(source, sourceUri, Instant.now());
    }

    /** Deterministic-output variant for reproducible batch pipelines and tests. */
    public CanonicalDocument parseWithExtractedAt(byte[] source, String sourceUri,
                                                  Instant extractedAt) {
        return convert(source, sourceUri, null, extractedAt);
    }

    /**
     * Sidecar-enriched parse: merges the scraper's per-note JSON (authors,
     * reviewers, display titles, stats) into provenance params — verbatim
     * provider facts, identity untouched (identity derives from the note
     * file checksum only). Fails closed on schema mismatch or note_id
     * disagreement (wrong-file pairing guard).
     */
    public CanonicalDocument parseWithSidecar(byte[] source, String sourceUri,
                                              byte[] sidecarJson, Instant extractedAt) {
        return convert(source, sourceUri, sidecarJson, extractedAt);
    }

    private CanonicalDocument convert(byte[] source, String sourceUri, byte[] sidecarJson,
                                      Instant extractedAt) {
        try {
            String text = new String(source, StandardCharsets.UTF_8);
            Parsed parsed = parseFrontMatter(text);
            Map<String, Object> params = parsed.params();
            if (sidecarJson != null) {
                mergeSidecar(new String(sidecarJson, StandardCharsets.UTF_8),
                        unquote(parsed.frontMatter().get("note_id")), params);
            }
            params.put("sourceLineCount", text.split("\n", -1).length);
            params.put("pageBoundaries", "none-in-source");
            params.put("notationNormalization", "verbatim-v1-no-notation-rewrites");

            Emit emit = parseBody(parsed.body());
            params.put("inlineMathCount", countInlineMath(parsed.body()));
            params.put("figureCount", emit.figures.size());
            params.put("specPointMarkerCount", emit.specPointMarkers);
            if (sourceUri != null && !sourceUri.isBlank()) {
                params.put("noteFile", sourceUri);
            }

            String fileName = sourceUri == null ? null
                    : sourceUri.substring(Math.max(sourceUri.lastIndexOf('/'),
                            sourceUri.lastIndexOf('\\')) + 1);

            CanonicalDocument document = CanonicalDocument.of(
                    new SourceInfo(parsed.frontMatter().get("source"),
                            Checksums.sha256Hex(source), "SHA-256", MARKDOWN_MIME, fileName),
                    1, List.of(new PageInfo(1)),
                    sectionsFrom(emit),
                    emit.textBlocks, emit.tables, emit.figures, emit.equations,
                    new ExtractionProvenance(ENGINE_NAME, ENGINE_VERSION, extractedAt, params,
                            ExtractionProvenance.APPLICATION, CanonicalSchema.VERSION));
            CanonicalValidator.validate(document);
            return document;
        } catch (IllegalArgumentException e) {
            throw new ParseFailureException(ENGINE_NAME, e.getMessage(), e);
        }
    }

    // ── front matter ──────────────────────────────────────────────────────────

    private record Parsed(Map<String, String> frontMatter, Map<String, Object> params,
                          String body) {
    }

    private Parsed parseFrontMatter(String text) {
        List<String> violations = new ArrayList<>();
        String[] lines = text.split("\n", -1);
        if (lines.length == 0 || !FRONT_OPEN.matcher(lines[0].strip()).matches()) {
            throw new IllegalArgumentException(
                    "front matter missing (note files must open with '---')");
        }
        int close = -1;
        for (int i = 1; i < lines.length; i++) {
            if (FRONT_OPEN.matcher(lines[i].strip()).matches()) {
                close = i;
                break;
            }
        }
        if (close < 0) {
            throw new IllegalArgumentException("front matter not closed with '---'");
        }
        Map<String, String> fm = new LinkedHashMap<>();
        Set<String> extraKeys = new LinkedHashSet<>();
        for (int i = 1; i < close; i++) {
            String line = lines[i];
            if (line.isBlank()) {
                continue;
            }
            int colon = line.indexOf(':');
            if (colon <= 0) {
                violations.add("front-matter line without 'key:': " + line.strip());
                continue;
            }
            String key = line.substring(0, colon).strip();
            String value = line.substring(colon + 1).strip();
            if (fm.putIfAbsent(key, value) != null) {
                violations.add("duplicate front-matter key: " + key);
            }
        }
        for (String required : REQUIRED_KEYS) {
            if (!fm.containsKey(required)) {
                violations.add("missing required front-matter key: " + required);
            }
        }
        if (!violations.isEmpty()) {
            throw new IllegalArgumentException(String.join("; ", violations));
        }
        if (!NOTE_ID.matcher(unquote(fm.get("note_id"))).matches()) {
            throw new IllegalArgumentException("note_id format unexpected: "
                    + fm.get("note_id") + " (expected rn_<alphanumeric>)");
        }
        try {
            Instant.parse(unquote(fm.get("updated_at")));
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("updated_at is not ISO-8601: "
                    + fm.get("updated_at"));
        }
        for (String key : fm.keySet()) {
            if (!REQUIRED_KEYS.contains(key)) {
                extraKeys.add(key);
            }
        }

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("noteId", unquote(fm.get("note_id")));
        params.put("notePath", unquote(fm.get("path")));
        params.put("noteUpdatedAt", unquote(fm.get("updated_at")));
        params.put("guidedStudy", Boolean.parseBoolean(unquote(fm.get("guided_study"))));
        params.put("specPointIds", splitList(fm.get("spec_point_ids")));
        params.put("specPointCodes", splitList(fm.get("spec_point_codes")));
        if (!extraKeys.isEmpty()) {
            params.put("frontMatterExtraKeys", List.copyOf(extraKeys));
        }
        String body = String.join("\n", Arrays.copyOfRange(lines, close + 1, lines.length));
        return new Parsed(fm, params, body);
    }

    private static String unquote(String value) {
        String v = value.strip();
        if (v.length() >= 2 && v.startsWith("\"") && v.endsWith("\"")) {
            return v.substring(1, v.length() - 1);
        }
        return v;
    }

    /** Inline scraper list: {@code ["a", "b"]} → [a, b]; empty/[] → []. */
    private static List<String> splitList(String value) {
        String v = unquote(value);
        if (v.startsWith("[") && v.endsWith("]")) {
            String inner = v.substring(1, v.length() - 1).strip();
            if (inner.isEmpty()) {
                return List.of();
            }
            List<String> out = new ArrayList<>();
            for (String part : inner.split(",")) {
                out.add(unquote(part));
            }
            return List.copyOf(out);
        }
        return v.isEmpty() ? List.of() : List.of(v);
    }

    // ── body flow → canonical elements ────────────────────────────────────────

    private static final class Emit {
        final List<TextBlockElement> textBlocks = new ArrayList<>();
        final List<TableElement> tables = new ArrayList<>();
        final List<FigureElement> figures = new ArrayList<>();
        final List<EquationElement> equations = new ArrayList<>();
        final List<String> emissionOrder = new ArrayList<>();
        int specPointMarkers;

        int total() {
            return textBlocks.size() + tables.size() + figures.size() + equations.size();
        }
    }

    private Emit parseBody(String body) {
        Emit emit = new Emit();
        StringBuilder paragraph = new StringBuilder();
        List<String> tableLines = new ArrayList<>();
        String[] lines = body.split("\n", -1);

        for (String raw : lines) {
            String line = raw.strip();
            if (line.isEmpty()) {
                tableLines = flushTable(emit, tableLines);
                paragraph = flushParagraph(emit, paragraph);
                continue;
            }
            if (TABLE_ROW.matcher(line).matches()) {
                tableLines.add(line);
                continue;
            }
            if (!tableLines.isEmpty()) {
                tableLines = flushTable(emit, tableLines);
            }
            Matcher heading = HEADING.matcher(line);
            if (heading.matches()) {
                paragraph = flushParagraph(emit, paragraph);
                String text = heading.group(2);
                String id = nextId(emit);
                emit.textBlocks.add(new TextBlockElement(id, 1, null, text,
                        emit.total(), 1.0, TextRole.HEADING, heading.group(1).length(),
                        ENGINE_NAME, ENGINE_VERSION));
                emit.emissionOrder.add(id);
                continue;
            }
            Matcher image = IMAGE.matcher(line);
            if (image.matches()) {
                paragraph = flushParagraph(emit, paragraph);
                figure(emit, image.group(2), image.group(1));
                continue;
            }
            Matcher quote = QUOTE.matcher(line);
            if (quote.matches()) {
                paragraph = flushParagraph(emit, paragraph);
                String inner = quote.group(1);
                if (inner.contains("**Spec point**")) {
                    emit.specPointMarkers++;
                }
                String id = nextId(emit);
                emit.textBlocks.add(new TextBlockElement(id, 1, null, inner,
                        emit.total(), 1.0, TextRole.PARAGRAPH, null,
                        ENGINE_NAME, ENGINE_VERSION));
                emit.emissionOrder.add(id);
                continue;
            }
            Matcher listItem = LIST_ITEM.matcher(line);
            if (listItem.matches()) {
                paragraph = flushParagraph(emit, paragraph);
                String text = listItem.group(1);
                String id = nextId(emit);
                emit.textBlocks.add(new TextBlockElement(id, 1, null, text,
                        emit.total(), 1.0, TextRole.LIST_ITEM, null,
                        ENGINE_NAME, ENGINE_VERSION));
                emit.emissionOrder.add(id);
                continue;
            }
            // plain prose: soft-join consecutive lines into one paragraph block
            if (paragraph.length() > 0) {
                paragraph.append('\n');
            }
            paragraph.append(line);
        }
        flushTable(emit, tableLines);
        flushParagraph(emit, paragraph);
        return emit;
    }

    private void figure(Emit emit, String ref, String alt) {
        String path = ref;
        String format = null;
        int dot = path.lastIndexOf('.');
        int slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
        if (dot > slash && dot < path.length() - 1) {
            format = path.substring(dot + 1);
        }
        String sourceName = slash >= 0 && slash < path.length() - 1
                ? path.substring(slash + 1) : path;
        String id = nextId(emit);
        // the house rule for third-party figure refs: text carries the COMPLETE
        // original reference (remote/relative paths both stay reconstructable)
        emit.figures.add(new FigureElement(
                id, ElementType.FIGURE, 1, null, ref,
                emit.total(), 1.0, format, sourceName, alt, ENGINE_NAME, ENGINE_VERSION));
        emit.emissionOrder.add(id);
    }

    private StringBuilder flushParagraph(Emit emit, StringBuilder paragraph) {
        if (paragraph.length() > 0) {
            String text = paragraph.toString();
            String id = nextId(emit);
            emit.textBlocks.add(new TextBlockElement(id, 1, null, text,
                    emit.total(), 1.0, TextRole.PARAGRAPH, null,
                    ENGINE_NAME, ENGINE_VERSION));
            emit.emissionOrder.add(id);
        }
        return new StringBuilder();
    }

    private List<String> flushTable(Emit emit, List<String> tableLines) {
        if (tableLines.isEmpty()) {
            return tableLines;
        }
        List<List<String>> rows = new ArrayList<>();
        for (String line : tableLines) {
            if (TABLE_SEP.matcher(line).matches()) {
                continue;
            }
            String inner = line.substring(1, line.lastIndexOf('|'));
            List<String> cells = new ArrayList<>();
            for (String cell : inner.split("\\|", -1)) {
                cells.add(cell.strip());
            }
            rows.add(List.copyOf(cells));
        }
        if (!rows.isEmpty()) {
            String id = nextId(emit);
            emit.tables.add(new TableElement(id, 1, null,
                    emit.total(), 1.0, rows, ENGINE_NAME, ENGINE_VERSION));
            emit.emissionOrder.add(id);
        }
        return new ArrayList<>();
    }

    private static int countInlineMath(String body) {
        int count = 0;
        boolean inside = false;
        for (int i = 0; i < body.length(); i++) {
            if (body.charAt(i) == '$' && (i == 0 || body.charAt(i - 1) != '\\')) {
                inside = !inside;
                if (!inside) {
                    count++;
                }
            }
        }
        return count;
    }

    private String nextId(Emit emit) {
        return "e" + String.format("%06d", emit.total());
    }

    // ── sections (every heading opens one; ALL element types attach) ──────────

    private List<SectionInfo> sectionsFrom(Emit emit) {
        Map<String, TextBlockElement> byId = new LinkedHashMap<>();
        for (TextBlockElement block : emit.textBlocks) {
            byId.put(block.elementId(), block);
        }
        List<SectionInfo> sections = new ArrayList<>();
        int counter = 0;
        SectionBuilder current = null;
        for (String elementId : emit.emissionOrder) {
            TextBlockElement block = byId.get(elementId);
            if (block != null && block.role() == TextRole.HEADING) {
                if (current != null) {
                    sections.add(current.build());
                }
                current = new SectionBuilder("s" + String.format("%03d", ++counter),
                        block.text(), block.headingLevel() == null ? 1 : block.headingLevel(), 1);
            }
            if (current != null) {
                current.add(elementId);
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

    // ── sidecar enrichment (provenance-only; pairing-guarded) ─────────────────

    @SuppressWarnings("unchecked")
    private void mergeSidecar(String sidecarText, String expectedNoteId,
                              Map<String, Object> params) {
        Map<String, Object> sidecar;
        try {
            sidecar = CanonicalJsonHolder.MAPPER.readValue(sidecarText,
                    new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {
                    });
        } catch (java.io.IOException e) {
            throw new IllegalArgumentException(
                    "sidecar JSON is not parseable: " + e.getMessage());
        }
        Object schema = sidecar.get("schema");
        if (!SIDECAR_SCHEMA.equals(schema)) {
            throw new IllegalArgumentException("sidecar schema " + schema
                    + " != " + SIDECAR_SCHEMA);
        }
        Object noteId = sidecar.get("note_id");
        if (!expectedNoteId.equals(noteId)) {
            throw new IllegalArgumentException("sidecar note_id " + noteId
                    + " does not match note front matter " + expectedNoteId);
        }
        putIfNotNull(params, "courseSlug", sidecar.get("course_slug"));
        putIfNotNull(params, "sidecarIsAiAssisted", sidecar.get("is_ai_assisted"));
        Object titles = sidecar.get("titles");
        if (titles instanceof Map<?, ?> t) {
            putIfNotNull(params, "sidecarSectionTitle", t.get("section"));
            putIfNotNull(params, "sidecarTopicTitle", t.get("topic"));
            putIfNotNull(params, "sidecarSubtopicTitle", t.get("subtopic"));
        }
        params.put("sidecarAuthors", names(sidecar.get("authors")));
        params.put("sidecarReviewers", names(sidecar.get("reviewers")));
        Object stats = sidecar.get("stats");
        if (stats instanceof Map<?, ?> s) {
            params.put("sidecarStats", String.valueOf(s));
        }
        Object equations = sidecar.get("equations");
        if (equations instanceof List<?> eq) {
            params.put("sidecarEquationCount", eq.size());
        }
    }

    private static void putIfNotNull(Map<String, Object> params, String key, Object value) {
        if (value != null) {
            params.put(key, value);
        }
    }

    private static List<String> names(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof Map<?, ?> m && m.get("name") != null) {
                out.add(String.valueOf(m.get("name")));
            }
        }
        return List.copyOf(out);
    }

    /** Lazy shared mapper (the canonical JSON codec's mapper, for consistency). */
    private static final class CanonicalJsonHolder {
        private static final com.fasterxml.jackson.databind.ObjectMapper MAPPER =
                com.syllabai.parser.canonical.CanonicalJson.mapper();
    }
}
