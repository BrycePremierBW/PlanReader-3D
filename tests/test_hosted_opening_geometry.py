"""Regression tests for pb_hosted_opening_geometry.

Real positive fixtures use the Lamu Ishakani ECD classrooms drawing
(benchmarks/sources/lamu-ishakani-ecd-classrooms-boq.pdf, page index 40):
its north wall shows 6 repeated hosted window voids drawn as gaps between
solid-fill wall piers, with internal glazing-bar strokes, and its
classroom/veranda dividing wall shows 2 hosted door voids at the same
piers-and-gaps convention, each with a jamb-anchored door-swing arc. Both
were located and hand-verified by direct PDF vector inspection this
session -- not from any benchmark expected value (this module has no
scorer mapping and is not wired into any takeoff quantity).

The requested "Baghau p36" / "Dungicha p134" fixtures were confirmed
genuinely unavailable on this machine after an exhaustive search (exact
filenames checked against the full contents of benchmarks/sources/,
confirmed identical between the worktree and the main checkout, plus a
repo-wide grep and a home-directory/OneDrive filesystem search -- zero
matches). Per explicit instruction, Lamu is used as the real-fixture
substitute; this module's real KSTVET north-wall window symbol (a jamb-box
drawn flush with the continuing wall-face lines, see
test_kstvet_frame_flush_convention_correctly_abstains below) is kept as a
documented, honest limitation rather than force-fit with a fragile
heuristic -- two such heuristics were tried and discarded during this
module's own development after they produced cascading false positives
(see git history / PR description for the full account).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import pytest

fitz = pytest.importorskip("fitz")

from pb_hosted_opening_geometry import resolve_hosted_opening_spans

_LAMU_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "lamu-ishakani-ecd-classrooms-boq.pdf"
)
_LAMU_PLAN_PAGE_INDEX = 40
_LAMU_SCALE_PT_PER_M = 28.0

_KSTVET_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "1727358888238-bq-nd-drawing.pdf"
)
_KSTVET_PLAN_PAGE_INDEX = 53
_KSTVET_SCALE_PT_PER_M = 37.24


def _load_page(pdf_path: Path, page_index: int):
    if not pdf_path.exists():
        pytest.skip(f"benchmark source fixture not present: {pdf_path}")
    doc = fitz.open(str(pdf_path))
    return doc, doc[page_index]


# ---------------------------------------------------------------------------
# Real positive fixtures: Lamu windows
# ---------------------------------------------------------------------------


def test_lamu_north_wall_finds_six_repeated_window_like_openings():
    doc, page = _load_page(_LAMU_PDF, _LAMU_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(190, 95, 660, 220), scale_authority=_LAMU_SCALE_PT_PER_M
        )
    finally:
        doc.close()

    assert ev.status == "found"
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    assert len(windows) == 6
    for w in windows:
        assert 45.0 <= w.span_pt <= 50.0
        assert w.width_m is not None
        assert 1.6 <= w.width_m <= 1.8
        assert 5.0 <= w.wall_thickness_pt <= 6.5
        assert "aligned_two_face_gap" in w.evidence_flags
        assert "internal_frame_or_glazing_evidence" in w.evidence_flags


def test_lamu_door_wall_distinguishes_door_like_from_window_like():
    doc, page = _load_page(_LAMU_PDF, _LAMU_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(190, 270, 660, 300), scale_authority=_LAMU_SCALE_PT_PER_M
        )
    finally:
        doc.close()

    assert ev.status == "found"
    doors = [o for o in ev.openings if o.subtype == "door_like"]
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    assert len(doors) >= 1
    assert len(windows) >= 1
    door = doors[0]
    assert "jamb_anchored_door_swing" in door.evidence_flags
    assert door.span_pt < min(w.span_pt for w in windows)  # doors narrower than windows here
    assert door.width_m is not None
    assert 1.2 <= door.width_m <= 1.6


def test_kstvet_frame_flush_convention_correctly_abstains():
    """Documented limitation: KSTVET's north-wall window symbol is a jamb
    box whose own top/bottom outline sits flush with the continuing
    wall-face lines (architecturally correct -- a jamb sits flush with the
    wall surface) rather than leaving a literal gap in those lines. This
    module deliberately does not attempt to recover that case (two
    heuristics were tried and discarded for producing false positives
    elsewhere on the same page) and must abstain here rather than guess."""
    doc, page = _load_page(_KSTVET_PDF, _KSTVET_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(260, 375, 650, 410), scale_authority=_KSTVET_SCALE_PT_PER_M
        )
    finally:
        doc.close()
    assert ev.status == "abstained"


def test_kstvet_hatch_only_wall_does_not_crash_and_abstains():
    """KSTVET's west/east walls are drawn as diagonal hatch ticks with no
    long bounding stroke lines and no solid fill -- this module has no
    evidence channel for that convention at all and must abstain cleanly,
    not raise."""
    doc, page = _load_page(_KSTVET_PDF, _KSTVET_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(260, 390, 280, 705), scale_authority=_KSTVET_SCALE_PT_PER_M
        )
    finally:
        doc.close()
    assert ev.status == "abstained"


def test_no_scale_authority_still_resolves_span_pt_but_not_width_m():
    doc, page = _load_page(_LAMU_PDF, _LAMU_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(page, viewport_bbox=(190, 95, 660, 220), scale_authority=None)
    finally:
        doc.close()
    assert ev.status == "found"
    for o in ev.openings:
        assert o.span_pt > 0
        assert o.width_m is None


# ---------------------------------------------------------------------------
# Synthetic fixtures: fake page + drawing dicts matching PyMuPDF's own shape
# ---------------------------------------------------------------------------


class _Pt:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _Rect:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.width = x1 - x0
        self.height = y1 - y0


class _FakePage:
    def __init__(self, drawings, rect=None, number=0):
        self._drawings = drawings
        self.rect = rect or _Rect(0, 0, 2000, 2000)
        self.number = number

    def get_drawings(self):
        return self._drawings

    def get_text(self, *_a, **_kw):
        return ""


def _line(x0, y0, x1, y1, color=(0.5, 0.5, 0.5), width=0.5):
    return {"color": color, "width": width, "fill": None, "items": [("l", _Pt(x0, y0), _Pt(x1, y1))]}


def _fill_rect(x0, y0, x1, y1, fill=(0.0, 0.0, 0.0)):
    return {
        "color": None,
        "fill": fill,
        "rect": _Rect(x0, y0, x1, y1),
        "items": [
            ("l", _Pt(x0, y0), _Pt(x1, y0)),
            ("l", _Pt(x1, y0), _Pt(x1, y1)),
            ("l", _Pt(x1, y1), _Pt(x0, y1)),
        ],
    }


def _white_mask(x0, y0, x1, y1):
    return {
        "color": None,
        "fill": (1.0, 1.0, 1.0),
        "rect": _Rect(x0, y0, x1, y1),
        "items": [
            ("l", _Pt(x0, y0), _Pt(x1, y0)),
            ("l", _Pt(x1, y0), _Pt(x1, y1)),
            ("l", _Pt(x1, y1), _Pt(x0, y1)),
        ],
    }


def _door_swing_arc(hinge_x, wall_y, radius, color=(0.0, 0.0, 0.0)):
    """A quarter-circle cubic matching pb_plan_door_swing_geometry's own
    expected shape (mirrors the real KSTVET D1 arc's own point layout):
    the door leaf swings from perpendicular-to-the-wall (start, directly
    'above' the hinge) to flat-against-the-wall (end, one radius away from
    the hinge along the wall line) -- axis-aligned tangent, equal radii."""
    start = (hinge_x, wall_y - radius)
    ctrl1 = (hinge_x, wall_y)
    ctrl2 = (hinge_x + radius * 0.55, wall_y)
    end = (hinge_x + radius, wall_y)
    return {
        "color": color,
        "fill": None,
        "items": [
            (
                "c",
                _Pt(*start),
                _Pt(*ctrl1),
                _Pt(*ctrl2),
                _Pt(*end),
            )
        ],
    }


def _two_pier_fill_wall_with_window(x_left_end, gap_start, gap_end, x_right_end, y0=100.0, thickness=6.0):
    """One real opening between two wall-like fill piers, plus a small
    internal glazing-bar line inside the gap (window_like evidence)."""
    y1 = y0 + thickness
    drawings = [
        _fill_rect(x_left_end - 20.0, y0, x_left_end, y1),
        _fill_rect(gap_start, y0, gap_start, y0),  # no-op filler removed below
    ]
    drawings = [
        _fill_rect(x_left_end - 20.0, y0, gap_start, y1),
        _fill_rect(gap_end, y0, x_right_end + 20.0, y1),
        _line(gap_start + 5.0, y0 + 1.0, gap_end - 5.0, y0 + 1.0, color=(0.0, 0.0, 0.0)),
    ]
    return drawings


def test_synthetic_paired_wall_faces_horizontal_window_like():
    drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    page = _FakePage(drawings)
    ev = resolve_hosted_opening_spans(page, scale_authority=25.0)
    assert ev.status == "found"
    assert len(ev.openings) == 1
    o = ev.openings[0]
    assert o.subtype == "window_like"
    assert abs(o.span_pt - 60.0) < 0.5
    assert abs(o.width_m - 2.4) < 0.05


def test_synthetic_door_swing_anchored_at_jamb_is_door_like():
    drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    # A quarter-circle swing anchored at the left jamb (x=200), radius 30pt.
    drawings.append(_door_swing_arc(200.0, 100.0, 30.0))
    page = _FakePage(drawings)
    ev = resolve_hosted_opening_spans(page, scale_authority=25.0)
    assert ev.status == "found"
    assert ev.openings[0].subtype == "door_like"
    assert "jamb_anchored_door_swing" in ev.openings[0].evidence_flags


# ---------------------------------------------------------------------------
# Metamorphic tests: 90-degree rotation, translation, 0.5x / 2x scale
# ---------------------------------------------------------------------------


def _transform_drawings(drawings, *, rotate90=False, dx=0.0, dy=0.0, scale=1.0):
    def tf(x, y):
        if rotate90:
            x, y = -y, x
        return (x * scale + dx, y * scale + dy)

    out = []
    for d in drawings:
        new_items = []
        for item in d["items"]:
            op = item[0]
            pts = [tf(p.x, p.y) for p in item[1:]]
            new_items.append((op, *[_Pt(px, py) for px, py in pts]))
        new_d = dict(d)
        new_d["items"] = new_items
        if d.get("rect") is not None:
            xs = [p.x for it in new_items for p in it[1:]]
            ys = [p.y for it in new_items for p in it[1:]]
            new_d["rect"] = _Rect(min(xs), min(ys), max(xs), max(ys))
        out.append(new_d)
    return out


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rotate90": True},
        {"dx": 500.0, "dy": -300.0},
        {"scale": 0.5},
        {"scale": 2.0},
    ],
    ids=["rotate90", "translate", "scale_half", "scale_double"],
)
def test_metamorphic_transforms_preserve_classification_and_span_ratio(kwargs):
    base_drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    base_drawings.append(_door_swing_arc(200.0, 100.0, 30.0))
    base_scale = 25.0

    # A rotation or a negative translation can carry real geometry outside
    # the FakePage's default (0,0,2000,2000) rect -- an explicit, generous
    # viewport avoids that being mistaken for the transform itself failing.
    big_viewport = (-2000.0, -2000.0, 2000.0, 2000.0)

    base_page = _FakePage(base_drawings)
    base_ev = resolve_hosted_opening_spans(base_page, viewport_bbox=big_viewport, scale_authority=base_scale)
    assert base_ev.status == "found"
    base = base_ev.openings[0]

    scale_factor = kwargs.get("scale", 1.0)
    transformed = _transform_drawings(base_drawings, **kwargs)
    transformed_page = _FakePage(transformed)
    transformed_scale = base_scale * scale_factor
    ev = resolve_hosted_opening_spans(transformed_page, viewport_bbox=big_viewport, scale_authority=transformed_scale)

    assert ev.status == "found", f"abstained after transform {kwargs}"
    o = ev.openings[0]
    assert o.subtype == base.subtype
    assert abs(o.span_pt - base.span_pt * scale_factor) < 0.5 * max(scale_factor, 1.0)
    assert abs((o.span_pt / o.wall_thickness_pt) - (base.span_pt / base.wall_thickness_pt)) < 0.1
    assert o.width_m is not None and abs(o.width_m - base.width_m) < 0.05


# ---------------------------------------------------------------------------
# Mandatory negatives
# ---------------------------------------------------------------------------


def test_dimension_line_is_not_a_hosted_opening():
    """A single long thin reference/dimension line with witness ticks --
    no paired second face at all -- must never resolve as a wall band."""
    drawings = [
        _line(100.0, 500.0, 400.0, 500.0, color=(0.5, 0.5, 0.5)),
        _line(100.0, 495.0, 100.0, 505.0, color=(0.5, 0.5, 0.5)),
        _line(400.0, 495.0, 400.0, 505.0, color=(0.5, 0.5, 0.5)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_dashed_grid_line_pair_is_rejected_as_host_wall():
    """Two parallel rows built from many short, regularly-repeating
    dash-simulated segments (a common CAD grid-centreline convention) must
    not be mistaken for a real wall band, regardless of any incidental
    aligned gap between them."""
    drawings = []
    y0, y1 = 100.0, 106.0
    x = 100.0
    while x < 500.0:
        drawings.append(_line(x, y0, x + 12.0, y0, color=(0.6, 0.6, 0.6)))
        drawings.append(_line(x, y1, x + 12.0, y1, color=(0.6, 0.6, 0.6)))
        x += 20.0
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_furniture_rectangle_is_not_a_hosted_opening():
    """A small stroked rectangle (e.g. a desk outline) has short parallel
    edges far below the minimum wall-band run and must not register."""
    drawings = [
        _line(100.0, 100.0, 130.0, 100.0, color=(0.0, 0.0, 0.0)),
        _line(100.0, 120.0, 130.0, 120.0, color=(0.0, 0.0, 0.0)),
        _line(100.0, 100.0, 100.0, 120.0, color=(0.0, 0.0, 0.0)),
        _line(130.0, 100.0, 130.0, 120.0, color=(0.0, 0.0, 0.0)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_title_block_border_rectangle_is_not_a_hosted_opening():
    """A page-spanning border rectangle has long, parallel, far-apart
    edges -- but the perpendicular distance between them is nowhere near a
    plausible wall thickness."""
    drawings = [
        _line(10.0, 10.0, 10.0, 1180.0, color=(0.0, 0.0, 0.0)),
        _line(830.0, 10.0, 830.0, 1180.0, color=(0.0, 0.0, 0.0)),
        _line(10.0, 10.0, 830.0, 10.0, color=(0.0, 0.0, 0.0)),
        _line(10.0, 1180.0, 830.0, 1180.0, color=(0.0, 0.0, 0.0)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_hatch_strokes_only_wall_abstains_cleanly():
    """A wall represented purely as short diagonal hatch ticks (no long
    bounding lines, no fill) has no evidence channel in this module at all
    -- it must abstain, not crash or invent a band from the ticks."""
    drawings = []
    x = 100.0
    while x < 300.0:
        drawings.append(_line(x, 100.0, x + 6.0, 108.0, color=(0.0, 0.0, 0.0), width=0.3))
        x += 9.6
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_wall_t_junction_is_not_misread_as_an_opening():
    """A perpendicular wall meeting a straight run creates a real vertical
    stroke crossing the wall thickness, but there is no genuine gap in
    either face line there -- must not register as a hosted opening."""
    y0, y1 = 100.0, 106.0
    drawings = [
        _line(100.0, y0, 400.0, y0, color=(0.5, 0.5, 0.5)),
        _line(100.0, y1, 400.0, y1, color=(0.5, 0.5, 0.5)),
        # perpendicular wall running down from the junction at x=250
        _line(250.0, y1, 250.0, 300.0, color=(0.5, 0.5, 0.5)),
        _line(256.0, y1, 256.0, 300.0, color=(0.5, 0.5, 0.5)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_paired_short_lines_not_hosted_by_a_wall_are_rejected():
    """Two short parallel verticals with nothing establishing them as
    within any real wall band (no matching horizontal faces at all) must
    not be treated as jambs of anything."""
    drawings = [
        _line(200.0, 100.0, 200.0, 106.0, color=(0.0, 0.0, 0.0)),
        _line(260.0, 100.0, 260.0, 106.0, color=(0.0, 0.0, 0.0)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_jamb_pair_with_only_one_wall_face_is_rejected():
    """Only ONE long face line exists (no matching parallel second face at
    a plausible wall thickness) -- a real gap on this single line is not
    sufficient; a hosted opening requires both faces confirming it."""
    y0 = 100.0
    drawings = [
        _line(100.0, y0, 200.0, y0, color=(0.5, 0.5, 0.5)),
        _line(260.0, y0, 400.0, y0, color=(0.5, 0.5, 0.5)),
        _line(200.0, y0, 200.0, y0 + 6.0, color=(0.0, 0.0, 0.0)),
        _line(260.0, y0, 260.0, y0 + 6.0, color=(0.0, 0.0, 0.0)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_candidate_crossing_two_possible_host_walls_abstains():
    """A horizontal wall band and a vertical wall band whose real-space
    extents genuinely overlap (the same small rectangle reads as either
    wall's own opening) must both be dropped -- neither can be trusted as
    belonging to one unambiguous host wall."""
    drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    # A vertical wall band whose own gap is exactly the horizontal wall's
    # thickness band (y=100-106), positioned inside the horizontal wall's
    # gap range (x=200-260) -- the rectangle (225-231, 100-106) is
    # genuinely ambiguous between the two walls.
    x0, x1 = 225.0, 231.0
    drawings += [
        _fill_rect(x0, 40.0, x1, 95.0),
        _fill_rect(x0, 111.0, x1, 200.0),
        _line(x0 + 1.0, 40.0, x0 + 1.0, 200.0, color=(0.0, 0.0, 0.0)),
    ]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    for o in ev.openings:
        # Neither the conflicted horizontal nor the conflicted vertical
        # candidate should survive.
        overlapping = (
            o.host_orientation_deg == 0.0 and o.jamb_start[0] <= x1 and x0 <= o.jamb_end[0]
        ) or (
            o.host_orientation_deg == 90.0 and o.jamb_start[1] <= 111.0 and 95.0 <= o.jamb_end[1]
        )
        assert not overlapping


def test_door_swing_without_valid_wall_host_is_rejected():
    """A door-swing arc sitting in isolation, with no confirmed wall band
    at all nearby, must not produce a hosted-opening result."""
    drawings = [_door_swing_arc(100.0, 100.0, 30.0)]
    ev = resolve_hosted_opening_spans(_FakePage(drawings), scale_authority=25.0)
    assert ev.status == "abstained"


def test_repeated_motif_outside_viewport_is_excluded():
    """A real, valid hosted opening that sits entirely outside the given
    viewport_bbox must not be found -- viewport scoping is authoritative."""
    drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    ev = resolve_hosted_opening_spans(
        _FakePage(drawings), viewport_bbox=(1000.0, 1000.0, 1500.0, 1500.0), scale_authority=25.0
    )
    assert ev.status == "abstained"
