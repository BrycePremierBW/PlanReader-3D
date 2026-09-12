"""Bounded diagnostic: classify a candidate wall edge as hatch-confirmed or not.

This is a standalone prototype, NOT wired into any production quantity
computation. It answers a narrow question raised while investigating
wall-area overcounting on floor plans with open verandah edges (e.g. a
naive 4-sided perimeter formula that does not know one side is open):

    Given a candidate straight edge of the building envelope (e.g. one side
    of the outer rectangle used for the naive perimeter formula), does the
    drawing's own vector hatch geometry actually show a continuous solid
    wall run along that edge, or is there no hatch evidence there?

It deliberately reuses the existing, already-tested hatch-stroke clustering
in ``pb_hatch_detection_v160`` (angle grouping, spacing consistency,
false-positive rejection) rather than re-deriving hatch detection from
scratch -- that module already solves "is this a real hatch pattern",
this module only adds "does a real hatch pattern run along THIS edge".

Classification is evidence-only and benchmark-independent: it never
consults an expected/gold quantity, only the position of the edge under
test (supplied by the caller, e.g. from envelope-detection or from direct
drawing inspection) and the hatch clusters PyMuPDF's vector geometry
actually contains.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence

from pb_hatch_detection_v160 import _MIN_HATCH_STROKES, HatchCluster

EdgeClassification = Literal[
    "SOLID_WALL_HATCH_CONFIRMED",
    "NO_HATCH_EVIDENCE",
    "ABSTAIN",
]

# An edge needs a minimum span before "no cluster found" is treated as
# meaningful evidence of an open edge rather than just a trivially short
# probe where absence proves nothing.
_MIN_EDGE_SPAN_PT = 20.0

# Fraction of the edge's span that a candidate cluster's own span along the
# edge axis must cover before the edge counts as hatch-confirmed.
_MIN_COVERAGE_FRACTION = 0.55

# How far (in PDF points) a cluster is allowed to sit off the edge line
# before it no longer counts as evidence for that specific edge.
_MAX_PERPENDICULAR_OFFSET_PT = 12.0

# Minimum spacing regularity (1.0 = perfectly even gaps between consecutive
# near-edge strokes, lower = noisier) required to call an edge confirmed.
# A genuine drafted hatch pattern repeats at a fixed pitch by construction;
# incidental strokes swept in from an unrelated, spatially diffuse cluster
# (upstream clustering can chain unrelated marks together -- see the
# docstring below) land at irregular intervals instead. Calibrated against
# this page's own confirmed wall run (regularity ~0.99) versus a known
# contaminating stray-cluster sample from the same page (regularity ~0.43);
# 0.6 sits with margin on both sides and is not tied to any one drawing.
_MIN_SPACING_REGULARITY = 0.6


@dataclass(frozen=True)
class EdgeHatchVerdict:
    classification: EdgeClassification
    confidence: float
    coverage_fraction: float
    reason: str
    supporting_cluster_bbox: Optional[tuple] = None
    supporting_cluster_strokes: int = 0


def _edge_axis_and_position(
    x1: float, y1: float, x2: float, y2: float
) -> tuple[str, float, float, float]:
    """Return (axis, fixed_position, span_lo, span_hi) for an axis-aligned edge.

    axis == "vertical" means the edge runs along Y at a fixed X.
    axis == "horizontal" means the edge runs along X at a fixed Y.
    """
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    if dy >= dx:
        return ("vertical", (x1 + x2) / 2.0, min(y1, y2), max(y1, y2))
    return ("horizontal", (y1 + y2) / 2.0, min(x1, x2), max(x1, x2))


def classify_edge_hatch_evidence(
    clusters: Sequence[HatchCluster],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> EdgeHatchVerdict:
    """Classify whether a straight candidate edge is backed by hatch evidence.

    ``clusters`` should be the ``all_clusters`` list returned by
    ``pb_hatch_detection_v160.detect_hatch_patterns`` for the same page
    (rejected clusters are ignored automatically).

    The edge is described by two endpoints and must be (approximately)
    axis-aligned -- this mirrors how building envelope sides are already
    represented elsewhere in this codebase (rectangular outer envelope).

    Evidence is gathered per-stroke rather than per-cluster: the upstream
    hatch clusterer (``pb_hatch_detection_v160``) is a general-purpose
    stroke grouper and can chain unrelated nearby marks (e.g. a wall's
    hatch ticks plus an adjacent column/grid-intersection symbol) into one
    cluster via transitive proximity. A cluster's own aggregate bbox and
    confidence are therefore too coarse for "does hatching run exactly
    along this edge" -- this function instead filters individual accepted
    strokes to the ones actually near the edge line and measures their
    coverage and spacing regularity directly.
    """
    axis, fixed_pos, span_lo, span_hi = _edge_axis_and_position(x1, y1, x2, y2)
    span = span_hi - span_lo

    if span < _MIN_EDGE_SPAN_PT:
        return EdgeHatchVerdict(
            classification="ABSTAIN",
            confidence=0.0,
            coverage_fraction=0.0,
            reason=f"edge span {span:.1f}pt below minimum {_MIN_EDGE_SPAN_PT}pt "
            "-- too short to conclude either way",
        )

    # A cluster whose own bounding box is far larger than any plausible
    # single wall run for an edge this size is not local hatch evidence for
    # this edge -- it is the upstream general-purpose clusterer chaining
    # unrelated marks together via transitive proximity (observed on this
    # page: a single accepted cluster spanning most of the sheet, over
    # 1300pt on a side, that incidentally contains a handful of stray
    # strokes near otherwise-unrelated edges). Scales with the edge's own
    # span so short probe edges aren't matched to page-spanning clusters,
    # with a floor so short edges can still match a modestly-sized cluster.
    max_cluster_diagonal = max(300.0, 4.0 * span)

    near_edge_positions: List[float] = []
    source_cluster: Optional[HatchCluster] = None

    for cluster in clusters:
        if cluster.rejected or not cluster.strokes:
            continue
        cx0, cy0, cx1, cy1 = cluster.bbox
        cluster_diagonal = math.hypot(cx1 - cx0, cy1 - cy0)
        if cluster_diagonal > max_cluster_diagonal:
            continue
        for stroke in cluster.strokes:
            pos = stroke.cx if axis == "vertical" else stroke.cy
            along = stroke.cy if axis == "vertical" else stroke.cx
            if abs(pos - fixed_pos) > _MAX_PERPENDICULAR_OFFSET_PT:
                continue
            if along < span_lo - 1.0 or along > span_hi + 1.0:
                continue
            near_edge_positions.append(along)
            if source_cluster is None:
                source_cluster = cluster

    if len(near_edge_positions) < _MIN_HATCH_STROKES:
        return EdgeHatchVerdict(
            classification="NO_HATCH_EVIDENCE",
            confidence=0.0,
            coverage_fraction=0.0,
            reason=(
                f"only {len(near_edge_positions)} accepted hatch strokes found "
                f"within {_MAX_PERPENDICULAR_OFFSET_PT}pt of this {axis} edge "
                f"(span {span:.1f}pt), below the {_MIN_HATCH_STROKES}-stroke "
                "minimum -- vector geometry does not show a continuous wall "
                "hatch run here"
            ),
        )

    near_edge_positions.sort()
    covered_lo = max(span_lo, near_edge_positions[0])
    covered_hi = min(span_hi, near_edge_positions[-1])
    coverage = max(0.0, covered_hi - covered_lo) / span

    gaps = [
        near_edge_positions[i + 1] - near_edge_positions[i]
        for i in range(len(near_edge_positions) - 1)
    ]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    if mean_gap > 0 and len(gaps) >= 2:
        variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        spacing_regularity = 1.0 / (1.0 + math.sqrt(variance) / mean_gap)
    else:
        spacing_regularity = 0.5

    confidence = round(min(1.0, coverage) * spacing_regularity, 3)

    if coverage >= _MIN_COVERAGE_FRACTION and spacing_regularity >= _MIN_SPACING_REGULARITY:
        classification: EdgeClassification = "SOLID_WALL_HATCH_CONFIRMED"
    else:
        classification = "ABSTAIN"

    return EdgeHatchVerdict(
        classification=classification,
        confidence=confidence,
        coverage_fraction=round(coverage, 3),
        reason=(
            f"{len(near_edge_positions)} accepted hatch strokes within "
            f"{_MAX_PERPENDICULAR_OFFSET_PT}pt of edge, mean spacing "
            f"{mean_gap:.1f}pt, covering {coverage * 100:.0f}% of edge span"
        ),
        supporting_cluster_bbox=source_cluster.bbox if source_cluster else None,
        supporting_cluster_strokes=len(near_edge_positions),
    )
