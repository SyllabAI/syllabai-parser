package com.syllabai.parser.structure;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.DocumentElement;
import com.syllabai.parser.canonical.TableElement;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.structure.dto.PastPaperDraft;
import com.syllabai.parser.structure.dto.PastPaperDraft.MarkPointDraft;
import com.syllabai.parser.structure.dto.PastPaperDraft.MarkSchemeDraft;
import com.syllabai.parser.structure.dto.PastPaperDraft.PaperMeta;
import com.syllabai.parser.structure.dto.PastPaperDraft.PartDraft;
import com.syllabai.parser.structure.dto.PastPaperDraft.QuestionDraft;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * T-011 (parser side): regex-heuristic extraction of question/part structure
 * from a past-paper canonical document, and of mark points from a mark-scheme
 * canonical document. <strong>v0 honesty:</strong> everything carries a
 * confidence &lt; 1.0 and {@code reviewRequired=true}; downstream ingestion
 * persists SUGGESTED rows awaiting human validation (Master Spec §7:
 * algorithmically suggested structure must be distinguishable from validated).
 *
 * <p>Patterns target Edexcel IGCSE/IAL layout conventions:</p>
 * <ul>
 *   <li>question starts: {@code "3 Some text …"} / {@code "3) …"}</li>
 *   <li>letter parts: {@code "(a) …"}; roman subparts: {@code "(i) …"}</li>
 *   <li>trailing marks: {@code "… (2)"}; question totals:
 *       {@code "Total for Question 3 = 12 marks"}</li>
 *   <li>mark-scheme points: {@code "3 (a)(i) point text (1)"}</li>
 * </ul>
 */
public final class PastPaperStructureExtractor {

    public static final String EXTRACTION_METHOD = "qp-ms-regex-v0";

    private static final Pattern QUESTION_START =
            Pattern.compile("^\\*{0,2}(\\d{1,2})\\*{0,2}\\)?[.\\s]\\s*(.*)$");
    private static final Pattern LETTER_PART = Pattern.compile("^\\(([a-h])\\)\\s*(.*)$");
    private static final Pattern ROMAN_PART = Pattern.compile("^\\(((?:i{1,3}|iv|v|vi{1,3}|ix|x))\\)\\s*(.*)$");
    private static final Pattern TRAILING_MARKS = Pattern.compile("\\((\\d{1,2})\\)\\s*$");
    private static final Pattern TOTAL_FOR_QUESTION = Pattern.compile(
            "[(*\\s]*Total for Question\\s+(\\d{1,2})\\s*=\\s*(\\d{1,3})\\s*marks[^)]*\\)?",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern MS_POINT = Pattern.compile(
            "^(\\d{1,2})\\s*(?:\\(([a-h])\\))?(?:\\(((?:i{1,3}|iv|v|vi{1,3}|ix|x))\\))?\\s*(.*)$");
    /** IGCSE mark-scheme layout: "9 d i M1 answer text" / "10 b M2 text". */
    private static final Pattern MS_POINT_IGCSE = Pattern.compile(
            "^(\\d{1,2})\\s+([a-h])\\s+((?:i{1,3}|iv|v|vi{1,3}|ix|x))?\\s*(?:(M\\d)\\s+)?(.*)$");
    /** Continuation mark point: "M2 further answer text". */
    private static final Pattern MS_CONTINUATION_M = Pattern.compile("^(M\\d)\\s+(.*)$");
    /** Continuation subpart: "ii M1 answer text". */
    private static final Pattern MS_CONTINUATION_ROMAN = Pattern.compile(
            "^((?:i{1,3}|iv|v|vi{1,3}|ix|x))\\s+(?:(M\\d)\\s+)?(.*)$");
    /** Continuation letter part: "(b) answer text". */
    private static final Pattern MS_CONTINUATION_LETTER = Pattern.compile(
            "^\\(([a-h])\\)\\s*(.*)$");
    /** Bare question-level point: "3 reduction (1)". */
    private static final Pattern MS_BARE_QUESTION = Pattern.compile(
            "^(\\d{1,2})\\s+(?:(M\\d)\\s+)?(.+)$");
    private static final Pattern EXPLICIT_MARKS = Pattern.compile(
            "(?:=(\\d)|\\((\\d)\\)|(^|\\s)(\\d)\\s*marks?)(?:\\s|$)", Pattern.CASE_INSENSITIVE);
    private static final Pattern NOISE = Pattern.compile(
            "^(Turn over|BLANK PAGE|Advice|TOTAL FOR PAPER.*|Paper Reference.*|"
                    + "Questions and answers.*|You must have.*|There are.*questions.*|"
                    + "Answer ALL questions.*)\\s*$", Pattern.CASE_INSENSITIVE);

    /** Question stems matching this are command-word bare — not counted as noise. */

    public PastPaperDraft extract(CanonicalDocument questionPaper,
                                  CanonicalDocument markScheme,
                                  String board, String qualification, String subject,
                                  String unit, String sessionLabel, String paperCode) {
        List<QuestionDraft> questions = extractQuestions(questionPaper);
        MarkSchemeDraft scheme = markScheme == null ? null : extractMarkScheme(markScheme);
        return new PastPaperDraft(PastPaperDraft.SCHEMA_VERSION,
                new PaperMeta(board, qualification, subject, unit, sessionLabel, paperCode,
                        questionPaper.documentId(),
                        markScheme == null ? null : markScheme.documentId()),
                questions, scheme, EXTRACTION_METHOD, true);
    }

    // ── question paper ─────────────────────────────────────────────────────────

    List<QuestionDraft> extractQuestions(CanonicalDocument paper) {
        List<RawQuestion> raw = segment(paper);
        List<QuestionDraft> result = new ArrayList<>();
        for (RawQuestion q : raw) {
            result.add(toDraft(q, paper.documentId()));
        }
        return result;
    }

    private List<RawQuestion> segment(CanonicalDocument paper) {
        List<RawQuestion> questions = new ArrayList<>();
        RawQuestion current = null;
        java.util.Map<String, Integer> totals = new java.util.HashMap<>();

        // Unified line stream: text blocks AND table rows — Edexcel mark schemes
        // keep their answers inside tables, question papers keep answer boxes in
        // tables. All engine role classifications are consumed; the regexes, not
        // the role, decide structure (ODL classifies sparse lines as headings).
        for (Line line : lines(paper)) {
            String text = line.text().strip();
            if (text.isEmpty() || NOISE.matcher(text).matches()) {
                continue;
            }
            // "(Total for Question 3 = 12 marks)" can be its own line OR merged
            // into the previous part's chunk by the engine — strip it wherever
            // it appears, record the total, and keep any remainder.
            Matcher total = TOTAL_FOR_QUESTION.matcher(text);
            if (total.find()) {
                totals.put(total.group(1), Integer.parseInt(total.group(2)));
                text = (text.substring(0, total.start()) + text.substring(total.end())).strip();
                if (text.isEmpty()) {
                    continue;
                }
            }
            Matcher questionStart = QUESTION_START.matcher(text);
            if (questionStart.matches()) {
                int number = Integer.parseInt(questionStart.group(1));
                current = new RawQuestion(number, line.pageNumber());
                current.stem.append(questionStart.group(2));
                questions.add(current);
                continue;
            }
            if (current == null) {
                continue;   // preamble/footer before the first question
            }
            Matcher letterPart = LETTER_PART.matcher(text);
            if (letterPart.matches()) {
                current.parts.add(new RawPart(letterPart.group(1), letterPart.group(2)));
                continue;
            }
            Matcher romanPart = ROMAN_PART.matcher(text);
            if (romanPart.matches() && !current.parts.isEmpty()) {
                String parentLabel = current.parts.getLast().label;
                String label = parentLabel.replaceFirst("(-.*)?$", "") + "-" + romanPart.group(1);
                current.parts.add(new RawPart(label, romanPart.group(2)));
                continue;
            }
            // continuation of the current part (or stem when no parts yet)
            if (current.parts.isEmpty()) {
                if (current.stem.length() > 0) {
                    current.stem.append(' ');
                }
                current.stem.append(text);
            } else {
                RawPart part = current.parts.getLast();
                if (!part.text.isEmpty()) {
                    part.text.append(' ');
                }
                part.text.append(text);
            }
        }
        for (RawQuestion q : questions) {
            Integer total = totals.get(Integer.toString(q.number));
            if (total != null) {
                q.totalFromPaper = total;
            }
        }
        return questions;
    }

    private QuestionDraft toDraft(RawQuestion raw, String documentId) {
        List<PartDraft> parts = new ArrayList<>();
        int partMarks = 0;
        boolean allMarksKnown = !raw.parts.isEmpty();
        for (RawPart part : raw.parts) {
            String text = part.text.toString().strip();
            int marks = trailingMarks(text);
            String stripped = stripTrailingMarks(text);
            Optional<String> commandWord = CommandWordLexicon.extract(stripped);
            partMarks += marks;
            if (marks <= 0) {
                allMarksKnown = false;
            }
            parts.add(new PartDraft(part.label, stripped, commandWord.orElse(null), marks,
                    confidence(marks > 0, commandWord.isPresent())));
        }

        String stem = stripTrailingMarks(raw.stem.toString().strip());
        Optional<String> stemCommand = CommandWordLexicon.extract(stem);
        int stemMarks = trailingMarks(raw.stem.toString().strip());
        int marks = !parts.isEmpty()
                ? (allMarksKnown ? partMarks : raw.totalFromPaper)
                : (stemMarks > 0 ? stemMarks : raw.totalFromPaper);
        String type = parts.isEmpty() ? "SHORT_ANSWER" : "STRUCTURED";
        double confidence = !parts.isEmpty()
                ? (allMarksKnown ? 0.8 : 0.55)
                : (marks > 0 ? 0.7 : 0.5);

        return new QuestionDraft("q" + raw.number + "-" + shortId(documentId),
                Integer.toString(raw.number), stem, stemCommand.orElse(null),
                Math.max(marks, 0), type, raw.pageNumber, confidence, parts);
    }

    // ── mark scheme ────────────────────────────────────────────────────────────

    MarkSchemeDraft extractMarkScheme(CanonicalDocument markScheme) {
        List<MarkPointDraft> points = new ArrayList<>();
        java.util.Map<String, Integer> orderInPart = new java.util.HashMap<>();
        String lastBaseRef = null;   // e.g. "9-d"
        String lastFullRef = null;   // e.g. "9-d-i"
        String lastQuestionNumber = null;
        for (Line line : lines(markScheme)) {
            String text = line.text().strip();
            if (text.isEmpty() || NOISE.matcher(text).matches()) {
                continue;
            }
            Matcher total = TOTAL_FOR_QUESTION.matcher(text);
            if (total.find()) {
                text = (text.substring(0, total.start()) + text.substring(total.end())).strip();
                if (text.isEmpty()) {
                    continue;
                }
            }

            String ref = null;
            String body = null;
            Matcher igcse = MS_POINT_IGCSE.matcher(text);
            Matcher ial = MS_POINT.matcher(text);
            Matcher continuationRoman = MS_CONTINUATION_ROMAN.matcher(text);
            Matcher continuationM = MS_CONTINUATION_M.matcher(text);
            Matcher continuationLetter = MS_CONTINUATION_LETTER.matcher(text);
            Matcher bareQuestion = MS_BARE_QUESTION.matcher(text);

            if (igcse.matches()) {
                // "9 d i M1 answer" → ref 9-d(-i)
                ref = igcse.group(1) + "-" + igcse.group(2);
                if (igcse.group(3) != null) {
                    ref = ref + "-" + igcse.group(3);
                }
                body = igcse.group(5);
                lastBaseRef = igcse.group(1) + "-" + igcse.group(2);
                lastQuestionNumber = igcse.group(1);
            } else if (ial.matches() && ial.group(2) != null) {
                // "3 (a)(i) point text" — only when a letter part is present,
                // otherwise every numeric line would match
                ref = ial.group(1) + "-" + ial.group(2);
                if (ial.group(3) != null) {
                    ref = ref + "-" + ial.group(3);
                }
                body = ial.group(4);
                lastBaseRef = ial.group(1) + "-" + ial.group(2);
                lastQuestionNumber = ial.group(1);
            } else if (continuationRoman.matches() && lastBaseRef != null) {
                // "ii M1 answer" → continuation subpart of the last base
                ref = lastBaseRef + "-" + continuationRoman.group(1);
                body = continuationRoman.group(3);
            } else if (continuationM.matches() && lastFullRef != null) {
                // "M2 further text" → additional mark point of the last ref
                ref = lastFullRef;
                body = continuationM.group(2);
            } else if (continuationLetter.matches() && lastQuestionNumber != null) {
                // "(b) answer" → letter part of the last question
                ref = lastQuestionNumber + "-" + continuationLetter.group(1);
                body = continuationLetter.group(2);
                lastBaseRef = ref;
            } else if (bareQuestion.matches() && !continuationM.matches()) {
                // "3 reduction (1)" → question-level point
                ref = bareQuestion.group(1);
                body = bareQuestion.group(3);
                lastQuestionNumber = bareQuestion.group(1);
            }
            if (ref == null || body == null) {
                continue;
            }
            body = body.strip();
            int marks = explicitMarks(body);
            boolean marksDeduced = marks <= 0;
            if (marksDeduced) {
                // Edexcel IGCSE convention: one mark per M-point unless stated
                marks = 1;
            }
            if (body.isEmpty()) {
                continue;
            }
            lastFullRef = ref;
            int order = orderInPart.merge(ref, 1, Integer::sum);
            points.add(new MarkPointDraft(ref, order, body, marks, List.of(),
                    marksDeduced ? 0.55 : 0.7));
        }
        return new MarkSchemeDraft("1", markScheme.documentId(), points);
    }

    /** "(2)", "= 1" or "3 marks" when the line states them explicitly. */
    private int explicitMarks(String body) {
        Matcher matcher = EXPLICIT_MARKS.matcher(body);
        if (matcher.find()) {
            for (int group = 1; group <= matcher.groupCount(); group++) {
                if (matcher.group(group) != null && group != 3) {
                    try {
                        return Integer.parseInt(matcher.group(group));
                    } catch (NumberFormatException ignored) {
                        // fall through
                    }
                }
            }
        }
        return 0;
    }

    /** Unified per-line view of a canonical document (text blocks + table rows). */
    private List<Line> lines(CanonicalDocument document) {
        List<Line> lines = new ArrayList<>();
        for (DocumentElement element : document.elementsInReadingOrder()) {
            if (element instanceof TextBlockElement block) {
                String text = block.text();
                if (text != null && !text.isBlank()) {
                    lines.add(new Line(text, block.pageNumber()));
                }
            } else if (element instanceof TableElement table) {
                for (List<String> row : table.rows()) {
                    String joined = String.join(" ", row).strip()
                            .replaceAll("\\s+", " ");
                    if (!joined.isBlank()) {
                        lines.add(new Line(joined, table.pageNumber()));
                    }
                }
            }
        }
        return lines;
    }

    private record Line(String text, int pageNumber) {
    }

    // ── helpers ────────────────────────────────────────────────────────────────

    private int trailingMarks(String text) {
        Matcher matcher = TRAILING_MARKS.matcher(text);
        return matcher.find() ? Integer.parseInt(matcher.group(1)) : 0;
    }

    private String stripTrailingMarks(String text) {
        Matcher matcher = TRAILING_MARKS.matcher(text);
        return matcher.find() ? text.substring(0, matcher.start()).strip() : text;
    }

    private double confidence(boolean marksKnown, boolean commandWordKnown) {
        double c = 0.5;
        if (marksKnown) {
            c += 0.2;
        }
        if (commandWordKnown) {
            c += 0.1;
        }
        return Math.min(c, 0.9);
    }

    private String shortId(String documentId) {
        return documentId == null ? "doc"
                : documentId.substring(0, Math.min(8, documentId.length()));
    }

    private static final class RawQuestion {
        final int number;
        final int pageNumber;
        final StringBuilder stem = new StringBuilder();
        final List<RawPart> parts = new ArrayList<>();
        int totalFromPaper;

        RawQuestion(int number, int pageNumber) {
            this.number = number;
            this.pageNumber = pageNumber;
        }
    }

    private static final class RawPart {
        final String label;
        final StringBuilder text;

        RawPart(String label, String text) {
            this.label = label;
            this.text = new StringBuilder(text == null ? "" : text);
        }
    }
}
