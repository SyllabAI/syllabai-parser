package com.syllabai.parser.structure.glmocr;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * T-MIG-141 Phase E intake law — Java consumer of the canonical
 * glyph-normalization table (spec §7).
 *
 * <p>Reads {@code tools/glyph-normalization/table.v1.json} — the SINGLE map
 * home (no second map anywhere). Faithful port of the frozen Phase-B driver
 * semantics (phase_b_apply.py {@code normalize_factory}) and of the Python
 * reference {@code tools/glmocr/normalize_pua.py}: cross-language conformance
 * is enforced by the glyph leg of {@code tools/glmocr/conformance.py}
 * (16/16 glyph fixture classes must stay green — CI fails on drift).</p>
 *
 * <p>Ordering law (spec §3.5): a single left-to-right pass; sequence rules
 * matched FIRST (longest sequence wins), then 1:1 single entries; no
 * re-scanning of replaced spans. Unobserved sequence lengths and unmapped
 * PUA codepoints pass through UNCHANGED — the born-clean census sees them
 * and the intake gate fails the batch (fail-closed, never silent serve).
 * C0 control chars (excluding tab/LF/CR) map to a single space; the DROP
 * class deletes.</p>
 *
 * <p>Canary of record: {@code C-intake-zero-pua} — every real intake batch
 * must census PUA=0 post-normalization.</p>
 */
public final class PuaNormalizer {

    private static final class SeqRule {
        final String id;
        final char[] from;
        final char to;

        SeqRule(String id, char[] from, char to) {
            this.id = id;
            this.from = from;
            this.to = to;
        }
    }

    private final List<SeqRule> seqs = new ArrayList<>();          // longest-first
    private final Map<String, Character> singles = new HashMap<>(); // "U+F02D" -> char; null = DROP
    private final String tableSha256;

    private PuaNormalizer(String tableSha256) {
        this.tableSha256 = tableSha256;
    }

    /** Load and compile the canonical table (fail-closed on shape errors). */
    public static PuaNormalizer load(Path tablePath) throws IOException {
        byte[] raw = Files.readAllBytes(tablePath);
        String sha = Sha256.hex(raw);
        JsonNode root = new ObjectMapper().readTree(raw);
        if (root == null || !root.has("entries") || !root.get("entries").isArray()
                || root.get("entries").isEmpty()) {
            throw new IOException("glyph table malformed: no entries");
        }
        if (!root.has("sequence_rules") || !root.get("sequence_rules").isArray()) {
            throw new IOException("glyph table malformed: no sequence_rules");
        }
        PuaNormalizer n = new PuaNormalizer(sha);
        List<JsonNode> rules = new ArrayList<>();
        root.get("sequence_rules").forEach(rules::add);
        rules.sort((a, b) -> Integer.compare(b.get("from").size(), a.get("from").size()));
        for (JsonNode rule : rules) {
            JsonNode from = rule.get("from");
            if (from == null || !from.isArray() || from.isEmpty()) {
                throw new IOException("sequence rule missing 'from': " + rule.path("id"));
            }
            char[] pattern = new char[from.size()];
            for (int i = 0; i < from.size(); i++) {
                pattern[i] = decodeCp(from.get(i).asText(), rule.path("id").asText());
            }
            char to = decodeCp(rule.get("to").asText(), rule.path("id").asText());
            n.seqs.add(new SeqRule(rule.path("id").asText("?"), pattern, to));
        }
        for (JsonNode entry : root.get("entries")) {
            String from = entry.path("from").asText("");
            if (!from.startsWith("U+")) {
                throw new IOException("bad entry 'from': " + from);
            }
            String to = entry.hasNonNull("to") ? entry.get("to").asText("") : "";
            if ("DROP".equals(to) || to.isEmpty()) {
                n.singles.put(from, null);       // DROP class: delete
            } else if (to.startsWith("U+")) {
                n.singles.put(from, decodeCp(to, from));
            } else {
                throw new IOException("bad entry 'to': " + to);
            }
        }
        return n;
    }

    private static char decodeCp(String spec, String owner) {
        if (spec == null || !spec.startsWith("U+") || spec.length() != 6) {
            throw new IllegalArgumentException("bad codepoint spec '" + spec + "' in " + owner);
        }
        return (char) Integer.parseInt(spec.substring(2), 16);
    }

    /** Resolve the canonical table: env override, else walk up from the
     * working directory looking for tools/glyph-normalization/table.v1.json. */
    public static Path resolveDefaultTable() {
        String env = System.getenv("GLYPH_NORMALIZATION_TABLE");
        if (env != null && !env.isBlank()) {
            return Path.of(env);
        }
        Path dir = Path.of("").toAbsolutePath();
        while (dir != null) {
            Path candidate = dir.resolve("tools").resolve("glyph-normalization")
                    .resolve("table.v1.json");
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
            dir = dir.getParent();
        }
        throw new IllegalStateException(
                "canonical glyph table not found (set GLYPH_NORMALIZATION_TABLE or run "
                        + "from the syllabai-parser repo; expected tools/glyph-normalization/"
                        + "table.v1.json) — intake law fails closed, never serves unnormalized");
    }

    /** Shared cached loader for pipeline entry points. */
    public static PuaNormalizer shared() throws IOException {
        if (SHARED == null) {
            synchronized (PuaNormalizer.class) {
                if (SHARED == null) {
                    SHARED = load(resolveDefaultTable());
                }
            }
        }
        return SHARED;
    }

    private static volatile PuaNormalizer SHARED;

    /** Normalize at intake: bytes in (any content), normalized UTF-8 bytes out. */
    public static byte[] normalizeAtIntake(byte[] source) throws IOException {
        String text = new String(source, java.nio.charset.StandardCharsets.UTF_8);
        return shared().normalize(text).getBytes(java.nio.charset.StandardCharsets.UTF_8);
    }

    /** The canonical normalization (ordering law §3.5, frozen-driver exact). */
    public String normalize(String text) {
        StringBuilder out = new StringBuilder(text.length());
        int i = 0;
        int n = text.length();
        while (i < n) {
            char ch = text.charAt(i);
            if (ch >= 0xE000 && ch <= 0xF8FF) {
                SeqRule hit = null;
                for (SeqRule s : seqs) {
                    int len = s.from.length;
                    if (i + len <= n) {                       // slice-match law
                        boolean all = true;
                        for (int j = 0; j < len; j++) {
                            if (text.charAt(i + j) != s.from[j]) {
                                all = false;
                                break;
                            }
                        }
                        if (all) {
                            hit = s;
                            break;
                        }
                    }
                }
                if (hit != null) {
                    out.append(hit.to);
                    i += hit.from.length;
                    continue;
                }
                String key = key(ch);
                if (singles.containsKey(key)) {
                    Character to = singles.get(key);
                    if (to != null) {
                        out.append(to.charValue());
                    }
                    // null = DROP class: delete
                } else {
                    out.append(ch);   // unmapped PUA passes through — born-clean sees it
                }
                i++;
            } else if (ch >= 0x00 && ch < 0x20 && ch != '\t' && ch != '\n' && ch != '\r') {
                out.append(' ');      // C0 control char -> single space (spec §3.4)
                i++;
            } else {
                out.append(ch);
                i++;
            }
        }
        return out.toString();
    }

    /** Born-clean census: PUA/C0 instances OUTSIDE the mapped set. */
    public Map<String, Object> census(String text) {
        Map<String, Integer> unmapped = new TreeMap<>();
        Map<String, Integer> c0 = new TreeMap<>();
        int i = 0;
        int n = text.length();
        while (i < n) {
            char ch = text.charAt(i);
            if (ch >= 0xE000 && ch <= 0xF8FF) {
                boolean matched = false;
                for (SeqRule s : seqs) {
                    int len = s.from.length;
                    if (i + len <= n) {
                        boolean all = true;
                        for (int j = 0; j < len; j++) {
                            if (text.charAt(i + j) != s.from[j]) {
                                all = false;
                                break;
                            }
                        }
                        if (all) {
                            i += len;
                            matched = true;
                            break;
                        }
                    }
                }
                if (matched) {
                    continue;
                }
                String key = key(ch);
                if (singles.containsKey(key)) {
                    i++;               // mapped (or DROP): consumed, not an artifact
                    continue;
                }
                unmapped.merge(key, 1, Integer::sum);
                i++;
                continue;
            }
            if (ch >= 0x00 && ch < 0x20 && ch != '\t' && ch != '\n' && ch != '\r') {
                c0.merge(key(ch), 1, Integer::sum);
            }
            i++;
        }
        Map<String, Integer> unmappedCounts = new TreeMap<>(unmapped);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("unmapped_pua_instances", unmapped.values().stream().mapToInt(Integer::intValue).sum());
        result.put("unmapped_pua_distinct", new ArrayList<>(unmapped.keySet()));
        result.put("unmapped_pua_counts", unmappedCounts);
        result.put("c0_outside_mapped_instances", c0.values().stream().mapToInt(Integer::intValue).sum());
        result.put("c0_distinct", new ArrayList<>(c0.keySet()));
        return result;
    }

    /** normalize(normalize(x)) == normalize(x) — 0 when clean. */
    public int idempotenceDelta(String text) {
        return normalize(normalize(text)).equals(normalize(text)) ? 0 : 1;
    }

    public String tableSha256() {
        return tableSha256;
    }

    public String canary() {
        return "C-intake-zero-pua";
    }

    private static String key(char ch) {
        return String.format("U+%04X", (int) ch);
    }

    /** Minimal sha256 hex (java.util.HexFormat exists since 17). */
    private static final class Sha256 {
        static String hex(byte[] data) {
            try {
                byte[] digest = java.security.MessageDigest.getInstance("SHA-256")
                        .digest(data);
                StringBuilder sb = new StringBuilder(digest.length * 2);
                for (byte b : digest) {
                    sb.append(String.format("%02x", b));
                }
                return sb.toString();
            } catch (java.security.NoSuchAlgorithmException e) {
                throw new IllegalStateException(e);
            }
        }
    }
}
