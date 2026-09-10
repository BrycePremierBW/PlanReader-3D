"""Compatibility alias for the canonical M5 commercial projection module.

Canonical implementation: ``pb_quantity_takeoff_adapter``.

This file exists only so older control-plane import paths resolve to the same
objects.  It must not define a second projection, a second source-trace type,
or a second measurement-authority type.
"""
from __future__ import annotations

from pb_quantity_takeoff_adapter import (
    COMMERCIAL_TAKEOFF_ADAPTER_VERSION,
    CommercialMeasurementAuthority,
    CommercialTakeoffConflictError,
    CommercialTakeoffProjectionError,
    CommercialTakeoffSourceTrace,
    MissingCommercialAuthorityError,
    compute_commercial_projection_fingerprint,
    existing_commercial_gate_results,
    quantities_to_takeoff_output_rows,
    quantity_evidence_to_takeoff_output_row,
)

CANONICAL_M5_MODULE = "pb_quantity_takeoff_adapter"

__all__ = (
    "CANONICAL_M5_MODULE",
    "COMMERCIAL_TAKEOFF_ADAPTER_VERSION",
    "CommercialMeasurementAuthority",
    "CommercialTakeoffConflictError",
    "CommercialTakeoffProjectionError",
    "CommercialTakeoffSourceTrace",
    "MissingCommercialAuthorityError",
    "compute_commercial_projection_fingerprint",
    "existing_commercial_gate_results",
    "quantities_to_takeoff_output_rows",
    "quantity_evidence_to_takeoff_output_row",
)
