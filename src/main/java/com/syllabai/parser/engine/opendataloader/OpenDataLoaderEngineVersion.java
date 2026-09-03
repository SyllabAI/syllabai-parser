package com.syllabai.parser.engine.opendataloader;

import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;

/**
 * Resolves the exact opendataloader-pdf-core version actually on the
 * classpath from its Maven pom.properties — provenance must describe the
 * artifact that really ran, not the version a constant was updated to match.
 */
public final class OpenDataLoaderEngineVersion {

    static final String FALLBACK = "unknown";

    private OpenDataLoaderEngineVersion() {
    }

    public static String resolve() {
        try (InputStream in = OpenDataLoaderEngineVersion.class.getClassLoader()
                .getResourceAsStream("META-INF/maven/org.opendataloader/opendataloader-pdf-core/pom.properties")) {
            if (in == null) {
                return FALLBACK;
            }
            Properties properties = new Properties();
            properties.load(in);
            String version = properties.getProperty("version");
            return version == null || version.isBlank() ? FALLBACK : version;
        } catch (IOException e) {
            return FALLBACK;
        }
    }
}
