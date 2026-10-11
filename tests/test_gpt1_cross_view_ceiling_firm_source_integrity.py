"""Firm cross-view ceiling area requires exact final room measurement receipts."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

import pytest

from pb_cross_view_ceiling_quantity_authority import publish_cross_view_ceiling_quantities
from pb_migration_contracts import EvidenceResolutionStatus
from tests.test_cross_view_ceiling_quantity_authority import _bridge, _finish, _rooms


def with_modified_area(**changes):
    bridge = _bridge()
    quantity = copy(bridge.quantities[0])
    for name, value in changes.items():
        object.__setattr__(quantity, name, value)
    return replace(bridge, quantities=(quantity,))


def outcome(bridge):
    return publish_cross_view_ceiling_quantities(
        rooms=_rooms(),
        room_area_bridges=(bridge,),
        finishes=_finish(),
    )


def test_original_documented_room_area_with_rcp_occurrence_still_seals_firm():
    positive = outcome(_bridge())
    assert positive.status is EvidenceResolutionStatus.CORROBORATED
    assert len(positive.quantities) == 1
    assert positive.quantities[0].value == 9.05352


@pytest.mark.parametrize("bad_value", [True, False, "9.05352", float("nan"), float("inf")])
def test_boolean_string_or_nonfinite_room_area_cannot_become_firm_ceiling(bad_value):
    rejected = outcome(with_modified_area(value=bad_value))
    assert rejected.records == ()
    assert rejected.unresolved_physical_room_ids == ("physical-room-1",)


@pytest.mark.parametrize("bad_receipts", [
    (), ("room-geometry-evidence", "room-geometry-evidence", "face-1"),
    ("face-1", "", "room-geometry-evidence"),
    ("face-1", True, "room-geometry-evidence"),
])
def test_invalid_original_area_receipts_cannot_be_carried_into_ceiling(bad_receipts):
    rejected = outcome(with_modified_area(evidence_ids=bad_receipts))
    assert rejected.quantities == ()


@pytest.mark.parametrize("bad_confidence", [True, "1.0", float("nan"), 1.1])
def test_room_area_confidence_must_be_original_finite_number(bad_confidence):
    rejected = outcome(with_modified_area(confidence=bad_confidence))
    assert rejected.quantities == ()


@pytest.mark.parametrize("bad_dimension_ids", [
    ["dim-h", "dim-v", "dim-v"],
    ["dim-h", "dim-v", "unrelated-system"],
    ["dim-h", "dim-h"], ["dim-h", "dim-v", ""],
    ["dim-h", "dim-v", True],
])
def test_unproven_dimension_universe_cannot_mint_firm_rcp_area(bad_dimension_ids):
    bridge = _bridge()
    area = bridge.quantities[0]
    metadata = {**area.metadata, "figured_dimension_ids": bad_dimension_ids}
    bad = replace(bridge, quantities=(replace(area, metadata=metadata),))
    assert outcome(bad).quantities == ()
