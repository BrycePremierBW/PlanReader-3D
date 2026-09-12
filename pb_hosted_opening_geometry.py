"""Generic, fail-closed detection of a wall-hosted opening (a window or
door void interrupting an otherwise continuous wall) from native PDF
vector geometry.

This module answers one narrow question: "does this stretch of drawn wall
show a genuine, jamb-bounded interruption, and what is its span?" It never
infers a W1/W2/D1 *identity*, never reads or binds to a schedule count or
callout text, and never assumes an opening height (plan geometry alone
cannot show height). ``width_m`` is only ever populated when the caller
supplies an already-established scale authority -- this module does not
derive scale from text, filenames, or project knowledge.

Two architecturally distinct wall-drawing conventions are supported
through one shared abstraction (a "wall band" = a near face and a far
face running parallel at a locally consistent perpendicular distance --
the wall thickness):

  - a wall drawn as two parallel STROKED lines (the classic double-line
    convention), where a jamb is a short stroke crossing between the two
    faces and a hosted opening is a place where BOTH faces stop
    simultaneously, resuming later at the same thickness;
  - a wall drawn as a sequence of solid-filled rectangles ("piers"), where
    each pier's own top/bottom (or left/right) edges serve as the two
    faces, and a hosted opening is the real gap between two consecutive
    piers.

A candidate span must show interruption evidence on BOTH the near and far
face simultaneously (never just one), must be flanked by genuine wall
material on both sides (never just the wall ending), and must be
materially wider than the local wall thickness. Subtype classification
(window_like / door_like / opening_unknown) is based only on what
additional vector content is found INSIDE the candidate span -- glazing/
frame stroke evidence for window_like, a jamb-anchored door swing (or a
straight leaf line) for door_like, neither for opening_unknown. Ambiguous
or conflicting evidence abstains rather than guessing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from pb_plan_door_swing_geometry import iter_quarter_circle_cubics

# A wall band's two faces must be within this perpendicular-distance range
# to be considered a plausible masonry/partition thickness at typical
# architectural drawing scales (roughly 40mm-500mm at scales seen so far).
_MIN_WALL_THICKNESS_PT = 1.5
_MAX_WALL_THICKNESS_PT = 40.0

# Two lines (or fill edges) at the same coordinate, within this tolerance,
# are treated as the same face (absorbs drafting/double-stroke noise).
_FACE_COORD_TOL_PT = 0.75

# Two candidate faces must agree on their perpendicular gap within this
# tolerance across the whole band to be one consistent wall thickness.
_THICKNESS_CONSISTENCY_TOL_PT = 1.0

# A gap must be at least this many multiples of the local wall thickness
# to count as a real opening rather than a coursing joint or drafting gap.
_MIN_GAP_TO_THICKNESS_RATIO = 1.5

# A gap this short in absolute terms is never a real hosted opening
# regardless of how it compares to a very thin wall.
_MIN_GAP_PT = 6.0

# How close a jamb-crossing stroke's own extent must come to the wall
# band's near/far faces to count as "crossing approximately the full
# wall thickness".
_JAMB_COVERAGE_TOL_PT = 1.5

# A short stroke inside the candidate span, within this extra margin of
# the near/far faces, counts as possible glazing/frame evidence.
_INTERNAL_EVIDENCE_FACE_MARGIN_PT = 2.0

# A door swing's own straight-line "radius" leg must land within this
# distance of a jamb x-position to count as anchored there.
_DOOR_SWING_JAMB_TOL_PT = 4.0

# A genuine wall face can legitimately have several real openings (a
# repeatedly-fenestrated classroom wall), so gap COUNT alone cannot
# distinguish it from a dash-simulated grid/reference line (drawn as many
# short solid segments, not a PDF dash array -- confirmed empty `dashes`
# metadata even on visibly dashed lines in these drawings, so that
# metadata cannot be relied on either). What differs is DENSITY: a
# dash-simulated line repeats its short segment/gap cycle far more often
# per unit length than real, meaningfully-spaced window openings ever do.
# Separately, two small, unrelated marks that happen to share the same
# perpendicular offset (e.g. two different doors' own leaf symbols) can
# align into one enormous spurious "gap" spanning nearly the whole run --
# a minimum coverage fraction rejects that (real wall material actually
# making up a reasonable share of its own run), set low enough to still
# accept a heavily-fenestrated real wall. Require a minimum overall run so
# two coincidentally-aligned short, unrelated lines never qualify at all.
_MAX_GAP_DENSITY_PER_100PT = 3.0
_MIN_BAND_COVERAGE_FRACTION = 0.25
_MIN_BAND_RUN_PT = 60.0


@dataclass(frozen=True)
class HostedOpeningSpan:
    page: int
    host_orientation_deg: float
    jamb_start: Tuple[float, float]
    jamb_end: Tuple[float, float]
    span_pt: float
    width_m: Optional[float]
    wall_thickness_pt: float
    subtype: Literal["window_like", "door_like", "opening_unknown"]
    evidence_flags: Tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class HostedOpeningEvidence:
    status: Literal["found", "abstained"]
    openings: Tuple[HostedOpeningSpan, ...]
    reason: str


@dataclass(frozen=True)
class _Interval:
    lo: float
    hi: float


def _merge_intervals(intervals: Sequence[_Interval]) -> List[_Interval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: iv.lo)
    merged = [ordered[0]]
    for iv in ordered[1:]:
        last = merged[-1]
        if iv.lo <= last.hi + 1e-6:
            merged[-1] = _Interval(last.lo, max(last.hi, iv.hi))
        else:
            merged.append(iv)
    return merged


def _is_credible_wall_face(covered: Sequence[_Interval], span_lo: float, span_hi: float) -> bool:
    """Reject rows whose gap density is consistent with a dash-simulated
    grid/reference line rather than a real, occasionally-interrupted wall
    face. See module constants for the reasoning -- confirmed necessary
    against a real KSTVET grid-centreline row during this module's own
    development, which was otherwise indistinguishable from a genuinely
    multi-window wall using gap count or coverage fraction alone."""
    span = span_hi - span_lo
    if span < _MIN_BAND_RUN_PT:
        return False
    merged = _merge_intervals(covered)
    clipped = [
        _Interval(max(iv.lo, span_lo), min(iv.hi, span_hi))
        for iv in merged
        if iv.hi > span_lo and iv.lo < span_hi
    ]
    covered_len = sum(iv.hi - iv.lo for iv in clipped)
    if covered_len / span < _MIN_BAND_COVERAGE_FRACTION:
        return False
    gaps = _gaps_between(merged, span_lo, span_hi)
    density = len(gaps) / span * 100.0
    return density <= _MAX_GAP_DENSITY_PER_100PT


def _gaps_between(intervals: Sequence[_Interval], lo: float, hi: float) -> List[_Interval]:
    """Internal gaps only -- never the space before the first or after the
    last covered interval (that would be the wall simply ending, not an
    interruption)."""
    merged = _merge_intervals(intervals)
    merged = [iv for iv in merged if iv.hi > lo and iv.lo < hi]
    if len(merged) < 2:
        return []
    gaps = []
    for a, b in zip(merged, merged[1:]):
        if b.lo > a.hi:
            gaps.append(_Interval(a.hi, b.lo))
    return gaps


@dataclass(frozen=True)
class _FaceEvidence:
    coord: float  # the shared y (horizontal band) or x (vertical band)
    covered: List[_Interval]  # covered ranges along the run axis
    jambs: List[float]  # positions along the run axis with a confirmed perpendicular crossing


def _horizontal_face_evidence(
    lines: Sequence[Tuple[float, float, float, float]],
    fills: Sequence[Tuple[float, float, float, float]],
) -> List[Tuple[float, List[_Interval]]]:
    """Group horizontal evidence by shared y-coordinate, returning
    [(y, covered_x_intervals), ...].

    Fill edges and stroked lines are deliberately NOT merged into the same
    row when they coincide: a wall drawn as solid piers is fully evidenced
    by the fills alone, and a short stroked line sitting at the same y is
    then almost always internal window content (a glazing/sill line drawn
    flush with the wall face), not a second, independent wall-face
    observation. Blending the two would silently bridge the very gaps
    between piers that this module exists to find -- confirmed as a real
    failure mode against the Lamu fixture during this module's own
    development, not a hypothetical."""
    fill_buckets: List[Tuple[float, List[_Interval]]] = []

    def _add_fill(y: float, x0: float, x1: float) -> None:
        for i, (by, _covered) in enumerate(fill_buckets):
            if abs(by - y) <= _FACE_COORD_TOL_PT:
                fill_buckets[i][1].append(_Interval(min(x0, x1), max(x0, x1)))
                return
        fill_buckets.append((y, [_Interval(min(x0, x1), max(x0, x1))]))

    for x0, y0, x1, y1 in fills:
        _add_fill(y0, x0, x1)
        _add_fill(y1, x0, x1)

    line_buckets: List[Tuple[float, List[_Interval]]] = []

    def _add_line(y: float, x0: float, x1: float) -> None:
        if any(abs(by - y) <= _FACE_COORD_TOL_PT for by, _ in fill_buckets):
            return
        for i, (by, _covered) in enumerate(line_buckets):
            if abs(by - y) <= _FACE_COORD_TOL_PT:
                line_buckets[i][1].append(_Interval(min(x0, x1), max(x0, x1)))
                return
        line_buckets.append((y, [_Interval(min(x0, x1), max(x0, x1))]))

    for x0, y0, x1, y1 in lines:
        if abs(y1 - y0) <= _FACE_COORD_TOL_PT and abs(x1 - x0) > 0.5:
            _add_line((y0 + y1) / 2.0, x0, x1)

    return fill_buckets + line_buckets


def _vertical_jamb_positions(
    lines: Sequence[Tuple[float, float, float, float]],
    near_y: float,
    far_y: float,
) -> List[float]:
    """x-positions of vertical strokes that cross approximately the full
    near..far span (candidate jambs).

    A single jamb is often drawn as two or more collinear sub-segments
    (e.g. a symbol's own outline broken at an internal vertex) rather than
    one continuous line -- confirmed against the real KSTVET window
    symbol during this module's own development, where neither half alone
    reached the full wall thickness. Segments at the same x are merged
    before checking full-thickness coverage."""
    lo, hi = min(near_y, far_y), max(near_y, far_y)
    by_x: List[Tuple[float, List[_Interval]]] = []
    for x0, y0, x1, y1 in lines:
        if abs(x1 - x0) > _FACE_COORD_TOL_PT:
            continue
        x = (x0 + x1) / 2.0
        seg = _Interval(min(y0, y1), max(y0, y1))
        for i, (bx, ivs) in enumerate(by_x):
            if abs(bx - x) <= _FACE_COORD_TOL_PT:
                ivs.append(seg)
                break
        else:
            by_x.append((x, [seg]))

    jambs = []
    for x, ivs in by_x:
        merged = _merge_intervals(ivs)
        if any(
            iv.lo <= lo + _JAMB_COVERAGE_TOL_PT and iv.hi >= hi - _JAMB_COVERAGE_TOL_PT
            for iv in merged
        ):
            jambs.append(x)
    return jambs


def _collect_axis_lines(
    page, viewport: Tuple[float, float, float, float]
) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]:
    """Return (horizontal_lines, vertical_lines) as (x0,y0,x1,y1) within
    viewport, from raw stroked 'l' path items only (fills handled
    separately)."""
    vx0, vy0, vx1, vy1 = viewport
    horiz: List[Tuple[float, float, float, float]] = []
    vert: List[Tuple[float, float, float, float]] = []
    try:
        drawings = page.get_drawings() or []
    except Exception:
        return horiz, vert
    for d in drawings:
        # A fill-only path (color is None) contributes no visible stroke --
        # its own boundary 'l' items are drawing-tool bookkeeping (e.g. a
        # white "mask" rectangle painted over a grid line behind a symbol),
        # not a real wall/jamb line. Confirmed as a real false-positive
        # source against the KSTVET fixture during this module's own
        # development: such a mask rectangle's edge silently bridged a
        # genuine gap between two wall-face line segments.
        if d.get("color") is None:
            continue
        for item in d.get("items") or []:
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            try:
                x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            except Exception:
                continue
            if not (vx0 <= x0 <= vx1 and vy0 <= y0 <= vy1 and vx0 <= x1 <= vx1 and vy0 <= y1 <= vy1):
                continue
            if abs(y1 - y0) <= 0.5 and abs(x1 - x0) > 0.5:
                horiz.append((x0, y0, x1, y1))
            elif abs(x1 - x0) <= 0.5 and abs(y1 - y0) > 0.5:
                vert.append((x0, y0, x1, y1))
    return horiz, vert


# A wall-like fill: near-black, thin-and-long (same heuristic family as
# pb_wall_fill_internal_partition_evidence, restated locally to keep this
# module independently testable without importing production wall-fill
# state).
_MAX_FILL_RGB_FOR_BLACK = 0.15
_MIN_FILL_ASPECT_RATIO = 3.0
_MIN_FILL_LONG_SIDE_PT = 4.0


def _collect_wall_like_fills(
    page, viewport: Tuple[float, float, float, float]
) -> List[Tuple[float, float, float, float]]:
    vx0, vy0, vx1, vy1 = viewport
    out: List[Tuple[float, float, float, float]] = []
    try:
        drawings = page.get_drawings() or []
    except Exception:
        return out
    for d in drawings:
        fill = d.get("fill")
        rect = d.get("rect")
        if not fill or rect is None:
            continue
        if any(c > _MAX_FILL_RGB_FOR_BLACK for c in fill[:3]):
            continue
        x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
        if not (vx0 <= x0 <= vx1 and vy0 <= y0 <= vy1 and vx0 <= x1 <= vx1 and vy0 <= y1 <= vy1):
            continue
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            continue
        short, long_ = min(w, h), max(w, h)
        if long_ < _MIN_FILL_LONG_SIDE_PT or short <= 0 or long_ / short < _MIN_FILL_ASPECT_RATIO:
            continue
        out.append((x0, y0, x1, y1))
    return out


def _horizontal_fill_faces(
    fills: Sequence[Tuple[float, float, float, float]]
) -> List[Tuple[float, float, float, float]]:
    """Only fills that are wall-band-like when read horizontally (wider
    than tall)."""
    return [f for f in fills if (f[2] - f[0]) >= (f[3] - f[1])]


def _vertical_fill_faces(
    fills: Sequence[Tuple[float, float, float, float]]
) -> List[Tuple[float, float, float, float]]:
    return [f for f in fills if (f[3] - f[1]) > (f[2] - f[0])]


def _has_internal_evidence(
    lines: Sequence[Tuple[float, float, float, float]],
    gap_lo: float,
    gap_hi: float,
    near: float,
    far: float,
) -> bool:
    """Any additional stroked line whose extent sits within the candidate
    span (not itself a jamb at the exact boundary) and roughly within the
    wall-thickness band -- glazing/frame/sill evidence."""
    lo, hi = min(near, far) - _INTERNAL_EVIDENCE_FACE_MARGIN_PT, max(near, far) + _INTERNAL_EVIDENCE_FACE_MARGIN_PT
    for x0, y0, x1, y1 in lines:
        seg_lo_run = min(x0, x1)
        seg_hi_run = max(x0, x1)
        seg_lo_perp = min(y0, y1)
        seg_hi_perp = max(y0, y1)
        if seg_lo_run < gap_lo - 0.5 or seg_hi_run > gap_hi + 0.5:
            continue
        if seg_hi_run - seg_lo_run < 1.0:
            continue
        if seg_lo_perp < lo or seg_hi_perp > hi:
            continue
        return True
    return False


def _door_swing_anchor(
    page,
    gap_lo: float,
    gap_hi: float,
    near: float,
    far: float,
    *,
    swapped: bool = False,
) -> bool:
    """A quarter-circle door-swing cubic whose own bbox starts at (or very
    near) one jamb of this candidate span, used purely as a comparator --
    never re-deriving or overriding pb_plan_door_swing_geometry's own
    counting/identity logic.

    ``swapped`` mirrors the x/y-swap trick ``resolve_hosted_opening_spans``
    uses to reuse this same horizontal-oriented resolver for vertical wall
    bands: the arc's real page coordinates are read as-is from ``page``
    (never swapped themselves), so they must be swapped here too before
    comparing against the already-swapped gap/near/far values, or a real
    door swing on a vertical wall would never match."""
    try:
        hits = iter_quarter_circle_cubics(page, page_num=0)
    except Exception:
        return False
    lo_perp, hi_perp = min(near, far), max(near, far)
    for hit in hits:
        hit_x, hit_y = (hit.y, hit.x) if swapped else (hit.x, hit.y)
        if not (gap_lo - _DOOR_SWING_JAMB_TOL_PT <= hit_x <= gap_hi + _DOOR_SWING_JAMB_TOL_PT):
            continue
        if not (lo_perp - hit.radius - _DOOR_SWING_JAMB_TOL_PT <= hit_y <= hi_perp + hit.radius + _DOOR_SWING_JAMB_TOL_PT):
            continue
        near_start = abs(hit_x - gap_lo) <= (hit.radius + _DOOR_SWING_JAMB_TOL_PT)
        near_end = abs(hit_x - gap_hi) <= (hit.radius + _DOOR_SWING_JAMB_TOL_PT)
        if near_start or near_end:
            return True
    return False


def _resolve_horizontal_openings(
    page,
    horiz_lines: Sequence[Tuple[float, float, float, float]],
    vert_lines: Sequence[Tuple[float, float, float, float]],
    fills: Sequence[Tuple[float, float, float, float]],
    *,
    source_page: int,
    scale_pt_per_m: Optional[float],
    swapped: bool = False,
) -> List[HostedOpeningSpan]:
    face_rows = _horizontal_face_evidence(horiz_lines, _horizontal_fill_faces(fills))
    results: List[HostedOpeningSpan] = []
    n = len(face_rows)
    for i in range(n):
        y_a, cov_a = face_rows[i]
        for j in range(i + 1, n):
            y_b, cov_b = face_rows[j]
            thickness = abs(y_b - y_a)
            if not (_MIN_WALL_THICKNESS_PT <= thickness <= _MAX_WALL_THICKNESS_PT):
                continue
            merged_a = _merge_intervals(cov_a)
            merged_b = _merge_intervals(cov_b)
            span_lo = max(min(iv.lo for iv in merged_a), min(iv.lo for iv in merged_b))
            span_hi = min(max(iv.hi for iv in merged_a), max(iv.hi for iv in merged_b))
            if span_hi <= span_lo:
                continue
            if not (
                _is_credible_wall_face(merged_a, span_lo, span_hi)
                and _is_credible_wall_face(merged_b, span_lo, span_hi)
            ):
                continue
            gaps_a = {round(g.lo, 1): g for g in _gaps_between(merged_a, span_lo, span_hi)}
            gaps_b = {round(g.lo, 1): g for g in _gaps_between(merged_b, span_lo, span_hi)}
            aligned_keys = set(gaps_a) & set(gaps_b)
            for key in aligned_keys:
                ga, gb = gaps_a[key], gaps_b[key]
                gap_lo = max(ga.lo, gb.lo)
                gap_hi = min(ga.hi, gb.hi)
                if gap_hi <= gap_lo:
                    continue
                gap_width = gap_hi - gap_lo
                if gap_width < _MIN_GAP_PT or gap_width < _MIN_GAP_TO_THICKNESS_RATIO * thickness:
                    continue
                jambs_start = _vertical_jamb_positions(vert_lines, y_a, y_b)
                # Fill-edge boundaries are themselves valid jambs (the
                # pier's own face) -- a fill-backed gap boundary always
                # qualifies; a line-only gap boundary requires an explicit
                # crossing stroke.
                boundary_confirmed_start = any(
                    abs(f[0] - gap_lo) <= _FACE_COORD_TOL_PT or abs(f[2] - gap_lo) <= _FACE_COORD_TOL_PT
                    for f in fills
                ) or any(abs(x - gap_lo) <= _JAMB_COVERAGE_TOL_PT for x in jambs_start)
                boundary_confirmed_end = any(
                    abs(f[0] - gap_hi) <= _FACE_COORD_TOL_PT or abs(f[2] - gap_hi) <= _FACE_COORD_TOL_PT
                    for f in fills
                ) or any(abs(x - gap_hi) <= _JAMB_COVERAGE_TOL_PT for x in jambs_start)
                if not (boundary_confirmed_start and boundary_confirmed_end):
                    continue

                width_m = round(gap_width / scale_pt_per_m, 4) if scale_pt_per_m else None
                evidence_flags: List[str] = ["host_wall_band", "aligned_two_face_gap", "jamb_boundaries_confirmed"]

                subtype: Literal["window_like", "door_like", "opening_unknown"] = "opening_unknown"
                if _door_swing_anchor(page, gap_lo, gap_hi, y_a, y_b, swapped=swapped):
                    subtype = "door_like"
                    evidence_flags.append("jamb_anchored_door_swing")
                elif _has_internal_evidence(horiz_lines, gap_lo, gap_hi, y_a, y_b):
                    subtype = "window_like"
                    evidence_flags.append("internal_frame_or_glazing_evidence")

                results.append(
                    HostedOpeningSpan(
                        page=source_page,
                        host_orientation_deg=0.0,
                        jamb_start=(round(gap_lo, 2), round((y_a + y_b) / 2.0, 2)),
                        jamb_end=(round(gap_hi, 2), round((y_a + y_b) / 2.0, 2)),
                        span_pt=round(gap_width, 2),
                        width_m=width_m,
                        wall_thickness_pt=round(thickness, 2),
                        subtype=subtype,
                        evidence_flags=tuple(evidence_flags),
                        reason=(
                            f"aligned gap on both wall faces ({gap_width:.2f}pt, "
                            f"{gap_width / thickness:.2f}x local thickness), jamb-confirmed "
                            f"both boundaries, classified {subtype}"
                        ),
                    )
                )
    return results


def resolve_hosted_opening_spans(
    page,
    *,
    viewport_bbox: Optional[Tuple[float, float, float, float]] = None,
    scale_authority: Optional[float] = None,
) -> HostedOpeningEvidence:
    """Detect wall-hosted opening spans on ``page`` from native vector
    geometry alone.

    ``scale_authority``, if given, is a pt-per-metre conversion factor
    already established by the caller from real drawing evidence (e.g. a
    figured dimension) -- never derived here from text, filenames, or
    project knowledge. When omitted, every returned span still carries a
    real ``span_pt`` but ``width_m`` is left ``None``.

    Both axis-aligned orientations (horizontal and vertical wall runs) are
    checked independently. A candidate whose gap is consistent with BOTH
    a horizontal and a vertical wall band interpretation at overlapping
    coordinates (i.e. it could belong to either of two crossing walls) is
    dropped rather than guessed at.
    """
    page_rect = getattr(page, "rect", None)
    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
    elif page_rect is not None:
        vx0, vy0, vx1, vy1 = page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1
    else:
        vx0, vy0, vx1, vy1 = float("-inf"), float("-inf"), float("inf"), float("inf")

    horiz_lines, vert_lines = _collect_axis_lines(page, (vx0, vy0, vx1, vy1))
    fills = _collect_wall_like_fills(page, (vx0, vy0, vx1, vy1))
    source_page = getattr(page, "number", 0) + 1 if hasattr(page, "number") else 0

    horizontal_hits = _resolve_horizontal_openings(
        page,
        horiz_lines,
        vert_lines,
        _horizontal_fill_faces(fills),
        source_page=source_page,
        scale_pt_per_m=scale_authority,
    )

    # Vertical orientation: reuse the same horizontal-oriented resolver by
    # swapping the x/y roles of every input, then swapping the results
    # back -- keeps one single, well-tested code path for both
    # orientations instead of a parallel, harder-to-keep-in-sync copy.
    swapped_horiz = [(y0, x0, y1, x1) for (x0, y0, x1, y1) in vert_lines]
    swapped_vert = [(y0, x0, y1, x1) for (x0, y0, x1, y1) in horiz_lines]
    swapped_fills = [(y0, x0, y1, x1) for (x0, y0, x1, y1) in _vertical_fill_faces(fills)]
    vertical_hits_swapped = _resolve_horizontal_openings(
        page,
        swapped_horiz,
        swapped_vert,
        swapped_fills,
        source_page=source_page,
        scale_pt_per_m=scale_authority,
        swapped=True,
    )
    vertical_hits = [
        HostedOpeningSpan(
            page=h.page,
            host_orientation_deg=90.0,
            jamb_start=(h.jamb_start[1], h.jamb_start[0]),
            jamb_end=(h.jamb_end[1], h.jamb_end[0]),
            span_pt=h.span_pt,
            width_m=h.width_m,
            wall_thickness_pt=h.wall_thickness_pt,
            subtype=h.subtype,
            evidence_flags=h.evidence_flags,
            reason=h.reason,
        )
        for h in vertical_hits_swapped
    ]

    all_hits = horizontal_hits + vertical_hits

    # Two-host-wall conflict: if a horizontal and a vertical candidate
    # overlap in real space (their jamb spans intersect), neither can be
    # trusted as belonging to a single, unambiguous host wall -- drop both.
    conflicted: set = set()
    for hi, h in enumerate(horizontal_hits):
        hx0, hx1 = h.jamb_start[0], h.jamb_end[0]
        hy0, hy1 = h.jamb_start[1] - h.wall_thickness_pt, h.jamb_start[1] + h.wall_thickness_pt
        for vi, v in enumerate(vertical_hits):
            vy0, vy1 = v.jamb_start[1], v.jamb_end[1]
            vx0_, vx1_ = v.jamb_start[0] - v.wall_thickness_pt, v.jamb_start[0] + v.wall_thickness_pt
            if hx0 <= vx1_ and vx0_ <= hx1 and vy0 <= hy1 and hy0 <= vy1:
                conflicted.add(("h", hi))
                conflicted.add(("v", vi))

    final: List[HostedOpeningSpan] = [
        h for hi, h in enumerate(horizontal_hits) if ("h", hi) not in conflicted
    ] + [v for vi, v in enumerate(vertical_hits) if ("v", vi) not in conflicted]

    if not final:
        return HostedOpeningEvidence(
            status="abstained",
            openings=(),
            reason="no jamb-bounded, both-face-confirmed wall interruption found in viewport",
        )
    return HostedOpeningEvidence(
        status="found",
        openings=tuple(final),
        reason=f"{len(final)} hosted opening span(s) found",
    )
