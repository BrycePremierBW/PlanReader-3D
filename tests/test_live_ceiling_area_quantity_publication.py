from __future__ import annotations

from dataclasses import replace
from copy import copy

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
import pb_live_ceiling_area_source_closed_export as ceiling_export
from pb_customer_output_verification import verify_sealed_customer_output
from pb_live_ceiling_area_customer_projection import (
    project_live_ceiling_area_customer_rows,
)
from pb_live_ceiling_area_quantity_publication import (
    LIVE_CEILING_AREA_QUANTITY_RESOLVED,
    publish_live_ceiling_area_quantities,
)
from pb_live_ceiling_lining_integration import (
    LiveCanonicalCeilingSurfaceObject,
    LiveCeilingLiningResult,
)
from pb_live_canonical_coverage_registry import collect_live_canonical_coverage
from pb_migration_contracts import EvidenceResolutionStatus, QuantityEvidence
from pb_takeoff_coverage_audit_adapter import build_runtime_coverage_publication


SOURCE_SHA = "a" * 64


def _shadow_quantity() -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id="qty-shadow-ceiling-1",
        family="ceiling_lining",
        semantic_key="ceiling_lining:room-1",
        value=13.270425,
        unit="m2",
        input_entity_ids=("room-1",),
        formula="reuse_same_scope_authoritative_area_with_explicit_ceiling_finish",
        formula_version="1",
        evidence_ids=("ev-dim-h", "ev-dim-v", "ev-finish"),
        authority=MeasurementAuthorityType.MODEL_DERIVED.value,
        status=AuthorityStatus.PROVISIONAL.value,
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        metadata={
            "source_sha256": SOURCE_SHA,
            "revision_id": "rev-1",
            "page_no": 1,
            "viewport_id": "vp-1",
            "upstream_area_quantity_id": "qty-room-area-1",
            "shadow_only": True,
            "commercial_projection_allowed": False,
        },
    )


def _ceiling(
    *,
    authority: str = MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
    physical_scale_record_id: str = "",
    figured_dimension_ids: tuple[str, ...] = ("dim-h", "dim-v"),
) -> LiveCanonicalCeilingSurfaceObject:
    return LiveCanonicalCeilingSurfaceObject(
        canonical_ceiling_id="canonical-ceiling-1",
        document_id="doc-1",
        snapshot_id="snapshot-1",
        room_entity_id="room-1",
        source_page=1,
        viewport_id="vp-1",
        source_sha256=SOURCE_SHA,
        revision_id="rev-1",
        polygon_pdf_pts=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        area_m2=13.270425,
        finish_descriptor="plasterboard",
        room_area_quantity_id="qty-room-area-1",
        ceiling_quantity_id="qty-shadow-ceiling-1",
        source_room_index_id="room-index-1",
        evidence_ids=("ev-dim-h", "ev-dim-v", "ev-finish"),
        physical_scale_record_id=physical_scale_record_id,
        measurement_authority=authority,
        figured_dimension_ids=figured_dimension_ids,
    )


def _result(ceiling=None, shadow=None) -> LiveCeilingLiningResult:
    return LiveCeilingLiningResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=("live_ceiling_lining_resolved",),
        claims=(),
        canonical_ceilings=((ceiling or _ceiling()),),
        quantity_evidence=((shadow or _shadow_quantity()),),
    )


def test_documented_dimension_canonical_ceiling_publishes_firm_without_scale() -> None:
    quantities = publish_live_ceiling_area_quantities(_result())

    assert len(quantities) == 1
    quantity = quantities[0]
    assert quantity.family == "ceiling_lining"
    assert quantity.value == 13.270425
    assert quantity.unit == "m2"
    assert quantity.input_entity_ids == ("canonical-ceiling-1",)
    assert quantity.authority == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
    assert quantity.status == AuthorityStatus.FIRM.value
    assert quantity.abstained is False
    assert quantity.reason_codes == (LIVE_CEILING_AREA_QUANTITY_RESOLVED,)
    assert quantity.metadata["figured_dimension_ids"] == ("dim-h", "dim-v")
    assert quantity.metadata["resolved_scale_id"] is None
    assert quantity.metadata["commercial_projection_allowed"] is False
    assert quantity.metadata["quantity_handoff_only"] is True


def test_ceiling_quantity_requires_nonempty_source_and_canonical_receipts() -> None:
    # An empty set previously passed the lineage-subset check vacuously.
    shadow = replace(_shadow_quantity(), evidence_ids=())
    assert publish_live_ceiling_area_quantities(_result(shadow=shadow)) == ()

    ceiling = replace(_ceiling(), evidence_ids=())
    assert publish_live_ceiling_area_quantities(_result(ceiling=ceiling)) == ()


def test_scaled_canonical_ceiling_requires_physical_scale_record() -> None:
    missing = _ceiling(
        authority=MeasurementAuthorityType.PDF_SCALED.value,
        physical_scale_record_id="",
        figured_dimension_ids=(),
    )
    assert publish_live_ceiling_area_quantities(_result(ceiling=missing)) == ()

    resolved = replace(
        missing,
        physical_scale_record_id="physical-scale-1",
    )
    quantities = publish_live_ceiling_area_quantities(_result(ceiling=resolved))
    assert len(quantities) == 1
    quantity = quantities[0]
    assert quantity.authority == MeasurementAuthorityType.PDF_SCALED.value
    assert quantity.status == AuthorityStatus.FIRM.value
    assert quantity.metadata["resolved_scale_id"] == "physical-scale-1"
    assert quantity.metadata["figured_dimension_ids"] == ()


def test_documented_dimension_requires_figured_dimension_lineage() -> None:
    ceiling = _ceiling(figured_dimension_ids=())
    assert publish_live_ceiling_area_quantities(_result(ceiling=ceiling)) == ()


def test_shadow_quantity_must_match_exact_upstream_area_identity() -> None:
    shadow = _shadow_quantity()
    shadow = replace(
        shadow,
        metadata={
            **dict(shadow.metadata),
            "upstream_area_quantity_id": "other-room-area",
        },
    )
    assert publish_live_ceiling_area_quantities(_result(shadow=shadow)) == ()


def test_review_or_promoted_quantity_cannot_replace_shadow_lineage() -> None:
    shadow = replace(
        _shadow_quantity(),
        status=AuthorityStatus.REVIEW_REQUIRED.value,
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        metadata={
            **dict(_shadow_quantity().metadata),
            "shadow_only": False,
            "commercial_projection_allowed": True,
        },
    )
    assert publish_live_ceiling_area_quantities(_result(shadow=shadow)) == ()


def test_quantity_identity_is_deterministic() -> None:
    first = publish_live_ceiling_area_quantities(_result())
    second = publish_live_ceiling_area_quantities(_result())

    assert len(first) == len(second) == 1
    assert first[0].to_dict() == second[0].to_dict()
    assert first[0].quantity_id == second[0].quantity_id


def test_canonical_ceiling_seals_on_exact_canonical_identity() -> None:
    result = _result()
    quantity = publish_live_ceiling_area_quantities(result)[0]

    traces = ceiling_export.build_live_ceiling_area_source_traces(
        result,
        workspace_id=7,
        project_id="source-project",
    )
    trace = traces[quantity.quantity_id]
    assert trace.canonical_entity_ids == ("canonical-ceiling-1",)
    assert trace.source_sha256 == SOURCE_SHA
    assert trace.revision_id == "rev-1"
    assert trace.current_revision_id == "rev-1"
    assert trace.viewport_id == "vp-1"
    assert trace.source_page == "1"
    assert set(quantity.evidence_ids).issubset(set(trace.evidence_ids))

    run = ceiling_export.seal_live_ceiling_area_run(
        result,
        workspace_id=7,
        project_id="source-project",
    )
    assert len(run.quantities) == 1
    row = run.quantities[0]
    assert row.quantity_id == quantity.quantity_id
    assert row.family == "ceiling_lining"
    assert row.value == 13.270425
    assert row.object_identity_refs == ("canonical-ceiling-1",)
    assert row.trace_canonical_entity_ids == ("canonical-ceiling-1",)
    assert row.lineage_ok is True


def test_canonical_ceiling_sealing_is_deterministic() -> None:
    result = _result()
    first = ceiling_export.seal_live_ceiling_area_run(
        result,
        workspace_id=7,
        project_id="source-project",
    )
    second = ceiling_export.seal_live_ceiling_area_run(
        result,
        workspace_id=7,
        project_id="source-project",
    )

    assert first.run_id == second.run_id
    assert first.fingerprint == second.fingerprint
    assert first.to_json() == second.to_json()


def test_canonical_ceiling_sealing_rejects_trace_identity_mismatch() -> None:
    bad = replace(
        _ceiling(),
        canonical_ceiling_id="canonical-ceiling-other",
    )
    result = _result(ceiling=bad)

    assert publish_live_ceiling_area_quantities(result)[0].input_entity_ids == (
        "canonical-ceiling-other",
    )


def test_canonical_ceiling_reaches_quantified_without_customer_row() -> None:
    result = _result()
    quantities = publish_live_ceiling_area_quantities(result)
    summaries, gaps = collect_live_canonical_coverage(
        objects=result.canonical_ceilings,
        quantities=quantities,
        output_rows=(),
        registry_run_scope="canonical-ceiling-quantity",
    )

    assert gaps == {}
    assert len(summaries) == 1
    record = summaries[0].object_records[0]
    assert record.object_id == "canonical-ceiling-1"
    assert record.quantity_ids == (quantities[0].quantity_id,)

    report = build_runtime_coverage_publication(
        summaries,
        family_gaps=gaps,
    )
    family = report["family_reports"]["ceiling"]
    assert family["stage_counts"] == {
        "DETECTED": 1,
        "AUTHENTICATED": 1,
        "CANONICALIZED": 1,
        "QUANTIFIED": 1,
        "PUBLISHED": 0,
    }


def test_legacy_canonical_ceiling_seal_reaches_one_persisted_customer_row() -> None:
    result = _result()
    run = ceiling_export.seal_live_ceiling_area_run(
        result,
        workspace_id=7,
        project_id="source-project",
    )
    rows = project_live_ceiling_area_customer_rows(
        result,
        workspace_id=7,
        project_id="source-project",
    )

    assert len(run.quantities) == len(rows) == 1
    row = rows[0]
    assert row["quantity_id"] == run.quantities[0].quantity_id
    assert row["quantity_family"] == "ceiling_lining"
    assert row["quantity_status"] == "To review"
    assert row["origin"] == "AI"
    assert row["row_role"] == "ceiling_area"
    assert row["finish_system"] == "plasterboard"
    assert row["measurement_method"] == "figured_dimension"
    assert row["figured_dimension_ids"] == ["dim-h", "dim-v"]

    live_report = verify_sealed_customer_output(run, rows)
    assert live_report.valid_quantity_count == 1
    assert live_report.customer_row_count == 1

    persisted = {
        "workspace_id": row["workspace_id"],
        "section": row["section"],
        "element": row["element"],
        "location": row["location"],
        "substrate": row["substrate"],
        "finish_system": row["finish_system"],
        "quantity": row["quantity"],
        "unit": "m²",
        "quantity_status": row["quantity_status"],
        "source_page": row["source_page"],
        "source_reference": "PB Auto Geometry v1.2.19 · " + row["source_reference"],
        "inclusion_status": row["inclusion_status"],
        "confidence": "Documented",
        "notes": row["notes"],
        "row_role": row["row_role"],
    }
    persisted_report = verify_sealed_customer_output(run, [persisted])
    assert persisted_report.verified_quantity_ids == (
        run.quantities[0].quantity_id,
    )


def test_scaled_legacy_ceiling_customer_projection_preserves_scale_authority() -> None:
    ceiling = _ceiling(
        authority=MeasurementAuthorityType.PDF_SCALED.value,
        physical_scale_record_id="physical-scale-1",
        figured_dimension_ids=(),
    )
    result = _result(ceiling=ceiling)
    run = ceiling_export.seal_live_ceiling_area_run(
        result,
        workspace_id=7,
        project_id="source-project",
    )
    rows = project_live_ceiling_area_customer_rows(
        result,
        workspace_id=7,
        project_id="source-project",
    )

    assert len(run.quantities) == len(rows) == 1
    row = rows[0]
    assert row["quantity_id"] == run.quantities[0].quantity_id
    assert row["measurement_method"] == "scaled_geometry"
    assert row["resolved_scale_id"] == "physical-scale-1"
    assert row["scale_status"] == "resolved"
    assert row["scale_conflicts"] == []

    report = verify_sealed_customer_output(run, rows)
    assert report.verified_quantity_ids == (run.quantities[0].quantity_id,)


def test_exact_shadow_quantity_replay_is_idempotent() -> None:
    shadow = _shadow_quantity()
    result = replace(
        _result(),
        quantity_evidence=(shadow, shadow),
    )
    assert publish_live_ceiling_area_quantities(result) == (
        publish_live_ceiling_area_quantities(_result())
    )


def test_conflicting_shadow_quantity_id_never_publishes_ceiling_area() -> None:
    shadow = _shadow_quantity()
    conflicting = (
        replace(shadow, value=14.0),
        replace(
            shadow,
            metadata={**shadow.metadata, "viewport_id": "conflicting-viewport"},
        ),
        replace(shadow, evidence_ids=("ev-dim-h", "ev-different", "ev-finish")),
    )
    for other in conflicting:
        for values in (
            (shadow, other),
            (other, shadow),
            (shadow, other, shadow),
        ):
            result = replace(_result(), quantity_evidence=values)
            assert publish_live_ceiling_area_quantities(result) == ()



def test_duplicate_canonical_ceiling_cannot_hide_in_abstained_candidate() -> None:
    firm = _ceiling()
    unsupported = replace(
        firm,
        metric_area_complete=False,
        area_m2=0.0,
    )
    assert len(publish_live_ceiling_area_quantities(_result(ceiling=firm))) == 1
    assert publish_live_ceiling_area_quantities(_result(ceiling=unsupported)) == ()
    result = replace(
        _result(),
        canonical_ceilings=(firm, unsupported),
    )
    import pytest
    with pytest.raises(ValueError, match="duplicate canonical ceiling identity"):
        publish_live_ceiling_area_quantities(result)


def test_duplicate_unmeasured_ceiling_id_is_still_quarantined() -> None:
    unresolved = replace(_ceiling(), metric_area_complete=False, area_m2=0.0)
    result = replace(
        _result(),
        canonical_ceilings=(unresolved, unresolved),
    )
    import pytest
    with pytest.raises(ValueError, match="duplicate canonical ceiling identity"):
        publish_live_ceiling_area_quantities(result)


def test_distinct_unresolved_ceiling_does_not_suppress_firm_ceiling() -> None:
    firm = _ceiling()
    unrelated = replace(
        _ceiling(),
        canonical_ceiling_id="canonical-ceiling-unmeasured",
        ceiling_quantity_id="shadow-unavailable",
        metric_area_complete=False,
        area_m2=0.0,
    )
    result = replace(_result(), canonical_ceilings=(firm, unrelated))
    quantities = publish_live_ceiling_area_quantities(result)
    assert len(quantities) == 1
    assert quantities[0].input_entity_ids == (firm.canonical_ceiling_id,)


def test_provisional_ceiling_source_unit_must_be_square_metres() -> None:
    non_metric = replace(_shadow_quantity(), unit="ft2")
    result = _result(shadow=non_metric)
    assert publish_live_ceiling_area_quantities(result) == ()


def test_two_canonical_ceilings_cannot_repeat_one_full_room_area_source() -> None:
    original = _ceiling()
    other = replace(
        original,
        canonical_ceiling_id="canonical-ceiling-2",
        ceiling_quantity_id="qty-shadow-ceiling-2",
    )
    shadow_other = replace(
        _shadow_quantity(), quantity_id="qty-shadow-ceiling-2",
    )
    result = replace(
        _result(), canonical_ceilings=(original, other),
        quantity_evidence=(_shadow_quantity(), shadow_other),
    )
    assert publish_live_ceiling_area_quantities(result) == ()
    assert publish_live_ceiling_area_quantities(
        replace(result, canonical_ceilings=(other, original)),
    ) == ()


def test_unmeasured_ceiling_without_positive_source_does_not_poison_firm() -> None:
    original = _ceiling()
    unresolved = replace(
        original,
        canonical_ceiling_id="canonical-ceiling-unmeasured",
        ceiling_quantity_id="",
        metric_area_complete=False,
        area_m2=None,
    )
    result = replace(
        _result(), canonical_ceilings=(original, unresolved),
    )
    expected = publish_live_ceiling_area_quantities(_result())
    assert len(expected) == 1
    assert publish_live_ceiling_area_quantities(result) == expected
    assert publish_live_ceiling_area_quantities(
        replace(result, canonical_ceilings=(unresolved, original))
    ) == expected


def test_different_room_area_sources_keep_independent_ceilings() -> None:
    first = _ceiling()
    second = replace(
        first,
        canonical_ceiling_id="canonical-ceiling-2",
        room_entity_id="room-2",
        room_area_quantity_id="qty-room-area-2",
        ceiling_quantity_id="qty-shadow-ceiling-2",
        source_room_index_id="room-index-2",
    )
    shadow_other = replace(
        _shadow_quantity(),
        quantity_id="qty-shadow-ceiling-2",
        semantic_key="ceiling_lining:room-2",
        input_entity_ids=("room-2",),
        metadata={
            **dict(_shadow_quantity().metadata),
            "upstream_area_quantity_id": "qty-room-area-2",
        },
    )
    result = replace(
        _result(), canonical_ceilings=(first, second),
        quantity_evidence=(_shadow_quantity(), shadow_other),
    )
    published = publish_live_ceiling_area_quantities(result)
    assert len(published) == 2
    assert {q.input_entity_ids for q in published} == {
        ("canonical-ceiling-1",), ("canonical-ceiling-2",),
    }


def test_single_figured_dimension_cannot_claim_full_metric_ceiling_area() -> None:
    for dimension_ids in (
        ("dim-h",),
        ("dim-h", "dim-h"),
        ("", "dim-h", ""),
    ):
        candidate = _ceiling(figured_dimension_ids=dimension_ids)
        assert publish_live_ceiling_area_quantities(
            _result(ceiling=candidate)
        ) == ()


def test_two_distinct_figured_dimension_receipts_retain_firm_ceiling_area() -> None:
    candidate = _ceiling(figured_dimension_ids=("dim-h", "dim-v"))
    published = publish_live_ceiling_area_quantities(_result(ceiling=candidate))
    assert len(published) == 1
    assert published[0].authority == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
    assert published[0].value == 13.270425


def test_two_distinct_area_receipt_ids_cannot_mint_two_full_ceilings_for_one_room() -> None:
    original = _ceiling()
    alternative = replace(
        original,
        canonical_ceiling_id="canonical-ceiling-alternative-full-area",
        ceiling_quantity_id="qty-shadow-ceiling-alternative",
        room_area_quantity_id="qty-room-area-alternative",
    )
    source_alternative = replace(
        _shadow_quantity(),
        quantity_id="qty-shadow-ceiling-alternative",
        metadata={
            **dict(_shadow_quantity().metadata),
            "upstream_area_quantity_id": "qty-room-area-alternative",
        },
    )
    # Both pass all existing individual-source and area checks, and neither
    # shares an upstream quantity ID. The collision is the *physical room*.
    first = publish_live_ceiling_area_quantities(_result())
    alternate = publish_live_ceiling_area_quantities(
        _result(ceiling=alternative, shadow=source_alternative)
    )
    assert len(first) == len(alternate) == 1
    result = replace(
        _result(),
        canonical_ceilings=(original, alternative),
        quantity_evidence=(_shadow_quantity(), source_alternative),
    )
    assert publish_live_ceiling_area_quantities(result) == ()
    assert publish_live_ceiling_area_quantities(
        replace(result, canonical_ceilings=(alternative, original))
    ) == ()


def test_different_rooms_with_distinct_area_sources_do_not_quarantine_each_other() -> None:
    first = _ceiling()
    second = replace(
        first,
        canonical_ceiling_id="canonical-ceiling-room-2",
        room_entity_id="room-2",
        room_area_quantity_id="qty-room-area-2",
        ceiling_quantity_id="qty-shadow-ceiling-room-2",
    )
    secondary_source = replace(
        _shadow_quantity(),
        quantity_id="qty-shadow-ceiling-room-2",
        input_entity_ids=("room-2",),
        semantic_key="ceiling_lining:room-2",
        metadata={
            **dict(_shadow_quantity().metadata),
            "upstream_area_quantity_id": "qty-room-area-2",
        },
    )
    result = replace(
        _result(),
        canonical_ceilings=(first, second),
        quantity_evidence=(_shadow_quantity(), secondary_source),
    )
    quantities = publish_live_ceiling_area_quantities(result)
    assert len(quantities) == 2
    assert {q.input_entity_ids for q in quantities} == {
        ("canonical-ceiling-1",), ("canonical-ceiling-room-2",)
    }


def test_final_ceiling_area_rejects_invalid_figured_receipt_collection_type() -> None:
    # This is the FINAL source→FIRM publication boundary. An upstream guard
    # cannot be assumed: caller-supplied canonical surfaces remain untrusted.
    for invalid in (
        "HV", "dim-h,dim-v",
        {"horizontal": "dim-h", "vertical": "dim-v"},
        ("dim-h", 123), ("dim-h", None),
        ["dim-h", ["dim-v"]],
    ):
        candidate = replace(_ceiling(), figured_dimension_ids=invalid)
        assert publish_live_ceiling_area_quantities(_result(ceiling=candidate)) == ()


def test_final_ceiling_area_keeps_genuine_two_native_source_receipts() -> None:
    for source_ids in (
        ["dim-v", "dim-h"],
        ("dim-h", "dim-v", "dim-h"),
    ):
        candidate = replace(_ceiling(), figured_dimension_ids=source_ids)
        published = publish_live_ceiling_area_quantities(_result(ceiling=candidate))
        assert len(published) == 1
        assert published[0].metadata["figured_dimension_ids"] == ("dim-h", "dim-v")
        assert published[0].status == AuthorityStatus.FIRM.value


def test_final_ceiling_area_does_not_use_figured_guard_to_block_scaled_source() -> None:
    candidate = replace(
        _ceiling(
            authority=MeasurementAuthorityType.PDF_SCALED.value,
            physical_scale_record_id="authenticated-scale-1",
            figured_dimension_ids=(),
        ),
        figured_dimension_ids="invalid-figured-only-for-scaled-authority",
    )
    published = publish_live_ceiling_area_quantities(_result(ceiling=candidate))
    assert len(published) == 1
    assert published[0].metadata["resolved_scale_id"] == "authenticated-scale-1"


def test_ceiling_area_rejects_missing_duplicate_or_blank_original_source_receipts():
    shadow = _shadow_quantity()
    ceiling = _ceiling()
    for bad_receipts in (
        ("ev-dim-h", "ev-dim-h", "ev-finish"),
        ("ev-dim-h", "   ", "ev-finish"),
        ("ev-dim-h", "", "ev-finish"),
        (),
    ):
        bad_source = copy(shadow)
        object.__setattr__(bad_source, "evidence_ids", bad_receipts)
        assert publish_live_ceiling_area_quantities(_result(shadow=bad_source)) == ()
        bad_ceiling = replace(ceiling, evidence_ids=bad_receipts)
        assert publish_live_ceiling_area_quantities(_result(ceiling=bad_ceiling)) == ()
    assert len(publish_live_ceiling_area_quantities(_result())) == 1


def test_ceiling_area_rejects_foreign_original_source_document_or_room_snapshot():
    shadow = _shadow_quantity()
    for key, value in (
        ("document_id", "foreign-document"),
        ("room_snapshot_id", "foreign-room-snapshot"),
    ):
        foreign = replace(
            shadow, metadata={**dict(shadow.metadata), key: value},
        )
        assert publish_live_ceiling_area_quantities(_result(shadow=foreign)) == ()

    same_source = replace(
        shadow,
        metadata={
            **dict(shadow.metadata),
            "document_id": _ceiling().document_id,
            "room_snapshot_id": _ceiling().snapshot_id,
        },
    )
    assert len(publish_live_ceiling_area_quantities(_result(shadow=same_source))) == 1
