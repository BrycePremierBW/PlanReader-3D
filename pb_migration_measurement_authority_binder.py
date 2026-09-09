"""Shared measurement-authority binder for M5 commercial projection.

Providers must not independently manufacture figured/scaled/resolved-scale
authority.  This binder reuses the existing scale, figured-dimension, and
geometry authority modules.  It does not create a second authority ladder.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pb_figured_dimension_authority import resolve_measurement_authority
from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_migration_contracts import QuantityEvidence
from pb_page_scale_calibration_authority import (
    ScaleCalibrationStatus,
    measurement_authority_for_page_scale,
    unknown_calibration,
)


class MeasurementAuthorityBindingError(RuntimeError):
    """Raised when scaled geometry lacks resolved scale or authority is inconsistent."""


UNRELIABLE_SCALE = {
    ScaleCalibrationStatus.UNKNOWN.value,
    ScaleCalibrationStatus.CONFLICTING.value,
    ScaleCalibrationStatus.MANUAL_REQUIRED.value,
    ScaleCalibrationStatus.BLOCKED.value,
}


@dataclass(frozen=True)
class CommercialMeasurementAuthority:
    """Projection-facing authority record built only from existing modules."""

    source_type: str
    authority_status: str
    scale_calibration_status: Optional[str]
    figured_mm: Optional[float]
    scaled_mm: Optional[float]
    notes: str
    blockers: tuple[str, ...]


def bind_commercial_measurement_authority(
    quantity: QuantityEvidence,
    *,
    figured_text: Optional[str] = None,
    figured_mm: Optional[float] = None,
    scaled_mm: Optional[float] = None,
    scale_calibration: Optional[ScaleCalibration] = None,
) -> CommercialMeasurementAuthority:
    """Resolve figured-vs-scaled authority with existing shared policy."""
    blockers: list[str] = []
    calibration = scale_calibration
    scale_status = None
    scale_reliable = True
    if quantity.authority == MeasurementAuthorityType.PDF_SCALED.value or scaled_mm is not None:
        if calibration is None:
            calibration = unknown_calibration(page_no=int((quantity.metadata or {}).get("source_page") or 1))
        scale_status = calibration.status
        measured = measurement_authority_for_page_scale(calibration)
        if scale_status in UNRELIABLE_SCALE or measured == AuthorityStatus.BLOCKED.value:
            scale_reliable = False
            blockers.append("unresolved_scale")
            raise MeasurementAuthorityBindingError(
                "scaled geometry requires resolved/verified/calibrated scale; unresolved scale fails closed"
            )

    result = resolve_measurement_authority(
        scaled_mm=scaled_mm,
        figured_text=figured_text,
        figured_mm=figured_mm,
        scale_reliable=scale_reliable,
    )
    if result.authority_status == AuthorityStatus.BLOCKED.value and not figured_text and figured_mm is None:
        if quantity.authority == MeasurementAuthorityType.PDF_SCALED.value:
            raise MeasurementAuthorityBindingError(result.notes)

    source_type = result.source_type or quantity.authority
    if quantity.authority == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value:
        source_type = MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
    if quantity.authority == MeasurementAuthorityType.SCHEDULE_EXTRACTED.value:
        source_type = MeasurementAuthorityType.SCHEDULE_EXTRACTED.value

    if result.authority_status == AuthorityStatus.BLOCKED.value:
        blockers.append(result.notes)

    return CommercialMeasurementAuthority(
        source_type=source_type,
        authority_status=result.authority_status,
        scale_calibration_status=scale_status,
        figured_mm=result.figured_mm,
        scaled_mm=result.scaled_mm,
        notes=result.notes,
        blockers=tuple(blockers),
    )


def bind_direct_evidence_authority(
    quantity: QuantityEvidence,
    *,
    source_type: str,
) -> CommercialMeasurementAuthority:
    """Schedule / documented evidence without inventing scaled firmness."""
    if source_type == MeasurementAuthorityType.PDF_SCALED.value:
        raise MeasurementAuthorityBindingError("direct evidence binder cannot certify scaled geometry")
    status = quantity.status or AuthorityStatus.PROVISIONAL.value
    if status == AuthorityStatus.FIRM.value and source_type == MeasurementAuthorityType.AI_DETECTED.value:
        status = AuthorityStatus.PROVISIONAL.value
    return CommercialMeasurementAuthority(
        source_type=source_type,
        authority_status=status,
        scale_calibration_status=None,
        figured_mm=None,
        scaled_mm=None,
        notes="direct evidence authority copied from existing quantity authority; not provider-certified",
        blockers=(),
    )
