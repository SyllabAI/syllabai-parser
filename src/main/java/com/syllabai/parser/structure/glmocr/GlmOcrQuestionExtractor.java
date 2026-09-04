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
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * GLM-OCR question-paper extractor (Session 8, syntax report §3).
 *
 * <p>Segmentation accepts BOTH real numbering styles — {@code "1: stem"}
 * (June export) and {@code "1 stem"} (October export) — plus the documented
 * artefacts: total lines promoted to headings, detached MCQ option letters,
 * options arriving out of order, centered {@code (N)} marks blocks, and
 * answer prompts ending in "=".</p>
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
    private static final Pattern QUESTION_SPACE = Pattern.compile("^(\\d{1,2})\\s+(\\S.*)$");
    private static final Pattern COMBINED_PART = Pattern.compile("^\\*?\\(([a-h])\\)\\s*\\(([ivx]+)\\)\\s*(.*)$");
    private static final Pattern LETTER_PART = Pattern.compile("^\\*?\\(([a-h])\\)\\s*(.*)$");
    private static final Pattern ROMAN_PART = Pattern.compile("^\\(([ivx]+)\\)\\s*(.*)$");
    private static final Pattern OPTION = Pattern.compile("^([A-D])\\s*(\\S.*)$");
    private static final Pattern BARE_LETTER = Pattern.compile("^([A-D])$");
    private static final Pattern MARKS_BLOCK = Pattern.compile("^\\((\\d{1,2})\\)\\s*$");
    private static final Pattern TOTAL_FOR_QUESTION = Pattern.compile(
            "^\\(?(?:Total for question|TOTAL FOR QUESTION)\\s*(\\d{1,2})\\s*=\\s*(\\d{1,3})\\s*marks?\\)?\\.?$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern TOTAL_FOR_PAPER = Pattern.compile(
            "TOTAL FOR PAPER\\s*=\\s*(\\d{1,3})\\s*MARKS", Pattern.CASE_INSENSITIVE);
    private static final Pattern TOTAL_FOR_SECTION = Pattern.compile(
            "TOTAL FOR SECTION\\s*([A-Z])\\s*=\\s*(\\d{1,3})\\s*MARKS", Pattern.CASE_INSENSITIVE);
    private static final Pattern PAPER_REF = Pattern.compile("\\b(W[A-Z]{2}\\d{2}/\\d{1,2}[A-Z]?)\\b");
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
        if (t.toLowerCase().contains("mark scheme")) {
            state.sawMarkScheme = true;
        }
        // any other heading inside the body is treated as structural noise but kept visible
        state.warnings.add("unclassified heading: " + t);
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

        // question starts — both numbering styles, sequence-checked
        Matcher colon = QUESTION_COLON.matcher(text);
        if (colon.matches() && isNextQuestion(Integer.parseInt(colon.group(1)), state)) {
            openQuestion(Integer.parseInt(colon.group(1)), "colon", colon.group(2), state);
            return;
        }
        Matcher space = QUESTION_SPACE.matcher(text);
        if (space.matches() && isNextQuestion(Integer.parseInt(space.group(1)), state)) {
            openQuestion(Integer.parseInt(space.group(1)), "space", space.group(2), state);
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
            RawPart parent = q.parts.getLast();
            RawPart sub = new RawPart(parent.label + "-" + roman.group(1));
            sub.text.append(roman.group(2));
            q.parts.add(sub);
            return;
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
        if (option.matches() && q.parts.isEmpty() && !q.figures.isEmpty() || option.matches()
                && q.parts.isEmpty() && optionLettersExpected(q, option.group(1))) {
            q.optionTexts.put(option.group(1), option.group(2));
            return;
        }
        if (option.matches() && q.parts.isEmpty() && !q.figures.isEmpty()) {
            q.optionTexts.put(option.group(1), option.group(2));
            return;
        }
        if (option.matches() && q.parts.isEmpty()) {
            // candidate option (validated in hindsight when the question closes)
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

    private boolean optionLettersExpected(RawQuestion q, String letter) {
        int expectedIndex = q.optionTexts.size();
        String expected = String.valueOf((char) ('A' + expectedIndex));
        return expected.equals(letter) || letter.compareTo(expected) < 0;
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

    private void recordTotal(Matcher total, State state) {
        state.totals.put(Integer.parseInt(total.group(1)), Integer.parseInt(total.group(2)));
    }

    private void extractMeta(String text, State state) {
        Matcher paperRef = PAPER_REF.matcher(text);
        if (paperRef.find() && state.meta[3] == null) {
            state.meta[3] = paperRef.group(1);
        }
        if (state.meta[0] == null && text.contains("Pearson Edexcel")) {
            state.meta[0] = "Edexcel";
        }
        if (state.meta[4] == null && text.matches("(?i)^(Summer|January|June|October|May|March)\\s+20\\d{2}$")) {
            state.meta[4] = text;
        }
        if (state.meta[6] == null && text.toLowerCase().contains("time:")
                && text.toLowerCase().contains("minutes")) {
            state.meta[6] = text.replaceAll("\\s+", " ").strip();
        }
        if (state.meta[5] == null && text.matches(
                "(?i)^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\\s+\\d{1,2}\\s+"
                        + "(January|February|March|April|May|June|July|August|September|October|"
                        + "November|December)\\s+20\\d{2}$")) {
            state.meta[5] = text;
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

    private PaperMeta paperMeta(CanonicalDocument doc, State state) {
        return new PaperMeta(
                state.meta[0] == null && state.meta[3] != null ? "Edexcel" : state.meta[0],
                state.meta[1], state.meta[2], state.meta[3], state.meta[4], state.meta[5],
                state.meta[6], doc.documentId());
    }

    // ── figures and tables ─────────────────────────────────────────────────────

    private void handleFigure(FigureElement figure, State state) {
        FigureRef ref = new FigureRef(figure.elementId(), figure.sourceName(), figure.format(),
                figure.text(), FIGURE_UNAVAILABLE);
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
        int marks = allMarksKnown ? partMarks
                : totalFromPaper != null ? totalFromPaper
                : mcq ? 1 : 0;

        double confidence = mcq ? 0.8
                : allMarksKnown ? 0.75
                : totalFromPaper != null ? 0.6 : 0.45;

        return new QuestionDraft(questionId, raw.number, raw.numberingStyle, raw.section,
                raw.stem.toString().strip(), mcq, options, parts, raw.figures,
                raw.tableElementIds, marks, allMarksKnown || totalFromPaper != null, raw.qwc,
                confidence);
    }

    private String shortId(String docId) {
        return docId == null ? "doc" : docId.substring(0, Math.min(8, docId.length()));
    }
}
