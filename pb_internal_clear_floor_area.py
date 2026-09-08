"""pb_internal_clear_floor_area.py — Internal Clear Floor-Finish Area from
Corroborated Wall Thickness (Phase F.21).

When a rectangular outer building envelope (length x width) is evidenced
and a wall thickness is independently corroborated (F.15,
pb_dimension_chain_evidence_extractor.resolve_corroborated_wall_thickness_m),
the internal clear rectangular floor-finish footprint is a plain
geometric consequence, not a separate measurement:

    clear_length = outer_length - 2 * thickness
    clear_width  = outer_width  - 2 * thickness
    clear_area   = clear_length * clear_width

A floor finish (screed, tiling, skirting extent) is laid to the internal
face of the walls, not to the outer envelope used for the structural
slab/DPM/mesh beneath it -- those remain on the outer/gross footprint
basis, since a slab does not stop short at the wall thickness the way a
finish does.

This module only performs that conversion and never invents a thickness,
envelope, or fallback value of its own: any missing, non-finite, or
non-positive input, or a wall thickness large enough to make either
clear dimension non-positive, resolves to UNRESOLVED rather than a
guessed, clamped, or zero/negative area.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClearFloorAreaResult:
    status: str = "unresolved"  # "resolved" | "unresolved"
    internal_clear_length_m: Optional[float] = None
    internal_clear_width_m: Optional[float] = None
    internal_clear_area_m2: Optional[float] = None
    notes: str = ""


def derive_internal_clear_floor_area(
    outer_length_m: Optional[float],
    outer_width_m: Optional[float],
    wall_thickness_m: Optional[float],
) -> ClearFloorAreaResult:
    """Convert an evidenced rectangular outer envelope to an internal
    clear floor-finish area using a corroborated wall thickness applied
    to all four sides. Fails closed to UNRESOLVED whenever any input is
    missing/non-finite/non-positive, or the resulting clear dimensions
    would not both be strictly positive -- never guesses or clamps."""
    if outer_length_m is None or outer_width_m is None or wall_thickness_m is None:
        return ClearFloorAreaResult(
            status="unresolved",
            notes="missing outer envelope dimension(s) or wall thickness evidence",
        )

    if not (
        math.isfinite(outer_length_m)
        and math.isfinite(outer_width_m)
        and math.isfinite(wall_thickness_m)
    ):
        return ClearFloorAreaResult(status="unresolved", notes="non-finite input")

    if outer_length_m <= 0 or outer_width_m <= 0 or wall_thickness_m <= 0:
        return ClearFloorAreaResult(status="unresolved", notes="non-positive input")

    clear_length_m = outer_length_m - 2.0 * wall_thickness_m
    clear_width_m = outer_width_m - 2.0 * wall_thickness_m

    if clear_length_m <= 0 or clear_width_m <= 0:
        return ClearFloorAreaResult(
            status="unresolved",
            notes=(
                "wall thickness too large relative to the evidenced envelope -- "
                "resulting clear dimension(s) would be non-positive"
            ),
        )

    return ClearFloorAreaResult(
        status="resolved",
        internal_clear_length_m=round(clear_length_m, 4),
        internal_clear_width_m=round(clear_width_m, 4),
        internal_clear_area_m2=round(clear_length_m * clear_width_m, 4),
    )
