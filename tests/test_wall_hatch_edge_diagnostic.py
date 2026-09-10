"""Regression + diagnostic evidence for pb_wall_hatch_edge_diagnostic.

Uses the real KSTVET CBC classroom source drawing
(benchmarks/sources/1727358888238-bq-nd-drawing.pdf, page index 53) as a
fixture. The candidate edge coordinates below were established by direct
visual + vector inspection of that page (PyMuPDF ``get_drawings()`` hatch
tick clustering, see session diagnostic notes) -- NOT from the benchmark's
expected/gold quantities. This module and its tests do not import, read,
or reference any ``expected_*.json`` file.

Findings this test locks in:
  - The classroom's west and east side walls (y roughly 390 to 705/720,
    at x roughly 268 and x roughly 646) carry a continuous, consistently
    spaced (~7.9-8.7pt) diagonal hatch stroke pattern for their full run
    -- classified SOLID_WALL_HATCH_CONFIRMED.
  - The same two x-positions, extended south into the verandah strip
    (y roughly 705 to 776), carry NO qualifying hatch strokes at all --
    classified NO_HATCH_EVIDENCE. This is vector-geometry confirmation
    (independent of any benchmark answer) that the verandah's side edges
    are not drawn as solid hatched masonry, which is the root cause of
    the naive 4-sided perimeter formula overcounting wall area for this
    drawing. This diagnostic is NOT wired into wall-area/perimeter
    production logic -- see module docstring for why.
  - The classroom's NORTH wall (a wall independently confirmed solid by
    visual inspection of the rendered page) is classified ABSTAIN, not
    SOLID_WALL_HATCH_CONFIRMED: this drawing does not hatch that wall
    with the same continuous, regularly-spaced diagonal tick pattern
    used on the side walls -- only sparse markers at grid intersections.
    This is a genuine, honestly-documented limitation of hatch-run
    evidence: absence of a clean hatch signature does not mean a wall
    is open, only that this particular signal is inconclusive for it.
    The classifier is designed to fail closed (ABSTAIN) rather than
    guess in that situation, per this session's integrity rules.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from pb_hatch_detection_v160 import detect_hatch_patterns
from pb_wall_hatch_edge_diagnostic import classify_edge_hatch_evidence

_KSTVET_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "1727358888238-bq-nd-drawing.pdf"
)
_KSTVET_FLOOR_PLAN_PAGE_INDEX = 53


def _load_kstvet_clusters():
    if not _KSTVET_PDF.exists():
        pytest.skip(f"benchmark source fixture not present: {_KSTVET_PDF}")
    doc = fitz.open(str(_KSTVET_PDF))
    try:
        page = doc[_KSTVET_FLOOR_PLAN_PAGE_INDEX]
        _evidence, clusters, _diag = detect_hatch_patterns(page, scale_info=None, words=None)
        return clusters
    finally:
        doc.close()


@pytest.fixture(scope="module")
def kstvet_clusters():
    return _load_kstvet_clusters()


def test_west_wall_run_is_hatch_confirmed(kstvet_clusters) -> None:
    verdict = classify_edge_hatch_evidence(
        kstvet_clusters, x1=268.0, y1=390.0, x2=268.0, y2=705.0
    )
    assert verdict.classification == "SOLID_WALL_HATCH_CONFIRMED"
    assert verdict.coverage_fraction >= 0.55
    assert verdict.supporting_cluster_strokes >= 5


def test_east_wall_run_is_hatch_confirmed(kstvet_clusters) -> None:
    verdict = classify_edge_hatch_evidence(
        kstvet_clusters, x1=646.0, y1=390.0, x2=646.0, y2=705.0
    )
    assert verdict.classification == "SOLID_WALL_HATCH_CONFIRMED"
    assert verdict.coverage_fraction >= 0.55
    assert verdict.supporting_cluster_strokes >= 5


def test_west_verandah_edge_has_no_hatch_evidence(kstvet_clusters) -> None:
    verdict = classify_edge_hatch_evidence(
        kstvet_clusters, x1=268.0, y1=720.0, x2=268.0, y2=776.0
    )
    assert verdict.classification == "NO_HATCH_EVIDENCE"
    assert verdict.coverage_fraction == 0.0


def test_east_verandah_edge_has_no_hatch_evidence(kstvet_clusters) -> None:
    verdict = classify_edge_hatch_evidence(
        kstvet_clusters, x1=646.0, y1=720.0, x2=646.0, y2=776.0
    )
    assert verdict.classification == "NO_HATCH_EVIDENCE"
    assert verdict.coverage_fraction == 0.0


def test_north_wall_without_regular_hatch_abstains_rather_than_confirms(
    kstvet_clusters,
) -> None:
    """The north wall is solid (confirmed by visual inspection of the
    rendered page) but this drawing does not hatch it with a continuous,
    regularly-spaced tick pattern -- only sparse grid-intersection
    markers. The classifier must ABSTAIN here, not silently pass or
    fail closed toward NO_HATCH_EVIDENCE (which would wrongly suggest
    the wall is open) or toward SOLID_WALL_HATCH_CONFIRMED (which would
    overstate evidence this drawing does not provide)."""
    verdict = classify_edge_hatch_evidence(
        kstvet_clusters, x1=268.0, y1=390.0, x2=646.0, y2=390.0
    )
    assert verdict.classification == "ABSTAIN"


def test_short_edge_abstains_rather_than_asserting_open() -> None:
    """A trivially short probe must not be treated as evidence of an open
    edge -- absence of hatch over a few points proves nothing."""
    verdict = classify_edge_hatch_evidence(
        [], x1=100.0, y1=100.0, x2=100.0, y2=105.0
    )
    assert verdict.classification == "ABSTAIN"


def test_no_clusters_on_a_real_span_is_no_hatch_evidence_not_a_crash() -> None:
    verdict = classify_edge_hatch_evidence(
        [], x1=0.0, y1=0.0, x2=0.0, y2=100.0
    )
    assert verdict.classification == "NO_HATCH_EVIDENCE"
