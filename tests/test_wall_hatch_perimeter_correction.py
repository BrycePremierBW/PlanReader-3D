"""Regression tests for pb_wall_hatch_perimeter_correction.

Uses the real KSTVET source drawing (benchmarks/sources/
1727358888238-bq-nd-drawing.pdf, page index 53) as the positive-evidence
fixture, plus synthetic HatchCluster fixtures for the negative/ambiguous
cases -- particularly the false-positive regression this module's own
development caught: hatch absence alone (no corroborating open-zone label)
must never be read as "confirmed open," because a real wall can lack a
continuous hatch signature on some drawings (KSTVET's own north wall,
confirmed solid by direct elevation inspection, has none) without being open.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from pb_hatch_detection_v160 import HatchCluster, Stroke, detect_hatch_patterns
from pb_wall_hatch_perimeter_correction import (
    _floor_plan_viewport_bbox,
    resolve_hatch_confirmed_open_length_m,
)

_KSTVET_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "1727358888238-bq-nd-drawing.pdf"
)
_KSTVET_FLOOR_PLAN_PAGE_INDEX = 53


def _load_kstvet_page():
    if not _KSTVET_PDF.exists():
        pytest.skip(f"benchmark source fixture not present: {_KSTVET_PDF}")
    doc = fitz.open(str(_KSTVET_PDF))
    return doc, doc[_KSTVET_FLOOR_PLAN_PAGE_INDEX]


def test_kstvet_real_drawing_finds_the_confirmed_open_verandah_segment() -> None:
    doc, page = _load_kstvet_page()
    try:
        _evidence, clusters, _diag = detect_hatch_patterns(page, scale_info=None, words=None)
        result = resolve_hatch_confirmed_open_length_m(
            clusters, length_m=10.15, width_m=8.35, page=page
        )
    finally:
        doc.close()

    assert result.status == "corrected"
    # Independently cross-checked earlier (manual hatch-edge sweep of the
    # same drawing) at ~4.86m for this same physical segment -- allow a
    # reasonable band around that rather than pinning an exact float.
    assert 3.5 <= result.open_length_m <= 6.5


def _diagonal_tick_strokes(x_center: float, y0: float, y1: float, spacing: float = 9.6) -> list:
    strokes = []
    y = y0
    while y < y1:
        strokes.append(
            Stroke(x1=x_center - 3.0, y1=y + 3.0, x2=x_center + 3.0, y2=y - 3.0)
        )
        y += spacing
    return strokes


def _wall_cluster(x_center: float, y0: float, y1: float) -> HatchCluster:
    strokes = _diagonal_tick_strokes(x_center, y0, y1)
    xs = [s.x1 for s in strokes] + [s.x2 for s in strokes]
    ys = [s.y1 for s in strokes] + [s.y2 for s in strokes]
    return HatchCluster(
        strokes=strokes,
        stroke_count=len(strokes),
        hatch_confidence=0.85,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        rejected=False,
    )


class _FakePage:
    """Minimal fitz.Page stand-in exposing only get_text('dict')."""

    def __init__(self, lines: list) -> None:
        self._lines = lines

    def get_text(self, mode: str):
        assert mode == "dict"
        return {
            "blocks": [
                {"lines": [{"bbox": bbox, "spans": [{"text": text}]}]}
                for text, bbox in self._lines
            ]
        }


def _synthetic_rectangle_clusters(west_x=100.0, east_x=1000.0, y0=100.0, y1=1000.0):
    # West and east walls fully hatched (confirmed solid); north and south
    # carry no hatch cluster at all -- simulating a drawing convention gap
    # exactly like KSTVET's own north wall, NOT a real opening. Sized large
    # enough (900pt sides) that the bottom edge sweeps into several
    # sub-segments, so a label-adjacent middle segment away from the two
    # wall corners can be checked cleanly, without their own corner ticks
    # (unavoidably coincident with the envelope's derived bottom edge)
    # contaminating every sub-segment's evidence.
    return [_wall_cluster(west_x, y0, y1), _wall_cluster(east_x, y0, y1)]


_SYNTHETIC_SCALE_PT_PER_M = 40.0
_SYNTHETIC_SIDE_PT = 900.0


def test_hatch_absence_without_a_corroborating_label_is_never_treated_as_open() -> None:
    """Regression for the false-positive this module's own development
    caught: north/south have zero hatch evidence here, same as west/east's
    own convention gap on a drawing with no open-zone label anywhere. Must
    abstain (no correction), not silently subtract those sides."""
    clusters = _synthetic_rectangle_clusters()
    page = _FakePage(
        lines=[("GROUND FLOOR PLAN", (400.0, 1020.0, 600.0, 1035.0))]
    )
    side_m = _SYNTHETIC_SIDE_PT / _SYNTHETIC_SCALE_PT_PER_M
    result = resolve_hatch_confirmed_open_length_m(
        clusters, length_m=side_m, width_m=side_m, page=page
    )
    assert result.status == "abstained"


def test_hatch_absence_with_a_corroborating_verandah_label_is_confirmed_open() -> None:
    """Same synthetic geometry, but now a 'VERANDAH' label sits directly
    below (outward of) the MIDDLE of the bottom edge, away from the two
    wall corners -- the corroboration this module requires before treating
    hatch absence as a real opening."""
    clusters = _synthetic_rectangle_clusters()
    side_m = _SYNTHETIC_SIDE_PT / _SYNTHETIC_SCALE_PT_PER_M
    page = _FakePage(
        lines=[
            ("GROUND FLOOR PLAN", (400.0, 1020.0, 600.0, 1035.0)),
            ("VERANDAH", (520.0, 1020.0, 590.0, 1035.0)),
        ]
    )
    result = resolve_hatch_confirmed_open_length_m(
        clusters, length_m=side_m, width_m=side_m, page=page
    )
    assert result.status == "corrected"
    assert result.open_length_m > 0


def test_scale_disagreement_between_hatch_bbox_and_known_dimensions_abstains() -> None:
    clusters = _synthetic_rectangle_clusters()
    # A plan-title-labelled page keeps both west/east walls (see the
    # documented fallback limitation above) so this test isolates the scale
    # cross-validation specifically, not cluster grouping.
    page = _FakePage(lines=[("GROUND FLOOR PLAN", (400.0, 1020.0, 600.0, 1035.0))])
    # Deliberately inconsistent length_m/width_m relative to the 900x900pt
    # synthetic bbox -- the two derived scales should disagree well beyond
    # tolerance.
    result = resolve_hatch_confirmed_open_length_m(
        clusters, length_m=5.0, width_m=50.0, page=page
    )
    assert result.status == "abstained"
    assert "corroborate" in result.reason


def test_fewer_than_two_wall_like_clusters_abstains() -> None:
    result = resolve_hatch_confirmed_open_length_m(
        [_wall_cluster(100.0, 100.0, 500.0)], length_m=10.0, width_m=8.0, page=None
    )
    assert result.status == "abstained"


def test_degenerate_single_line_cluster_is_excluded_from_wall_like_set() -> None:
    """A cluster with a real bbox width/height of zero (a straight
    dimension/witness line the upstream detector mis-tagged as a low
    confidence parallel-hatch) must not corrupt the derived envelope.

    Scoped via a plan-title-labelled page (the primary, tested mechanism)
    rather than the no-viewport fallback: the fallback's spatial-proximity
    grouping is a separate, known-limited mechanism (see
    test_spatial_connectivity_fallback_can_lose_a_widely_separated_wall
    below) and entangling the two would test the wrong thing here.
    """
    good = _synthetic_rectangle_clusters()
    degenerate = HatchCluster(
        strokes=[Stroke(x1=50.0, y1=y, x2=50.0, y2=y + 1.0) for y in range(50, 600, 10)],
        stroke_count=20,
        hatch_confidence=0.7,
        bbox=(50.0, 50.0, 50.0, 600.0),
        rejected=False,
    )
    from pb_wall_hatch_perimeter_correction import _wall_like_clusters

    page = _FakePage(lines=[("GROUND FLOOR PLAN", (400.0, 1020.0, 600.0, 1035.0))])
    viewport_bbox = _floor_plan_viewport_bbox(page)
    survivors = _wall_like_clusters(good + [degenerate], viewport_bbox)
    assert degenerate not in survivors
    assert len(survivors) == 2


def test_spatial_connectivity_fallback_can_lose_a_widely_separated_wall() -> None:
    """Known, documented limitation: with no plan-title label to scope by,
    the fallback groups wall-like clusters purely by mutual proximity. Two
    genuinely opposite walls of the same room (e.g. west/east, far apart by
    definition, with no hatched north/south cluster bridging them) are NOT
    spatially connected to each other and can end up in separate groups --
    only the larger group survives, silently dropping the other wall. This
    is exactly why the plan-title-anchored path is primary and this
    fallback is a secondary, weaker mechanism, not why it should be trusted
    to reconstruct a whole building's envelope on its own. Locked in as a
    regression so a future change to the fallback's behaviour is a
    deliberate, visible decision rather than a silent one.
    """
    from pb_wall_hatch_perimeter_correction import _wall_like_clusters

    clusters = _synthetic_rectangle_clusters()  # west/east, 900pt apart, no bridge
    survivors = _wall_like_clusters(clusters, None)
    assert len(survivors) == 1
