"""Fail-closed final floor-finish QuantityEvidence -> customer projection."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from pb_customer_output_verification import verify_sealed_customer_output

from pb_live_floor_finish_area_source_closed_export import (
    build_live_floor_finish_area_source_traces,
)
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import seal_source_closed_run
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    quantities_to_takeoff_output_rows,
)


LIVE_FLOOR_FINISH_CUSTOMER_PROJECTION_SCHEMA_VERSION = "1.0.0"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _measurement_authority(quantity: QuantityEvidence) -> CommercialMeasurementAuthority:
    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    raw = metadata.get("figured_dimension_ids") or ()
    if isinstance(raw, (str, bytes)):
        raw = (raw,)
    if not isinstance(raw, (list, tuple)):
        raw = ()
    figured_ids = tuple(sorted({_clean(value) for value in raw if _clean(value)}))
    if figured_ids:
        return CommercialMeasurementAuthority(
            method="figured_dimension",
            figured_dimension_ids=figured_ids,
            metadata={
                "source": "live_floor_finish_customer_projection",
                "quantity_id": quantity.quantity_id,
                "finish_code": metadata.get("finish_code"),
                "semantic_finish": metadata.get("semantic_finish"),
            },
        )
    return CommercialMeasurementAuthority(
        method="direct_evidence",
        metadata={
            "source": "live_floor_finish_customer_projection",
            "quantity_id": quantity.quantity_id,
            "quantity_authority": quantity.authority,
            "source_dimension_page_id": metadata.get("source_dimension_page_id"),
            "finish_code": metadata.get("finish_code"),
            "semantic_finish": metadata.get("semantic_finish"),
        },
    )


def project_live_floor_finish_customer_rows(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> tuple[dict[str, Any], ...]:
    """Project every final sealable floor-finish quantity to one AI-review row."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    quantities = tuple(
        quantity
        for quantity in claim.floor_finish_quantity_evidence
        if (
            isinstance(quantity, QuantityEvidence)
            and quantity.family == "floor_finish_area"
            and not quantity.abstained
            and quantity.value is not None
            and not quantity.blocking_reasons
        )
    )
    if not quantities:
        return ()

    traces = build_live_floor_finish_area_source_traces(
        claim,
        workspace_id=int(workspace_id),
        project_id=project_id,
    )
    # Source-closed finish QuantityEvidence owns the canonical floor ID.
    # Physical floor IDs can differ; resolving them here silently drops
    # otherwise authenticated finish rows even though sealing uses canonical.
    floors = {}
    for floor in claim.canonical_floors:
        canonical_id = _clean(floor.canonical_floor_id)
        if not canonical_id:
            continue
        if canonical_id in floors:
            # The upstream source trace builder rejects duplicates too,
            # but never silently pick a last-writer-wins customer location.
            raise ValueError("duplicate canonical floor identity in finish projection")
        floors[canonical_id] = floor
    projected_quantities: list[QuantityEvidence] = []
    authorities: dict[str, CommercialMeasurementAuthority] = {}
    for quantity in quantities:
        if len(quantity.input_entity_ids) != 1:
            continue
        floor = floors.get(_clean(quantity.input_entity_ids[0]))
        if floor is None:
            continue
        metadata = (
            dict(quantity.metadata)
            if isinstance(quantity.metadata, Mapping)
            else {}
        )
        metadata.update(
            {
                "section": "Internal",
                "element": "Floor finish area",
                "location": _clean(floor.room_entity_id),
                "substrate": "Floor",
                "finish_system": _clean(
                    metadata.get("semantic_finish")
                    or floor.finish_descriptor
                ),
                "inclusion_status": "INCLUSION",
                "row_role": "floor_area",
                "commercial_projection_allowed": True,
            }
        )
        customer_quantity = replace(quantity, metadata=metadata)
        projected_quantities.append(customer_quantity)
        authorities[quantity.quantity_id] = _measurement_authority(
            customer_quantity
        )
    rows = tuple(
        quantities_to_takeoff_output_rows(
            tuple(projected_quantities),
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
    "LIVE_FLOOR_FINISH_CUSTOMER_PROJECTION_SCHEMA_VERSION",
    "project_live_floor_finish_customer_rows",
]
