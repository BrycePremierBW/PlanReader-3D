"""Generic, fail-closed measurement of a gable roof's pitch and topology
from an elevation drawing's own vector roofline geometry.

This module never assumes a pitch value -- not a BOQ specification's
regulatory upper bound (e.g. "not exceeding 30 degrees from horizontal" is
a workmanship ceiling, not a measured as-drawn angle), not a "typical"
default, and never treats a single level datum (e.g. a "+3000 ROOF LEVEL"
annotation) as if it were the ridge height above the wall-plate. Level
annotations mark whatever the drawing's author chose to dimension (often
the wall-plate/eave, not the ridge) and are not read by this module at all.

Pitch is measured directly from the two roof-slope line segments that meet
at the ridge apex in a genuine gable-end elevation view. Each slope's
horizontal run is measured out to the nearest genuine wall-corner vertical
whose own top point actually lies on that slope's line -- never to an
assumed or dimensioned building width, and never to the slope's own
outermost drawn point (which may include an undimensioned eaves overhang
this module deliberately does not try to quantify).

Fails closed (returns None) unless, across the whole document, there is
exactly one "ELEVATION"-titled viewport containing exactly one unambiguous
apex whose two sides independently measure the same pitch and each
terminate at a real wall-corner vertical.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_ELEVATION_TITLE_RE = re.compile(r"\bELEVATION\b", re.I)

# A genuine roofline segment is long enough to not be a dimension tick
# (~10-25pt), an arrowhead (~5-15pt), or a hatch stroke -- all of which are
# far shorter than any real roof slope drawn at an architectural scale.
_MIN_ROOFLINE_LENGTH_PT = 40.0

# Two diagonal segments belong to the same ridge apex when their own high
# (smallest-y) endpoints sit within this distance of each other -- large
# enough to absorb a double-line (roof-thickness) rendering, small enough
# to reject unrelated geometry.
_MAX_APEX_ENDPOINT_GAP_PT = 6.0

# All segments contributing to one side of the roof (there may be more
# than one per side, e.g. a short "to wall corner" stub plus a longer
# continuation "to outer eave") must agree with each other, and the two
# sides must agree with each other, on the implied pitch within this many
# degrees -- otherwise this is not one consistent roof plane.
_MAX_PITCH_DISAGREEMENT_DEG = 2.0

# Pitches outside this range are not a plausible pitched-roof gable end --
# too shallow to distinguish from a flat parapet/fascia box (long-side
# elevations render one of those, not a peak), or too steep to be a roof.
_MIN_PLAUSIBLE_PITCH_DEG = 3.0
_MAX_PLAUSIBLE_PITCH_DEG = 60.0

# A wall-corner vertical must be tall enough to plausibly be a real wall
# (not a window mullion stub or a dimension witness tick).
_MIN_WALLCORNER_VERTICAL_LENGTH_PT = 20.0

# How close a candidate wall-corner vertical's own top point must fall to
# the ray projected from the apex at the measured pitch.
_MAX_WALLCORNER_RAY_GAP_PT = 10.0

# A "run" (apex to wall corner) this short is not a credible wall corner --
# it would place the wall directly under the ridge.
_MIN_RUN_PT = 15.0

# Region searched for roofline/wall-corner geometry: a generous box above
# each "ELEVATION" title, wide enough for a full building elevation.
_VIEWPORT_MARGIN_ABOVE_PT = 500.0
_VIEWPORT_MARGIN_SIDE_PT = 400.0


@dataclass(frozen=True)
class _DiagSegment:
    x_hi: float
    y_hi: float
    x_lo: float
    y_lo: float
    length: float

    @property
    def direction(self) -> int:
        if self.x_lo > self.x_hi:
            return 1
        if self.x_lo < self.x_hi:
            return -1
        return 0

    @property
    def pitch_deg(self) -> float:
        dx = abs(self.x_lo - self.x_hi)
        dy = abs(self.y_lo - self.y_hi)
        if dx <= 0:
            return 90.0
        return math.degrees(math.atan(dy / dx))


@dataclass(frozen=True)
class _VertSegment:
    x: float
    top_y: float
    bottom_y: float
    length: float


@dataclass(frozen=True)
class GableRoofPitchEvidence:
    pitch_deg: float
    run_a_pt: float
    run_b_pt: float
    apex_xy: Tuple[float, float]
    source_page: int
    reason: str


def _cluster_apex_candidates(
    diagonals: Sequence[_DiagSegment],
) -> List[Tuple[Tuple[float, float], List[_DiagSegment]]]:
    """Group diagonal segments by shared high (apex) endpoints.

    Returns one (apex_point, member_segments) entry per cluster that
    contains at least one left-going and one right-going member -- the
    signature of a real ridge, not a single lone slope.
    """
    unclustered = list(diagonals)
    clusters: List[Tuple[Tuple[float, float], List[_DiagSegment]]] = []
    while unclustered:
        seed = unclustered.pop(0)
        members = [seed]
        i = 0
        while i < len(unclustered):
            seg = unclustered[i]
            if any(
                math.hypot(seg.x_hi - m.x_hi, seg.y_hi - m.y_hi) <= _MAX_APEX_ENDPOINT_GAP_PT
                for m in members
            ):
                members.append(seg)
                unclustered.pop(i)
                continue
            i += 1
        directions = {m.direction for m in members}
        if 1 in directions and -1 in directions:
            avg_x = sum(m.x_hi for m in members) / len(members)
            avg_y = sum(m.y_hi for m in members) / len(members)
            clusters.append(((avg_x, avg_y), members))
    return clusters


def _resolve_side_run(
    apex: Tuple[float, float],
    pitch_deg: float,
    direction: int,
    verticals: Sequence[_VertSegment],
) -> Optional[float]:
    """Find the farthest wall-corner vertical on one side of the apex whose
    top point lies on the ray cast from the apex at ``pitch_deg`` in
    ``direction`` (-1 = left, +1 = right). Returns the horizontal run in
    points, or None if no qualifying vertical is found.

    The farthest (not nearest) qualifying match is used deliberately: on a
    roof plane extended over a secondary space (e.g. a verandah), the
    nearer wall's own corner sits, by simple trigonometry, exactly on the
    same single-pitch ray as the farther verandah post -- both are real
    points on one continuous slope. Picking the nearest match would silently
    collapse an extended roof plane down to its shorter, un-extended run.
    The farthest match is still never the roofline's own outermost drawn
    point (the eaves tip) unless a real vertical structural element -- a
    wall or post -- actually stands there, so this does not smuggle in an
    undimensioned eaves overhang."""
    ax, ay = apex
    pitch_rad = math.radians(pitch_deg)
    best_run: Optional[float] = None
    for v in verticals:
        if v.length < _MIN_WALLCORNER_VERTICAL_LENGTH_PT:
            continue
        run = (v.x - ax) * direction
        if run < _MIN_RUN_PT:
            continue
        expected_y = ay + run * math.tan(pitch_rad)
        if abs(v.top_y - expected_y) > _MAX_WALLCORNER_RAY_GAP_PT:
            continue
        if best_run is None or run > best_run:
            best_run = run
    return best_run


def _resolve_gable_pitch_in_viewport(
    diagonals: Sequence[_DiagSegment],
    verticals: Sequence[_VertSegment],
    *,
    source_page: int,
) -> Optional[GableRoofPitchEvidence]:
    apex_clusters = _cluster_apex_candidates(
        [d for d in diagonals if d.length >= _MIN_ROOFLINE_LENGTH_PT]
    )
    if len(apex_clusters) != 1:
        return None
    apex, members = apex_clusters[0]

    pitches = [m.pitch_deg for m in members]
    mean_pitch = sum(pitches) / len(pitches)
    if any(abs(p - mean_pitch) > _MAX_PITCH_DISAGREEMENT_DEG for p in pitches):
        return None
    if not (_MIN_PLAUSIBLE_PITCH_DEG <= mean_pitch <= _MAX_PLAUSIBLE_PITCH_DEG):
        return None

    verts = [v for v in verticals if v.length >= _MIN_WALLCORNER_VERTICAL_LENGTH_PT]
    run_left = _resolve_side_run(apex, mean_pitch, -1, verts)
    run_right = _resolve_side_run(apex, mean_pitch, 1, verts)
    if run_left is None or run_right is None:
        return None

    return GableRoofPitchEvidence(
        pitch_deg=round(mean_pitch, 3),
        run_a_pt=round(run_left, 2),
        run_b_pt=round(run_right, 2),
        apex_xy=(round(apex[0], 2), round(apex[1], 2)),
        source_page=source_page,
        reason=(
            f"single unambiguous ridge apex with {len(members)} agreeing roofline "
            f"segment(s) (pitch {mean_pitch:.2f} deg), both sides terminate at a "
            f"real wall-corner vertical"
        ),
    )


def _diagonal_and_vertical_segments(
    page, viewport: Tuple[float, float, float, float]
) -> Tuple[List[_DiagSegment], List[_VertSegment]]:
    vx0, vy0, vx1, vy1 = viewport
    diag: List[_DiagSegment] = []
    vert: List[_VertSegment] = []
    try:
        drawings = page.get_drawings() or []
    except Exception:
        return diag, vert
    for d in drawings:
        for item in d.get("items") or []:
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            try:
                x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            except Exception:
                continue
            if not (
                vx0 <= x0 <= vx1
                and vy0 <= y0 <= vy1
                and vx0 <= x1 <= vx1
                and vy0 <= y1 <= vy1
            ):
                continue
            length = math.hypot(x1 - x0, y1 - y0)
            if abs(x1 - x0) < 0.5 and abs(y1 - y0) >= 0.5:
                vert.append(_VertSegment(x=x0, top_y=min(y0, y1), bottom_y=max(y0, y1), length=length))
            elif abs(y1 - y0) >= 0.5 and abs(x1 - x0) >= 0.5:
                if y0 <= y1:
                    diag.append(_DiagSegment(x_hi=x0, y_hi=y0, x_lo=x1, y_lo=y1, length=length))
                else:
                    diag.append(_DiagSegment(x_hi=x1, y_hi=y1, x_lo=x0, y_lo=y0, length=length))
    return diag, vert


def _elevation_viewports(page) -> List[Tuple[float, float, float, float]]:
    """Bounding boxes of the region above each 'ELEVATION' title on this
    page -- the same title-anchored-viewport convention already used for
    '...FLOOR PLAN' elsewhere in this codebase."""
    viewports: List[Tuple[float, float, float, float]] = []
    try:
        d = page.get_text("dict")
    except Exception:
        return viewports
    page_rect = getattr(page, "rect", None)
    page_x0 = page_rect.x0 if page_rect is not None else float("-inf")
    page_x1 = page_rect.x1 if page_rect is not None else float("inf")
    page_y0 = page_rect.y0 if page_rect is not None else float("-inf")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if not _ELEVATION_TITLE_RE.search(text):
                continue
            bx0, by0, bx1, _by1 = line["bbox"]
            cx = (bx0 + bx1) / 2.0
            vx0 = max(page_x0, cx - _VIEWPORT_MARGIN_SIDE_PT)
            vx1 = min(page_x1, cx + _VIEWPORT_MARGIN_SIDE_PT)
            vy1 = by0
            vy0 = max(page_y0, by0 - _VIEWPORT_MARGIN_ABOVE_PT)
            if vy0 < vy1 and vx0 < vx1:
                viewports.append((vx0, vy0, vx1, vy1))
    return viewports


def resolve_sole_gable_roof_pitch(doc) -> Optional[GableRoofPitchEvidence]:
    """Scan every page of ``doc`` for an 'ELEVATION'-titled viewport
    showing a genuine gable roofline, and return the evidence only if
    EXACTLY ONE such viewport, across the whole document, yields an
    unambiguous single-apex, matching-pitch, both-sides-wall-cornered
    result. Abstains (returns None) on zero or multiple candidates."""
    found: List[GableRoofPitchEvidence] = []
    for pno in range(len(doc)):
        page = doc[pno]
        for viewport in _elevation_viewports(page):
            diag, vert = _diagonal_and_vertical_segments(page, viewport)
            evidence = _resolve_gable_pitch_in_viewport(diag, vert, source_page=pno + 1)
            if evidence is not None:
                found.append(evidence)
    if len(found) != 1:
        return None
    return found[0]
