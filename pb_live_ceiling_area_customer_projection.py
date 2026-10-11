"""Fail-closed legacy canonical ceiling-area -> customer projection.

This bridge consumes only final canonical ceiling quantities that already pass
source-closed export. It changes no quantity identity, value, source authority,
or evidence lineage; it adds only customer presentation metadata and keeps the
row as an unreviewed AI draft.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from pb_customer_output_verification import verify_sealed_customer_output

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_live_ceiling_area_quantity_publication import (
    publish_live_ceiling_area_quantities,
)
from pb_live_ceiling_area_source_closed_export import (
    build_live_ceiling_area_source_traces,
)
from pb_live_ceiling_lining_integration import LiveCeilingLiningResult
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import seal_source_closed_run
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    quantities_to_takeoff_output_rows,
)


LIVE_CEILING_AREA_CUSTOMER_PROJECTION_SCHEMA_VERSION = "1.0.0"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _customer_quantity(
    quantity: QuantityEvidence,
    *,
    room_entity_id: str,
    finish_descriptor: str,
) -> QuantityEvidence:
    metadata = dict(quantity.metadata) if isinstance(quantity.metadata, Mapping) else {}
    metadata.update(
        {
            "commercial_projection_allowed": True,
            "section": "Internal",
            "element": "Ceiling lining area",
            "location": room_entity_id,
            "substrate": "Other",
            "finish_system": finish_descriptor,
            "inclusion_status": "INCLUSION",
            "row_role": "ceiling_area",
        }
    )
    return replace(quantity, metadata=metadata)


def _measurement_authority(
    quantity: QuantityEvidence,
) -> CommercialMeasurementAuthority | None:
    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    authority = _clean(quantity.authority)
    if authority == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value:
        raw = metadata.get("figured_dimension_ids") or ()
        if isinstance(raw, (str, bytes)):
            raw = (raw,)
        if not isinstance(raw, (list, tuple)):
            raw = ()
        figured = tuple(sorted({_clean(value) for value in raw if _clean(value)}))
        if not figured:
            return None
        return CommercialMeasurementAuthority(
            method="figured_dimension",
            figured_dimension_ids=figured,
            metadata={
                "source": "live_ceiling_area_customer_projection",
                "quantity_id": quantity.quantity_id,
            },
        )
    if authority == MeasurementAuthorityType.PDF_SCALED.value:
        scale_id = _clean(metadata.get("resolved_scale_id"))
        if not scale_id:
            return None
        return CommercialMeasurementAuthority(
            method="scaled_geometry",
            resolved_scale_id=scale_id,
            scale_status="resolved",
            scale_conflicts=(),
            metadata={
                "source": "live_ceiling_area_customer_projection",
                "quantity_id": quantity.quantity_id,
            },
        )
    return None


def project_live_ceiling_area_customer_rows(
    result: LiveCeilingLiningResult,
    *,
    workspace_id: int,
    project_id: str,
) -> tuple[dict[str, Any], ...]:
    """Project every final sealable legacy canonical ceiling to one AI-review row."""
    if type(result) is not LiveCeilingLiningResult:
        raise TypeError("result must be LiveCeilingLiningResult")
    if type(workspace_id) is not int or workspace_id <= 0:
        raise ValueError("workspace_id must be an authenticated positive integer")

    original = tuple(
        quantity
        for quantity in publish_live_ceiling_area_quantities(result)
        if (
            isinstance(quantity, QuantityEvidence)
            and not quantity.abstained
            and quantity.value is not None
            and not quantity.blocking_reasons
        )
    )
    if not original:
        return ()

    ceilings = {
        _clean(ceiling.canonical_ceiling_id): ceiling
        for ceiling in result.canonical_ceilings
        if _clean(ceiling.canonical_ceiling_id)
    }
    projected_quantities: list[QuantityEvidence] = []
    authorities: dict[str, CommercialMeasurementAuthority] = {}
    for quantity in original:
        if len(quantity.input_entity_ids) != 1:
            continue
        ceiling = ceilings.get(_clean(quantity.input_entity_ids[0]))
        if ceiling is None:
            continue
        customer_quantity = _customer_quantity(
            quantity,
            room_entity_id=_clean(ceiling.room_entity_id),
            finish_descriptor=_clean(ceiling.finish_descriptor),
        )
        projected_quantities.append(customer_quantity)
        authority = _measurement_authority(customer_quantity)
        if authority is not None:
            authorities[customer_quantity.quantity_id] = authority

    traces = build_live_ceiling_area_source_traces(
        result,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    rows = tuple(
        quantities_to_takeoff_output_rows(
            tuple(projected_quantities),
            traces_by_quantity_id=traces,
            authorities_by_quantity_id=authorities,
        )
    )
    sealed = seal_source_closed_run(
        original,
        project_id=project_id,
        traces_by_quantity_id=traces,
    )
    verify_sealed_customer_output(sealed, rows)
    return rows


__all__ = [
    "LIVE_CEILING_AREA_CUSTOMER_PROJECTION_SCHEMA_VERSION",
    "project_live_ceiling_area_customer_rows",
]
