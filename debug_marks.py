# coding=utf-8
# Copyright (C) 2026 soswow
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw node numbers and segment lengths beside a path.

Each curve gets one group. The group is positioned in document coordinates
and then transformed so it sits correctly inside a transformed parent.
"""

from __future__ import annotations

import math

import inkex

from node_spacing import curve_marks


def _format_length(length_in_units: float, unit_name: str) -> str:
    text = f"{length_in_units:.2f}".rstrip("0").rstrip(".")
    return f"{text} {unit_name}"


def text_rotation_degrees(tangent: complex, alignment: str):
    """Degrees for an SVG rotate(), or None when the text stays horizontal.

    SVG angles match atan2 in y-down coordinates, so this turns the baseline
    onto the tangent. "along-90" is that direction turned 90 degrees back.
    """
    if alignment == "horizontal":
        return None
    angle = math.degrees(math.atan2(tangent.imag, tangent.real))
    if alignment == "along-90":
        return angle - 90.0
    return angle


def _unit(vector: complex) -> complex:
    length = abs(vector)
    if length < 1e-12:
        return 1 + 0j
    return vector / length


def _right_normal(tangent: complex) -> complex:
    """Screen-space right of travel. (1, 0) becomes (0, 1), which is downward."""
    return _unit(tangent) * 1j


def text_axes(tangent: complex, alignment: str):
    """Baseline and glyph-up directions after the alignment rotation.

    Both are unit vectors in y-down coordinates. Glyph up is the direction
    the letters rise from the baseline.
    """
    if alignment == "along":
        direction = _unit(tangent)
        return direction, -_right_normal(direction)
    if alignment == "along-90":
        direction = _unit(tangent)
        # Baseline is the tangent turned 90° back, which is the left normal.
        return -_right_normal(direction), -direction
    return 1 + 0j, 0 - 1j


def text_placement(tangent: complex, normal: complex, alignment: str):
    """Rotation, text-anchor, and dominant-baseline so the text sits outside.

    The anchor is already offset along `normal`. text-anchor and the
    baseline then decide which side of that point the letters occupy.
    """
    baseline, glyph_up = text_axes(tangent, alignment)
    text_anchor = "start"
    if (baseline.real * normal.real + baseline.imag * normal.imag) < -1e-8:
        text_anchor = "end"
    dominant_baseline = "alphabetic"
    if (glyph_up.real * normal.real + glyph_up.imag * normal.imag) < -1e-8:
        dominant_baseline = "hanging"
    return text_rotation_degrees(tangent, alignment), text_anchor, dominant_baseline


def label_tangent(tangent: complex, number_from_end: bool) -> complex:
    """Tangent in the direction of increasing node numbers.

    Labels are rotated from that direction, so the top of an along-90 label
    points back toward the lower number on both paths. A path numbered from
    its other end is stored the opposite way, and its tangent is flipped.
    """
    if number_from_end:
        return -tangent
    return tangent


def node_label_order(nodes, number_from_end: bool, closed: bool):
    """Order nodes so label 1 is the end chosen in the dialog.

    An open path counted from the other end is reversed. A closed path keeps
    its start node and walks the remaining nodes backwards, which is how
    distances are measured the other way around the loop.
    """
    ordered = list(nodes)
    if not number_from_end or len(ordered) < 2:
        return ordered
    if closed:
        return [ordered[0]] + list(reversed(ordered[1:]))
    return list(reversed(ordered))


def _add_text(
    parent,
    x: float,
    y: float,
    text: str,
    font_size: float,
    rotation_degrees,
    text_anchor: str = "start",
    dominant_baseline: str = "alphabetic",
):
    element = parent.add(inkex.TextElement())
    element.set("x", str(x))
    element.set("y", str(y))
    element.text = text
    style = {
        "font-size": str(font_size),
        "font-family": "sans-serif",
        "fill": "#000000",
        "stroke": "none",
    }
    # Defaults leave the text growing to the right and upward. Anything else
    # is what keeps the letters on the outside of this particular curve.
    if text_anchor != "start":
        style["text-anchor"] = text_anchor
    if dominant_baseline != "alphabetic":
        style["dominant-baseline"] = dominant_baseline
    element.style = style
    if rotation_degrees is not None:
        element.set("transform", f"rotate({rotation_degrees},{x},{y})")
    return element


def _add_node_circle(parent, x: float, y: float, radius: float):
    circle = parent.add(inkex.Circle(cx=str(x), cy=str(y), r=str(radius)))
    circle.style = {"fill": "#000000", "stroke": "none"}
    return circle


def clear_debug_group(svg, path_element):
    """Remove a previous debug group created for this path."""
    debug_id = _debug_group_id(path_element)
    previous = svg.getElementById(debug_id)
    if previous is not None:
        previous.delete()


def add_debug_group(
    svg,
    path_element,
    group_label: str,
    number_nodes: bool,
    segment_lengths: bool,
    unit_name: str,
    text_size: float,
    length_factor: float,
    text_alignment: str = "horizontal",
    text_offset: float = 12.0,
    number_from_end: bool = False,
):
    """Add one group of debug marks for path_element, replacing any earlier group."""
    clear_debug_group(svg, path_element)
    if not number_nodes and not segment_lengths:
        return None

    parent = path_element.getparent()
    if parent is None:
        return None

    marks = curve_marks(path_element.path, path_element.composed_transform())
    # Text size and the gap from the curve are in pixels. Units only change length labels.
    font_size = svg.unittouu(f"{text_size}px")
    if font_size <= 0:
        font_size = 1.0
    offset_distance = svg.unittouu(f"{text_offset}px")
    if offset_distance < 0:
        offset_distance = 0.0

    group = parent.add(inkex.Group())
    group.set("id", _debug_group_id(path_element))
    group.set(inkex.addNS("label", "inkscape"), group_label)
    # Positions are in document space. Cancel the parent's transform so the
    # marks land on the path even when the path sits inside a scaled group.
    group.transform = -parent.composed_transform()

    if number_nodes:
        radius = font_size * 0.22
        labeled_nodes = node_label_order(marks.nodes, number_from_end, marks.closed)
        for index, node in enumerate(labeled_nodes, start=1):
            position = node.position
            label_position = position + node.normal * offset_distance
            rotation, text_anchor, dominant_baseline = text_placement(
                label_tangent(node.tangent, number_from_end),
                node.normal,
                text_alignment,
            )
            _add_node_circle(group, position.real, position.imag, radius)
            _add_text(
                group,
                label_position.real,
                label_position.imag,
                str(index),
                font_size,
                rotation,
                text_anchor,
                dominant_baseline,
            )

    if segment_lengths:
        for segment in marks.segments:
            label_position = segment.midpoint + segment.normal * offset_distance
            rotation, text_anchor, dominant_baseline = text_placement(
                label_tangent(segment.tangent, number_from_end),
                segment.normal,
                text_alignment,
            )
            _add_text(
                group,
                label_position.real,
                label_position.imag,
                _format_length(segment.length * length_factor, unit_name),
                font_size,
                rotation,
                text_anchor,
                dominant_baseline,
            )

    return group


def _debug_group_id(path_element) -> str:
    raw_id = path_element.get_id()
    safe_id = "".join(character if character.isalnum() else "-" for character in raw_id)
    return f"node-spacing-debug-{safe_id}"
