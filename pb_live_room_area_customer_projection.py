"""Fail-closed live room-area -> customer draft projection.

This bridge consumes only already-FIRM room-area QuantityEvidence plus the exact
source/canonical trace produced by the live room-area source-closed exporter.
It does not create room geometry, measurement authority, estimator approval, or
benchmark identity.

Figured/documented room areas are admitted only with explicit figured-dimension
evidence. Scaled-geometry room areas are admitted only when the upstream
QuantityEvidence also carries a current resolved scale identity/status and zero
scale conflicts. This bridge never invents scale authority. Every emitted row is
the existing commercial adapter unreviewed AI draft ("To review").
"""
from __future__ import annotations

from typing import Any, Mapping

from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_live_room_area_source_closed_export import (
    build_live_room_area_source_traces,
)
from pb_migration_contracts import QuantityEvidence
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    quantity_evidence_to_takeoff_output_row,
)


LIVE_ROOM_AREA_CUSTOMER_PROJECTION_SCHEMA_VERSION = "1.0.0"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _firm_room_area_quantities(
    claim: LivePhysicalNetWallClaim,
) -> tuple[QuantityEvidence, ...]:
    quantities: list[QuantityEvidence] = []
    seen: set[str] = set()
    for quantity in claim.room_area_quantity_evidence:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError(
                "room_area_quantity_evidence must contain QuantityEvidence"
            )
        if quantity.family != "room_area":
            continue
        if (
            quantity.abstained
            or quantity.value is None
            or _clean(quantity.status).lower() != "firm"
        ):
            continue
        quantity_id = _clean(quantity.quantity_id)
        if not quantity_id:
            continue
        if quantity_id in seen:
            raise ValueError(
                f"duplicate firm room-area quantity id: {quantity_id}"
            )
        seen.add(quantity_id)
        quantities.append(quantity)
    return tuple(sorted(quantities, key=lambda item: item.quantity_id))


def _figured_measurement_authority(
    quantity: QuantityEvidence,
) -> CommercialMeasurementAuthority | None:
    """Return explicit figured authority, never inferred scale authority."""
    authority = (
        _clean(quantity.authority)
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if authority not in {
        "documented_dimension",
        "figured_dimension",
        "documented/figured",
    } and "figured" not in authority:
        return None

    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    raw_ids = metadata.get("figured_dimension_ids")
    if (
        not isinstance(raw_ids, (tuple, list))
        or len(raw_ids) != 2
        or any(type(value) is not str or not value.strip() for value in raw_ids)
        or len(set(raw_ids)) != 2
    ):
        return None
    figured_ids = tuple(sorted(raw_ids))

    return CommercialMeasurementAuthority(
        method="figured_dimension",
        figured_dimension_ids=figured_ids,
        metadata={
            "source": "live_room_area_customer_projection",
            "quantity_id": quantity.quantity_id,
        },
    )


def _scaled_measurement_authority(
    quantity: QuantityEvidence,
) -> CommercialMeasurementAuthority | None:
    """Return explicit scaled authority, never inferred from a fingerprint."""
    authority = (
        _clean(quantity.authority)
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if "scale" not in authority and "geometry" not in authority:
        return None

    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    scale_id = _clean(metadata.get("resolved_scale_id"))
    scale_status = _clean(metadata.get("scale_status"))
    raw_conflicts = metadata.get("scale_conflicts") or ()
    if isinstance(raw_conflicts, (str, bytes)):
        raw_conflicts = (raw_conflicts,)
    elif not isinstance(raw_conflicts, (list, tuple)):
        raw_conflicts = ()
    conflicts = tuple(
        sorted({_clean(value) for value in raw_conflicts if _clean(value)})
    )
    if not scale_id or not scale_status:
        return None

    return CommercialMeasurementAuthority(
        method="scaled_geometry",
        resolved_scale_id=scale_id,
        scale_status=scale_status,
        scale_conflicts=conflicts,
        metadata={
            "source": "live_room_area_customer_projection",
            "quantity_id": quantity.quantity_id,
            "scale_fingerprint": _clean(metadata.get("scale_fingerprint")),
        },
    )


def _measurement_authority(
    quantity: QuantityEvidence,
) -> CommercialMeasurementAuthority | None:
    figured = _figured_measurement_authority(quantity)
    if figured is not None:
        return figured
    return _scaled_measurement_authority(quantity)


def project_live_room_area_customer_rows(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> tuple[dict[str, Any], ...]:
    """Project source-closed room areas into unreviewed customer rows.

    Source/canonical lineage is revalidated by
    build_live_room_area_source_traces. Missing or ambiguous floor mapping
    fails closed there. ABSTAIN/BLOCKED quantities are omitted. Scaled geometry
    is admitted only when the quantity explicitly carries current resolved scale
    authority; a scale fingerprint alone is never sufficient.
    """
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    quantities = _firm_room_area_quantities(claim)
    if not quantities:
        return ()

    traces = build_live_room_area_source_traces(
        claim,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    rows: list[dict[str, Any]] = []
    for quantity in quantities:
        trace = traces.get(quantity.quantity_id)
        if trace is None:
            raise ValueError(
                f"missing live room-area source trace: {quantity.quantity_id}"
            )
        authority = _measurement_authority(quantity)
        if authority is None:
            continue
        row = quantity_evidence_to_takeoff_output_row(
            quantity,
            trace=trace,
            authority=authority,
        )
        if row is not None:
            rows.append(row)
    return tuple(rows)


__all__ = [
    "LIVE_ROOM_AREA_CUSTOMER_PROJECTION_SCHEMA_VERSION",
    "project_live_room_area_customer_rows",
]
