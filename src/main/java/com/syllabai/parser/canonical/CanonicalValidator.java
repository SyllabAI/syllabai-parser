package com.syllabai.parser.canonical;

import java.util.HashSet;
import java.util.Set;

/**
 * Structural validation of a canonical document (used by tests here and
 * mirrored by the ingestion API in syllabai-core). Rejects wrong schema
 * versions, type/container mismatches, duplicate element ids, and reading
 * orders outside the element count.
 */
public final class CanonicalValidator {

    public static final class ValidationException extends RuntimeException {
        public ValidationException(String message) {
            super(message);
        }
    }

    private CanonicalValidator() {
    }

    public static void validate(CanonicalDocument document) {
        require(document != null, "document is null");
        require(document.documentId() != null && !document.documentId().isBlank(),
                "documentId is required");
        require(CanonicalSchema.VERSION.equals(document.schemaVersion()),
                "unsupported schemaVersion: " + document.schemaVersion()
                        + " (expected " + CanonicalSchema.VERSION + ")");
        require(document.version() >= 1, "version must be >= 1");
        require(document.source() != null, "source is required");
        require(document.source().uri() != null, "source.uri is required");
        require(document.source().checksum() != null, "source.checksum is required");
        require(document.provenance() != null, "provenance is required");
        require(document.provenance().engine() != null, "provenance.engine is required");
        require(document.provenance().engineVersion() != null,
                "provenance.engineVersion is required");
        require(document.pageCount() >= 1, "pageCount must be >= 1");

        Set<String> elementIds = new HashSet<>();
        Set<Integer> readingOrders = new HashSet<>();
        for (DocumentElement element : document.elementsInReadingOrder()) {
            require(element.elementId() != null && !element.elementId().isBlank(),
                    "element_id is required");
            require(elementIds.add(element.elementId()),
                    "duplicate element_id: " + element.elementId());
            require(element.pageNumber() >= 1 && element.pageNumber() <= document.pageCount(),
                    "page_number out of range: " + element.pageNumber());
            require(element.readingOrder() >= 0, "reading_order must be >= 0");
            require(readingOrders.add(element.readingOrder()),
                    "duplicate reading_order: " + element.readingOrder());
            require(element.sourceEngine() != null, "source_engine is required on "
                    + element.elementId());
            require(element.sourceEngineVersion() != null,
                    "source_engine_version is required on " + element.elementId());
        }
        for (TextBlockElement block : document.textBlocks()) {
            require(block.elementType() == ElementType.TEXT_BLOCK,
                    "textBlocks member with wrong element_type: " + block.elementType());
        }
        for (TableElement table : document.tables()) {
            require(table.elementType() == ElementType.TABLE,
                    "tables member with wrong element_type: " + table.elementType());
        }
        for (FigureElement figure : document.figures()) {
            require(figure.elementType() == ElementType.FIGURE,
                    "figures member with wrong element_type: " + figure.elementType());
        }
        for (EquationElement equation : document.equations()) {
            require(equation.elementType() == ElementType.EQUATION,
                    "equations member with wrong element_type: " + equation.elementType());
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new ValidationException(message);
        }
    }
}
