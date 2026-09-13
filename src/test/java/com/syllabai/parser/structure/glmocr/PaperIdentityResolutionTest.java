package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PaperMeta;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * T-C04 r2 identity invariants, pinned permanently (operator directive 2026-09-13):
 * every printed-identity behaviour the 81-session campaign depended on must stay
 * exactly as shipped. The QP cover is the authoritative identity source; the
 * extractor reports what is PRINTED — honestly null when nothing is printed,
 * never a guessed code/session (the core identity gate quarantines such drafts).
 *
 * <p>Covers exercised here are the two real shapes: plain printed lines and the
 * newer table-template covers whose identity lives inside HTML table cells
 * (commits 0d8b72c / 180b2b2 / d095510 / 577eca6).</p>
 */
class PaperIdentityResolutionTest {

    private final GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
    private final GlmOcrQuestionExtractor extractor = new GlmOcrQuestionExtractor();

    private static final String ONE_QUESTION = """
            1 Name the product formed at the negative electrode.

            (Total for Question 1 = 1 mark)
            """;

    private GlmOcrPaperDraft extract(String markdown) {
        CanonicalDocument document = parser.parse(
                markdown.getBytes(StandardCharsets.UTF_8), "test/identity.md");
        return extractor.extract(document);
    }

    /** IGCSE-style table cover: identity inside table cells, session printed as a line. */
    private static String tableCover(String paperReferenceCell, String sessionLine) {
        return "<table><tr><td colspan=\"2\">Pearson Edexcel International GCSE</td></tr>"
                + "<tr><td colspan=\"2\">" + paperReferenceCell + "</td></tr>"
                + "<tr><td colspan=\"2\">" + sessionLine + "</td></tr>"
                + "<tr><td colspan=\"2\">Time: 1 hour</td></tr></table>\n"
                + ONE_QUESTION;
    }

    @Test
    @DisplayName("missing printed identity stays honestly null — no guessed code or session")
    void missingIdentityIsHonestNull() {
        GlmOcrPaperDraft draft = extract(ONE_QUESTION);

        PaperMeta meta = draft.paper();
        assertThat(meta).isNotNull();
        assertThat(meta.paperReference()).isNull();
        assertThat(meta.session()).isNull();
        // the parser never fabricates placeholders: nulls flow to the core
        // identity gate, which rejects the draft fail-closed (quarantine path)
    }

    @Test
    @DisplayName("table-template cover: identity is recovered from table cells")
    void tableTemplateCoverIdentity() {
        GlmOcrPaperDraft draft = extract(tableCover(
                "Paper Reference<br>4CH1/1C", "January 2016"));

        assertThat(draft.paper().paperReference()).isEqualTo("4CH1/1C");
        assertThat(draft.paper().session()).isEqualTo("January 2016");
    }

    @Test
    @DisplayName("<br> inside a cover cell is a printed line break — codes stay separate tokens")
    void brInsideCellIsPrintedLineBreak() {
        // the 2012-Jun defect shape: Certificate twin above the International GCSE
        // code, <br>-separated. Dropping <br> glues "KCH0/1C4CH0/1C" into one
        // token that defeats every line-based identity regex.
        GlmOcrPaperDraft draft = extract(tableCover(
                "Paper Reference<br>KCH0/1C<br>4CH0/1C", "June 2012"));

        assertThat(draft.paper().paperReference()).isEqualTo("4CH0/1C");
        assertThat(draft.paper().session()).isEqualTo("June 2012");
    }

    @Test
    @DisplayName("glued token soup (no <br>) yields an honest null, never a fabricated code")
    void gluedCodesStayUnmatched() {
        GlmOcrPaperDraft draft = extract(tableCover(
                "Paper Reference KCH0/1C4CH0/1C", "June 2012"));

        assertThat(draft.paper().paperReference()).isNull();
    }

    @Test
    @DisplayName("multiple printed codes: the printed International GCSE 4-prefixed code wins")
    void internationalGcseCodePreferredAmongSeveral() {
        // Certificate twin KCH0/1C + International GCSE 4CH1/1C on one cover
        GlmOcrPaperDraft certificateTwin = extract(tableCover(
                "Paper Reference<br>KCH0/1C 4CH1/1C", "January 2017"));
        assertThat(certificateTwin.paper().paperReference()).isEqualTo("4CH1/1C");

        // Double-Award companion codes printed after the chemistry code —
        // the FIRST printed 4-prefixed code is deterministic (2012-Jun case)
        GlmOcrPaperDraft multiCode = extract(tableCover(
                "Paper Reference<br>4CH1/1C 4SD0/1C 4SC0/1C", "June 2012"));
        assertThat(multiCode.paper().paperReference()).isEqualTo("4CH1/1C");
    }

    @Test
    @DisplayName("regional R papers: the R suffix is preserved, never truncated")
    void regionalRPaperCodePreserved() {
        GlmOcrPaperDraft draft = extract(tableCover(
                "Paper Reference<br>4CH1/1CR", "Summer 2019"));

        assertThat(draft.paper().paperReference()).isEqualTo("4CH1/1CR");
        assertThat(draft.paper().session()).isEqualTo("Summer 2019");
    }

    @Test
    @DisplayName("identity resolution is deterministic: same cover, same meta, twice")
    void identityResolutionIsDeterministic() {
        GlmOcrPaperDraft first = extract(tableCover(
                "Paper Reference<br>KCH0/2C 4CH0/2C", "January 2013"));
        GlmOcrPaperDraft second = extract(tableCover(
                "Paper Reference<br>KCH0/2C 4CH0/2C", "January 2013"));

        assertThat(second.paper().paperReference())
                .isEqualTo(first.paper().paperReference())
                .isEqualTo("4CH0/2C");
        assertThat(second.paper().session()).isEqualTo(first.paper().session());
    }
}
