"""Q01: a FIRM sheet scale is not permission to measure corrupt page primitives."""
from __future__ import annotations

from copy import copy

import pytest

from pb_room_area_quantity import _polygon_area
from tests.test_room_area_quantity_v2 import _room, _scale, _scaled_qty, _square


@pytest.mark.parametrize("broken_ring", [
    ((0., 0.), (5., 5.), (10., 10.)),
    ((0., 0.), (5., 0.), (5., 0.), (0., 5.)),
    ((0., 0.), (5., 0.), (5., True), (0., 5.)),
    ((0., 0.), (float("nan"), 0.), (5., 5.), (0., 5.)),
    ((0., 0.), (float("inf"), 0.), (5., 5.), (0., 5.)),
    ((0., 0.), (1e308, 0.), (1e308, 1e308), (0., 1e308)),
    ((0., 0.), ("5", 0.), (5., 5.), (0., 5.)),
    ((0., 0.), (5., 0.), (5.,), (0., 5.)),
])
def test_bad_page_polygon_never_becomes_firm_scaled_floor_area(broken_ring):
    authentic = _room(points=_square(_scale()))
    # Imported/edited objects may not run RoomCandidate constructor checks.
    replay = copy(authentic)
    object.__setattr__(replay, "polygon_pdf_pts", broken_ring)
    quantity = _scaled_qty(room=replay)
    assert quantity.abstained is True
    assert quantity.value is None
    assert "room_polygon_area_invalid" in quantity.blocking_reasons
    assert _polygon_area(broken_ring) == 0.0


def test_valid_metric_scale_still_measures_original_source_polygon():
    scale = _scale()
    quantity = _scaled_qty(room=_room(points=_square(scale)), scale=scale)
    assert quantity.abstained is False
    assert quantity.value == 25.0


def test_closed_last_vertex_is_allowed_when_source_ring_is_non_degenerate():
    scale = _scale()
    ring = _square(scale)
    quantity = _scaled_qty(room=_room(points=(*ring, ring[0])), scale=scale)
    assert quantity.abstained is False
    assert quantity.value == 25.0
