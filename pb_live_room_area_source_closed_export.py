"""Source-closed export for live authenticated room-area quantities.

This module consumes only the live production claim and its already-published
room-area QuantityEvidence. It does not rediscover rooms, dimensions or area.
Each firm quantity must map back to exactly one enriched canonical floor and
one canonical room before a source trace can be sealed.

Unavailable/abstained room areas are intentionally omitted from the sealed
quantity set; they are not converted to zero and cannot create unsupported
commercial claims.
"""
from __future__ import annotations

import math

from pb_geometry_takeoff_model import MeasurementAuthorityType
from types import MappingProxyType
from typing import Mapping

from pb_live_canonical_floor_surface import LiveCanonicalFloorSurfaceObject
from pb_live_canonical_room_composition import LiveCanonicalRoomObject
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


def _quantity_metadata(quantity: QuantityEvidence) -> Mapping[str, object]:
    value = quantity.metadata
    return value if isinstance(value, Mapping) else {}


def _firm_room_area_quantities(
    claim: LivePhysicalNetWallClaim,
) -> tuple[QuantityEvidence, ...]:
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    out: list[QuantityEvidence] = []
    seen_ids: set[str] = set()
    for quantity in claim.room_area_quantity_evidence:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError(
                "room_area_quantity_evidence must contain QuantityEvidence"
            )
        if _clean(quantity.family) != "room_area":
            raise SourceClosedRunConflictError(
                "room-area claim contains a non-room-area quantity"
            )
        if quantity.abstained:
            continue
        quantity_id = _clean(quantity.quantity_id)
        if not quantity_id:
            raise SourceClosedRunConflictError(
                "firm room-area quantity id must be non-empty"
            )
        if quantity_id in seen_ids:
            raise SourceClosedRunConflictError(
                f"duplicate room-area quantity id: {quantity_id}"
            )
        seen_ids.add(quantity_id)
        if _clean(quantity.status).lower() != "firm":
            raise SourceClosedRunConflictError(
                f"non-abstained room-area quantity is not firm: {quantity_id}"
            )
        if _clean(quantity.unit).lower() not in {"m2", "m²"}:
            raise SourceClosedRunConflictError(
                f"room-area quantity has unsupported unit: {quantity_id}"
            )
        if quantity.blocking_reasons or quantity.authority not in {
            MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            MeasurementAuthorityType.PDF_SCALED.value,
        }:
            raise SourceClosedRunConflictError(
                f"room-area quantity lacks admissible metric authority: {quantity_id}"
            )
        for receipts in (quantity.input_entity_ids, quantity.evidence_ids):
            if (
                not isinstance(receipts, (tuple, list))
                or not receipts
                or any(type(value) is not str or not value.strip()
                       for value in receipts)
                or len(set(receipts)) != len(receipts)
            ):
                raise SourceClosedRunConflictError(
                    f"room-area source identity receipts are invalid: {quantity_id}"
                )
        try:
            numeric = float(quantity.value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceClosedRunConflictError(
                f"room-area quantity is not numeric: {quantity_id}"
            ) from exc
        if not math.isfinite(numeric) or numeric <= 0.0:
            raise SourceClosedRunConflictError(
                f"room-area quantity must be finite and positive: {quantity_id}"
            )
        if len(tuple(quantity.input_entity_ids or ())) != 1:
            raise SourceClosedRunConflictError(
                f"room-area quantity must reference exactly one source room: {quantity_id}"
            )
        out.append(quantity)

    return tuple(sorted(out, key=lambda item: item.quantity_id))


def _source_bbox(
    floor: LiveCanonicalFloorSurfaceObject,
) -> tuple[float, float, float, float]:
    points = tuple(floor.polygon_pdf_pts or ())
    if len(points) < 3:
        raise SourceClosedRunConflictError(
            f"canonical floor lacks source polygon: {floor.canonical_floor_id}"
        )
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError, IndexError) as exc:
        raise SourceClosedRunConflictError(
            f"canonical floor polygon is invalid: {floor.canonical_floor_id}"
        ) from exc
    if not xs or not all(math.isfinite(value) for value in (*xs, *ys)):
        raise SourceClosedRunConflictError(
            f"canonical floor polygon is non-finite: {floor.canonical_floor_id}"
        )
    bbox = (min(xs), min(ys), max(xs), max(ys))
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise SourceClosedRunConflictError(
            f"canonical floor polygon is degenerate: {floor.canonical_floor_id}"
        )
    return bbox


def _rooms_by_id(
    claim: LivePhysicalNetWallClaim,
) -> Mapping[str, LiveCanonicalRoomObject]:
    by_id: dict[str, LiveCanonicalRoomObject] = {}
    for room in claim.canonical_rooms:
        if type(room) is not LiveCanonicalRoomObject:
            raise TypeError("canonical_rooms must contain LiveCanonicalRoomObject")
        room_id = _clean(room.canonical_room_id)
        if not room_id:
            raise SourceClosedRunConflictError(
                "canonical room identity must be non-empty"
            )
        if room_id in by_id:
            raise SourceClosedRunConflictError(
                f"duplicate canonical room identity: {room_id}"
            )
        by_id[room_id] = room
    return MappingProxyType(by_id)


def build_live_room_area_source_traces(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    """Build exact source/canonical traces for firm live room-area quantities."""

    quantities = _firm_room_area_quantities(claim)
    rooms = _rooms_by_id(claim)

    floors_by_quantity_id: dict[str, list[LiveCanonicalFloorSurfaceObject]] = {}
    for floor in claim.canonical_floors:
        if type(floor) is not LiveCanonicalFloorSurfaceObject:
            raise TypeError(
                "canonical_floors must contain LiveCanonicalFloorSurfaceObject"
            )
        quantity_id = _clean(floor.metric_area_quantity_id)
        if quantity_id:
            floors_by_quantity_id.setdefault(quantity_id, []).append(floor)

    traces: dict[str, CommercialTakeoffSourceTrace] = {}
    for quantity in quantities:
        quantity_id = _clean(quantity.quantity_id)
        floors = floors_by_quantity_id.get(quantity_id, ())
        if len(floors) != 1:
            raise SourceClosedRunConflictError(
                f"room-area quantity {quantity_id} does not map to exactly one canonical floor"
            )
        floor = floors[0]
        room = rooms.get(_clean(floor.room_entity_id))
        if room is None:
            raise SourceClosedRunConflictError(
                f"canonical floor {floor.canonical_floor_id} references unknown room"
            )
        if (
            room.document_id != floor.document_id
            or room.revision_id != floor.revision_id
            or room.source_sha256 != floor.source_sha256
            or room.snapshot_id != floor.snapshot_id
            or str(room.page_id) != str(floor.page_id)
            or (room.viewport_id and floor.viewport_id
                and room.viewport_id != floor.viewport_id)
        ):
            raise SourceClosedRunConflictError(
                f"room and canonical floor have inconsistent original source lineage: {floor.canonical_floor_id}"
            )
        if (
            _clean(room.source_room_face_record_id)
            != _clean(floor.source_room_face_record_id)
        ):
            raise SourceClosedRunConflictError(
                f"room/floor source-face identity mismatch: {floor.canonical_floor_id}"
            )

        try:
            quantity_value = float(quantity.value)
            floor_value = float(floor.metric_area_m2)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceClosedRunConflictError(
                f"room-area metric value is unavailable: {quantity_id}"
            ) from exc
        if (
            not math.isfinite(floor_value)
            or abs(quantity_value - floor_value) > 1e-9
        ):
            raise SourceClosedRunConflictError(
                f"room-area quantity/floor metric mismatch: {quantity_id}"
            )
        if _clean(floor.metric_area_authority) != _clean(quantity.authority):
            raise SourceClosedRunConflictError(
                f"room-area quantity/floor authority mismatch: {quantity_id}"
            )

        metadata = _quantity_metadata(quantity)
        # A source room-area producer may carry additional original room
        # identity. If supplied, it must describe this exact canonical face.
        for metadata_key, original_owner in (
            ("document_id", floor.document_id),
            ("room_snapshot_id", floor.snapshot_id),
            ("source_room_face_record_id", floor.source_room_face_record_id),
        ):
            if metadata.get(metadata_key) is not None and (
                _clean(metadata[metadata_key]) != _clean(original_owner)
            ):
                raise SourceClosedRunConflictError(
                    f"room-area original source {metadata_key} mismatch: {quantity_id}"
                )
        if _clean(metadata.get("source_sha256")).lower() != floor.source_sha256.lower():
            raise SourceClosedRunConflictError(
                f"room-area quantity source hash mismatch: {quantity_id}"
            )
        if _clean(metadata.get("revision_id")) != _clean(floor.revision_id):
            raise SourceClosedRunConflictError(
                f"room-area quantity revision mismatch: {quantity_id}"
            )
        if _clean(metadata.get("page_no")) != _clean(floor.page_id):
            raise SourceClosedRunConflictError(
                f"room-area quantity source page mismatch: {quantity_id}"
            )
        viewport_id = _clean(metadata.get("viewport_id"))
        if not viewport_id:
            raise SourceClosedRunConflictError(
                f"room-area quantity viewport is unavailable: {quantity_id}"
            )
        floor_viewport = _clean(floor.viewport_id)
        if floor_viewport and floor_viewport != viewport_id:
            raise SourceClosedRunConflictError(
                f"room-area quantity/floor viewport mismatch: {quantity_id}"
            )

        if (
            not floor.geometry_complete
            or not floor.physical_floor_surface_identity_resolved
            or not _clean(floor.physical_floor_surface_id)
        ):
            raise SourceClosedRunConflictError(
                f"room-area canonical floor lacks authenticated physical geometry: {quantity_id}"
            )
        if not isinstance(floor.evidence_ids, (tuple, list)) or not floor.evidence_ids or (
            any(type(v) is not str or not v.strip() for v in floor.evidence_ids)
            or len(set(floor.evidence_ids)) != len(floor.evidence_ids)
        ):
            raise SourceClosedRunConflictError(
                f"room-area source floor evidence is invalid: {quantity_id}"
            )
        evidence_ids = tuple(floor.evidence_ids)
        missing_evidence = set(quantity.evidence_ids) - set(evidence_ids)
        if missing_evidence:
            raise SourceClosedRunConflictError(
                "canonical floor trace does not cover room-area evidence: "
                + ", ".join(sorted(missing_evidence))
            )

        canonical_entity_ids = tuple(
            dict.fromkeys(
                _clean(value)
                for value in (
                    *tuple(quantity.input_entity_ids or ()),
                    floor.canonical_floor_id,
                    floor.physical_floor_surface_id,
                    floor.room_entity_id,
                )
                if _clean(value)
            )
        )
        trace = CommercialTakeoffSourceTrace(
            workspace_id=workspace_id,
            project_id=project_id,
            document_id=floor.document_id,
            source_sha256=floor.source_sha256,
            source_page=str(floor.page_id),
            viewport_id=viewport_id,
            revision_id=floor.revision_id,
            current_revision_id=floor.revision_id,
            evidence_ids=evidence_ids,
            canonical_entity_ids=canonical_entity_ids,
            source_bbox=_source_bbox(floor),
            metadata={
                "family": quantity.family,
                "canonical_floor_id": floor.canonical_floor_id,
                "physical_floor_surface_id": floor.physical_floor_surface_id,
                "room_entity_id": floor.room_entity_id,
                "source_room_face_record_id": floor.source_room_face_record_id,
                "room_label": _clean(metadata.get("room_label")),
                "metric_area_authority": floor.metric_area_authority,
            },
        )
        if quantity_id in traces:
            raise SourceClosedRunConflictError(
                f"duplicate room-area trace quantity id: {quantity_id}"
            )
        traces[quantity_id] = trace

    return MappingProxyType(traces)


def seal_live_room_area_run(
    claim: LivePhysicalNetWallClaim,
    *,
    workspace_id: int,
    project_id: str,
) -> SealedSourceClosedRun:
    """Seal all currently firm live room-area quantities."""

    quantities = _firm_room_area_quantities(claim)
    traces = build_live_room_area_source_traces(
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
    "build_live_room_area_source_traces",
    "seal_live_room_area_run",
]
