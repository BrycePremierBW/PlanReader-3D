"""Focused regressions for the seven post-e4715c2 control-plane blockers.

Does not promote opening counts, change gold/scoring, or inspect the holdout.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pb_geometry_takeoff_model import MeasurementAuthorityType, ScaleCalibration
from pb_migration_claim_arbiter import arbitrate_claims, assert_exactly_one_selected
from pb_migration_contracts import MigrationAuthorityState, QuantityEvidence
from pb_migration_family_router import FamilyAuthorityRouter, FamilyRouterError
from pb_migration_decision_ledger import MigrationDecisionLedger
from pb_migration_measurement_authority_binder import (
    MeasurementAuthorityBindingError,
    bind_commercial_measurement_authority,
)
from pb_migration_provider_envelope import (
    EligibilityDecision,
    ProviderContext,
    ProviderDescriptor,
    ProviderResult,
    ProviderResultBindingError,
    assert_provider_result_binding,
)
from pb_migration_report import MigrationReportError, build_migration_report
from pb_migration_source_trace_binder import (
    SourceTraceBindingError,
    bind_commercial_source_trace,
    bind_multi_source_provenance,
)
from pb_opening_count_control_adapter import OpeningCountControlAdapter, opening_count_descriptor
from pb_page_scale_calibration_authority import (
    ScaleCalibrationStatus,
    ScaleSourceType,
    unknown_calibration,
)
from pb_provider_gold_isolation import inspect_provider_isolation
from pb_provider_runtime_isolation import (
    assert_staged_workspace_has_no_gold_resources,
    run_staged_provider_extract,
    stage_production_provider_workspace,
)
from pb_shadow_opening_count_provider import ShadowOpeningCountProvider


SHA = "ab" * 32
REPO_ROOT = Path(__file__).resolve().parents[1]


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
        status="blocked" if abstained else "provisional",
        confidence=0.0 if abstained else 0.8,
        metadata=meta,
    )
    if abstained:
        kwargs.update(abstained=True, blocking_reasons=("ambiguous_identity",))
    return QuantityEvidence(**kwargs)


def _descriptor(**overrides) -> ProviderDescriptor:
    base = opening_count_descriptor()
    payload = dict(
        provider_id=base.provider_id,
        family=base.family,
        provider_version=base.provider_version,
        output_schema_version=base.output_schema_version,
        code_fingerprint=base.code_fingerprint,
    )
    payload.update(overrides)
    return ProviderDescriptor(**payload)


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
        canonical_graph_snapshot_id=None,
        measurement_authority_snapshot_id="meas_1",
        source_pdf=None,
        workspace_record_id=1,
    )
    payload.update(overrides)
    return ProviderContext(**payload)


def _router(tmp_path: Path) -> FamilyAuthorityRouter:
    return FamilyAuthorityRouter(MigrationDecisionLedger(tmp_path / "migration.sqlite"))


def _valid_scale(
    page_no: int = 1,
    *,
    status: str = ScaleCalibrationStatus.VALID.value,
    ratio_str: str = "1:50",
    source_type: str = ScaleSourceType.SCALE_BAR.value,
) -> ScaleCalibration:
    return ScaleCalibration(
        page_no=page_no,
        ratio_str=ratio_str,
        px_per_m=56.7,
        method="SCALE_BAR",
        is_verified=status in {
            ScaleCalibrationStatus.VALID.value,
            ScaleCalibrationStatus.USER_APPROVED.value,
        },
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
        descriptor=_descriptor(),
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


def test_parent_init_direct_gold_import_detected() -> None:
    report = inspect_provider_isolation(
        "parent_init_only_leaf",
        "tests.fixtures.migration_isolation.parent_init_only.leaf",
    )
    assert report.ok is False
    assert any("pb_public_tender_benchmark" in item.reason for item in report.findings)
    assert any(
        "parent_init_only" in "->".join(item.via) and "leaf" in "->".join(item.via)
        for item in report.findings
    )


def test_parent_init_relative_helper_gold_import_detected() -> None:
    report = inspect_provider_isolation(
        "parent_init_rel_leaf",
        "tests.fixtures.migration_isolation.parent_init_rel.leaf",
    )
    assert report.ok is False
    assert any("pb_benchmark_accuracy_engine" in item.reason for item in report.findings)
    assert any("helper" in "->".join(item.via) for item in report.findings)
    assert any("parent_init_rel" in "->".join(item.via) for item in report.findings)


def test_parent_init_aliased_nested_eval_import_detected() -> None:
    report = inspect_provider_isolation(
        "parent_init_nested_leaf",
        "tests.fixtures.migration_isolation.parent_init_nested.inner.leaf",
    )
    assert report.ok is False
    assert any("pb_shadow_opening_count_eval" in item.reason for item in report.findings)
    assert any("parent_init_nested.inner" in "->".join(item.via) for item in report.findings)


def test_parent_init_package_level_root_still_detected() -> None:
    report = inspect_provider_isolation(
        "parent_init_only_pkg",
        "tests.fixtures.migration_isolation.parent_init_only",
    )
    assert report.ok is False
    assert any("pb_public_tender_benchmark" in item.reason for item in report.findings)


def test_trusted_scale_rejects_missing_calibration() -> None:
    with pytest.raises(MeasurementAuthorityBindingError, match="trusted control-plane scale"):
        bind_commercial_measurement_authority(_scaled_qty(), scaled_mm=3000.0)


def test_trusted_scale_rejects_provider_self_certified_resolved() -> None:
    with pytest.raises(MeasurementAuthorityBindingError, match="self-certify"):
        bind_commercial_measurement_authority(
            _scaled_qty(scale_status="resolved"),
            scaled_mm=3000.0,
            scale_calibration=unknown_calibration(1),
        )


def test_trusted_scale_rejects_status_disagreement() -> None:
    with pytest.raises(MeasurementAuthorityBindingError, match="disagrees"):
        bind_commercial_measurement_authority(
            _scaled_qty(scale_status="valid"),
            scaled_mm=3000.0,
            scale_calibration=_valid_scale(status=ScaleCalibrationStatus.CONFLICTING.value),
        )


def test_trusted_scale_rejects_stale_or_invented_scale_id() -> None:
    calibration = _valid_scale()
    with pytest.raises(MeasurementAuthorityBindingError, match="stale or invented"):
        bind_commercial_measurement_authority(
            _scaled_qty(scale_id="provider_invented_scale"),
            scaled_mm=3000.0,
            scale_calibration=calibration,
            trusted_scale_id="control_plane_scale_1",
        )


def test_trusted_scale_rejects_unresolved_and_conflicting() -> None:
    with pytest.raises(MeasurementAuthorityBindingError, match="unresolved"):
        bind_commercial_measurement_authority(
            _scaled_qty(),
            scaled_mm=3000.0,
            scale_calibration=unknown_calibration(1),
        )
    with pytest.raises(MeasurementAuthorityBindingError, match="unresolved"):
        bind_commercial_measurement_authority(
            _scaled_qty(),
            scaled_mm=3000.0,
            scale_calibration=_valid_scale(status=ScaleCalibrationStatus.CONFLICTING.value),
        )


def test_trusted_scale_accepts_control_plane_valid_identity() -> None:
    bound = bind_commercial_measurement_authority(
        _scaled_qty(scale_status="valid", scale_id="control_plane_scale_1"),
        scaled_mm=3000.0,
        scale_calibration=_valid_scale(),
        trusted_scale_id="control_plane_scale_1",
    )
    assert bound.resolved_scale_id == "control_plane_scale_1"
    assert bound.scale_status == "resolved"
    assert bound.metadata["scale_from"] == "trusted_control_plane_calibration"
    assert bound.metadata["trusted_scale_status"] == "valid"


def test_report_rejects_inconsistent_precomputed_coverage() -> None:
    with pytest.raises(MigrationReportError, match="coverage"):
        _report(precomputed_coverage=0.9)


def test_report_rejects_inconsistent_exact_and_precision_counts() -> None:
    with pytest.raises(MigrationReportError, match="exact_correctness"):
        _report(exact_among_answered=1.0, exact_correct_count=0)
    with pytest.raises(MigrationReportError, match="precision"):
        _report(precision=1.0, precision_correct_count=0)


def test_report_rejects_relabeling_coverage_as_accuracy() -> None:
    with pytest.raises(MigrationReportError, match="accuracy"):
        _report(extra={"accuracy": 15 / 24})


def test_report_computes_coverage_from_counts_and_keeps_abstentions() -> None:
    answered = tuple(_qty(f"W{index}", 1.0) for index in range(1, 16))
    abstained = _qty("W99", abstained=True)
    report = _report(
        frozen_new=answered + (abstained,),
        exact_among_answered=1.0,
        exact_correct_count=15,
        precision=1.0,
        precision_correct_count=15,
        recall=15 / 24,
        recall_correct_count=15,
        precomputed_coverage=15 / 24,
    )
    accuracy = report.payload["accuracy"]
    population = report.payload["population"]
    assert population["eligible"] == 24
    assert population["answered"] == 15
    assert population["abstained"] == 1
    assert accuracy["coverage"] == pytest.approx(15 / 24)
    assert accuracy["coverage_answered_over_evaluation_eligible"] == pytest.approx(15 / 24)
    assert accuracy["exact_denominator"] == "answered"
    assert accuracy["precision_denominator"] == "answered"
    assert accuracy["recall_denominator"] == "evaluation_eligible_includes_abstentions"
    assert accuracy["not_canonical_benchmark_accuracy"] is True
    assert "15/24" not in json.dumps(report.payload.get("extra") or {})


def test_runtime_isolation_paths_are_portable(tmp_path: Path) -> None:
    import fitz

    pdf = tmp_path / "schedule.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "DRAWING TITLE: WINDOW & DOOR SCHEDULE", fontsize=10)
    doc.save(pdf)
    doc.close()
    repo = Path(__file__).resolve().parents[1]
    assert repo.is_dir()
    workspace = stage_production_provider_workspace(
        tmp_path / "portable-stage",
        pdf,
        repo_root=repo,
    )
    assert_staged_workspace_has_no_gold_resources(workspace)
    out = tmp_path / "isolated.json"
    proc = run_staged_provider_extract(workspace, out)
    assert proc.returncode == 0
    script = repo / "scripts" / "run_isolated_opening_count_extract.py"
    cli_out = tmp_path / "cli.json"
    cli = subprocess.run(
        [
            sys.executable,
            str(script),
            str(pdf.resolve()),
            str(cli_out.resolve()),
            str((tmp_path / "cli-stage").resolve()),
        ],
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(repo)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0
    assert cli_out.is_file()
    source = (REPO_ROOT / "tests" / "test_migration_control_plane.py").read_text(encoding="utf-8")
    assert 'cwd="/workspace"' not in source
    assert 'PYTHONPATH": "/workspace"' not in source


def test_result_binding_rejects_provider_source_revision_family_and_replay() -> None:
    context = _context()
    descriptor = _descriptor()
    result = ProviderResult.build(descriptor=descriptor, context=context, quantities=(_qty("W1", 6),))
    assert_provider_result_binding(result, descriptor, context)

    other_provider = _descriptor(provider_id="other_provider", code_fingerprint="b" * 64)
    with pytest.raises(ProviderResultBindingError, match="descriptor"):
        assert_provider_result_binding(result, other_provider, context)

    other_source = _context(source_sha256="cd" * 32)
    with pytest.raises(ProviderResultBindingError, match="context"):
        assert_provider_result_binding(result, descriptor, other_source)

    other_revision = _context(revision_id="rev-b", current_revision_id="rev-b")
    with pytest.raises(ProviderResultBindingError, match="context"):
        assert_provider_result_binding(result, descriptor, other_revision)

    other_family = _descriptor(family="other_family")
    with pytest.raises(ProviderResultBindingError, match="family"):
        assert_provider_result_binding(result, other_family, context)

    tampered = replace(result, quantities=(_qty("W1", 99),))
    with pytest.raises(ProviderResultBindingError, match="fingerprint"):
        assert_provider_result_binding(tampered, descriptor, context)


def test_router_rejects_replayed_result_under_different_context(tmp_path: Path) -> None:
    context_a = _context()
    context_b = _context(source_sha256="cd" * 32, document_id="doc_other")
    result = ProviderResult.build(
        descriptor=_descriptor(),
        context=context_a,
        quantities=(_qty("W1", 6),),
    )
    router = _router(tmp_path)
    with pytest.raises(FamilyRouterError, match="context"):
        router.route(
            family="opening_count",
            context=context_b,
            legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
            new_result=result,
        )


def test_mixed_accepted_and_conflicting_claims_are_arbitrated_per_key(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test_only_not_a_promotion",
    )
    context = _context()
    new_result = ProviderResult.build(
        descriptor=_descriptor(),
        context=context,
        quantities=(
            _qty("W1", 6, quantity_id="new_w1"),
            _qty("D1", 2, quantity_id="d1_a"),
            _qty("D1", 3, quantity_id="d1_b"),
        ),
    )
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(
            _qty("W1", 4, quantity_id="legacy_w1"),
            _qty("D1", 2, quantity_id="legacy_d1"),
        ),
        new_result=new_result,
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1", "D1")),
    )
    by_key = {item.claim.semantic_key: item for item in routed.selected}
    assert by_key["W1"].selected_authority == "new"
    assert by_key["W1"].quantity.quantity_id == "new_w1"
    assert by_key["D1"].selected_authority == "legacy"
    assert by_key["D1"].fallback_reason == "unresolved_authority_conflict"
    assert by_key["D1"].quantity.quantity_id == "legacy_d1"
    values = [item.quantity.value for item in routed.selected if item.quantity is not None]
    assert 8 not in values
    assert 11 not in values
    assert_exactly_one_selected(routed.selected_keys())
    assert "conflicting_new_claims" in routed.arbitration.kinds


def test_mixed_accepted_and_blocked_claims_do_not_mask_each_other(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test_only_not_a_promotion",
    )
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(
            _qty("W1", 4, quantity_id="legacy_w1"),
            _qty("D1", 2, quantity_id="legacy_d1"),
        ),
        new_result=ProviderResult.build(
            descriptor=_descriptor(),
            context=context,
            quantities=(
                _qty("W1", 6, quantity_id="new_w1"),
                _qty("D1", abstained=True, quantity_id="blocked_d1"),
            ),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1", "D1")),
    )
    by_key = {item.claim.semantic_key: item for item in routed.selected}
    assert by_key["W1"].selected_authority == "new"
    assert by_key["D1"].selected_authority == "legacy"
    assert by_key["D1"].fallback_reason == "new_abstention_fallback"
    assert_exactly_one_selected(routed.selected_keys())


def test_mixed_batch_does_not_sum_aggregate_and_instance(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test_only_not_a_promotion",
    )
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("door_total", 12, quantity_id="legacy_total"), _qty("D1", 4, quantity_id="legacy_d1")),
        new_result=ProviderResult.build(
            descriptor=_descriptor(),
            context=context,
            quantities=(_qty("door_total", 12, quantity_id="new_total"), _qty("D1", 4, quantity_id="new_d1")),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ()),
    )
    values = [item.quantity.value for item in routed.selected if item.quantity is not None]
    assert 16 not in values
    assert {item.quantity.value for item in routed.selected if item.quantity is not None} == {4.0, 12.0}
    arbitration = arbitrate_claims(
        family="opening_count",
        project_id="proj_1",
        revision_id="rev-a",
        new_quantities=(_qty("door_total", 12), _qty("D1", 4)),
    )
    assert "aggregate_instance_overlap" in arbitration.kinds


def test_page_ownership_rejects_invented_page() -> None:
    qty = _qty("W1", 6, extra_meta={"source_page": 99, "page": 99})
    with pytest.raises(SourceTraceBindingError, match="not owned"):
        bind_commercial_source_trace(qty, _context())


def test_page_ownership_rejects_unowned_viewport() -> None:
    qty = _qty("W1", 6, extra_meta={"viewport_id": "vp_forged"})
    with pytest.raises(SourceTraceBindingError, match="viewport"):
        bind_commercial_source_trace(qty, _context())


def test_page_ownership_rejects_viewport_page_mismatch() -> None:
    context = _context(
        owned_page_numbers=(1, 2),
        owned_viewport_ids=("vp_1", "vp_plan"),
        viewport_page_ownership=(("vp_plan", 2),),
    )
    qty = _qty("W1", 6, extra_meta={"source_page": 1, "viewport_id": "vp_plan"})
    with pytest.raises(SourceTraceBindingError, match="owned by page"):
        bind_commercial_source_trace(qty, context)


def test_page_ownership_rejects_wrong_document_and_stale_revision() -> None:
    qty = _qty("W1", 6, extra_meta={"document_id": "doc_other"})
    with pytest.raises(SourceTraceBindingError, match="document"):
        bind_commercial_source_trace(qty, _context())
    stale = _context(revision_id="rev-old", current_revision_id="rev-new")
    with pytest.raises(SourceTraceBindingError, match="stale revision"):
        bind_commercial_source_trace(_qty("W1", 6), stale)


def test_page_ownership_rejects_cross_document_replay() -> None:
    qty = _qty("W1", 6, extra_meta={"document_id": "doc_replay"})
    other = _context(document_id="doc_2", owned_page_numbers=(1,))
    with pytest.raises(SourceTraceBindingError, match="document"):
        bind_commercial_source_trace(qty, other)


def test_page_ownership_accepts_trusted_multisource() -> None:
    qty = _qty(
        "W1",
        6,
        extra_meta={"source_pages": [2, 5], "source_page": 2},
        evidence_ids=("ev_a", "ev_b"),
    )
    context = _context(
        selected_pages=(1, 4),
        owned_page_numbers=(1, 2, 5),
        owned_viewport_ids=("vp_1", "vp_plan", "vp_sched"),
        viewport_page_ownership=(("vp_plan", 2), ("vp_sched", 5)),
    )
    provenance = bind_multi_source_provenance(
        qty,
        context,
        contributing_pages=(2, 5),
        contributing_viewports=("vp_plan", "vp_sched"),
    )
    assert provenance.primary.source_page == "2"
    assert provenance.primary.document_id == "doc_1"
    assert [item.page for item in provenance.contributors] == [2, 5]
    assert [item.viewport_id for item in provenance.contributors] == ["vp_plan", "vp_sched"]


def test_frozen_metrics_remain_unchanged() -> None:
    headline = json.loads(
        (REPO_ROOT / "benchmark_results" / "headline_accuracy_dashboard.json").read_text(encoding="utf-8")
    )
    metrics = headline["headline_metrics"]
    accepted = int(metrics["exact_matches"]) + int(metrics["within_5_percent"])
    assert accepted == 24
    assert int(metrics["total_items_compared"]) == 61
    assert pytest.approx(metrics["overall_accuracy_percentage"], rel=0, abs=0.01) == 39.34
    shadow = json.loads(
        (REPO_ROOT / "shadow_reports" / "opening_count_shadow_development.json").read_text(encoding="utf-8")
    )
    assert shadow["authority_state"] == "new_shadow"
    assert shadow.get("holdout_scored") is False
    assert int(shadow["metrics"]["eligible_opening_count_items"]) == 24
    assert int(shadow["metrics"]["answered"]) == 15
    assert ShadowOpeningCountProvider is not None
    assert opening_count_descriptor().family == "opening_count"
    assert OpeningCountControlAdapter is not None
