package com.syllabai.parser.structure;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class CommandWordLexiconTest {

    @Test
    @DisplayName("extracts the leading command word")
    void extractsLeading() {
        assertThat(CommandWordLexicon.extract("State what is meant by the term mole."))
                .isEqualTo(Optional.of("state"));
        assertThat(CommandWordLexicon.extract("Explain why the mixture boils."))
                .isEqualTo(Optional.of("explain"));
    }

    @Test
    @DisplayName("longest match wins: 'show that' over 'show'")
    void longestMatchWins() {
        assertThat(CommandWordLexicon.extract("Show that the relative formula mass is 74."))
                .isEqualTo(Optional.of("show that"));
    }

    @Test
    @DisplayName("a leading part label does not hide the command word")
    void skipsPartLabel() {
        assertThat(CommandWordLexicon.extract("(b) Calculate the mass in grams."))
                .isEqualTo(Optional.of("calculate"));
        assertThat(CommandWordLexicon.extract("(ii) Deduce the temperature."))
                .isEqualTo(Optional.of("deduce"));
    }

    @Test
    @DisplayName("prompts not starting with a command word yield empty")
    void noCommandWord() {
        assertThat(CommandWordLexicon.extract("The diagram shows a cell.")).isEmpty();
        assertThat(CommandWordLexicon.extract("")).isEmpty();
        assertThat(CommandWordLexicon.extract(null)).isEmpty();
    }
}
