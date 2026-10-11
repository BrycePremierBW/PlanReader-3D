"""Q01: a confirmed finish occurrence does not make Boolean PDF metrics authoritative."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

import pytest

from pb_cross_view_floor_finish_authority import _area_value, _bbox, _matching_floor
from tests.test_cross_view_floor_finish_authority_v1 import _payload, _source_room_area_and_floor


@pytest.mark.parametrize("bad", [
    (True, 0.0, 10.0, 10.0),
    ("0", 0.0, 10.0, 10.0),
    (0.0, 0.0, float("nan"), 10.0),
    (0.0, 0.0, 10.0, float("inf")),
])
def test_forged_dimension_box_cannot_bind_material_occurrence(bad):
    assert _bbox(bad) is None


def test_native_typed_source_dimension_box_still_resolves():
    assert _bbox((0.0, 1.0, 10.0, 12.0)) == (0.0, 1.0, 10.0, 12.0)


@pytest.mark.parametrize("bad_area", [True, False, "8.64", float("nan"), float("inf")])
def test_replayed_figured_area_cannot_be_reused_as_floor_finish_m2(bad_area):
    source, areas, floors = _source_room_area_and_floor(_payload())
    record = copy(areas.records[0])
    evidence = copy(record.area_evidence)
    object.__setattr__(evidence, "normalized_value", bad_area)
    object.__setattr__(record, "area_evidence", evidence)
    assert _area_value(record) is None
    assert _matching_floor(floors, record) is None


def test_double_boolean_replay_does_not_make_a_fake_one_square_metre_floor():
    _source, areas, floors = _source_room_area_and_floor(_payload())
    record = copy(areas.records[0])
    evidence = copy(record.area_evidence)
    object.__setattr__(evidence, "normalized_value", True)
    object.__setattr__(record, "area_evidence", evidence)
    floor = replace(floors.floors[0], metric_area_m2=True)
    fake_floors = replace(floors, floors=(floor,))
    assert _matching_floor(fake_floors, record) is None


def test_authentic_documented_floor_area_remains_bound_to_physical_floor():
    _source, areas, floors = _source_room_area_and_floor(_payload())
    authentic = _matching_floor(floors, areas.records[0])
    assert authentic is not None
    assert authentic.metric_area_m2 == 8.64
