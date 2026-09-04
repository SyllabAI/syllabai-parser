package com.syllabai.parser.structure;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.SectionInfo;
import com.syllabai.parser.structure.dto.CurriculumDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.DraftProvenance;
import com.syllabai.parser.structure.dto.CurriculumDraft.SubjectDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.TopicDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.UnitDraft;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * T-010: deterministic outline extraction for Edexcel-numbered specifications.
 *
 * <p>Edexcel IAL/IGCSE specs are not level-structured (heading levels are
 * font-derived), but their numbering is highly regular:
 * {@code Unit N: ...}, {@code Topic N: ...}, {@code NC: ...} (subtopic of
 * topic N). This extractor matches those patterns, ignores everything else
 * (front matter, assessment information, appendices) and — crucially —
 * never invents hierarchy: a node exists only where the spec itself prints a
 * numbered heading, and every node carries the source element ids, page and
 * an extraction confidence for downstream provenance (Master Spec §7/§17).
 * Output is always SUGGESTED; only teacher validation in syllabai-core can
 * promote it.</p>
 *
 * <p>Confidence rationale (documented, not tuned): unit/topic headings
 * matched against the strict {@code ^Unit N:} / {@code ^Topic N:} patterns
 * are 0.95 — headings occasionally absorb trailing body text; subtopics
 * ({@code ^NC:}) are 0.85 — the pattern is shorter and noisier.</p>
 */
public final class EdexcelSyllabusOutlineExtractor {

    public static final String EXTRACTION_METHOD = "edexcel-numbered-outline-v1";

    private static final Pattern UNIT = Pattern.compile("^Unit\\s+(\\d+)\\s*[:\\u2013-]?\\s*(.+)$");
    private static final Pattern TOPIC = Pattern.compile("^Topic\\s+(\\d+)\\s*[:\\u2013-]?\\s*(.+)$");
    private static final Pattern SUBTOPIC = Pattern.compile("^(\\d+)\\s*([A-Z])\\s*[:\\u2013-]?\\s*(.+)$");
    private static final Pattern ASSESSED_NOISE =
            Pattern.compile("\\s*Students?\\s+will\\s+be\\s+assessed.*", Pattern.CASE_INSENSITIVE);

    private static final double UNIT_TOPIC_CONFIDENCE = 0.95;
    private static final double SUBTOPIC_CONFIDENCE = 0.85;
    private static final int TITLE_BOUND = 200;

    /**
     * @param syllabus      canonical document of the specification
     * @param board         e.g. "Edexcel"
     * @param qualification e.g. "IAL"
     * @param code          curriculum code, e.g. "IAL-CHEM-2018"
     * @param title         curriculum title
     * @param subjectCode   subject code, e.g. "CH"
     * @param subjectName   subject display name
     */
    public CurriculumDraft extract(CanonicalDocument syllabus, String board,
                                   String qualification, String code, String title,
                                   String subjectCode, String subjectName) {
        // mutable working copies; frozen into immutable drafts on build()
        List<MutableUnit> units = new ArrayList<>();
        Set<Integer> seenUnits = new HashSet<>();
        Set<Integer> seenTopics = new HashSet<>();

        MutableUnit currentUnit = null;
        MutableTopic currentTopic = null;

        for (SectionInfo section : syllabus.sections()) {
            String raw = section.title() == null ? "" : section.title().strip();
            if (raw.isEmpty()) {
                continue;
            }
            Matcher unitMatch = UNIT.matcher(raw);
            if (unitMatch.find()) {
                int number = parseInt(unitMatch.group(1));
                String unitTitle = cleanTitle(unitMatch.group(2));
                if (seenUnits.add(number) && !unitTitle.isBlank()) {
                    currentUnit = new MutableUnit(number, unitTitle, section);
                    units.add(currentUnit);
                    currentTopic = null;
                }
                // duplicate unit number (e.g. a repeated TOC line) — first match wins
                continue;
            }
            Matcher topicMatch = TOPIC.matcher(raw);
            if (topicMatch.find() && currentUnit != null) {
                int number = parseInt(topicMatch.group(1));
                String topicTitle = cleanTitle(topicMatch.group(2));
                if (seenTopics.add(number) && !topicTitle.isBlank()) {
                    currentTopic = new MutableTopic(currentUnit.topicCode(number), topicTitle,
                            section, UNIT_TOPIC_CONFIDENCE);
                    currentUnit.addTopic(currentTopic);
                }
                continue;
            }
            Matcher subtopicMatch = SUBTOPIC.matcher(raw);
            if (subtopicMatch.find() && currentUnit != null && currentTopic != null) {
                int topicNumber = parseInt(subtopicMatch.group(1));
                String letter = subtopicMatch.group(2);
                // a real subtopic heading cites its own topic number (e.g. "3C" under
                // Topic 3); a mismatch is layout noise, never a cross-topic guess
                if (topicNumber == currentTopic.topicNumber() && !currentTopic.hasSubtopic(letter)) {
                    String subtopicTitle = cleanTitle(subtopicMatch.group(3));
                    if (!subtopicTitle.isBlank()) {
                        currentTopic.addSubtopic(new MutableTopic(
                                currentTopic.code() + "-" + letter, subtopicTitle,
                                section, SUBTOPIC_CONFIDENCE));
                    }
                }
            }
        }

        return new CurriculumDraft(CurriculumDraft.SCHEMA_VERSION, board, qualification,
                code, title, new SubjectDraft(subjectCode, subjectName),
                units.stream().map(MutableUnit::build).toList(),
                new DraftProvenance(syllabus.documentId(), syllabus.source().checksum(),
                        syllabus.provenance().engine(), syllabus.provenance().engineVersion(),
                        EXTRACTION_METHOD, "SUGGESTED"));
    }

    private String cleanTitle(String raw) {
        String cleaned = ASSESSED_NOISE.matcher(raw).replaceFirst("").strip();
        // NB: trailing digits are NOT stripped — real titles can end in numbers
        // ("Redox Chemistry and Groups 1, 2 and 7"); TOC noise is handled by
        // the first-match-wins number dedup, not title guessing
        cleaned = cleaned.replaceAll("[:\\u2013-]+$", "").strip();
        return cleaned.length() > TITLE_BOUND ? cleaned.substring(0, TITLE_BOUND) : cleaned;
    }

    private int parseInt(String digits) {
        try {
            return Integer.parseInt(digits);
        } catch (NumberFormatException e) {
            return -1;   // regex guarantees digits; defensive only
        }
    }

    /** Mutable working state for a unit while walking sections in order. */
    private static final class MutableUnit {
        private final int number;
        private final String title;
        private final String sourceSectionId;
        private final List<String> sourceElementIds;
        private final int pageNumber;
        private final List<MutableTopic> topics = new ArrayList<>();

        MutableUnit(int number, String title, SectionInfo source) {
            this.number = number;
            this.title = title;
            this.sourceSectionId = source.sectionId();
            this.sourceElementIds = source.elementIds() == null
                    ? List.of() : List.copyOf(source.elementIds());
            this.pageNumber = source.pageNumber();
        }

        void addTopic(MutableTopic topic) {
            topics.add(topic);
        }

        String topicCode(int topicNumber) {
            return "U" + number + "-T" + topicNumber;
        }

        UnitDraft build() {
            return new UnitDraft("U" + number, title,
                    topics.stream().map(MutableTopic::build).toList(),
                    sourceSectionId, sourceElementIds, pageNumber, UNIT_TOPIC_CONFIDENCE);
        }
    }

    /** Mutable working state for a topic/subtopic. */
    private static final class MutableTopic {
        private final String code;
        private final String title;
        private final List<String> sourceElementIds;
        private final int pageNumber;
        private final List<MutableTopic> subtopics = new ArrayList<>();
        private final int topicNumber;
        private final double confidence;
        private final String sourceSectionId;

        MutableTopic(String code, String title, SectionInfo source, double confidence) {
            this.code = code;
            this.title = title;
            this.sourceSectionId = source.sectionId();
            this.sourceElementIds = source.elementIds() == null
                    ? List.of() : List.copyOf(source.elementIds());
            this.pageNumber = source.pageNumber();
            this.topicNumber = parseTopicNumber(code);
            this.confidence = confidence;
        }

        void addSubtopic(MutableTopic subtopic) {
            subtopics.add(subtopic);
        }

        boolean hasSubtopic(String letter) {
            return subtopics.stream().anyMatch(s -> s.code().endsWith("-" + letter));
        }

        int topicNumber() {
            return topicNumber;
        }

        String code() {
            return code;
        }

        TopicDraft build() {
            return new TopicDraft(code, title,
                    subtopics.stream().map(MutableTopic::build).toList(),
                    sourceSectionId, sourceElementIds, pageNumber, confidence);
        }

        private int parseTopicNumber(String code) {
            int at = code.lastIndexOf("-T");
            if (at < 0) {
                return -1;   // subtopic — number validated by the caller instead
            }
            try {
                return Integer.parseInt(code.substring(at + 2));
            } catch (NumberFormatException e) {
                return -1;
            }
        }
    }
}
