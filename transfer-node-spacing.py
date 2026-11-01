#!/usr/bin/env python3
# coding=utf-8
# Copyright (C) 2026 soswow
# SPDX-License-Identifier: GPL-3.0-or-later
"""Inkscape entry point for transferring arc-length node spacing."""

import inkex

from debug_marks import add_debug_group
from node_spacing import PathSpacingError, transfer_node_spacing


class TransferNodeSpacing(inkex.EffectExtension):
    """Subdivide a two-node curve using node spacing from another path."""

    def add_arguments(self, pars):
        pars.add_argument(
            "--distance_mode",
            default="absolute",
            help=(
                "absolute keeps the same arc lengths from the start; "
                "proportional scales them onto the target length"
            ),
        )
        pars.add_argument(
            "--source_end",
            default="start",
            help="Which end of the spacing path is distance zero: start or end",
        )
        pars.add_argument(
            "--target_end",
            default="start",
            help="Which end of the curve receives the first node: start or end",
        )
        pars.add_argument("--tab", default="transfer")
        pars.add_argument(
            "--number_nodes",
            type=inkex.Boolean,
            default=False,
            help="Draw numbered dots at the nodes of both paths",
        )
        pars.add_argument(
            "--segment_lengths",
            type=inkex.Boolean,
            default=False,
            help="Label the arc length of each segment on both paths",
        )
        pars.add_argument(
            "--unit",
            default="mm",
            help="Unit for the segment length labels",
        )
        pars.add_argument(
            "--text_size",
            type=float,
            default=10.0,
            help="Debug text height in pixels",
        )
        pars.add_argument(
            "--text_alignment",
            default="horizontal",
            help="horizontal, along the curve, or along the curve minus 90 degrees",
        )
        pars.add_argument(
            "--text_offset",
            type=float,
            default=12.0,
            help="Distance of debug text from the curve, in pixels",
        )

    def effect(self):
        selected_elements = list(self.svg.selection)
        path_elements = [
            element
            for element in selected_elements
            if isinstance(element, inkex.PathElement)
        ]
        if len(selected_elements) != 2 or len(path_elements) != 2:
            raise inkex.AbortExtension(
                "Select exactly two paths. Rectangles, circles, and other "
                "shapes need Object > Object to Path first."
            )

        proportional = self.options.distance_mode == "proportional"
        measure_source_from_end = self.options.source_end == "end"
        add_nodes_from_end = self.options.target_end == "end"
        first_element = path_elements[0]
        second_element = path_elements[1]
        try:
            result = transfer_node_spacing(
                first_element.path,
                first_element.composed_transform(),
                second_element.path,
                second_element.composed_transform(),
                proportional=proportional,
                measure_source_from_end=measure_source_from_end,
                add_nodes_from_end=add_nodes_from_end,
            )
        except PathSpacingError as error:
            raise inkex.AbortExtension(str(error)) from error

        if result.curve_index == 0:
            curve_element = first_element
        else:
            curve_element = second_element

        if result.curve_index == 0:
            spacing_element = second_element
        else:
            spacing_element = first_element

        if result.placed_count:
            curve_element.path = result.path
            self._clear_cached_node_types(curve_element)
        elif result.skipped_count == 0:
            raise inkex.AbortExtension(
                "The spacing path has no node distances to copy."
            )

        length_factor = self.svg.unit_to_viewport(1, self.options.unit)
        # Label 1 is the end the distances are measured from. The spacing path
        # is not rewritten, so its labels have to be counted backwards when
        # that end is the last node. The curve is rewritten from the chosen
        # end, so its path order is already the label order.
        curve_numbered_from_end = add_nodes_from_end and not result.placed_count
        add_debug_group(
            self.svg,
            spacing_element,
            "Node spacing debug: spacing path",
            self.options.number_nodes,
            self.options.segment_lengths,
            self.options.unit,
            self.options.text_size,
            length_factor,
            self.options.text_alignment,
            self.options.text_offset,
            measure_source_from_end,
        )
        add_debug_group(
            self.svg,
            curve_element,
            "Node spacing debug: curve",
            self.options.number_nodes,
            self.options.segment_lengths,
            self.options.unit,
            self.options.text_size,
            length_factor,
            self.options.text_alignment,
            self.options.text_offset,
            curve_numbered_from_end,
        )

    def _clear_cached_node_types(self, element):
        # Inkscape caches node type letters next to the path data. They no
        # longer match after nodes are inserted, so drop the cache and let
        # Inkscape rebuild it.
        nodetypes_attribute = inkex.addNS("nodetypes", "sodipodi")
        if nodetypes_attribute in element.attrib:
            del element.attrib[nodetypes_attribute]


if __name__ == "__main__":
    TransferNodeSpacing().run()
