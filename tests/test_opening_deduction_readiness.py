from __future__ import annotations

from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    ViewportEvidence,
    ViewportResolutionStatus,
)
from pb_migration_provider_envelope import ProviderContext
from pb_opening_deduction_readiness import (
    build_opening_deduction_quantities,
    build_opening_deduction_quantity,
)
from pb_wall_room_topology_contracts import OpeningHostCandidate


def _ctx() -> ProviderContext:
    return ProviderContext(
        run_id="run-1",
        workspace_id="ws-1",
        project_id="p-1",
        document_id="doc-1",
        source_sha256="a" * 64,
        revision_id="R1",
        current_revision_id="R1",
        selected_pages=(0,),
        owned_viewport_ids=("VP-1",),
        evidence_snapshot_id="evsnap",
        owned_page_numbers=(1,),
        viewport_page_ownership=(("VP-1", 1),),
    )


def _viewport() -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id="VP-1",
        document_id="doc-1",
        page_id="page-1",
        bbox=(0.0, 0.0, 100.0, 100.0),
        view_type="plan",
        status=ViewportResolutionStatus.RESOLVED,
        evidence_ids=("ev-w", "ev-h"),
        confidence=1.0,
    )


def _doc(*ids: str) -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc-1",
        source_sha256="a" * 64,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=tuple(ids),
    )


def _ev(eid: str, kind: str, value: float, unit: str = "mm") -> EvidenceAtom:
    return EvidenceAtom(
        evidence_id=eid,
        document_id="doc-1",
        page_id="page-1",
        viewport_id="VP-1",
        kind=kind,
        method="documented_dimension",
        normalized_value=value,
        unit=unit,
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=0.99,
    )


def _entity(opening_id: str, ids=("ev-w", "ev-h")) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id=opening_id,
        candidate_type="opening",
        evidence_ids=tuple(ids),
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=0.95,
    )


def _host(
    opening_id: str = "OP-1",
    *,
    status: str = "hosted",
    walls=("WALL-1",),
    wall_id: str = "WALL-1",
    gap_width_m: float | None = None,
) -> OpeningHostCandidate:
    reason_codes = ("multiple_candidate_walls",) if status == "ambiguous_host" else ()
    return OpeningHostCandidate(
        host_candidate_id=opening_id,
        wall_candidate_id=wall_id,
        position_along_wall_m=None,
        gap_width_m=gap_width_m,
        host_status=status,
        candidate_wall_ids_considered=tuple(walls),
        confidence=0.9,
        reason_codes=reason_codes,
    )


def test_current_w7_ambiguous_host_must_abstain() -> None:
    result = build_opening_deduction_quantity(
        host=_host(status="ambiguous_host", walls=("WALL-1", "WALL-2")),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-w", "ev-h"),
        viewport=_viewport(),
        opening_entity=_entity("OP-1"),
        width_evidence=_ev("ev-w", "opening_width_dimension", 900.0),
        height_evidence=_ev("ev-h", "opening_height_dimension", 2100.0),
    )
    assert result.abstained
    assert "opening_host_not_uniquely_resolved" in result.blocking_reasons
    assert "opening_host_candidate_cardinality_not_one" in result.blocking_reasons


def test_synthetic_uniquely_hosted_dimensioned_opening_is_ready() -> None:
    result = build_opening_deduction_quantity(
        host=_host(),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-w", "ev-h"),
        viewport=_viewport(),
        opening_entity=_entity("OP-1"),
        width_evidence=_ev("ev-w", "door_width_dimension", 900.0),
        height_evidence=_ev("ev-h", "door_height_dimension", 2100.0),
    )
    assert not result.abstained
    assert result.value == 1.89
    assert result.metadata["wall_id"] == "WALL-1"
    assert result.metadata["host_status"] == "hosted"


def test_w7_gap_width_is_never_used_as_authoritative_dimension() -> None:
    result = build_opening_deduction_quantity(
        host=_host(gap_width_m=0.9),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-h"),
        viewport=_viewport(),
        opening_entity=_entity("OP-1", ids=("ev-h",)),
        width_evidence=None,
        height_evidence=_ev("ev-h", "opening_height_dimension", 2100.0),
    )
    assert result.abstained
    assert "opening_width_missing" in result.blocking_reasons
    assert result.metadata["w7_gap_width_ignored"] == 0.9


def test_opening_count_evidence_cannot_pose_as_dimension() -> None:
    result = build_opening_deduction_quantity(
        host=_host(),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-w", "ev-h"),
        viewport=_viewport(),
        opening_entity=_entity("OP-1"),
        width_evidence=_ev("ev-w", "opening_count", 1.0, unit="ea"),
        height_evidence=_ev("ev-h", "opening_height_dimension", 2100.0),
    )
    assert result.abstained
    assert "opening_width_evidence_kind_not_authoritative" in result.blocking_reasons
    assert "opening_width_dimension_invalid" in result.blocking_reasons


def test_noncorroborated_dimension_abstains() -> None:
    width = _ev("ev-w", "opening_width_dimension", 900.0)
    width = EvidenceAtom(
        **{**width.to_dict(), "status": EvidenceResolutionStatus.CANDIDATE}
    )
    result = build_opening_deduction_quantity(
        host=_host(),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-w", "ev-h"),
        viewport=_viewport(),
        opening_entity=_entity("OP-1"),
        width_evidence=width,
        height_evidence=_ev("ev-h", "opening_height_dimension", 2100.0),
    )
    assert result.abstained
    assert "opening_width_evidence_not_corroborated" in result.blocking_reasons


def test_shared_dimension_evidence_across_opening_identities_fails_closed() -> None:
    host1 = _host("OP-1")
    host2 = _host("OP-2")
    shared_width = _ev("ev-w", "opening_width_dimension", 900.0)
    h1 = _ev("ev-h1", "opening_height_dimension", 2100.0)
    h2 = _ev("ev-h2", "opening_height_dimension", 1200.0)
    results = build_opening_deduction_quantities(
        hosts=(host1, host2),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-w", "ev-h1", "ev-h2"),
        viewport=_viewport(),
        opening_entities={
            "OP-1": _entity("OP-1", ids=("ev-w", "ev-h1")),
            "OP-2": _entity("OP-2", ids=("ev-w", "ev-h2")),
        },
        width_evidence={"OP-1": shared_width, "OP-2": shared_width},
        height_evidence={"OP-1": h1, "OP-2": h2},
    )
    assert len(results) == 2
    assert all(r.abstained for r in results)
    assert all(
        "opening_dimension_evidence_reused_across_identities" in r.blocking_reasons
        for r in results
    )


def test_deterministic_replay() -> None:
    kwargs = dict(
        host=_host(),
        wall_id="WALL-1",
        context=_ctx(),
        document=_doc("ev-w", "ev-h"),
        viewport=_viewport(),
        opening_entity=_entity("OP-1"),
        width_evidence=_ev("ev-w", "window_width_dimension", 1200.0),
        height_evidence=_ev("ev-h", "window_height_dimension", 1500.0),
    )
    first = build_opening_deduction_quantity(**kwargs)
    replay = build_opening_deduction_quantity(**kwargs)
    assert first.to_dict() == replay.to_dict()
