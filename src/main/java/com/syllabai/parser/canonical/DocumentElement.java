package com.syllabai.parser.canonical;

/**
 * Any extracted element of the canonical document (Master Spec §8). Sealed:
 * the four permitted shapes are exactly the four arrays of the canonical
 * JSON — text blocks, tables, figures, equations. Every element, whatever
 * its container, carries the same §8 core fields.
 */
public sealed interface DocumentElement
        permits TextBlockElement, TableElement, FigureElement, EquationElement {

    /** Stable id within the document, e.g. "e000123". */
    String elementId();

    /** 1-based page number the element appears on. */
    int pageNumber();

    /** Geometry in PDF points, or null when the engine reports none. */
    BoundingBox boundingBox();

    /** Extracted text ("content"); null for pure figures without captions. */
    String text();

    /** Container/type discriminant (§8 element_type). */
    ElementType elementType();

    /** Document-wide reading order, 0-based, assigned by the engine's output order. */
    int readingOrder();

    /** Extraction confidence 0–1; engines that assert exactness report 1.0. */
    Double confidence();

    /** Producing engine, e.g. "opendataloader-pdf". */
    String sourceEngine();

    /** Producing engine's exact version. */
    String sourceEngineVersion();
}
