"""Fail-closed replay integrity at the canonical floor QuantityEvidence boundary."""
from __future__ import annotations

from dataclasses import replace

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_live_floor_area_quantity_publication import (
    publish_live_floor_area_quantities,
    publish_live_canonical_room_area_quantities,
)
from pb_live_canonical_room_composition import LiveCanonicalRoomObject
from pb_migration_contracts import QuantityEvidence
from tests.test_live_floor_finish_area_source_closed_export import _claim, _floor


def _source_area() -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id="room-area-1",
        family="room_area",
        semantic_key="room_area:source-room-1",
        value=8.64,
        unit="m2",
        input_entity_ids=("source-room-1",),
        formula="authenticated_documented_room_area",
        formula_version="1",
        evidence_ids=("ev-room", "ev-area"),
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.FIRM.value,
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=("authenticated_room_area",),
        metadata={
            "source_sha256": "a" * 64,
            "revision_id": "rev-1",
            "page_no": "1",
            "viewport_id": "vp-1",
        },
    )


def _claim_with(*quantities: QuantityEvidence):
    return replace(
        _claim(_floor()),
        room_area_quantity_evidence=tuple(quantities),
    )


def test_unique_firm_room_area_publishes_exactly_one_canonical_floor_quantity() -> None:
    published = publish_live_floor_area_quantities(_claim_with(_source_area()))

    assert len(published) == 1
    result = published[0]
    assert result.family == "floor_area"
    assert result.value == 8.64
    assert result.status == AuthorityStatus.FIRM.value
    assert result.input_entity_ids == ("floor-1",)
    assert result.metadata["upstream_room_area_quantity_id"] == "room-area-1"


def test_competing_room_area_sources_for_one_physical_floor_fail_closed() -> None:
    source = _source_area()
    floor = _floor()
    other_source = replace(source, quantity_id="room-area-competing")
    other_floor = replace(
        floor,
        canonical_floor_id="canonical-floor-competing",
        metric_area_quantity_id=other_source.quantity_id,
    )
    claim = replace(
        _claim_with(source, other_source),
        canonical_floors=(floor, other_floor),
    )
    assert publish_live_floor_area_quantities(claim) == ()

    # Removing the competing source restores one authentic floor quantity.
    assert len(publish_live_floor_area_quantities(_claim_with(source))) == 1


def test_identical_source_room_area_replay_is_idempotent() -> None:
    source = _source_area()

    unique = publish_live_floor_area_quantities(_claim_with(source))
    replay = publish_live_floor_area_quantities(_claim_with(source, source))

    assert len(unique) == 1
    assert replay == unique


def test_conflicting_duplicate_id_never_publishes_floor_area() -> None:
    original = _source_area()
    changes = (
        replace(original, value=9.0),
        replace(original, evidence_ids=("ev-room",)),
        replace(
            original,
            metadata={**original.metadata, "viewport_id": "another-viewport"},
        ),
    )
    for conflicting in changes:
        for quantities in (
            (original, conflicting),
            (conflicting, original),
            (original, conflicting, original),
        ):
            assert publish_live_floor_area_quantities(_claim_with(*quantities)) == ()


def test_unrelated_non_firm_replay_does_not_poison_a_firm_source_id() -> None:
    source = _source_area()
    rejected = replace(
        source,
        status=AuthorityStatus.PROVISIONAL.value,
        value=None,
        abstained=True,
        blocking_reasons=("not_firm",),
    )

    published = publish_live_floor_area_quantities(
        _claim_with(source, rejected)
    )
    assert len(published) == 1


def test_empty_source_receipts_cannot_mint_firm_floor_area() -> None:
    source = _source_area()
    # Previously the empty source evidence set passed the subset test
    # vacuously, despite proving no relationship to the physical floor.
    missing_source = replace(source, evidence_ids=())
    assert publish_live_floor_area_quantities(
        _claim_with(missing_source)
    ) == ()

    floor = replace(_floor(), evidence_ids=())
    claim = replace(_claim_with(source), canonical_floors=(floor,))
    assert publish_live_floor_area_quantities(claim) == ()


def test_unsupported_area_units_and_blocked_claims_do_not_publish_m2() -> None:
    source = _source_area()
    invalid_claims = (
        replace(source, unit="ft2"),
        replace(source, blocking_reasons=("unresolved_source_authority",)),
    )
    for invalid in invalid_claims:
        assert publish_live_floor_area_quantities(_claim_with(invalid)) == ()


def test_unsupported_firm_authority_cannot_publish_canonical_floor_quantity() -> None:
    source = _source_area()
    for authority in ("model_derived", "schedule_extracted", "ai_detected"):
        unsupported = replace(source, authority=authority)
        floor = replace(_floor(), metric_area_authority=authority)
        claim = replace(
            _claim_with(unsupported),
            canonical_floors=(floor,),
        )
        assert publish_live_floor_area_quantities(claim) == ()


def test_figured_room_snapshot_and_physical_face_identity_match_canonical_floor() -> None:
    source = _source_area()
    floor = _floor()
    evidence = replace(
        source,
        metadata={
            **source.metadata,
            "room_snapshot_id": floor.snapshot_id,
            "source_room_face_record_id": floor.source_room_face_record_id,
            # The independent dimension support view is allowed to use a
            # different snapshot without changing physical room ownership.
            "source_dimension_snapshot_id": "support-snapshot-other",
        },
    )
    assert len(publish_live_floor_area_quantities(_claim_with(evidence))) == 1


def test_canonical_floor_quantity_rejects_cross_snapshot_figured_area() -> None:
    source = _source_area()
    floor = _floor()
    alien = replace(
        source,
        metadata={
            **source.metadata,
            "room_snapshot_id": "other-physical-room-snapshot",
            "source_room_face_record_id": floor.source_room_face_record_id,
        },
    )
    assert publish_live_floor_area_quantities(_claim_with(alien)) == ()


def test_canonical_floor_quantity_rejects_unrelated_source_room_face() -> None:
    source = _source_area()
    floor = _floor()
    alien = replace(
        source,
        metadata={
            **source.metadata,
            "room_snapshot_id": floor.snapshot_id,
            "source_room_face_record_id": "other-room-face",
        },
    )
    assert publish_live_floor_area_quantities(_claim_with(alien)) == ()


def _claim_with_canonical_room(*quantities: QuantityEvidence):
    floor = _floor()
    room = LiveCanonicalRoomObject(
        canonical_room_id=floor.room_entity_id,
        physical_room_id="physical-room-1",
        document_id=floor.document_id,
        revision_id=floor.revision_id,
        source_sha256=floor.source_sha256,
        snapshot_id=floor.snapshot_id,
        page_id=floor.page_id,
        viewport_id=floor.viewport_id,
        decision_scope_id="source-room-scope-1",
        polygon_pdf_pts=floor.polygon_pdf_pts,
        bounding_wall_ids=floor.bounding_wall_ids,
        canonical_bounding_wall_ids=floor.canonical_bounding_wall_ids,
        wall_relationships_complete=True,
        area_page_pts2=floor.area_page_pts2,
        source_room_face_record_id=floor.source_room_face_record_id,
        evidence_ids=("ev-room",),
        geometry_complete=True,
        metric_geometry_complete=False,
    )
    return replace(
        _claim_with(*quantities),
        canonical_rooms=(room,),
    )


def test_canonical_room_reissue_preserves_approved_firm_source_evidence() -> None:
    source = _source_area()
    claim = _claim_with_canonical_room(source)
    output = publish_live_canonical_room_area_quantities(claim)
    assert len(output) == 1
    assert output[0].status == AuthorityStatus.FIRM.value
    assert output[0].value == source.value
    assert output[0].evidence_ids == source.evidence_ids
    assert output[0].input_entity_ids == ("physical-room-1",)


def test_canonical_room_reissue_rejects_foreign_room_snapshot() -> None:
    floor = _floor()
    source = replace(
        _source_area(),
        metadata={
            **_source_area().metadata,
            "room_snapshot_id": floor.snapshot_id,
            "source_room_face_record_id": floor.source_room_face_record_id,
            "source_dimension_snapshot_id": "independent-dimension-support",
        },
    )
    matching_claim = _claim_with_canonical_room(source)
    assert len(publish_live_canonical_room_area_quantities(matching_claim)) == 1

    foreign_room = replace(
        matching_claim.canonical_rooms[0],
        snapshot_id="other-physical-room-snapshot",
    )
    altered_claim = replace(
        matching_claim,
        canonical_rooms=(foreign_room,),
    )
    # The floor is valid, but an unrelated canonical room must not inherit it.
    assert len(publish_live_floor_area_quantities(altered_claim)) == 1
    assert publish_live_canonical_room_area_quantities(altered_claim) == ()


def test_canonical_room_reissue_rejects_foreign_viewport() -> None:
    source = _source_area()
    claim = _claim_with_canonical_room(source)
    assert len(publish_live_canonical_room_area_quantities(claim)) == 1
    alien_room = replace(
        claim.canonical_rooms[0],
        viewport_id="foreign-room-viewport",
    )
    assert publish_live_canonical_room_area_quantities(
        replace(claim, canonical_rooms=(alien_room,))
    ) == ()


def test_provisional_duplicate_replay_cannot_replace_approved_firm_room_source() -> None:
    source = _source_area()
    rejected = replace(
        source,
        status=AuthorityStatus.PROVISIONAL.value,
        value=None,
        abstained=True,
        evidence_ids=("untrusted-source-replay",),
        blocking_reasons=("not_firm",),
    )
    original = publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(source)
    )
    assert len(original) == 1
    for order in (
        (source, rejected),
        (rejected, source),
        (source, rejected, source),
    ):
        assert publish_live_canonical_room_area_quantities(
            _claim_with_canonical_room(*order)
        ) == original


def test_conflicting_firm_duplicate_quarantines_canonical_room_quantity() -> None:
    source = _source_area()
    altered = replace(source, evidence_ids=("ev-room",))
    for order in (
        (source, altered),
        (altered, source),
        (source, altered, source),
    ):
        assert publish_live_canonical_room_area_quantities(
            _claim_with_canonical_room(*order)
        ) == ()


def test_unmeasured_alternative_unit_cannot_overwrite_firm_room_source() -> None:
    source = _source_area()
    invalid = replace(source, unit="ft2", evidence_ids=("bad-unit",))
    original = publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(source)
    )
    assert len(original) == 1
    assert publish_live_canonical_room_area_quantities(
        _claim_with_canonical_room(source, invalid)
    ) == original


def test_duplicate_physical_room_identity_quarantines_canonical_area_reissue() -> None:
    source = _source_area()
    claim = _claim_with_canonical_room(source)
    authentic = claim.canonical_rooms[0]
    competing = replace(
        authentic,
        canonical_room_id="competing-canonical-room",
        source_room_face_record_id="another-source-room-face",
    )
    conflicted = replace(claim, canonical_rooms=(authentic, competing))
    # The independently valid floor cannot promote either conflicting room.
    assert len(publish_live_floor_area_quantities(conflicted)) == 1
    assert publish_live_canonical_room_area_quantities(conflicted) == ()


def test_duplicate_source_face_owner_quarantines_canonical_area_reissue() -> None:
    source = _source_area()
    claim = _claim_with_canonical_room(source)
    authentic = claim.canonical_rooms[0]
    competing = replace(
        authentic,
        canonical_room_id="competing-canonical-room",
        physical_room_id="competing-physical-room",
    )
    conflicted = replace(claim, canonical_rooms=(authentic, competing))
    assert len(publish_live_floor_area_quantities(conflicted)) == 1
    assert publish_live_canonical_room_area_quantities(conflicted) == ()


def test_unscaled_page_polygon_never_becomes_metric_floor_area() -> None:
    # A fully closed source polygon may have an enormous PDF-points² area;
    # geometric completeness is not a physical scale or m² source receipt.
    floor = replace(
        _floor(),
        area_page_pts2=250000.0,
        geometry_complete=True,
        metric_geometry_complete=False,
        metric_area_m2=None,
        metric_area_quantity_id=None,
        metric_area_authority=None,
    )
    claim = replace(_claim_with(), canonical_floors=(floor,))
    assert publish_live_floor_area_quantities(claim) == ()
    assert publish_live_canonical_room_area_quantities(claim) == ()


def test_source_firm_area_does_not_override_unmeasured_pdf_polygon() -> None:
    source = _source_area()
    floor = replace(
        _floor(),
        area_page_pts2=999999.0,
        geometry_complete=True,
        metric_geometry_complete=False,
        metric_area_m2=None,
    )
    claim = replace(_claim_with(source), canonical_floors=(floor,))
    assert publish_live_floor_area_quantities(claim) == ()
    assert publish_live_canonical_room_area_quantities(claim) == ()


def test_firm_documented_area_is_valid_without_geometric_scale() -> None:
    # Figured m² authority is independent of whether PDF geometry is scaled.
    floor = replace(
        _floor(),
        area_page_pts2=100000.0,
        geometry_complete=True,
        metric_geometry_complete=False,
    )
    claim = replace(_claim_with(_source_area()), canonical_floors=(floor,))
    published = publish_live_floor_area_quantities(claim)
    assert len(published) == 1
    assert published[0].value == 8.64
    assert published[0].unit == "m2"
    assert published[0].metadata["upstream_room_area_quantity_id"] == "room-area-1"


def test_unmeasured_duplicate_physical_floor_cannot_be_filtered_away() -> None:
    source = _source_area()
    authentic = _floor()
    unresolved = replace(
        authentic,
        canonical_floor_id="unresolved-canonical-floor",
        metric_area_quantity_id=None,
        metric_area_m2=None,
        metric_area_authority=None,
        physical_floor_surface_identity_resolved=False,
    )
    conflicted = replace(
        _claim_with(source),
        canonical_floors=(authentic, unresolved),
    )
    assert publish_live_floor_area_quantities(conflicted) == ()
    assert publish_live_canonical_room_area_quantities(conflicted) == ()


def test_unmeasured_duplicate_canonical_floor_cannot_be_filtered_away() -> None:
    source = _source_area()
    authentic = _floor()
    unresolved = replace(
        authentic,
        physical_floor_surface_id="unresolved-physical-floor",
        room_entity_id="unresolved-room",
        metric_area_quantity_id=None,
        metric_area_m2=None,
        metric_area_authority=None,
        physical_floor_surface_identity_resolved=False,
    )
    assert publish_live_floor_area_quantities(
        replace(_claim_with(source), canonical_floors=(authentic, unresolved))
    ) == ()


def test_unrelated_unmeasured_floor_does_not_poison_firm_source_area() -> None:
    source = _source_area()
    authentic = _floor()
    unresolved = replace(
        authentic,
        canonical_floor_id="other-canonical-floor",
        physical_floor_surface_id="other-physical-floor",
        room_entity_id="other-room",
        source_room_face_record_id="other-source-face",
        metric_area_quantity_id=None,
        metric_area_m2=None,
        metric_area_authority=None,
        physical_floor_surface_identity_resolved=False,
    )
    claim = replace(_claim_with(source), canonical_floors=(authentic, unresolved))
    quantities = publish_live_floor_area_quantities(claim)
    assert len(quantities) == 1
    assert quantities[0].input_entity_ids == (authentic.physical_floor_surface_id,)
    assert quantities == publish_live_floor_area_quantities(
        replace(claim, canonical_floors=(unresolved, authentic))
    )


def _independent_second_floor_and_area(*, same_room=False, same_face=False):
    original = _floor()
    second = replace(
        original,
        canonical_floor_id="floor-2",
        physical_floor_surface_id="floor-2",
        room_entity_id=original.room_entity_id if same_room else "room-2",
        source_room_face_record_id=(
            original.source_room_face_record_id if same_face else "face-2"
        ),
        metric_area_quantity_id="room-area-2",
    )
    second_area = replace(
        _source_area(),
        quantity_id="room-area-2",
        semantic_key="room_area:source-room-2",
    )
    return second, second_area


def test_one_canonical_room_cannot_mint_two_different_full_floor_areas() -> None:
    second, second_area = _independent_second_floor_and_area(same_room=True)
    authentic = _floor()
    # Both quantities are individually eligible, carry different source IDs,
    # and have unique physical/canonical floor identities. Only the claimed
    # full canonical ROOM identity is shared.
    assert len(publish_live_floor_area_quantities(
        replace(_claim_with(second_area), canonical_floors=(second,))
    )) == 1
    claim = replace(
        _claim_with(_source_area(), second_area),
        canonical_floors=(authentic, second),
    )
    assert publish_live_floor_area_quantities(claim) == ()
    assert publish_live_floor_area_quantities(
        replace(claim, canonical_floors=(second, authentic))
    ) == ()


def test_one_source_room_face_cannot_mint_two_separate_full_floor_areas() -> None:
    second, second_area = _independent_second_floor_and_area(same_face=True)
    authentic = _floor()
    assert len(publish_live_floor_area_quantities(
        replace(_claim_with(second_area), canonical_floors=(second,))
    )) == 1
    claim = replace(
        _claim_with(_source_area(), second_area),
        canonical_floors=(authentic, second),
    )
    assert publish_live_floor_area_quantities(claim) == ()
    assert publish_live_floor_area_quantities(
        replace(claim, canonical_floors=(second, authentic))
    ) == ()


def test_unmeasured_full_floor_replay_cannot_hide_shared_room_owner() -> None:
    second, _ = _independent_second_floor_and_area(same_room=True)
    unresolved = replace(
        second,
        metric_area_quantity_id=None,
        metric_area_m2=None,
        metric_area_authority=None,
        physical_floor_surface_identity_resolved=False,
    )
    claim = replace(
        _claim_with(_source_area()),
        canonical_floors=(_floor(), unresolved),
    )
    assert publish_live_floor_area_quantities(claim) == ()


def test_genuinely_separate_rooms_and_faces_preserve_two_firm_floor_areas() -> None:
    second, second_area = _independent_second_floor_and_area()
    claim = replace(
        _claim_with(_source_area(), second_area),
        canonical_floors=(_floor(), second),
    )
    results = publish_live_floor_area_quantities(claim)
    assert len(results) == 2
    assert {q.input_entity_ids for q in results} == {("floor-1",), ("floor-2",)}
    assert {q.metadata["upstream_room_area_quantity_id"] for q in results} == {
        "room-area-1", "room-area-2"
    }
    assert results == publish_live_floor_area_quantities(
        replace(claim, canonical_floors=(second, _floor()))
    )


def test_unmeasured_other_room_using_same_source_face_quarantines_firm() -> None:
    source = _source_area()
    authentic = _floor()
    unresolved = replace(
        authentic,
        canonical_floor_id="unmeasured-second-floor",
        physical_floor_surface_id="unmeasured-second-physical",
        room_entity_id="other-canonical-room",
        # Source-face ID intentionally remains authentic.source_room_face_record_id.
        metric_area_quantity_id=None,
        metric_area_m2=None,
        metric_area_authority=None,
        physical_floor_surface_identity_resolved=False,
    )
    claim = replace(
        _claim_with(source),
        canonical_floors=(authentic, unresolved),
    )
    assert publish_live_floor_area_quantities(claim) == ()
    assert publish_live_floor_area_quantities(
        replace(claim, canonical_floors=(unresolved, authentic))
    ) == ()


def test_floor_quantity_rejects_missing_or_duplicate_source_room_owner_receipts() -> None:
    source = _source_area()
    for fields in (
        {"input_entity_ids": ()},
        {"input_entity_ids": ("source-room-1", "source-room-1")},
        {"input_entity_ids": ("   ",)},
        {"evidence_ids": ("ev-room", "ev-room")},
        {"evidence_ids": ("ev-room", "")},
    ):
        untrusted = replace(source, **fields)
        assert publish_live_floor_area_quantities(_claim_with(untrusted)) == (), fields
    assert len(publish_live_floor_area_quantities(_claim_with(source))) == 1


def test_floor_quantity_rejects_replayed_foreign_document_metadata() -> None:
    source = _source_area()
    foreign = replace(
        source,
        metadata={**dict(source.metadata), "document_id": "foreign-document"},
    )
    assert publish_live_floor_area_quantities(_claim_with(foreign)) == ()
    authentic = replace(
        source,
        metadata={**dict(source.metadata), "document_id": _floor().document_id},
    )
    assert len(publish_live_floor_area_quantities(_claim_with(authentic))) == 1


def test_floor_quantity_rejects_duplicate_or_untyped_floor_evidence_ids() -> None:
    source = _source_area()
    for receipts in (
        ("ev-room", "ev-room", "ev-area"),
        ("ev-room", "", "ev-area"),
        ("ev-room", "   ", "ev-area"),
    ):
        claim = replace(
            _claim_with(source),
            canonical_floors=(replace(_floor(), evidence_ids=receipts),),
        )
        assert publish_live_floor_area_quantities(claim) == ()


def test_floor_area_rejects_boolean_and_nonfinite_quantities_or_confidence():
    source = _source_area()
    for bad in (
        {"value": True},
        {"value": float("nan")},
        {"confidence": True},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": -0.1},
        {"confidence": 1.1},
    ):
        replay = replace(source, **bad)
        assert publish_live_floor_area_quantities(_claim_with(replay)) == (), bad
    for value in (True, False):
        corrupted_floor = replace(_floor(), metric_area_m2=value)
        claim = replace(_claim_with(source), canonical_floors=(corrupted_floor,))
        assert publish_live_floor_area_quantities(claim) == ()
    assert len(publish_live_floor_area_quantities(_claim_with(source))) == 1
