package com.syllabai.parser.structure;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.structure.dto.CurriculumDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.DraftProvenance;
import com.syllabai.parser.structure.dto.CurriculumDraft.SubjectDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.TopicDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.UnitDraft;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * T-010 (parser side): heading-derived curriculum structure from a syllabus
 * canonical document. Heuristic v0 — level-1 headings map to units,
 * level-2 to topics, level-3 to subtopics. Codes are generated
 * deterministically (U1/U1-T1/U1-T1-S1). Output is always SUGGESTED:
 * the knowledge-graph seed that syllabai-core derives from it must pass
 * human validation before becoming VALIDATED.
 */
public final class SyllabusStructureExtractor {

    public static final String EXTRACTION_METHOD = "heading-heuristic-v0";

    private static final Pattern CODE_SAFE = Pattern.compile("[^A-Za-z0-9]+");

    /**
     * @param syllabus  canonical document of the specification
     * @param board     e.g. "Edexcel"
     * @param qualification e.g. "IAL"
     * @param code      curriculum code, e.g. "WCH11"
     * @param title     curriculum title
     * @param subjectCode subject code, e.g. "CH"
     * @param subjectName subject display name
     */
    public CurriculumDraft extract(CanonicalDocument syllabus, String board,
                                   String qualification, String code, String title,
                                   String subjectCode, String subjectName) {
        List<TopicDraft> topics = new ArrayList<>();
        List<UnitDraft> units = new ArrayList<>();
        int unitCounter = 0;

        for (var section : syllabus.sections()) {
            int level = section.level();
            String name = section.title() == null ? "" : section.title().strip();
            if (name.isEmpty()) {
                continue;
            }
            if (level <= 1) {
                unitCounter++;
                units.add(new UnitDraft("U" + unitCounter, name, new ArrayList<>()));
            } else if (!units.isEmpty()) {
                UnitDraft unit = units.getLast();
                List<TopicDraft> target = level == 2 ? unit.topics() : leafOf(unit);
                target.add(new TopicDraft(nextTopicCode(unit, target), name, new ArrayList<>()));
            }
        }

        return new CurriculumDraft(CurriculumDraft.SCHEMA_VERSION, board, qualification,
                code, title, new SubjectDraft(subjectCode, subjectName), units,
                new DraftProvenance(syllabus.documentId(), syllabus.source().checksum(),
                        syllabus.provenance().engine(), syllabus.provenance().engineVersion(),
                        EXTRACTION_METHOD, "SUGGESTED"));
    }

    private List<TopicDraft> leafOf(UnitDraft unit) {
        List<TopicDraft> topics = unit.topics();
        if (topics.isEmpty()) {
            return topics;
        }
        return topics.getLast().subtopics();
    }

    private String nextTopicCode(UnitDraft unit, List<TopicDraft> target) {
        String prefix = unit.code() + "-T";
        int max = 0;
        for (TopicDraft existing : target) {
            String existingCode = existing.code();
            if (existingCode.startsWith(prefix)) {
                String suffix = existingCode.substring(prefix.length());
                int dash = suffix.indexOf('-');
                if (dash > 0) {
                    suffix = suffix.substring(0, dash);
                }
                try {
                    max = Math.max(max, Integer.parseInt(suffix.replaceAll("\\D", "")));
                } catch (NumberFormatException ignored) {
                    // non-numeric sibling code — skip
                }
            }
        }
        return prefix + (max + 1);
    }

    /** Utility used by tests and tools to build synthetic syllabus docs. */
    public static TextBlockElement heading(String elementId, int pageNumber, String text,
                                           int level, int readingOrder, String engine,
                                           String engineVersion) {
        return new TextBlockElement(elementId, pageNumber, null, text, readingOrder,
                1.0, com.syllabai.parser.canonical.TextRole.HEADING, level, engine, engineVersion);
    }
}
