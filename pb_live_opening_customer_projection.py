"""Fail-closed live opening QuantityEvidence -> customer draft projection.

Only opening quantities that satisfy the same source-owned trace requirements as
source-closed sealing may enter this bridge. It creates no geometry, identities,
counts, measurements, or estimator approval.
"""
from __future__ import annotations

from typing import Any, Mapping

from pb_customer_output_verification import verify_sealed_customer_output

from pb_live_opening_count_source_closed_export import (
    build_live_opening_count_source_traces,
)
from pb_live_opening_source_closed_export import (
    build_live_opening_area_claim_source_traces,
)
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import seal_source_closed_run
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    quantities_to_takeoff_output_rows,
)


LIVE_OPENING_CUSTOMER_PROJECTION_SCHEMA_VERSION = "1.0.0"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _eligible_area_quantities(
    claim: LivePhysicalNetWallClaim,
) -> tuple[QuantityEvidence, ...]:
    return tuple(
        quantity
        for quantity in claim.opening_quantity_evidence
        if isinstance(quantity, QuantityEvidence)
        and quantity.family == "opening_area"
        and not quantity.abstained
        and quantity.value is not None
        and not quantity.blocking_reasons
        and (
            not isinstance(quantity.metadata, Mapping)
            or quantity.metadata.get("commercial_projection_allowed") is not False
        )
    )


def _eligible_count_quantities(
    claim: LivePhysicalNetWallClaim,
) -> tuple[QuantityEvidence, ...]:
    quantities: list[QuantityEvidence] = []
    for quantity in claim.opening_count_quantity_evidence:
        if not isinstance(quantity, QuantityEvidence):
            continue
        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        if (
            quantity.family != "opening_count"
            or quantity.abstained
            or quantity.value is None
            or quantity.blocking_reasons
            or metadata.get("schedule_corroborated") is not True
            or not _clean(metadata.get("opening_mark"))
        ):
            continue
        quantities.append(quantity)
    return tuple(quantities)


def project_live_opening_customer_rows(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> tuple[dict[str, Any], ...]:
    """Project all currently sealable opening quantities to AI-review rows."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")
    if type(workspace_id) is not int or workspace_id <= 0:
        raise ValueError("workspace_id must be an authenticated positive integer")

    area_quantities = _eligible_area_quantities(claim)
    count_quantities = _eligible_count_quantities(claim)
    quantities = (*area_quantities, *count_quantities)
    if not quantities:
        return ()

    traces = {}
    if area_quantities:
        area_traces = build_live_opening_area_claim_source_traces(
            claim,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        traces.update(
            (quantity.quantity_id, area_traces[quantity.quantity_id])
            for quantity in area_quantities
        )
    if count_quantities:
        count_traces = build_live_opening_count_source_traces(
            claim,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        traces.update(
            (quantity.quantity_id, count_traces[quantity.quantity_id])
            for quantity in count_quantities
        )

    authorities = {}
    for quantity in quantities:
        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        basis = _clean(metadata.get("area_basis")).lower()
        measurement_record_id = _clean(metadata.get("measurement_record_id"))
        if (
            quantity.family == "opening_area"
            and basis == "figured_opening_label"
            and measurement_record_id
        ):
            authority = CommercialMeasurementAuthority(
                method="figured_dimension",
                figured_dimension_ids=(measurement_record_id,),
                metadata={
                    "source": "live_opening_customer_projection",
                    "quantity_id": quantity.quantity_id,
                    "area_basis": basis,
                },
            )
        else:
            authority = CommercialMeasurementAuthority(
                method="direct_evidence",
                metadata={
                    "source": "live_opening_customer_projection",
                    "quantity_id": quantity.quantity_id,
                    "area_basis": basis or None,
                },
            )
        authorities[quantity.quantity_id] = authority
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
    "LIVE_OPENING_CUSTOMER_PROJECTION_SCHEMA_VERSION",
    "project_live_opening_customer_rows",
]
