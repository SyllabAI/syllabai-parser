package com.syllabai.parser.structure.glmocr;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.FigureRef;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Image-reality rules (Session 9): deterministic img:&lt;sha256&gt; identity,
 * content-based MIME sniffing (the JPEG-content-with-.png-name regression),
 * container-header dimensions, expired signed-URL preservation, and
 * ownership propagation.
 */
class GlmOcrImageAssetsTest {

    // minimal PNG header: 89 50 4E 47 0D 0A 1A 0A | IHDR | width=59(0x3B) height=40(0x28)
    private static final byte[] PNG_HEADER = new byte[] {
            (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x3B, 0x00, 0x00, 0x00, 0x28,
            0x08, 0x06, 0x00, 0x00, 0x00};

    // minimal JPEG: SOI, APP0(JFIF), SOF0 (height=72, width=96), EOI
    private static final byte[] JPEG_MINIMAL = new byte[] {
            (byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0, 0x00, 0x10,
            0x4A, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            (byte) 0xFF, (byte) 0xC0, 0x00, 0x11, 0x08, 0x00, 0x48, 0x00, 0x60,
            0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01,
            (byte) 0xFF, (byte) 0xD9};

    // minimal GIF89a header: width=32 (LE), height=16 (LE)
    private static final byte[] GIF_MINIMAL = new byte[] {
            0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x20, 0x00, 0x10, 0x00,
            (byte) 0x80, 0x00, 0x00};

    @Test
    @DisplayName("PNG bytes: sniffed type, header dimensions, deterministic img:<sha256> id")
    void pngAsset() {
        GlmOcrImageAssets.ImageAsset asset = GlmOcrImageAssets.fromBytes(
                PNG_HEADER, "crop_1_1774977205806.png", "https://host/ocr/crop/crop_1.png", "q03-doc");
        assertThat(asset.mimeType()).isEqualTo("image/png");
        assertThat(asset.declaredFormat()).isEqualTo("png");
        assertThat(asset.formatMismatch()).isFalse();
        assertThat(asset.width()).isEqualTo(59);
        assertThat(asset.height()).isEqualTo(40);
        assertThat(asset.assetId()).startsWith("img:").hasSize(4 + 64);
        assertThat(asset.availability()).isEqualTo("available");
        assertThat(asset.ownership()).isEqualTo("q03-doc");
        assertThat(asset.url()).isEqualTo("https://host/ocr/crop/crop_1.png");
    }

    @Test
    @DisplayName("REGRESSION: JPEG content in a .png-named file is detected, mismatch flagged")
    void jpegContentWithPngName() {
        GlmOcrImageAssets.ImageAsset asset = GlmOcrImageAssets.fromBytes(
                JPEG_MINIMAL, "crop_2_1774977205868.png", null, "q04-doc");
        // content wins, the lie stays visible — never "fixed"
        assertThat(asset.mimeType()).isEqualTo("image/jpeg");
        assertThat(asset.declaredFormat()).isEqualTo("png");
        assertThat(asset.formatMismatch()).isTrue();
        assertThat(asset.width()).isEqualTo(96);
        assertThat(asset.height()).isEqualTo(72);
        assertThat(asset.assetId()).startsWith("img:");
    }

    @Test
    @DisplayName("GIF bytes: little-endian dimensions")
    void gifAsset() {
        GlmOcrImageAssets.ImageAsset asset = GlmOcrImageAssets.fromBytes(
                GIF_MINIMAL, "diagram.gif", null, "q05-doc");
        assertThat(asset.mimeType()).isEqualTo("image/gif");
        assertThat(asset.width()).isEqualTo(32);
        assertThat(asset.height()).isEqualTo(16);
    }

    @Test
    @DisplayName("same bytes → same img:<sha256> id; different bytes → different id")
    void deterministicIdentity() {
        GlmOcrImageAssets.ImageAsset a = GlmOcrImageAssets.fromBytes(PNG_HEADER, "a.png", null, "q");
        GlmOcrImageAssets.ImageAsset b = GlmOcrImageAssets.fromBytes(PNG_HEADER, "b.png", null, "q");
        GlmOcrImageAssets.ImageAsset c = GlmOcrImageAssets.fromBytes(GIF_MINIMAL, "c.gif", null, "q");
        assertThat(b.assetId()).isEqualTo(a.assetId());
        assertThat(c.assetId()).isNotEqualTo(a.assetId());
    }

    @Test
    @DisplayName("local files resolve through fromLocalFile with the same identity rules")
    void localFileResolution(@TempDir Path temp) throws Exception {
        Path file = temp.resolve("crop_3_1774977205873.png");
        Files.write(file, JPEG_MINIMAL);
        GlmOcrImageAssets.ImageAsset asset = GlmOcrImageAssets.fromLocalFile(file, "q06-doc");
        assertThat(asset.mimeType()).isEqualTo("image/jpeg");
        assertThat(asset.formatMismatch()).isTrue();
        assertThat(asset.sourceName()).isEqualTo("crop_3_1774977205873.png");
        assertThat(asset.sha256Hex()).hasSize(64);
        assertThat(asset.assetId()).isEqualTo("img:" + asset.sha256Hex());
    }

    @Test
    @DisplayName("expired signed-URL references preserve URL, location, ownership, failure state")
    void expiredUrlReference() {
        FigureRef ref = new FigureRef("e000007",
                "/ocr/crop/20260401/crop_1_1774977149836.png", "png",
                "https://host/ocr%2Fcrop%2F20260401%2Fcrop_1_1774977149836.png"
                        + "?UCloudPublicKey=TOKEN&Signature=4lRw%3D&Expires=1775581949",
                "unavailable-signed-url", null, null, null, null, null, null);
        GlmOcrImageAssets.ImageAsset asset = GlmOcrImageAssets.unavailableReference(ref, "q01-doc");
        assertThat(asset.availability()).isEqualTo("unavailable-signed-url");
        assertThat(asset.url()).contains("Expires=1775581949"); // expiry evidence preserved
        assertThat(asset.sourceName()).isEqualTo("/ocr/crop/20260401/crop_1_1774977149836.png");
        assertThat(asset.ownership()).isEqualTo("q01-doc");
        assertThat(asset.assetId()).isNull(); // no bytes → no img: id, never faked
        assertThat(asset.mimeType()).isNull();
    }

    @Test
    @DisplayName("source-name matching links local assets back to figure references")
    void sourceNameMatching() {
        FigureRef ref = new FigureRef("e000007",
                "/ocr/crop/20260401/crop_1_1774977149836.png", "png", null,
                "unavailable-signed-url", null, null, null, null, null, null);
        GlmOcrImageAssets.ImageAsset saved = GlmOcrImageAssets.fromBytes(
                PNG_HEADER, "/ocr/crop/20260401/crop_1_1774977149836.png", null, "q01-doc");
        assertThat(GlmOcrImageAssets.matchesBySourceName(saved, ref)).isTrue();

        GlmOcrImageAssets.ImageAsset other = GlmOcrImageAssets.fromBytes(
                PNG_HEADER, "/ocr/crop/other/crop_9.png", null, "q02-doc");
        assertThat(GlmOcrImageAssets.matchesBySourceName(other, ref)).isFalse();
    }
}
