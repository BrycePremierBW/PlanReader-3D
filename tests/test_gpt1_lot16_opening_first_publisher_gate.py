"""Lot16 source diagnostics may never self-certify canonical opening quantities."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pb_live_opening_area_quantity_publication import _opening_quantity
from tests.test_live_opening_area_quantity_publication import _opening
from tools.diag_lot16_room_face_scope import (
    _opening_quantity_diagnostic,
    _opening_quantity_first_failure,
)


def test_valid_figured_hosted_opening_is_ready_at_the_actual_production_gate():
    opening = _opening()
    assert _opening_quantity(opening) is not None
    assert _opening_quantity_first_failure(opening) == (
        "opening_area_quantity_prerequisites_resolved"
    )


@pytest.mark.parametrize("area", [True, False, "2.172", float("nan")])
def test_untyped_or_nonfinite_metric_cannot_appear_ready_for_opening_quantity(area):
    opening = replace(_opening(), area_m2=area)
    assert _opening_quantity_first_failure(opening) == "metric_opening_area_unavailable"


@pytest.mark.parametrize("bad_evidence", [
    ("figured-1", "figured-1", "host-binding-1"),
    ("figured-1", "", "host-binding-1"),
    ("figured-1", False, "host-binding-1"),
])
def test_damaged_original_opening_evidence_cannot_look_quantity_ready(bad_evidence):
    opening = replace(_opening(), evidence_ids=bad_evidence)
    assert _opening_quantity_first_failure(opening) == "opening_source_evidence_unavailable"


def test_diagonal_diagnostic_does_not_override_actual_producer_on_missing_document():
    opening = replace(_opening(), document_id="")
    assert _opening_quantity(opening) is None
    assert _opening_quantity_first_failure(opening) == (
        "production_opening_area_quantity_gate_unresolved"
    )


def test_real_publisher_failure_is_reported_separately_from_canonical_count():
    opening = _opening()
    wrong = replace(_opening(canonical_id="opening-2"), document_id="")
    source_qty = _opening_quantity(opening)
    assert source_qty is not None
    claim = SimpleNamespace(
        canonical_openings=(opening, wrong),
        opening_quantity_evidence=(source_qty,),
        opening_count_quantity_evidence=(),
    )
    report = _opening_quantity_diagnostic(claim)
    assert report["canonical_opening_count"] == 2
    assert report["published_area_quantity_count"] == 1
    assert report["producer_ready_but_no_area_quantity_count"] == 0
    assert report["first_failure_frequency"] == {
        "opening_area_quantity_prerequisites_resolved": 1,
        "production_opening_area_quantity_gate_unresolved": 1,
    }



def test_lot16_floor_diagnostic_never_hides_duplicate_canonical_room_owner():
    from tests.test_live_floor_area_quantity_publication_integrity import (
        _claim_with_canonical_room, _source_area,
    )
    from tools.diag_lot16_room_face_scope import _floor_quantity_diagnostic

    authentic = _claim_with_canonical_room(_source_area())
    original = _floor_quantity_diagnostic(authentic)
    assert original["per_floor"][0]["first_missing_prerequisite"] == (
        "floor_area_quantity_prerequisites_resolved"
    )

    # Two original source-room records with the same canonical ID cannot be
    # silently reduced to one by the diagnostic dict, even when the metric
    # area supplier happens to remain valid on that floor.
    colliding = replace(
        authentic,
        canonical_rooms=(*authentic.canonical_rooms, authentic.canonical_rooms[0]),
    )
    report = _floor_quantity_diagnostic(colliding)
    assert report["per_floor"][0]["first_missing_prerequisite"] == (
        "duplicate_canonical_room_source_owner_conflict"
    )


def test_duplicate_room_conflict_does_not_precede_missing_physical_floor():
    from types import SimpleNamespace
    from tools.diag_lot16_room_face_scope import _floor_quantity_first_failure

    floor = SimpleNamespace(
        physical_floor_surface_identity_resolved=False,
        physical_floor_surface_id="",
        source_room_face_record_id="face-1",
        evidence_ids=("ev-room",),
    )
    assert _floor_quantity_first_failure(
        floor, SimpleNamespace(room_label="ROOM"), set(), duplicate_room_owner=True
    ) == "physical_floor_identity_unresolved"
