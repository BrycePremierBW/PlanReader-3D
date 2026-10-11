"""GPT1 Q01: FIRM canonical floors may only reuse typed source-owned room m²."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

import pytest

from pb_live_floor_area_quantity_publication import (
    publish_live_floor_area_quantities,
    publish_live_canonical_room_area_quantities,
)
from tests.test_live_floor_area_quantity_publication_integrity import (
    _source_area, _claim_with, _claim_with_canonical_room,
)
from tests.test_live_floor_finish_area_source_closed_export import _floor


def replay(**changes):
    original = copy(_source_area())
    for key, value in changes.items():
        object.__setattr__(original, key, value)
    return original


@pytest.mark.parametrize("bad", [True, False, "8.64", float("nan"), float("inf"), 0])
def test_replayed_source_value_cannot_make_positive_firm_floor_or_room_area(bad):
    forged = replay(value=bad)
    assert publish_live_floor_area_quantities(_claim_with(forged)) == ()
    assert publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(forged)
    ) == ()


@pytest.mark.parametrize("bad", [True, False, "1.0", float("nan"), -0.2, 1.2])
def test_source_confidence_must_be_finite_typed_probability(bad):
    forged = replay(confidence=bad)
    assert publish_live_floor_area_quantities(_claim_with(forged)) == ()
    assert publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(forged)
    ) == ()


@pytest.mark.parametrize("bad", [(), ("ev-area", "ev-area"), ("ev-room", "  "),
                                      ("ev-room", True), ("ev-room", "ev-area", "ev-room")])
def test_missing_duplicate_or_invalid_original_evidence_does_not_publish(bad):
    forged = replay(evidence_ids=bad)
    assert publish_live_floor_area_quantities(_claim_with(forged)) == ()
    assert publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(forged)
    ) == ()


@pytest.mark.parametrize("bad", [True, "8.64", float("nan"), float("inf")])
def test_canonical_floor_metric_replay_cannot_authorize_firm_room_area(bad):
    floor = replace(_floor(), metric_area_m2=bad)
    claim = replace(_claim_with(_source_area()), canonical_floors=(floor,))
    assert publish_live_floor_area_quantities(claim) == ()


def test_original_firm_source_and_orthogonal_figured_area_work_without_scale():
    original = _source_area()
    floor = publish_live_floor_area_quantities(_claim_with(original))
    room = publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(original)
    )
    assert len(floor) == len(room) == 1
    assert floor[0].value == room[0].value == 8.64
    assert floor[0].unit == room[0].unit == "m2"
