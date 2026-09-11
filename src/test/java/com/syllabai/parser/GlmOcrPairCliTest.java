package com.syllabai.parser;

import static org.assertj.core.api.Assertions.assertThat;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import com.syllabai.parser.structure.glmocr.GlmOcrMarkReconciliation;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * The T-C03 pair CLI: real GLM-OCR Markdown QP + MS → the five-file bundle
 * the core bridge consumes. Pinned against the REAL corpus fixtures: the
 * June pair is clean (80/80), the October 1A pair carries the audited
 * 80-vs-120 paper-total conflict — the CLI must surface it, never merge it.
 */
class GlmOcrPairCliTest {

    private static final List<String> BUNDLE = List.of(
            "qp-canonical.json", "ms-canonical.json", "qp-draft.json",
            "ms-draft.json", "reconciliation.json");

    private static final String URI_PREFIX = "Past-Papers/GLM-markdown-sample";

    @Test
    @DisplayName("June pair: five-file bundle, deterministic ids, drafts claim their canonical ids")
    void junePairBundle(@TempDir Path work) throws Exception {
        Path input = work.resolve("input");
        Path out = work.resolve("june");
        copyFixtures(input, "june-2025-wph11-01-qp.md", "june-2025-wph11-01-ms.md");

        GlmOcrPairCli.main(new String[] {
                input.resolve("june-2025-wph11-01-qp.md").toString(),
                input.resolve("june-2025-wph11-01-ms.md").toString(),
                out.toString(), "--uri-prefix=" + URI_PREFIX});

        for (String file : BUNDLE) {
            assertThat(out.resolve(file)).as("bundle file %s", file).isRegularFile();
        }

        CanonicalDocument qp = CanonicalJson.read(out.resolve("qp-canonical.json"));
        GlmOcrPaperDraft qpDraft = CanonicalJson.mapper()
                .readValue(out.resolve("qp-draft.json").toFile(), GlmOcrPaperDraft.class);
        GlmOcrMarkSchemeDraft msDraft = CanonicalJson.mapper()
                .readValue(out.resolve("ms-draft.json").toFile(), GlmOcrMarkSchemeDraft.class);
        GlmOcrMarkReconciliation.Reconciliation reconciliation = CanonicalJson.mapper()
                .readValue(out.resolve("reconciliation.json").toFile(),
                        GlmOcrMarkReconciliation.Reconciliation.class);

        // corpus URIs keep the Past-Papers repository-relative shape
        assertThat(qp.source().uri())
                .isEqualTo(URI_PREFIX + "/june-2025-wph11-01-qp.md");

        // the drafts claim exactly the canonical documents they came from —
        // the bundle-consistency invariant core's bridge validation checks
        assertThat(qpDraft.paper().canonicalDocumentId()).isEqualTo(qp.documentId());
        assertThat(msDraft.paper().canonicalDocumentId())
                .isEqualTo(CanonicalJson.read(out.resolve("ms-canonical.json")).documentId());

        // known June facts: 20 questions, clean 80/80 reconciliation
        assertThat(qpDraft.questions()).hasSize(20);
        assertThat(reconciliation.reviewRequired()).isFalse();
        assertThat(reconciliation.mismatchCount()).isZero();
        assertThat(reconciliation.paperTotalConflict()).isFalse();
        assertThat(reconciliation.qpPaperTotal()).isEqualTo(80);
        assertThat(reconciliation.msPaperTotal()).isEqualTo(80);
    }

    @Test
    @DisplayName("1A pair: the 80-vs-120 paper-total conflict is written out, never merged")
    void oneAConflictPreserved(@TempDir Path work) throws Exception {
        Path input = work.resolve("input");
        Path out = work.resolve("one-a");
        copyFixtures(input, "october-2025-wph11-01a-qp.md", "october-2025-wph11-01a-ms.md");

        GlmOcrPairCli.main(new String[] {
                input.resolve("october-2025-wph11-01a-qp.md").toString(),
                input.resolve("october-2025-wph11-01a-ms.md").toString(),
                out.toString(), "--uri-prefix=" + URI_PREFIX});

        GlmOcrMarkReconciliation.Reconciliation reconciliation = CanonicalJson.mapper()
                .readValue(out.resolve("reconciliation.json").toFile(),
                        GlmOcrMarkReconciliation.Reconciliation.class);

        assertThat(reconciliation.paperTotalConflict()).isTrue();
        assertThat(reconciliation.reviewRequired()).isTrue();
        // both totals preserved verbatim — never 80, never 120, never merged
        assertThat(reconciliation.qpPaperTotal()).isEqualTo(80);
        assertThat(reconciliation.msPaperTotal()).isEqualTo(120);
    }

    @Test
    @DisplayName("rerun over the same inputs yields the same deterministic document ids")
    void rerunIsDeterministic(@TempDir Path work) throws Exception {
        Path input = work.resolve("input");
        Path first = work.resolve("first");
        Path second = work.resolve("second");
        copyFixtures(input, "october-2025-wph11-01-qp.md", "october-2025-wph11-01-ms.md");
        String[] args = {
                input.resolve("october-2025-wph11-01-qp.md").toString(),
                input.resolve("october-2025-wph11-01-ms.md").toString(),
                first.toString(), "--uri-prefix=" + URI_PREFIX};

        GlmOcrPairCli.main(args);
        GlmOcrPairCli.main(withOutDir(args, second));

        // identity = SHA-256(checksum + engine + version): rerun-stable by construction
        assertThat(CanonicalJson.read(second.resolve("qp-canonical.json")).documentId())
                .isEqualTo(CanonicalJson.read(first.resolve("qp-canonical.json")).documentId());
        assertThat(CanonicalJson.read(second.resolve("ms-canonical.json")).documentId())
                .isEqualTo(CanonicalJson.read(first.resolve("ms-canonical.json")).documentId());

        // drafts and reconciliation are deterministic structures too (no timestamps
        // inside them; only the canonical provenance honestly carries extractedAt)
        assertThat(Files.readString(second.resolve("qp-draft.json")))
                .isEqualTo(Files.readString(first.resolve("qp-draft.json")));
        assertThat(Files.readString(second.resolve("reconciliation.json")))
                .isEqualTo(Files.readString(first.resolve("reconciliation.json")));
    }

    private static String[] withOutDir(String[] args, Path outDir) {
        String[] copy = args.clone();
        copy[2] = outDir.toString();
        return copy;
    }

    @Test
    @DisplayName("--assets-dir: sidecar assets-report.json ledgers resolved + unresolved refs")
    void assetsSidecarReport(@TempDir Path work) throws Exception {
        Path input = work.resolve("input");
        Path out = work.resolve("bundle");
        Path assets = Files.createDirectories(work.resolve("assets"));
        // minimal valid PNG (59x40 header) for the resolvable reference
        Files.write(assets.resolve("crop_front.png"), new byte[] {
                (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
                0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
                0x00, 0x00, 0x00, 0x3B, 0x00, 0x00, 0x00, 0x28,
                0x08, 0x06, 0x00, 0x00, 0x00});
        // crop_q1.png deliberately MISSING — the operator-deletion scenario
        copyFixtures(input, "figure-ms-qp.md", "figure-ms-ms.md");

        GlmOcrPairCli.main(new String[] {
                input.resolve("figure-ms-qp.md").toString(),
                input.resolve("figure-ms-ms.md").toString(),
                out.toString(),
                "--uri-prefix=" + URI_PREFIX,
                "--assets-dir=" + assets});

        // the five-file bundle is unchanged; the report is a sixth SIDEcar file
        for (String file : BUNDLE) {
            assertThat(out.resolve(file)).as("bundle file %s", file).isRegularFile();
        }
        com.fasterxml.jackson.databind.JsonNode report = CanonicalJson.mapper()
                .readTree(out.resolve("assets-report.json").toFile());
        assertThat(report.get("referencesTotal").asInt()).isEqualTo(2);
        assertThat(report.get("referencesResolved").asInt()).isEqualTo(1);
        assertThat(report.get("distinctAssets").asInt()).isEqualTo(1);
        assertThat(report.get("unresolved")).hasSize(1);
        assertThat(report.get("unresolved").get(0).get("url").asText())
                .isEqualTo("assets/crop_q1.png");
        assertThat(report.get("unresolved").get(0).get("elementId").asText()).isNotBlank();
    }

    private static void copyFixtures(Path inputDir, String qp, String ms) throws IOException {
        Files.createDirectories(inputDir);
        Files.write(inputDir.resolve(qp), fixture(qp));
        Files.write(inputDir.resolve(ms), fixture(ms));
    }

    static byte[] fixture(String name) throws IOException {
        try (InputStream in = GlmOcrPairCliTest.class.getResourceAsStream("/glm-ocr/" + name)) {
            assertThat(in).as("fixture " + name).isNotNull();
            return in.readAllBytes();
        }
    }
}
