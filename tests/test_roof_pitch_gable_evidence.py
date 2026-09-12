"""Regression tests for pb_roof_pitch_gable_evidence.

Uses the real Lamu Ishakani ECD classrooms source drawing (benchmarks/
sources/lamu-ishakani-ecd-classrooms-boq.pdf, page index 40, "ELEVATION
02") as the positive-evidence fixture, plus synthetic segment-tuple
fixtures for the false positives/negatives this module's own design had to
guard against: a flat long-side elevation with no peak, an ambiguous
multi-apex page, two roof slopes with genuinely different pitches, a side
with no matching wall-corner vertical, short noise segments (dimension
ticks / arrowheads) that must not be treated as roofline, and -- the
trickiest case -- a roof plane extended over a secondary space (e.g. a
verandah) where the nearer wall's own corner sits, by simple trigonometry,
exactly on the same ray as the farther verandah post.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from pb_roof_pitch_gable_evidence import (
    _DiagSegment,
    _VertSegment,
    _resolve_gable_pitch_in_viewport,
    resolve_sole_gable_roof_pitch,
)

_LAMU_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "lamu-ishakani-ecd-classrooms-boq.pdf"
)


def test_real_lamu_drawing_finds_the_sole_gable_elevation() -> None:
    if not _LAMU_PDF.exists():
        pytest.skip(f"benchmark source fixture not present: {_LAMU_PDF}")
    doc = fitz.open(str(_LAMU_PDF))
    try:
        evidence = resolve_sole_gable_roof_pitch(doc)
    finally:
        doc.close()

    assert evidence is not None
    assert evidence.source_page == 41
    # Directly measured from the drawing's own roofline vectors -- nowhere
    # near the BOQ spec's "not exceeding 30 degrees" ceiling, and not
    # derived from the "+3000 ROOF LEVEL" datum (which this module never
    # reads at all).
    assert 17.5 <= evidence.pitch_deg <= 18.5
    # The verandah-side run must come out LARGER than the classroom-only
    # side -- this is the whole point of picking the farthest, not
    # nearest, qualifying wall-corner vertical.
    assert evidence.run_a_pt > evidence.run_b_pt
    assert 85.0 <= evidence.run_b_pt <= 100.0
    assert 130.0 <= evidence.run_a_pt <= 150.0


def _symmetric_gable(pitch_deg=18.0, run=92.0, apex=(500.0, 900.0)):
    import math

    ax, ay = apex
    pitch_rad = math.radians(pitch_deg)
    rise = run * math.tan(pitch_rad)
    diagonals = [
        _DiagSegment(x_hi=ax, y_hi=ay, x_lo=ax + run, y_lo=ay + rise, length=run / math.cos(pitch_rad)),
        _DiagSegment(x_hi=ax, y_hi=ay, x_lo=ax - run, y_lo=ay + rise, length=run / math.cos(pitch_rad)),
    ]
    verticals = [
        _VertSegment(x=ax + run, top_y=ay + rise, bottom_y=ay + rise + 80.0, length=80.0),
        _VertSegment(x=ax - run, top_y=ay + rise, bottom_y=ay + rise + 80.0, length=80.0),
    ]
    return diagonals, verticals


def test_simple_symmetric_gable_resolves_equal_runs() -> None:
    diagonals, verticals = _symmetric_gable(pitch_deg=20.0, run=100.0)
    evidence = _resolve_gable_pitch_in_viewport(diagonals, verticals, source_page=1)
    assert evidence is not None
    assert abs(evidence.pitch_deg - 20.0) < 0.1
    assert abs(evidence.run_a_pt - 100.0) < 0.5
    assert abs(evidence.run_b_pt - 100.0) < 0.5


def test_asymmetric_verandah_extension_picks_farther_post_not_nearer_wall() -> None:
    """The exact Lamu-shaped case: one side's roofline is a single
    continuous slope that passes over BOTH the classroom's own wall corner
    (nearer) and the verandah's post (farther) at the same pitch. Both
    verticals genuinely lie on the ray; the farther one is the correct
    answer for roof-covering area, not the nearer one."""
    import math

    ax, ay = 500.0, 900.0
    pitch_deg = 18.0
    pitch_rad = math.radians(pitch_deg)
    near_run, far_run = 92.0, 140.0
    diagonals = [
        _DiagSegment(x_hi=ax, y_hi=ay, x_lo=ax + near_run, y_lo=ay + near_run * math.tan(pitch_rad), length=60.0),
        _DiagSegment(x_hi=ax, y_hi=ay, x_lo=ax - far_run, y_lo=ay + far_run * math.tan(pitch_rad), length=150.0),
    ]
    verticals = [
        # Right side: single ordinary wall corner.
        _VertSegment(x=ax + near_run, top_y=ay + near_run * math.tan(pitch_rad), bottom_y=ay + 180.0, length=90.0),
        # Left side: the classroom's own (nearer) wall corner...
        _VertSegment(x=ax - near_run, top_y=ay + near_run * math.tan(pitch_rad), bottom_y=ay + 180.0, length=90.0),
        # ...and the verandah's (farther) post, also genuinely on the same ray.
        _VertSegment(x=ax - far_run, top_y=ay + far_run * math.tan(pitch_rad), bottom_y=ay + 150.0, length=45.0),
    ]
    evidence = _resolve_gable_pitch_in_viewport(diagonals, verticals, source_page=1)
    assert evidence is not None
    assert abs(evidence.run_b_pt - near_run) < 1.0  # right side unaffected
    assert abs(evidence.run_a_pt - far_run) < 1.0    # left side: farther post wins, not the nearer wall


def test_flat_long_side_elevation_has_no_apex() -> None:
    """A long-side elevation shows a flat/rectangular roofline silhouette --
    no two diagonals meeting at a peak -- and must not be misread as gable
    evidence."""
    diagonals: list = []
    verticals = [
        _VertSegment(x=100.0, top_y=500.0, bottom_y=600.0, length=100.0),
        _VertSegment(x=800.0, top_y=500.0, bottom_y=600.0, length=100.0),
    ]
    evidence = _resolve_gable_pitch_in_viewport(diagonals, verticals, source_page=1)
    assert evidence is None


def test_short_noise_segments_are_not_treated_as_roofline() -> None:
    """Dimension ticks and arrowheads are short diagonals that can
    coincidentally meet at a point; they must be filtered out by the
    minimum roofline length before apex clustering even runs."""
    diagonals = [
        _DiagSegment(x_hi=500.0, y_hi=900.0, x_lo=510.0, y_lo=908.0, length=12.8),
        _DiagSegment(x_hi=500.0, y_hi=900.0, x_lo=490.0, y_lo=908.0, length=12.8),
    ]
    verticals = [
        _VertSegment(x=510.0, top_y=908.0, bottom_y=988.0, length=80.0),
        _VertSegment(x=490.0, top_y=908.0, bottom_y=988.0, length=80.0),
    ]
    evidence = _resolve_gable_pitch_in_viewport(diagonals, verticals, source_page=1)
    assert evidence is None


def test_disagreeing_pitch_between_two_diagonals_abstains() -> None:
    """Two diagonals that happen to share a high endpoint but slope at
    very different angles are not a real single-pitch roof plane."""
    diagonals = [
        _DiagSegment(x_hi=500.0, y_hi=900.0, x_lo=600.0, y_lo=940.0, length=107.7),  # ~21.8 deg
        _DiagSegment(x_hi=500.0, y_hi=900.0, x_lo=400.0, y_lo=980.0, length=134.5),  # ~38.7 deg
    ]
    verticals = [
        _VertSegment(x=600.0, top_y=940.0, bottom_y=1020.0, length=80.0),
        _VertSegment(x=400.0, top_y=980.0, bottom_y=1060.0, length=80.0),
    ]
    evidence = _resolve_gable_pitch_in_viewport(diagonals, verticals, source_page=1)
    assert evidence is None


def test_missing_wall_corner_on_one_side_abstains() -> None:
    """A real apex with a matching pitch on both slopes, but no vertical
    structural element actually meets the roofline on one side -- must not
    guess a run for that side."""
    diagonals, _verticals = _symmetric_gable(pitch_deg=18.0, run=100.0)
    only_right_vertical = [
        _VertSegment(x=600.0, top_y=932.5, bottom_y=1012.5, length=80.0),
    ]
    evidence = _resolve_gable_pitch_in_viewport(diagonals, only_right_vertical, source_page=1)
    assert evidence is None


def test_multiple_ambiguous_apexes_on_one_page_abstain() -> None:
    """Two unrelated, independent apex clusters on the same viewport (e.g.
    a decorative pediment plus the real roof peak) must not be resolved by
    picking one arbitrarily."""
    diagonals, verticals = _symmetric_gable(pitch_deg=18.0, run=100.0, apex=(500.0, 900.0))
    d2, v2 = _symmetric_gable(pitch_deg=25.0, run=60.0, apex=(500.0, 1200.0))
    evidence = _resolve_gable_pitch_in_viewport(diagonals + d2, verticals + v2, source_page=1)
    assert evidence is None
