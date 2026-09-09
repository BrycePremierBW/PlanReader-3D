"""M5 regressions for QuantityEvidence -> commercial takeoff projection."""
from __future__ import annotations

import inspect

import pytest

import pb_quantity_takeoff_adapter as adapter
from pb_migration_contracts import QuantityEvidence
from pb_takeoff_authority_v164 import (
    prepare_ai_takeoff_editor_save,
    takeoff_row_publishability,
    takeoff_row_pricing_authority,
    is_jobhub_eligible_row,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def quantity(**overrides) -> QuantityEvidence:
    data = {
        "quantity_id": "qty-1",
        "family": "test_family",
        "semantic_key": "wall.area",
        "value": 12.5,
        "unit": "m²",
        "input_entity_ids": ("entity-1",),
        "formula": "L*H",
        "formula_version": "1",
        "evidence_ids": ("ev-1",),
        "authority": "figured_dimension",
        "status": "corroborated",
        "confidence": 0.99,
        "metadata": {
            "workspace_id": 7,
            "project_id": "project-7",
            "document_id": "doc-1",
            "source_sha256": SHA_A,
            "revision_id": "rev-3",
            "section": "Internal",
            "location": "Level 1",
        },
    }
    data.update(overrides)
    return QuantityEvidence(**data)


def source_trace(**overrides) -> adapter.CommercialTakeoffSourceTrace:
    data = {
        "workspace_id": 7,
        "project_id": "project-7",
        "document_id": "doc-1",
        "source_sha256": SHA_A,
        "source_page": "A-101 / p3",
        "viewport_id": "vp-3-main",
        "revision_id": "rev-3",
        "current_revision_id": "rev-3",
        "evidence_ids": ("ev-1",),
        "canonical_entity_ids": ("entity-1",),
        "source_bbox": (10.0, 20.0, 300.0, 420.0),
    }
    data.update(overrides)
    return adapter.CommercialTakeoffSourceTrace(**data)


def figured(**overrides) -> adapter.CommercialMeasurementAuthority:
    data = {
        "method": "figured_dimension",
        "figured_dimension_ids": ("dim-1", "dim-2"),
        "scale_status": "conflict",
        "scale_conflicts": ("scale note disagrees with title block",),
    }
    data.update(overrides)
    return adapter.CommercialMeasurementAuthority(**data)


def scaled(**overrides) -> adapter.CommercialMeasurementAuthority:
    data = {
        "method": "scaled_geometry",
        "resolved_scale_id": "scale-1",
        "scale_status": "resolved",
    }
    data.update(overrides)
    return adapter.CommercialMeasurementAuthority(**data)


def test_source_document_page_viewport_entity_and_evidence_trace_is_preserved() -> None:
    row = adapter.quantity_evidence_to_takeoff_output_row(
        quantity(), trace=source_trace(), authority=figured()
    )
    assert row is not None
    assert row["workspace_id"] == 7
    assert row["project_id"] == "project-7"
    assert row["document_id"] == "doc-1"
    assert row["source_sha256"] == SHA_A
    assert row["source_page"] == "A-101 / p3"
    assert row["viewport_id"] == "vp-3-main"
    assert row["source_bbox"] == [10.0, 20.0, 300.0, 420.0]
    assert row["evidence_ids"] == ["ev-1"]
    assert row["canonical_entity_ids"] == ["entity-1"]
    assert SHA_A in row["source_reference"]
    assert '"canonical_entity_ids":["entity-1"]' in row["notes"]


def test_figured_dimension_authority_survives_unrelated_scale_conflict() -> None:
    row = adapter.quantity_evidence_to_takeoff_output_row(
        quantity(), trace=source_trace(), authority=figured()
    )
    assert row["measurement_method"] == "figured_dimension"
    assert row["figured_dimension_ids"] == ["dim-1", "dim-2"]
    assert row["scale_status"] == "conflict"
    assert row["scale_conflicts"] == ["scale note disagrees with title block"]


def test_scaled_geometry_requires_resolved_scale() -> None:
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="resolved/verified"):
        adapter.CommercialMeasurementAuthority(
            method="scaled_geometry",
            resolved_scale_id="scale-1",
            scale_status="ambiguous",
        )


def test_scaled_geometry_scale_conflict_fails_closed() -> None:
    with pytest.raises(adapter.CommercialTakeoffConflictError, match="scale conflicts"):
        scaled(scale_conflicts=("1:50 vs 1:100",))


def test_scaled_geometry_projection_preserves_scale_authority() -> None:
    q = quantity(authority="scaled_geometry")
    row = adapter.quantity_evidence_to_takeoff_output_row(
        q, trace=source_trace(), authority=scaled()
    )
    assert row["measurement_method"] == "scaled_geometry"
    assert row["resolved_scale_id"] == "scale-1"
    assert row["scale_status"] == "resolved"
    assert row["scale_conflicts"] == []


@pytest.mark.parametrize("field,value", [
    ("workspace_id", 99),
    ("project_id", "other-project"),
    ("document_id", "other-doc"),
    ("source_sha256", SHA_B),
    ("revision_id", "rev-2"),
])
def test_quantity_identity_metadata_mismatch_fails_closed(field: str, value: object) -> None:
    metadata = dict(quantity().metadata)
    metadata[field] = value
    with pytest.raises(adapter.CommercialTakeoffConflictError, match=field):
        adapter.quantity_evidence_to_takeoff_output_row(
            quantity(metadata=metadata), trace=source_trace(), authority=figured()
        )


def test_missing_evidence_or_entity_trace_fails_closed() -> None:
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="evidence IDs"):
        adapter.quantity_evidence_to_takeoff_output_row(
            quantity(), trace=source_trace(evidence_ids=()), authority=figured()
        )
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="canonical entity IDs"):
        adapter.quantity_evidence_to_takeoff_output_row(
            quantity(), trace=source_trace(canonical_entity_ids=()), authority=figured()
        )


def test_stale_revision_cannot_construct_commercial_source_trace() -> None:
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="stale"):
        source_trace(current_revision_id="rev-4")


def test_invalid_source_sha_cannot_construct_commercial_source_trace() -> None:
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="SHA-256"):
        source_trace(source_sha256="not-a-hash")


def test_missing_commercial_authority_fails_closed() -> None:
    q = quantity()
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="source trace"):
        adapter.quantity_evidence_to_takeoff_output_row(q, trace=None, authority=figured())
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="measurement authority"):
        adapter.quantity_evidence_to_takeoff_output_row(q, trace=source_trace(), authority=None)


def test_abstention_emits_no_row_and_never_zero() -> None:
    q = quantity(
        value=None,
        abstained=True,
        blocking_reasons=("insufficient drawing evidence",),
    )
    assert adapter.quantity_evidence_to_takeoff_output_row(
        q, trace=None, authority=None
    ) is None
    assert adapter.quantities_to_takeoff_output_rows(
        [q], traces_by_quantity_id={}, authorities_by_quantity_id={}
    ) == []


def test_high_confidence_automation_is_not_estimator_approved() -> None:
    row = adapter.quantity_evidence_to_takeoff_output_row(
        quantity(confidence=1.0), trace=source_trace(), authority=figured()
    )
    assert row["origin"] == "AI"
    assert row["quantity_status"] == "To review"
    assert row["confidence"] == 1.0
    allowed, reason = takeoff_row_publishability(row)
    assert allowed is False
    assert "reviewed by an estimator" in reason


def test_existing_estimator_review_transition_controls_approval() -> None:
    row = adapter.quantity_evidence_to_takeoff_output_row(
        quantity(), trace=source_trace(), authority=figured()
    )
    reviewed = prepare_ai_takeoff_editor_save(
        row,
        {"quantity_status": "Measured", "confidence": "Reviewed"},
    )
    assert reviewed["origin"] == "AI_REVIEWED"
    assert takeoff_row_publishability(reviewed) == (True, "PUBLISHABLE")
    assert takeoff_row_pricing_authority(reviewed) == (True, "PRICING_AUTHORISED")
    assert is_jobhub_eligible_row(reviewed) == (True, "ELIGIBLE")


def test_incomplete_scope_remains_blocked_by_existing_pricing_gate_after_review() -> None:
    q = quantity(metadata={**quantity().metadata, "inclusion_status": "CLARIFICATION"})
    row = adapter.quantity_evidence_to_takeoff_output_row(
        q, trace=source_trace(), authority=figured()
    )
    reviewed = prepare_ai_takeoff_editor_save(
        row, {"quantity_status": "Measured", "confidence": "Reviewed"}
    )
    assert takeoff_row_publishability(reviewed) == (True, "PUBLISHABLE")
    assert takeoff_row_pricing_authority(reviewed) == (False, "CLARIFICATION")
    assert is_jobhub_eligible_row(reviewed) == (False, "CLARIFICATION")


def test_zero_quantity_is_not_publishable_to_jobhub_even_after_review() -> None:
    row = adapter.quantity_evidence_to_takeoff_output_row(
        quantity(value=0.0), trace=source_trace(), authority=figured()
    )
    reviewed = prepare_ai_takeoff_editor_save(
        row, {"quantity_status": "Measured", "confidence": "Reviewed"}
    )
    assert takeoff_row_publishability(reviewed) == (True, "PUBLISHABLE")
    assert is_jobhub_eligible_row(reviewed) == (False, "ZERO_OR_INVALID_QUANTITY")


def test_invalid_unit_fails_closed_without_mapping_or_guessing() -> None:
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="unit"):
        adapter.quantity_evidence_to_takeoff_output_row(
            quantity(unit="percent"), trace=source_trace(), authority=figured()
        )


def test_quantity_publication_blocker_fails_closed() -> None:
    with pytest.raises(adapter.MissingCommercialAuthorityError, match="publication blockers"):
        adapter.quantity_evidence_to_takeoff_output_row(
            quantity(blocking_reasons=("manual check required",)),
            trace=source_trace(),
            authority=figured(),
        )


def test_quantity_conflict_status_fails_closed() -> None:
    with pytest.raises(adapter.CommercialTakeoffConflictError, match="conflicting"):
        adapter.quantity_evidence_to_takeoff_output_row(
            quantity(status="conflict"), trace=source_trace(), authority=figured()
        )


def test_duplicate_and_conflicting_semantic_claims_fail_closed() -> None:
    q1 = quantity(quantity_id="qty-1")
    q2 = quantity(quantity_id="qty-2")
    q3 = quantity(quantity_id="qty-3", value=13.0)
    traces = {"qty-1": source_trace(), "qty-2": source_trace(), "qty-3": source_trace()}
    authorities = {"qty-1": figured(), "qty-2": figured(), "qty-3": figured()}
    with pytest.raises(adapter.CommercialTakeoffConflictError, match="duplicate"):
        adapter.quantities_to_takeoff_output_rows(
            [q1, q2], traces_by_quantity_id=traces, authorities_by_quantity_id=authorities
        )
    with pytest.raises(adapter.CommercialTakeoffConflictError, match="conflicting"):
        adapter.quantities_to_takeoff_output_rows(
            [q1, q3], traces_by_quantity_id=traces, authorities_by_quantity_id=authorities
        )


def test_projection_fingerprint_binds_quantity_source_revision_and_authority() -> None:
    q = quantity()
    a = adapter.compute_commercial_projection_fingerprint(
        q, trace=source_trace(), authority=figured()
    )
    assert len(a) == 64
    assert a == adapter.compute_commercial_projection_fingerprint(
        q, trace=source_trace(), authority=figured()
    )
    assert a != adapter.compute_commercial_projection_fingerprint(
        q, trace=source_trace(source_sha256=SHA_B), authority=figured()
    )
    assert a != adapter.compute_commercial_projection_fingerprint(
        q, trace=source_trace(), authority=figured(figured_dimension_ids=("dim-9",))
    )


def test_existing_commercial_gate_wrapper_delegates_without_authority_replacement() -> None:
    row = adapter.quantity_evidence_to_takeoff_output_row(
        quantity(), trace=source_trace(), authority=figured()
    )
    results = adapter.existing_commercial_gate_results(row)
    assert results["publishability"][0] is False
    assert results["pricing"][0] is False
    assert results["jobhub"][0] is False


def test_adapter_has_no_benchmark_gold_or_extractor_dependency() -> None:
    source = inspect.getsource(adapter)
    forbidden_imports = (
        "benchmarks.public_tenders",
        "expected_project",
        "expected_boq",
        "pb_planreader_pdf_extractor",
    )
    for forbidden in forbidden_imports:
        assert forbidden not in source
