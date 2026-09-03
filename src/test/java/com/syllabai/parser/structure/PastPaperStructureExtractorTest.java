package com.syllabai.parser.structure;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalSchema;
import com.syllabai.parser.canonical.ExtractionProvenance;
import com.syllabai.parser.canonical.PageInfo;
import com.syllabai.parser.canonical.SourceInfo;
import com.syllabai.parser.canonical.TextBlockElement;
import com.syllabai.parser.canonical.TextRole;
import com.syllabai.parser.structure.dto.PastPaperDraft;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class PastPaperStructureExtractorTest {

    private static final String[] QP_LINES = {
            "1 A student heats copper(II) carbonate in a test tube.",
            "(a) State the colour change of the solid. (1)",
            "(b) Name the gas produced. (1)",
            "(Total for Question 1 = 2 marks)",
            "2 The diagram shows the electrolysis of molten lead bromide.",
            "(a) Explain why lead bromide must be molten for electrolysis. (2)",
            "(b) Write the half-equation at the cathode. (2)",
            "(i) the first part of a two-mark sub-item (1)",
            "(Total for Question 2 = 5 marks)",
            "3 Copper is extracted from its ore by heating with carbon.",
            "State the type of reaction involved. (1)",
            "Turn over"
    };

    private static final String[] MS_LINES = {
            "1 (a) an answer that makes reference to brown (1)",
            "(b) carbon dioxide (1)",
            "2 (a) an explanation that makes reference to ions cannot move (1)",
            "and so cannot carry charge (1)",
            "(b) Pb2+ + 2e- → Pb (1)",
            "3 reduction (1)",
            "Total for Question 2 = 5 marks"
    };

    @Test
    @DisplayName("extracts questions, letter parts, marks and command words from a QP")
    void extractsQuestions() {
        PastPaperDraft draft = new PastPaperStructureExtractor()
                .extract(questionPaper(QP_LINES), null, "Edexcel", "IGCSE",
                        "Chemistry", "Paper 1C", "January 2012", "4CH0/1C");

        assertThat(draft.questions()).hasSize(3);
        assertThat(draft.reviewRequired()).isTrue();
        assertThat(draft.extractionMethod())
                .isEqualTo(PastPaperStructureExtractor.EXTRACTION_METHOD);

        PastPaperDraft.QuestionDraft q1 = draft.questions().get(0);
        assertThat(q1.questionNumber()).isEqualTo("1");
        assertThat(q1.prompt()).startsWith("A student heats");
        assertThat(q1.marks()).isEqualTo(2);
        assertThat(q1.parts()).hasSize(2);
        assertThat(q1.parts().get(0).label()).isEqualTo("a");
        assertThat(q1.parts().get(0).commandWord()).isEqualTo("state");
        assertThat(q1.parts().get(0).marks()).isEqualTo(1);
        assertThat(q1.parts().get(1).label()).isEqualTo("b");
        assertThat(q1.parts().get(1).marks()).isEqualTo(1);
        assertThat(q1.questionType()).isEqualTo("STRUCTURED");

        PastPaperDraft.QuestionDraft q2 = draft.questions().get(1);
        assertThat(q2.marks()).isEqualTo(5);   // parts 2 + 2 + sub-item 1 = 5
        assertThat(q2.parts()).hasSize(3);     // a, b, b-i
        assertThat(q2.parts().get(2).label()).isEqualTo("b-i");

        PastPaperDraft.QuestionDraft q3 = draft.questions().get(2);
        assertThat(q3.parts()).isEmpty();
        assertThat(q3.questionType()).isEqualTo("SHORT_ANSWER");
        assertThat(q3.marks()).isEqualTo(1);
        assertThat(q3.commandWord()).isEqualTo("state");
    }

    @Test
    @DisplayName("mark-scheme points are keyed to question parts with marks")
    void extractsMarkScheme() {
        CanonicalDocument qp = questionPaper(QP_LINES);
        CanonicalDocument ms = markScheme(MS_LINES);
        PastPaperDraft draft = new PastPaperStructureExtractor()
                .extract(qp, ms, "Edexcel", "IGCSE", "Chemistry", "Paper 1C",
                        "January 2012", "4CH0/1C");

        assertThat(draft.markScheme()).isNotNull();
        assertThat(draft.markScheme().points()).isNotEmpty();
        assertThat(draft.markScheme().points())
                .anySatisfy(p -> {
                    assertThat(p.questionRef()).isEqualTo("1-a");
                    assertThat(p.text()).contains("brown");
                    assertThat(p.marks()).isEqualTo(1);
                });
        assertThat(draft.markScheme().points())
                .anySatisfy(p -> assertThat(p.questionRef()).isEqualTo("3"));
        assertThat(draft.paper().questionPaperDocumentId()).isEqualTo(qp.documentId());
        assertThat(draft.paper().markSchemeDocumentId()).isEqualTo(ms.documentId());
    }

    // ── fixtures ───────────────────────────────────────────────────────────────

    private CanonicalDocument questionPaper(String[] lines) {
        return textDocument("qp", lines);
    }

    private CanonicalDocument markScheme(String[] lines) {
        return textDocument("ms", lines);
    }

    private CanonicalDocument textDocument(String prefix, String[] lines) {
        List<TextBlockElement> blocks = new ArrayList<>();
        for (int i = 0; i < lines.length; i++) {
            blocks.add(new TextBlockElement("e" + String.format("%06d", i), 1, null,
                    lines[i], i, 1.0, TextRole.PARAGRAPH, null, "synthetic", "1"));
        }
        return new CanonicalDocument("synthetic-" + prefix + "-1", CanonicalSchema.VERSION, 1,
                new SourceInfo("test://" + prefix + ".pdf", "c".repeat(64), "SHA-256",
                        "application/pdf", prefix + ".pdf"),
                1, List.of(new PageInfo(1)), List.of(), blocks, List.of(), List.of(),
                List.of(),
                new ExtractionProvenance("synthetic", "1", Instant.EPOCH, Map.of(),
                        "syllabai-parser", CanonicalSchema.VERSION));
    }
}
