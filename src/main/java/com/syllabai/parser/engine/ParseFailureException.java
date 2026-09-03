package com.syllabai.parser.engine;

/** An extraction engine failed on the given source. */
public final class ParseFailureException extends RuntimeException {

    public ParseFailureException(String engine, String detail, Throwable cause) {
        super("parser '" + engine + "' failed: " + detail, cause);
    }
}
