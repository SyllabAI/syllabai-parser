package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.FigureRef;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.PartDraft;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * OPT-IN local asset enrichment (T-C03 parser patch, 2026-09): figure
 * references resolving under --assets-dir become availability=available with
 * content-derived identity, unresolved references stay byte-identical (per-
 * field NON_NULL keeps absent asset fields out of the JSON), and the
 * resolution counts are honest.
 */
class GlmOcrAssetEnricherTest {

    // same fixtures as GlmOcrImageAssetsTest (single source of truth is the
    // sniffing logic itself, duplicated here to keep the tests independent)
    private static final byte[] PNG_59X40 = new byte[] {
            (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x3B, 0x00, 0x00, 0x00, 0x28,
            0x08, 0x06, 0x00, 0x00, 0x00};

    private static final byte[] JPEG_BYTES = new byte[] {
            (byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0, 0x00, 0x10,
            0x4A, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            (byte) 0xFF, (byte) 0xC0, 0x00, 0x11, 0x08, 0x00, 0x48, 0x00, 0x60,
            0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01,
            (byte) 0xFF, (byte) 0xD9};

    private static FigureRef ref(String elementId, String url) {
        return new FigureRef(elementId, "assets/crop_" + elementId + ".png", "png",
                url, "unavailable-signed-url", null, null, null, null, null, null);
    }

    private static GlmOcrPaperDraft draft(FigureRef... figures) {
        List<FigureRef> refs = List.of(figures);
        PartDraft part = new PartDraft("q01-doc-pa", "a", "part text", 2, false,
                refs.subList(0, Math.min(1, refs.size())), List.of(), 0.8);
        GlmOcrPaperDraft.QuestionDraft question = new GlmOcrPaperDraft.QuestionDraft(
                "q01-doc", 1, "colon", null, "stem", false, List.of(),
                List.of(part), refs.size() > 1 ? refs.subList(1, refs.size()) : List.of(),
                List.of(), 2, true, false, List.of(), 0.75);
        return new GlmOcrPaperDraft(
                GlmOcrPaperDraft.SCHEMA_VERSION, "glm-ocr-qp-v1", true,
                null, List.of(question), java.util.Map.of(), 2, java.util.Map.of(),
                refs.size() > 2 ? refs.subList(2, refs.size()) : List.of(),
                List.of());
    }

    @Test
    @DisplayName("resolved assets: availability=available, img:<sha256>, dims, ownership=elementId")
    void resolvesLocalAssets(@TempDir Path tempDir) throws Exception {
        Path assets = Files.createDirectories(tempDir.resolve("assets"));
        Files.write(assets.resolve("crop_e000007.png"), PNG_59X40);
        Files.write(assets.resolve("crop_e000009.png"), PNG_59X40);
        FigureRef resolvable = ref("e000007", "assets/crop_e000007.png");
        FigureRef missing = ref("e000008", "assets/crop_e000008.png");
        FigureRef frontMatter = ref("e000009", "assets/crop_e000009.png");

        GlmOcrAssetEnricher.EnrichedDraft result =
                GlmOcrAssetEnricher.enrich(draft(resolvable, missing, frontMatter), tempDir);

        assertThat(result.enrichment().referencesTotal()).isEqualTo(4);
        assertThat(result.enrichment().referencesResolved()).isEqualTo(3);

        GlmOcrPaperDraft.FigureRef enriched =
                result.draft().questions().get(0).parts().get(0).figures().get(0);
        assertThat(enriched.availability()).isEqualTo("available");
        assertThat(enriched.assetId()).startsWith("img:").hasSize(4 + 64);
        assertThat(enriched.sha256()).isEqualTo(enriched.assetId().substring(4));
        assertThat(enriched.mimeType()).isEqualTo("image/png");
        assertThat(enriched.width()).isEqualTo(59);
        assertThat(enriched.height()).isEqualTo(40);
        assertThat(enriched.formatMismatch()).isFalse();
        assertThat(enriched.url()).isEqualTo("assets/crop_e000007.png");

        // unresolved: untouched in every field
        GlmOcrPaperDraft.FigureRef untouched =
                result.draft().questions().get(0).figures().get(0);
        assertThat(untouched).isEqualTo(missing);
        assertThat(untouched.availability()).isEqualTo("unavailable-signed-url");
    }

    @Test
    @DisplayName("JSON parity: unresolved refs carry NO asset fields; resolved refs do")
    void jsonSerializationParity(@TempDir Path tempDir) throws Exception {
        Path assets = Files.createDirectories(tempDir.resolve("assets"));
        Files.write(assets.resolve("crop_e000007.png"), PNG_59X40);
        GlmOcrAssetEnricher.EnrichedDraft result =
                GlmOcrAssetEnricher.enrich(
                        draft(ref("e000007", "assets/crop_e000007.png"),
                              ref("e000008", "assets/crop_e000008.png")),
                        tempDir);
        JsonNode root = CanonicalJson.mapper().readTree(
                CanonicalJson.mapper().writeValueAsString(result.draft()));
        JsonNode partFigures = root.at("/questions/0/parts/0/figures");
        assertThat(partFigures.get(0).has("assetId")).isTrue();
        assertThat(partFigures.get(0).get("availability").asText()).isEqualTo("available");
        JsonNode questionFigures = root.at("/questions/0/figures");
        assertThat(questionFigures.get(0).has("assetId")).isFalse();
        assertThat(questionFigures.get(0).has("sha256")).isFalse();
        assertThat(questionFigures.get(0).get("availability").asText())
                .isEqualTo("unavailable-signed-url");
    }

    @Test
    @DisplayName("content/extension mismatch is flagged, not fixed (JPEG bytes named .png)")
    void formatMismatchFlagged(@TempDir Path tempDir) throws Exception {
        Path assets = Files.createDirectories(tempDir.resolve("assets"));
        Files.write(assets.resolve("crop_e000007.png"), JPEG_BYTES);
        GlmOcrAssetEnricher.EnrichedDraft result = GlmOcrAssetEnricher.enrich(
                draft(ref("e000007", "assets/crop_e000007.png")), tempDir);
        GlmOcrPaperDraft.FigureRef enriched =
                result.draft().questions().get(0).parts().get(0).figures().get(0);
        assertThat(enriched.mimeType()).isEqualTo("image/jpeg");
        assertThat(enriched.formatMismatch()).isTrue();
        assertThat(enriched.width()).isEqualTo(96);
        assertThat(enriched.height()).isEqualTo(72);
    }

    @Test
    @DisplayName("decoded remote URL: bare file-name fallback resolves; others stay untouched")
    void decodedUrlPathResolution(@TempDir Path tempDir) throws Exception {
        // basename fallback: a saved crop re-exported flat under the assets root
        Files.write(tempDir.resolve("crop_1_1789046647734.png"), PNG_59X40);
        FigureRef encoded = new FigureRef("e000007",
                "assets/crop_1_1789046647734.png", "png",
                "https://host/ocr%2Fcrop%2Fcrop_1_1789046647734.png",
                "unavailable-signed-url", null, null, null, null, null, null);
        GlmOcrAssetEnricher.EnrichedDraft result =
                GlmOcrAssetEnricher.enrich(draft(encoded), tempDir);
        // the signed URL host does not exist locally, but the decoded file NAME does
        assertThat(result.enrichment().referencesResolved()).isEqualTo(1);
        assertThat(result.draft().questions().get(0).parts().get(0).figures().get(0)
                .availability()).isEqualTo("available");
    }
}
