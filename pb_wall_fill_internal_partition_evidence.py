"""Generic, fail-closed detection of internal partition walls drawn as solid
filled bands (a different convention than diagonal hatch ticks -- some
native-CAD drawings render wall thickness as a plain solid black fill
rather than hatching it).

Answers a narrow question: does this floor plan's own vector geometry show
a genuine internal partition wall (as opposed to furniture/desk outlines,
which are stroke-only in this drawing convention, or a symbol/annotation),
and if so, what is its real length?

This module never invents the building envelope or wall thickness. It
derives both from the drawing's own geometry:
  - wall thickness is the dominant (modal, low-variance) short-side width
    among solid near-black fills within the floor-plan viewport -- most
    walls on one drawing share a thickness, so this is a self-consistent,
    data-driven estimate, not a guessed constant;
  - the outer envelope is the combined bounding box of those same
    wall-like fills;
  - a wall-like fill is classified "perimeter" (already counted elsewhere)
    when it lies on/near that envelope's own boundary, and "internal
    partition" only when it sits strictly inside it.

Consumers are responsible for deciding whether an internal partition's
length is relevant to their specific quantity (e.g. damp-proof course
scoped explicitly to "all walls" by the drawing's own notes) -- this module
only reports evidenced internal wall segments and their lengths.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from pb_wall_hatch_perimeter_correction import _floor_plan_viewport_bbox

# length_m/width_m (caller-supplied, already resolved by production from
# real drawing evidence) ARE the physical scale authority here -- not one
# side of a cross-validation. Scale is computed directly as
# scale_pt_per_m = pixel_major / real_major (the wall-fill bbox's longer
# pixel span divided by the longer of the two known real dimensions).
#
# Only the longer axis is used for this division. The shorter axis is not
# required to agree, for a real, structural reason: a wall drawn as a
# solid fill on one side of a building can legitimately stop well short of
# an open/differently-constructed opposite side (e.g. a verandah whose
# outer edge has no continuous wall fill at all), so the fill bbox's
# shorter axis often will NOT span the full corresponding real dimension.
# Requiring both axes to agree would abstain on exactly the buildings
# worth investigating.
#
# There is no independent fill-derived real-world scale being
# cross-validated against length_m/width_m. The wall-fill thickness check
# below is a SEPARATE, subsequent plausibility/fail-closed check applied
# AFTER scale is already fixed from length_m/width_m -- it asks only
# "does this already-authoritative scale imply a physically realistic
# wall thickness for the fills found," never re-derives or second-guesses
# the scale itself.
_PLAUSIBLE_WALL_THICKNESS_RANGE_M = (0.08, 0.35)

# A wall-like fill must be nearly black (this drawing's own wall-fill
# convention, confirmed against both an exterior wall and the internal
# partition on the same page) and thin-and-long -- excludes furniture/desk
# symbols (stroke-only, no fill, in this drawing) and roughly-square
# symbols (grid bubbles, fixture marks).
_MAX_FILL_RGB_FOR_BLACK = 0.15
_MIN_ASPECT_RATIO = 6.0
_MIN_LONG_SIDE_PT = 30.0

# Wall-thickness candidates (the short side of each wall-like fill) must
# cluster within this relative tolerance of their own median to be trusted
# as one consistent wall-thickness scale for this drawing.
_MAX_THICKNESS_RELATIVE_SPREAD = 0.25

# A wall-like fill counts as "on the perimeter" (already represented in the
# naive envelope, not a new internal partition) when it comes within this
# many multiples of the derived wall thickness of the envelope's own
# bounding edge.
_PERIMETER_PROXIMITY_THICKNESS_MULTIPLE = 2.0


@dataclass(frozen=True)
class InternalPartitionEvidence:
    status: str  # "found" | "abstained"
    reason: str
    total_length_m: float = 0.0
    wall_thickness_m: Optional[float] = None
    scale_pt_per_m: Optional[float] = None
    segment_lengths_m: Tuple[float, ...] = ()


def _is_wall_like_fill(d: dict, page_rect: Optional[Any] = None) -> bool:
    fill = d.get("fill")
    if not fill or any(c > _MAX_FILL_RGB_FOR_BLACK for c in fill[:3]):
        return False
    x0, y0, x1, y1 = d["rect"]
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return False
    if page_rect is not None:
        # A page border/title-block frame line is also thin, long, and
        # often solid-filled -- but unlike any real wall, it spans nearly
        # the entire sheet. Exclude by comparing against the page's own
        # actual size, not a fixed length threshold.
        if w >= 0.9 * page_rect.width or h >= 0.9 * page_rect.height:
            return False
    short, long_ = min(w, h), max(w, h)
    if long_ < _MIN_LONG_SIDE_PT:
        return False
    if short <= 0 or long_ / short < _MIN_ASPECT_RATIO:
        return False
    return True


def resolve_internal_partition_length_m(
    drawings: Sequence[dict],
    *,
    length_m: float,
    width_m: float,
    page: Optional[Any] = None,
) -> InternalPartitionEvidence:
    """Find genuine internal partition walls from solid-fill wall geometry.

    ``drawings`` must be the raw ``page.get_drawings()`` list. ``length_m``/
    ``width_m`` are whatever production has already resolved for the
    envelope from real drawing evidence -- they ARE the physical scale
    authority (scale_pt_per_m = pixel_major / real_major, see module-level
    note), never merely a cross-check against some other fill-derived
    scale. They are also never used to select which fills are wall-like --
    that classification (fill colour, aspect ratio, page-relative size) is
    entirely independent of them. ``page`` (optional) scopes the search to
    the floor-plan viewport via a "...FLOOR PLAN" title label, the same
    mechanism used in pb_wall_hatch_perimeter_correction, to avoid picking
    up wall-like fills from an unrelated view on a multi-view sheet.
    """
    viewport_bbox = _floor_plan_viewport_bbox(page) if page is not None else None

    page_rect = getattr(page, "rect", None) if page is not None else None
    candidates = [d for d in drawings if _is_wall_like_fill(d, page_rect)]
    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
        scoped = []
        for d in candidates:
            x0, y0, x1, y1 = d["rect"]
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            if vx0 <= cx <= vx1 and vy0 <= cy <= vy1:
                scoped.append(d)
        if len(scoped) >= 2:
            candidates = scoped

    if len(candidates) < 2:
        return InternalPartitionEvidence(
            status="abstained",
            reason=f"only {len(candidates)} wall-like solid fill(s) found, need >= 2",
        )

    thicknesses = []
    for d in candidates:
        x0, y0, x1, y1 = d["rect"]
        thicknesses.append(min(x1 - x0, y1 - y0))
    median_thickness = statistics.median(thicknesses)
    consistent = [
        t for t in thicknesses
        if median_thickness > 0
        and abs(t - median_thickness) / median_thickness <= _MAX_THICKNESS_RELATIVE_SPREAD
    ]
    if len(consistent) < 2:
        return InternalPartitionEvidence(
            status="abstained",
            reason="wall-like fills do not share a consistent thickness scale",
        )
    wall_thickness_pt = statistics.median(consistent)

    min_x = min(d["rect"][0] for d in candidates)
    min_y = min(d["rect"][1] for d in candidates)
    max_x = max(d["rect"][2] for d in candidates)
    max_y = max(d["rect"][3] for d in candidates)
    bbox_w, bbox_h = max_x - min_x, max_y - min_y
    if bbox_w <= 0 or bbox_h <= 0:
        return InternalPartitionEvidence(status="abstained", reason="degenerate wall-fill bounding box")

    # length_m/width_m are the scale authority (see module-level note).
    # Scale is a direct division, not a cross-validation of two
    # independent estimates: the longer of the two real dimensions divides
    # the wall-fill bbox's longer pixel span (see module-level note for why
    # only the longer axis is used).
    real_major = max(length_m, width_m)
    pixel_major = max(bbox_w, bbox_h)
    if real_major <= 0:
        return InternalPartitionEvidence(status="abstained", reason="non-positive envelope dimension")
    scale_pt_per_m = pixel_major / real_major

    # Plausibility/fail-closed check only, applied AFTER scale is already
    # fixed from length_m/width_m above -- not a re-derivation of scale
    # and not a cross-validation against any independent fill-derived
    # scale (there isn't one). If this already-authoritative scale implies
    # an unrealistic wall thickness for the fills actually found, that is
    # reason to distrust the fill classification, not the scale itself.
    implied_thickness_m = wall_thickness_pt / scale_pt_per_m
    lo, hi = _PLAUSIBLE_WALL_THICKNESS_RANGE_M
    if not (lo <= implied_thickness_m <= hi):
        return InternalPartitionEvidence(
            status="abstained",
            reason=(
                f"derived scale ({scale_pt_per_m:.2f}pt/m from the longer envelope "
                f"axis) implies an unrealistic wall thickness ({implied_thickness_m:.3f}m, "
                f"outside {lo}-{hi}m) -- not trusted"
            ),
        )

    margin = wall_thickness_pt * _PERIMETER_PROXIMITY_THICKNESS_MULTIPLE

    internal_lengths_pt: List[float] = []
    for d in candidates:
        x0, y0, x1, y1 = d["rect"]
        w, h = x1 - x0, y1 - y0
        long_ = max(w, h)
        # Only the boundary proximity relevant to THIS fill's own axis
        # counts as "perimeter" evidence. A vertical internal partition
        # spans, by definition, from one perimeter wall to the opposite
        # one -- its own top/bottom endpoints will legitimately sit near
        # min_y/max_y without that making the partition itself part of the
        # horizontal perimeter. Only its left/right position (is it out
        # near the building's own left/right edge, or genuinely in the
        # middle?) is the relevant question for a vertical fill, and vice
        # versa for a horizontal one.
        if h >= w:  # vertical-ish fill: only left/right proximity matters
            on_perimeter = (x0 - min_x <= margin) or (max_x - x1 <= margin)
        else:  # horizontal-ish fill: only top/bottom proximity matters
            on_perimeter = (y0 - min_y <= margin) or (max_y - y1 <= margin)
        if on_perimeter:
            continue  # part of the already-counted outer perimeter
        internal_lengths_pt.append(long_)

    if not internal_lengths_pt:
        return InternalPartitionEvidence(
            status="abstained",
            reason="no wall-like fill sits strictly inside the derived envelope",
            wall_thickness_m=round(wall_thickness_pt / scale_pt_per_m, 4),
            scale_pt_per_m=scale_pt_per_m,
        )

    segment_lengths_m = tuple(round(length_pt / scale_pt_per_m, 3) for length_pt in internal_lengths_pt)
    return InternalPartitionEvidence(
        status="found",
        reason=(
            f"{len(segment_lengths_m)} internal partition segment(s) found, "
            f"total {sum(segment_lengths_m):.3f}m"
        ),
        wall_thickness_m=round(wall_thickness_pt / scale_pt_per_m, 4),
        scale_pt_per_m=scale_pt_per_m,
        total_length_m=round(sum(segment_lengths_m), 3),
        segment_lengths_m=segment_lengths_m,
    )
