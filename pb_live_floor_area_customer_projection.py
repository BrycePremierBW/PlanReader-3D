"""Fail-closed canonical floor-area -> customer draft projection.

Consumes only final floor_area QuantityEvidence already published on physical
canonical floor identity plus the exact source-closed floor trace. It does not
measure rooms/floors, infer scale, create identity, or grant estimator approval.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pb_customer_output_verification import verify_sealed_customer_output

from pb_live_floor_area_quantity_publication import (
    publish_live_floor_area_quantities,
)
from pb_live_floor_area_source_closed_export import (
    build_live_floor_area_source_traces,
)
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import seal_source_closed_run
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    quantities_to_takeoff_output_rows,
)


LIVE_FLOOR_AREA_CUSTOMER_PROJECTION_SCHEMA_VERSION = "1.0.0"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _measurement_authority(
    quantity: QuantityEvidence,
) -> CommercialMeasurementAuthority | None:
    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    authority = (
        _clean(quantity.authority)
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    if authority in {
        "documented_dimension",
        "figured_dimension",
        "documented/figured",
    } or "figured" in authority:
        raw_ids = metadata.get("figured_dimension_ids")
        if (
            not isinstance(raw_ids, (tuple, list))
            or len(raw_ids) != 2
            or any(type(value) is not str or not value.strip() for value in raw_ids)
            or len(set(raw_ids)) != 2
        ):
            # One raw string, one source tick, or competing dimension
            # systems cannot authorize physical m² at customer projection.
            return None
        figured_ids = tuple(sorted(raw_ids))
        return CommercialMeasurementAuthority(
            method="figured_dimension",
            figured_dimension_ids=figured_ids,
            metadata={
                "source": "live_floor_area_customer_projection",
                "quantity_id": quantity.quantity_id,
                "upstream_room_area_quantity_id": metadata.get(
                    "upstream_room_area_quantity_id"
                ),
            },
        )

    if "scale" in authority or "geometry" in authority:
        scale_id = _clean(metadata.get("resolved_scale_id"))
        scale_status = _clean(metadata.get("scale_status"))
        raw_conflicts = metadata.get("scale_conflicts") or ()
        if isinstance(raw_conflicts, (str, bytes)):
            raw_conflicts = (raw_conflicts,)
        if not isinstance(raw_conflicts, (list, tuple)):
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
                "source": "live_floor_area_customer_projection",
                "quantity_id": quantity.quantity_id,
                "scale_fingerprint": _clean(metadata.get("scale_fingerprint")),
            },
        )

    return None


def project_live_floor_area_customer_rows(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> tuple[dict[str, Any], ...]:
    """Project every final sealable floor_area quantity to one AI review row."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    quantities = tuple(
        quantity
        for quantity in publish_live_floor_area_quantities(claim)
        if (
            isinstance(quantity, QuantityEvidence)
            and not quantity.abstained
            and quantity.value is not None
            and not quantity.blocking_reasons
        )
    )
    if not quantities:
        return ()

    traces = build_live_floor_area_source_traces(
        claim,
        workspace_id=int(workspace_id),
        project_id=project_id,
    )
    authorities = {
        quantity.quantity_id: authority
        for quantity in quantities
        for authority in (_measurement_authority(quantity),)
        if authority is not None
    }

    # Missing measurement authority remains a hard adapter failure rather than
    # silently dropping an otherwise valid sealed floor quantity.
    rows = tuple(
        quantities_to_takeoff_output_rows(
            quantities,
            traces_by_quantity_id=traces,
            authorities_by_quantity_id=authorities,
        )
    )
    sealed = seal_source_closed_run(
        quantities,
        project_id=project_id,
        traces_by_quantity_id=traces,
    )
    verify_sealed_customer_output(sealed, rows)
    return rows


__all__ = [
    "LIVE_FLOOR_AREA_CUSTOMER_PROJECTION_SCHEMA_VERSION",
    "project_live_floor_area_customer_rows",
]
