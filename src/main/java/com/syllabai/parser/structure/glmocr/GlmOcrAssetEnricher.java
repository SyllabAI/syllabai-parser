package com.syllabai.parser.structure.glmocr;

import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft.FigureRef;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * OPT-IN local asset resolution for figure references (T-C03 hardening,
 * 2026-09). Wires the otherwise-unused {@link GlmOcrImageAssets} machinery
 * into the pair pipeline: when the operator passes {@code --assets-dir} to
 * {@code GlmOcrPairCli}, every draft figure reference is resolved against
 * the corpus assets directory and, when the file exists, upgraded from the
 * failure state {@code unavailable-signed-url} to {@code available} with
 * content-derived identity ({@code img:<sha256>}, sniffed MIME, container
 * dimensions, extension/content mismatch flag).
 *
 * <p><strong>Default-off by design:</strong> without the flag no filesystem
 * access happens and draft bytes are identical to the pre-hardening engine.
 * The asset fields serialize per-field NON_NULL, so even WITH the flag,
 * references that do not resolve carry no new fields — the failure state
 * stays honest and visible.</p>
 *
 * <p><strong>Ownership:</strong> the figure's canonical element id is passed
 * through as the asset ownership (the extractor has already decided which
 * question/part owns the reference; this class never re-guesses).</p>
 */
public final class GlmOcrAssetEnricher {

    private GlmOcrAssetEnricher() {
    }

    /** Result of enriching one paper draft.
     *
     * @param referencesTotal    figure references walked (question, part, front matter)
     * @param referencesResolved references upgraded to {@code available}
     * @param distinctAssets     distinct asset files behind the resolved references
     *                           (several questions may share one image)
     * @param unresolved         references that did not resolve under the assets
     *                           root, in encounter order — the machine-readable
     *                           input for the persisted assets report
     */
    public record Enrichment(int referencesTotal, int referencesResolved,
                             int distinctAssets, List<UnresolvedRef> unresolved) {

        public Enrichment {
            unresolved = unresolved == null ? List.of() : List.copyOf(unresolved);
        }
    }

    /** One reference that did not resolve under the assets root. */
    public record UnresolvedRef(String elementId, String sourceName, String url) {
    }

    /** Encounter-order collector for totals, distinct assets and unresolved refs. */
    private static final class Collector {
        int total;
        int resolved;
        final Set<String> assetShas = new HashSet<>();
        final List<UnresolvedRef> unresolved = new ArrayList<>();

        Enrichment enrichment() {
            return new Enrichment(total, resolved, assetShas.size(), unresolved);
        }
    }

    /**
     * Walks every figure reference of the draft (question level, part level,
     * front matter) and upgrades the ones that resolve under
     * {@code assetsDir}. Returns the enriched draft plus resolution counts.
     */
    public static EnrichedDraft enrich(GlmOcrPaperDraft draft, Path assetsDir) {
        Collector collector = new Collector();

        List<GlmOcrPaperDraft.QuestionDraft> questions = new ArrayList<>();
        for (GlmOcrPaperDraft.QuestionDraft question : draft.questions()) {
            List<FigureRef> qFigures = enrichAll(question.figures(), assetsDir, collector);
            List<GlmOcrPaperDraft.PartDraft> parts = new ArrayList<>();
            for (GlmOcrPaperDraft.PartDraft part : question.parts()) {
                parts.add(new GlmOcrPaperDraft.PartDraft(
                        part.partId(), part.label(), part.text(), part.marks(), part.qwc(),
                        enrichAll(part.figures(), assetsDir, collector),
                        part.answerPrompts(), part.confidence()));
            }
            questions.add(new GlmOcrPaperDraft.QuestionDraft(
                    question.questionId(), question.number(), question.numberingStyle(),
                    question.section(), question.stem(), question.mcq(), question.options(),
                    question.parts() == null ? List.of() : parts,
                    qFigures, question.tableElementIds(), question.marks(),
                    question.marksKnown(), question.qwc(), question.answerPrompts(),
                    question.confidence()));
        }
        GlmOcrPaperDraft enriched = new GlmOcrPaperDraft(
                draft.schemaVersion(), draft.extractionMethod(), draft.reviewRequired(),
                draft.paper(), questions, draft.questionTotals(), draft.paperTotal(),
                draft.sectionTotals(),
                draft.frontMatterFigures() == null ? null
                        : enrichAll(draft.frontMatterFigures(), assetsDir, collector),
                draft.warnings());
        return new EnrichedDraft(enriched, collector.enrichment());
    }

    /** Enriched draft + counts (record holder without touching the DTO). */
    public record EnrichedDraft(GlmOcrPaperDraft draft, Enrichment enrichment) {
    }

    private static List<FigureRef> enrichAll(List<FigureRef> refs, Path assetsDir,
                                             Collector collector) {
        if (refs == null || refs.isEmpty()) {
            return refs;
        }
        List<FigureRef> out = new ArrayList<>(refs.size());
        for (FigureRef ref : refs) {
            collector.total++;
            FigureRef resolved = resolve(ref, assetsDir);
            if (resolved != ref) {
                collector.resolved++;
                if (resolved.sha256() != null) {
                    collector.assetShas.add(resolved.sha256());
                }
            } else {
                collector.unresolved.add(new UnresolvedRef(
                        ref.elementId(), ref.sourceName(), ref.url()));
            }
            out.add(resolved);
        }
        return out;
    }

    /**
     * Resolves one reference: the decoded URL path is tried relative to
     * {@code assetsDir}, then its bare file name. Unresolvable references
     * come back untouched.
     *
     * <p><strong>Containment:</strong> a candidate is only considered when it
     * stays inside {@code assetsDir}. Reference URLs are corpus data, not
     * trusted input — a crafted or corrupted {@code src} such as
     * {@code ../../secrets.png} (or an absolute path) must never make the
     * enricher read outside the declared assets root; such references simply
     * keep their failure state.</p>
     */
    static FigureRef resolve(FigureRef ref, Path assetsDir) {
        String url = ref.url();
        if (url == null || url.isBlank()) {
            return ref;
        }
        Path root = assetsDir.toAbsolutePath().normalize();
        String path = urlPath(url);
        List<Path> candidates = new ArrayList<>(2);
        if (!path.startsWith("/")) {
            candidates.add(assetsDir.resolve(path).normalize());
        }
        String name = fileNameOf(path);
        if (!name.isEmpty()) {
            Path byName = assetsDir.resolve(name).normalize();
            if (!candidates.contains(byName)) {
                candidates.add(byName);
            }
        }
        for (Path candidate : candidates) {
            Path normalized = candidate.toAbsolutePath().normalize();
            if (!normalized.startsWith(root)) {
                continue;
            }
            if (!Files.isRegularFile(normalized)) {
                continue;
            }
            GlmOcrImageAssets.ImageAsset asset = GlmOcrImageAssets.fromBytes(
                    readAll(normalized), ref.sourceName(), url, ref.elementId());
            Integer width = asset.width() >= 0 ? asset.width() : null;
            Integer height = asset.height() >= 0 ? asset.height() : null;
            return new FigureRef(ref.elementId(), ref.sourceName(), ref.format(), ref.url(),
                    GlmOcrImageAssets.AVAILABILITY_AVAILABLE,
                    asset.assetId(), asset.sha256Hex(), asset.mimeType(),
                    width, height,
                    asset.mimeType() == null ? null : asset.formatMismatch());
        }
        return ref;
    }

    private static byte[] readAll(Path file) {
        try {
            return Files.readAllBytes(file);
        } catch (Exception e) {
            throw new IllegalStateException("cannot read image asset " + file, e);
        }
    }

    /** Decoded URL path; falls back to the raw string on malformed input. */
    static String urlPath(String url) {
        try {
            URI uri = new URI(url);
            String path = uri.getPath();
            if (path == null) {
                return url;
            }
            return URLDecoder.decode(path, StandardCharsets.UTF_8);
        } catch (URISyntaxException | IllegalArgumentException e) {
            return url;
        }
    }

    private static String fileNameOf(String path) {
        int slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
        return slash >= 0 ? path.substring(slash + 1) : path;
    }
}
