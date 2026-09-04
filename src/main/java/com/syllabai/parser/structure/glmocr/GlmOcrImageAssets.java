package com.syllabai.parser.structure.glmocr;

import com.syllabai.parser.canonical.Checksums;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.FigureRef;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * GLM-OCR image asset handling (Session 9, image-reality rules).
 *
 * <p>Two worlds, never mixed:</p>
 * <ol>
 *   <li><strong>Expired signed-URL references</strong> (the entire current
 *       sample corpus): the bytes are gone, so the asset preserves the URL,
 *       source location (decoded URL path), intended ownership and the
 *       failure state {@code unavailable-signed-url}. The URL itself keeps
 *       the {@code Expires=} evidence. Nothing is ever fetched at parse
 *       time.</li>
 *   <li><strong>Valid local assets</strong> (a future re-export that saves
 *       images at export time): byte hashing (SHA-256), content-based MIME
 *       sniffing (magic bytes — extension is recorded separately so a
 *       JPEG-named-{@code .png} is visible, never "fixed"), dimensions from
 *       the container headers, and the deterministic identity
 *       {@code img:<sha256>}.</li>
 * </ol>
 *
 * <p>Ownership: the caller supplies the question/part id the asset belongs
 * to (from {@code GlmOcrQuestionExtractor} output); this class never guesses
 * ownership from pixels or paths.</p>
 */
public final class GlmOcrImageAssets {

    public static final String AVAILABILITY_AVAILABLE = "available";
    public static final String AVAILABILITY_UNAVAILABLE_SIGNED_URL = "unavailable-signed-url";

    /**
     * A resolved image asset.
     *
     * @param assetId        deterministic identity "img:&lt;sha256hex&gt;"
     * @param sourceName     durable source location (decoded URL path / file name)
     * @param url            original reference URL (null for local-only files)
     * @param sha256Hex      SHA-256 of the exact bytes (null when unavailable)
     * @param mimeType       sniffed content type (null when unavailable)
     * @param declaredFormat extension-derived format, kept for mismatch evidence
     * @param formatMismatch true when sniffed type contradicts the extension
     * @param width          pixel width from the container header (-1 unknown)
     * @param height         pixel height from the container header (-1 unknown)
     * @param ownership      owning question / question-part id (caller-supplied)
     * @param availability   "available" or "unavailable-signed-url"
     */
    public record ImageAsset(
            String assetId,
            String sourceName,
            String url,
            String sha256Hex,
            String mimeType,
            String declaredFormat,
            boolean formatMismatch,
            int width,
            int height,
            String ownership,
            String availability) {
    }

    private GlmOcrImageAssets() {
    }

    /**
     * Resolves a local image file into an asset with content-derived identity:
     * hash, sniffed MIME, dimensions, and {@code img:<sha256>} id.
     */
    public static ImageAsset fromLocalFile(Path file, String ownership) {
        byte[] bytes;
        try {
            bytes = Files.readAllBytes(file);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read image asset " + file, e);
        }
        return fromBytes(bytes, file.getFileName().toString(), null, ownership);
    }

    /**
     * Resolves in-memory image bytes; {@code sourceName} carries the durable
     * location (e.g. the decoded URL path of a saved crop), {@code url} the
     * original reference when known.
     */
    public static ImageAsset fromBytes(byte[] bytes, String sourceName, String url,
                                       String ownership) {
        String sha256Hex = Checksums.sha256Hex(bytes);
        String sniffed = sniffMime(bytes);
        String declared = declaredFormat(sourceName);
        boolean mismatch = sniffed != null && declared != null
                && !sniffed.equals("image/" + declared.toLowerCase(java.util.Locale.ROOT));
        int[] dims = dimensions(bytes, sniffed);
        return new ImageAsset("img:" + sha256Hex, sourceName, url, sha256Hex, sniffed,
                declared, mismatch, dims[0], dims[1], ownership, AVAILABILITY_AVAILABLE);
    }

    /**
     * The expired-reference form: bytes gone, URL + source location + ownership
     * preserved, failure state explicit.
     */
    public static ImageAsset unavailableReference(FigureRef ref, String ownership) {
        return new ImageAsset(null, ref.sourceName(), ref.url(), null, null, ref.format(),
                false, -1, -1, ownership,
                ref.availability() == null ? AVAILABILITY_UNAVAILABLE_SIGNED_URL
                        : ref.availability());
    }

    /**
     * True when a local asset's durable location matches a figure reference's
     * source name (the crop path survives in both).
     */
    public static boolean matchesBySourceName(ImageAsset asset, FigureRef ref) {
        if (asset == null || ref == null || asset.sourceName() == null
                || ref.sourceName() == null) {
            return false;
        }
        return asset.sourceName().equals(ref.sourceName())
                || asset.sourceName().endsWith(fileNameOf(ref.sourceName()));
    }

    // ── MIME sniffing (magic bytes) ─────────────────────────────────────────────

    static String sniffMime(byte[] b) {
        if (b == null || b.length < 12) {
            return null;
        }
        if ((b[0] & 0xFF) == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G'
                && b[4] == 0x0D && b[5] == 0x0A && b[6] == 0x1A && b[7] == 0x0A) {
            return "image/png";
        }
        if ((b[0] & 0xFF) == 0xFF && (b[1] & 0xFF) == 0xD8 && (b[2] & 0xFF) == 0xFF) {
            return "image/jpeg";
        }
        if (b[0] == 'G' && b[1] == 'I' && b[2] == 'F' && b[3] == '8') {
            return "image/gif";
        }
        if (b[0] == 'B' && b[1] == 'M') {
            return "image/bmp";
        }
        if (b[0] == 'R' && b[1] == 'I' && b[2] == 'F' && b[3] == 'F'
                && b[8] == 'W' && b[9] == 'E' && b[10] == 'B' && b[11] == 'P') {
            return "image/webp";
        }
        return null;
    }

    // ── dimensions ─────────────────────────────────────────────────────────────

    /** [width, height] from the container header; [-1,-1] when unknown. */
    static int[] dimensions(byte[] b, String mimeType) {
        if (b == null || mimeType == null) {
            return new int[] {-1, -1};
        }
        return switch (mimeType) {
            case "image/png" -> pngDimensions(b);
            case "image/jpeg" -> jpegDimensions(b);
            case "image/gif" -> gifDimensions(b);
            case "image/bmp" -> bmpDimensions(b);
            default -> new int[] {-1, -1};
        };
    }

    private static int[] pngDimensions(byte[] b) {
        if (b.length < 24) {
            return new int[] {-1, -1};
        }
        return new int[] {beInt(b, 16), beInt(b, 20)};
    }

    private static int[] jpegDimensions(byte[] b) {
        // scan segment headers for SOF0..SOF15 (excluding DHT C4, JPG C8, DAC CC)
        int i = 2;
        while (i + 9 < b.length) {
            if ((b[i] & 0xFF) != 0xFF) {
                i++;
                continue;
            }
            int marker = b[i + 1] & 0xFF;
            boolean sof = marker >= 0xC0 && marker <= 0xCF
                    && marker != 0xC4 && marker != 0xC8 && marker != 0xCC;
            if (sof) {
                // SOF: [len hi][len lo][precision][height hi][height lo][width hi][width lo]
                int height = ((b[i + 5] & 0xFF) << 8) | (b[i + 6] & 0xFF);
                int width = ((b[i + 7] & 0xFF) << 8) | (b[i + 8] & 0xFF);
                return new int[] {width, height};
            }
            if (marker == 0xD8 || marker == 0x01 || (marker >= 0xD0 && marker <= 0xD7)) {
                i += 2;
                continue;
            }
            int segmentLength = ((b[i + 2] & 0xFF) << 8) | (b[i + 3] & 0xFF);
            if (segmentLength <= 0) {
                break;
            }
            i += 2 + segmentLength;
        }
        return new int[] {-1, -1};
    }

    private static int[] gifDimensions(byte[] b) {
        if (b.length < 10) {
            return new int[] {-1, -1};
        }
        return new int[] {leInt(b, 6), leInt(b, 8)};
    }

    private static int[] bmpDimensions(byte[] b) {
        if (b.length < 26) {
            return new int[] {-1, -1};
        }
        int width = (b[18] & 0xFF) | ((b[19] & 0xFF) << 8) | ((b[20] & 0xFF) << 16)
                | ((b[21] & 0xFF) << 24);
        int height = (b[22] & 0xFF) | ((b[23] & 0xFF) << 8) | ((b[24] & 0xFF) << 16)
                | ((b[25] & 0xFF) << 24);
        return new int[] {width, Math.abs(height)};
    }

    private static int beInt(byte[] b, int offset) {
        return ((b[offset] & 0xFF) << 24) | ((b[offset + 1] & 0xFF) << 16)
                | ((b[offset + 2] & 0xFF) << 8) | (b[offset + 3] & 0xFF);
    }

    private static int leInt(byte[] b, int offset) {
        return (b[offset] & 0xFF) | ((b[offset + 1] & 0xFF) << 8);
    }

    private static String declaredFormat(String sourceName) {
        if (sourceName == null || !sourceName.contains(".")) {
            return null;
        }
        return sourceName.substring(sourceName.lastIndexOf('.') + 1);
    }

    private static String fileNameOf(String path) {
        if (path == null) {
            return "";
        }
        int slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
        return slash >= 0 ? path.substring(slash + 1) : path;
    }
}
