package com.syllabai.parser;

import com.syllabai.parser.canonical.CanonicalDocument;
import com.syllabai.parser.canonical.CanonicalJson;
import com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser;
import com.syllabai.parser.structure.glmocr.GlmOcrAssetEnricher;
import com.syllabai.parser.structure.glmocr.GlmOcrMarkReconciliation;
import com.syllabai.parser.structure.glmocr.GlmOcrMarkSchemeExtractor;
import com.syllabai.parser.structure.glmocr.GlmOcrQuestionExtractor;
import com.syllabai.parser.structure.dto.GlmOcrMarkSchemeDraft;
import com.syllabai.parser.structure.dto.GlmOcrPaperDraft;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

/**
 * Content-operations pair CLI for the GLM-OCR Markdown path (T-C03: the
 * committed production command for "GLM-OCR → canonical documents → drafts →
 * reconciliation", replacing the session-10 workbench script that generated
 * the bridge fixtures). Offline; not part of any deployed runtime.
 *
 * <pre>
 *   syllabai-glmocr-pair &lt;qp.md&gt; &lt;ms.md&gt; &lt;out-dir&gt; [--uri-prefix &lt;prefix&gt;]
 *                         [--assets-dir &lt;dir&gt;] [--paper-code &lt;code&gt;] [--session-label &lt;label&gt;]
 * </pre>
 *
 * Writes the five-file bundle that syllabai-core's T-C02 bridge consumes,
 * exactly as the bridge's pair/batch CLIs read them:
 * {@code qp-canonical.json}, {@code ms-canonical.json}, {@code qp-draft.json},
 * {@code ms-draft.json}, {@code reconciliation.json}.
 *
 * <p><strong>Determinism:</strong> canonical document ids are derived from
 * SHA-256(checksum + engine + engineVersion) — never from the timestamp — so
 * re-running this CLI over the same inputs produces the SAME document ids
 * (only {@code extractedAt} honestly differs). The QP/MS drafts carry
 * {@code canonicalDocumentId} claims that match the serialized canonical
 * documents, which is exactly the bundle-consistency invariant the core
 * bridge's fail-loud validation checks.</p>
 *
 * <p><strong>Pairing is the operator's responsibility</strong> (same policy as
 * the corpus audit): the two files must be the QP and MS of the same paper.
 * The reconciliation output makes mismatches visible instead of hiding them.</p>
 *
 * <p><strong>Asset enrichment is opt-in:</strong> with {@code --assets-dir},
 * QP figure references that resolve to real files under that directory are
 * upgraded to {@code available} with content-derived identity
 * ({@code img:<sha256>}, sniffed MIME, dimensions — via
 * {@link GlmOcrAssetEnricher}); unresolvable references keep their failure
 * state and carry no new fields. Without the flag no filesystem access
 * happens and drafts are byte-identical to the pre-hardening engine.</p>
 */
public final class GlmOcrPairCli {

    public static void main(String[] args) throws Exception {
        String uriPrefix = "";
        Path assetsDir = null;
        String paperCodeOverride = null;
        String sessionLabelOverride = null;
        int positional = 0;
        Path qpFile = null;
        Path msFile = null;
        Path outDir = null;
        for (int a = 0; a < args.length; a++) {
            String arg = args[a];
            if (arg.startsWith("--uri-prefix=")) {
                uriPrefix = arg.substring("--uri-prefix=".length());
            } else if (arg.startsWith("--uri-prefix")) {
                uriPrefix = arg.substring("--uri-prefix".length());
                if (uriPrefix.startsWith("=")) {
                    uriPrefix = uriPrefix.substring(1);
                }
            } else if (arg.startsWith("--assets-dir=")) {
                assetsDir = Path.of(arg.substring("--assets-dir=".length()));
            } else if (arg.startsWith("--paper-code=")) {
                paperCodeOverride = arg.substring("--paper-code=".length()).strip();
            } else if (arg.startsWith("--session-label=")) {
                sessionLabelOverride = arg.substring("--session-label=".length()).strip();
            } else if (arg.equals("--assets-dir")) {
                if (a + 1 >= args.length) {
                    System.err.println("--assets-dir requires a directory argument");
                    usage();
                    System.exit(2);
                }
                assetsDir = Path.of(args[++a]);
            } else if (arg.startsWith("--assets-dir")) {
                assetsDir = Path.of(arg.substring("--assets-dir".length()));
                if (assetsDir.toString().startsWith("=")) {
                    assetsDir = Path.of(assetsDir.toString().substring(1));
                }
            } else switch (positional) {
                case 0 -> qpFile = Path.of(arg);
                case 1 -> msFile = Path.of(arg);
                case 2 -> outDir = Path.of(arg);
                default -> {
                    System.err.println("unexpected argument: " + arg);
                    usage();
                    System.exit(2);
                }
            }
            if (!arg.startsWith("--")) {
                positional++;
            }
        }
        if (qpFile == null || msFile == null || outDir == null) {
            usage();
            System.exit(2);
        }
        for (Path required : new Path[] {qpFile, msFile}) {
            if (!Files.isRegularFile(required)) {
                System.err.println("not a readable file: " + required);
                System.exit(2);
            }
        }
        if (assetsDir != null && !Files.isDirectory(assetsDir)) {
            System.err.println("not a readable directory: " + assetsDir);
            System.exit(2);
        }

        GlmOcrMarkdownParser parser = new GlmOcrMarkdownParser();
        CanonicalDocument qp = parser.parse(Files.readAllBytes(qpFile), uri(qpFile, uriPrefix));
        CanonicalDocument ms = parser.parse(Files.readAllBytes(msFile), uri(msFile, uriPrefix));

        GlmOcrPaperDraft qpDraft = new GlmOcrQuestionExtractor().extract(qp);
        GlmOcrMarkSchemeDraft msDraft = new GlmOcrMarkSchemeExtractor().extract(ms);
        if (paperCodeOverride != null || sessionLabelOverride != null) {
            // Operator-supplied identity for covers whose printed identity the OCR
            // cannot recover (e.g. the cover page was lost). The override is printed
            // loudly here and archived with the run log; the printed MS cover is the
            // acceptable evidence source. Extraction still fills everything else.
            GlmOcrPaperDraft.PaperMeta m = qpDraft.paper();
            qpDraft = new GlmOcrPaperDraft(
                    qpDraft.schemaVersion(), qpDraft.extractionMethod(), qpDraft.reviewRequired(),
                    new GlmOcrPaperDraft.PaperMeta(
                            m.board(), m.qualification(), m.subject(),
                            paperCodeOverride != null ? paperCodeOverride : m.paperReference(),
                            m.logNumber(), m.publicationCode(),
                            sessionLabelOverride != null ? sessionLabelOverride : m.session(),
                            m.examDate(), m.duration(), m.canonicalDocumentId()),
                    qpDraft.questions(), qpDraft.questionTotals(), qpDraft.paperTotal(),
                    qpDraft.sectionTotals(), qpDraft.frontMatterFigures(), qpDraft.warnings());
            System.out.println("[identity] OPERATOR-SUPPLIED:" 
                    + (paperCodeOverride != null ? " paper-code=" + paperCodeOverride : "")
                    + (sessionLabelOverride != null ? " session-label=" + sessionLabelOverride : "")
                    + " (printed cover identity unrecoverable — see campaign audit)");
        }
        GlmOcrAssetEnricher.Enrichment assetEnrichment = null;
        if (assetsDir != null) {
            GlmOcrAssetEnricher.EnrichedDraft enrichedDraft =
                    GlmOcrAssetEnricher.enrich(qpDraft, assetsDir);
            qpDraft = enrichedDraft.draft();
            assetEnrichment = enrichedDraft.enrichment();
        }
        GlmOcrMarkReconciliation.Reconciliation reconciliation =
                GlmOcrMarkReconciliation.reconcile(qpDraft, msDraft);

        Files.createDirectories(outDir);
        CanonicalJson.write(qp, outDir.resolve("qp-canonical.json"));
        CanonicalJson.write(ms, outDir.resolve("ms-canonical.json"));
        writeJson(outDir.resolve("qp-draft.json"), qpDraft);
        writeJson(outDir.resolve("ms-draft.json"), msDraft);
        writeJson(outDir.resolve("reconciliation.json"), reconciliation);

        System.out.println("pair: qp=" + qp.documentId() + " ms=" + ms.documentId()
                + "; questions: " + qpDraft.questions().size()
                + "; ms entries: " + msDraft.entries().size()
                + "; review required: " + reconciliation.reviewRequired()
                + " (mismatches: " + reconciliation.mismatchCount()
                + ", paper-total conflict: " + reconciliation.paperTotalConflict() + ")");
        if (assetEnrichment != null) {
            System.out.println("assets: " + assetEnrichment.referencesResolved() + "/"
                    + assetEnrichment.referencesTotal() + " figure references resolved under "
                    + assetsDir.toAbsolutePath());
        }
        System.out.println("bundle written to: " + outDir.toAbsolutePath());
    }

    /** corpus URIs keep the repository-relative shape (Past-Papers convention) */
    private static String uri(Path file, String prefix) {
        String name = file.getFileName().toString();
        return prefix.isBlank() ? name : prefix + "/" + name;
    }

    private static void writeJson(Path file, Object value) throws Exception {
        Files.writeString(file, CanonicalJson.mapper().writeValueAsString(value),
                StandardCharsets.UTF_8);
    }

    private static void usage() {
        System.err.println("""
                usage:
                  syllabai-glmocr-pair <qp.md> <ms.md> <out-dir> [--uri-prefix <corpus-prefix>] [--assets-dir <dir>]
                        [--paper-code <code>] [--session-label <label>]

                writes the five-file T-C02/T-C03 bundle (qp-canonical.json,
                ms-canonical.json, qp-draft.json, ms-draft.json, reconciliation.json);
                --assets-dir optionally enriches QP figure references that resolve
                to real local files (availability=available, img:<sha256>)
                """);
    }

    private GlmOcrPairCli() {
    }
}
