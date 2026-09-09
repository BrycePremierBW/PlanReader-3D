"""Mutation/metamorphic/red-team tests for F.23 secondary-footprint evidence.

All drawings are synthetic. No development-benchmark quantities, project
names, file names, or expected takeoff outputs are used anywhere here.

Layout notes (see ``_build_plan_page``): the calibrated same-row tolerance
for 10pt synthetic text is roughly 40pt against a 280pt-tall frame, i.e.
~15% of the frame's span. Edge/center fractions below are chosen with at
least 0.20 of separation from each other and from the unrelated content
row at the frame's vertical center so that unrelated content never
accidentally lands in a test's row-matching tolerance band.
"""
from __future__ import annotations

import fitz
import pytest

from pb_secondary_footprint_evidence import resolve_secondary_footprint_width_m


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


_EDGE_FRACTIONS = {
    "top": (0.5, 0.05),
    "bottom": (0.5, 0.95),
    # Kept further than the vector witness-binding distance from the frame's
    # own vertical edges (a synthetic-test artifact: the frame rectangle used
    # to earn a RESOLVED viewport is itself vector geometry, so text placed
    # too close to it can be spuriously witness-bound as a vertical
    # dimension against the frame edge) while still inside the adjacency
    # band checked against the viewport's own extent.
    "left": (0.15, 0.25),
    "right": (0.85, 0.75),
    "center": (0.5, 0.5),
}


def _build_plan_page(
    *,
    dx: float = 0.0,
    dy: float = 0.0,
    scale: float = 1.0,
    edge: str = "bottom",
    chain_text: str = "1800",
    label_text: str = "VERANDAH",
    label_gap_pt: float = 4.0,
    second_label: bool = False,
    include_chain: bool = True,
    page_w: float = 640.0,
    page_h: float = 460.0,
) -> fitz.Document:
    """One framed 'GROUND FLOOR PLAN' viewport with a label + nearby chain.

    ``edge`` controls which side of the frame the label/chain pair sits near
    ("top", "bottom", "left", "right", or "center" for the non-adjacent
    negative case). All geometry is derived from the frame's own extent so
    ``scale``/``dx``/``dy`` mutate the whole drawing consistently. The
    dimension chain is placed directly below the label at the same x so it
    can never overflow the frame regardless of which edge is under test.
    """
    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)
    fs = 10.0 * scale

    fx0, fy0 = 30.0 * scale + dx, 30.0 * scale + dy
    fx1, fy1 = fx0 + 280.0 * scale, fy0 + 280.0 * scale
    frame = fitz.Rect(fx0, fy0, fx1, fy1)
    page.draw_rect(frame)

    width = fx1 - fx0
    height = fy1 - fy0

    # Unrelated main-room content, always at the frame's vertical center --
    # comfortably separated (>=0.20 of the frame height) from every edge
    # fraction used below -- plus the title near the frame's bottom.
    page.insert_text((fx0 + 0.10 * width, fy0 + 0.50 * height), "150 5,700 150", fontsize=fs)
    page.insert_text((fx0 + 0.10 * width, fy1 - 6.0 * scale), "GROUND FLOOR PLAN", fontsize=fs)

    x_frac, y_frac = _EDGE_FRACTIONS[edge]
    # insert_text's point is the text's left-baseline origin, not its bbox
    # center -- correct for the label's own rendered width so the resulting
    # bbox center lands at the intended fraction of the frame regardless of
    # label string length.
    label_width = fitz.get_text_length(label_text, fontsize=fs)
    label_x = fx0 + x_frac * width - label_width / 2.0
    label_y = fy0 + y_frac * height
    page.insert_text((label_x, label_y), label_text, fontsize=fs)
    if second_label:
        # A safe interior position, always inside the frame regardless of
        # which edge the primary label under test sits near.
        page.insert_text((fx0 + 0.5 * width, fy0 + 0.5 * height + 12.0 * scale), label_text, fontsize=fs)
    if include_chain:
        # Row-matching only compares y-position to the label, so the chain's
        # x-position is free to stay clear of the frame's own vertical edges
        # (near which text can be spuriously witness-bound as a vertical
        # dimension against the frame edge itself -- a synthetic-test
        # artifact, since the frame rectangle doubles as both the viewport
        # boundary and the nearest vector geometry here).
        chain_x = fx0 + 0.5 * width
        page.insert_text((chain_x, label_y + label_gap_pt * scale), chain_text, fontsize=fs)

    return _reopen(doc)


def _resolve(doc: fitz.Document):
    result = resolve_secondary_footprint_width_m(doc[0], page_num=1)
    doc.close()
    return result


# ---------------------------------------------------------------------------
# Nominal resolution
# ---------------------------------------------------------------------------

def test_single_segment_chain_resolves_width_adjacent_to_bottom_edge():
    result = _resolve(_build_plan_page(edge="bottom", chain_text="1800"))
    assert result is not None
    assert result.width_m == pytest.approx(1.8)
    assert result.edge == "bottom"
    assert result.label_text == "verandah"


def test_wall_bracketed_chain_resolves_middle_span_only():
    # "150 1800 150" is the same shape as F.15's wall-thickness bracket
    # pattern; classify_chain_segments must strip the flanking wall-thickness
    # values and keep only the enclosed 1800mm span.
    result = _resolve(_build_plan_page(edge="bottom", chain_text="150 1800 150"))
    assert result is not None
    assert result.width_m == pytest.approx(1.8)


@pytest.mark.parametrize("edge", ["top", "bottom", "left", "right"])
def test_all_four_edges_resolve_with_correct_edge_label(edge: str):
    result = _resolve(_build_plan_page(edge=edge, chain_text="2400"))
    assert result is not None
    assert result.edge == edge
    assert result.width_m == pytest.approx(2.4)


# ---------------------------------------------------------------------------
# Metamorphic invariance: translation, scale, dimension-value mutation
# ---------------------------------------------------------------------------

def test_translation_invariance():
    base = _resolve(_build_plan_page(edge="bottom", chain_text="1800"))
    shifted = _resolve(_build_plan_page(edge="bottom", chain_text="1800", dx=137.0, dy=-22.0))
    assert base is not None and shifted is not None
    assert shifted.width_m == pytest.approx(base.width_m)
    assert shifted.edge == base.edge


def test_scale_invariance():
    base = _resolve(_build_plan_page(edge="right", chain_text="1800", scale=1.0))
    scaled = _resolve(
        _build_plan_page(edge="right", chain_text="1800", scale=1.8, page_w=900.0, page_h=700.0)
    )
    assert base is not None and scaled is not None
    # The scale only stretches page-space geometry; the printed dimension
    # value (and therefore the resolved real-world width) is unaffected.
    assert scaled.width_m == pytest.approx(base.width_m)
    assert scaled.edge == base.edge


def test_dimension_value_mutation_changes_resolved_width():
    small = _resolve(_build_plan_page(edge="bottom", chain_text="1200"))
    large = _resolve(_build_plan_page(edge="bottom", chain_text="2400"))
    assert small is not None and large is not None
    assert small.width_m == pytest.approx(1.2)
    assert large.width_m == pytest.approx(2.4)
    assert small.width_m != large.width_m


# ---------------------------------------------------------------------------
# Fail-closed: missing/removed evidence
# ---------------------------------------------------------------------------

def test_no_label_at_all_returns_none():
    result = _resolve(_build_plan_page(edge="bottom", label_text="STORE"))
    assert result is None


def test_label_present_but_dimension_evidence_removed_returns_none():
    result = _resolve(_build_plan_page(edge="bottom", include_chain=False))
    assert result is None


def test_label_not_adjacent_to_any_viewport_edge_returns_none():
    # A secondary space in the plan's interior is not a genuine adjacency
    # signal -- this must fail closed rather than accept an interior label.
    result = _resolve(_build_plan_page(edge="center", chain_text="1800"))
    assert result is None


# ---------------------------------------------------------------------------
# Fail-closed: ambiguity
# ---------------------------------------------------------------------------

def test_two_label_instances_in_same_viewport_fails_closed():
    result = _resolve(_build_plan_page(edge="bottom", second_label=True))
    assert result is None


def test_conflicting_nearby_chains_fail_closed():
    doc = fitz.open()
    page = doc.new_page(width=640, height=460)
    frame = fitz.Rect(30, 30, 310, 310)
    page.draw_rect(frame)
    page.insert_text((50, 170), "150 5,700 150", fontsize=10)
    page.insert_text((50, 302), "GROUND FLOOR PLAN", fontsize=10)
    label_y = 295.0  # near the bottom edge band
    page.insert_text((150, label_y), "VERANDAH", fontsize=10)
    # Two distinct same-row-tolerance chains with disagreeing values.
    page.insert_text((60, label_y + 3), "1800", fontsize=10)
    page.insert_text((220, label_y + 3), "2100", fontsize=10)
    doc = _reopen(doc)
    result = _resolve(doc)
    assert result is None


def test_label_in_two_distinct_floor_plan_viewports_fails_closed():
    doc = fitz.open()
    page = doc.new_page(width=900, height=460)
    left = fitz.Rect(30, 30, 310, 310)
    right = fitz.Rect(360, 30, 640, 310)
    page.draw_rect(left)
    page.draw_rect(right)
    page.insert_text((50, 170), "150 5,700 150", fontsize=10)
    page.insert_text((50, 302), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((380, 170), "150 5,700 150", fontsize=10)
    page.insert_text((380, 302), "FIRST FLOOR PLAN", fontsize=10)

    label_y = 295.0
    page.insert_text((150, label_y), "VERANDAH", fontsize=10)
    page.insert_text((150, label_y + 3), "1800", fontsize=10)
    page.insert_text((480, label_y), "VERANDAH", fontsize=10)
    page.insert_text((480, label_y + 3), "1800", fontsize=10)
    doc = _reopen(doc)
    result = _resolve(doc)
    assert result is None


# ---------------------------------------------------------------------------
# Cross-view isolation: an elevation's own numbers must never leak in
# ---------------------------------------------------------------------------

def test_elevation_viewport_evidence_is_never_used():
    doc = fitz.open()
    page = doc.new_page(width=900, height=460)
    plan = fitz.Rect(30, 30, 310, 310)
    elevation = fitz.Rect(360, 30, 640, 310)
    page.draw_rect(plan)
    page.draw_rect(elevation)
    page.insert_text((50, 170), "150 5,700 150", fontsize=10)
    page.insert_text((50, 302), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((380, 170), "300 2,900 300", fontsize=10)
    page.insert_text((400, 302), "WEST ELEVATION", fontsize=10)

    label_y = 295.0
    page.insert_text((150, label_y), "VERANDAH", fontsize=10)
    page.insert_text((150, label_y + 3), "1800", fontsize=10)
    # A tempting same-row trap sitting in the elevation viewport, at the same
    # absolute page y-coordinate as the plan's genuine evidence.
    page.insert_text((480, label_y), "VERANDAH", fontsize=10)
    page.insert_text((480, label_y + 3), "9999", fontsize=10)
    doc = _reopen(doc)
    result = _resolve(doc)
    # The label now genuinely exists in two distinct owned viewports (one
    # plan, one elevation) -- but only the plan one is FLOOR_PLAN-typed, so
    # exactly one anchor should qualify and resolve to the plan's own value.
    assert result is not None
    assert result.width_m == pytest.approx(1.8)
    assert result.view_id != ""


def test_non_adjacent_far_dimension_in_same_viewport_is_ignored():
    # A stray number elsewhere in the same plan (e.g. an unrelated room
    # dimension row far from the label) must never be mistaken for the
    # secondary footprint's own width.
    doc = fitz.open()
    page = doc.new_page(width=640, height=460)
    frame = fitz.Rect(30, 30, 310, 310)
    page.draw_rect(frame)
    page.insert_text((50, 60), "5500", fontsize=10)  # far from the label's row
    page.insert_text((50, 302), "GROUND FLOOR PLAN", fontsize=10)
    label_y = 295.0
    page.insert_text((150, label_y), "VERANDAH", fontsize=10)
    doc = _reopen(doc)
    result = _resolve(doc)
    assert result is None


# ---------------------------------------------------------------------------
# DERIVED-tier fallback (unframed, title-partitioned viewports)
# ---------------------------------------------------------------------------

def test_derived_viewport_tier_still_resolves_with_lower_authority():
    doc = fitz.open()
    page = doc.new_page(width=900, height=460)
    # No vector frames at all -- two separated, classifiable titles let F.07
    # derive a non-overlapping page partition instead.
    page.insert_text((60, 170), "150 5,700 150", fontsize=10)
    page.insert_text((60, 400), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((520, 170), "300 2,900 300", fontsize=10)
    page.insert_text((520, 400), "WEST ELEVATION", fontsize=11)

    label_y = 385.0  # near the bottom edge of the derived left partition
    page.insert_text((150, label_y), "VERANDAH", fontsize=10)
    page.insert_text((150, label_y + 3), "1800", fontsize=10)
    doc = _reopen(doc)
    result = _resolve(doc)
    assert result is not None
    assert result.width_m == pytest.approx(1.8)
    assert result.view_status == "derived"


def test_single_unresolved_title_with_no_partition_evidence_returns_none():
    doc = fitz.open()
    page = doc.new_page(width=640, height=460)
    # A single unframed title cannot prove any viewport extent at all.
    page.insert_text((60, 170), "150 5,700 150", fontsize=10)
    page.insert_text((60, 400), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((150, 385), "VERANDAH", fontsize=10)
    page.insert_text((150, 388), "1800", fontsize=10)
    doc = _reopen(doc)
    result = _resolve(doc)
    assert result is None
