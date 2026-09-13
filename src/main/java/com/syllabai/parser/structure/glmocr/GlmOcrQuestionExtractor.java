package com.syllabai.parser.structure.glmocr;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.DocumentElement;
import com.syllabai.parser.canonical.EquationElement;
import com.syllabai.parser.canonical.FigureElement;
import com.syllabai.parser.canonical.TableElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.FigureRef;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.McqOption;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PaperMeta;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PartDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.QuestionDraft;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * GLM-OCR question-paper extractor (Session 8, syntax report §3).
 *
 * <p>Segmentation accepts THREE real numbering styles — {@code "1: stem"}
 * (June export), {@code "1 stem"} (October export) and {@code "1. stem"}
 * (2011-June / Specimen-2017 export) — plus the documented
 * artefacts: total lines promoted to headings, detached MCQ option letters,
 * options arriving out of order, centered {@code (N)} marks blocks, and
 * answer prompts ending in "=". The dot style requires the stem to start
 * with a part label "(a)" or a capital letter: GLM-OCR line-breaks decimal
 * quantities after the point ("25.0 cm3" → "25. 0 cm3…") and such fragments
 * must never open a question (sequence check plus stem plausibility).</p>
 *
 * <p><strong>Honesty:</strong> MCQ status is validated in hindsight — a
 * pending option set only counts if the complete A–D set closes before the
 * next question, otherwise the lines fold back into stem/part text. Figures
 * attach to the open question/part as unavailable references. Everything
 * carries {@code reviewRequired=true} and confidence &lt; 1.0.</p>
 */
public final class GlmOcrQuestionExtractor {

    public static final String EXTRACTION_METHOD = "glm-ocr-qp-v1";

    private static final Pattern QUESTION_COLON = Pattern.compile("^\\*?(\\d{1,2}):\\s*(.*)$");
    private static final Pattern QUESTION_SPACE = Pattern.compile("^(\\*?)(\\d{1,2})\\s+(\\S.*)$");
    private static final Pattern QUESTION_DOT = Pattern.compile("^(\\*?)(\\d{1,2})\\.\\s+(\\S.*)$");
    private static final Pattern COMBINED_PART = Pattern.compile("^\\*?\\(([a-h])\\)\\s*\\(([ivx]+)\\)\\s*(.*)$");
    private static final Pattern LETTER_PART = Pattern.compile("^\\*?\\(([a-h])\\)\\s*(.*)$");
    private static final Pattern ROMAN_PART = Pattern.compile("^\\(([ivx]+)\\)\\s*(.*)$");
    private static final Pattern OPTION = Pattern.compile("^([A-D])\\s+(\\S.*)$");
    private static final Pattern BARE_LETTER = Pattern.compile("^([A-D])$");
    private static final Pattern MARKS_BLOCK = Pattern.compile("^\\((\\d{1,2})\\)\\s*$");
    private static final Pattern TOTAL_FOR_QUESTION = Pattern.compile(
            "^\\(?(?:Total for question|TOTAL FOR QUESTION)\\s*(\\d{1,2})\\s*=\\s*(\\d{1,3})\\s*marks?\\)?\\.?$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern TOTAL_FOR_PAPER = Pattern.compile(
            "TOTAL FOR PAPER\\s*=\\s*(\\d{1,3})\\s*MARKS", Pattern.CASE_INSENSITIVE);
    private static final Pattern TOTAL_FOR_SECTION = Pattern.compile(
            "TOTAL FOR SECTION\\s*([A-Z])\\s*=\\s*(\\d{1,3})\\s*MARKS", Pattern.CASE_INSENSITIVE);
    /**
     * Paper reference codes. Two printed families:
     *  - IAL unit codes  : WCH11/1C  (W + 2 letters + 2 digits)
     *  - IGCSE codes     : 4CH0/1C, 4CH1/1CR, KCH0/2C (4 chars + / + number + optional R)
     * When a cover prints several codes (e.g. "4CH1/1C 4SD0/1C" or the Edexcel
     * Certificate twin "KCH0/2C 4CH0/2C"), the FIRST printed code wins — the
     * chemistry paper is printed first on every observed 4CH1 cover.
     */
    private static final Pattern PAPER_REF = Pattern.compile(
            "\\b((?:W[A-Z]{2}\\d{2}|[A-Z0-9]{4})/\\d{1,2}[A-Z]?)\\b");
    /** months accepted on a printed session line (e.g. "Summer 2013", "November 2021") */
    private static final String SESSION_MONTHS = "January|February|March|April|May|June|July|"
            + "August|September|October|November|December";
    private static final Pattern LOG_NUMBER = Pattern.compile(
            "(?i)log\\s+number\\s+(P\\d{5,6}[A-Z])\\b");
    private static final Pattern PUBLICATION_CODE = Pattern.compile(
            "(?i)publications?\\s+code\\s+(\\S+)");
    private static final Pattern LOG_TOTAL = Pattern.compile(
            "total mark for this paper is\\s*(\\d{1,3})", Pattern.CASE_INSENSITIVE);
    private static final Pattern TURN_OVER = Pattern.compile("^Turn over\\s*$", Pattern.CASE_INSENSITIVE);
    private static final Pattern NOISE = Pattern.compile(
            "^(Not to scale|\\*NOT TO SCALE\\*|See next page|End of Question Paper)\\s*$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern SOURCE_NOTE = Pattern.compile("^\\(Source: ?(.*)\\)\\s*$");

    private static final String FIGURE_UNAVAILABLE = "unavailable-signed-url";

    public GlmOcrPaperDraft extract(CanonicalDocument questionPaper) {
        State state = new State(questionPaper.documentId());
        for (DocumentElement element : questionPaper.elementsInReadingOrder()) {
            if (element instanceof TextBlockElement block) {
                if (block.role() == TextRole.HEADING) {
                    handleHeading(block.text(), state);
                } else {
                    handleLine(block.text(), state);
                }
            } else if (element instanceof FigureElement figure) {
                handleFigure(figure, state);
            } else if (element instanceof TableElement table) {
                handleTable(table, state);
            } else if (element instanceof EquationElement equation) {
                if (state.current != null && equation.latex() != null) {
                    appendText(" $" + equation.latex().replace("\n", " ").strip() + "$", state);
                }
            }
        }
        finishQuestion(state);

        Map<String, Integer> totals = new LinkedHashMap<>();
        for (Map.Entry<Integer, Integer> e : state.totals.entrySet()) {
            totals.put(Integer.toString(e.getKey()), e.getValue());
        }
        return new GlmOcrPaperDraft(GlmOcrPaperDraft.SCHEMA_VERSION, EXTRACTION_METHOD, true,
                paperMeta(questionPaper, state), buildQuestions(state), totals,
                state.paperTotal, state.sectionTotals, state.frontMatterFigures, state.warnings);
    }

    // ── state ──────────────────────────────────────────────────────────────────

    private static final class State {
        final String docId;
        final List<RawQuestion> questions = new ArrayList<>();
        final Map<Integer, Integer> totals = new LinkedHashMap<>();
        final Map<String, Integer> sectionTotals = new LinkedHashMap<>();
        final List<FigureRef> frontMatterFigures = new ArrayList<>();
        final List<String> warnings = new ArrayList<>();
        final String[] meta = new String[7]; // board, qual, subject, paperRef, session, date, duration
        String logNumber;
        String publicationCode;
        String specimenYear;
        Integer paperTotal;
        String section = null;
        boolean inFormulaAppendix;
        boolean sawMarkScheme;
        RawQuestion current;

        State(String docId) {
            this.docId = docId;
        }
    }

    private static final class RawQuestion {
        final int number;
        final String numberingStyle;
        String section;
        final StringBuilder stem = new StringBuilder();
        boolean qwc;
        final List<String> optionLetters = new ArrayList<>();
        final Map<String, String> optionTexts = new LinkedHashMap<>();
        final List<RawPart> parts = new ArrayList<>();
        final List<FigureRef> figures = new ArrayList<>();
        final List<String> tableElementIds = new ArrayList<>();
        final List<String> answerPrompts = new ArrayList<>();
        Integer totalFromPaper;
        boolean bareLetterLines;

        RawQuestion(int number, String numberingStyle) {
            this.number = number;
            this.numberingStyle = numberingStyle;
        }
    }

    private static final class RawPart {
        final String label;
        final StringBuilder text = new StringBuilder();
        final List<FigureRef> figures = new ArrayList<>();
        final List<String> answerPrompts = new ArrayList<>();
        Integer marks;
        boolean qwc;

        RawPart(String label) {
            this.label = label;
        }
    }

    // ── line handling ──────────────────────────────────────────────────────────

    private void handleHeading(String text, State state) {
        Matcher total = TOTAL_FOR_QUESTION.matcher(text.strip());
        if (total.matches()) {
            recordTotal(total, state);
            return;
        }
        String t = text.strip();
        if (t.matches("(?i)^SECTION ([A-Z])$")) {
            state.section = t.substring(t.length() - 1);
            return;
        }
        if (t.toLowerCase().startsWith("list of data")
                || t.toLowerCase().startsWith("formulae")) {
            state.inFormulaAppendix = true;
            return;
        }
        if (t.equalsIgnoreCase("BLANK PAGE") || t.equalsIgnoreCase("Advice")
                || t.toLowerCase().startsWith("instructions") || t.equalsIgnoreCase("information")
                || t.toLowerCase().startsWith("answer all")) {
            return; // boilerplate headings
        }
        // documented defect: question numbers promoted to Markdown headings
        // (October export: "## 15 A student investigated a spring.") — accept a
        // FORWARD jump so the sequence resumes; backward/duplicate still rejected
        Matcher colonHeading = QUESTION_COLON.matcher(t);
        if (colonHeading.matches() && isForwardQuestion(
                Integer.parseInt(colonHeading.group(1)), state)) {
            openQuestion(Integer.parseInt(colonHeading.group(1)), "colon",
                    colonHeading.group(2), state);
            if (t.startsWith("*")) {
                state.current.qwc = true;
            }
            state.warnings.add("Q" + colonHeading.group(1)
                    + ": question number promoted to heading (opened from heading)");
            return;
        }
        Matcher spaceHeading = QUESTION_SPACE.matcher(t);
        if (spaceHeading.matches() && isForwardQuestion(
                Integer.parseInt(spaceHeading.group(2)), state)) {
            openQuestion(Integer.parseInt(spaceHeading.group(2)), "space",
                    spaceHeading.group(3), state);
            if (!spaceHeading.group(1).isEmpty()) {
                state.current.qwc = true;
            }
            state.warnings.add("Q" + spaceHeading.group(2)
                    + ": question number promoted to heading (opened from heading)");
            return;
        }
        Matcher dotHeading = QUESTION_DOT.matcher(t);
        if (dotHeading.matches() && isForwardQuestion(
                Integer.parseInt(dotHeading.group(2)), state)
                && dotStemPlausible(dotHeading.group(3))) {
            openQuestion(Integer.parseInt(dotHeading.group(2)), "dot",
                    dotHeading.group(3), state);
            if (!dotHeading.group(1).isEmpty()) {
                state.current.qwc = true;
            }
            state.warnings.add("Q" + dotHeading.group(2)
                    + ": question number promoted to heading (opened from heading)");
            return;
        }
        if (t.toLowerCase().contains("mark scheme")) {
            state.sawMarkScheme = true;
        }
        // any other heading inside the body is treated as structural noise but kept visible
        state.warnings.add("unclassified heading: " + t);
    }

    /** Forward numbering only: strictly increasing, no duplicates. */
    private boolean isForwardQuestion(int number, State state) {
        return state.current == null || number > state.current.number;
    }

    private void handleLine(String rawLine, State state) {
        String text = rawLine == null ? "" : rawLine.strip();
        if (text.isEmpty() || NOISE.matcher(text).matches() || TURN_OVER.matcher(text).matches()) {
            return;
        }

        Matcher total = TOTAL_FOR_QUESTION.matcher(text);
        if (total.matches()) {
            recordTotal(total, state);
            return;
        }
        Matcher paperTotal = TOTAL_FOR_PAPER.matcher(text);
        if (paperTotal.find()) {
            state.paperTotal = Integer.parseInt(paperTotal.group(1));
            // "TOTAL FOR SECTION B=70 MARKS TOTAL FOR PAPER=80 MARKS" can share a line
            Matcher sectionTotal = TOTAL_FOR_SECTION.matcher(text);
            if (sectionTotal.find()) {
                state.sectionTotals.put(sectionTotal.group(1), Integer.parseInt(sectionTotal.group(2)));
            }
            return;
        }
        Matcher sectionTotal = TOTAL_FOR_SECTION.matcher(text);
        if (sectionTotal.find()) {
            state.sectionTotals.put(sectionTotal.group(1), Integer.parseInt(sectionTotal.group(2)));
            return;
        }
        Matcher logTotal = LOG_TOTAL.matcher(text);
        if (logTotal.find()) {
            state.paperTotal = Integer.parseInt(logTotal.group(1));
            return;
        }
        extractMeta(text, state);

        if (state.inFormulaAppendix) {
            return; // appendix text after "List of data…" is not question content
        }

        // question starts — all three numbering styles, sequence-checked
        Matcher colon = QUESTION_COLON.matcher(text);
        if (colon.matches() && isNextQuestion(Integer.parseInt(colon.group(1)), state)) {
            openQuestion(Integer.parseInt(colon.group(1)), "colon", colon.group(2), state);
            if (text.startsWith("*")) {
                state.current.qwc = true; // question-level QWC asterisk (*14)
            }
            return;
        }
        Matcher space = QUESTION_SPACE.matcher(text);
        if (space.matches() && isNextQuestion(Integer.parseInt(space.group(2)), state)) {
            openQuestion(Integer.parseInt(space.group(2)), "space", space.group(3), state);
            if (!space.group(1).isEmpty()) {
                state.current.qwc = true; // question-level QWC asterisk (*14)
            }
            return;
        }
        Matcher dot = QUESTION_DOT.matcher(text);
        if (dot.matches() && isNextQuestion(Integer.parseInt(dot.group(2)), state)
                && dotStemPlausible(dot.group(3))) {
            openQuestion(Integer.parseInt(dot.group(2)), "dot", dot.group(3), state);
            if (!dot.group(1).isEmpty()) {
                state.current.qwc = true; // question-level QWC asterisk (*14)
            }
            return;
        }

        if (state.current == null) {
            // content before the first question: instructions/front matter, already meta-scanned
            return;
        }
        RawQuestion q = state.current;

        Matcher combined = COMBINED_PART.matcher(text);
        if (combined.matches()) {
            String label = combined.group(1);
            RawPart part = new RawPart(label);
            part.text.append(combined.group(3));
            q.parts.add(part);
            if (text.startsWith("*")) {
                part.qwc = true;
            }
            return;
        }
        Matcher letter = LETTER_PART.matcher(text);
        if (letter.matches()) {
            RawPart part = new RawPart(letter.group(1));
            part.text.append(letter.group(2));
            if (text.startsWith("*")) {
                part.qwc = true;
                q.qwc = true;
            }
            q.parts.add(part);
            return;
        }
        Matcher roman = ROMAN_PART.matcher(text);
        if (roman.matches() && !q.parts.isEmpty()) {
            // parent = last LETTER-level part (label without dash), so "(ii)"
            // after the combined part "b-i" attaches to "b" → "b-ii", never "b-i-ii"
            RawPart parent = null;
            for (int p = q.parts.size() - 1; p >= 0; p--) {
                if (!q.parts.get(p).label.contains("-")) {
                    parent = q.parts.get(p);
                    break;
                }
            }
            if (parent != null) {
                RawPart sub = new RawPart(parent.label + "-" + roman.group(1));
                sub.text.append(roman.group(2));
                q.parts.add(sub);
                return;
            }
        }
        Matcher marks = MARKS_BLOCK.matcher(text);
        if (marks.matches()) {
            int value = Integer.parseInt(marks.group(1));
            if (!q.parts.isEmpty()) {
                q.parts.getLast().marks = value;
            } else {
                q.answerPrompts.add(text); // stem-level (N) — recorded, marks stay unknown
            }
            return;
        }
        Matcher bare = BARE_LETTER.matcher(text);
        if (bare.matches() && q.parts.isEmpty()) {
            // detached MCQ option letters (defect: letters on their own lines after figures)
            q.optionLetters.add(bare.group(1));
            q.bareLetterLines = true;
            return;
        }
        Matcher option = OPTION.matcher(text);
        if (option.matches() && q.parts.isEmpty()) {
            // candidate option — letter + whitespace required, so prose words
            // starting with A-D ("Acceleration =", "As shown…") never match;
            // validated in hindsight when the question closes
            q.optionTexts.put(option.group(1), option.group(2));
            return;
        }
        Matcher source = SOURCE_NOTE.matcher(text);
        if (source.matches()) {
            if (!q.figures.isEmpty()) {
                q.figures.getLast().availability(); // attribution kept implicitly in draft warnings
            }
            state.warnings.add("figure attribution Q" + q.number + ": " + text);
            return;
        }
        if (text.endsWith("=") || text.matches(".*=\\s*$")) {
            String prompt = text.replaceAll("\\s*=\\s*$", "").strip();
            if (!q.parts.isEmpty()) {
                q.parts.getLast().answerPrompts.add(prompt);
            } else {
                q.answerPrompts.add(prompt);
            }
            return;
        }

        appendText(" " + text, state);
    }

    private void appendText(String text, State state) {
        RawQuestion q = state.current;
        if (q == null) {
            return;
        }
        if (q.parts.isEmpty()) {
            q.stem.append(text);
        } else {
            RawPart part = q.parts.getLast();
            if (part.text.length() > 0) {
                part.text.append(' ');
            }
            part.text.append(text.strip());
        }
    }

    private void openQuestion(int number, String style, String stem, State state) {
        finishQuestion(state);
        RawQuestion raw = new RawQuestion(number, style);
        raw.section = state.section;
        if (stem != null && !stem.isBlank()) {
            raw.stem.append(stem.strip());
        }
        state.current = raw;
        state.questions.add(raw);
    }

    private boolean isNextQuestion(int number, State state) {
        if (state.current == null) {
            return number == 1;
        }
        return number == state.current.number + 1;
    }

    /**
     * Decimal-quantity guard for the "N." numbering style (2011-Jun,
     * Specimen-2017). GLM-OCR line-breaks decimal quantities after the
     * decimal point — "25.0 cm3" surfaces as "25. 0 cm3…" — and such a
     * fragment must NOT open question 25. Every real dot-style stem in the
     * audited corpus starts with a part label "(a)" or a capital letter;
     * every observed decimal fragment starts with a digit. A rejected real
     * stem fails safe: its text stays attached to the previous question
     * where teacher review sees it.
     */
    static boolean dotStemPlausible(String remainder) {
        return remainder != null && !remainder.isEmpty()
                && (remainder.charAt(0) == '('
                || Character.isUpperCase(remainder.charAt(0)));
    }

    private void recordTotal(Matcher total, State state) {
        state.totals.put(Integer.parseInt(total.group(1)), Integer.parseInt(total.group(2)));
    }

    private void extractMeta(String text, State state) {
        if (text.indexOf('<') >= 0 && text.toLowerCase(Locale.ROOT).contains("<table")) {
            // Cover metadata on newer templates lives inside HTML table cells; a
            // whole-table element defeats the ^...$ line regexes. Run the same
            // matchers against each printed cell line (tags split, entities kept
            // simple). Plain-line extraction below still runs first.
            for (String candidate : tableCellLines(text)) {
                metaFromLine(candidate, state);
            }
        }
        metaFromLine(text, state);
    }

    /** splits an HTML-table element into printed cell lines, tags stripped */
    static List<String> tableCellLines(String tableHtml) {
        List<String> lines = new ArrayList<>();
        if (!tableHtml.toLowerCase(Locale.ROOT).contains("<table")) {
            return lines;
        }
        for (String cell : tableHtml.split("</t[dh]>|<tr[^>]*>|</tr>")) {
            // cells keep raw internal newlines (e.g. "Wednesday 18 January 2017 – Afternoon\nTime: 1 hour");
            // each printed line is matched separately so the ^...$ identity regexes survive
            for (String line : cell.replaceAll("<[^>]+>", " ").split("\\n")) {
                String stripped = line.replace("&amp;", "&").replace("&nbsp;", " ")
                        .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
                        .replaceAll("[ \\t\\r]+", " ").strip();
                if (!stripped.isEmpty()) {
                    lines.add(stripped);
                }
            }
        }
        return lines;
    }

    private void metaFromLine(String text, State state) {
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
        if (state.meta[4] == null
                && text.matches("(?i)^(Summer|Autumn|Winter|" + SESSION_MONTHS + ")\\s+20\\d{2}$")) {
            state.meta[4] = text;
        }
        if (state.meta[6] == null && text.toLowerCase().contains("time:")
                && text.toLowerCase().contains("minutes")) {
            state.meta[6] = text.replaceAll("\\s+", " ").strip();
        }
        if (state.meta[5] == null && text.matches(
                "(?i)^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\\s+\\d{1,2}\\s+"
                        + "(" + SESSION_MONTHS + ")\\s+20\\d{2}"
                        // newer covers append the sitting time to the same line:
                        // "Wednesday 18 January 2017 – Afternoon"
                        + "(\\s*[–—-]\\s*(Morning|Afternoon|Evening))?$")) {
            state.meta[5] = text;
        }
        if (state.specimenYear == null) {
            Matcher specimen = Pattern.compile(
                    "(?i)Sample Assessment Materials.*?(20\\d{2})").matcher(text);
            if (specimen.find()) {
                state.specimenYear = specimen.group(1);
            }
        }
        if (state.meta[2] == null && state.meta[3] != null && paperRef.find()) {
            // subject stays null unless an identity line names it
        }
        if (state.meta[2] == null && text.matches(
                "(?i).*Advanced (Subsidiary )?(Level|Levels).*")) {
            Matcher subject = Pattern.compile("(?i)\\bin\\s+([A-Za-z]+)\\s*\\(").matcher("");
        }
        if (state.meta[1] == null && text.toLowerCase().contains("international advanced")) {
            state.meta[1] = "IAL";
        }
    }

    /**
     * Session label resolution, first evidence wins:
     *  1. a printed session line ("Summer 2013", "November 2021");
     *  2. the printed exam date ("Thursday 14 May 2020") — month mapped to the
     *     session name (May and June sittings are the "June" session; every other
     *     month maps to itself). Both tokens are printed on the cover; the May→June
     *     mapping is Pearson's own session naming (the approved corpus slugs use it:
     *     2020jun), NOT a guess;
     *  3. "Specimen &lt;year&gt;" for Sample Assessment Materials covers (the year is
     *     printed on the same line: "... for first teaching September 2017").
     */
    private String sessionLabel(State state) {
        if (state.meta[4] != null) {
            return state.meta[4];
        }
        if (state.meta[5] != null) {
            Matcher m = Pattern.compile(
                    "(?i)(" + SESSION_MONTHS + ")\\s+(20\\d{2})").matcher(state.meta[5]);
            if (m.find()) {
                String month = m.group(1);
                month = month.equalsIgnoreCase("May") ? "June"
                        : month.substring(0, 1).toUpperCase(Locale.ROOT)
                                + month.substring(1).toLowerCase(Locale.ROOT);
                return month + " " + m.group(2);
            }
        }
        return state.specimenYear == null ? null : "Specimen " + state.specimenYear;
    }

    private PaperMeta paperMeta(CanonicalDocument doc, State state) {
        return new PaperMeta(
                state.meta[0] == null && state.meta[3] != null ? "Edexcel" : state.meta[0],
                state.meta[1], state.meta[2], state.meta[3], state.logNumber,
                state.publicationCode, sessionLabel(state), state.meta[5],
                state.meta[6], doc.documentId());
    }

    // ── figures and tables ─────────────────────────────────────────────────────

    private void handleFigure(FigureElement figure, State state) {
        FigureRef ref = new FigureRef(figure.elementId(), figure.sourceName(), figure.format(),
                figure.text(), FIGURE_UNAVAILABLE, null, null, null, null, null, null);
        RawQuestion q = state.current;
        if (q == null || state.inFormulaAppendix) {
            if (q == null) {
                state.frontMatterFigures.add(ref);
            } else {
                q.figures.add(ref);
            }
            return;
        }
        q.figures.add(ref);
        if (!q.parts.isEmpty()) {
            q.parts.getLast().figures.add(ref);
        }
    }

    private void handleTable(TableElement table, State state) {
        RawQuestion q = state.current;
        if (q == null) {
            return; // front-matter cover table (1A variant)
        }
        q.tableElementIds.add(table.elementId());
        // MCQ grid: rows whose first cell is a bare letter A-D with text cells
        List<McqOption> gridOptions = mcqGridOptions(table);
        if (!gridOptions.isEmpty() && q.parts.isEmpty()) {
            for (McqOption option : gridOptions) {
                q.optionTexts.put(option.letter(), option.text());
            }
        }
    }

    private List<McqOption> mcqGridOptions(TableElement table) {
        List<McqOption> options = new ArrayList<>();
        for (List<String> row : table.rows()) {
            if (row.size() >= 2) {
                String first = row.get(0).strip();
                if (first.matches("^[A-D]$")) {
                    options.add(new McqOption(first, String.join(" ", row.subList(1, row.size())).strip()));
                }
            }
        }
        return options.size() >= 2 ? options : List.of();
    }

    // ── completion ─────────────────────────────────────────────────────────────

    private void finishQuestion(State state) {
        RawQuestion q = state.current;
        if (q == null) {
            return;
        }
        state.current = null;
    }

    private List<QuestionDraft> buildQuestions(State state) {
        List<QuestionDraft> result = new ArrayList<>();
        for (RawQuestion raw : state.questions) {
            result.add(toDraft(raw, state));
        }
        return result;
    }

    private QuestionDraft toDraft(RawQuestion raw, State state) {
        String shortDoc = shortId(state.docId);
        String questionId = "q" + String.format("%02d", raw.number) + "-" + shortDoc;

        // MCQ validation in hindsight: complete A–D set, no parts
        boolean mcq = raw.parts.isEmpty() && raw.optionTexts.keySet().containsAll(
                List.of("A", "B", "C", "D"));
        if (raw.bareLetterLines && !mcq) {
            state.warnings.add("Q" + raw.number + ": detached option letters without option text");
        }

        List<McqOption> options = new ArrayList<>();
        if (mcq) {
            for (String letter : List.of("A", "B", "C", "D")) {
                options.add(new McqOption(letter, raw.optionTexts.get(letter)));
            }
        } else if (!raw.optionTexts.isEmpty()) {
            // incomplete option set folds back into stem (defect evidence)
            raw.optionTexts.forEach((letter, text) -> raw.stem.append(' ').append(letter).append(' ').append(text));
            state.warnings.add("Q" + raw.number + ": incomplete MCQ option set folded into stem");
        }

        List<PartDraft> parts = new ArrayList<>();
        int partMarks = 0;
        boolean allMarksKnown = !raw.parts.isEmpty();
        for (RawPart part : raw.parts) {
            String text = part.text.toString().strip();
            parts.add(new PartDraft(
                    questionId + "-p" + part.label, part.label, text, part.marks, part.qwc,
                    part.figures, part.answerPrompts,
                    part.marks != null ? 0.8 : 0.55));
            if (part.marks != null) {
                partMarks += part.marks;
            } else {
                allMarksKnown = false;
            }
        }

        Integer totalFromPaper = state.totals.get(raw.number);
        // honesty: when both the part-marks sum and the printed total are known
        // and disagree (OCR damage, e.g. October Q18: parts sum 2 vs total 8),
        // the marks are NOT exact — conflict recorded, never silently resolved
        boolean marksConflict = allMarksKnown && totalFromPaper != null
                && partMarks != totalFromPaper;
        if (marksConflict) {
            state.warnings.add("Q" + raw.number + ": part marks sum (" + partMarks
                    + ") conflicts with printed total (" + totalFromPaper + ")");
        }
        int marks = allMarksKnown ? partMarks
                : totalFromPaper != null ? totalFromPaper
                : mcq ? 1 : 0;

        double confidence = mcq ? 0.8
                : allMarksKnown ? 0.75
                : totalFromPaper != null ? 0.6 : 0.45;

        return new QuestionDraft(questionId, raw.number, raw.numberingStyle, raw.section,
                raw.stem.toString().strip(), mcq, options, parts, raw.figures,
                raw.tableElementIds, marks, (allMarksKnown || totalFromPaper != null)
                && !marksConflict, raw.qwc,
                raw.answerPrompts, confidence);
    }

    private String shortId(String docId) {
        return docId == null ? "doc" : docId.substring(0, Math.min(8, docId.length()));
    }
}
