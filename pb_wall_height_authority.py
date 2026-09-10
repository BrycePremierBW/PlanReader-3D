"""Fail-closed wall-height QuantityEvidence authority.

Accepts only explicit, provenance-bound height evidence or a corroborated datum
pair. Legacy/model defaults (including the historical 2.8 m assumption) are never
measurement authority merely because their numeric value is plausible.
"""
from __future__ import annotations

import math
from typing import Optional

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

WALL_HEIGHT_FAMILY = "wall_height"
WALL_HEIGHT_FORMULA_VERSION = "1.0.0"

_ALLOWED_DIRECT_KINDS = {
    "wall_height_dimension",
    "ceiling_height_dimension",
    "storey_height_dimension",
    "wall_height_schedule",
    "explicit_wall_height",
}
_ALLOWED_DATUM_KINDS = {
    "level_datum",
    "elevation_datum",
    "floor_level_datum",
    "ceiling_level_datum",
}
_FORBIDDEN_DEFAULT_METHOD_TOKENS = {
    "default",
    "assumed",
    "fallback",
    "legacy_default",
    "model_default",
}


def _numeric_to_m(value: float, unit: Optional[str]) -> Optional[float]:
    if not math.isfinite(float(value)):
        return None
    normalized = (unit or "").strip().lower().replace("²", "2")
    if normalized in ("m", "metre", "meter", "metres", "meters"):
        return float(value)
    if normalized in ("mm", "millimetre", "millimeter", "millimetres", "millimeters"):
        return float(value) / 1000.0
    return None


def _evidence_is_default_or_assumed(evidence: EvidenceAtom) -> bool:
    method = str(evidence.method or "").strip().lower()
    if any(token in method for token in _FORBIDDEN_DEFAULT_METHOD_TOKENS):
        return True
    metadata = evidence.metadata if isinstance(evidence.metadata, dict) else dict(evidence.metadata)
    for key in ("default", "assumed", "is_default", "is_assumed", "legacy_default"):
        if bool(metadata.get(key)):
            return True
    origin = str(metadata.get("origin") or "").strip().lower()
    return origin in _FORBIDDEN_DEFAULT_METHOD_TOKENS


def _validate_owned_evidence(
    evidence: EvidenceAtom,
    *,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if evidence.document_id != document.document_id or document.document_id != context.document_id:
        blockers.append("height_document_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append("height_source_sha256_mismatch")
    if evidence.page_id != viewport.page_id:
        blockers.append("height_page_mismatch")
    if evidence.viewport_id not in (None, viewport.viewport_id):
        blockers.append("height_viewport_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append("height_viewport_not_owned")
    if evidence.evidence_id not in document.evidence_ids:
        blockers.append("height_evidence_not_owned_by_document")
    if evidence.evidence_id not in entity.evidence_ids:
        blockers.append("height_evidence_not_owned_by_entity")
    if evidence.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("height_evidence_not_corroborated")
    if _evidence_is_default_or_assumed(evidence):
        blockers.append("default_or_assumed_height_forbidden")
    return tuple(blockers)


def _abstain(
    *,
    wall_id: str,
    entity: EntityEvidence,
    context: ProviderContext,
    blockers: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    metadata: Optional[dict[str, object]] = None,
) -> QuantityEvidence:
    payload = {
        "family": WALL_HEIGHT_FAMILY,
        "wall_id": wall_id,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "blockers": list(blockers),
        "evidence_ids": list(evidence_ids),
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=WALL_HEIGHT_FAMILY,
        semantic_key=f"wall_height:{wall_id}",
        value=None,
        unit="m",
        input_entity_ids=(wall_id,),
        formula="explicit_height OR corroborated_datum_difference",
        formula_version=WALL_HEIGHT_FORMULA_VERSION,
        evidence_ids=evidence_ids or tuple(entity.evidence_ids),
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=blockers,
        reason_codes=blockers,
        metadata=metadata or {},
    )


def build_wall_height_quantity(
    *,
    wall_id: str,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
    direct_height_evidence: Optional[EvidenceAtom] = None,
    lower_datum_evidence: Optional[EvidenceAtom] = None,
    upper_datum_evidence: Optional[EvidenceAtom] = None,
) -> QuantityEvidence:
    """Resolve explicit wall height or datum difference; otherwise abstain."""
    if entity.candidate_entity_id != wall_id:
        return _abstain(
            wall_id=wall_id,
            entity=entity,
            context=context,
            blockers=("wall_height_entity_identity_mismatch",),
            evidence_ids=tuple(entity.evidence_ids),
        )
    if entity.status != EvidenceResolutionStatus.CORROBORATED:
        return _abstain(
            wall_id=wall_id,
            entity=entity,
            context=context,
            blockers=("wall_height_entity_not_corroborated",),
            evidence_ids=tuple(entity.evidence_ids),
        )

    if direct_height_evidence is not None:
        blockers = list(
            _validate_owned_evidence(
                direct_height_evidence,
                context=context,
                document=document,
                viewport=viewport,
                entity=entity,
            )
        )
        if direct_height_evidence.kind not in _ALLOWED_DIRECT_KINDS:
            blockers.append("unsupported_direct_height_evidence_kind")
        value_m = None
        if direct_height_evidence.normalized_value is not None:
            value_m = _numeric_to_m(direct_height_evidence.normalized_value, direct_height_evidence.unit)
        if value_m is None or value_m <= 0.0:
            blockers.append("invalid_direct_height_value")
        if blockers:
            return _abstain(
                wall_id=wall_id,
                entity=entity,
                context=context,
                blockers=tuple(blockers),
                evidence_ids=(direct_height_evidence.evidence_id,),
            )
        payload = {
            "wall_id": wall_id,
            "value_m": round(value_m, 6),
            "evidence_id": direct_height_evidence.evidence_id,
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
        }
        return QuantityEvidence(
            quantity_id=stable_contract_id("qty", payload),
            family=WALL_HEIGHT_FAMILY,
            semantic_key=f"wall_height:{wall_id}",
            value=round(value_m, 6),
            unit="m",
            input_entity_ids=(wall_id,),
            formula="authoritative_explicit_height",
            formula_version=WALL_HEIGHT_FORMULA_VERSION,
            evidence_ids=(direct_height_evidence.evidence_id,),
            authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            status=AuthorityStatus.FIRM.value,
            confidence=min(float(entity.confidence), float(direct_height_evidence.confidence)),
            abstained=False,
            metadata={
                "source_sha256": context.source_sha256,
                "revision_id": context.current_revision_id,
                "viewport_id": viewport.viewport_id,
                "evidence_kind": direct_height_evidence.kind,
            },
        )

    if lower_datum_evidence is None or upper_datum_evidence is None:
        return _abstain(
            wall_id=wall_id,
            entity=entity,
            context=context,
            blockers=("no_authoritative_wall_height_evidence",),
            evidence_ids=tuple(entity.evidence_ids),
        )

    blockers: list[str] = []
    for evidence, label in ((lower_datum_evidence, "lower"), (upper_datum_evidence, "upper")):
        blockers.extend(
            _validate_owned_evidence(
                evidence,
                context=context,
                document=document,
                viewport=viewport,
                entity=entity,
            )
        )
        if evidence.kind not in _ALLOWED_DATUM_KINDS:
            blockers.append(f"unsupported_{label}_datum_kind")
        if evidence.normalized_value is None:
            blockers.append(f"missing_{label}_datum_value")
    lower_m = (
        _numeric_to_m(lower_datum_evidence.normalized_value, lower_datum_evidence.unit)
        if lower_datum_evidence.normalized_value is not None
        else None
    )
    upper_m = (
        _numeric_to_m(upper_datum_evidence.normalized_value, upper_datum_evidence.unit)
        if upper_datum_evidence.normalized_value is not None
        else None
    )
    if lower_m is None or upper_m is None:
        blockers.append("invalid_datum_units_or_values")
        height_m = None
    else:
        height_m = upper_m - lower_m
        if not math.isfinite(height_m) or height_m <= 0.0:
            blockers.append("nonpositive_or_invalid_datum_height")

    if blockers:
        return _abstain(
            wall_id=wall_id,
            entity=entity,
            context=context,
            blockers=tuple(dict.fromkeys(blockers)),
            evidence_ids=(lower_datum_evidence.evidence_id, upper_datum_evidence.evidence_id),
        )

    assert height_m is not None
    value = round(height_m, 6)
    payload = {
        "wall_id": wall_id,
        "value_m": value,
        "lower": lower_datum_evidence.evidence_id,
        "upper": upper_datum_evidence.evidence_id,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=WALL_HEIGHT_FAMILY,
        semantic_key=f"wall_height:{wall_id}",
        value=value,
        unit="m",
        input_entity_ids=(wall_id,),
        formula="upper_datum - lower_datum",
        formula_version=WALL_HEIGHT_FORMULA_VERSION,
        evidence_ids=(lower_datum_evidence.evidence_id, upper_datum_evidence.evidence_id),
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        status=AuthorityStatus.FIRM.value,
        confidence=min(
            float(entity.confidence),
            float(lower_datum_evidence.confidence),
            float(upper_datum_evidence.confidence),
        ),
        abstained=False,
        metadata={
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "viewport_id": viewport.viewport_id,
            "lower_datum_kind": lower_datum_evidence.kind,
            "upper_datum_kind": upper_datum_evidence.kind,
        },
    )
