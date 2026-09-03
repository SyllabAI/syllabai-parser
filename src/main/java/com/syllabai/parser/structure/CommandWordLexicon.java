package com.syllabai.parser.structure;

import java.util.List;
import java.util.Locale;
import java.util.Optional;

/**
 * Edexcel command-word lexicon (Paper A "exam literacy" construct: the
 * command word carries the cognitive demand the mark scheme rewards).
 * Longest-match-wins at the start of a part prompt.
 */
public final class CommandWordLexicon {

    /** Low-order recall: state/name/give/… */
    public static final List<String> LOW_ORDER = List.of(
            "state", "name", "give", "identify", "label", "complete", "draw", "write",
            "plot", "circle", "tick", "put a cross", "select", "choose", "which");

    /** Mid-order explanation/application: describe/explain/calculate/… */
    public static final List<String> MID_ORDER = List.of(
            "describe", "explain", "calculate", "deduce", "determine", "estimate",
            "predict", "sketch", "outline", "measure", "comment", "show that",
            "show", "find", "convert", "balance", "refer to", "look at");

    /** High-order evaluation/discussion: discuss/justify/evaluate/… */
    public static final List<String> HIGH_ORDER = List.of(
            "discuss", "justify", "evaluate", "compare", "contrast", "analyse",
            "analyze", "suggest", "interpret", "assess", "consider");

    private static final List<String> ALL = merge();

    private CommandWordLexicon() {
    }

    private static List<String> merge() {
        // longest first so "show that" wins over "show"
        List<String> all = new java.util.ArrayList<>(LOW_ORDER.size()
                + MID_ORDER.size() + HIGH_ORDER.size());
        all.addAll(LOW_ORDER);
        all.addAll(MID_ORDER);
        all.addAll(HIGH_ORDER);
        all.sort((a, b) -> Integer.compare(b.length(), a.length()));
        return List.copyOf(all);
    }

    /**
     * Extracts the leading command word of a prompt, if any. Match is
     * case-insensitive at the start of the text (allowing an optional part
     * label), and — because exam stems often open with a context sentence
     * ("Copper is extracted… State the type of reaction.") — at the start of
     * any subsequent sentence. The first sentence-initial command word wins.
     */
    public static Optional<String> extract(String prompt) {
        if (prompt == null || prompt.isBlank()) {
            return Optional.empty();
        }
        String text = stripLeadingPartLabel(prompt.strip());
        for (String sentence : text.split("(?<=[.!?])\\s+")) {
            String candidate = matchAtStart(sentence.strip());
            if (candidate != null) {
                return Optional.of(candidate);
            }
        }
        return Optional.empty();
    }

    private static String matchAtStart(String sentence) {
        if (sentence.isEmpty()) {
            return null;
        }
        String lowered = sentence.toLowerCase(Locale.ROOT);
        for (String candidate : ALL) {
            if (lowered.startsWith(candidate + " ")
                    || lowered.startsWith(candidate + ",")
                    || lowered.equals(candidate)) {
                return candidate;
            }
        }
        return null;
    }

    private static String stripLeadingPartLabel(String text) {
        return text.replaceFirst("^\\(?[a-h]\\)\\s*", "")
                   .replaceFirst("^\\(?(i{1,3}|iv|v|vi{1,3}|ix|x)\\)\\s*", "");
    }
}
