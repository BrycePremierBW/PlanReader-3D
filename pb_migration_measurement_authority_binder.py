"""Shared measurement-authority binder for canonical M5 projection.

Providers must not independently manufacture figured/scaled/resolved-scale
authority.  This binder reuses the existing scale, figured-dimension, and
geometry authority modules, then constructs the canonical M5
``CommercialMeasurementAuthority``.  It does not define a second authority type.
"""
from __future__ import annotations

from typing import Optional

from pb_figured_dimension_authority import resolve_measurement_authority
from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_migration_contracts import QuantityEvidence
from pb_page_scale_calibration_authority import (
    ScaleCalibrationStatus,
    measurement_authority_for_page_scale,
    unknown_calibration,
)
from pb_quantity_takeoff_adapter import CommercialMeasurementAuthority


class MeasurementAuthorityBindingError(RuntimeError):
    """Raised when scaled geometry lacks resolved scale or authority is inconsistent."""


UNRELIABLE_SCALE = {
    ScaleCalibrationStatus.UNKNOWN.value,
    ScaleCalibrationStatus.CONFLICTING.value,
    ScaleCalibrationStatus.MANUAL_REQUIRED.value,
    ScaleCalibrationStatus.BLOCKED.value,
}

_RESOLVED_SCALE = {"resolved", "verified", "authoritative", "calibrated"}


def bind_commercial_measurement_authority(
    quantity: QuantityEvidence,
    *,
    figured_text: Optional[str] = None,
    figured_mm: Optional[float] = None,
    scaled_mm: Optional[float] = None,
    scale_calibration: Optional[ScaleCalibration] = None,
    figured_dimension_ids: tuple[str, ...] = (),
) -> CommercialMeasurementAuthority:
    """Resolve figured-vs-scaled authority with existing shared policy, then emit M5 type."""
    wants_scaled = quantity.authority == MeasurementAuthorityType.PDF_SCALED.value or scaled_mm is not None
    if wants_scaled and not figured_text and figured_mm is None:
        calibration = scale_calibration
        if calibration is None:
            calibration = unknown_calibration(page_no=int((quantity.metadata or {}).get("source_page") or 1))
        scale_status = str(calibration.status)
        measured = measurement_authority_for_page_scale(calibration)
        if scale_status in UNRELIABLE_SCALE or measured == AuthorityStatus.BLOCKED.value:
            raise MeasurementAuthorityBindingError(
                "scaled geometry requires resolved/verified/calibrated scale; unresolved scale fails closed"
            )
        if scale_status.lower() not in _RESOLVED_SCALE:
            raise MeasurementAuthorityBindingError(
                "scaled geometry requires resolved/verified/calibrated scale; unresolved scale fails closed"
            )
        resolved_scale_id = str((quantity.metadata or {}).get("scale_id") or getattr(calibration, "scale_id", "") or "bound_scale")
        return CommercialMeasurementAuthority(
            method="scaled_geometry",
            resolved_scale_id=resolved_scale_id,
            scale_status=scale_status.lower() if scale_status.lower() in _RESOLVED_SCALE else "resolved",
            metadata={
                "bound_by": "pb_migration_measurement_authority_binder",
                "canonical_m5_module": "pb_quantity_takeoff_adapter",
                "existing_resolver": "pb_page_scale_calibration_authority",
            },
        )

    result = resolve_measurement_authority(
        scaled_mm=scaled_mm,
        figured_text=figured_text,
        figured_mm=figured_mm,
        scale_reliable=not wants_scaled,
    )
    if result.authority_status == AuthorityStatus.BLOCKED.value and not figured_text and figured_mm is None:
        if quantity.authority == MeasurementAuthorityType.PDF_SCALED.value:
            raise MeasurementAuthorityBindingError(result.notes)

    ids = figured_dimension_ids or tuple(quantity.evidence_ids[:1]) or ("figured_bound",)
    if quantity.authority == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value or figured_text or figured_mm is not None:
        return CommercialMeasurementAuthority(
            method="figured_dimension",
            figured_dimension_ids=ids,
            metadata={
                "bound_by": "pb_migration_measurement_authority_binder",
                "canonical_m5_module": "pb_quantity_takeoff_adapter",
                "existing_resolver": "pb_figured_dimension_authority",
                "figured_mm": result.figured_mm,
                "notes": result.notes,
            },
        )
    return bind_direct_evidence_authority(quantity, source_type=quantity.authority)


def bind_direct_evidence_authority(
    quantity: QuantityEvidence,
    *,
    source_type: str,
) -> CommercialMeasurementAuthority:
    """Schedule / documented evidence without inventing scaled firmness."""
    if source_type == MeasurementAuthorityType.PDF_SCALED.value:
        raise MeasurementAuthorityBindingError("direct evidence binder cannot certify scaled geometry")
    return CommercialMeasurementAuthority(
        method="direct_evidence",
        metadata={
            "bound_by": "pb_migration_measurement_authority_binder",
            "canonical_m5_module": "pb_quantity_takeoff_adapter",
            "source_type": source_type,
            "quantity_status": quantity.status,
            "notes": "direct evidence authority copied from existing quantity authority; not provider-certified",
        },
    )
