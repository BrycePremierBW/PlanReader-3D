"""Recover axis-aligned masonry wall-network evidence from a raster-backed plan.

The resolver is deliberately conservative.  It does not infer scale from an
assumed DPI, page size, benchmark quantity, or drawing title.  Callers must
supply independently resolved horizontal / vertical building spans and a
corroborated wall thickness.  The raster itself must then contain one unique
outer wall rectangle whose X and Y scales agree and whose four boundary edges
have inward parallel companions at the independently resolved wall thickness.

Only internal double-line wall runs connected into that accepted masonry
network are returned.  Isolated parallel rectangles such as benches, desks,
worktops and service units are therefore rejected even if their line spacing
happens to resemble a wall thickness.  Door-sized gaps may join collinear wall
fragments topologically, but the gaps are preserved in the evidence rather than
silently counted as masonry.

This module contains no BOQ mappings, expected quantities, project names or
benchmark identities.  Ambiguous geometry fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Optional, Sequence, Tuple

import cv2
import fitz
import numpy as np


@dataclass(frozen=True)
class RasterWallRun:
    orientation: str  # "horizontal" or "vertical"
    centerline_start_pt: Tuple[float, float]
    centerline_end_pt: Tuple[float, float]
    span_length_m: float
    solid_length_m: float
    opening_gaps_m: Tuple[float, ...]
    edge_separation_m: float
    boundary_connection_count: int
    junction_count: int


@dataclass(frozen=True)
class RasterWallNetworkEvidence:
    source_page: Optional[int]
    render_scale: float
    horizontal_px_per_m: float
    vertical_px_per_m: float
    px_per_m: float
    scale_relative_error: float
    wall_thickness_m: float
    outer_bbox_pt: Tuple[float, float, float, float]
    partition_runs: Tuple[RasterWallRun, ...]
    solid_partition_length_m: float
    spanned_partition_length_m: float
    authority: str = "raster_double_line_wall_network_with_documented_scale"


@dataclass
class _LineGroup:
    orientation: str
    coord: float
    intervals: list[tuple[float, float]]


@dataclass
class _BandRun:
    orientation: str
    coord: float
    edge_a: float
    edge_b: float
    intervals: list[tuple[float, float]]
    solid_intervals: list[tuple[float, float]]
    gaps: list[float]
    boundary_connections: int = 0
    junctions: int = 0

    @property
    def start(self) -> float:
        return self.intervals[0][0]

    @property
    def end(self) -> float:
        return self.intervals[-1][1]

    @property
    def span(self) -> float:
        return self.end - self.start

    @property
    def solid(self) -> float:
        return sum(b - a for a, b in self.solid_intervals)


@dataclass(frozen=True)
class _OuterCandidate:
    left: float
    top: float
    right: float
    bottom: float
    scale_x: float
    scale_y: float
    scale_error: float
    score: float


def _merge_intervals(
    intervals: Iterable[tuple[float, float]], *, gap: float = 0.0
) -> list[tuple[float, float]]:
    ordered = sorted((float(a), float(b)) for a, b in intervals if b > a)
    if not ordered:
        return []
    merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def _interval_total(intervals: Sequence[tuple[float, float]]) -> float:
    return sum(max(0.0, b - a) for a, b in intervals)


def _clip_intervals(
    intervals: Sequence[tuple[float, float]], low: float, high: float
) -> list[tuple[float, float]]:
    return [
        (max(a, low), min(b, high))
        for a, b in intervals
        if min(b, high) > max(a, low)
    ]


def _intersect_intervals(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    a = _merge_intervals(left)
    b = _merge_intervals(right)
    out: list[tuple[float, float]] = []
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if end > start:
            out.append((start, end))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return _merge_intervals(out)


def _coverage(
    intervals: Sequence[tuple[float, float]], low: float, high: float
) -> float:
    if high <= low:
        return 0.0
    return _interval_total(_merge_intervals(_clip_intervals(intervals, low, high))) / (
        high - low
    )


def _render_binary(page: fitz.Page, render_scale: float) -> np.ndarray:
    pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
    array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n >= 3:
        gray = cv2.cvtColor(array[:, :, :3], cv2.COLOR_RGB2GRAY)
    else:
        gray = array[:, :, 0]
    # A fixed dark-ink threshold is intentional: architectural wall edges are
    # dark linework.  Anti-aliased light grey text/noise is excluded rather
    # than promoted into geometry.
    return cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY_INV)[1]


def _axis_line_groups(binary: np.ndarray) -> tuple[list[_LineGroup], list[_LineGroup]]:
    height, width = binary.shape[:2]
    edges = cv2.Canny(binary, 50, 150, apertureSize=3)
    short_side = float(min(height, width))
    min_line = max(28, int(round(short_side * 0.035)))
    threshold = max(35, int(round(short_side * 0.035)))
    max_gap = max(4, int(round(short_side * 0.004)))
    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=threshold,
        minLineLength=min_line,
        maxLineGap=max_gap,
    )
    if raw is None:
        return [], []

    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    for x1, y1, x2, y2 in raw[:, 0, :]:
        dx = float(x2 - x1)
        dy = float(y2 - y1)
        length = math.hypot(dx, dy)
        if length < min_line:
            continue
        axis_tol = max(2.0, length * 0.012)
        if abs(dy) <= axis_tol:
            horizontal.append(((float(y1) + float(y2)) / 2.0, min(x1, x2), max(x1, x2)))
        elif abs(dx) <= axis_tol:
            vertical.append(((float(x1) + float(x2)) / 2.0, min(y1, y2), max(y1, y2)))

    def cluster(rows: list[tuple[float, float, float]], orientation: str) -> list[_LineGroup]:
        if not rows:
            return []
        rows.sort(key=lambda row: row[0])
        clusters: list[list[tuple[float, float, float]]] = []
        coord_tolerance = max(2.0, short_side * 0.0018)
        for row in rows:
            if not clusters:
                clusters.append([row])
                continue
            centre = sum(item[0] for item in clusters[-1]) / len(clusters[-1])
            if abs(row[0] - centre) <= coord_tolerance:
                clusters[-1].append(row)
            else:
                clusters.append([row])
        groups: list[_LineGroup] = []
        for items in clusters:
            coord = float(np.median([item[0] for item in items]))
            intervals = _merge_intervals(
                [(float(item[1]), float(item[2])) for item in items],
                gap=max_gap,
            )
            if intervals:
                groups.append(_LineGroup(orientation=orientation, coord=coord, intervals=intervals))
        return groups

    return cluster(horizontal, "horizontal"), cluster(vertical, "vertical")


def _nearest_group(
    groups: Sequence[_LineGroup], target: float, tolerance: float
) -> Optional[_LineGroup]:
    matches = [group for group in groups if abs(group.coord - target) <= tolerance]
    if not matches:
        return None
    matches.sort(key=lambda group: abs(group.coord - target))
    if len(matches) > 1 and abs(matches[0].coord - target) == abs(matches[1].coord - target):
        return None
    return matches[0]


def _outer_candidates(
    horizontal: Sequence[_LineGroup],
    vertical: Sequence[_LineGroup],
    *,
    horizontal_span_m: float,
    vertical_span_m: float,
    wall_thickness_m: float,
) -> list[_OuterCandidate]:
    candidates: list[_OuterCandidate] = []
    for left_idx, left in enumerate(vertical):
        for right in vertical[left_idx + 1 :]:
            x_sep = right.coord - left.coord
            if x_sep <= 0:
                continue
            scale_x = x_sep / horizontal_span_m
            if not (8.0 <= scale_x <= 500.0):
                continue
            expected_t_x = wall_thickness_m * scale_x
            companion_tol_x = max(2.5, expected_t_x * 0.35)
            left_inner = _nearest_group(vertical, left.coord + expected_t_x, companion_tol_x)
            right_inner = _nearest_group(vertical, right.coord - expected_t_x, companion_tol_x)
            if left_inner is None or right_inner is None:
                continue

            for top_idx, top in enumerate(horizontal):
                for bottom in horizontal[top_idx + 1 :]:
                    y_sep = bottom.coord - top.coord
                    if y_sep <= 0:
                        continue
                    scale_y = y_sep / vertical_span_m
                    scale_error = abs(scale_x - scale_y) / max(scale_x, scale_y)
                    if scale_error > 0.035:
                        continue
                    scale = (scale_x + scale_y) / 2.0
                    expected_t_y = wall_thickness_m * scale_y
                    companion_tol_y = max(2.5, expected_t_y * 0.35)
                    top_inner = _nearest_group(horizontal, top.coord + expected_t_y, companion_tol_y)
                    bottom_inner = _nearest_group(horizontal, bottom.coord - expected_t_y, companion_tol_y)
                    if top_inner is None or bottom_inner is None:
                        continue

                    x_low, x_high = left.coord, right.coord
                    y_low, y_high = top.coord, bottom.coord
                    boundary_coverages = (
                        _coverage(top.intervals, x_low, x_high),
                        _coverage(bottom.intervals, x_low, x_high),
                        _coverage(left.intervals, y_low, y_high),
                        _coverage(right.intervals, y_low, y_high),
                    )
                    companion_coverages = (
                        _coverage(top_inner.intervals, x_low, x_high),
                        _coverage(bottom_inner.intervals, x_low, x_high),
                        _coverage(left_inner.intervals, y_low, y_high),
                        _coverage(right_inner.intervals, y_low, y_high),
                    )
                    if min(boundary_coverages) < 0.35 or min(companion_coverages) < 0.25:
                        continue

                    # Require a plausible wall-band separation on all four
                    # sides, not merely nearby dimension or grid lines.
                    measured_thicknesses = (
                        left_inner.coord - left.coord,
                        right.coord - right_inner.coord,
                        top_inner.coord - top.coord,
                        bottom.coord - bottom_inner.coord,
                    )
                    if any(
                        abs(value - wall_thickness_m * scale) / (wall_thickness_m * scale) > 0.42
                        for value in measured_thicknesses
                    ):
                        continue

                    score = (
                        sum(boundary_coverages)
                        + 0.7 * sum(companion_coverages)
                        - 5.0 * scale_error
                    )
                    candidates.append(
                        _OuterCandidate(
                            left=left.coord,
                            top=top.coord,
                            right=right.coord,
                            bottom=bottom.coord,
                            scale_x=scale_x,
                            scale_y=scale_y,
                            scale_error=scale_error,
                            score=score,
                        )
                    )

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates


def _select_unique_outer(candidates: Sequence[_OuterCandidate]) -> Optional[_OuterCandidate]:
    if not candidates:
        return None
    best = candidates[0]
    # Geometrically equivalent candidates caused by Hough duplicate edges are
    # tolerated only inside a tiny coordinate band.  A genuinely different
    # second rectangle of comparable quality is ambiguous and fails closed.
    for other in candidates[1:]:
        same = (
            abs(best.left - other.left) <= 3.0
            and abs(best.right - other.right) <= 3.0
            and abs(best.top - other.top) <= 3.0
            and abs(best.bottom - other.bottom) <= 3.0
        )
        if same:
            continue
        if other.score >= best.score * 0.94:
            return None
        break
    return best


def _logical_intervals(
    solid: Sequence[tuple[float, float]], max_gap: float
) -> list[tuple[list[tuple[float, float]], list[float]]]:
    solid = _merge_intervals(solid)
    if not solid:
        return []
    runs: list[tuple[list[tuple[float, float]], list[float]]] = []
    current = [solid[0]]
    gaps: list[float] = []
    for interval in solid[1:]:
        gap = interval[0] - current[-1][1]
        if gap <= max_gap:
            gaps.append(gap)
            current.append(interval)
        else:
            runs.append((current, gaps))
            current = [interval]
            gaps = []
    runs.append((current, gaps))
    return runs


def _candidate_internal_bands(
    horizontal: Sequence[_LineGroup],
    vertical: Sequence[_LineGroup],
    outer: _OuterCandidate,
    *,
    wall_thickness_m: float,
    px_per_m: float,
) -> list[_BandRun]:
    expected_t = wall_thickness_m * px_per_m
    min_sep = expected_t * 0.58
    max_sep = expected_t * 1.45
    max_opening_gap = 1.55 * px_per_m
    min_solid = max(0.9 * px_per_m, expected_t * 4.0)
    inside_margin = expected_t * 1.5
    candidates: list[_BandRun] = []

    def bands_for(groups: Sequence[_LineGroup], orientation: str) -> None:
        for idx, a in enumerate(groups):
            if orientation == "vertical":
                if not (outer.left + inside_margin < a.coord < outer.right - inside_margin):
                    continue
                clip_low, clip_high = outer.top, outer.bottom
            else:
                if not (outer.top + inside_margin < a.coord < outer.bottom - inside_margin):
                    continue
                clip_low, clip_high = outer.left, outer.right

            for b in groups[idx + 1 :]:
                separation = b.coord - a.coord
                if separation < min_sep:
                    continue
                if separation > max_sep:
                    break
                solid = _intersect_intervals(
                    _clip_intervals(a.intervals, clip_low, clip_high),
                    _clip_intervals(b.intervals, clip_low, clip_high),
                )
                if _interval_total(solid) < min_solid:
                    continue
                for pieces, gaps in _logical_intervals(solid, max_opening_gap):
                    if _interval_total(pieces) < min_solid:
                        continue
                    candidates.append(
                        _BandRun(
                            orientation=orientation,
                            coord=(a.coord + b.coord) / 2.0,
                            edge_a=a.coord,
                            edge_b=b.coord,
                            intervals=[(pieces[0][0], pieces[-1][1])],
                            solid_intervals=list(pieces),
                            gaps=list(gaps),
                        )
                    )

    bands_for(vertical, "vertical")
    bands_for(horizontal, "horizontal")

    # Deduplicate multiple Hough edge combinations describing the same thick
    # wall band.  Prefer the separation closest to the documented thickness,
    # then the greater amount of corroborated solid edge overlap.
    candidates.sort(
        key=lambda run: (
            run.orientation,
            run.coord,
            abs((run.edge_b - run.edge_a) - expected_t),
            -run.solid,
        )
    )
    kept: list[_BandRun] = []
    centre_tol = max(3.0, expected_t * 0.38)
    for run in candidates:
        conflicts = [
            existing
            for existing in kept
            if existing.orientation == run.orientation
            and abs(existing.coord - run.coord) <= centre_tol
            and max(existing.start, run.start) < min(existing.end, run.end)
        ]
        if not conflicts:
            kept.append(run)
            continue
        best_existing = min(
            conflicts,
            key=lambda item: (
                abs((item.edge_b - item.edge_a) - expected_t),
                -item.solid,
            ),
        )
        current_key = (abs((run.edge_b - run.edge_a) - expected_t), -run.solid)
        existing_key = (
            abs((best_existing.edge_b - best_existing.edge_a) - expected_t),
            -best_existing.solid,
        )
        if current_key < existing_key:
            kept.remove(best_existing)
            kept.append(run)
    return kept


def _network_filter(
    runs: Sequence[_BandRun], outer: _OuterCandidate, *, px_per_m: float, wall_thickness_m: float
) -> list[_BandRun]:
    if not runs:
        return []
    tolerance = max(5.0, wall_thickness_m * px_per_m * 1.8)

    def boundary_connections(run: _BandRun) -> int:
        if run.orientation == "vertical":
            return int(abs(run.start - outer.top) <= tolerance) + int(
                abs(run.end - outer.bottom) <= tolerance
            )
        return int(abs(run.start - outer.left) <= tolerance) + int(
            abs(run.end - outer.right) <= tolerance
        )

    for run in runs:
        run.boundary_connections = boundary_connections(run)

    accepted: list[_BandRun] = [run for run in runs if run.boundary_connections > 0]
    pending = [run for run in runs if run.boundary_connections == 0]

    def intersects(a: _BandRun, b: _BandRun) -> bool:
        if a.orientation == b.orientation:
            return False
        vertical = a if a.orientation == "vertical" else b
        horizontal = b if a.orientation == "vertical" else a
        return (
            vertical.start - tolerance <= horizontal.coord <= vertical.end + tolerance
            and horizontal.start - tolerance <= vertical.coord <= horizontal.end + tolerance
        )

    changed = True
    while changed and pending:
        changed = False
        for run in list(pending):
            junctions = sum(1 for other in accepted if intersects(run, other))
            if junctions:
                run.junctions = junctions
                accepted.append(run)
                pending.remove(run)
                changed = True

    # Update junction counts for the complete accepted graph.
    for run in accepted:
        run.junctions = sum(1 for other in accepted if other is not run and intersects(run, other))

    # A line that reaches only one boundary but has no masonry junction can be
    # a counter, screen or other fixture touching an external wall.  Require
    # either two boundary connections or at least one orthogonal network
    # junction for final acceptance.
    final = [
        run
        for run in accepted
        if run.boundary_connections >= 2 or run.junctions >= 1
    ]
    return final


def resolve_raster_wall_network(
    page: fitz.Page,
    *,
    horizontal_span_m: float,
    vertical_span_m: float,
    wall_thickness_m: float,
    source_page: Optional[int] = None,
    render_scale: float = 3.0,
) -> Optional[RasterWallNetworkEvidence]:
    """Resolve a unique, scale-authoritative internal masonry wall network.

    ``horizontal_span_m`` and ``vertical_span_m`` must come from independent
    drawing evidence (for example F.30's orthogonal figured dimensions), while
    ``wall_thickness_m`` must be independently corroborated.  The function
    never invents either value from pixels.
    """
    try:
        h_span = float(horizontal_span_m)
        v_span = float(vertical_span_m)
        thickness = float(wall_thickness_m)
        scale = float(render_scale)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (h_span, v_span, thickness, scale)):
        return None
    if h_span <= 0 or v_span <= 0 or not (0.05 <= thickness <= 0.6) or not (1.5 <= scale <= 6.0):
        return None

    try:
        binary = _render_binary(page, scale)
    except Exception:
        return None
    horizontal, vertical = _axis_line_groups(binary)
    if len(horizontal) < 4 or len(vertical) < 4:
        return None

    outer = _select_unique_outer(
        _outer_candidates(
            horizontal,
            vertical,
            horizontal_span_m=h_span,
            vertical_span_m=v_span,
            wall_thickness_m=thickness,
        )
    )
    if outer is None:
        return None

    px_per_m = (outer.scale_x + outer.scale_y) / 2.0
    internal = _candidate_internal_bands(
        horizontal,
        vertical,
        outer,
        wall_thickness_m=thickness,
        px_per_m=px_per_m,
    )
    accepted = _network_filter(
        internal,
        outer,
        px_per_m=px_per_m,
        wall_thickness_m=thickness,
    )
    if not accepted:
        return None

    accepted.sort(key=lambda run: (run.orientation, run.coord, run.start, run.end))
    public_runs: list[RasterWallRun] = []
    for run in accepted:
        if run.orientation == "vertical":
            start_px = (run.coord, run.start)
            end_px = (run.coord, run.end)
        else:
            start_px = (run.start, run.coord)
            end_px = (run.end, run.coord)
        public_runs.append(
            RasterWallRun(
                orientation=run.orientation,
                centerline_start_pt=(round(start_px[0] / scale, 3), round(start_px[1] / scale, 3)),
                centerline_end_pt=(round(end_px[0] / scale, 3), round(end_px[1] / scale, 3)),
                span_length_m=round(run.span / px_per_m, 4),
                solid_length_m=round(run.solid / px_per_m, 4),
                opening_gaps_m=tuple(round(gap / px_per_m, 4) for gap in run.gaps if gap > 0),
                edge_separation_m=round((run.edge_b - run.edge_a) / px_per_m, 4),
                boundary_connection_count=run.boundary_connections,
                junction_count=run.junctions,
            )
        )

    return RasterWallNetworkEvidence(
        source_page=source_page,
        render_scale=scale,
        horizontal_px_per_m=round(outer.scale_x, 5),
        vertical_px_per_m=round(outer.scale_y, 5),
        px_per_m=round(px_per_m, 5),
        scale_relative_error=round(outer.scale_error, 6),
        wall_thickness_m=round(thickness, 4),
        outer_bbox_pt=(
            round(outer.left / scale, 3),
            round(outer.top / scale, 3),
            round(outer.right / scale, 3),
            round(outer.bottom / scale, 3),
        ),
        partition_runs=tuple(public_runs),
        solid_partition_length_m=round(sum(run.solid_length_m for run in public_runs), 4),
        spanned_partition_length_m=round(sum(run.span_length_m for run in public_runs), 4),
    )
