from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    ViewportResolutionStatus,
)
from pb_migration_provider_envelope import ProviderContext
from pb_wall_net_area_quantity import build_net_wall_area_quantity


def _ctx() -> ProviderContext:
    return ProviderContext(
        run_id="run",
        workspace_id="ws",
        project_id="p",
        document_id="doc",
        source_sha256="a" * 64,
        revision_id="R1",
        current_revision_id="R1",
        selected_pages=(0,),
        owned_viewport_ids=("VP-1",),
        evidence_snapshot_id="snap",
        owned_page_numbers=(1,),
        viewport_page_ownership=(("VP-1", 1),),
    )


def _viewport() -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id="VP-1",
        document_id="doc",
        page_id="page-1",
        bbox=(0.0, 0.0, 100.0, 100.0),
        view_type="plan",
        status=ViewportResolutionStatus.RESOLVED,
        confidence=1.0,
    )


def _gross(value=12.0) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id="qty-gross",
        family="wall_gross_area",
        semantic_key="wall_gross_area:WALL-1",
        value=value,
        unit="m2",
        input_entity_ids=("WALL-1",),
        formula="length*height",
        formula_version="1",
        evidence_ids=("ev-wall",),
        authority="derived_from_firm_measurements",
        status=AuthorityStatus.FIRM.value,
        confidence=0.95,
        metadata={
            "source_sha256": "a" * 64,
            "revision_id": "R1",
            "viewport_id": "VP-1",
        },
    )


def _deduction(opening_id: str, value: float) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id=f"qty-ded-{opening_id}",
        family="opening_deduction_area",
        semantic_key=f"opening_deduction:{opening_id}",
        value=value,
        unit="m2",
        input_entity_ids=(opening_id, "WALL-1"),
        formula="width*height",
        formula_version="1",
        evidence_ids=(f"ev-{opening_id}-w", f"ev-{opening_id}-h"),
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.FIRM.value,
        confidence=0.9,
        metadata={
            "source_sha256": "a" * 64,
            "revision_id": "R1",
            "viewport_id": "VP-1",
            "wall_id": "WALL-1",
        },
    )


def _complete(ids: tuple[str, ...]) -> EvidenceAtom:
    return EvidenceAtom(
        evidence_id="ev-opening-set",
        document_id="doc",
        page_id="page-1",
        viewport_id="VP-1",
        kind="opening_set_complete",
        method="corroborated_opening_reconciliation",
        confidence=0.99,
        status=EvidenceResolutionStatus.CORROBORATED,
        metadata={"wall_id": "WALL-1", "opening_ids": list(ids)},
    )


def _wall_entity(extra_ids=()) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id="WALL-1",
        candidate_type="wall",
        evidence_ids=("ev-wall", "ev-opening-set", *tuple(extra_ids)),
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=0.95,
    )


def _doc(*extra: str) -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc",
        source_sha256="a" * 64,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=("ev-wall", "ev-opening-set", *extra),
    )


def test_net_area_with_complete_authoritative_opening_set() -> None:
    d1 = _deduction("OP-1", 1.89)
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(d1,),
        opening_set_complete_evidence=_complete(("OP-1",)),
        context=_ctx(),
        document=_doc(*d1.evidence_ids),
        viewport=_viewport(),
        wall_entity=_wall_entity(d1.evidence_ids),
    )
    assert not result.abstained
    assert result.value == 10.11
    assert result.metadata["opening_ids"] == ["OP-1"]
    assert result.metadata["total_opening_deduction_m2"] == 1.89


def test_unresolved_w7_host_blocks_net_area_even_with_other_evidence() -> None:
    d1 = _deduction("OP-1", 1.0)
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(d1,),
        opening_set_complete_evidence=_complete(("OP-1",)),
        context=_ctx(),
        document=_doc(*d1.evidence_ids),
        viewport=_viewport(),
        wall_entity=_wall_entity(d1.evidence_ids),
        unresolved_opening_host_ids=("openinghost-ambiguous",),
    )
    assert result.abstained
    assert "unresolved_opening_hosts_present" in result.blocking_reasons


def test_empty_detector_result_is_not_proof_of_no_openings() -> None:
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(),
        opening_set_complete_evidence=None,
        context=_ctx(),
        document=_doc(),
        viewport=_viewport(),
        wall_entity=_wall_entity(),
    )
    assert result.abstained
    assert "opening_set_completeness_not_evidenced" in result.blocking_reasons


def test_explicitly_corroborated_zero_opening_set_can_equal_gross() -> None:
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(),
        opening_set_complete_evidence=_complete(()),
        context=_ctx(),
        document=_doc(),
        viewport=_viewport(),
        wall_entity=_wall_entity(),
    )
    assert not result.abstained
    assert result.value == 12.0
    assert result.metadata["opening_ids"] == []


def test_declared_opening_set_must_exactly_match_deductions() -> None:
    d1 = _deduction("OP-1", 1.0)
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(d1,),
        opening_set_complete_evidence=_complete(("OP-1", "OP-2")),
        context=_ctx(),
        document=_doc(*d1.evidence_ids),
        viewport=_viewport(),
        wall_entity=_wall_entity(d1.evidence_ids),
    )
    assert result.abstained
    assert "opening_deduction_set_not_complete" in result.blocking_reasons


def test_deduction_cannot_exceed_gross() -> None:
    d1 = _deduction("OP-1", 13.0)
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(d1,),
        opening_set_complete_evidence=_complete(("OP-1",)),
        context=_ctx(),
        document=_doc(*d1.evidence_ids),
        viewport=_viewport(),
        wall_entity=_wall_entity(d1.evidence_ids),
    )
    assert result.abstained
    assert "opening_deductions_exceed_gross_area" in result.blocking_reasons


def test_duplicate_physical_opening_deduction_is_blocked() -> None:
    d1 = _deduction("OP-1", 1.0)
    result = build_net_wall_area_quantity(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(d1, d1),
        opening_set_complete_evidence=_complete(("OP-1",)),
        context=_ctx(),
        document=_doc(*d1.evidence_ids),
        viewport=_viewport(),
        wall_entity=_wall_entity(d1.evidence_ids),
    )
    assert result.abstained
    assert "duplicate_opening_deduction_identity" in result.blocking_reasons


def test_deterministic_replay() -> None:
    d1 = _deduction("OP-1", 1.2)
    kwargs = dict(
        wall_id="WALL-1",
        gross_wall_area=_gross(),
        opening_deductions=(d1,),
        opening_set_complete_evidence=_complete(("OP-1",)),
        context=_ctx(),
        document=_doc(*d1.evidence_ids),
        viewport=_viewport(),
        wall_entity=_wall_entity(d1.evidence_ids),
    )
    first = build_net_wall_area_quantity(**kwargs)
    replay = build_net_wall_area_quantity(**kwargs)
    assert first.to_dict() == replay.to_dict()
