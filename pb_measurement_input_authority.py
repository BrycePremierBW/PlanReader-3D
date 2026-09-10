"""Trusted deterministic measurement-input binding for quantity providers.

This module is a narrow seam over existing PlanReader authority contracts. It does
NOT define a second scale system, canonical graph, quantity schema, migration
router, or commercial authority ladder.

It binds one physical entity measurement to the exact document/source/revision,
page, viewport and evidence owned by the reviewed migration control plane, then
reuses:

- ``pb_page_scale_calibration_authority`` for page-scale authority/freshness;
- ``pb_figured_dimension_authority`` for figured-dimension precedence/conflict;
- M1 ``DocumentEvidence`` / ``ViewportEvidence`` / ``EntityEvidence`` provenance.

Only ``AuthorityStatus.FIRM`` resolutions return a value. Everything else fails
closed as an explicit abstention record.
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
    canonical_contract_json,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import (
    check_calibration_freshness,
    measurement_authority_for_page_scale,
)

MEASUREMENT_INPUT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class MeasurementInputResolution:
    """One deterministic, provenance-bound measurement resolution.

    ``authority_status`` is always from the existing ``AuthorityStatus`` enum.
    This record is evidence plumbing only; it does not introduce a new authority
    ladder. A blocked result has ``value_m=None`` and at least one blocker.
    """

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
        return hashlib.sha256(canonical_contract_json(payload).encode("utf-8")).hexdigest()


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
    return hashlib.sha256(canonical_contract_json(payload).encode("utf-8")).hexdigest()


def _validate_ownership(
    *,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
    page_no: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if document.document_id != context.document_id:
        reasons.append("document_id_mismatch")
    if document.source_sha256 != context.source_sha256:
        reasons.append("source_sha256_mismatch")
    if viewport.document_id != context.document_id:
        reasons.append("viewport_document_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        reasons.append("viewport_not_owned")
    if page_no not in context.trusted_page_numbers():
        reasons.append("page_not_owned")
    mapped_page = context.page_for_viewport(viewport.viewport_id)
    if mapped_page is not None and mapped_page != page_no:
        reasons.append("viewport_page_mismatch")
    if entity.status in (EvidenceResolutionStatus.CONFLICT, EvidenceResolutionStatus.ABSTAINED):
        reasons.append("entity_unresolved")
    if not set(entity.evidence_ids).issubset(set(document.evidence_ids)):
        reasons.append("entity_evidence_not_owned_by_document")
    return tuple(reasons)


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
    """Resolve one linear measurement using trusted figured or FIRM scaled evidence.

    Figured evidence has precedence according to the existing resolver. Scaled
    geometry is only admissible when the page calibration is current and maps to
    ``AuthorityStatus.FIRM``. Any source/revision/page/viewport/evidence mismatch
    returns an explicit blocked/abstained resolution.
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
        if figured_evidence.status in (EvidenceResolutionStatus.CONFLICT, EvidenceResolutionStatus.ABSTAINED):
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
            fresh = check_calibration_freshness(scale_calibration, context.current_revision_id)
            if (
                fresh.page_no == page_no
                and measurement_authority_for_page_scale(fresh) == AuthorityStatus.FIRM.value
                and math.isfinite(fresh.px_per_m)
                and fresh.px_per_m > 0.0
                and math.isfinite(float(scaled_length_page_units))
                and float(scaled_length_page_units) > 0.0
            ):
                trusted_scaled_mm = float(scaled_length_page_units) / fresh.px_per_m * 1000.0
                scale_fp = scale_calibration_fingerprint(fresh)

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

    if scale_calibration.page_no != page_no:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=("scale_page_mismatch",),
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
        )

    fresh = check_calibration_freshness(scale_calibration, context.current_revision_id)
    scale_fp = scale_calibration_fingerprint(fresh)
    if measurement_authority_for_page_scale(fresh) != AuthorityStatus.FIRM.value:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=("scale_not_firm",),
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            scale_fingerprint=scale_fp,
            notes="; ".join(fresh.issues),
        )
    if not math.isfinite(fresh.px_per_m) or fresh.px_per_m <= 0.0:
        return _blocked(
            context=context,
            document=document,
            page_no=page_no,
            viewport_id=viewport.viewport_id,
            entity_id=entity.candidate_entity_id,
            evidence_ids=evidence_ids,
            reasons=("invalid_scale_factor",),
            source_type=MeasurementAuthorityType.PDF_SCALED.value,
            scale_fingerprint=scale_fp,
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
