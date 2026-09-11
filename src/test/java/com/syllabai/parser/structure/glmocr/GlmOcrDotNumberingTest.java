package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * "N." numbering style hardening (2011-June / Specimen-2017 exports). The
 * digit-period style must open questions (the old engine extracted exactly
 * ONE question from the 2011-Jun paper), while OCR-broken decimal quantities
 * ("25.0 cm3" → "25. 0 cm3…") must never open one. Sequence checking and the
 * stem-plausibility guard together give both properties.
 */
class GlmOcrDotNumberingTest {

    private final GlmOcrQuestionExtractor extractor = new GlmOcrQuestionExtractor();

    private GlmOcrPaperDraft extract(String markdown) {
        GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
        return extractor.extract(parser.parseWithFixedIdentity(
                markdown.getBytes(StandardCharsets.UTF_8), "corpus/sample.md",
                java.time.Instant.EPOCH));
    }

    @Test
    @DisplayName("2011-Jun shape: space-style q1 followed by dot-style q2 with part label")
    void dotStyleOpensQuestionAfterSpaceStyle() {
        GlmOcrPaperDraft draft = extract("""
                # Pearson Edexcel Level 1/Level 2 GCSE Chemistry

                1 Atoms contain three different types of particle. These are electrons, protons and neutrons.
                (a) Complete the sentence.
                (b) Name the third type of particle.
                (Total for Question 1 = 4 marks)

                2. (a) Substances can be classified as elements, compounds or mixtures.
                Each of the diagrams below represents either an element, a compound or a mixture.
                (b) State which one is represented by diagram 1.
                (Total for Question 2 = 6 marks)
                """);
        assertThat(draft.questions()).hasSize(2);
        GlmOcrPaperDraft.QuestionDraft q2 = draft.questions().get(1);
        assertThat(q2.number()).isEqualTo(2);
        assertThat(q2.numberingStyle()).isEqualTo("dot");
        assertThat(q2.stem()).startsWith("(a) Substances can be classified");
        assertThat(draft.questionTotals()).containsEntry("2", 6);
    }

    @Test
    @DisplayName("dot-style stem starting with a capital letter opens normally")
    void dotStyleWithCapitalStem() {
        GlmOcrPaperDraft draft = extract("""
                1 First question stem
                (a) part
                (Total for Question 1 = 2 marks)

                2. Some iron(II) sulfate was heated in a test tube.
                (Total for Question 2 = 3 marks)
                """);
        assertThat(draft.questions()).hasSize(2);
        assertThat(draft.questions().get(1).numberingStyle()).isEqualTo("dot");
        assertThat(draft.questions().get(1).stem()).isEqualTo(
                "Some iron(II) sulfate was heated in a test tube.");
    }

    @Test
    @DisplayName("REGRESSION: OCR-broken decimals never open questions")
    void decimalFragmentsRejected() {
        GlmOcrPaperDraft draft = extract("""
                # Instructions

                1. 0 mol/dm3 of acid was measured before the first real question.

                1 Real first question stem
                (a) part
                25. 0 cm3 of gas were produced during the reaction.
                (Total for Question 1 = 3 marks)

                2. (a) Substances can be classified as elements, compounds or mixtures.
                (Total for Question 2 = 4 marks)
                """);
        assertThat(draft.questions()).hasSize(2);
        assertThat(draft.questions().get(0).number()).isEqualTo(1);
        assertThat(draft.questions().get(0).stem()).isEqualTo("Real first question stem");
        assertThat(draft.questions().get(1).number()).isEqualTo(2);
        // the decimal fragments stayed attached to question text, not invented questions
        assertThat(draft.warnings().stream().noneMatch(w -> w.startsWith("Q25"))).isTrue();
    }

    @Test
    @DisplayName("dot-numbered question promoted to a Markdown heading still opens")
    void dotStylePromotedToHeading() {
        GlmOcrPaperDraft draft = extract("""
                1 First question stem
                (Total for Question 1 = 2 marks)

                ## 2. The diagram shows the electrolysis of molten lead bromide.

                (a) Describe what is seen at the cathode.
                """);
        assertThat(draft.questions()).hasSize(2);
        assertThat(draft.questions().get(1).number()).isEqualTo(2);
        assertThat(draft.questions().get(1).numberingStyle()).isEqualTo("dot");
        assertThat(draft.warnings()).anyMatch(
                w -> w.equals("Q2: question number promoted to heading (opened from heading)"));
    }
}
