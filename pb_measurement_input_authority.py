"""Trusted deterministic measurement-input binding for quantity providers.

This module is a narrow seam over existing PlanReader authority contracts. It
does NOT define a second scale system, canonical graph, quantity schema,
migration router, or commercial authority ladder.

It binds one physical-entity measurement to exact document/source/revision,
page, viewport and evidence ownership, then reuses the existing page-scale and
figured-dimension authorities. Only existing ``AuthorityStatus.FIRM`` results
return a value; everything else is an explicit abstention.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Optional

from pb_figured_dimension_authority import resolve_measurement_authority
from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    ViewportEvidence,
    ViewportResolutionStatus,
    canonical_contract_json,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import (
    check_calibration_freshness,
    measurement_authority_for_page_scale,
)

MEASUREMENT_INPUT_SCHEMA_VERSION = "1.0.2"


@dataclass(frozen=True)
class MeasurementInputResolution:
    """One deterministic, provenance-bound linear measurement resolution."""

    value_m: Optional[float]
    source_type: Optional[str]
    authority_status: str
    document_id: str
    source_sha256: str
    revision_id: Optional[str]
    page_no: int
    viewport_id: str
    entity_id: str
    evidence_ids: tuple[str, ...]
    figured_evidence_id: Optional[str] = None
    scale_fingerprint: Optional[str] = None
    blocking_reasons: tuple[str, ...] = ()
    notes: str = ""
    schema_version: str = MEASUREMENT_INPUT_SCHEMA_VERSION

    @property
    def abstained(self) -> bool:
        return self.value_m is None

    def fingerprint(self) -> str:
        payload = {
            "value_m": self.value_m,
            "source_type": self.source_type,
            "authority_status": self.authority_status,
            "document_id": self.document_id,
            "source_sha256": self.source_sha256,
            "revision_id": self.revision_id,
            "page_no": self.page_no,
            "viewport_id": self.viewport_id,
            "entity_id": self.entity_id,
            "evidence_ids": list(self.evidence_ids),
            "figured_evidence_id": self.figured_evidence_id,
            "scale_fingerprint": self.scale_fingerprint,
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "schema_version": self.schema_version,
        }
        return hashlib.sha256(
            canonical_contract_json(payload).encode("utf-8")
        ).hexdigest()


def _blocked(
    *,
    context: ProviderContext,
    document: DocumentEvidence,
    page_no: int,
    viewport_id: str,
    entity_id: str,
    evidence_ids: tuple[str, ...],
    reasons: tuple[str, ...],
    source_type: Optional[str] = None,
    figured_evidence_id: Optional[str] = None,
    scale_fingerprint: Optional[str] = None,
    notes: str = "",
) -> MeasurementInputResolution:
    return MeasurementInputResolution(
        value_m=None,
        source_type=source_type,
        authority_status=AuthorityStatus.BLOCKED.value,
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        revision_id=context.current_revision_id,
        page_no=page_no,
        viewport_id=viewport_id,
        entity_id=entity_id,
        evidence_ids=evidence_ids,
        figured_evidence_id=figured_evidence_id,
        scale_fingerprint=scale_fingerprint,
        blocking_reasons=reasons,
        notes=notes,
    )


def scale_calibration_fingerprint(calibration: ScaleCalibration) -> str:
    """Content fingerprint for the trusted calibration inputs actually consumed."""
    payload = {
        "page_no": calibration.page_no,
        "ratio_str": calibration.ratio_str,
        "px_per_m": calibration.px_per_m,
        "method": calibration.method,
        "is_verified": calibration.is_verified,
        "confidence": calibration.confidence,
        "sheet_label": calibration.sheet_label,
        "scale_text": calibration.scale_text,
        "source_type": calibration.source_type,
        "status": calibration.status,
        "issues": list(calibration.issues),
        "revision_id": calibration.revision_id,
        "approved_by": calibration.approved_by,
        "approved_at": calibration.approved_at,
    }
    return hashlib.sha256(
        canonical_contract_json(payload).encode("utf-8")
    ).hexdigest()


def _validate_ownership(
    *,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
    page_no: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not context.revision_id or not context.current_revision_id:
        reasons.append("revision_unbound")
    elif context.revision_id != context.current_revision_id:
        reasons.append("stale_revision")
    if document.document_id != context.document_id:
        reasons.append("document_id_mismatch")
    if document.source_sha256 != context.source_sha256:
        reasons.append("source_sha256_mismatch")
    if viewport.document_id != context.document_id:
        reasons.append("viewport_document_mismatch")
    if document.page_ids and viewport.page_id not in document.page_ids:
        reasons.append("viewport_page_not_owned_by_document")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        reasons.append("viewport_not_owned")
    if viewport.status not in (
        ViewportResolutionStatus.RESOLVED,
        ViewportResolutionStatus.DERIVED,
    ):
        reasons.append("viewport_unresolved")
    if page_no not in context.trusted_page_numbers():
        reasons.append("page_not_owned")
    mapped_page = context.page_for_viewport(viewport.viewport_id)
    if mapped_page is not None and mapped_page != page_no:
        reasons.append("viewport_page_mismatch")
    if entity.status != EvidenceResolutionStatus.CORROBORATED:
        reasons.append("entity_unresolved")
    if not set(entity.evidence_ids).issubset(set(document.evidence_ids)):
        reasons.append("entity_evidence_not_owned_by_document")
    return tuple(reasons)


def validate_scale_binding(
    *,
    context: ProviderContext,
    viewport: ViewportEvidence,
    page_no: int,
    calibration: ScaleCalibration,
) -> tuple[tuple[str, ...], ScaleCalibration, str]:
    """Validate one existing page-scale calibration for one owned viewport.

    Returns ``(blocking_reasons, freshness_checked_calibration, fingerprint)``.
    This is the shared scale-binding seam for all measurement families; it does
    not create or resolve a new scale authority.
    """
    fresh = check_calibration_freshness(calibration, context.current_revision_id)
    scale_fp = scale_calibration_fingerprint(fresh)
    reasons: list[str] = []

    if fresh.page_no != page_no:
        reasons.append("scale_page_mismatch")
    if fresh.revision_id is None:
        reasons.append("scale_revision_unbound")
    if measurement_authority_for_page_scale(fresh) != AuthorityStatus.FIRM.value:
        reasons.append("scale_not_firm")
    if not math.isfinite(float(fresh.px_per_m)) or fresh.px_per_m <= 0.0:
        reasons.append("invalid_scale_factor")

    same_page_viewports = {
        str(vp)
        for vp, owned_page in context.viewport_page_ownership
        if int(owned_page) == int(page_no)
    }
    if len(same_page_viewports) > 1:
        if viewport.resolved_scale_id != scale_fp:
            reasons.append("scale_not_bound_to_multi_viewport")
    elif not context.viewport_page_ownership and len(context.trusted_viewport_ids()) > 1:
        if viewport.resolved_scale_id != scale_fp:
            reasons.append("scale_not_bound_to_multi_viewport")
    elif viewport.resolved_scale_id is not None and viewport.resolved_scale_id != scale_fp:
        reasons.append("viewport_scale_fingerprint_mismatch")

    return tuple(reasons), fresh, scale_fp


def resolve_linear_measurement_input(
    *,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
    page_no: int,
    scaled_length_page_units: Optional[float] = None,
    scale_calibration: Optional[ScaleCalibration] = None,
    figured_evidence: Optional[EvidenceAtom] = None,
    max_delta_ratio: float = 0.05,
) -> MeasurementInputResolution:
    """Resolve one linear measurement using authoritative figured or FIRM scale.

    A CORROBORATED figured dimension has precedence. If a FIRM, viewport-bound
    scaled comparison is also available, disagreement beyond the existing
    figured-dimension tolerance blocks. Scaled-only geometry requires a current
    FIRM page scale that is unambiguous for the target viewport.
    """
    evidence_ids = tuple(entity.evidence_ids)
    ownership_reasons = _validate_ownership(
        context=context,
        document=document,
        viewport=viewport,
        entity=entity,
        page_no=page_no,
    )
    if ownership_reasons:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=ownership_reasons,
        )

    if figured_evidence is not None:
        fig_reasons: list[str] = []
        if figured_evidence.document_id != document.document_id:
            fig_reasons.append("figured_document_mismatch")
        if figured_evidence.page_id != viewport.page_id:
            fig_reasons.append("figured_page_mismatch")
        if figured_evidence.viewport_id not in (None, viewport.viewport_id):
            fig_reasons.append("figured_viewport_mismatch")
        if figured_evidence.evidence_id not in document.evidence_ids:
            fig_reasons.append("figured_evidence_not_owned_by_document")
        if figured_evidence.evidence_id not in entity.evidence_ids:
            fig_reasons.append("figured_evidence_not_owned_by_entity")
        if figured_evidence.status != EvidenceResolutionStatus.CORROBORATED:
            fig_reasons.append("figured_evidence_unresolved")
        if fig_reasons:
            return _blocked(
                context=context,
                document=document,
                page_no=page_no,
                viewport_id=viewport.viewport_id,
                entity_id=entity.candidate_entity_id,
                evidence_ids=evidence_ids,
                reasons=tuple(fig_reasons),
                source_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                figured_evidence_id=figured_evidence.evidence_id,
            )

        trusted_scaled_mm: Optional[float] = None
        scale_fp: Optional[str] = None
        if scaled_length_page_units is not None and scale_calibration is not None:
            if math.isfinite(float(scaled_length_page_units)) and float(scaled_length_page_units) > 0.0:
                scale_reasons, fresh, candidate_fp = validate_scale_binding(
                    context=context,
                    viewport=viewport,
                    page_no=page_no,
                    calibration=scale_calibration,
                )
                if not scale_reasons:
                    trusted_scaled_mm = float(scaled_length_page_units) / fresh.px_per_m * 1000.0
                    scale_fp = candidate_fp

        result = resolve_measurement_authority(
            scaled_mm=trusted_scaled_mm,
            figured_text=figured_evidence.raw_text or None,
            figured_mm=(
                figured_evidence.normalized_value
                if figured_evidence.normalized_value is not None and not figured_evidence.raw_text
                else None
            ),
            scale_reliable=trusted_scaled_mm is not None,
            max_delta_ratio=max_delta_ratio,
        )
        if result.authority_status != AuthorityStatus.FIRM.value or result.value_m is None:
            return _blocked(
                context=context,
                document=document,
                page_no=page_no,
                viewport_id=viewport.viewport_id,
                entity_id=entity.candidate_entity_id,
                evidence_ids=evidence_ids,
                reasons=("figured_measurement_not_firm",),
                source_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                figured_evidence_id=figured_evidence.evidence_id,
                scale_fingerprint=scale_fp,
                notes=result.notes,
            )
        return MeasurementInputResolution(
            value_m=result.value_m,
            source_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            authority_status=AuthorityStatus.FIRM.value,
            document_id=document.document_id,
            source_sha256=document.source_sha256,
            revision_id=context.current_revision_id,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            figured_evidence_id=figured_evidence.evidence_id,
            scale_fingerprint=scale_fp,
            notes=result.notes,
        )

    if scaled_length_page_units is None or scale_calibration is None:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=("no_authoritative_measurement_input",),
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
        )
    if not math.isfinite(float(scaled_length_page_units)) or float(scaled_length_page_units) <= 0.0:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=("invalid_scaled_geometry",),
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
        )

    scale_reasons, fresh, scale_fp = validate_scale_binding(
        context=context,
        viewport=viewport,
        page_no=page_no,
        calibration=scale_calibration,
    )
    if scale_reasons:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=scale_reasons,
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            scale_fingerprint=scale_fp,
            notes="; ".join(fresh.issues),
        )

    value_m = float(scaled_length_page_units) / fresh.px_per_m
    return MeasurementInputResolution(
        value_m=round(value_m, 6),
        source_type=MeasurementAuthorityType.PDF_SCALED.value,
        authority_status=AuthorityStatus.FIRM.value,
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        revision_id=context.current_revision_id,
        page_no=page_no,
        viewport_id=viewport.viewport_id,
        entity_id=entity.candidate_entity_id,
        evidence_ids=evidence_ids,
        scale_fingerprint=scale_fp,
        notes="FIRM page-scale authority applied to owned viewport geometry",
    )
