package com.syllabai.parser.canonical;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Axis-aligned bounding box of an extracted element, in PDF points
 * (1/72 inch), PDF user-space coordinates: origin bottom-left, y grows upward.
 * Engines that only produce page-level or no geometry may leave the box null
 * (Master Spec §8: "bounding box if available").
 *
 * @param x      left edge
 * @param y      bottom edge
 * @param width  box width
 * @param height box height
 * @param unit   coordinate unit, currently always "pt"
 */
public record BoundingBox(
        @JsonProperty("x") double x,
        @JsonProperty("y") double y,
        @JsonProperty("width") double width,
        @JsonProperty("height") double height,
        @JsonProperty("unit") String unit) {

    public BoundingBox(double x, double y, double width, double height) {
        this(x, y, width, height, "pt");
    }

    /** Box from corner coordinates [x1, y1, x2, y2] as emitted by engines. */
    public static BoundingBox fromCorners(double x1, double y1, double x2, double y2) {
        return new BoundingBox(x1, y1, x2 - x1, y2 - y1, "pt");
    }
}
