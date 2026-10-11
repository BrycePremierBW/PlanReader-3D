"""Source-closed export for canonical floor-area quantities.

Consumes only floor-area QuantityEvidence already published from a FIRM room-area
authority by publish_live_floor_area_quantities. This module does not measure
floors and does not read benchmark truth.
"""
from __future__ import annotations

import math
from types import MappingProxyType
from typing import Mapping

from pb_live_floor_area_quantity_publication import (
    publish_live_floor_area_quantities,
)
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import QuantityEvidence
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace
from pb_source_closed_run_export import (
    SealedSourceClosedRun,
    SourceClosedRunConflictError,
    seal_source_closed_run,
)


def _clean(value: object) -> str:
    return str(value or "").strip()


def build_live_floor_area_source_traces(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    """Build exact floor-owned source traces for final floor-area quantities."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    floors_by_physical_id = {}
    for floor in claim.canonical_floors:
        physical_id = _clean(floor.physical_floor_surface_id)
        if not physical_id:
            continue
        if physical_id in floors_by_physical_id:
            raise SourceClosedRunConflictError(
                f"duplicate physical floor surface identity: {physical_id}"
            )
        floors_by_physical_id[physical_id] = floor

    traces: dict[str, CommercialTakeoffSourceTrace] = {}
    for quantity in publish_live_floor_area_quantities(claim):
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("floor quantities must contain QuantityEvidence")
        if quantity.family != "floor_area":
            raise SourceClosedRunConflictError(
                f"non-floor quantity reached floor exporter: {quantity.quantity_id}"
            )
        if quantity.abstained or quantity.value is None:
            continue
        if len(quantity.input_entity_ids) != 1:
            raise SourceClosedRunConflictError(
                f"floor quantity must own one physical floor identity: {quantity.quantity_id}"
            )

        physical_id = _clean(quantity.input_entity_ids[0])
        floor = floors_by_physical_id.get(physical_id)
        if floor is None:
            raise SourceClosedRunConflictError(
                f"floor quantity references unknown physical floor: {physical_id}"
            )
        if not floor.physical_floor_surface_identity_resolved:
            raise SourceClosedRunConflictError(
                f"physical floor identity is unresolved: {physical_id}"
            )

        try:
            qvalue = float(quantity.value)
            floor_value = float(floor.metric_area_m2)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceClosedRunConflictError(
                f"floor quantity is not metric: {quantity.quantity_id}"
            ) from exc
        if (
            not math.isfinite(qvalue)
            or qvalue <= 0.0
            or not math.isfinite(floor_value)
            or abs(qvalue - floor_value) > 1e-9
        ):
            raise SourceClosedRunConflictError(
                f"floor quantity value disagrees with canonical floor: {quantity.quantity_id}"
            )

        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        if _clean(metadata.get("physical_floor_surface_id")) != physical_id:
            raise SourceClosedRunConflictError(
                f"floor quantity physical identity metadata mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("canonical_floor_id")) != _clean(floor.canonical_floor_id):
            raise SourceClosedRunConflictError(
                f"floor quantity canonical identity mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("source_sha256")).lower() != _clean(floor.source_sha256).lower():
            raise SourceClosedRunConflictError(
                f"floor quantity source SHA mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("revision_id")) != _clean(floor.revision_id):
            raise SourceClosedRunConflictError(
                f"floor quantity revision mismatch: {quantity.quantity_id}"
            )

        viewport_id = _clean(metadata.get("viewport_id"))
        if not viewport_id:
            raise SourceClosedRunConflictError(
                f"floor quantity lacks owned viewport: {quantity.quantity_id}"
            )
        if _clean(floor.viewport_id) and _clean(floor.viewport_id) != viewport_id:
            raise SourceClosedRunConflictError(
                f"floor quantity viewport mismatch: {quantity.quantity_id}"
            )

        for receipts in (floor.evidence_ids, quantity.evidence_ids):
            if (
                not isinstance(receipts, (tuple, list))
                or not receipts
                or any(type(value) is not str or not value.strip() for value in receipts)
                or len(set(receipts)) != len(receipts)
            ):
                raise SourceClosedRunConflictError(
                    f"floor source evidence receipts are incomplete: {quantity.quantity_id}"
                )
        evidence_ids = tuple(floor.evidence_ids)
        if not set(quantity.evidence_ids).issubset(set(evidence_ids)):
            raise SourceClosedRunConflictError(
                f"floor source trace does not cover quantity evidence: {quantity.quantity_id}"
            )

        points = tuple(floor.polygon_pdf_pts or ())
        if not floor.geometry_complete or len(points) < 3:
            raise SourceClosedRunConflictError(
                f"floor source geometry is missing or incomplete: {quantity.quantity_id}"
            )
        source_bbox = None
        if points:
            try:
                xs = tuple(float(point[0]) for point in points)
                ys = tuple(float(point[1]) for point in points)
            except (TypeError, ValueError, IndexError) as exc:
                raise SourceClosedRunConflictError(
                    f"floor source polygon is invalid: {quantity.quantity_id}"
                ) from exc
            if xs and ys:
                if (
                    not all(math.isfinite(value) for value in (*xs, *ys))
                    or max(xs) <= min(xs)
                    or max(ys) <= min(ys)
                ):
                    raise SourceClosedRunConflictError(
                        f"floor source polygon is invalid: {quantity.quantity_id}"
                    )
                source_bbox = (min(xs), min(ys), max(xs), max(ys))

        trace = CommercialTakeoffSourceTrace(
            workspace_id=int(workspace_id),
            project_id=str(project_id),
            document_id=floor.document_id,
            source_sha256=floor.source_sha256,
            source_page=str(floor.page_id),
            viewport_id=viewport_id,
            revision_id=floor.revision_id,
            current_revision_id=floor.revision_id,
            evidence_ids=evidence_ids,
            canonical_entity_ids=tuple(
                dict.fromkeys(
                    value
                    for value in (
                        physical_id,
                        _clean(floor.canonical_floor_id),
                    )
                    if value
                )
            ),
            source_bbox=source_bbox,
            metadata={
                "family": "floor_area",
                "canonical_floor_id": floor.canonical_floor_id,
                "physical_floor_surface_id": physical_id,
                "room_entity_id": floor.room_entity_id,
                "source_room_face_record_id": floor.source_room_face_record_id,
                "upstream_room_area_quantity_id": metadata.get(
                    "upstream_room_area_quantity_id"
                ),
            },
        )
        if quantity.quantity_id in traces:
            raise SourceClosedRunConflictError(
                f"duplicate floor quantity id: {quantity.quantity_id}"
            )
        traces[quantity.quantity_id] = trace

    return MappingProxyType(traces)


def seal_live_floor_area_run(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> SealedSourceClosedRun:
    """Seal final canonical floor-area quantities on physical floor identity."""
    quantities = tuple(
        quantity
        for quantity in publish_live_floor_area_quantities(claim)
        if not quantity.abstained and quantity.value is not None
    )
    traces = build_live_floor_area_source_traces(
        claim,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return seal_source_closed_run(
        quantities,
        project_id=project_id,
        traces_by_quantity_id=traces,
    )


__all__ = [
    "build_live_floor_area_source_traces",
    "seal_live_floor_area_run",
]
