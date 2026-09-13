"""Regression tests for pb_hosted_opening_geometry.

Mandatory real-fixture tests use the Baghau Primary School single-classroom
drawing (benchmarks/sources/bq_and_drawing_1747803602496.pdf, page index
35 / "page 36") and the Dungicha 3-classroom block drawing (benchmarks/
sources/dungicha_3classrooms.pdf, page index 133 / "page 134") -- both
confirmed present after the earlier "genuinely unavailable" finding was
corrected once the exact files were placed in benchmarks/sources/.

Baghau's floor plan draws masonry as a field of short 45-degree hatch
ticks between two continuous wall-face lines (the ticks are the only
`material' evidence -- the boundary lines themselves never break at an
opening, since the opening's own frame sits flush with the wall face).
It shows all 3 of its real WD-01 windows (north wall, "at least three
repeated" per the original brief), both WD-02 windows (classroom/
verandah wall), and the real DR-01 door with a jamb-anchored swing arc --
each independently hand-verified against the drawing's own schedule text
this session (2,000x1,500 / 2,000x900 / 1,500x2,400), never used to derive
the geometry.

Dungicha's floor plan uses the same hatch-tick wall convention and shows
11 repeated real W1-like window voids (span 42.52pt = 1.500m at this
sheet's own 28.35pt/m scale, matching the "1,500" figured dimension next
to each) along the classroom block's front wall -- the module reports
only span/subtype, never the "W1" tag text itself, so type-mark identity
is correctly absent from the API by construction. Dungicha's own door
(schedule not parsed here, but a real quarter-circle swing arc was found
by pb_plan_door_swing_geometry near its corner post) turned out to sit on
a wall segment whose hatch-tick pattern runs fully continuous straight
through the door's own real-space location -- a third, distinct
convention from Baghau's and Lamu's (neither a face-line gap nor a
hatch-tick gap marks the opening; only the swing arc's mere presence
does). This module deliberately does NOT add an "arc alone, regardless of
any wall-material evidence" rule to catch it: that signal is far weaker
and far more prone to false positives than every other channel here (it
would fire on any door swing found merely near any wall, with no
independent confirmation the wall material actually changes), which is
exactly the class of overly permissive shortcut this module's development
already tried and discarded twice for KSTVET. Dungicha's door is recorded
here as a second honest, documented limitation alongside KSTVET's.

Lamu and KSTVET fixtures are kept as supplementary real evidence (Lamu's
solid-fill-pier convention and door distinguishing; KSTVET's jamb-box
flush-frame limitation) -- no longer the primary/substitute real fixtures
now that Baghau and Dungicha are available, per explicit instruction.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import pytest

fitz = pytest.importorskip("fitz")

from pb_hosted_opening_geometry import resolve_hosted_opening_spans

_BAGHAU_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "bq_and_drawing_1747803602496.pdf"
)
_BAGHAU_PLAN_PAGE_INDEX = 35
_BAGHAU_SCALE_PT_PER_M = 28.3

_DUNGICHA_PDF = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "sources"
    / "dungicha_3classrooms.pdf"
)
_DUNGICHA_PLAN_PAGE_INDEX = 133
_DUNGICHA_SCALE_PT_PER_M = 28.35

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
# CI-reproducible native-vector snapshots (never skip -- see
# scripts/export_hosted_opening_vector_fixture.py for how these were
# produced and why: benchmarks/sources/ is gitignored repo-wide and no source PDF
# has ever been committed under any existing policy, so a clean clone/CI
# cannot run the real-PDF tests above at all; these committed JSON
# snapshots close that gap without committing the PDFs themselves).
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "hosted_opening_geometry"
_BAGHAU_SNAPSHOT_PATH = _FIXTURES_DIR / "baghau_p36.json"
_DUNGICHA_SNAPSHOT_PATH = _FIXTURES_DIR / "dungicha_p134.json"


def _load_snapshot(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _snapshot_page(snapshot: dict):
    """Reconstruct a _FakePage from an exported snapshot's raw drawings --
    same 'l'/'c' item shapes, color/fill/width/rect, that a real
    fitz.Page.get_drawings() would return, so resolve_hosted_opening_spans
    runs its identical, unmodified code path against it."""
    drawings = []
    for d in snapshot["drawings"]:
        items = []
        for item in d["items"]:
            op = item[0]
            items.append((op, *[_Pt(x, y) for x, y in item[1:]]))
        drawings.append(
            {
                "color": tuple(d["color"]) if d["color"] is not None else None,
                "fill": tuple(d["fill"]) if d["fill"] is not None else None,
                "width": d["width"],
                "rect": _Rect(*d["rect"]) if d["rect"] is not None else None,
                "items": items,
            }
        )
    page_rect = _Rect(*snapshot["page_rect"])
    return _FakePage(drawings, rect=page_rect, number=snapshot["source"]["pdf_page_0based"])


def _assert_snapshot_provenance(snapshot: dict, *, expected_pdf_sha256: str, expected_page_0based: int) -> None:
    src = snapshot["source"]
    assert src["pdf_sha256"] == expected_pdf_sha256, "snapshot was not generated from the stated source PDF"
    assert src["pdf_page_0based"] == expected_page_0based
    assert snapshot["schema_version"] >= 1
    assert src["generator"] == "scripts/export_hosted_opening_vector_fixture.py"


_BAGHAU_PDF_SHA256 = "1621f411597f5aac2bb7a6109db8d3e15d370dd642c95ad5aa25c51aa84803c1"
_DUNGICHA_PDF_SHA256 = "62013d17dbf84d5459345ddde8feaf0d5c48e57728c4f087ee36ff3fafcf9a56"


def test_baghau_snapshot_north_wall_three_repeated_windows_never_skips():
    snapshot = _load_snapshot(_BAGHAU_SNAPSHOT_PATH)
    _assert_snapshot_provenance(snapshot, expected_pdf_sha256=_BAGHAU_PDF_SHA256, expected_page_0based=35)
    page = _snapshot_page(snapshot)

    ev = resolve_hosted_opening_spans(page, viewport_bbox=(440, 440, 880, 500), scale_authority=28.3)
    assert ev.status == "found"
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    assert len(windows) == 3
    for w in windows:
        assert not hasattr(w, "tag") and not hasattr(w, "type_mark") and not hasattr(w, "identity")
        assert 1.9 <= w.width_m <= 2.1  # already-observed range from the real-PDF run


def test_baghau_snapshot_full_wall_area_five_windows_one_door_never_skips():
    snapshot = _load_snapshot(_BAGHAU_SNAPSHOT_PATH)
    _assert_snapshot_provenance(snapshot, expected_pdf_sha256=_BAGHAU_PDF_SHA256, expected_page_0based=35)
    page = _snapshot_page(snapshot)

    ev = resolve_hosted_opening_spans(page, viewport_bbox=(440, 440, 880, 760), scale_authority=28.3)
    assert ev.status == "found"
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    doors = [o for o in ev.openings if o.subtype == "door_like"]
    assert len(windows) == 5
    assert len(doors) == 1
    assert 1.4 <= doors[0].width_m <= 1.6
    for o in ev.openings:
        assert not hasattr(o, "tag") and not hasattr(o, "type_mark") and not hasattr(o, "identity")


def test_dungicha_snapshot_repeated_windows_stable_and_deduped_never_skips():
    snapshot = _load_snapshot(_DUNGICHA_SNAPSHOT_PATH)
    _assert_snapshot_provenance(snapshot, expected_pdf_sha256=_DUNGICHA_PDF_SHA256, expected_page_0based=133)
    page = _snapshot_page(snapshot)

    ev = resolve_hosted_opening_spans(page, viewport_bbox=(60, 600, 800, 780), scale_authority=28.35)
    assert ev.status == "found"
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    assert len(windows) == 11  # stable, exact count against the committed snapshot
    # Dedup: no two windows share near-identical jamb positions.
    seen = []
    for w in windows:
        for other in seen:
            assert not (
                abs(w.jamb_start[0] - other.jamb_start[0]) < w.wall_thickness_pt
                and abs(w.jamb_end[0] - other.jamb_end[0]) < w.wall_thickness_pt
            ), "duplicate opening reported for the same physical window"
        seen.append(w)
        assert 1.4 <= w.width_m <= 1.6  # figured "1,500" next to each W1 tag


def test_dungicha_snapshot_door_region_fail_closed_never_skips():
    snapshot = _load_snapshot(_DUNGICHA_SNAPSHOT_PATH)
    _assert_snapshot_provenance(snapshot, expected_pdf_sha256=_DUNGICHA_PDF_SHA256, expected_page_0based=133)
    page = _snapshot_page(snapshot)

    ev = resolve_hosted_opening_spans(page, viewport_bbox=(90, 790, 145, 870), scale_authority=28.35)
    for o in ev.openings:
        assert o.subtype != "door_like"


@pytest.mark.parametrize(
    "real_pdf,page_index,snapshot_path,viewport,scale",
    [
        (
            _BAGHAU_PDF,
            35,
            _BAGHAU_SNAPSHOT_PATH,
            (440, 440, 880, 760),
            28.3,
        ),
        (
            _DUNGICHA_PDF,
            133,
            _DUNGICHA_SNAPSHOT_PATH,
            (60, 600, 800, 780),
            28.35,
        ),
    ],
    ids=["baghau_full_wall_area", "dungicha_front_wall"],
)
def test_real_pdf_and_snapshot_agree_when_pdf_present(real_pdf, page_index, snapshot_path, viewport, scale):
    """Parity gate: when the real PDF genuinely is available (e.g. locally,
    or in an environment that has copied benchmarks/sources/ in), its live
    output and the committed snapshot's output must agree. The real-PDF
    side may skip when the source is genuinely unavailable; the snapshot
    side (exercised by the four never-skip tests above) never does."""
    if not real_pdf.exists():
        pytest.skip(f"real source PDF not present locally: {real_pdf} (snapshot-only parity cannot be checked)")

    doc = fitz.open(str(real_pdf))
    try:
        real_page = doc[page_index]
        real_ev = resolve_hosted_opening_spans(real_page, viewport_bbox=viewport, scale_authority=scale)
    finally:
        doc.close()

    snapshot_ev = resolve_hosted_opening_spans(
        _snapshot_page(_load_snapshot(snapshot_path)), viewport_bbox=viewport, scale_authority=scale
    )

    assert real_ev.status == snapshot_ev.status
    assert len(real_ev.openings) == len(snapshot_ev.openings)

    def _key(o):
        return (o.host_orientation_deg, round(o.jamb_start[0], 0), round(o.jamb_start[1], 0))

    real_sorted = sorted(real_ev.openings, key=_key)
    snap_sorted = sorted(snapshot_ev.openings, key=_key)
    for r, s in zip(real_sorted, snap_sorted):
        assert r.subtype == s.subtype
        assert r.host_orientation_deg == s.host_orientation_deg
        assert abs(r.span_pt - s.span_pt) < 0.5
        assert set(r.evidence_flags) == set(s.evidence_flags)


@pytest.mark.parametrize(
    "spec_name",
    ["baghau_p36", "dungicha_p134"],
)
def test_exporter_is_deterministic(spec_name):
    """Running the exporter twice against the same source/page/viewport
    must produce canonically identical fixture content -- no timestamps,
    no UUIDs, no non-deterministic ordering. Runs directly against the
    real source PDF (skips if genuinely unavailable, matching the
    real-PDF tests elsewhere in this file); the already-committed
    snapshot files were themselves produced by two such runs agreeing
    during this module's own development, which is how this property was
    first verified."""
    from scripts.export_hosted_opening_vector_fixture import _SPECS, _serialise, export_page_snapshot

    spec = next(s for s in _SPECS if s["name"] == spec_name)
    if not spec["pdf_path"].exists():
        pytest.skip(f"real source PDF not present locally: {spec['pdf_path']}")

    kwargs = {k: v for k, v in spec.items() if k != "name"}
    first = _serialise(export_page_snapshot(**kwargs))
    second = _serialise(export_page_snapshot(**kwargs))
    assert first == second, "exporter output was not byte-identical across two runs"


# ---------------------------------------------------------------------------
# Mandatory real fixtures: Baghau (p36) and Dungicha (p134)
# ---------------------------------------------------------------------------


def test_baghau_north_wall_finds_all_three_repeated_windows():
    doc, page = _load_page(_BAGHAU_PDF, _BAGHAU_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(440, 440, 880, 500), scale_authority=_BAGHAU_SCALE_PT_PER_M
        )
    finally:
        doc.close()

    assert ev.status == "found"
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    assert len(windows) == 3
    for w in windows:
        assert "diagonal_hatch_tick_gap" in w.evidence_flags
        assert "jamb_boundaries_confirmed" in w.evidence_flags
        assert w.width_m is not None
        # WD-01 schedule: 2,000mm wide.
        assert 1.9 <= w.width_m <= 2.1


def test_baghau_classroom_verandah_wall_finds_windows_and_door():
    doc, page = _load_page(_BAGHAU_PDF, _BAGHAU_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(440, 440, 880, 760), scale_authority=_BAGHAU_SCALE_PT_PER_M
        )
    finally:
        doc.close()

    assert ev.status == "found"
    doors = [o for o in ev.openings if o.subtype == "door_like"]
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    # 3 WD-01 (north wall) + 2 WD-02 (classroom/verandah wall).
    assert len(windows) == 5
    assert len(doors) == 1
    door = doors[0]
    assert "jamb_anchored_door_swing" in door.evidence_flags
    # DR-01 schedule: 1,500mm wide -- and narrower than every window here.
    assert door.width_m is not None
    assert 1.4 <= door.width_m <= 1.6
    assert door.width_m < min(w.width_m for w in windows)


def test_dungicha_front_wall_finds_repeated_w1_windows_without_identity():
    doc, page = _load_page(_DUNGICHA_PDF, _DUNGICHA_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(60, 600, 800, 780), scale_authority=_DUNGICHA_SCALE_PT_PER_M
        )
    finally:
        doc.close()

    assert ev.status == "found"
    windows = [o for o in ev.openings if o.subtype == "window_like"]
    # At least the "multiple repeated" W1-like geometries required by the
    # brief -- 11 were found in this viewport at the time of writing.
    assert len(windows) >= 8
    spans = {round(w.span_pt, 1) for w in windows}
    assert len(spans) <= 2, f"expected one consistent repeated span, got {spans}"
    for w in windows:
        assert w.width_m is not None
        assert 1.4 <= w.width_m <= 1.6  # figured "1,500" next to each W1 tag
        # The API has no field a type-mark identity could occupy -- this
        # assertion documents that "W1" is structurally unrepresentable,
        # not merely unpopulated.
        assert not hasattr(w, "tag")
        assert not hasattr(w, "type_mark")
        assert not hasattr(w, "identity")


def test_dungicha_repeated_windows_stable_under_bbox_perturbation():
    """Real-fixture bbox-sensitivity regression (Phase 9 of the local-
    component audit): expanding the viewport must only ever ADD a window
    with an identical signature to its siblings (never mutate an existing
    one), and contracting must only ever cleanly drop the one window whose
    own evidence is clipped (never touch the others) -- confirmed for the
    Gap Chain Rule fix by an exhaustive mechanical perturbation matrix
    during that audit; this locks in the two most informative points from
    it (a real 12th window becoming visible on expansion; the first window
    cleanly dropping on left contraction) as a permanent check."""
    base_bbox = (60, 600, 800, 780)

    def _signature(ev):
        return sorted(
            (o.subtype, round(o.jamb_start[0], 1), round(o.jamb_end[0], 1), round(o.span_pt, 1))
            for o in ev.openings
        )

    doc, page = _load_page(_DUNGICHA_PDF, _DUNGICHA_PLAN_PAGE_INDEX)
    try:
        base_ev = resolve_hosted_opening_spans(
            page, viewport_bbox=base_bbox, scale_authority=_DUNGICHA_SCALE_PT_PER_M
        )
        base_sig = _signature(base_ev)
        assert len(base_sig) == 11

        x0, y0, x1, y1 = base_bbox
        w = x1 - x0
        expanded_bbox = (x0 - w * 0.05, y0, x1 + w * 0.05, y1)
        expanded_ev = resolve_hosted_opening_spans(
            page, viewport_bbox=expanded_bbox, scale_authority=_DUNGICHA_SCALE_PT_PER_M
        )
        expanded_sig = _signature(expanded_ev)
        assert len(expanded_sig) == 12
        assert set(base_sig).issubset(set(expanded_sig)), (
            "expansion must only add a window, never mutate an existing one -- "
            f"lost or changed: {set(base_sig) - set(expanded_sig)}"
        )

        contracted_bbox = (x0 + w * 0.10, y0, x1, y1)
        contracted_ev = resolve_hosted_opening_spans(
            page, viewport_bbox=contracted_bbox, scale_authority=_DUNGICHA_SCALE_PT_PER_M
        )
        contracted_sig = _signature(contracted_ev)
        assert len(contracted_sig) == 10
        assert set(contracted_sig).issubset(set(base_sig)), (
            "contraction must only drop windows, never mutate a surviving one -- "
            f"unexpected: {set(contracted_sig) - set(base_sig)}"
        )
    finally:
        doc.close()


def test_dungicha_door_area_is_a_documented_limitation_not_a_crash():
    """Dungicha's own door sits on a wall whose hatch-tick pattern runs
    fully continuous straight through the door's real-space location --
    neither a face-line gap nor a hatch-tick gap marks it, only the swing
    arc's mere presence does. This module deliberately does not add an
    "arc alone" rule (far weaker and more false-positive-prone than every
    other channel here) to catch this specific case. The requirement this
    test locks in is narrower and still meaningful: scanning directly over
    a real door-swing arc with no corroborating wall-material interruption
    must abstain (or find only genuinely separate, unrelated openings),
    never crash, and never emit a confident but evidence-less door_like
    result for this exact span."""
    doc, page = _load_page(_DUNGICHA_PDF, _DUNGICHA_PLAN_PAGE_INDEX)
    try:
        ev = resolve_hosted_opening_spans(
            page, viewport_bbox=(90, 790, 145, 870), scale_authority=_DUNGICHA_SCALE_PT_PER_M
        )
    finally:
        doc.close()
    # Either abstains outright, or (if some unrelated nearby geometry
    # happens to qualify) does not fabricate a door_like reading for the
    # arc's own real-space span without a genuine material interruption.
    for o in ev.openings:
        assert o.subtype != "door_like"


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


# ---------------------------------------------------------------------------
# Viewport-bbox sensitivity regression (found auditing real Baghau behavior
# under an automatically-resolved, rather than hand-picked, viewport bbox).
# ---------------------------------------------------------------------------


def _opening_signature(o):
    return (o.subtype, o.jamb_start, o.jamb_end, round(o.span_pt, 3), o.evidence_flags)


def test_unrelated_far_fragment_sharing_a_face_y_does_not_erase_a_real_opening():
    """A real hosted opening must not disappear merely because the caller's
    viewport_bbox grows to also include a spatially disconnected, entirely
    unrelated fragment elsewhere on the page that happens to share this
    wall band's exact y-coordinate.

    Root cause (confirmed by direct instrumentation before fixing):
    _is_credible_wall_face's span_lo/span_hi used to be the row's GLOBAL
    min/max coverage extent. A single small fragment far away in x, sharing
    a face's y-coordinate purely by coincidence, could drag span_hi out by
    thousands of points while contributing almost no covered length,
    collapsing the coverage-fraction ratio for the ENTIRE row (including
    the real opening nowhere near that fragment) below
    _MIN_BAND_COVERAGE_FRACTION and rejecting it as "not a credible wall
    face". A real, minimal, first-of-its-kind end-to-end run against real
    Baghau drawing data with an automatically-resolved (not hand-picked)
    viewport bbox is what first surfaced this pattern."""
    left_pier = _fill_rect(180.0, 100.0, 200.0, 106.0)
    right_pier = _fill_rect(260.0, 100.0, 320.0, 106.0)
    glazing = _line(205.0, 101.0, 255.0, 101.0, color=(0.0, 0.0, 0.0))
    far_unrelated_fragment = _fill_rect(2000.0, 100.0, 2020.0, 106.0)
    drawings = [left_pier, right_pier, glazing, far_unrelated_fragment]

    tight_bbox = (170.0, 90.0, 330.0, 116.0)  # excludes the far fragment
    wide_bbox = (170.0, 90.0, 2050.0, 116.0)  # includes it; real evidence unchanged

    ev_tight = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=tight_bbox, scale_authority=25.0)
    ev_wide = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=wide_bbox, scale_authority=25.0)

    assert ev_tight.status == "found" and len(ev_tight.openings) == 1
    assert ev_wide.status == "found" and len(ev_wide.openings) == 1
    assert _opening_signature(ev_tight.openings[0]) == _opening_signature(ev_wide.openings[0])
    assert ev_wide.openings[0].subtype == "window_like"


def test_far_fragment_does_not_corrupt_diagonal_hatch_tick_channel_either():
    """The same class of defect, for the diagonal-hatch-tick-gap channel:
    both channels shared the same vulnerable global-span credibility gate
    before the fix."""

    def _tick(x, y0, y1):
        return _line(x, y0, x + 10.0, y1, color=(0.0, 0.0, 0.0), width=0.3)

    y0, y1 = 100.0, 110.0
    xs_before = [0.0, 14.0, 28.0, 42.0]
    xs_after = [76.0, 90.0, 104.0, 118.0]
    drawings = [
        _line(-20.0, y0, 148.0, y0, color=(0.0, 0.0, 0.0), width=0.75),
        _line(-20.0, y1, 148.0, y1, color=(0.0, 0.0, 0.0), width=0.75),
    ]
    for x in xs_before + xs_after:
        drawings.append(_tick(x, y0, y1))
    drawings.append(_line(52.0, y0, 52.0, y1, color=(0.0, 0.0, 0.0), width=0.5))
    drawings.append(_line(76.0, y0, 76.0, y1, color=(0.0, 0.0, 0.0), width=0.5))
    drawings.append(_line(54.0, (y0 + y1) / 2.0, 74.0, (y0 + y1) / 2.0, color=(0.0, 0.0, 0.0), width=0.3))
    far_unrelated_fragment = _fill_rect(2000.0, y0, 2020.0, y1)
    drawings_with_far = drawings + [far_unrelated_fragment]

    tight_bbox = (-40.0, 80.0, 170.0, 130.0)
    wide_bbox = (-40.0, 80.0, 2050.0, 130.0)

    ev_tight = resolve_hosted_opening_spans(_FakePage(drawings_with_far), viewport_bbox=tight_bbox, scale_authority=25.0)
    ev_wide = resolve_hosted_opening_spans(_FakePage(drawings_with_far), viewport_bbox=wide_bbox, scale_authority=25.0)

    assert ev_tight.status == "found" and len(ev_tight.openings) == 1
    assert ev_wide.status == "found" and len(ev_wide.openings) == 1
    assert _opening_signature(ev_tight.openings[0]) == _opening_signature(ev_wide.openings[0])
    assert "diagonal_hatch_tick_gap" in ev_wide.openings[0].evidence_flags


@pytest.mark.parametrize(
    "bbox",
    [
        (170.0, 90.0, 330.0, 116.0),  # base
        (166.6, 88.7, 333.4, 117.3),  # +2% expansion
        (162.5, 86.5, 337.5, 119.5),  # +5% expansion
        (173.2, 91.3, 326.8, 114.7),  # -2% contraction
        (171.6, 90.65, 331.6, 116.65),  # translate right/down ~1%
        (168.4, 89.35, 328.4, 115.35),  # translate left/up ~1%
    ],
)
def test_translation_expansion_contraction_invariance_aligned_two_face_gap(bbox):
    """Small, mechanically-derived expansions/contractions/translations of
    a viewport bbox that keep all of a real opening's own evidence fully
    inside must never change its presence, subtype, geometry, or evidence
    flags."""
    drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    base_ev = resolve_hosted_opening_spans(
        _FakePage(drawings), viewport_bbox=(170.0, 90.0, 330.0, 116.0), scale_authority=25.0
    )
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "found" and len(ev.openings) == 1
    assert _opening_signature(ev.openings[0]) == _opening_signature(base_ev.openings[0])


def test_cropping_away_one_wall_face_aborts_rather_than_invents():
    """Genuinely removing required evidence (here: the entire right pier)
    must abstain, never invent a different opening or silently keep a
    result built on partial evidence."""
    drawings = _two_pier_fill_wall_with_window(200.0, 200.0, 260.0, 300.0)
    ev = resolve_hosted_opening_spans(
        _FakePage(drawings), viewport_bbox=(170.0, 90.0, 245.0, 116.0), scale_authority=25.0
    )
    assert ev.status == "abstained"
    assert ev.openings == ()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the Gap Chain Rule fix (see _local_credibility_window) resolves "
        "the marginal-gap-borrowing half of this -- the 10pt gap is no "
        "longer manufactured -- but the 150pt gap between the second pier "
        "and the fragment is now found DIRECTLY: its own two immediate "
        "flanking pieces already satisfy _MIN_BAND_RUN_PT with no extra hop "
        "needed, which is structurally indistinguishable from a genuine "
        "wide doorway given this data model alone (same class of ambiguity "
        "as defect 2, not a Gap Chain Rule defect -- see the audit report)"
    ),
)
def test_distant_long_fragment_must_not_manufacture_credibility_for_a_marginal_gap():
    """_local_credibility_window (added to fix the far-fragment defect
    above) walks outward from a candidate gap, pulling in whichever
    interval is nearest on each side, until it accumulates at least
    _MIN_BAND_RUN_PT of span -- with no bound on how FAR that walk is
    allowed to reach. This checks whether that absence of a distance bound
    lets a distant, unrelated fragment manufacture credibility for a
    candidate that has nowhere near enough real LOCAL evidence on its own,
    merely because the fragment happens to be long enough to satisfy the
    coverage-fraction ratio once absorbed.

    Two 20pt piers with a 10pt gap between them (thickness 6pt) have only
    50pt of real, immediate local coverage on each face -- short of
    _MIN_BAND_RUN_PT (60pt) on their own, so a tight viewport containing
    only this structure must correctly abstain (asserted below as a
    control). A third, 40pt-long fragment placed 150pt further along the
    same two faces -- clearly a separate, disconnected piece of geometry,
    not part of the same local wall run by any reasonable reading -- must
    not change that outcome merely because a wider viewport also includes
    it and the walk-outward helper is willing to reach that far to hit its
    span target.
    """
    y0, y1 = 100.0, 106.0
    left_pier = _fill_rect(0.0, y0, 20.0, y1)
    right_pier = _fill_rect(30.0, y0, 50.0, y1)
    base_drawings = [left_pier, right_pier]

    tight_bbox = (-10.0, 90.0, 60.0, 116.0)
    ev_tight = resolve_hosted_opening_spans(_FakePage(base_drawings), viewport_bbox=tight_bbox, scale_authority=25.0)
    assert ev_tight.status == "abstained"
    assert ev_tight.openings == ()

    far_fragment = _fill_rect(200.0, y0, 240.0, y1)  # 150pt beyond the right pier, 40pt long
    drawings = base_drawings + [far_fragment]
    wide_bbox = (-10.0, 90.0, 250.0, 116.0)
    ev_wide = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=wide_bbox, scale_authority=25.0)

    marginal_gap = next(
        (o for o in ev_wide.openings if o.jamb_start[0] == 20.0 and o.jamb_end[0] == 30.0), None
    )
    assert marginal_gap is None, (
        "the 10pt gap between the two short piers must not become a hosted "
        f"opening merely because a distant, unrelated fragment let the local "
        f"credibility window reach _MIN_BAND_RUN_PT; got {marginal_gap!r} "
        f"among {ev_wide.openings!r}"
    )

    synthetic_gap_to_fragment = next(
        (o for o in ev_wide.openings if o.jamb_start[0] == 50.0 and o.jamb_end[0] == 200.0), None
    )
    assert synthetic_gap_to_fragment is None, (
        "the 150pt real gap between the right pier and the distant, "
        f"unrelated fragment must not itself be manufactured into a hosted "
        f"opening either; got {synthetic_gap_to_fragment!r} among {ev_wide.openings!r}"
    )

    assert ev_wide.status == "abstained" and ev_wide.openings == (), (
        "this fixture has no genuine hosted opening at all once the distant "
        f"fragment is present -- the correct result is a clean abstention, "
        f"not any combination of the marginal gap and/or the synthetic gap "
        f"to the fragment; got status={ev_wide.status!r} openings={ev_wide.openings!r}"
    )

# ---------------------------------------------------------------------------
# Gap Chain Rule invariant matrix (A-J): principled locality bound for
# _local_credibility_window. See pb_hosted_opening_geometry.py's own
# docstring on _local_credibility_window for the precise rule. Every case
# below is independent of project names, benchmark values, or fixture
# coordinates from any real drawing -- purely synthetic, purely structural.
# ---------------------------------------------------------------------------


def _pier_wall_with_gap(pier1_len, gap_len, pier2_len, *, y0=100.0, thickness=6.0, x0=0.0):
    """One real two-face-fill wall band: pier1 -- gap -- pier2, all at the
    same y0/thickness. Returns (drawings, gap_lo, gap_hi)."""
    y1 = y0 + thickness
    p1_lo, p1_hi = x0, x0 + pier1_len
    gap_lo, gap_hi = p1_hi, p1_hi + gap_len
    p2_lo, p2_hi = gap_hi, gap_hi + pier2_len
    drawings = [_fill_rect(p1_lo, y0, p1_hi, y1), _fill_rect(p2_lo, y0, p2_hi, y1)]
    return drawings, gap_lo, gap_hi


def test_locality_a_valid_local_wall_is_found():
    """A: long piers on each side of a real gap -- ample immediate local
    coverage, no extra hop ever needed. Must be found."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(150.0, 40.0, 150.0)
    bbox = (-20.0, 90.0, 360.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "found" and len(ev.openings) == 1
    o = ev.openings[0]
    assert (o.jamb_start[0], o.jamb_end[0]) == (gap_lo, gap_hi)


def test_locality_b_marginal_local_wall_abstains_alone():
    """B: two short piers, insufficient immediate local coverage (50pt <
    _MIN_BAND_RUN_PT) with nothing else nearby at all. Must abstain."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(20.0, 10.0, 20.0)
    bbox = (-10.0, 90.0, 60.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "abstained"
    assert ev.openings == ()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the Gap Chain Rule fix resolves the marginal-borrowing half of this "
        "(the 10pt gap is no longer manufactured), but the 150pt gap between "
        "pier2 and the fragment is now found DIRECTLY -- its own two "
        "immediate flanking pieces (pier2, fragment) already satisfy "
        "_MIN_BAND_RUN_PT with zero extra hops, which is indistinguishable, "
        "by any evidence this two-interval-and-a-gap data model carries, "
        "from test_locality_g's genuine wide doorway (structurally identical "
        "fixture shape). This is the same class of ambiguity as defect 2 "
        "(two coincidentally-aligned real structures read as one wall band), "
        "not a bug in the Gap Chain Rule itself -- see the final report."
    ),
)
def test_locality_c_distant_unrelated_fragment_does_not_manufacture_credibility():
    """C: the core defect reproduction (same as the strict xfail below). A
    40pt-long fragment 150pt beyond the marginal wall's own material must
    not make the 10pt gap credible, and must not manufacture a second,
    synthetic 150pt "opening" either."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(20.0, 10.0, 20.0)
    far_fragment = _fill_rect(200.0, 100.0, 240.0, 106.0)
    drawings = drawings + [far_fragment]
    bbox = (-10.0, 90.0, 250.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "abstained" and ev.openings == (), (
        f"expected clean abstention, got status={ev.status!r} openings={ev.openings!r}"
    )


def test_locality_d_nearby_but_disconnected_fragment_does_not_contribute():
    """D: a fragment only 10pt beyond the marginal wall's own material (far
    closer than case C) must still not contribute, because it only exists
    on the NEAR face's own row (y=100) -- the far face (y=106) has no
    matching evidence there at all, so the gap to it can never be an
    independently-validated, both-faces-aligned opening. Proximity alone,
    without that independent validation, must not help."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(20.0, 10.0, 20.0)
    # Present only at y=100 (matches the near face's own row) with y1=101,
    # far from the real far face at y=106 -- never visible to that row at all.
    one_sided_fragment = _fill_rect(60.0, 100.0, 100.0, 101.0)
    drawings = drawings + [one_sided_fragment]
    bbox = (-10.0, 90.0, 110.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "abstained" and ev.openings == (), (
        f"expected clean abstention (fragment is not independently connected to "
        f"the wall band), got status={ev.status!r} openings={ev.openings!r}"
    )


def test_locality_e_repeated_real_openings_in_one_wall_run_both_survive():
    """E: pier -- windowA -- short mullion pier -- windowB -- pier. Neither
    individual pier alone reaches _MIN_BAND_RUN_PT, so each window's own
    credibility legitimately needs to borrow across the OTHER, real,
    independently-validated window -- and must be ALLOWED to, since that
    intervening gap is itself a genuine two-face-aligned opening in the
    same row pair, not an unexplained void. Both windows must be found."""
    y0, y1 = 100.0, 106.0
    pier1 = _fill_rect(0.0, y0, 20.0, y1)
    # windowA: 20 -> 60
    pier2 = _fill_rect(60.0, y0, 80.0, y1)
    # windowB: 80 -> 120
    pier3 = _fill_rect(120.0, y0, 220.0, y1)
    drawings = [pier1, pier2, pier3]
    bbox = (-10.0, 90.0, 230.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "found", f"expected both windows found, got {ev.status}: {ev.reason}"
    gaps = sorted((o.jamb_start[0], o.jamb_end[0]) for o in ev.openings)
    assert gaps == [(20.0, 60.0), (80.0, 120.0)], f"expected both real windows, got {gaps}"


def test_locality_f_short_but_locally_sufficient_wall_is_not_penalized():
    """F: individually modest piers whose COMBINED immediate local coverage
    already clears _MIN_BAND_RUN_PT without any extra hop. The fix must not
    make this any stricter than before."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(35.0, 15.0, 35.0)  # 35+15+35=85 >= 60
    bbox = (-10.0, 90.0, 100.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "found" and len(ev.openings) == 1


def test_locality_g_large_real_opening_remains_detectable():
    """G: a genuinely wide doorway/opening (150pt, evidenced by proper
    flanking piers) must remain detectable -- gap width alone is never
    proof of disconnection for the CANDIDATE gap itself."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(40.0, 150.0, 40.0)
    bbox = (-10.0, 90.0, 240.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "found" and len(ev.openings) == 1
    assert ev.openings[0].span_pt == pytest.approx(150.0, abs=0.5)


def test_locality_h_unrelated_noise_does_not_join_wall_evidence():
    """H: unrelated diagonal marks near a marginal wall (furniture/hatch-
    like strokes that never pass the axis-aligned face-line or wall-like-
    fill filters at all) must not change the correct abstention -- a basic
    filtering-hygiene check under the new code path."""
    drawings, gap_lo, gap_hi = _pier_wall_with_gap(20.0, 10.0, 20.0)
    noise = [
        _line(25.0, 200.0, 32.0, 208.0, color=(0.3, 0.3, 0.3), width=0.3),  # diagonal, different y entirely
        _line(5.0, 100.0, 5.0, 100.3, color=(0.3, 0.3, 0.3), width=0.3),  # degenerate near-zero-length
    ]
    drawings = drawings + noise
    bbox = (-10.0, 90.0, 60.0, 220.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=25.0)
    assert ev.status == "abstained"


def _rotate_pt(x, y, deg):
    rad = math.radians(deg)
    return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))


def _rotate_drawings(drawings, deg):
    out = []
    for d in drawings:
        new_items = []
        for item in d["items"]:
            op = item[0]
            pts = [_rotate_pt(p.x, p.y, deg) for p in item[1:]]
            new_items.append((op, *[_Pt(px, py) for px, py in pts]))
        new_d = dict(d)
        new_d["items"] = new_items
        if d.get("rect") is not None:
            xs = [p.x for it in new_items for p in it[1:]]
            ys = [p.y for it in new_items for p in it[1:]]
            new_d["rect"] = _Rect(min(xs), min(ys), max(xs), max(ys))
        out.append(new_d)
    return out


@pytest.mark.xfail(
    strict=True,
    reason="same unresolved direct-adjacency ambiguity as test_locality_c, at every axis-preserving orientation",
)
@pytest.mark.parametrize("deg", [90.0, 180.0, 270.0], ids=["rotate90", "rotate180", "rotate270"])
def test_locality_i_case_c_holds_under_rotation(deg):
    """I: the case-C defect-reproduction scenario must resolve the same way
    (clean abstention) at every axis-preserving orientation.

    Deliberately does NOT test a non-round angle: this detector is
    explicitly axis-aligned-only by design (its own module docstring:
    "Both axis-aligned orientations... are checked"), and a fill's own
    bounding "rect" (both in real PyMuPDF output and in this fixture's
    _rotate_drawings, which recomputes it the same way) is inherently
    axis-aligned -- rotating a real wall-like fill by a non-multiple of 90
    degrees does not produce "the same wall viewed at an angle", it
    produces an axis-aligned bounding diamond with a different aspect
    ratio, silently testing a different, invalid fixture instead (confirmed
    by trying 41 degrees here: fills stopped qualifying as wall-like at
    all, and the test passed for an uninteresting, unrelated reason). This
    matches why the existing repository metamorphic test for this module
    also only exercises rotate90, not an arbitrary angle."""
    drawings, _, _ = _pier_wall_with_gap(20.0, 10.0, 20.0)
    far_fragment = _fill_rect(200.0, 100.0, 240.0, 106.0)
    drawings = drawings + [far_fragment]
    rotated = _rotate_drawings(drawings, deg)
    big_viewport = (-500.0, -500.0, 500.0, 500.0)
    ev = resolve_hosted_opening_spans(_FakePage(rotated), viewport_bbox=big_viewport, scale_authority=25.0)
    assert ev.status == "abstained" and ev.openings == (), (
        f"deg={deg}: expected clean abstention, got status={ev.status!r} openings={ev.openings!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="same unresolved direct-adjacency ambiguity as test_locality_c, independent of scale_authority",
)
@pytest.mark.parametrize("scale_authority", [12.5, 33.75, 50.0], ids=["scale_half", "scale_1_35x", "scale_double"])
def test_locality_j_case_c_holds_under_scale_authority(scale_authority):
    """J: the qualitative result (marginal + distant-unrelated -> clean
    abstention) must be independent of the caller-supplied scale_authority.

    Deliberately does NOT scale the raw fixture geometry itself:
    _MIN_BAND_RUN_PT, _MIN_GAP_PT, and every other threshold in this
    module operate on raw PDF points, not real-world metres -- they are
    fixed absolute constants, not scale-relative (confirmed directly:
    naively scaling this same fixture's raw coordinates by 2x made the
    "marginal" wall's own immediate local coverage exceed _MIN_BAND_RUN_PT
    on its own, silently testing a different, no-longer-marginal scenario
    instead of the same one at a different scale). scale_authority's only
    real effect anywhere in this module is the width_m conversion applied
    to an already-resolved span_pt -- it must never change whether a span
    is found, abstained, or how it is classified, which is exactly what
    varying only scale_authority against fixed raw geometry tests."""
    drawings, _, _ = _pier_wall_with_gap(20.0, 10.0, 20.0)
    far_fragment = _fill_rect(200.0, 100.0, 240.0, 106.0)
    drawings = drawings + [far_fragment]
    bbox = (-10.0, 90.0, 250.0, 116.0)
    ev = resolve_hosted_opening_spans(_FakePage(drawings), viewport_bbox=bbox, scale_authority=scale_authority)
    assert ev.status == "abstained" and ev.openings == (), (
        f"scale_authority={scale_authority}: expected clean abstention, "
        f"got status={ev.status!r} openings={ev.openings!r}"
    )
