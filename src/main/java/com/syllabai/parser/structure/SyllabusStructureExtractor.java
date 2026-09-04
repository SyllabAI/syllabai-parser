package com.syllabai.parser.structure;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.SectionInfo;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.structure.dto.CurriculumDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.DraftProvenance;
import com.syllabai.parser.structure.dto.CurriculumDraft.SubjectDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.TopicDraft;
import com.syllabai.parser.structure.dto.CurriculumDraft.UnitDraft;
import java.util.ArrayList;
import java.util.List;

/**
 * T-010 (parser side): heading-level curriculum structure from a generic syllabus
 * canonical document. Heuristic v0 — level-1 headings map to units, level-2 to
 * topics, level-3+ to nested subtopics. Codes are generated deterministically
 * (U1 / U1-T1 / U1-T1-S1). Confidence is low (0.5) because heading levels are
 * font-derived and front matter regularly pollutes level-1 — boards with
 * numbered outlines should use {@link EdexcelSyllabusOutlineExtractor}.
 * Output is always SUGGESTED: the knowledge-graph seed that syllabai-core
 * derives from it must pass human validation before becoming VALIDATED.
 */
public final class SyllabusStructureExtractor {

    public static final String EXTRACTION_METHOD = "heading-heuristic-v0";

    private static final double HEURISTIC_CONFIDENCE = 0.5;

    /**
     * @param syllabus      canonical document of the specification
     * @param board         e.g. "Edexcel"
     * @param qualification e.g. "IAL"
     * @param code          curriculum code, e.g. "WCH11"
     * @param title         curriculum title
     * @param subjectCode   subject code, e.g. "CH"
     * @param subjectName   subject display name
     */
    public CurriculumDraft extract(CanonicalDocument syllabus, String board,
                                   String qualification, String code, String title,
                                   String subjectCode, String subjectName) {
        List<UnitDraft> units = new ArrayList<>();
        int unitCounter = 0;

        for (SectionInfo section : syllabus.sections()) {
            int level = section.level();
            String name = section.title() == null ? "" : section.title().strip();
            if (name.isEmpty()) {
                continue;
            }
            if (level <= 1) {
                unitCounter++;
                units.add(newUnit(unitCounter, name, section));
            } else if (!units.isEmpty()) {
                addSectionUnder(units.getLast(), level, name, section);
            }
        }

        return new CurriculumDraft(CurriculumDraft.SCHEMA_VERSION, board, qualification,
                code, title, new SubjectDraft(subjectCode, subjectName), units,
                new DraftProvenance(syllabus.documentId(), syllabus.source().checksum(),
                        syllabus.provenance().engine(), syllabus.provenance().engineVersion(),
                        EXTRACTION_METHOD, "SUGGESTED"));
    }

    private UnitDraft newUnit(int number, String title, SectionInfo section) {
        return new UnitDraft("U" + number, title, new ArrayList<>(),
                section.sectionId(), elementIds(section), section.pageNumber(),
                HEURISTIC_CONFIDENCE);
    }

    /**
     * Level-2 lands under the unit as a topic; each deeper level descends one
     * node through LAST children — so consecutive same-level headings stay
     * siblings (v0 semantics), one level deeper nests. A heading deeper than
     * the existing chain clamps to the deepest list (v0 tolerance).
     */
    private void addSectionUnder(UnitDraft unit, int level, String name, SectionInfo section) {
        List<TopicDraft> target = unit.topics();
        String prefix = unit.code() + "-T";
        for (int depth = 2; depth < level && !target.isEmpty(); depth++) {
            TopicDraft last = target.getLast();
            target = last.subtopics();
            prefix = last.code() + "-S";
        }
        target.add(new TopicDraft(nextCode(target, prefix), name, new ArrayList<>(),
                section.sectionId(), elementIds(section), section.pageNumber(),
                HEURISTIC_CONFIDENCE));
    }

    /** Next deterministic sibling code: prefix + (max sibling suffix + 1). */
    private String nextCode(List<TopicDraft> siblings, String prefix) {
        int max = 0;
        for (TopicDraft sibling : siblings) {
            String code = sibling.code();
            if (code.startsWith(prefix)) {
                String suffix = code.substring(prefix.length());
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

    private List<String> elementIds(SectionInfo section) {
        return section.elementIds() == null ? List.of() : List.copyOf(section.elementIds());
    }

    /** Utility used by tests and tools to build synthetic syllabus docs. */
    public static TextBlockElement heading(String elementId, int pageNumber, String text,
                                           int level, int readingOrder, String engine,
                                           String engineVersion) {
        return new TextBlockElement(elementId, pageNumber, null,
                text, readingOrder, 1.0, TextRole.HEADING, level,
                engine, engineVersion);
    }
}
