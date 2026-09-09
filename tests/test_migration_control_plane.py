from __future__ import annotations

from pathlib import Path
import json

import fitz
import pytest

from pb_figured_dimension_authority import resolve_measurement_authority
from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_gold_free_shadow_runner import GoldFreeShadowRunner, compare_shadow_quantities
from pb_legacy_extractor_adapter import (
    LEGACY_EXTRACTOR_ADAPTER_VERSION,
    LEGACY_EXTRACTOR_ENGINE_ID,
    LegacyExtractionResult,
    LegacyPredictionSnapshot,
)
from pb_migration_claim_arbiter import (
    ClaimArbitrationError,
    arbitrate_claims,
    assert_exactly_one_selected,
    claim_key,
)
from pb_migration_contracts import MigrationAuthorityState, QuantityEvidence
from pb_migration_decision_ledger import MigrationDecisionLedger
from pb_migration_family_router import FamilyAuthorityRouter, FamilyRegistration
from pb_migration_measurement_authority_binder import (
    MeasurementAuthorityBindingError,
    bind_commercial_measurement_authority,
    bind_direct_evidence_authority,
)
from pb_migration_provider_envelope import (
    EligibilityDecision,
    ProviderContext,
    ProviderDescriptor,
    ProviderResult,
)
from pb_migration_report import build_migration_report
from pb_migration_source_trace_binder import (
    SourceTraceBindingError,
    bind_commercial_source_trace,
    bind_multi_source_provenance,
)
from pb_opening_count_control_adapter import (
    OpeningCountControlAdapter,
    is_production_opening_identity,
    opening_count_descriptor,
    source_sha256,
)
from pb_page_scale_calibration_authority import unknown_calibration
from pb_provider_gold_isolation import (
    ProviderGoldIsolationError,
    assert_provider_gold_free,
    assert_registered_providers_gold_free,
    inspect_provider_isolation,
    inspect_registered_production_providers,
)
from pb_quantity_commercial_adapter import (
    CommercialProjectionContext,
    quantity_evidence_to_takeoff_output_row,
)
from pb_shadow_opening_count_provider import ShadowOpeningCountProvider
from pb_takeoff_authority_v164 import ai_takeoff_authority, takeoff_row_publishability


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


def _descriptor() -> ProviderDescriptor:
    return opening_count_descriptor()


def _context(tmp_path: Path | None = None, **overrides) -> ProviderContext:
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
        source_pdf=str(tmp_path / "x.pdf") if tmp_path else None,
    )
    payload.update(overrides)
    return ProviderContext(**payload)


def _router(tmp_path: Path) -> FamilyAuthorityRouter:
    ledger = MigrationDecisionLedger(tmp_path / "migration.sqlite")
    return FamilyAuthorityRouter(ledger)


def _schedule_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "schedule.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "DRAWING TITLE: WINDOW & DOOR SCHEDULE", fontsize=10)
    rows = [
        ["Mark", "Description", "Qty", "Width", "Height"],
        ["W1", "casement window", "6", "1800", "1200"],
        ["D1", "flush door", "2", "900", "2100"],
    ]
    y = 80
    for row in rows:
        x = 40
        for cell in row:
            page.insert_text((x, y), cell, fontsize=9)
            x += 90
        y += 22
    doc.save(path)
    doc.close()
    return path


def test_01_direct_provider_gold_import_rejected() -> None:
    report = inspect_provider_isolation(
        "direct_dirty",
        "tests.fixtures.migration_isolation.direct_dirty_provider",
    )
    assert report.ok is False
    assert any("pb_public_tender_benchmark" in item.reason for item in report.findings)
    with pytest.raises(ProviderGoldIsolationError):
        assert_provider_gold_free(
            "direct_dirty",
            "tests.fixtures.migration_isolation.direct_dirty_provider",
        )


def test_02_transitive_provider_gold_import_rejected() -> None:
    report = inspect_provider_isolation(
        "dirty_shadow",
        "tests.fixtures.migration_isolation.dirty_provider",
    )
    assert report.ok is False
    assert any("pb_benchmark_accuracy_engine" in item.reason for item in report.findings)
    assert any("dirty_helper" in "->".join(item.via) for item in report.findings)


def test_03_clean_provider_accepted() -> None:
    report = inspect_provider_isolation(
        "clean_shadow",
        "tests.fixtures.migration_isolation.clean_provider",
    )
    assert report.ok is True
    registered = inspect_registered_production_providers()
    assert registered["shadow_opening_count"].ok is True
    assert registered["opening_count_control_adapter"].ok is True
    assert_registered_providers_gold_free()


def test_04_deterministic_provider_context_fingerprint() -> None:
    left = _context().fingerprint()
    right = _context().fingerprint()
    assert left == right
    changed = _context(revision_id="rev-b", current_revision_id="rev-b").fingerprint()
    assert changed != left


def test_05_deterministic_provider_result_fingerprint() -> None:
    context = _context()
    qty = _qty("W1", 6)
    left = ProviderResult.build(descriptor=_descriptor(), context=context, quantities=(qty,))
    right = ProviderResult.build(descriptor=_descriptor(), context=context, quantities=(qty,))
    assert left.result_fingerprint == right.result_fingerprint
    other = ProviderResult.build(descriptor=_descriptor(), context=context, quantities=(_qty("W1", 7),))
    assert other.result_fingerprint != left.result_fingerprint


def test_06_semantic_key_collision_detected() -> None:
    report = arbitrate_claims(
        family="opening_count",
        project_id="proj_1",
        revision_id="rev-a",
        new_quantities=(_qty("W1", 6, quantity_id="a"), _qty("W1", 6, quantity_id="b")),
    )
    assert "duplicate_new_claim" in report.kinds
    assert report.blocking is True


def test_07_duplicate_new_claim() -> None:
    report = arbitrate_claims(
        family="opening_count",
        project_id="p",
        revision_id="",
        new_quantities=(_qty("D1", 2, quantity_id="d1a"), _qty("D1", 2, quantity_id="d1b")),
    )
    assert report.findings[0].kind == "duplicate_new_claim"


def test_08_conflicting_new_claims() -> None:
    report = arbitrate_claims(
        family="opening_count",
        project_id="p",
        revision_id="",
        new_quantities=(_qty("D1", 2, quantity_id="c1"), _qty("D1", 3, quantity_id="c2")),
    )
    assert "conflicting_new_claims" in report.kinds


def test_09_new_shadow_selects_legacy_only(tmp_path: Path) -> None:
    router = _router(tmp_path)
    context = _context()
    new = ProviderResult.build(
        descriptor=_descriptor(),
        context=context,
        quantities=(_qty("W1", 6),),
    )
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
        new_result=new,
    )
    assert routed.state == MigrationAuthorityState.NEW_SHADOW.value
    assert routed.new_ran is True
    assert routed.commercially_selected_from_new is False
    assert all(item.selected_authority == "legacy" for item in routed.selected)
    assert routed.selected[0].quantity is not None
    assert routed.selected[0].quantity.quantity_id == "legacy_w1"
    assert routed.selected[0].diagnostic_new is not None


def test_10_new_selective_valid_new_selection(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test_only_not_a_promotion",
    )
    context = _context()
    new_row = _qty("W1", 6, quantity_id="new_w1")
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 4, quantity_id="legacy_w1"),),
        new_result=ProviderResult.build(descriptor=_descriptor(), context=context, quantities=(new_row,)),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1",)),
    )
    assert routed.selected[0].selected_authority == "new"
    assert routed.selected[0].quantity.quantity_id == "new_w1"


def test_11_new_selective_abstention_fallback(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test",
    )
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
        new_result=ProviderResult.build(
            descriptor=_descriptor(),
            context=context,
            quantities=(_qty("W1", abstained=True, quantity_id="abs_w1"),),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1",)),
    )
    assert routed.selected[0].selected_authority == "legacy"
    assert routed.selected[0].fallback_reason == "new_abstention_fallback"
    assert routed.selected[0].quantity.quantity_id == "legacy_w1"


def test_12_new_selective_conflict_fallback(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test",
    )
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 6, quantity_id="legacy_w1"),),
        new_result=ProviderResult.build(
            descriptor=_descriptor(),
            context=context,
            quantities=(_qty("W1", 6, quantity_id="n1"), _qty("W1", 9, quantity_id="n2")),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1",)),
    )
    assert routed.selected[0].selected_authority == "legacy"
    assert routed.selected[0].fallback_reason == "unresolved_authority_conflict"


def test_13_new_authoritative_behavior(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_AUTHORITATIVE.value,
        project_id="proj_1",
        provider=_descriptor(),
        reason="test_only",
    )
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 99, quantity_id="legacy_w1"),),
        new_result=ProviderResult.build(
            descriptor=_descriptor(),
            context=context,
            quantities=(_qty("W1", abstained=True, quantity_id="abs_w1"),),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1",)),
    )
    assert routed.selected[0].selected_authority == "new_authoritative_abstention"
    assert routed.selected[0].quantity is None
    assert routed.selected[0].fallback_reason == "authoritative_abstention_no_legacy_substitution"
    routed_ok = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 99, quantity_id="legacy_w1"),),
        new_result=ProviderResult.build(
            descriptor=_descriptor(),
            context=context,
            quantities=(_qty("W1", 6, quantity_id="new_w1"),),
        ),
        eligibility=EligibilityDecision(True, "opening_count", ("test",), "tag", ("W1",)),
    )
    assert routed_ok.selected[0].selected_authority == "new"
    assert routed_ok.selected[0].quantity.quantity_id == "new_w1"


def test_14_exactly_one_authority_invariant(tmp_path: Path) -> None:
    router = _router(tmp_path)
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 6, quantity_id="l"),),
        new_result=ProviderResult.build(descriptor=_descriptor(), context=context, quantities=(_qty("W1", 6, quantity_id="n"),)),
    )
    assert_exactly_one_selected(routed.selected_keys())
    with pytest.raises(ClaimArbitrationError):
        assert_exactly_one_selected(
            (
                claim_key(family="opening_count", project_id="p", revision_id="r", semantic_key="W1"),
                claim_key(family="opening_count", project_id="p", revision_id="r", semantic_key="W1"),
            )
        )


def test_15_rollback_selective_to_shadow(tmp_path: Path) -> None:
    router = _router(tmp_path)
    desc = _descriptor()
    router.set_state("opening_count", MigrationAuthorityState.NEW_SELECTIVE.value, project_id="p", provider=desc, reason="up")
    router.rollback("opening_count", target=MigrationAuthorityState.NEW_SHADOW.value, project_id="p", provider=desc, reason="rollback")
    assert router.current_state("opening_count") == MigrationAuthorityState.NEW_SHADOW.value
    history = router.ledger.history("opening_count")
    assert any(row["prior_state"] == "new_selective" for row in history)


def test_16_rollback_authoritative_to_shadow(tmp_path: Path) -> None:
    router = _router(tmp_path)
    desc = _descriptor()
    router.set_state("opening_count", MigrationAuthorityState.NEW_AUTHORITATIVE.value, project_id="p", provider=desc, reason="up")
    router.rollback("opening_count", target=MigrationAuthorityState.NEW_SHADOW.value, project_id="p", provider=desc, reason="rollback")
    assert router.current_state("opening_count") == MigrationAuthorityState.NEW_SHADOW.value


def test_17_severe_rollback_to_legacy(tmp_path: Path) -> None:
    router = _router(tmp_path)
    desc = _descriptor()
    router.set_state("opening_count", MigrationAuthorityState.NEW_SELECTIVE.value, project_id="p", provider=desc, reason="up")
    router.rollback(
        "opening_count",
        target=MigrationAuthorityState.LEGACY_AUTHORITATIVE.value,
        project_id="p",
        provider=desc,
        reason="severe",
    )
    assert router.current_state("opening_count") == MigrationAuthorityState.LEGACY_AUTHORITATIVE.value
    context = _context()
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=(_qty("W1", 6, quantity_id="l"),),
        new_result=ProviderResult.build(descriptor=desc, context=context, quantities=(_qty("W1", 6, quantity_id="n"),)),
        execute_new=True,
    )
    assert routed.new_ran is False
    assert routed.selected[0].selected_authority == "legacy"


def test_18_stale_revision_rejected() -> None:
    qty = _qty("W1", 6)
    context = _context(revision_id="rev-old", current_revision_id="rev-new")
    with pytest.raises(SourceTraceBindingError, match="stale revision"):
        bind_commercial_source_trace(qty, context)


def test_19_source_sha_mismatch_rejected() -> None:
    qty = _qty("W1", 6, extra_meta={"source_sha256": "cd" * 32})
    with pytest.raises(SourceTraceBindingError, match="source SHA"):
        bind_commercial_source_trace(qty, _context())


def test_20_unresolved_scaled_authority_rejected() -> None:
    qty = _qty(
        "LEN",
        3.0,
        family="figured_dimension",
        extra_meta={"source_page": 1},
        authority=MeasurementAuthorityType.PDF_SCALED.value,
    )
    with pytest.raises(MeasurementAuthorityBindingError, match="unresolved"):
        bind_commercial_measurement_authority(
            qty,
            scaled_mm=3000.0,
            scale_calibration=unknown_calibration(1),
        )


def test_21_direct_evidence_binder() -> None:
    qty = _qty("W1", 6)
    bound = bind_direct_evidence_authority(qty, source_type="schedule_extracted")
    assert bound.source_type == "schedule_extracted"
    assert bound.scale_calibration_status is None


def test_22_figured_authority_binder() -> None:
    qty = _qty(
        "LEN",
        6.5,
        family="figured_dimension",
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
    )
    bound = bind_commercial_measurement_authority(qty, figured_text="6500")
    assert bound.source_type == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
    assert bound.figured_mm == 6500.0
    existing = resolve_measurement_authority(figured_text="6500")
    assert bound.authority_status == existing.authority_status


def test_23_multi_page_provenance() -> None:
    qty = _qty("W1", 6, extra_meta={"source_pages": [2, 5]}, evidence_ids=("ev_a", "ev_b"))
    provenance = bind_multi_source_provenance(
        qty,
        _context(),
        contributing_pages=(2, 5),
        contributing_viewports=("vp_plan", "vp_sched"),
    )
    assert provenance.primary.source_page == 2
    assert [item.page for item in provenance.contributors] == [2, 5]
    assert provenance.evidence_fingerprint
    assert provenance.primary.project_id == "proj_1"


def test_24_aggregate_instance_collision() -> None:
    report = arbitrate_claims(
        family="opening_count",
        project_id="p",
        revision_id="",
        new_quantities=(_qty("door_total", 12), _qty("D1", 4)),
    )
    assert "aggregate_instance_overlap" in report.kinds
    assert is_production_opening_identity("D1") is True
    assert is_production_opening_identity("door_total") is False


def test_25_estimator_approval_remains_separate() -> None:
    qty = _qty("W1", 6)
    row = quantity_evidence_to_takeoff_output_row(
        qty,
        CommercialProjectionContext(project_id="proj_1", source_sha256=SHA),
    )
    assert row is not None
    assert row.approved_by is None
    assert str(row.confidence) not in {"approved", "estimator_verified"}


def test_26_commercial_publishability_controlled_by_existing_authority() -> None:
    qty = _qty("W1", 6)
    row = quantity_evidence_to_takeoff_output_row(
        qty,
        CommercialProjectionContext(project_id="proj_1", source_sha256=SHA),
    )
    review = {
        "origin": "AI",
        "quantity": row.value,
        "quantity_status": "to_review",
        "confidence": str(row.confidence),
        "source_reference": "ai draft opening-count shadow",
    }
    publishable, reason = takeoff_row_publishability(review)
    ai_ok, _ = ai_takeoff_authority(review)
    assert publishable is False
    assert ai_ok is False
    assert "estimator" in reason.lower() or "ai" in reason.lower()


def test_27_frozen_before_gold_evaluation(tmp_path: Path) -> None:
    context = _context()
    frozen = ProviderResult.build(
        descriptor=_descriptor(),
        context=context,
        quantities=(_qty("W1", 6),),
    )
    report = build_migration_report(
        family="opening_count",
        descriptor=_descriptor(),
        migration_state=MigrationAuthorityState.NEW_SHADOW.value,
        source_set_fingerprint="src",
        evaluated_commit="test",
        eligible=24,
        eligible_keys=("W1",) * 24,
        frozen_new=frozen.quantities,
        exact_among_answered=1.0,
        precision=1.0,
        hallucinations=0,
        gold_joined_after_freeze=True,
        gate_decision="HOLD",
        gate_reasons=("remain_new_shadow",),
    )
    assert report.payload["population"]["eligible"] == 24
    assert report.payload["population"]["answered"] == 1
    assert report.payload["population"]["eligible"] != report.payload["population"]["answered"]
    assert report.payload["accuracy"]["coverage"] == pytest.approx(1 / 24)
    assert report.payload["benchmark_integrity"]["frozen_before_gold_join"] is True
    assert report.payload["benchmark_integrity"]["holdout_status"] == "NOT_RUN"
    assert report.payload["gate"]["decision"] == "HOLD"
    assert report.payload["gate"]["target_state"] == "new_selective"
    assert report.payload["identity"]["provider_id"]
    assert report.payload["fingerprints"]["legacy_output"]
    assert report.payload["fingerprints"]["comparison"]
    assert report.payload["fingerprints"]["report"]


def test_28_opening_count_provider_output_unchanged_through_adapter(tmp_path: Path) -> None:
    pdf = _schedule_pdf(tmp_path)
    raw = ShadowOpeningCountProvider().extract_quantities(pdf, pages=[0])
    adapted = OpeningCountControlAdapter().extract_quantities(pdf, pages=[0])
    assert [item.to_dict() for item in raw] == [item.to_dict() for item in adapted]
    context = _context(
        tmp_path,
        source_pdf=str(pdf),
        source_sha256=source_sha256(pdf),
        selected_pages=(0,),
    )
    result = OpeningCountControlAdapter().extract(context)
    assert [item.to_dict() for item in result.quantities] == [item.to_dict() for item in raw]


def test_new_shadow_does_not_publish_and_legacy_stays_selected(tmp_path: Path) -> None:
    pdf = _schedule_pdf(tmp_path)
    adapter = OpeningCountControlAdapter()
    context = _context(tmp_path, source_pdf=str(pdf), source_sha256=source_sha256(pdf), selected_pages=(0,))
    new_result = adapter.extract(context)
    frozen = tuple(item.to_dict() for item in new_result.quantities)
    sha = source_sha256(pdf)
    legacy_result = LegacyExtractionResult(
        result_id="legacy_e2e",
        engine_id=LEGACY_EXTRACTOR_ENGINE_ID,
        adapter_version=LEGACY_EXTRACTOR_ADAPTER_VERSION,
        source_sha256=sha,
        source_size_bytes=pdf.stat().st_size,
        pages=(0,),
        predictions=(
            LegacyPredictionSnapshot(
                tag="W1",
                trade_type="windows",
                description="legacy W1",
                quantity=6.0,
                unit="ea",
                confidence=0.5,
                source_page=1,
            ),
        ),
    )

    class _StubLegacy:
        def extract(self, pdf_path, pages=None):
            return legacy_result

    shadow = GoldFreeShadowRunner(legacy_adapter=_StubLegacy()).run(pdf, adapter, pages=[0])
    compare_shadow_quantities(shadow.legacy_output, shadow.new_output)
    legacy_quantities = tuple(
        _qty(str(item.tag), float(item.quantity), quantity_id=f"legacy_{item.tag}")
        for item in shadow.legacy_output.predictions
        if str(item.tag or "").strip()
    )
    router = _router(tmp_path)
    routed = router.route(
        family="opening_count",
        context=context,
        legacy_quantities=legacy_quantities,
        new_result=new_result,
    )
    assert frozen == tuple(item.to_dict() for item in new_result.quantities)
    assert router.current_state("opening_count") == "new_shadow"
    assert routed.commercially_selected_from_new is False
    assert all(item.selected_authority == "legacy" for item in routed.selected)
    eligibility = adapter.eligibility(context)
    assert eligibility.eligible is True
    assert eligibility.eligible_semantic_keys == ()
    assert eligibility.declared_identity_grammar


def test_isolated_provider_execution_does_not_need_gold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _schedule_pdf(tmp_path)

    def blocked_gold(path, *args, **kwargs):
        text = str(path)
        if "expected_boq" in text or "benchmark_rules" in text or "holdout" in text:
            raise AssertionError(f"gold path opened during provider execution: {path}")
        return original_read_text(path, *args, **kwargs)

    original_read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", blocked_gold)
    OpeningCountControlAdapter().extract_quantities(pdf, pages=[0])


def test_29_deterministic_replay(tmp_path: Path) -> None:
    pdf = _schedule_pdf(tmp_path)
    adapter = OpeningCountControlAdapter()
    context = _context(tmp_path, source_pdf=str(pdf), source_sha256=source_sha256(pdf), selected_pages=(0,))
    first = adapter.extract(context)
    second = adapter.extract(context)
    assert first.result_fingerprint == second.result_fingerprint
    assert first.context_fingerprint == second.context_fingerprint
    assert [item.to_dict() for item in first.quantities] == [item.to_dict() for item in second.quantities]


def test_30_unrelated_family_unaffected_by_rollback(tmp_path: Path) -> None:
    router = _router(tmp_path)
    desc = _descriptor()
    other = ProviderDescriptor(
        provider_id="other_family_provider",
        family="other_family",
        provider_version="1.0.0",
        output_schema_version="1.0.0",
        code_fingerprint="0" * 64,
    )
    router.registry["other_family"] = FamilyRegistration(
        family="other_family",
        provider_id="other_family_provider",
        provider_module="pb_migration_contracts",
        default_state=MigrationAuthorityState.NEW_SELECTIVE.value,
    )
    router.set_state(
        "other_family",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="p",
        provider=other,
        reason="unrelated",
    )
    router.set_state(
        "opening_count",
        MigrationAuthorityState.NEW_SELECTIVE.value,
        project_id="p",
        provider=desc,
        reason="up",
    )
    router.rollback(
        "opening_count",
        target=MigrationAuthorityState.NEW_SHADOW.value,
        project_id="p",
        provider=desc,
        reason="family_scoped",
    )
    assert router.current_state("opening_count") == MigrationAuthorityState.NEW_SHADOW.value
    assert router.current_state("other_family") == MigrationAuthorityState.NEW_SELECTIVE.value


def test_headline_dashboard_still_canonical() -> None:
    data = json.loads(Path("benchmark_results/headline_accuracy_dashboard.json").read_text(encoding="utf-8"))
    metrics = data["headline_metrics"]
    accepted = int(metrics["exact_matches"]) + int(metrics["within_5_percent"])
    assert accepted == 24
    assert int(metrics["total_items_compared"]) == 61
