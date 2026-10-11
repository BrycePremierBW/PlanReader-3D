"""Fail-closed final canonical ceiling QuantityEvidence -> customer projection."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from pb_customer_output_verification import verify_sealed_customer_output

from pb_live_ceiling_lining_source_closed_export import (
    build_live_ceiling_lining_source_traces,
)
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import seal_source_closed_run
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    quantities_to_takeoff_output_rows,
)


LIVE_CEILING_CUSTOMER_PROJECTION_SCHEMA_VERSION = "1.0.0"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _figured_authority(quantity: QuantityEvidence) -> CommercialMeasurementAuthority | None:
    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    raw = metadata.get("figured_dimension_ids") or ()
    if isinstance(raw, (str, bytes)):
        raw = (raw,)
    if not isinstance(raw, (list, tuple)):
        raw = ()
    figured_ids = tuple(sorted({_clean(value) for value in raw if _clean(value)}))
    if len(figured_ids) != 2:
        return None
    return CommercialMeasurementAuthority(
        method="figured_dimension",
        figured_dimension_ids=figured_ids,
        metadata={
            "source": "live_ceiling_customer_projection",
            "quantity_id": quantity.quantity_id,
            "finish_code": metadata.get("finish_code"),
            "semantic_finish": metadata.get("semantic_finish"),
        },
    )


def project_live_ceiling_customer_rows(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> tuple[dict[str, Any], ...]:
    """Project every final sealable canonical ceiling quantity to one AI-review row."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")
    if type(workspace_id) is not int or workspace_id <= 0:
        raise ValueError("workspace_id must be an authenticated positive integer")

    quantities = tuple(
        quantity
        for quantity in claim.ceiling_lining_quantity_evidence
        if (
            isinstance(quantity, QuantityEvidence)
            and quantity.family == "ceiling_lining"
            and not quantity.abstained
            and quantity.value is not None
            and not quantity.blocking_reasons
        )
    )
    if not quantities:
        return ()

    traces = build_live_ceiling_lining_source_traces(
        claim,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    ceilings = {
        _clean(ceiling.canonical_ceiling_id): ceiling
        for ceiling in claim.canonical_ceilings
        if _clean(ceiling.canonical_ceiling_id)
    }
    projected_quantities: list[QuantityEvidence] = []
    authorities: dict[str, CommercialMeasurementAuthority] = {}
    for quantity in quantities:
        if len(quantity.input_entity_ids) != 1:
            continue
        ceiling = ceilings.get(_clean(quantity.input_entity_ids[0]))
        if ceiling is None:
            continue
        metadata = (
            dict(quantity.metadata)
            if isinstance(quantity.metadata, Mapping)
            else {}
        )
        metadata.update(
            {
                "commercial_projection_allowed": True,
                "section": "Internal",
                "element": "Ceiling lining area",
                "location": _clean(
                    metadata.get("physical_room_id")
                    or metadata.get("canonical_room_id")
                    or ceiling.room_entity_id
                ),
                "substrate": "Other",
                "finish_system": _clean(
                    metadata.get("semantic_finish")
                    or ceiling.finish_descriptor
                ),
                "inclusion_status": "INCLUSION",
                "row_role": "ceiling_area",
            }
        )
        customer_quantity = replace(quantity, metadata=metadata)
        projected_quantities.append(customer_quantity)
        authority = _figured_authority(customer_quantity)
        if authority is not None:
            authorities[quantity.quantity_id] = authority
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
    "LIVE_CEILING_CUSTOMER_PROJECTION_SCHEMA_VERSION",
    "project_live_ceiling_customer_rows",
]
