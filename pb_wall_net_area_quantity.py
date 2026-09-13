"""Fail-closed net wall-area readiness.

Net wall area is derived only after every dependency is authoritative:
FIRM gross wall area, a corroborated/owned declaration of the complete physical
opening set for that wall, and one FIRM uniquely-hosted opening deduction for
every declared opening. Any unresolved W7 opening-host candidate blocks the
result.

The completion evidence is an ordinary M1 ``EvidenceAtom`` (no new evidence
schema). Its metadata must identify the wall and the exact physical opening ids
it certifies. This module does not discover openings, does not infer missing
dimensions, and does not treat an empty detector result as proof that a wall has
no openings.
"""
from __future__ import annotations

import hashlib
import math
from typing import Mapping, Sequence

from pb_geometry_takeoff_model import AuthorityStatus
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    canonical_contract_json,
    stable_contract_id,
)
from pb_migration_provider_envelope import ProviderContext
from pb_wall_gross_area_quantity import quantity_evidence_fingerprint

NET_WALL_AREA_FAMILY = "wall_net_area"
NET_WALL_AREA_FORMULA_VERSION = "1.0.0"
_GROSS_FAMILY = "wall_gross_area"
_DEDUCTION_FAMILY = "opening_deduction_area"
_OPENING_SET_KIND = "opening_set_complete"


def _meta(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _completion_fingerprint(evidence: EvidenceAtom) -> str:
    return hashlib.sha256(
        canonical_contract_json(evidence.to_dict()).encode("utf-8")
    ).hexdigest()


def _opening_id_from_deduction(quantity: QuantityEvidence, wall_id: str) -> str | None:
    if len(quantity.input_entity_ids) != 2:
        return None
    first, second = (str(v) for v in quantity.input_entity_ids)
    if second == wall_id and first != wall_id:
        return first
    return None


def _abstain(
    *,
    wall_id: str,
    gross: QuantityEvidence,
    deductions: Sequence[QuantityEvidence],
    blockers: tuple[str, ...],
    completion_evidence: EvidenceAtom | None,
) -> QuantityEvidence:
    gross_fp = quantity_evidence_fingerprint(gross)
    deduction_fps = [quantity_evidence_fingerprint(q) for q in deductions]
    payload = {
        "family": NET_WALL_AREA_FAMILY,
        "wall_id": wall_id,
        "gross_quantity_id": gross.quantity_id,
        "gross_fingerprint": gross_fp,
        "deduction_quantity_ids": [q.quantity_id for q in deductions],
        "deduction_fingerprints": deduction_fps,
        "completion_evidence_id": completion_evidence.evidence_id if completion_evidence else None,
        "blockers": list(blockers),
    }
    evidence_ids = list(gross.evidence_ids)
    for deduction in deductions:
        evidence_ids.extend(deduction.evidence_ids)
    if completion_evidence is not None:
        evidence_ids.append(completion_evidence.evidence_id)
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=NET_WALL_AREA_FAMILY,
        semantic_key=f"wall_net_area:{wall_id}",
        value=None,
        unit="m2",
        input_entity_ids=(wall_id,),
        formula="firm_gross_wall_area_m2 - complete_firm_opening_deductions_m2",
        formula_version=NET_WALL_AREA_FORMULA_VERSION,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        authority="derived_from_firm_measurements",
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=blockers,
        reason_codes=blockers,
        metadata={
            "gross_dependency_fingerprint": gross_fp,
            "deduction_dependency_fingerprints": deduction_fps,
            "opening_set_completion_fingerprint": (
                _completion_fingerprint(completion_evidence)
                if completion_evidence is not None
                else None
            ),
        },
    )


def build_net_wall_area_quantity(
    *,
    wall_id: str,
    gross_wall_area: QuantityEvidence,
    opening_deductions: Sequence[QuantityEvidence],
    opening_set_complete_evidence: EvidenceAtom | None,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    wall_entity: EntityEvidence,
    unresolved_opening_host_ids: Sequence[str] = (),
) -> QuantityEvidence:
    """Build net area only when the opening set is explicitly complete."""
    blockers: list[str] = []
    gross_meta = _meta(gross_wall_area.metadata)

    if gross_wall_area.family != _GROSS_FAMILY:
        blockers.append("invalid_gross_wall_area_family")
    if gross_wall_area.semantic_key != f"wall_gross_area:{wall_id}":
        blockers.append("gross_wall_semantic_identity_mismatch")
    if gross_wall_area.unit != "m2":
        blockers.append("invalid_gross_wall_area_unit")
    if gross_wall_area.abstained or gross_wall_area.value is None:
        blockers.append("gross_wall_area_abstained")
    if gross_wall_area.status != AuthorityStatus.FIRM.value:
        blockers.append("gross_wall_area_not_firm")
    if tuple(gross_wall_area.input_entity_ids) != (wall_id,):
        blockers.append("gross_wall_entity_identity_mismatch")

    if wall_entity.candidate_entity_id != wall_id:
        blockers.append("wall_entity_identity_mismatch")
    if wall_entity.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("wall_entity_not_corroborated")
    if document.document_id != context.document_id:
        blockers.append("document_identity_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append("source_sha_mismatch")
    if viewport.document_id != context.document_id:
        blockers.append("viewport_document_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append("viewport_not_owned")
    if gross_meta.get("source_sha256") != context.source_sha256:
        blockers.append("gross_source_sha_mismatch")
    if gross_meta.get("revision_id") != context.current_revision_id:
        blockers.append("gross_revision_mismatch")
    if gross_meta.get("viewport_id") != viewport.viewport_id:
        blockers.append("gross_viewport_mismatch")

    unresolved_ids = tuple(str(v) for v in unresolved_opening_host_ids if str(v))
    if unresolved_ids:
        blockers.append("unresolved_opening_hosts_present")

    declared_opening_ids: tuple[str, ...] = ()
    if opening_set_complete_evidence is None:
        blockers.append("opening_set_completeness_not_evidenced")
    else:
        ev = opening_set_complete_evidence
        ev_meta = _meta(ev.metadata)
        if ev.kind != _OPENING_SET_KIND:
            blockers.append("opening_set_completion_kind_invalid")
        if ev.status != EvidenceResolutionStatus.CORROBORATED:
            blockers.append("opening_set_completion_not_corroborated")
        if ev.document_id != document.document_id:
            blockers.append("opening_set_completion_document_mismatch")
        if ev.page_id != viewport.page_id:
            blockers.append("opening_set_completion_page_mismatch")
        if ev.viewport_id not in (None, viewport.viewport_id):
            blockers.append("opening_set_completion_viewport_mismatch")
        if ev.evidence_id not in document.evidence_ids:
            blockers.append("opening_set_completion_not_owned_by_document")
        if ev.evidence_id not in wall_entity.evidence_ids:
            blockers.append("opening_set_completion_not_owned_by_wall")
        if str(ev_meta.get("wall_id") or "") != wall_id:
            blockers.append("opening_set_completion_wall_mismatch")
        raw_ids = ev_meta.get("opening_ids")
        if not isinstance(raw_ids, (list, tuple)):
            blockers.append("opening_set_completion_ids_missing")
        else:
            declared_opening_ids = tuple(str(v) for v in raw_ids)
            if any(not v for v in declared_opening_ids):
                blockers.append("opening_set_completion_id_empty")
            if len(set(declared_opening_ids)) != len(declared_opening_ids):
                blockers.append("opening_set_completion_ids_duplicate")

    observed_opening_ids: list[str] = []
    total_deduction = 0.0
    for deduction in opening_deductions:
        opening_id = _opening_id_from_deduction(deduction, wall_id)
        if deduction.family != _DEDUCTION_FAMILY:
            blockers.append("invalid_opening_deduction_family")
        if deduction.unit != "m2":
            blockers.append("invalid_opening_deduction_unit")
        if opening_id is None:
            blockers.append("opening_deduction_identity_mismatch")
        else:
            observed_opening_ids.append(opening_id)
        if deduction.abstained or deduction.value is None:
            blockers.append("opening_deduction_abstained")
        if deduction.status != AuthorityStatus.FIRM.value:
            blockers.append("opening_deduction_not_firm")
        dmeta = _meta(deduction.metadata)
        if dmeta.get("source_sha256") != context.source_sha256:
            blockers.append("opening_deduction_source_sha_mismatch")
        if dmeta.get("revision_id") != context.current_revision_id:
            blockers.append("opening_deduction_revision_mismatch")
        if dmeta.get("viewport_id") != viewport.viewport_id:
            blockers.append("opening_deduction_viewport_mismatch")
        if dmeta.get("wall_id") != wall_id:
            blockers.append("opening_deduction_wall_metadata_mismatch")
        if deduction.value is not None:
            numeric = float(deduction.value)
            if not math.isfinite(numeric) or numeric < 0.0:
                blockers.append("opening_deduction_value_invalid")
            else:
                total_deduction += numeric

    if len(set(observed_opening_ids)) != len(observed_opening_ids):
        blockers.append("duplicate_opening_deduction_identity")
    if tuple(sorted(observed_opening_ids)) != tuple(sorted(declared_opening_ids)):
        blockers.append("opening_deduction_set_not_complete")

    if gross_wall_area.value is not None:
        gross_value = float(gross_wall_area.value)
        if not math.isfinite(gross_value) or gross_value <= 0.0:
            blockers.append("gross_wall_area_value_invalid")
        elif total_deduction > gross_value:
            blockers.append("opening_deductions_exceed_gross_area")

    if blockers:
        return _abstain(
            wall_id=wall_id,
            gross=gross_wall_area,
            deductions=opening_deductions,
            blockers=tuple(dict.fromkeys(blockers)),
            completion_evidence=opening_set_complete_evidence,
        )

    assert gross_wall_area.value is not None
    value_m2 = round(float(gross_wall_area.value) - total_deduction, 6)
    gross_fp = quantity_evidence_fingerprint(gross_wall_area)
    deduction_fps = [quantity_evidence_fingerprint(q) for q in opening_deductions]
    completion_fp = _completion_fingerprint(opening_set_complete_evidence)
    payload = {
        "family": NET_WALL_AREA_FAMILY,
        "wall_id": wall_id,
        "value_m2": value_m2,
        "gross_fingerprint": gross_fp,
        "deduction_fingerprints": deduction_fps,
        "opening_set_completion_fingerprint": completion_fp,
    }
    evidence_ids = list(gross_wall_area.evidence_ids)
    for deduction in opening_deductions:
        evidence_ids.extend(deduction.evidence_ids)
    evidence_ids.append(opening_set_complete_evidence.evidence_id)
    confidences = [float(gross_wall_area.confidence), float(opening_set_complete_evidence.confidence)]
    confidences.extend(float(q.confidence) for q in opening_deductions)
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=NET_WALL_AREA_FAMILY,
        semantic_key=f"wall_net_area:{wall_id}",
        value=value_m2,
        unit="m2",
        input_entity_ids=(wall_id,),
        formula="firm_gross_wall_area_m2 - complete_firm_opening_deductions_m2",
        formula_version=NET_WALL_AREA_FORMULA_VERSION,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        authority="derived_from_firm_measurements",
        status=AuthorityStatus.FIRM.value,
        confidence=min(confidences),
        abstained=False,
        metadata={
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "viewport_id": viewport.viewport_id,
            "gross_dependency_fingerprint": gross_fp,
            "deduction_dependency_fingerprints": deduction_fps,
            "opening_set_completion_fingerprint": completion_fp,
            "opening_ids": sorted(observed_opening_ids),
            "total_opening_deduction_m2": round(total_deduction, 6),
        },
    )
