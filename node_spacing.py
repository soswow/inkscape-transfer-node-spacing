# coding=utf-8
# Copyright (C) 2026 soswow
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy arc-length node positions from one path onto a two-node curve.

Distances are measured along the path (arc length), not as straight-line
chords between nodes. The curve that receives the nodes must be a single
open segment. Its existing shape is kept; only intermediate nodes are inserted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from inkex.paths import Move, Path
from inkex.paths.interfaces import ILengthSettings, LengthSettings
from inkex.transforms import Transform


# Tighter than inkex defaults so inserted nodes land on the requested length.
LENGTH_SETTINGS = LengthSettings(min_depth=6, error=1e-8)
ILENGTH_SETTINGS = ILengthSettings(
    min_depth=6,
    error=1e-8,
    length_tol=1e-7,
    maxits=10000,
)


class PathSpacingError(ValueError):
    """The selected paths cannot be used for this transfer."""


@dataclass(frozen=True)
class MeasuredPath:
    """Node positions along one subpath, in the same units as the path."""

    # Includes the start node at 0. For an open path the last entry is the
    # path length. For a closed path the last entry is the last corner, and
    # the return to the start is only included in total_length.
    node_distances: Tuple[float, ...]
    total_length: float
    closed: bool

    @property
    def node_count(self) -> int:
        return len(self.node_distances)

    def spacing_distances(self) -> Tuple[float, ...]:
        """Arc length of every node except the start.

        The start is already the curve's first node. The spacing path's last
        node is included: if the curve is longer, that distance becomes a
        node before the curve's own end. A closed path does not add an extra
        distance for the return to the start.
        """
        return self.node_distances[1:]


@dataclass(frozen=True)
class TransferResult:
    """New path data for the curve that was subdivided."""

    path: Path
    # 0 if the first path argument was the curve, 1 if the second was.
    curve_index: int
    placed_count: int
    skipped_count: int


def length_tolerance(total_length: float) -> float:
    """Ignore gaps smaller than this when deciding whether two nodes coincide."""
    return max(1e-6, abs(total_length) * 1e-9)


def normalized_path(path: Path, transform: Transform | None = None) -> Path:
    """Absolute path with shorthand commands expanded, optionally transformed.

    Arc length is measured after the transform so a scaled object uses its
    on-canvas length. The curve parameter itself is unchanged by an affine
    transform, so a split time computed in document space can be applied to
    the untransformed path and the element's transform can stay as it is.
    """
    if transform is not None:
        path = path.transform(transform)
    return path.to_absolute().to_non_shorthand()


def measure_path(
    path: Path,
    length_settings: LengthSettings = LENGTH_SETTINGS,
) -> MeasuredPath:
    """Cumulative arc length at each node of a single subpath."""
    node_distances: List[float] = [0.0]
    total_length = 0.0
    closed = False
    subpath_count = 0
    has_segment = False

    for proxy in path.proxy_iterator():
        command_letter = proxy.letter.upper()
        if command_letter == "M":
            subpath_count += 1
            if subpath_count > 1:
                raise PathSpacingError(
                    "Paths with more than one subpath are not supported. "
                    "Use Path > Break Apart, then run the extension on one subpath."
                )
            continue

        segment_length = proxy.length(settings=length_settings)
        if command_letter == "Z":
            closed = True
            total_length += segment_length
            continue

        total_length += segment_length
        node_distances.append(total_length)
        has_segment = True

    if not has_segment:
        raise PathSpacingError("One of the paths has no segments.")

    return MeasuredPath(tuple(node_distances), total_length, closed)


@dataclass(frozen=True)
class NodeMark:
    """A node and the direction of the path as it leaves that node."""

    position: complex
    # Unit tangent. The last node of an open path uses the incoming direction.
    tangent: complex
    # Unit normal pointing to the same side as the segment labels.
    normal: complex


@dataclass(frozen=True)
class SegmentMark:
    """Arc-length midpoint of one segment, in the path's coordinate system."""

    midpoint: complex
    length: float
    # Unit normal used to nudge a label off the stroke. Falls back to +x.
    normal: complex
    # Unit tangent at the midpoint, used to rotate labels along the curve.
    tangent: complex


@dataclass(frozen=True)
class CurveMarks:
    """Node positions and segment midpoints for debug labels."""

    nodes: Tuple[NodeMark, ...]
    segments: Tuple[SegmentMark, ...]
    # True when the path returns to its start. Numbering from the other end
    # keeps that start node and walks the rest backwards.
    closed: bool = False


def _as_complex(point) -> complex:
    return complex(point.x, point.y)


def _right_normal(tangent: complex) -> complex:
    """Screen-space right-hand normal of a unit tangent."""
    normal = tangent * 1j
    if abs(normal) < 1e-12:
        return 0 + 1j
    return normal


def _signed_fill_area(path: Path) -> float:
    """Signed area of the path the way SVG would fill it.

    Positive means the path runs counterclockwise on screen, so the interior
    is on the left of travel. An open path is closed for this measurement
    because fill does the same.
    """
    from inkex.bezier import csparea
    from inkex.paths import ZoneClose

    closed = Path(path)
    if not closed or str(closed[-1].letter).upper() != "Z":
        closed.append(ZoneClose())
    try:
        return float(csparea(closed.to_superpath()))
    except (ValueError, ZeroDivisionError, FloatingPointError):
        return 0.0


def _outside_sign(path: Path) -> float:
    """+1 when the right-hand normal points outside the fill, otherwise -1.

    A straight path has no interior, so labels stay on the right of travel.
    """
    area = _signed_fill_area(path)
    if area < -1e-6:
        return -1.0
    return 1.0


def _unit_tangent(proxy, time: float) -> complex:
    """Unit tangent at time. +x if the tangent is undefined."""
    try:
        tangent = proxy.cunit_tangent(time)
    except (ValueError, ZeroDivisionError, FloatingPointError):
        return 1 + 0j
    if abs(tangent) < 1e-12:
        return 1 + 0j
    return tangent


def curve_marks(
    path: Path,
    transform: Transform | None = None,
) -> CurveMarks:
    """Node positions and per-segment arc lengths after an optional transform.

    Positions are in the transformed coordinate system. A closed path does
    not repeat its start node, but the closing segment is included.
    """
    document_path = normalized_path(path, transform)
    node_positions: List[complex] = []
    segments: List[SegmentMark] = []
    # Tangent of the segment that leaves each node, in node order.
    outgoing_tangents: List[complex] = []
    last_end_tangent = 1 + 0j
    closed = False

    for proxy in document_path.proxy_iterator():
        command_letter = proxy.letter.upper()
        if command_letter == "M":
            node_positions.append(_as_complex(proxy.end_point))
            continue

        segment_length = proxy.length(settings=LENGTH_SETTINGS)
        if segment_length <= length_tolerance(segment_length):
            midpoint = _as_complex(proxy.end_point)
            tangent = 1 + 0j
            normal = 1 + 0j
            start_tangent = 1 + 0j
            end_tangent = 1 + 0j
        else:
            time = proxy.ilength(segment_length / 2, settings=ILENGTH_SETTINGS)
            midpoint = _as_complex(proxy.point(time))
            tangent = _unit_tangent(proxy, time)
            normal = _right_normal(tangent)
            start_tangent = _unit_tangent(proxy, 0)
            end_tangent = _unit_tangent(proxy, 1)

        segments.append(SegmentMark(midpoint, segment_length, normal, tangent))
        outgoing_tangents.append(start_tangent)
        last_end_tangent = end_tangent
        if command_letter == "Z":
            closed = True
        else:
            node_positions.append(_as_complex(proxy.end_point))

    nodes: List[NodeMark] = []
    for index, position in enumerate(node_positions):
        if index < len(outgoing_tangents):
            tangent = outgoing_tangents[index]
        else:
            tangent = last_end_tangent
        nodes.append(NodeMark(position, tangent, _right_normal(tangent)))

    outside_sign = _outside_sign(document_path)
    if outside_sign < 0:
        nodes = [
            NodeMark(node.position, node.tangent, node.normal * outside_sign)
            for node in nodes
        ]
        segments = [
            SegmentMark(
                segment.midpoint,
                segment.length,
                segment.normal * outside_sign,
                segment.tangent,
            )
            for segment in segments
        ]

    return CurveMarks(tuple(nodes), tuple(segments), closed)


def _is_open_two_node_curve(measured: MeasuredPath) -> bool:
    return (not measured.closed) and measured.node_count == 2


def choose_curve_index(first: MeasuredPath, second: MeasuredPath) -> int:
    """Return 0 or 1: which measured path is the curve to subdivide.

    The open path with exactly two nodes is the curve. The other path
    supplies distances. Click order is not used. The two-node curve is
    unambiguous, and Inkscape does not always pass click order through
    to extensions.
    """
    first_is_curve = _is_open_two_node_curve(first)
    second_is_curve = _is_open_two_node_curve(second)

    if first_is_curve and second_is_curve:
        raise PathSpacingError(
            "Both paths have only two nodes, so there is no spacing to copy. "
            "One path needs intermediate nodes. The other must be an open "
            "curve with exactly two nodes."
        )

    if first_is_curve and not second_is_curve:
        return 0

    if second_is_curve and not first_is_curve:
        return 1

    raise PathSpacingError(
        "The curve to subdivide must be an open path with exactly two nodes "
        "(one segment). The other path supplies the node distances. "
        "A target that already has extra nodes is not handled yet."
    )


def flip_measurement(measured: MeasuredPath) -> MeasuredPath:
    """Same nodes, measured from the other end of the path.

    An open path swaps its ends. A closed path keeps its start node and
    walks the loop the other way.
    """
    total_length = measured.total_length
    if measured.closed:
        mirrored_distances = [0.0]
        for distance in reversed(measured.node_distances[1:]):
            mirrored_distances.append(total_length - distance)
        return MeasuredPath(tuple(mirrored_distances), total_length, True)

    mirrored_distances = [
        total_length - distance for distance in reversed(measured.node_distances)
    ]
    return MeasuredPath(tuple(mirrored_distances), total_length, False)


def distances_to_place(
    source: MeasuredPath,
    target_length: float,
    proportional: bool,
) -> Tuple[Tuple[float, ...], int]:
    """Return distances that fall strictly inside the target, and a skip count."""
    if target_length <= length_tolerance(target_length):
        raise PathSpacingError("The curve to subdivide has zero length.")

    source_distances = source.spacing_distances()
    if proportional:
        if source.total_length <= length_tolerance(source.total_length):
            raise PathSpacingError("The spacing path has zero length.")
        scale = target_length / source.total_length
        source_distances = tuple(distance * scale for distance in source_distances)

    tolerance = length_tolerance(target_length)
    accepted: List[float] = []
    skipped_count = 0
    for distance in source_distances:
        # The curve already has a node at 0 and at its own end.
        if distance <= tolerance or abs(distance - target_length) <= tolerance:
            continue
        if distance > target_length:
            skipped_count += 1
            continue
        if accepted and abs(distance - accepted[-1]) <= tolerance:
            continue
        accepted.append(distance)

    return tuple(accepted), skipped_count


def _single_drawing_segment(path: Path):
    """Return the Move and the only drawing command of a two-node open path."""
    move_proxy = None
    drawing_proxy = None
    for proxy in path.proxy_iterator():
        command_letter = proxy.letter.upper()
        if command_letter == "M":
            if move_proxy is not None:
                raise PathSpacingError(
                    "The curve to subdivide must be a single open segment."
                )
            move_proxy = proxy
            continue
        if command_letter == "Z":
            raise PathSpacingError(
                "The curve to subdivide must be open, with exactly two nodes."
            )
        if drawing_proxy is not None:
            raise PathSpacingError(
                "The curve to subdivide must be a single open segment."
            )
        drawing_proxy = proxy

    if move_proxy is None or drawing_proxy is None:
        raise PathSpacingError(
            "The curve to subdivide must be a single open segment."
        )
    return move_proxy, drawing_proxy


def subdivide_at_distances(
    document_segment,
    local_segment,
    distances: Sequence[float],
) -> List:
    """Split one segment so new nodes sit at the given document-space arc lengths.

    Each split is done on the remaining tail. The time comes from the
    transformed segment (real on-canvas length) and is applied to the local
    segment, which keeps the element's transform intact.
    """
    document_remaining = document_segment
    local_remaining = local_segment
    consumed_length = 0.0
    pieces = []

    for distance in distances:
        travel = distance - consumed_length
        remaining_length = document_remaining.length(settings=LENGTH_SETTINGS)
        tolerance = length_tolerance(remaining_length)
        if travel <= tolerance or travel >= remaining_length - tolerance:
            continue

        time = document_remaining.ilength(travel, settings=ILENGTH_SETTINGS)
        if time <= 0.0 or time >= 1.0:
            continue

        _document_left, document_remaining = document_remaining.split(time)
        local_left, local_remaining = local_remaining.split(time)
        pieces.append(local_left.command)
        consumed_length = distance

    pieces.append(local_remaining.command)
    return pieces


def rebuild_open_path(move_proxy, pieces: Sequence) -> Path:
    """Build an absolute open path from the original start point and new segments."""
    start_point = move_proxy.end_point
    rebuilt = Path()
    rebuilt.append(Move(complex(start_point.x, start_point.y)))
    for piece in pieces:
        rebuilt.append(piece)
    return rebuilt


def transfer_node_spacing(
    first_path: Path,
    first_transform: Transform,
    second_path: Path,
    second_transform: Transform,
    proportional: bool = False,
    measure_source_from_end: bool = False,
    add_nodes_from_end: bool = False,
) -> TransferResult:
    """Subdivide the two-node curve using arc lengths from the other path.

    Either argument may be the spacing path. The open two-node path is the
    one that is rewritten. The two direction flags choose which end of the
    spacing path is distance zero, and which end of the curve receives the
    first inserted node. Choosing the curve's last node reverses that curve,
    so its old last node becomes the first node.
    """
    first_document = normalized_path(first_path, first_transform)
    second_document = normalized_path(second_path, second_transform)
    first_measured = measure_path(first_document)
    second_measured = measure_path(second_document)
    curve_index = choose_curve_index(first_measured, second_measured)

    if curve_index == 0:
        source_measured = second_measured
        target_document = first_document
        target_local = normalized_path(first_path)
    else:
        source_measured = first_measured
        target_document = second_document
        target_local = normalized_path(second_path)

    if curve_index == 0:
        target_length = first_measured.total_length
    else:
        target_length = second_measured.total_length

    if measure_source_from_end:
        source_measured = flip_measurement(source_measured)

    # Reverse both copies together. Split times are computed on the
    # on-canvas curve and applied to the local curve, so they must start
    # at the same end.
    if add_nodes_from_end:
        target_document = target_document.reverse()
        target_local = target_local.reverse()

    distances, skipped_count = distances_to_place(
        source_measured,
        target_length,
        proportional,
    )
    _document_move, document_segment = _single_drawing_segment(target_document)
    move_proxy, local_segment = _single_drawing_segment(target_local)
    pieces = subdivide_at_distances(document_segment, local_segment, distances)
    rebuilt = rebuild_open_path(move_proxy, pieces)
    return TransferResult(
        path=rebuilt,
        curve_index=curve_index,
        placed_count=len(pieces) - 1,
        skipped_count=skipped_count,
    )
