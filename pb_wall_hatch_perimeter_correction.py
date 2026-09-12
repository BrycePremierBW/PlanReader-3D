"""Generic, fail-closed perimeter correction using hatch-run evidence.

Answers a narrow, bounded question: given a floor plan's already-resolved
envelope dimensions (``length_m``/``width_m``, however production already
derived them) and the page's own vector hatch geometry, is any portion of
the naive rectangular perimeter demonstrably NOT backed by a masonry hatch
run -- i.e. a genuinely open edge (a verandah front, an unenclosed bay)?

This module never invents the envelope itself. It only:
  1. auto-derives a wall-evidenced bounding rectangle from hatch clusters
     that independently corroborates (within tolerance) the already-known
     length_m/width_m -- if the two disagree, it abstains entirely;
  2. sweeps each of that rectangle's four sides in fixed sub-segments using
     the already-tested ``pb_wall_hatch_edge_diagnostic.classify_edge_hatch_
     evidence`` (committed, regression-tested separately);
  3. sums only the sub-segments confidently classified NO_HATCH_EVIDENCE,
     converts that pixel length to metres using the cross-validated local
     scale, and returns it as a length to subtract from the naive perimeter.

Nothing here references a benchmark, a project name, or an expected
quantity. A side with mixed/ambiguous/absent hatch evidence is left
untouched (never counted as open, never invented as solid) -- the naive
perimeter is only ever reduced when hatch evidence for open space is
directly and locally observed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from pb_hatch_detection_v160 import HatchCluster
from pb_wall_hatch_edge_diagnostic import classify_edge_hatch_evidence

_PLAN_TITLE_RE = re.compile(
    r"\b(?:ground\s+floor|floor|first\s+floor|site)\s+plan\b", re.IGNORECASE
)

# Absence of hatch evidence on a side is NOT, by itself, proof that side is
# open -- KSTVET's own north wall is confirmed solid (by direct elevation
# corroboration) yet carries no continuous hatch signature at all, because
# this drawing simply doesn't hatch that wall the same way. Treating hatch
# absence alone as "confirmed open" would silently promote an untested
# assumption to certainty on any drawing with a wall convention gap like
# that one. A side is only accepted as confirmed-open when the hatch-free
# reading is corroborated by an independent signal: a named open/semi-open
# space label (the same "verandah" convention already used elsewhere in
# this codebase, e.g. pb_secondary_area_support_evidence._zone_type)
# positioned on the outward side of that specific edge.
_OPEN_ZONE_LABEL_RE = re.compile(
    r"\b(?:verandah?|porch|carport|balcony|loggia|breezeway)\b", re.IGNORECASE
)

# How far outward (away from the envelope centre, beyond the edge itself) an
# open-zone label may sit and still count as corroborating that edge.
_OPEN_ZONE_LABEL_MAX_OUTWARD_PT = 150.0
# How far the label may sit sideways (along the edge) from the sub-segment
# under test and still count.
_OPEN_ZONE_LABEL_MAX_LATERAL_PT = 250.0


def _open_zone_label_bboxes(page: Any) -> List[Tuple[float, float, float, float]]:
    try:
        page_dict = page.get_text("dict")
    except Exception:
        return []
    boxes: List[Tuple[float, float, float, float]] = []
    for block in page_dict.get("blocks", []) or []:
        for line in block.get("lines", []) or []:
            text = "".join(s.get("text", "") for s in line.get("spans", []) or [])
            if _OPEN_ZONE_LABEL_RE.search(text):
                boxes.append(tuple(line["bbox"]))
    return boxes


def _edge_corroborated_by_open_zone_label(
    sx1: float,
    sy1: float,
    sx2: float,
    sy2: float,
    center: Tuple[float, float],
    labels: Sequence[Tuple[float, float, float, float]],
) -> bool:
    if not labels:
        return False
    mx, my = (sx1 + sx2) / 2.0, (sy1 + sy2) / 2.0
    cx, cy = center
    # Outward unit direction: away from the envelope centre, through this
    # sub-segment's own midpoint.
    dx, dy = mx - cx, my - cy
    norm = math.hypot(dx, dy)
    if norm == 0:
        return False
    dx, dy = dx / norm, dy / norm
    for x0, y0, x1, y1 in labels:
        lx, ly = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        outward = (lx - mx) * dx + (ly - my) * dy
        if outward < -10.0 or outward > _OPEN_ZONE_LABEL_MAX_OUTWARD_PT:
            continue
        lateral = math.hypot(lx - mx, ly - my) - abs(outward)
        if lateral <= _OPEN_ZONE_LABEL_MAX_LATERAL_PT:
            return True
    return False

# A floor-plan drawing conventionally has its title label directly BELOW the
# drawing itself, not the reverse -- a standard drafting layout convention,
# not specific to any one project. Used only to scope which hatch clusters
# belong to the plan view on a multi-view sheet (floor plan + elevations +
# sections sharing one PDF page); never used to derive a quantity.
_PLAN_LABEL_MARGIN_ABOVE_PT = 900.0
_PLAN_LABEL_MARGIN_SIDE_PT = 500.0


def _floor_plan_viewport_bbox(page: Any) -> Optional[Tuple[float, float, float, float]]:
    try:
        page_dict = page.get_text("dict")
    except Exception:
        return None
    for block in page_dict.get("blocks", []) or []:
        for line in block.get("lines", []) or []:
            text = "".join(s.get("text", "") for s in line.get("spans", []) or [])
            if _PLAN_TITLE_RE.search(text):
                x0, y0, x1, y1 = line["bbox"]
                cx = (x0 + x1) / 2.0
                return (
                    cx - _PLAN_LABEL_MARGIN_SIDE_PT,
                    y0 - _PLAN_LABEL_MARGIN_ABOVE_PT,
                    cx + _PLAN_LABEL_MARGIN_SIDE_PT,
                    y1,
                )
    return None

# A wall-like cluster must clear this confidence bar to help derive the
# evidenced envelope -- reuses the hatch detector's own confidence metric,
# no separately invented threshold logic.
_MIN_WALL_CLUSTER_CONFIDENCE = 0.5
_MIN_WALL_CLUSTER_STROKES = 15

# A genuine diagonal-tick masonry hatch run has real lateral extent from the
# ticks' own diagonal angle (each tick spans a few points in both axes) --
# unlike a single straight dimension/witness line, which the upstream
# detector can occasionally still classify as a low-variance "parallel
# hatch" cluster despite having zero width in one axis. Reject those.
_MIN_WALL_CLUSTER_BBOX_DIMENSION_PT = 3.0

# The two independent scale estimates (pixel-bbox-width vs length_m, and
# pixel-bbox-height vs width_m) must agree within this fraction before the
# auto-derived envelope is trusted as corroborating the known dimensions.
_MAX_SCALE_DISAGREEMENT_FRACTION = 0.12

# Each side is swept in equal sub-segments long enough to physically contain
# pb_hatch_detection_v160's own _MIN_HATCH_STROKES (5) even at a generously
# sparse hatch pitch -- chopping finer than this would make a genuinely
# solid wall read as "open" purely from stroke starvation in each slice, not
# from any real absence of evidence (a real failure mode caught while
# testing this against KSTVET's own confirmed-solid west/east walls).
_ASSUMED_MAX_HATCH_SPACING_PT = 25.0
_MIN_SUBSEGMENT_SPAN_PT = _ASSUMED_MAX_HATCH_SPACING_PT * 6


@dataclass(frozen=True)
class PerimeterCorrectionResult:
    status: str  # "corrected" | "abstained"
    reason: str
    open_length_m: float = 0.0
    evidenced_bbox: Optional[Tuple[float, float, float, float]] = None
    scale_pt_per_m: Optional[float] = None


def _cluster_center(c: HatchCluster) -> Tuple[float, float]:
    x0, y0, x1, y1 = c.bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


# A multi-view sheet (floor plan + elevations + sections all on one PDF page)
# can have hatch-confident clusters from unrelated views. Rather than assume
# a fixed viewport rectangle (which would only be valid for one drawing),
# group wall-like clusters by spatial proximity and keep only the largest
# connected group -- the plan's own walls cluster tightly together, while an
# elevation or section drawn elsewhere on the sheet forms its own separate,
# disconnected group. This is a density/connectivity heuristic, not a
# hand-picked region.
_CLUSTER_PROXIMITY_PT = 400.0


def _largest_spatially_connected_group(
    clusters: Sequence[HatchCluster],
) -> List[HatchCluster]:
    if len(clusters) <= 1:
        return list(clusters)

    centers = [_cluster_center(c) for c in clusters]
    n = len(clusters)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            dx = centers[i][0] - centers[j][0]
            dy = centers[i][1] - centers[j][1]
            if math.hypot(dx, dy) <= _CLUSTER_PROXIMITY_PT:
                union(i, j)

    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(clusters[i])

    return max(groups.values(), key=len)


def _wall_like_clusters(
    clusters: Sequence[HatchCluster],
    viewport_bbox: Optional[Tuple[float, float, float, float]],
) -> List[HatchCluster]:
    candidates = [
        c
        for c in clusters
        if not c.rejected
        and c.stroke_count >= _MIN_WALL_CLUSTER_STROKES
        and c.hatch_confidence >= _MIN_WALL_CLUSTER_CONFIDENCE
        and (c.bbox[2] - c.bbox[0]) >= _MIN_WALL_CLUSTER_BBOX_DIMENSION_PT
        and (c.bbox[3] - c.bbox[1]) >= _MIN_WALL_CLUSTER_BBOX_DIMENSION_PT
    ]
    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
        scoped = [
            c
            for c in candidates
            if vx0 <= _cluster_center(c)[0] <= vx1 and vy0 <= _cluster_center(c)[1] <= vy1
        ]
        if len(scoped) >= 2:
            return scoped
    # No plan-title label found, or too little survived scoping to it --
    # fall back to the largest spatially-connected group. Less precise on a
    # cluttered multi-view sheet, but still never references fixed coordinates.
    return _largest_spatially_connected_group(candidates)


def resolve_hatch_confirmed_open_length_m(
    clusters: Sequence[HatchCluster],
    *,
    length_m: float,
    width_m: float,
    page: Optional[Any] = None,
) -> PerimeterCorrectionResult:
    """Compute confirmed-open perimeter length from hatch evidence alone.

    ``clusters`` must be the ``all_clusters`` list from
    ``pb_hatch_detection_v160.detect_hatch_patterns`` for the relevant page.
    ``length_m``/``width_m`` are whatever production has already resolved
    for the envelope -- this function never re-derives or second-guesses
    them, only checks whether the hatch geometry corroborates them closely
    enough to trust a local pixel-to-metre scale.

    ``page`` (optional): the same fitz.Page the clusters came from. When
    given, used only to locate a "...FLOOR PLAN" title label and scope the
    search to the drawing above it -- a multi-view sheet (floor plan plus
    elevations/sections) can otherwise have hatch-confident clusters
    belonging to an unrelated view. Falls back to spatial-connectivity
    grouping when no such label is found.
    """
    viewport_bbox = _floor_plan_viewport_bbox(page) if page is not None else None
    wall_clusters = _wall_like_clusters(clusters, viewport_bbox)
    if len(wall_clusters) < 2:
        return PerimeterCorrectionResult(
            status="abstained",
            reason=f"only {len(wall_clusters)} wall-like hatch cluster(s) found, need >= 2",
        )

    min_x = min(c.bbox[0] for c in wall_clusters)
    min_y = min(c.bbox[1] for c in wall_clusters)
    max_x = max(c.bbox[2] for c in wall_clusters)
    max_y = max(c.bbox[3] for c in wall_clusters)
    bbox_w = max_x - min_x
    bbox_h = max_y - min_y
    if bbox_w <= 0 or bbox_h <= 0:
        return PerimeterCorrectionResult(
            status="abstained", reason="degenerate evidenced bounding box"
        )

    # Match the larger pixel span to the larger real dimension, and the
    # smaller to the smaller -- order-based, no axis metadata required.
    real_major, real_minor = sorted((length_m, width_m), reverse=True)
    pixel_major, pixel_minor = sorted((bbox_w, bbox_h), reverse=True)
    if real_major <= 0 or real_minor <= 0:
        return PerimeterCorrectionResult(status="abstained", reason="non-positive envelope dimension")

    scale_major = pixel_major / real_major
    scale_minor = pixel_minor / real_minor
    disagreement = abs(scale_major - scale_minor) / max(scale_major, scale_minor)
    if disagreement > _MAX_SCALE_DISAGREEMENT_FRACTION:
        return PerimeterCorrectionResult(
            status="abstained",
            reason=(
                f"hatch-evidenced bbox ({bbox_w:.1f}x{bbox_h:.1f}pt) does not "
                f"corroborate length_m/width_m ({length_m}/{width_m}) within "
                f"{_MAX_SCALE_DISAGREEMENT_FRACTION:.0%} (scales {scale_major:.2f} "
                f"vs {scale_minor:.2f} pt/m)"
            ),
        )

    scale_pt_per_m = (scale_major + scale_minor) / 2.0
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    open_zone_labels = _open_zone_label_bboxes(page) if page is not None else []

    sides = [
        (min_x, min_y, max_x, min_y),  # top
        (min_x, max_y, max_x, max_y),  # bottom
        (min_x, min_y, min_x, max_y),  # left
        (max_x, min_y, max_x, max_y),  # right
    ]

    total_open_pt = 0.0
    for x1, y1, x2, y2 in sides:
        side_span = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(side_span // _MIN_SUBSEGMENT_SPAN_PT))
        for i in range(n):
            t0 = i / n
            t1 = (i + 1) / n
            sx1 = x1 + (x2 - x1) * t0
            sy1 = y1 + (y2 - y1) * t0
            sx2 = x1 + (x2 - x1) * t1
            sy2 = y1 + (y2 - y1) * t1
            span = math.hypot(sx2 - sx1, sy2 - sy1)
            if span < _MIN_SUBSEGMENT_SPAN_PT:
                continue
            verdict = classify_edge_hatch_evidence(wall_clusters, sx1, sy1, sx2, sy2)
            if verdict.classification != "NO_HATCH_EVIDENCE":
                continue
            # Hatch absence alone is never enough -- require independent
            # corroboration from a named open/semi-open space label sitting
            # outward of this specific sub-segment before trusting it as a
            # real opening rather than just an undetected wall convention.
            if _edge_corroborated_by_open_zone_label(sx1, sy1, sx2, sy2, center, open_zone_labels):
                total_open_pt += span

    open_length_m = round(total_open_pt / scale_pt_per_m, 3)

    if open_length_m <= 0:
        return PerimeterCorrectionResult(
            status="abstained",
            reason="no sub-segment of any side was confirmed open",
            evidenced_bbox=(min_x, min_y, max_x, max_y),
            scale_pt_per_m=scale_pt_per_m,
        )

    return PerimeterCorrectionResult(
        status="corrected",
        reason=(
            f"{open_length_m}m of the naive perimeter is confirmed open by "
            "hatch evidence (zero qualifying strokes across contiguous "
            "sub-segments)"
        ),
        open_length_m=open_length_m,
        evidenced_bbox=(min_x, min_y, max_x, max_y),
        scale_pt_per_m=scale_pt_per_m,
    )
