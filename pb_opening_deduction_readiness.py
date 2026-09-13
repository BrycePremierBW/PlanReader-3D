"""Strict opening-deduction dependency readiness.

This development-only quantity layer consumes the existing W7
``OpeningHostCandidate`` contract plus M1 evidence contracts. It deliberately
does not use the permissive legacy bbox/single-wall fallback binder.

Current W7 detection emits ``ambiguous_host`` only, so production W7 output
abstains here. A numeric deduction becomes possible only if a future,
independently-supported topology/evidence stage resolves one opening candidate
to exactly one host wall AND authoritative width/height evidence is bound to
that same physical opening identity.

No schedule count is interpreted as a dimension and ``gap_width_m`` is never
treated as authoritative width.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    stable_contract_id,
)
from pb_migration_provider_envelope import ProviderContext
from pb_wall_room_topology_contracts import OpeningHostCandidate

OPENING_DEDUCTION_FAMILY = "opening_deduction_area"
OPENING_DEDUCTION_FORMULA_VERSION = "1.0.0"

_WIDTH_KINDS = frozenset({
    "opening_width_dimension",
    "door_width_dimension",
    "window_width_dimension",
    "opening_width_schedule",
})
_HEIGHT_KINDS = frozenset({
    "opening_height_dimension",
    "door_height_dimension",
    "window_height_dimension",
    "opening_height_schedule",
})


def _value_m(evidence: EvidenceAtom) -> Optional[float]:
    if evidence.normalized_value is None:
        return None
    value = float(evidence.normalized_value)
    if not math.isfinite(value) or value <= 0.0:
        return None
    unit = str(evidence.unit or "").strip().lower()
    if unit in {"m", "metre", "meter", "metres", "meters"}:
        return value
    if unit in {"mm", "millimetre", "millimeter", "millimetres", "millimeters"}:
        return value / 1000.0
    return None


def _validate_evidence(
    evidence: EvidenceAtom,
    *,
    allowed_kinds: frozenset[str],
    label: str,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    opening_entity: EntityEvidence,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if evidence.kind not in allowed_kinds:
        blockers.append(f"{label}_evidence_kind_not_authoritative")
    if evidence.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append(f"{label}_evidence_not_corroborated")
    if evidence.document_id != document.document_id or document.document_id != context.document_id:
        blockers.append(f"{label}_document_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append(f"{label}_source_sha_mismatch")
    if evidence.page_id != viewport.page_id:
        blockers.append(f"{label}_page_mismatch")
    if evidence.viewport_id not in (None, viewport.viewport_id):
        blockers.append(f"{label}_viewport_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append(f"{label}_viewport_not_owned")
    if evidence.evidence_id not in document.evidence_ids:
        blockers.append(f"{label}_evidence_not_owned_by_document")
    if evidence.evidence_id not in opening_entity.evidence_ids:
        blockers.append(f"{label}_evidence_not_owned_by_opening")
    if _value_m(evidence) is None:
        blockers.append(f"{label}_dimension_invalid")
    return tuple(blockers)


def _abstain(
    *,
    opening_id: str,
    wall_id: str,
    opening_entity: EntityEvidence,
    context: ProviderContext,
    blockers: tuple[str, ...],
    evidence_ids: tuple[str, ...] = (),
    metadata: Optional[Mapping[str, object]] = None,
) -> QuantityEvidence:
    payload = {
        "family": OPENING_DEDUCTION_FAMILY,
        "opening_id": opening_id,
        "wall_id": wall_id,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "blockers": list(blockers),
    }
    traced = evidence_ids or tuple(opening_entity.evidence_ids)
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=OPENING_DEDUCTION_FAMILY,
        semantic_key=f"opening_deduction:{opening_id}",
        value=None,
        unit="m2",
        input_entity_ids=(opening_id, wall_id),
        formula="authoritative_opening_width_m * authoritative_opening_height_m",
        formula_version=OPENING_DEDUCTION_FORMULA_VERSION,
        evidence_ids=traced,
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=blockers,
        reason_codes=blockers,
        metadata=dict(metadata or {}),
    )


def build_opening_deduction_quantity(
    *,
    host: OpeningHostCandidate,
    wall_id: str,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    opening_entity: EntityEvidence,
    width_evidence: Optional[EvidenceAtom],
    height_evidence: Optional[EvidenceAtom],
) -> QuantityEvidence:
    """Return opening area only for a uniquely hosted, dimensioned physical opening."""
    opening_id = host.host_candidate_id
    blockers: list[str] = []

    if opening_entity.candidate_entity_id != opening_id:
        blockers.append("opening_entity_identity_mismatch")
    if opening_entity.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("opening_entity_not_corroborated")
    if document.document_id != context.document_id:
        blockers.append("opening_document_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append("opening_source_sha_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append("opening_viewport_not_owned")

    # W7 currently always takes this branch. Do not turn ambiguous gap geometry
    # into a host merely because there is only one wall in a downstream collection.
    if host.host_status != "hosted":
        blockers.append("opening_host_not_uniquely_resolved")
    if len(host.candidate_wall_ids_considered) != 1:
        blockers.append("opening_host_candidate_cardinality_not_one")
    elif host.candidate_wall_ids_considered[0] != host.wall_candidate_id:
        blockers.append("opening_host_identity_inconsistent")
    if host.wall_candidate_id != wall_id:
        blockers.append("opening_host_wall_mismatch")

    if width_evidence is None:
        blockers.append("opening_width_missing")
    if height_evidence is None:
        blockers.append("opening_height_missing")

    if blockers:
        evidence_ids = tuple(
            e.evidence_id for e in (width_evidence, height_evidence) if e is not None
        )
        return _abstain(
            opening_id=opening_id,
            wall_id=wall_id,
            opening_entity=opening_entity,
            context=context,
            blockers=tuple(dict.fromkeys(blockers)),
            evidence_ids=evidence_ids,
            metadata={
                "host_status": host.host_status,
                "candidate_wall_ids_considered": list(host.candidate_wall_ids_considered),
                "w7_gap_width_ignored": host.gap_width_m,
            },
        )

    assert width_evidence is not None and height_evidence is not None
    evidence_blockers = [
        *_validate_evidence(
            width_evidence,
            allowed_kinds=_WIDTH_KINDS,
            label="opening_width",
            context=context,
            document=document,
            viewport=viewport,
            opening_entity=opening_entity,
        ),
        *_validate_evidence(
            height_evidence,
            allowed_kinds=_HEIGHT_KINDS,
            label="opening_height",
            context=context,
            document=document,
            viewport=viewport,
            opening_entity=opening_entity,
        ),
    ]
    if width_evidence.evidence_id == height_evidence.evidence_id:
        evidence_blockers.append("opening_width_height_evidence_not_distinct")
    if evidence_blockers:
        return _abstain(
            opening_id=opening_id,
            wall_id=wall_id,
            opening_entity=opening_entity,
            context=context,
            blockers=tuple(dict.fromkeys(evidence_blockers)),
            evidence_ids=(width_evidence.evidence_id, height_evidence.evidence_id),
            metadata={
                "host_status": host.host_status,
                "candidate_wall_ids_considered": list(host.candidate_wall_ids_considered),
            },
        )

    width_m = _value_m(width_evidence)
    height_m = _value_m(height_evidence)
    assert width_m is not None and height_m is not None
    value_m2 = round(width_m * height_m, 6)
    payload = {
        "family": OPENING_DEDUCTION_FAMILY,
        "opening_id": opening_id,
        "wall_id": wall_id,
        "width_evidence_id": width_evidence.evidence_id,
        "height_evidence_id": height_evidence.evidence_id,
        "value_m2": value_m2,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "viewport_id": viewport.viewport_id,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=OPENING_DEDUCTION_FAMILY,
        semantic_key=f"opening_deduction:{opening_id}",
        value=value_m2,
        unit="m2",
        input_entity_ids=(opening_id, wall_id),
        formula="authoritative_opening_width_m * authoritative_opening_height_m",
        formula_version=OPENING_DEDUCTION_FORMULA_VERSION,
        evidence_ids=(width_evidence.evidence_id, height_evidence.evidence_id),
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.FIRM.value,
        confidence=min(
            float(opening_entity.confidence),
            float(width_evidence.confidence),
            float(height_evidence.confidence),
            float(host.confidence),
        ),
        abstained=False,
        metadata={
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "viewport_id": viewport.viewport_id,
            "page_id": viewport.page_id,
            "wall_id": wall_id,
            "host_candidate_id": opening_id,
            "host_status": host.host_status,
            "candidate_wall_ids_considered": list(host.candidate_wall_ids_considered),
            "w7_gap_width_ignored": host.gap_width_m,
        },
    )


def build_opening_deduction_quantities(
    *,
    hosts: Sequence[OpeningHostCandidate],
    wall_id: str,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    opening_entities: Mapping[str, EntityEvidence],
    width_evidence: Mapping[str, EvidenceAtom],
    height_evidence: Mapping[str, EvidenceAtom],
) -> tuple[QuantityEvidence, ...]:
    """Batch builder with duplicate physical-evidence protection.

    If the same opening id occurs twice, or one dimension EvidenceAtom is reused
    across two different opening ids, every affected claim abstains instead of
    being silently summed.
    """
    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    for host in hosts:
        if host.host_candidate_id in seen_ids:
            duplicate_ids.add(host.host_candidate_id)
        seen_ids.add(host.host_candidate_id)

    evidence_to_openings: dict[str, set[str]] = {}
    for host in hosts:
        opening_id = host.host_candidate_id
        for ev in (width_evidence.get(opening_id), height_evidence.get(opening_id)):
            if ev is not None:
                evidence_to_openings.setdefault(ev.evidence_id, set()).add(opening_id)
    shared_evidence_openings = {
        opening_id
        for openings in evidence_to_openings.values()
        if len(openings) > 1
        for opening_id in openings
    }

    out: list[QuantityEvidence] = []
    for host in hosts:
        opening_id = host.host_candidate_id
        entity = opening_entities.get(opening_id)
        if entity is None:
            raise ValueError(f"missing EntityEvidence for opening {opening_id!r}")
        duplicate_blockers: list[str] = []
        if opening_id in duplicate_ids:
            duplicate_blockers.append("duplicate_opening_identity")
        if opening_id in shared_evidence_openings:
            duplicate_blockers.append("opening_dimension_evidence_reused_across_identities")
        if duplicate_blockers:
            out.append(
                _abstain(
                    opening_id=opening_id,
                    wall_id=wall_id,
                    opening_entity=entity,
                    context=context,
                    blockers=tuple(duplicate_blockers),
                    evidence_ids=tuple(
                        ev.evidence_id
                        for ev in (width_evidence.get(opening_id), height_evidence.get(opening_id))
                        if ev is not None
                    ),
                )
            )
            continue
        out.append(
            build_opening_deduction_quantity(
                host=host,
                wall_id=wall_id,
                context=context,
                document=document,
                viewport=viewport,
                opening_entity=entity,
                width_evidence=width_evidence.get(opening_id),
                height_evidence=height_evidence.get(opening_id),
            )
        )
    return tuple(out)
