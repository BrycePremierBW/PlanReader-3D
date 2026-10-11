"""Canonical room-floor surface projection from source-owned room faces.

A source-authenticated room footprint is useful shared geometry for flooring,
tiling, coatings, skirtings, costing, 3D and drawings. This module preserves
that footprint once as a room-owned horizontal surface without claiming that:
- a structural slab has been identified,
- a floor finish/material has been identified,
- metric geometry or metric area is resolved,
- a commercial quantity is authorized.

Structural slabs remain a separate canonical object family.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Optional

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_live_canonical_room_composition import (
    LiveCanonicalRoomComposition,
    LiveCanonicalRoomObject,
)
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_source_room_area_bridge import SourceRoomAreaBridgeResult


LIVE_CANONICAL_FLOOR_SURFACE_SCHEMA_VERSION = "1.1.0"
LIVE_CANONICAL_FLOOR_SURFACE_RESOLVED = (
    "live_canonical_floor_surface_projection_resolved"
)
LIVE_CANONICAL_FLOOR_SURFACE_PARTIAL = (
    "live_canonical_floor_surface_projection_partial"
)
LIVE_CANONICAL_FLOOR_SURFACE_UNAVAILABLE = (
    "live_canonical_floor_surface_projection_unavailable"
)
LIVE_CANONICAL_FLOOR_METRIC_AREA_RESOLVED = (
    "live_canonical_floor_metric_area_resolved"
)
LIVE_CANONICAL_FLOOR_METRIC_AREA_PARTIAL = (
    "live_canonical_floor_metric_area_partial"
)
LIVE_CANONICAL_FLOOR_METRIC_AREA_UNAVAILABLE = (
    "live_canonical_floor_metric_area_unavailable"
)
LIVE_CANONICAL_FLOOR_METRIC_AREA_CONFLICT = (
    "live_canonical_floor_metric_area_conflict"
)


@dataclass(frozen=True)
class LiveCanonicalFloorSurfaceObject:
    canonical_floor_id: str
    physical_floor_surface_id: str
    room_entity_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    viewport_id: Optional[str]
    polygon_pdf_pts: tuple[tuple[float, float], ...]
    area_page_pts2: float
    bounding_wall_ids: tuple[str, ...]
    canonical_bounding_wall_ids: tuple[str, ...]
    source_room_face_record_id: str
    evidence_ids: tuple[str, ...]
    geometry_complete: bool
    metric_geometry_complete: bool
    metric_area_m2: Optional[float]
    metric_area_quantity_id: Optional[str]
    metric_area_authority: Optional[str]
    finish_descriptor: Optional[str]
    structural_slab_id: Optional[str]
    physical_floor_surface_identity_resolved: bool
    commercial_quantity_authority: bool
    coordinate_space: str = "source_page_points"
    schema_version: str = LIVE_CANONICAL_FLOOR_SURFACE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "canonical_floor_id": self.canonical_floor_id,
            "physical_floor_surface_id": self.physical_floor_surface_id,
            "room_entity_id": self.room_entity_id,
            "document_id": self.document_id,
            "revision_id": self.revision_id,
            "source_sha256": self.source_sha256,
            "snapshot_id": self.snapshot_id,
            "page_id": self.page_id,
            "viewport_id": self.viewport_id,
            "polygon_pdf_pts": [list(point) for point in self.polygon_pdf_pts],
            "area_page_pts2": self.area_page_pts2,
            "bounding_wall_ids": list(self.bounding_wall_ids),
            "canonical_bounding_wall_ids": list(
                self.canonical_bounding_wall_ids
            ),
            "source_room_face_record_id": self.source_room_face_record_id,
            "evidence_ids": list(self.evidence_ids),
            "geometry_complete": self.geometry_complete,
            "metric_geometry_complete": self.metric_geometry_complete,
            "metric_area_m2": self.metric_area_m2,
            "metric_area_quantity_id": self.metric_area_quantity_id,
            "metric_area_authority": self.metric_area_authority,
            "finish_descriptor": self.finish_descriptor,
            "structural_slab_id": self.structural_slab_id,
            "physical_floor_surface_identity_resolved": (
                self.physical_floor_surface_identity_resolved
            ),
            "commercial_quantity_authority": self.commercial_quantity_authority,
            "coordinate_space": self.coordinate_space,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LiveCanonicalFloorSurfaceComposition:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    floors: tuple[LiveCanonicalFloorSurfaceObject, ...]
    source_pages: tuple[int, ...]
    schema_version: str = LIVE_CANONICAL_FLOOR_SURFACE_SCHEMA_VERSION


def _floor_from_room(room: LiveCanonicalRoomObject) -> LiveCanonicalFloorSurfaceObject:
    physical_room_id = str(room.physical_room_id or "").strip()
    if not physical_room_id:
        raise ValueError("canonical room physical identity is required for floor projection")
    floor_id = stable_contract_id(
        "physical_room_floor_surface",
        {
            "document_id": room.document_id,
            "physical_room_id": physical_room_id,
            "surface_role": "floor",
        },
        digest_chars=32,
    )
    return LiveCanonicalFloorSurfaceObject(
        canonical_floor_id=floor_id,
        physical_floor_surface_id=floor_id,
        room_entity_id=room.canonical_room_id,
        document_id=room.document_id,
        revision_id=room.revision_id,
        source_sha256=room.source_sha256,
        snapshot_id=room.snapshot_id,
        page_id=room.page_id,
        viewport_id=room.viewport_id,
        polygon_pdf_pts=room.polygon_pdf_pts,
        area_page_pts2=float(room.area_page_pts2),
        bounding_wall_ids=room.bounding_wall_ids,
        canonical_bounding_wall_ids=room.canonical_bounding_wall_ids,
        source_room_face_record_id=room.source_room_face_record_id,
        evidence_ids=room.evidence_ids,
        geometry_complete=bool(room.geometry_complete),
        metric_geometry_complete=False,
        metric_area_m2=None,
        metric_area_quantity_id=None,
        metric_area_authority=None,
        finish_descriptor=None,
        structural_slab_id=None,
        physical_floor_surface_identity_resolved=True,
        commercial_quantity_authority=False,
    )


def compose_live_canonical_floor_surfaces(
    room_composition: LiveCanonicalRoomComposition,
) -> LiveCanonicalFloorSurfaceComposition:
    """Project canonical room footprints into reusable floor-surface candidates."""

    if type(room_composition) is not LiveCanonicalRoomComposition:
        raise TypeError(
            "room_composition must be LiveCanonicalRoomComposition"
        )

    if not room_composition.rooms:
        return LiveCanonicalFloorSurfaceComposition(
            status=EvidenceResolutionStatus.ABSTAINED,
            reason_codes=(LIVE_CANONICAL_FLOOR_SURFACE_UNAVAILABLE,),
            floors=(),
            source_pages=(),
        )

    floors = tuple(
        sorted(
            (_floor_from_room(room) for room in room_composition.rooms),
            key=lambda floor: (floor.page_id, floor.canonical_floor_id),
        )
    )

    if room_composition.status is EvidenceResolutionStatus.CORROBORATED:
        status = EvidenceResolutionStatus.CORROBORATED
        reasons = (LIVE_CANONICAL_FLOOR_SURFACE_RESOLVED,)
    else:
        status = EvidenceResolutionStatus.CANDIDATE
        reasons = (
            LIVE_CANONICAL_FLOOR_SURFACE_PARTIAL,
            *room_composition.reason_codes,
        )

    return LiveCanonicalFloorSurfaceComposition(
        status=status,
        reason_codes=reasons,
        floors=floors,
        source_pages=room_composition.source_pages,
    )


def _valid_metric_area_quantity(
    floor: LiveCanonicalFloorSurfaceObject,
    quantity,
    *,
    source_room_entity,
) -> bool:
    if quantity.abstained:
        return False
    if str(quantity.family or "") != "room_area":
        return False
    if str(quantity.status or "").lower() != "firm":
        return False
    if str(quantity.unit or "").lower() not in {"m2", "m²"}:
        return False
    if quantity.blocking_reasons:
        return False
    if str(quantity.authority or "").strip() not in {
        MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        MeasurementAuthorityType.PDF_SCALED.value,
    }:
        return False
    if source_room_entity.status is not EvidenceResolutionStatus.CORROBORATED:
        return False
    source_room_id = str(source_room_entity.candidate_entity_id or "").strip()
    if not source_room_id:
        return False
    if tuple(quantity.input_entity_ids or ()) != (source_room_id,):
        return False
    if floor.source_room_face_record_id not in tuple(
        str(value) for value in (source_room_entity.evidence_ids or ())
    ):
        return False
    source_metadata = dict(source_room_entity.metadata or {})
    if str(source_metadata.get("source_sha256") or "").lower() != floor.source_sha256.lower():
        return False
    if str(source_metadata.get("revision_id") or "") != floor.revision_id:
        return False
    if str(source_metadata.get("page_id") or "") != str(floor.page_id):
        return False
    if (
        type(quantity.value) not in (int, float)
        or type(quantity.confidence) not in (int, float)
        or not isinstance(quantity.evidence_ids, (tuple, list))
        or not quantity.evidence_ids
        or any(type(receipt) is not str or not receipt or receipt != receipt.strip()
               for receipt in quantity.evidence_ids)
        or len(set(quantity.evidence_ids)) != len(quantity.evidence_ids)
    ):
        return False
    try:
        source_confidence = float(quantity.confidence)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(source_confidence) or not 0.0 <= source_confidence <= 1.0:
        return False
    if not str(quantity.quantity_id or "").strip():
        return False
    if not str(quantity.authority or "").strip():
        return False
    try:
        value = float(quantity.value)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(value) or value <= 0.0:
        return False
    metadata = dict(quantity.metadata or {})
    if str(metadata.get("source_sha256") or "").lower() != floor.source_sha256.lower():
        return False
    if str(metadata.get("revision_id") or "") != floor.revision_id:
        return False
    # A dimension-support snapshot may legitimately differ from the room
    # snapshot. But if the source quantity declares the physical ROOM's
    # source snapshot or source face, it must match the floor being enriched.
    # Otherwise two same-value room areas can cross-bind by page/viewport.
    room_snapshot = str(metadata.get("room_snapshot_id") or "").strip()
    if room_snapshot and room_snapshot != floor.snapshot_id:
        return False
    source_face = str(metadata.get("source_room_face_record_id") or "").strip()
    if source_face and source_face != floor.source_room_face_record_id:
        return False
    if str(metadata.get("page_no") or "") != str(floor.page_id):
        return False
    quantity_evidence_ids = tuple(quantity.evidence_ids)
    if not quantity_evidence_ids:
        return False
    if not set(quantity_evidence_ids).issubset(
        {str(value) for value in (source_room_entity.evidence_ids or ())}
    ):
        return False
    return True


def enrich_live_canonical_floor_metric_areas(
    floor_composition: LiveCanonicalFloorSurfaceComposition,
    room_area_bridge: SourceRoomAreaBridgeResult,
) -> LiveCanonicalFloorSurfaceComposition:
    """Attach producer-owned metric room area to the same canonical floor identity.

    The bridge may enrich area only.  It cannot promote source-page polygon
    coordinates into metric geometry, identify a structural slab, assign a
    finish, or grant commercial quantity authority.
    """

    if type(floor_composition) is not LiveCanonicalFloorSurfaceComposition:
        raise TypeError(
            "floor_composition must be LiveCanonicalFloorSurfaceComposition"
        )
    if type(room_area_bridge) is not SourceRoomAreaBridgeResult:
        raise TypeError("room_area_bridge must be SourceRoomAreaBridgeResult")
    if not floor_composition.floors:
        return floor_composition
    if floor_composition.status is EvidenceResolutionStatus.CONFLICT:
        # A conflicted physical floor must not regain FIRM quantity merely
        # because a third producer's bridge happens to arrive later. Keep
        # the fail-closed composition immutable across sequential replays.
        return floor_composition

    quantities_by_room: dict[str, list] = {}
    for quantity in room_area_bridge.quantities:
        room_ids = tuple(str(value) for value in (quantity.input_entity_ids or ()))
        if len(room_ids) == 1:
            quantities_by_room.setdefault(room_ids[0], []).append(quantity)

    source_entities_by_face_record: dict[str, list] = {}
    for entity in room_area_bridge.entities:
        for evidence_id in tuple(str(value) for value in (entity.evidence_ids or ())):
            source_entities_by_face_record.setdefault(evidence_id, []).append(entity)

    enriched: list[LiveCanonicalFloorSurfaceObject] = []
    conflict = False
    for floor in floor_composition.floors:
        source_entities = source_entities_by_face_record.get(
            floor.source_room_face_record_id,
            (),
        )
        if len(source_entities) != 1:
            enriched.append(floor)
            continue
        source_room_entity = source_entities[0]
        source_room_id = str(source_room_entity.candidate_entity_id or "").strip()
        candidates = [
            quantity
            for quantity in quantities_by_room.get(source_room_id, ())
            if _valid_metric_area_quantity(
                floor,
                quantity,
                source_room_entity=source_room_entity,
            )
        ]
        # Identical producer-owned FIRM receipts can be replayed harmlessly.
        # Distinct receipts remain competing authority and must fail closed.
        unique_candidates = []
        for candidate in candidates:
            if not any(candidate == previous for previous in unique_candidates):
                unique_candidates.append(candidate)
        candidates = unique_candidates
        if len(candidates) > 1:
            conflict = True
            # No quantity may escape for a face with competing FIRM claims.
            enriched.append(
                replace(
                    floor,
                    metric_area_m2=None,
                    metric_area_quantity_id=None,
                    metric_area_authority=None,
                )
            )
            continue
        if not candidates:
            enriched.append(floor)
            continue

        quantity = candidates[0]
        value = float(quantity.value)
        # A later bridge must not silently replace an independently
        # authenticated measurement already attached to this physical floor.
        # The exact same claim may be replayed, but contradictory identities,
        # values, or measurement authorities are a conflict.
        if (
            floor.metric_area_quantity_id is not None
            or floor.metric_area_m2 is not None
            or floor.metric_area_authority is not None
        ):
            try:
                same_claim = (
                    str(floor.metric_area_quantity_id or "").strip()
                    == str(quantity.quantity_id or "").strip()
                    and str(floor.metric_area_authority or "").strip()
                    == str(quantity.authority or "").strip()
                    and floor.metric_area_m2 is not None
                    and math.isfinite(float(floor.metric_area_m2))
                    and abs(float(floor.metric_area_m2) - value) <= 1e-9
                )
            except (TypeError, ValueError, OverflowError):
                same_claim = False
            if not same_claim:
                conflict = True
                # Retain physical identity and provenance, but revoke the
                # contested metric measurement from this claim's output.
                # Otherwise the downstream floor quantity publisher could
                # still seal the original value despite the CONFLICT.
                enriched.append(
                    replace(
                        floor,
                        metric_area_m2=None,
                        metric_area_quantity_id=None,
                        metric_area_authority=None,
                    )
                )
                continue
        enriched.append(
            replace(
                floor,
                evidence_ids=tuple(
                    dict.fromkeys(
                        (
                            *floor.evidence_ids,
                            *(str(item) for item in quantity.evidence_ids),
                        )
                    )
                ),
                metric_area_m2=value,
                metric_area_quantity_id=str(quantity.quantity_id),
                metric_area_authority=str(quantity.authority),
                metric_geometry_complete=False,
                commercial_quantity_authority=False,
            )
        )

    if conflict:
        return LiveCanonicalFloorSurfaceComposition(
            status=EvidenceResolutionStatus.CONFLICT,
            reason_codes=(LIVE_CANONICAL_FLOOR_METRIC_AREA_CONFLICT,),
            floors=tuple(enriched),
            source_pages=floor_composition.source_pages,
        )

    # Each input bridge covers one exact page/scope; a canonical floor may
    # already have a valid measurement from an earlier bridge. Resolve status
    # from the CUMULATIVE floor state, not just matches in this bridge.
    def _measured(floor: LiveCanonicalFloorSurfaceObject) -> bool:
        if not floor.metric_area_quantity_id or not floor.metric_area_authority:
            return False
        if type(floor.metric_area_m2) not in (int, float):
            return False
        try:
            area = float(floor.metric_area_m2)
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(area) and area > 0.0

    measured_count = sum(_measured(floor) for floor in enriched)
    metric_reasons = {
        LIVE_CANONICAL_FLOOR_METRIC_AREA_RESOLVED,
        LIVE_CANONICAL_FLOOR_METRIC_AREA_PARTIAL,
        LIVE_CANONICAL_FLOOR_METRIC_AREA_UNAVAILABLE,
    }
    base_reasons = tuple(
        reason
        for reason in floor_composition.reason_codes
        if reason not in metric_reasons
    )

    if measured_count == len(enriched):
        # Only a previously source-corroborated floor universe may regain
        # CORROBORATED after all its separate measurement bridges close.
        topology_complete = (
            LIVE_CANONICAL_FLOOR_SURFACE_RESOLVED in base_reasons
            and LIVE_CANONICAL_FLOOR_SURFACE_PARTIAL not in base_reasons
        )
        return LiveCanonicalFloorSurfaceComposition(
            status=(
                EvidenceResolutionStatus.CORROBORATED
                if topology_complete
                else floor_composition.status
            ),
            reason_codes=(
                *base_reasons,
                LIVE_CANONICAL_FLOOR_METRIC_AREA_RESOLVED,
            ),
            floors=tuple(enriched),
            source_pages=floor_composition.source_pages,
        )

    if measured_count:
        return LiveCanonicalFloorSurfaceComposition(
            status=EvidenceResolutionStatus.CANDIDATE,
            reason_codes=(
                *base_reasons,
                LIVE_CANONICAL_FLOOR_METRIC_AREA_PARTIAL,
            ),
            floors=tuple(enriched),
            source_pages=floor_composition.source_pages,
        )

    return LiveCanonicalFloorSurfaceComposition(
        status=floor_composition.status,
        reason_codes=(
            *base_reasons,
            LIVE_CANONICAL_FLOOR_METRIC_AREA_UNAVAILABLE,
        ),
        floors=tuple(enriched),
        source_pages=floor_composition.source_pages,
    )


__all__ = [
    "LIVE_CANONICAL_FLOOR_METRIC_AREA_CONFLICT",
    "LIVE_CANONICAL_FLOOR_METRIC_AREA_PARTIAL",
    "LIVE_CANONICAL_FLOOR_METRIC_AREA_RESOLVED",
    "LIVE_CANONICAL_FLOOR_METRIC_AREA_UNAVAILABLE",
    "LIVE_CANONICAL_FLOOR_SURFACE_PARTIAL",
    "LIVE_CANONICAL_FLOOR_SURFACE_RESOLVED",
    "LIVE_CANONICAL_FLOOR_SURFACE_SCHEMA_VERSION",
    "LIVE_CANONICAL_FLOOR_SURFACE_UNAVAILABLE",
    "LiveCanonicalFloorSurfaceComposition",
    "LiveCanonicalFloorSurfaceObject",
    "compose_live_canonical_floor_surfaces",
    "enrich_live_canonical_floor_metric_areas",
]
