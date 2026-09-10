"""Focused regressions for the five remaining post-ad2a544 control-plane blockers.

Does not promote opening counts, change gold/scoring, or inspect the holdout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_migration_claim_arbiter import arbitrate_claims, assert_exactly_one_selected
from pb_migration_contracts import MigrationAuthorityState, QuantityEvidence
from pb_migration_decision_ledger import MigrationDecisionLedger
from pb_migration_family_router import FamilyAuthorityRouter, FamilyRouterError
from pb_migration_measurement_authority_binder import (
    MeasurementAuthorityBindingError,
    bind_commercial_measurement_authority,
)
from pb_migration_provider_envelope import EligibilityDecision, ProviderContext, ProviderResult
from pb_migration_report import MigrationReportError, build_migration_report
from pb_migration_source_trace_binder import (
    SourceTraceBindingError,
    bind_multi_source_provenance,
)
from pb_opening_count_control_adapter import opening_count_descriptor
from pb_page_scale_calibration_authority import (
    ScaleCalibrationStatus,
    ScaleSourceType,
    measurement_authority_for_page_scale,
)


SHA = "ab" * 32


def _qty(
    key: str,
    value: float | None = 1.0,
    *,
    family: str = "opening_count",
    abstained: bool = False,
    extra_meta: dict | None = None,
    quantity_id: str | None = None,
    authority: str = "schedule_extracted",
    evidence_ids: tuple[str, ...] = ("ev_1",),
    status: str | None = None,
) -> QuantityEvidence:
    meta = {
        "document_id": "doc_1",
        "source_sha256": SHA,
        "source_page": 1,
        "page": 1,
        **(extra_meta or {}),
    }
    kwargs = dict(
        quantity_id=quantity_id or f"qty_{key}_{value}",
        family=family,
        semantic_key=key,
        value=None if abstained else value,
        unit="ea",
        evidence_ids=evidence_ids,
        authority=authority,
        status=status or ("blocked" if abstained else "provisional"),
        confidence=0.0 if abstained else 0.8,
        metadata=meta,
    )
    if abstained:
        kwargs.update(abstained=True, blocking_reasons=("ambiguous_identity",))
    return QuantityEvidence(**kwargs)


def _context(**overrides) -> ProviderContext:
    payload = dict(
        run_id="run_1",
        workspace_id="ws_1",
        project_id="proj_1",
        document_id="doc_1",
        source_sha256=SHA,
        revision_id="rev-a",
        current_revision_id="rev-a",
        selected_pages=(0,),
        owned_viewport_ids=("vp_1",),
        evidence_snapshot_id="evsnap_1",
        measurement_authority_snapshot_id="meas_1",
        workspace_record_id=1,
    )
    payload.update(overrides)
    return ProviderContext(**payload)


def _router(tmp_path: Path) -> FamilyAuthorityRouter:
    return FamilyAuthorityRouter(MigrationDecisionLedger(tmp_path / "migration.sqlite"))


def _owned_context() -> ProviderContext:
    return _context(
        selected_pages=(1, 4),
        owned_page_numbers=(1, 2, 5),
        owned_viewport_ids=("vp_1", "vp_plan", "vp_sched", "vp_extra"),
        viewport_page_ownership=(("vp_plan", 2), ("vp_sched", 5), ("vp_extra", 99)),
    )


def _valid_scale(
    *,
    status: str = ScaleCalibrationStatus.VALID.value,
    source_type: str = ScaleSourceType.SCALE_BAR.value,
) -> ScaleCalibration:
    return ScaleCalibration(
        page_no=1,
        ratio_str="1:50",
        px_per_m=56.7,
        method="SCALE_BAR",
        is_verified=True,
        confidence=1.0,
        source_type=source_type,
        status=status,
    )


def _scaled_qty(**meta) -> QuantityEvidence:
    return _qty(
        "LEN",
        3.0,
        family="figured_dimension",
        extra_meta={"source_page": 1, **meta},
        authority=MeasurementAuthorityType.PDF_SCALED.value,
    )


def _report(**overrides):
    payload = dict(
        family="opening_count",
        descriptor=opening_count_descriptor(),
        migration_state=MigrationAuthorityState.NEW_SHADOW.value,
        source_set_fingerprint="src",
        evaluated_commit="test",
        eligible=24,
        eligible_keys=(),
        frozen_new=tuple(_qty(f"W{index}", 1.0) for index in range(1, 16)),
        holdout_status="NOT_RUN",
        gate_decision="HOLD",
        gate_reasons=("remain_new_shadow",),
    )
    payload.update(overrides)
    return build_migration_report(**payload)


def test_provisional_title_block_cannot_emit_scaled_geometry() -> None:
    calibration = _valid_scale(source_type=ScaleSourceType.TITLE_BLOCK.value)
    assert measurement_authority_for_page_scale(calibration) == AuthorityStatus.PROVISIONAL.value
    with pytest.raises(MeasurementAuthorityBindingError, match="FIRM|provisional"):
        bind_commercial_measurement_authority(
            _scaled_qty(),
            scaled_mm=3000.0,
            scale_calibration=calibration,
            trusted_scale_id="control_plane_scale_1",
        )


def test_provisional_status_cannot_emit_scaled_geometry() -> None:
    calibration = _valid_scale(status=ScaleCalibrationStatus.PROVISIONAL.value)
    assert measurement_authority_for_page_scale(calibration) == AuthorityStatus.PROVISIONAL.value
    with pytest.raises(MeasurementAuthorityBindingError, match="FIRM|provisional|unresolved"):
        bind_commercial_measurement_authority(
            _scaled_qty(),
            scaled_mm=3000.0,
            scale_calibration=calibration,
        )


def test_firm_scale_bar_still_emits_scaled_geometry() -> None:
    calibration = _valid_scale()
    assert measurement_authority_for_page_scale(calibration) == AuthorityStatus.FIRM.value
    bound = bind_commercial_measurement_authority(
        _scaled_qty(scale_status="valid", scale_id="control_plane_scale_1"),
        scaled_mm=3000.0,
        scale_calibration=calibration,
        trusted_scale_id="control_plane_scale_1",
    )
    assert bound.method == "scaled_geometry"
    assert bound.resolved_scale_id == "control_plane_scale_1"


def test_report_rejects_precision_without_numerator() -> None:
    with pytest.raises(MigrationReportError, match="precision.*numerator"):
        _report(precision=1.0)


def test_report_rejects_exactness_without_numerator() -> None:
    with pytest.raises(MigrationReportError, match="exact_correctness.*numerator"):
        _report(exact_among_answered=1.0)


def test_report_rejects_recall_without_numerator() -> None:
    with pytest.raises(MigrationReportError, match="recall.*numerator"):
        _report(recall=15 / 24)


def test_report_rejects_inconsistent_ratio_vs_counts() -> None:
    with pytest.raises(MigrationReportError, match="precision"):
        _report(precision=0.9, precision_correct_count=15)


def test_report_provenance_completeness_is_traced_over_answered() -> None:
    report = _report(missing_provenance=3)
    integrity = report.payload["integrity"]
    assert integrity["answered"] == 15
    assert integrity["fully_traced_answered"] == 12
    assert integrity["provenance_completeness"] == pytest.approx(12 / 15)
    assert integrity["provenance_denominator"] == "answered"


def test_report_zero_answered_ratios_are_zero() -> None:
    report = _report(
        frozen_new=(_qty("W1", abstained=True),),
        exact_correct_count=0,
        precision_correct_count=0,
        recall_correct_count=0,
        missing_provenance=0,
    )
    assert report.payload["population"]["answered"] == 0
    assert report.payload["population"]["eligible"] == 24
    assert report.payload["population"]["abstained"] == 1
    assert report.payload["accuracy"]["coverage"] == 0.0
    assert report.payload["accuracy"]["exact_correctness_among_answered"] == 0.0
    assert report.payload["accuracy"]["precision"] == 0.0
    assert report.payload["accuracy"]["recall"] == 0.0
    assert report.payload["accuracy"]["zero_denominator_policy"] == "ratio_is_0.0"
    assert report.payload["integrity"]["provenance_completeness"] == 0.0
    assert report.payload["integrity"]["fully_traced_answered"] == 0


def test_registered_provider_result_is_accepted(tmp_path: Path) -> None:
    context = _context()
    descriptor = opening_count_descriptor()
    routed = _router(tmp_path).route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
        new_result=ProviderResult.build(descriptor=descriptor, context=context, quantities=(_qty("W1", 6),)),
    )
    assert routed.new_ran is True
    assert all(item.selected_authority == "legacy" for item in routed.selected)


def test_same_family_substitute_provider_is_rejected(tmp_path: Path) -> None:
    context = _context()
    trusted = opening_count_descriptor()
    substitute = type(trusted)(
        provider_id="other_opening_provider",
        family="opening_count",
        provider_version=trusted.provider_version,
        output_schema_version=trusted.output_schema_version,
        code_fingerprint="b" * 64,
    )
    result = ProviderResult.build(descriptor=substitute, context=context, quantities=(_qty("W1", 6),))
    with pytest.raises(FamilyRouterError, match="descriptor|provider"):
        _router(tmp_path).route(
            family="opening_count",
            context=context,
            legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
            new_result=result,
        )


def test_same_provider_wrong_version_is_rejected(tmp_path: Path) -> None:
    context = _context()
    trusted = opening_count_descriptor()
    wrong = type(trusted)(
        provider_id=trusted.provider_id,
        family=trusted.family,
        provider_version="9.9.9",
        output_schema_version=trusted.output_schema_version,
        code_fingerprint=trusted.code_fingerprint,
    )
    result = ProviderResult.build(descriptor=wrong, context=context, quantities=(_qty("W1", 6),))
    with pytest.raises(FamilyRouterError, match="descriptor|fingerprint"):
        _router(tmp_path).route(
            family="opening_count",
            context=context,
            legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
            new_result=result,
        )


def test_wrong_code_fingerprint_is_rejected(tmp_path: Path) -> None:
    context = _context()
    trusted = opening_count_descriptor()
    wrong = type(trusted)(
        provider_id=trusted.provider_id,
        family=trusted.family,
        provider_version=trusted.provider_version,
        output_schema_version=trusted.output_schema_version,
        code_fingerprint="c" * 64,
    )
    result = ProviderResult.build(descriptor=wrong, context=context, quantities=(_qty("W1", 6),))
    with pytest.raises(FamilyRouterError, match="descriptor|fingerprint"):
        _router(tmp_path).route(
            family="opening_count",
            context=context,
            legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
            new_result=result,
        )


def test_registered_provider_cross_context_replay_is_rejected(tmp_path: Path) -> None:
    context_a = _context()
    context_b = _context(source_sha256="cd" * 32, document_id="doc_other")
    result = ProviderResult.build(
        descriptor=opening_count_descriptor(),
        context=context_a,
        quantities=(_qty("W1", 6),),
    )
    with pytest.raises(FamilyRouterError, match="context"):
        _router(tmp_path).route(
            family="opening_count",
            context=context_b,
            legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
            new_result=result,
        )


def _selective_router(tmp_path: Path) -> FamilyAuthorityRouter:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=opening_count_descriptor(),
        reason="test_only_not_a_promotion",
    )
    return router


def test_same_key_accepted_and_abstained_is_unresolved(tmp_path: Path) -> None:
    context = _context()
    routed = _selective_router(tmp_path).route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("D1", 2, quantity_id="legacy_d1"),),
        new_result=ProviderResult.build(
            descriptor=opening_count_descriptor(),
            context=context,
            quantities=(
                _qty("D1", 2, quantity_id="accepted_d1"),
                _qty("D1", abstained=True, quantity_id="abstained_d1"),
            ),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("D1",)),
    )
    assert routed.selected[0].claim.semantic_key == "D1"
    assert routed.selected[0].selected_authority == "legacy"
    assert routed.selected[0].fallback_reason == "unresolved_authority_conflict"
    assert routed.selected[0].quantity.quantity_id == "legacy_d1"
    assert "unresolved_mixed_claim" in routed.arbitration.kinds
    assert_exactly_one_selected(routed.selected_keys())


def test_same_key_accepted_and_blocked_is_unresolved(tmp_path: Path) -> None:
    context = _context()
    routed = _selective_router(tmp_path).route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("D1", 2, quantity_id="legacy_d1"),),
        new_result=ProviderResult.build(
            descriptor=opening_count_descriptor(),
            context=context,
            quantities=(
                _qty("D1", 2, quantity_id="accepted_d1"),
                _qty("D1", 2, quantity_id="blocked_d1", status="blocked"),
            ),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("D1",)),
    )
    assert routed.selected[0].selected_authority == "legacy"
    assert routed.selected[0].fallback_reason == "unresolved_authority_conflict"
    assert "unresolved_mixed_claim" in routed.arbitration.kinds


def test_same_key_accepted_and_conflicting_is_unresolved(tmp_path: Path) -> None:
    context = _context()
    routed = _selective_router(tmp_path).route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("D1", 2, quantity_id="legacy_d1"),),
        new_result=ProviderResult.build(
            descriptor=opening_count_descriptor(),
            context=context,
            quantities=(
                _qty("D1", 2, quantity_id="d1_a"),
                _qty("D1", 3, quantity_id="d1_b"),
            ),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("D1",)),
    )
    assert routed.selected[0].selected_authority == "legacy"
    assert routed.selected[0].fallback_reason == "unresolved_authority_conflict"
    assert "conflicting_new_claims" in routed.arbitration.kinds


def test_unrelated_accepted_and_abstained_claims_remain_independent(tmp_path: Path) -> None:
    context = _context()
    routed = _selective_router(tmp_path).route(
        family="opening_count",
        context=context,
        legacy_quantities=(
            _qty("W1", 4, quantity_id="legacy_w1"),
            _qty("D1", 2, quantity_id="legacy_d1"),
        ),
        new_result=ProviderResult.build(
            descriptor=opening_count_descriptor(),
            context=context,
            quantities=(
                _qty("W1", 6, quantity_id="new_w1"),
                _qty("D1", abstained=True, quantity_id="abstained_d1"),
            ),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1", "D1")),
    )
    by_key = {item.claim.semantic_key: item for item in routed.selected}
    assert by_key["W1"].selected_authority == "new"
    assert by_key["W1"].quantity.quantity_id == "new_w1"
    assert by_key["D1"].selected_authority == "legacy"
    assert by_key["D1"].fallback_reason == "new_abstention_fallback"
    assert "unresolved_mixed_claim" not in routed.arbitration.kinds
    assert_exactly_one_selected(routed.selected_keys())


def test_valid_multisource_contributors_are_all_owned() -> None:
    qty = _qty("W1", 6, extra_meta={"source_pages": [2, 5], "source_page": 2}, evidence_ids=("ev_a", "ev_b"))
    provenance = bind_multi_source_provenance(
        qty,
        _owned_context(),
        contributing_pages=(2, 5),
        contributing_viewports=("vp_plan", "vp_sched"),
    )
    assert [item.page for item in provenance.contributors] == [2, 5]
    assert [item.viewport_id for item in provenance.contributors] == ["vp_plan", "vp_sched"]
    assert [item.evidence_id for item in provenance.contributors] == ["ev_a", "ev_b"]


def test_extra_viewport_contributor_is_rejected() -> None:
    qty = _qty("W1", 6, evidence_ids=("ev_a", "ev_b"))
    with pytest.raises(SourceTraceBindingError, match="cardinality|viewport"):
        bind_multi_source_provenance(
            qty,
            _owned_context(),
            contributing_pages=(2, 5),
            contributing_viewports=("vp_plan", "vp_sched", "vp_extra"),
        )


def test_extra_evidence_contributor_is_rejected() -> None:
    qty = _qty("W1", 6, evidence_ids=("ev_a", "ev_b", "ev_extra"))
    with pytest.raises(SourceTraceBindingError, match="cardinality|evidence"):
        bind_multi_source_provenance(
            qty,
            _owned_context(),
            contributing_pages=(2, 5),
            contributing_viewports=("vp_plan", "vp_sched"),
        )


def test_mismatched_contributor_cardinality_is_rejected() -> None:
    qty = _qty("W1", 6, evidence_ids=("ev_a", "ev_b"))
    with pytest.raises(SourceTraceBindingError, match="cardinality"):
        bind_multi_source_provenance(
            qty,
            _owned_context(),
            contributing_pages=(2, 5),
            contributing_viewports=("vp_plan",),
        )


def test_viewport_attached_to_wrong_page_is_rejected() -> None:
    qty = _qty("W1", 6, extra_meta={"source_page": 5}, evidence_ids=("ev_a", "ev_b"))
    with pytest.raises(SourceTraceBindingError, match="owned by page"):
        bind_multi_source_provenance(
            qty,
            _owned_context(),
            contributing_pages=(5, 2),
            contributing_viewports=("vp_plan", "vp_sched"),
        )


def test_cross_document_contributor_is_rejected() -> None:
    qty = _qty(
        "W1",
        6,
        extra_meta={"document_id": "doc_other", "source_page": 2},
        evidence_ids=("ev_a", "ev_b"),
    )
    with pytest.raises(SourceTraceBindingError, match="document"):
        bind_multi_source_provenance(
            qty,
            _owned_context(),
            contributing_pages=(2, 5),
            contributing_viewports=("vp_plan", "vp_sched"),
        )
