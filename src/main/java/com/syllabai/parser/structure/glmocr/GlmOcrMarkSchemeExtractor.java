package com.syllabai.parser.structure.glmocr;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.DocumentElement;
import com.syllabai.parser.canonical.TableElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.GuidanceLine;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.IcTable;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkPoint;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft.MarkSchemeEntry;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PaperMeta;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * GLM-OCR mark-scheme extractor (Session 9, syntax report §4).
 *
 * <p>Table-first: every non-boilerplate HTML table is a mark-scheme block.
 * Row shapes handled: header rows ({@code Question Number | Answer |
 * [Additional Guidance] | Mark}, 3–5 columns), label rows
 * ({@code 11}, {@code 13(a)}, {@code *14} in cell 0), two-level label rows
 * (the "Question number" column spanning two cells: {@code 7 | (a)(i)} —
 * T-C04 repair), continuation-label rows (cell 0 is a bare sub-part label
 * such as {@code (ii)}, {@code (iii)}, {@code (b)(i)}, {@code (c)} — a new
 * sub-part of the current question, T-C04 repair), rowspan continuation
 * rows (label and/or marks deferred), in-table total rows
 * ({@code Total for question 12}), embedded IC tables, and the QWC
 * structure rubric. Standalone {@code (Total for Question N=X marks)} lines
 * between tables (June/1A export) are read from text blocks.</p>
 *
 * <p><strong>Honesty:</strong> marks cells that are empty (rowspan-deferred)
 * stay {@code null} — never summed or guessed; both total placements are
 * recorded and a conflict produces a warning, never a silent fix; every
 * entry carries {@code reviewRequired=true} and confidence &lt; 1.0.</p>
 */
public final class GlmOcrMarkSchemeExtractor {

    public static final String EXTRACTION_METHOD = "glm-ocr-ms-v1";

    private static final Pattern LABEL = Pattern.compile(
            "^(\\*?)(\\d{1,2})\\s*((?:\\([a-h]\\))?(?:\\([ivx]+\\))?)\\s*$");
    /** cell 0 of a continuation-label row: "(ii)", "(iii)", "(b)(i)", "(c)" */
    private static final Pattern CONT_LABEL = Pattern.compile(
            "^(?:\\([a-h]\\))?(?:\\([ivx]+\\))+$|^(?:\\([a-h]\\))$");
    /** cell 1 of a two-level label row: "(a)(i)", "(b)", "a (i)" (spaced) */
    private static final Pattern SUB_LABEL = Pattern.compile(
            "^(?:\\([a-h]\\))(?:\\([ivx]+\\))?$|^[a-h]\\s*\\([ivx]+\\)$");
    /** captures the letter and roman of a continuation label, e.g. "(b)(ii)";
     * both groups optional, at least one required (null-null guarded in code) */
    private static final Pattern CONT_LABEL_PARTS = Pattern.compile(
            "^(?:(\\([a-h]\\)))?(?:(\\([ivx]+\\)))?$");
    private static final Pattern TOTAL_IN_TABLE = Pattern.compile(
            "(?i)^total for question\\s*(\\d{1,2})\\s*$");
    private static final Pattern TOTAL_STANDALONE = Pattern.compile(
            "[Tt]otal for [Qq]uestion\\s*(\\d{1,2})\\s*=?\\s*(\\d{1,3})\\s*marks?");
    private static final Pattern PAPER_TOTAL_IN_LINE = Pattern.compile(
            "(?i)total for paper\\s*=?\\s*(\\d{1,3})\\s*marks?");
    private static final Pattern MCQ_ANSWER = Pattern.compile(
            "The only correct answer is\\s*([A-D])\\b");
    private static final Pattern MARKER = Pattern.compile("\\((\\d{1,2})\\)");
    private static final Pattern DEPENDENT_ON = Pattern.compile(
            "(?i)dependent on\\s+([^)]*)");
    private static final Pattern MP_REF = Pattern.compile("\\bMP\\s?(\\d+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern PAPER_REF = Pattern.compile("\\b(W[A-Z]{2}\\d{2}/\\d{1,2}[A-Z]?)\\b");
    private static final Pattern LOG_NUMBER = Pattern.compile(
            "(?i)log\\s+number\\s+(P\\d{5,6}[A-Z])\\b");
    private static final Pattern PUBLICATION_CODE = Pattern.compile(
            "(?i)publications?\\s+code\\s+(\\S+)");
    private static final Pattern SESSION_LINE = Pattern.compile(
            "(?i)^(Summer|Autumn|Winter|January|February|March|April|May|June|July|August|"
                    + "September|October|November|December)\\s+20\\d{2}$");
    private static final Pattern IC_HEADER_CELL = Pattern.compile(
            "(?i)^(ic points|number of indicative marking points.*)$");
    private static final Pattern IC_VALUE = Pattern.compile("^\\d{1,2}([\\u2013\\u2014-]\\d{1,2})?$");
    private static final Pattern BARE_INT = Pattern.compile("^\\d{1,3}$");
    private static final Pattern BOILERPLATE_HEADING = Pattern.compile(
            "(?i)^(edexcel and btec|pearson|general marking|mark scheme notes|underlying principle|"
                    + "1\\. mark scheme|2\\. unit error|3\\. significant|4\\. calculations|"
                    + "5\\. quality of written).*$");

    public GlmOcrMarkSchemeDraft extract(CanonicalDocument markScheme) {
        State state = new State(markScheme.documentId());
        for (DocumentElement element : markScheme.elementsInReadingOrder()) {
            if (element instanceof TableElement table) {
                handleTable(table, state);
            } else if (element instanceof TextBlockElement block) {
                handleTextLine(block.text(), state);
            }
        }
        closeEntry(state);
        return new GlmOcrMarkSchemeDraft(GlmOcrMarkSchemeDraft.SCHEMA_VERSION,
                EXTRACTION_METHOD, true, paperMeta(markScheme, state), state.entries,
                stringTotals(state.totals), state.paperTotal, state.icTable == null ? null : state.icTable,
                state.warnings);
    }

    // ── state ──────────────────────────────────────────────────────────────────

    private static final class State {
        final String docId;
        final List<MarkSchemeEntry> entries = new ArrayList<>();
        final Map<Integer, Integer> totals = new LinkedHashMap<>();
        final List<String> warnings = new ArrayList<>();
        final List<List<String>> icRows = new ArrayList<>();
        final String[] meta = new String[7]; // board, qual, subject, paperRef, session, date, duration
        String logNumber;
        String publicationCode;
        Integer paperTotal;
        IcTable icTable;
        RawEntry current;
        boolean inIcBlock;
        String icLocation;
        /** last part letter seen in the current question ("b" of "2(b)(i)");
         * letter context for bare-roman continuation labels */
        String lastPartLetter;

        State(String docId) {
            this.docId = docId;
        }
    }

    private static final class RawEntry {
        final String entryId;
        final String label;
        final int number;
        final boolean qwc;
        final StringBuilder answerText = new StringBuilder();
        final List<MarkPoint> markPoints;
        final List<GuidanceLine> guidance = new ArrayList<>();
        Integer marks;
        String marksCellSource;

        RawEntry(String entryId, String label, int number, boolean qwc,
                 List<MarkPoint> markPoints, String initialAnswer) {
            this.entryId = entryId;
            this.label = label;
            this.number = number;
            this.qwc = qwc;
            this.markPoints = markPoints;
            this.answerText.append(initialAnswer);
        }
    }

    // ── table handling ────────────────────────────────────────────────────────

    private void handleTable(TableElement table, State state) {
        state.inIcBlock = false;
        for (List<String> row : table.rows()) {
            handleRow(row, state);
        }
        state.inIcBlock = false;
        finalizeIcBlock(state);
        closeEntry(state); // each table completes its entries (rowspan continuations never cross tables)
    }

    private void finalizeIcBlock(State state) {
        if (!state.icRows.isEmpty() && state.icTable == null) {
            state.icTable = new IcTable(List.copyOf(state.icRows),
                    state.icLocation == null ? "standalone" : state.icLocation);
            state.icRows.clear();
        }
    }

    private void handleRow(List<String> row, State state) {
        List<String> cells = stripCells(row);
        if (cells.isEmpty()) {
            return;
        }

        // IC header (standalone table or embedded in the QWC question)
        if (cells.size() >= 3 && IC_HEADER_CELL.matcher(cells.get(0).strip()).matches()) {
            state.inIcBlock = true;
            if (state.icTable == null) {
                state.icLocation = state.current == null ? "standalone" : "embedded";
            } else if (state.current != null) {
                state.warnings.add("duplicate IC table header at " + labelOf(state));
            }
            return;
        }
        if (state.inIcBlock && allIcValues(cells)) {
            state.icRows.add(cells);
            return;
        }
        if (state.inIcBlock) {
            state.inIcBlock = false; // first non-value row exits the IC block
            finalizeIcBlock(state);
        }

        // header row
        if (cells.get(0).strip().equalsIgnoreCase("Question Number")) {
            return;
        }

        // in-table total row: any cell "Total for question N" + trailing mark cell
        for (String cell : cells) {
            Matcher total = TOTAL_IN_TABLE.matcher(cell.strip());
            if (total.matches()) {
                Integer mark = trailingInteger(cells);
                recordTotal(total.group(1), mark, "in-table row", state);
                return;
            }
        }

        // two-level label row: the "Question number" column spans two cells —
        // cell 0 carries the question number, cell 1 the sub-part label
        // ("(a)(i)", "a (i)"); the answer starts at cell 2 (T-C04 repair)
        if (cells.size() >= 5 && SUB_LABEL.matcher(cells.get(1).strip()).matches()
                && LABEL.matcher(cells.get(0).strip()).matches()) {
            openTwoLevelEntry(cells, state);
            return;
        }

        // label row → new entry
        Matcher label = LABEL.matcher(cells.get(0).strip());
        if (label.matches()) {
            openEntry(label, cells, state);
            return;
        }

        // continuation-label row: cell 0 is a bare sub-part label ("(ii)",
        // "(iii)", "(b)(i)", "(c)") — a new sub-part of the current question,
        // never a rowspan continuation of the previous entry. A second label
        // in cell 1 marks the two-level group layout, which stays on the
        // continuation path (T-C04 repair).
        if (state.current != null && cells.size() >= 3
                && CONT_LABEL.matcher(cells.get(0).strip()).matches()
                && !CONT_LABEL.matcher(cells.get(1).strip()).matches()
                && openContinuationEntry(cells, state)) {
            return;
        }

        // everything else is a continuation of the current entry (rowspan)
        handleContinuation(cells, state);
    }

    private void handleContinuation(List<String> cells, State state) {
        RawEntry current = state.current;
        if (current == null) {
            if (anyNonEmpty(cells)) {
                state.warnings.add("orphan row before first entry: "
                        + firstNonEmpty(cells));
            }
            return;
        }
        for (int i = 0; i < cells.size(); i++) {
            String cell = cells.get(i);
            if (cell.isBlank()) {
                continue;
            }
            boolean last = i == cells.size() - 1;
            if (last && BARE_INT.matcher(cell.strip()).matches() && cells.size() >= 3
                    && current.marks == null) {
                // rowspan-deferred marks arriving on a later row (e.g. Q11 October)
                current.marks = Integer.parseInt(cell.strip());
                current.marksCellSource = "rowspan continuation row";
                continue;
            }
            if (BARE_INT.matcher(cell.strip()).matches()) {
                state.warnings.add(labelOf(state) + ": bare integer cell \""
                        + cell.strip() + "\" skipped (rubric/rowspan ambiguity)");
                continue;
            }
            if (i == 0 && cells.size() <= 2) {
                current.answerText.append('\n').append(cell.strip());
            } else {
                classifyGuidance(cell.strip(), current.guidance);
            }
        }
    }

    private void openEntry(Matcher label, List<String> cells, State state) {
        closeEntry(state);
        String asterisk = label.group(1);
        int number = Integer.parseInt(label.group(2));
        String part = label.group(3) == null ? "" : label.group(3).replaceAll("[()]", "");
        String printedLabel = asterisk + label.group(2) + label.group(3);
        String entryId = "ms-" + shortId(state.docId) + "-q" + number + part;

        String answer = cellAt(cells, 1);
        Integer marks = trailingInteger(cells);

        List<MarkPoint> markPoints = markPoints(answer);
        List<GuidanceLine> guidance = new ArrayList<>();
        // guidance cells live between the answer cell and the mark cell —
        // 4-col and 5-col tables carry them; 3-col MCQ tables do not
        for (int i = 2; i <= cells.size() - 2; i++) {
            String cell = cells.get(i);
            if (cell != null && !cell.isBlank()) {
                classifyGuidance(cell.strip(), guidance);
            }
        }

        RawEntry entry = new RawEntry(entryId, printedLabel, number,
                !asterisk.isEmpty(), markPoints, answer == null ? "" : answer.strip());
        entry.marks = marks;
        entry.marksCellSource = marks != null ? "label row" : null;
        entry.guidance.addAll(guidance);
        state.current = entry;
        state.entries.add(toEntry(entry));
        // part-letter context for later bare-roman continuation labels; a
        // question-level label ("11") resets it — letters never cross questions
        state.lastPartLetter = part.isEmpty() ? null
                : part.substring(0, 1);
    }

    /**
     * Two-level label row: cell 0 = question number, cell 1 = sub-part label
     * ("(a)(i)", "a (i)"). Opens the entry with the compound label
     * ({@code 7(a)(i)}), the answer at cell 2, and the marks cell last —
     * instead of losing the real answer into the guidance of a bare
     * question-level entry.
     */
    private void openTwoLevelEntry(List<String> cells, State state) {
        closeEntry(state);
        String subLabel = cells.get(1).strip();
        // canonicalize the spaced form "a (i)" → "(a)(i)"
        String canonical = subLabel.matches("^[a-h]\\s*\\([ivx]+\\)$")
                ? "(" + subLabel.substring(0, 1) + ")" + subLabel.substring(1).strip()
                : subLabel;
        Matcher question = LABEL.matcher(cells.get(0).strip());
        if (!question.matches()) {
            return; // unreachable from handleRow; defensive
        }
        int number = Integer.parseInt(question.group(2));
        String part = canonical.replaceAll("[()]", "");
        String printedLabel = number + canonical;
        String entryId = "ms-" + shortId(state.docId) + "-q" + number + part;

        String answer = cellAt(cells, 2);
        Integer marks = trailingInteger(cells);

        List<MarkPoint> markPoints = markPoints(answer);
        List<GuidanceLine> guidance = new ArrayList<>();
        for (int i = 3; i <= cells.size() - 2; i++) {
            String cell = cells.get(i);
            if (cell != null && !cell.isBlank()) {
                classifyGuidance(cell.strip(), guidance);
            }
        }

        RawEntry entry = new RawEntry(entryId, printedLabel, number, false,
                markPoints, answer == null ? "" : answer.strip());
        entry.marks = marks;
        entry.marksCellSource = marks != null ? "two-level label row" : null;
        entry.guidance.addAll(guidance);
        state.current = entry;
        state.entries.add(toEntry(entry));
        state.lastPartLetter = part.isEmpty() ? null : part.substring(0, 1);
    }

    /**
     * Continuation-label row: cell 0 is a bare sub-part label of the current
     * question ("(ii)", "(b)(i)"). Letter-bearing labels name the part
     * directly; bare roman labels continue the letter of the current part
     * sequence. Returns false (row left on the continuation path) when no
     * letter context exists for a bare-roman label — the association would be
     * a guess, and guessing is not this extractor's contract.
     */
    private boolean openContinuationEntry(List<String> cells, State state) {
        String contLabel = cells.get(0).strip();
        Matcher parts = CONT_LABEL_PARTS.matcher(contLabel);
        if (!parts.matches()) {
            return false;
        }
        String letterGroup = parts.group(1); // "(b)" or null
        String romanGroup = parts.group(2);  // "(ii)" or null
        if (letterGroup == null && romanGroup == null) {
            return false;
        }
        String letter;
        if (letterGroup != null) {
            letter = letterGroup.replaceAll("[()]", "");
            state.lastPartLetter = letter;
        } else {
            if (state.lastPartLetter == null) {
                return false; // conservative: no letter context, do not guess
            }
            letter = state.lastPartLetter;
        }
        String roman = romanGroup == null ? "" : romanGroup;

        RawEntry current = state.current;
        String printedLabel = current.number + "(" + letter + ")" + roman;
        String entryId = "ms-" + shortId(state.docId) + "-q" + current.number
                + letter + roman.replaceAll("[()]", "");

        String answer = cellAt(cells, 1);
        Integer marks = trailingInteger(cells);

        List<MarkPoint> markPoints = markPoints(answer);
        List<GuidanceLine> guidance = new ArrayList<>();
        for (int i = 2; i <= cells.size() - 2; i++) {
            String cell = cells.get(i);
            if (cell != null && !cell.isBlank()) {
                classifyGuidance(cell.strip(), guidance);
            }
        }

        closeEntry(state);
        RawEntry entry = new RawEntry(entryId, printedLabel, current.number,
                false, markPoints, answer == null ? "" : answer.strip());
        entry.marks = marks;
        entry.marksCellSource = marks != null ? "continuation label row" : null;
        entry.guidance.addAll(guidance);
        state.current = entry;
        state.entries.add(toEntry(entry));
        return true;
    }

    private void closeEntry(State state) {
        // RawEntry is already converted to its immutable form when opened;
        // continuations mutate the raw builder, so re-convert at close.
        if (state.current != null) {
            int lastIndex = state.entries.size() - 1;
            state.entries.set(lastIndex, toEntry(state.current));
            state.current = null;
        }
    }

    private MarkSchemeEntry toEntry(RawEntry raw) {
        String answer = raw.answerText.toString().strip();
        Matcher mcq = MCQ_ANSWER.matcher(answer);
        boolean isMcq = mcq.find();
        double confidence = raw.marks != null ? 0.75 : 0.5;
        if (isMcq) {
            confidence = 0.85;
        }
        return new MarkSchemeEntry(raw.entryId, raw.label, raw.number, raw.qwc, isMcq,
                isMcq ? mcq.group(1) : null, answer, raw.markPoints, raw.guidance,
                raw.marks, raw.marksCellSource, confidence);
    }

    // ── text lines (standalone totals + metadata) ─────────────────────────────

    private void handleTextLine(String rawLine, State state) {
        String text = rawLine == null ? "" : rawLine.strip();
        if (text.isEmpty()) {
            return;
        }
        // find() — not matches() — because June/1A glue the paper total onto the
        // question-total line: "(Total for Question 20 =15 marks) TOTAL FOR PAPER=80 MARKS"
        Matcher total = TOTAL_STANDALONE.matcher(text);
        if (total.find()) {
            recordTotal(total.group(1), Integer.valueOf(total.group(2)), "standalone line", state);
        }
        Matcher paperTotal = PAPER_TOTAL_IN_LINE.matcher(text);
        if (paperTotal.find()) {
            if (state.paperTotal != null && state.paperTotal != Integer.parseInt(
                    paperTotal.group(1))) {
                state.warnings.add("paper total conflict: " + state.paperTotal
                        + " vs " + paperTotal.group(1));
            }
            state.paperTotal = Integer.parseInt(paperTotal.group(1));
        }
        extractMeta(text, state);
    }

    private void extractMeta(String text, State state) {
        Matcher paperRef = PAPER_REF.matcher(text);
        if (paperRef.find() && state.meta[3] == null) {
            state.meta[3] = paperRef.group(1);
        }
        Matcher logNumber = LOG_NUMBER.matcher(text);
        if (logNumber.find() && state.logNumber == null) {
            state.logNumber = logNumber.group(1);
        }
        Matcher publicationCode = PUBLICATION_CODE.matcher(text);
        if (publicationCode.find() && state.publicationCode == null) {
            state.publicationCode = publicationCode.group(1);
        }
        if (state.meta[0] == null && text.contains("Pearson Edexcel")) {
            state.meta[0] = "Edexcel";
        }
        if (state.meta[4] == null && SESSION_LINE.matcher(text).matches()) {
            state.meta[4] = text;
        }
        if (state.meta[1] == null && text.toLowerCase().contains("international advanced")) {
            state.meta[1] = "IAL";
        }
    }

    // ── mark points and guidance ──────────────────────────────────────────────

    /**
     * Splits an answer cell into marking points on "(N)" markers — a marker
     * is a paren whose content is purely digits (may be glued to the preceding
     * word: "plank(1)"). Non-digit parens like "(allow370Nto390N)" or
     * "(0.5-0.4)" never match. Segments without markers (rowspan answers
     * like October 13(a)) yield an empty list: the cell stays whole in
     * {@code answerText}, never guessed into points. Empty segments (the
     * standalone "(1)" separators OCR emits in Any-two-from cells) are
     * skipped without inventing text.
     */
    static List<MarkPoint> markPoints(String answerCell) {
        if (answerCell == null || answerCell.isBlank()) {
            return List.of();
        }
        List<MarkPoint> points = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        Matcher marker = MARKER.matcher(answerCell);
        int consumed = 0;
        int ordinal = 0;
        while (marker.find()) {
            current.append(answerCell, consumed, marker.start());
            if (!current.toString().isBlank()) {
                ordinal++;
                points.add(markPoint(ordinal, current.toString(),
                        Integer.parseInt(marker.group(1))));
            }
            current.setLength(0);
            consumed = marker.end();
        }
        current.append(answerCell.substring(Math.min(consumed, answerCell.length())));
        String tail = current.toString().strip();
        if (!tail.isEmpty() && points.isEmpty()) {
            // no markers at all — not a splittable cell; leave whole (honesty)
            return List.of();
        }
        if (!tail.isEmpty()) {
            ordinal++;
            points.add(markPoint(ordinal, tail, null));
        }
        return points;
    }

    private static MarkPoint markPoint(int ordinal, String segment, Integer marks) {
        String raw = segment.strip();
        List<String> dependentOn = new ArrayList<>();
        Matcher dependent = DEPENDENT_ON.matcher(raw);
        while (dependent.find()) {
            Matcher refs = MP_REF.matcher(dependent.group(1));
            while (refs.find()) {
                String ref = "MP" + refs.group(1);
                if (!dependentOn.contains(ref)) {
                    dependentOn.add(ref);
                }
            }
        }
        boolean ecf = Pattern.compile("\\becf\\b", Pattern.CASE_INSENSITIVE).matcher(raw).find();
        boolean anyTwoFrom = Pattern.compile("(?i)any\\s+two\\s+from").matcher(raw).find();
        boolean reject = Pattern.compile("(?i)do\\s+not\\s+accept|is\\s+insufficient")
                .matcher(raw).find();
        List<String> alternatives = new ArrayList<>();
        String[] orParts = raw.split("(?i)\\bor\\b");
        if (orParts.length > 1) {
            for (int i = 1; i < orParts.length; i++) {
                String alt = orParts[i].strip();
                if (!alt.isEmpty()) {
                    alternatives.add(alt);
                }
            }
        }
        String text = orParts[0].strip();
        return new MarkPoint(ordinal, text, marks, dependentOn, ecf, alternatives,
                anyTwoFrom, reject, raw);
    }

    static void classifyGuidance(String guidanceText, List<GuidanceLine> sink) {
        String[] lines = guidanceText.split("\n");
        for (String line : lines) {
            String t = line.strip();
            if (t.isEmpty()) {
                continue;
            }
            String lower = t.toLowerCase();
            String kind;
            if (lower.startsWith("allow")) {
                kind = "allow";
            } else if (lower.startsWith("ignore")) {
                kind = "ignore";
            } else if (lower.startsWith("example calculation")) {
                kind = "example-calculation";
            } else if (lower.startsWith("example diagram") || lower.startsWith("example graph")) {
                kind = "example-diagram";
            } else if (lower.startsWith("ecf")) {
                kind = "ecf";
            } else if (lower.startsWith("mp") && lower.contains("dependent")) {
                kind = "dependent";
            } else {
                kind = "note";
            }
            sink.add(new GuidanceLine(kind, t));
        }
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    private void recordTotal(String numberText, Integer mark, String placement, State state) {
        int number = Integer.parseInt(numberText);
        if (mark == null) {
            state.warnings.add("total for question " + number + " (" + placement
                    + "): no mark value in row");
            return;
        }
        Integer existing = state.totals.get(number);
        if (existing != null && existing != mark) {
            state.warnings.add("total conflict for question " + number + ": " + existing
                    + " (" + "first" + ") vs " + mark + " (" + placement + ")");
        }
        state.totals.put(number, mark);
    }

    private Map<String, Integer> stringTotals(Map<Integer, Integer> totals) {
        Map<String, Integer> result = new LinkedHashMap<>();
        for (Map.Entry<Integer, Integer> e : totals.entrySet()) {
            result.put(Integer.toString(e.getKey()), e.getValue());
        }
        return result;
    }

    private PaperMeta paperMeta(CanonicalDocument doc, State state) {
        return new PaperMeta(
                state.meta[0] == null && state.meta[3] != null ? "Edexcel" : state.meta[0],
                state.meta[1], state.meta[2], state.meta[3], state.logNumber,
                state.publicationCode, state.meta[4], state.meta[5], state.meta[6],
                doc.documentId());
    }

    private static String cellAt(List<String> cells, int index) {
        return index < cells.size() ? cells.get(index) : null;
    }

    private static Integer trailingInteger(List<String> cells) {
        for (int i = cells.size() - 1; i >= 0; i--) {
            String cell = cells.get(i).strip();
            if (cell.isEmpty()) {
                continue;
            }
            return BARE_INT.matcher(cell).matches() ? Integer.parseInt(cell) : null;
        }
        return null;
    }

    private static boolean allIcValues(List<String> cells) {
        boolean any = false;
        for (String cell : cells) {
            String c = cell.strip();
            if (c.isEmpty()) {
                continue;
            }
            if (!IC_VALUE.matcher(c).matches()) {
                return false;
            }
            any = true;
        }
        return any;
    }

    private static boolean anyNonEmpty(List<String> cells) {
        return cells.stream().anyMatch(c -> !c.isBlank());
    }

    private static String firstNonEmpty(List<String> cells) {
        for (String cell : cells) {
            if (!cell.isBlank()) {
                return cell.strip();
            }
        }
        return "";
    }

    private static List<String> stripCells(List<String> row) {
        List<String> result = new ArrayList<>();
        for (String cell : row) {
            result.add(cell == null ? "" : cell);
        }
        return result;
    }

    private static String labelOf(State state) {
        return state.current == null ? "?" : state.current.label;
    }

    private static String shortId(String docId) {
        return docId == null ? "doc" : docId.substring(0, Math.min(8, docId.length()));
    }
}
