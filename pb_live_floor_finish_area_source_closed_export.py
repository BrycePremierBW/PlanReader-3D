"""Source-closed export for authenticated canonical floor-finish quantities.

Consumes only FIRM floor_finish_area QuantityEvidence already produced by
CrossViewFloorFinishProducer and retained on the same canonical floor. This
module does not infer finishes, dimensions, room identity, or benchmark mappings.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from pb_geometry_takeoff_model import AuthorityStatus
from pb_live_canonical_floor_surface import LiveCanonicalFloorSurfaceObject
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


def build_live_floor_finish_area_source_traces(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    """Build exact source traces for already-authenticated floor finishes."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    floors_by_id: dict[str, LiveCanonicalFloorSurfaceObject] = {}
    for floor in claim.canonical_floors:
        if type(floor) is not LiveCanonicalFloorSurfaceObject:
            raise TypeError(
                "canonical_floors must contain LiveCanonicalFloorSurfaceObject"
            )
        floor_id = _clean(floor.canonical_floor_id)
        if not floor_id:
            continue
        if floor_id in floors_by_id:
            raise SourceClosedRunConflictError(
                f"duplicate canonical floor identity: {floor_id}"
            )
        floors_by_id[floor_id] = floor

    traces: dict[str, CommercialTakeoffSourceTrace] = {}
    # Defensive replay boundary: producer-owned source occurrence and physical
    # floor identity are one-to-one. Different QuantityEvidence IDs cannot
    # mint independent customer rows from the same upstream physical fact.
    quantity_owner_by_floor: dict[str, str] = {}
    quantity_owner_by_physical_floor: dict[str, tuple[str, str]] = {}
    floor_owner_by_occurrence: dict[str, str] = {}
    for quantity in claim.floor_finish_quantity_evidence:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError(
                "floor_finish_quantity_evidence must contain QuantityEvidence"
            )
        if quantity.family != "floor_finish_area":
            raise SourceClosedRunConflictError(
                f"non-floor-finish quantity reached exporter: {quantity.quantity_id}"
            )
        if quantity.abstained or quantity.value is None:
            continue
        if quantity.unit != "m2" or quantity.status != AuthorityStatus.FIRM.value:
            raise SourceClosedRunConflictError(
                "floor-finish quantity must be FIRM m2: "
                f"{quantity.quantity_id}"
            )
        if len(quantity.input_entity_ids) != 1:
            raise SourceClosedRunConflictError(
                "floor-finish quantity must own exactly one canonical floor: "
                f"{quantity.quantity_id}"
            )

        floor_id = _clean(quantity.input_entity_ids[0])
        floor = floors_by_id.get(floor_id)
        if floor is None:
            raise SourceClosedRunConflictError(
                f"floor-finish quantity references unknown canonical floor: {floor_id}"
            )
        if not floor.physical_floor_surface_identity_resolved:
            raise SourceClosedRunConflictError(
                f"physical floor identity is unresolved: {floor_id}"
            )
        if not _clean(floor.physical_floor_surface_id):
            raise SourceClosedRunConflictError(
                f"physical floor identity is missing: {floor_id}"
            )

        try:
            qvalue = float(quantity.value)
            floor_value = float(floor.metric_area_m2)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceClosedRunConflictError(
                f"floor-finish quantity is not metric: {quantity.quantity_id}"
            ) from exc
        if (
            not math.isfinite(qvalue)
            or qvalue <= 0.0
            or not math.isfinite(floor_value)
            or abs(qvalue - floor_value) > 1e-9
        ):
            raise SourceClosedRunConflictError(
                "floor-finish quantity value disagrees with canonical floor: "
                f"{quantity.quantity_id}"
            )

        metadata = (
            quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        )
        if _clean(metadata.get("canonical_floor_id")) != floor_id:
            raise SourceClosedRunConflictError(
                "floor-finish canonical identity metadata mismatch: "
                f"{quantity.quantity_id}"
            )
        if _clean(metadata.get("physical_floor_surface_id")) != _clean(
            floor.physical_floor_surface_id
        ):
            raise SourceClosedRunConflictError(
                "floor-finish physical identity metadata mismatch: "
                f"{quantity.quantity_id}"
            )
        if _clean(metadata.get("source_sha256")).lower() != _clean(
            floor.source_sha256
        ).lower():
            raise SourceClosedRunConflictError(
                f"floor-finish source SHA mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("revision_id")) != _clean(floor.revision_id):
            raise SourceClosedRunConflictError(
                f"floor-finish revision mismatch: {quantity.quantity_id}"
            )

        if _clean(metadata.get("source_room_face_record_id")) != _clean(
            floor.source_room_face_record_id
        ):
            raise SourceClosedRunConflictError(
                "floor-finish source room face mismatch: "
                f"{quantity.quantity_id}"
            )
        if _clean(metadata.get("page_no")) != _clean(floor.page_id):
            raise SourceClosedRunConflictError(
                "floor-finish source page mismatch: "
                f"{quantity.quantity_id}"
            )

        occurrence_id = _clean(metadata.get("finish_occurrence_record_id"))
        definition_id = _clean(metadata.get("finish_definition_record_id"))
        occurrence_evidence_id = _clean(
            metadata.get("finish_occurrence_evidence_id")
        )
        # Occurrence record and source receipt are different producer IDs.
        # Require the exact source occurrence witness actually retained in
        # both QuantityEvidence and its canonical floor; a metadata-only
        # occurrence assertion cannot authorize a customer finish quantity.
        if (
            not occurrence_evidence_id
            or occurrence_evidence_id not in quantity.evidence_ids
            or occurrence_evidence_id not in floor.evidence_ids
        ):
            raise SourceClosedRunConflictError(
                "floor-finish occurrence evidence receipt mismatch: "
                f"{quantity.quantity_id}"
            )
        if not occurrence_id or not definition_id:
            raise SourceClosedRunConflictError(
                "floor-finish source occurrence/definition receipt is missing: "
                f"{quantity.quantity_id}"
            )
        prior_floor = floor_owner_by_occurrence.get(occurrence_id)
        if prior_floor is not None and prior_floor != floor_id:
            raise SourceClosedRunConflictError(
                "floor-finish source occurrence has competing physical floors: "
                f"{occurrence_id}"
            )
        # Resolve the most specific failed authority first: a repeated
        # canonical floor is a direct conflict before considering competing
        # canonical aliases of the same physical surface.
        prior_quantity = quantity_owner_by_floor.get(floor_id)
        if prior_quantity is not None and prior_quantity != quantity.quantity_id:
            raise SourceClosedRunConflictError(
                "canonical floor has competing finish area quantities: "
                f"{floor_id}"
            )
        physical_floor_id = _clean(floor.physical_floor_surface_id)
        prior_physical_owner = quantity_owner_by_physical_floor.get(
            physical_floor_id
        )
        if (
            prior_physical_owner is not None
            and prior_physical_owner != (floor_id, quantity.quantity_id)
        ):
            raise SourceClosedRunConflictError(
                "physical floor has competing finish area quantities: "
                f"{physical_floor_id}"
            )
        floor_owner_by_occurrence[occurrence_id] = floor_id
        quantity_owner_by_floor[floor_id] = quantity.quantity_id
        quantity_owner_by_physical_floor[physical_floor_id] = (
            floor_id, quantity.quantity_id
        )

        semantic_finish = _clean(metadata.get("semantic_finish")).lower()
        if (
            not _clean(metadata.get("support_snapshot_id"))
            or not _clean(metadata.get("support_page_id"))
            or not _clean(metadata.get("support_viewport_id"))
            or not semantic_finish
            or _clean(floor.finish_descriptor).lower() != semantic_finish
        ):
            raise SourceClosedRunConflictError(
                "floor-finish semantic mismatch with canonical floor: "
                f"{quantity.quantity_id}"
            )

        viewport_id = _clean(metadata.get("viewport_id"))
        if not viewport_id:
            raise SourceClosedRunConflictError(
                f"floor-finish quantity lacks owned viewport: {quantity.quantity_id}"
            )
        if _clean(floor.viewport_id) and _clean(floor.viewport_id) != viewport_id:
            raise SourceClosedRunConflictError(
                f"floor-finish viewport mismatch: {quantity.quantity_id}"
            )

        # A source trace may not conceal duplicated or blank evidence IDs
        # through set normalization before commercial sealing.
        for receipts in (floor.evidence_ids, quantity.evidence_ids):
            if (
                not isinstance(receipts, (tuple, list))
                or not receipts
                or any(type(value) is not str or not value.strip() for value in receipts)
                or len(set(receipts)) != len(receipts)
            ):
                raise SourceClosedRunConflictError(
                    "floor-finish source evidence receipts are incomplete or duplicated: "
                    f"{quantity.quantity_id}"
                )
        floor_evidence = set(floor.evidence_ids)
        if not set(quantity.evidence_ids).issubset(floor_evidence):
            raise SourceClosedRunConflictError(
                "floor-finish source trace does not cover quantity evidence: "
                f"{quantity.quantity_id}"
            )

        points = tuple(floor.polygon_pdf_pts or ())
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
                    len(points) < 3
                    or not all(math.isfinite(value) for value in (*xs, *ys))
                    or max(xs) <= min(xs)
                    or max(ys) <= min(ys)
                ):
                    raise SourceClosedRunConflictError(
                        "floor-finish source polygon is invalid: "
                        f"{quantity.quantity_id}"
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
            evidence_ids=tuple(sorted(floor_evidence)),
            canonical_entity_ids=tuple(
                dict.fromkeys(
                    value
                    for value in (
                        floor_id,
                        _clean(floor.physical_floor_surface_id),
                        _clean(floor.room_entity_id),
                    )
                    if value
                )
            ),
            source_bbox=source_bbox,
            metadata={
                "family": "floor_finish_area",
                "canonical_floor_id": floor_id,
                "physical_floor_surface_id": floor.physical_floor_surface_id,
                "room_entity_id": floor.room_entity_id,
                "source_room_face_record_id": floor.source_room_face_record_id,
                "finish_code": metadata.get("finish_code"),
                "semantic_finish": semantic_finish,
                "support_snapshot_id": metadata.get("support_snapshot_id"),
                "support_page_id": metadata.get("support_page_id"),
                "support_viewport_id": metadata.get("support_viewport_id"),
                "support_source_partition_id": metadata.get(
                    "support_source_partition_id"
                ),
                "support_block_no": metadata.get("support_block_no"),
                "finish_binding_mode": metadata.get("finish_binding_mode"),
                "finish_definition_record_id": metadata.get(
                    "finish_definition_record_id"
                ),
                "finish_occurrence_record_id": metadata.get(
                    "finish_occurrence_record_id"
                ),
                "source_dimension_page_id": metadata.get(
                    "source_dimension_page_id"
                ),
            },
        )
        if quantity.quantity_id in traces:
            raise SourceClosedRunConflictError(
                f"duplicate floor-finish quantity id: {quantity.quantity_id}"
            )
        traces[quantity.quantity_id] = trace

    return MappingProxyType(traces)


def seal_live_floor_finish_area_run(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> SealedSourceClosedRun:
    """Seal already-FIRM canonical floor-finish area quantities."""
    quantities = tuple(
        quantity
        for quantity in claim.floor_finish_quantity_evidence
        if isinstance(quantity, QuantityEvidence)
        and not quantity.abstained
        and quantity.value is not None
    )
    traces = build_live_floor_finish_area_source_traces(
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
    "build_live_floor_finish_area_source_traces",
    "seal_live_floor_finish_area_run",
]
