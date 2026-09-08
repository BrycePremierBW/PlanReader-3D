"""Generic floor-finish geometry derived strictly from drawing evidence.

This module intentionally knows nothing about benchmark projects, BOQs, or expected
quantities.  It converts an evidenced rectangular *outer* envelope to an internal
clear floor-finish footprint only when an independently resolved wall thickness is
available and physically valid.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional


@dataclass(frozen=True)
class InternalClearFloorAreaResult:
    """Traceable rectangular outer-to-clear geometry result."""

    outer_length_m: float
    outer_width_m: float
    wall_thickness_m: float
    clear_length_m: float
    clear_width_m: float
    outer_area_m2: float
    internal_clear_area_m2: float


def derive_internal_clear_rectangular_area(
    outer_length_m: float,
    outer_width_m: float,
    wall_thickness_m: Optional[float],
) -> Optional[InternalClearFloorAreaResult]:
    """Return internal clear floor area from an evidenced outer rectangle.

    For a rectangular envelope with wall thickness ``t`` on both opposing faces,
    the clear footprint is ``(L - 2t) * (W - 2t)``.  The function fails closed
    (returns ``None``) for missing/non-finite/non-positive evidence or when the
    thickness would consume either clear dimension.  No default thickness or
    minimum clear dimension is invented.
    """
    if wall_thickness_m is None:
        return None

    values = (outer_length_m, outer_width_m, wall_thickness_m)
    if any(not math.isfinite(v) or v <= 0.0 for v in values):
        return None

    clear_length_m = outer_length_m - 2.0 * wall_thickness_m
    clear_width_m = outer_width_m - 2.0 * wall_thickness_m
    if clear_length_m <= 0.0 or clear_width_m <= 0.0:
        return None

    return InternalClearFloorAreaResult(
        outer_length_m=round(outer_length_m, 4),
        outer_width_m=round(outer_width_m, 4),
        wall_thickness_m=round(wall_thickness_m, 4),
        clear_length_m=round(clear_length_m, 4),
        clear_width_m=round(clear_width_m, 4),
        outer_area_m2=round(outer_length_m * outer_width_m, 4),
        internal_clear_area_m2=round(clear_length_m * clear_width_m, 4),
    )
