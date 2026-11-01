#!/usr/bin/env python3
# coding=utf-8
# Copyright (C) 2026 soswow
# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry checks for arc-length node transfer. Run with Inkscape's Python."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inkex.paths import Path
from inkex.transforms import Transform

from node_spacing import (
    PathSpacingError,
    curve_marks,
    measure_path,
    normalized_path,
    transfer_node_spacing,
)
from debug_marks import (
    label_tangent,
    node_label_order,
    text_axes,
    text_placement,
    text_rotation_degrees,
)


def assert_close(actual, expected, tolerance=1e-4, label="distance"):
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: {actual} != {expected} (tol {tolerance})")


def node_distances_of(path, transform=None):
    measured = measure_path(normalized_path(Path(path), transform))
    return measured.node_distances


def test_straight_line_keeps_absolute_distances():
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,5 L 100,5")
    result = transfer_node_spacing(
        source, Transform(), target, Transform(), proportional=False
    )
    if result.curve_index != 1 or result.placed_count != 3 or result.skipped_count != 0:
        raise AssertionError(result)
    distances = node_distances_of(result.path)
    assert_close(distances[1], 10)
    assert_close(distances[2], 30)
    assert_close(distances[3], 60)
    assert_close(distances[4], 100)


def test_either_argument_can_be_the_curve():
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,5 L 100,5")
    result = transfer_node_spacing(target, Transform(), source, Transform())
    if result.curve_index != 0:
        raise AssertionError(result.curve_index)
    distances = node_distances_of(result.path)
    assert_close(distances[1], 10)
    assert_close(distances[2], 30)
    assert_close(distances[3], 60)


def test_cubic_curve_uses_arc_length_not_chord():
    source = Path("M 0,0 L 25,0 L 40,0")
    target = Path("M 0,0 C 0,80 100,80 100,0")
    result = transfer_node_spacing(source, Transform(), target, Transform())
    distances = node_distances_of(result.path)
    if len(distances) != 4:
        raise AssertionError(distances)
    assert_close(distances[1], 25, tolerance=1e-3)
    assert_close(distances[2], 40, tolerance=1e-3)
    if distances[-1] <= 100:
        raise AssertionError(f"curve should be longer than its chord, got {distances[-1]}")


def test_distances_past_the_end_are_skipped():
    source = Path("M 0,0 L 10,0 L 80,0 L 120,0")
    target = Path("M 0,0 L 50,0")
    result = transfer_node_spacing(source, Transform(), target, Transform())
    if result.placed_count != 1 or result.skipped_count != 2:
        raise AssertionError(result)
    distances = node_distances_of(result.path)
    assert_close(distances[1], 10)
    assert_close(distances[2], 50)


def test_proportional_mode_scales_to_the_curve():
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,0 L 120,0")
    result = transfer_node_spacing(
        source, Transform(), target, Transform(), proportional=True
    )
    distances = node_distances_of(result.path)
    assert_close(distances[1], 20)
    assert_close(distances[2], 60)
    assert_close(distances[3], 120)


def test_element_scale_is_measured_on_the_canvas():
    # translate(5) scale(2): local x maps to document x = 2x + 5, length scale 2.
    # Local segment is 50 long, so the on-canvas curve is 100 long.
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,0 L 50,0")
    transform = Transform("translate(5,0) scale(2,2)")
    result = transfer_node_spacing(source, Transform(), target, transform)
    distances = node_distances_of(result.path, transform)
    assert_close(distances[1], 10, tolerance=1e-3)
    assert_close(distances[2], 30, tolerance=1e-3)
    assert_close(distances[-1], 100, tolerance=1e-3)


def test_closed_spacing_path_uses_corner_distances():
    # Legs 30 and 50, closing side 40. Corners at 0, 30 and 80. Loop length 120.
    source = Path("M 0,0 L 30,0 L 0,40 Z")
    target = Path("M 0,0 L 200,0")
    result = transfer_node_spacing(source, Transform(), target, Transform())
    distances = node_distances_of(result.path)
    assert_close(distances[1], 30, tolerance=1e-3)
    assert_close(distances[2], 80, tolerance=1e-3)
    assert_close(distances[3], 200, tolerance=1e-3)


def test_relative_and_horizontal_commands():
    source = Path("m 0,0 l 10,0 l 20,0")
    target = Path("M 0,8 H 90")
    result = transfer_node_spacing(source, Transform(), target, Transform())
    distances = node_distances_of(result.path)
    assert_close(distances[1], 10)
    assert_close(distances[2], 30)
    assert_close(distances[3], 90)


def test_arc_target():
    # Semicircle radius 10, length pi*10. Place a node 10 units along it.
    source = Path("M 0,0 L 10,0 L 40,0")
    target = Path("M 0,0 A 10,10 0 0 1 20,0")
    result = transfer_node_spacing(source, Transform(), target, Transform())
    distances = node_distances_of(result.path)
    assert_close(distances[1], 10, tolerance=1e-2)
    if distances[-1] < 30:
        raise AssertionError(distances)


def test_straight_cubic_matches_a_line():
    source = Path("M 0,0 L 15,0 L 45,0")
    target = Path("M 0,0 C 30,0 60,0 90,0")
    result = transfer_node_spacing(source, Transform(), target, Transform())
    distances = node_distances_of(result.path)
    assert_close(distances[1], 15, tolerance=1e-3)
    assert_close(distances[2], 45, tolerance=1e-3)
    assert_close(distances[3], 90, tolerance=1e-3)


def test_curve_marks_follow_nodes_and_arc_midpoints():
    path = Path("M 0,0 L 10,0 L 40,0")
    marks = curve_marks(path, Transform())
    if len(marks.nodes) != 3 or len(marks.segments) != 2:
        raise AssertionError(marks)
    assert_close(marks.nodes[0].position.real, 0, label="node x")
    assert_close(marks.nodes[1].position.real, 10, label="node x")
    assert_close(marks.nodes[2].position.real, 40, label="node x")
    assert_close(marks.nodes[0].tangent.real, 1, tolerance=1e-6, label="tangent x")
    assert_close(marks.nodes[2].tangent.real, 1, tolerance=1e-6, label="end tangent x")
    assert_close(marks.segments[0].length, 10)
    assert_close(marks.segments[0].midpoint.real, 5, label="midpoint x")
    assert_close(marks.segments[1].length, 30)
    assert_close(marks.segments[1].midpoint.real, 25, label="midpoint x")
    assert_close(marks.segments[0].normal.real, 0, tolerance=1e-6, label="normal x")
    assert_close(abs(marks.segments[0].normal.imag), 1, tolerance=1e-6, label="normal y")
    assert_close(marks.nodes[0].normal.imag, marks.segments[0].normal.imag, tolerance=1e-6, label="same side")


def test_labels_sit_outside_a_clockwise_shape():
    # Clockwise on screen. The top edge runs left to right, so outside is up.
    path = Path("M 0,0 L 10,0 L 10,10 L 0,10 Z")
    marks = curve_marks(path, Transform())
    top = marks.segments[0]
    assert_close(top.normal.real, 0, tolerance=1e-6, label="normal x")
    assert_close(top.normal.imag, -1, tolerance=1e-6, label="normal y")
    assert_close(marks.nodes[0].normal.imag, -1, tolerance=1e-6, label="node normal y")


def test_closed_curve_marks_include_the_return_segment():
    path = Path("M 0,0 L 30,0 L 0,40 Z")
    marks = curve_marks(path, Transform())
    if len(marks.nodes) != 3 or len(marks.segments) != 3:
        raise AssertionError((marks.nodes, marks.segments))
    assert_close(marks.segments[2].length, 40, tolerance=1e-3)
    assert_close(marks.segments[2].midpoint.real, 0, tolerance=1e-3, label="close x")
    assert_close(marks.segments[2].midpoint.imag, 20, tolerance=1e-3, label="close y")


def test_node_numbers_follow_the_chosen_end():
    nodes = [1, 2, 3, 4]
    if node_label_order(nodes, False, False) != [1, 2, 3, 4]:
        raise AssertionError("path order")
    if node_label_order(nodes, True, False) != [4, 3, 2, 1]:
        raise AssertionError("open path from the other end")
    if node_label_order(nodes, True, True) != [1, 4, 3, 2]:
        raise AssertionError("closed path from the other way")


def _text_extent(tangent, normal, alignment):
    """Direction the letters occupy, starting from the offset anchor."""
    _rotation, text_anchor, dominant = text_placement(tangent, normal, alignment)
    baseline, glyph_up = text_axes(tangent, alignment)
    along_baseline = baseline if text_anchor == "start" else -baseline
    across_baseline = glyph_up if dominant == "alphabetic" else -glyph_up
    return along_baseline, across_baseline


def test_text_stays_on_the_outside_for_either_direction():
    # Horizontal tangent. Right of travel is downward. A counterclockwise
    # fill keeps that side; a clockwise fill uses the opposite side.
    tangent = 1 + 0j
    outside_ccw = 0 + 1j
    outside_cw = 0 - 1j
    for alignment in ("horizontal", "along", "along-90"):
        for normal in (outside_ccw, outside_cw):
            along_baseline, across_baseline = _text_extent(tangent, normal, alignment)
            # The long side of an along-90 label is the baseline. The long
            # side of an along label is the glyph height. Either way the
            # text must not step back toward the fill.
            along_dot = along_baseline.real * normal.real + along_baseline.imag * normal.imag
            across_dot = across_baseline.real * normal.real + across_baseline.imag * normal.imag
            if along_dot < -1e-6 or across_dot < -1e-6:
                raise AssertionError(
                    f"{alignment} grows into the fill: {along_dot}, {across_dot}"
                )


def test_along_90_up_points_toward_the_lower_number():
    # Node 1 is to the left of node 2. The top of the label points left,
    # whether the path was drawn that way or numbered from the other end.
    numbering = 1 + 0j
    for path_tangent, from_end in ((numbering, False), (-numbering, True)):
        used = label_tangent(path_tangent, from_end)
        _baseline, glyph_up = text_axes(used, "along-90")
        assert_close(glyph_up.real, -1, tolerance=1e-6, label="up x")
        assert_close(glyph_up.imag, 0, tolerance=1e-6, label="up y")


def test_text_rotation_follows_the_tangent():
    right = 1 + 0j
    down = 0 + 1j
    if text_rotation_degrees(right, "horizontal") is not None:
        raise AssertionError("horizontal text should not rotate")
    assert_close(text_rotation_degrees(right, "along"), 0, label="along")
    assert_close(text_rotation_degrees(right, "along-90"), -90, label="along-90")
    assert_close(text_rotation_degrees(down, "along"), 90, label="down along")
    assert_close(text_rotation_degrees(down, "along-90"), 0, label="down along-90")


def test_refuses_two_bare_segments():
    try:
        transfer_node_spacing(
            Path("M 0,0 L 10,0"),
            Transform(),
            Path("M 0,1 L 10,1"),
            Transform(),
        )
    except PathSpacingError:
        return
    raise AssertionError("expected PathSpacingError")


def end_point_of(path, index):
    proxies = list(normalized_path(Path(path)).proxy_iterator())
    return proxies[index].end_point


def test_measure_spacing_from_the_last_node():
    # Nodes at 0, 10, 30, 60. From the last node those are 0, 30, 50, 60.
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,0 L 100,0")
    result = transfer_node_spacing(
        source,
        Transform(),
        target,
        Transform(),
        measure_source_from_end=True,
    )
    distances = node_distances_of(result.path)
    assert_close(distances[1], 30)
    assert_close(distances[2], 50)
    assert_close(distances[3], 60)
    assert_close(distances[4], 100)
    assert_close(end_point_of(result.path, 0).x, 0, label="start x")


def test_add_nodes_from_the_last_node_of_the_curve():
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,0 L 100,0")
    result = transfer_node_spacing(
        source,
        Transform(),
        target,
        Transform(),
        add_nodes_from_end=True,
    )
    distances = node_distances_of(result.path)
    assert_close(distances[1], 10)
    assert_close(distances[2], 30)
    assert_close(distances[3], 60)
    assert_close(end_point_of(result.path, 0).x, 100, label="start x")
    assert_close(end_point_of(result.path, -1).x, 0, label="end x")


def test_source_and_curve_ends_are_independent():
    source = Path("M 0,0 L 10,0 L 30,0 L 60,0")
    target = Path("M 0,0 L 100,0")
    result = transfer_node_spacing(
        source,
        Transform(),
        target,
        Transform(),
        measure_source_from_end=True,
        add_nodes_from_end=True,
    )
    distances = node_distances_of(result.path)
    assert_close(distances[1], 30)
    assert_close(distances[2], 50)
    assert_close(distances[3], 60)
    assert_close(end_point_of(result.path, 0).x, 100, label="start x")
    assert_close(end_point_of(result.path, -1).x, 0, label="end x")


def test_closed_spacing_can_be_measured_the_other_way():
    # Forward corners at 30 and 80. The other way reaches them at 40 and 90.
    source = Path("M 0,0 L 30,0 L 0,40 Z")
    target = Path("M 0,0 L 200,0")
    result = transfer_node_spacing(
        source,
        Transform(),
        target,
        Transform(),
        measure_source_from_end=True,
    )
    distances = node_distances_of(result.path)
    assert_close(distances[1], 40, tolerance=1e-3)
    assert_close(distances[2], 90, tolerance=1e-3)


def test_reversed_cubic_keeps_arc_length_from_the_new_start():
    source = Path("M 0,0 L 25,0 L 40,0")
    target = Path("M 0,0 C 0,80 100,80 100,0")
    result = transfer_node_spacing(
        source,
        Transform(),
        target,
        Transform(),
        add_nodes_from_end=True,
    )
    distances = node_distances_of(result.path)
    assert_close(distances[1], 25, tolerance=1e-3)
    assert_close(distances[2], 40, tolerance=1e-3)
    start = end_point_of(result.path, 0)
    assert_close(start.x, 100, tolerance=1e-3, label="start x")
    assert_close(start.y, 0, tolerance=1e-3, label="start y")


def test_refuses_a_target_that_already_has_nodes():
    try:
        transfer_node_spacing(
            Path("M 0,0 L 1,0 L 2,0"),
            Transform(),
            Path("M 0,1 L 1,1 L 2,1"),
            Transform(),
        )
    except PathSpacingError:
        return
    raise AssertionError("expected PathSpacingError")


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"ok {test.__name__}")
        except Exception as error:
            failed += 1
            print(f"FAIL {test.__name__}: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
