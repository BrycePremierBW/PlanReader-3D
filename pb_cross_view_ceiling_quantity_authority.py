"""Publish canonical ceiling-lining quantities from proven room area + RCP finish.

This module composes already-proven facts only:
- one source-owned canonical physical room;
- one FIRM documented room-area QuantityEvidence from the live room-area bridge;
- one fail-closed cross-view RCP ceiling-finish binding.

The room-area bridge may have received its documented area from either same-view
or cross-view figured-dimension authority. This module consumes only the final
FIRM quantity and its exact producer-owned room entity. PDF-scaled ceiling
publication remains on the existing scale-aware ceiling pipeline; this path does
not invent or reconstruct scale authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping, Optional, Sequence

from pb_cross_view_ceiling_finish_authority import (
    CrossViewCeilingFinishRecord,
    CrossViewCeilingFinishResult,
)
from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_live_canonical_room_composition import (
    LiveCanonicalRoomComposition,
    LiveCanonicalRoomObject,
)
from pb_live_ceiling_lining_integration import LiveCanonicalCeilingSurfaceObject
from pb_migration_contracts import (
    EntityEvidence,
    EvidenceResolutionStatus,
    QuantityEvidence,
    stable_contract_id,
)
from pb_source_room_area_bridge import SourceRoomAreaBridgeResult


CROSS_VIEW_CEILING_QUANTITY_SCHEMA_VERSION = "1.2.0"
CROSS_VIEW_CEILING_QUANTITY_RESOLVED = "cross_view_ceiling_quantity_resolved"
CROSS_VIEW_CEILING_QUANTITY_PARTIAL = "cross_view_ceiling_quantity_partial"
CROSS_VIEW_CEILING_QUANTITY_UNAVAILABLE = "cross_view_ceiling_quantity_unavailable"
CROSS_VIEW_CEILING_QUANTITY_CONFLICT = "cross_view_ceiling_quantity_conflict"
CROSS_VIEW_CEILING_QUANTITY_LINEAGE_CONFLICT = (
    "cross_view_ceiling_quantity_lineage_conflict"
)
CROSS_VIEW_CEILING_QUANTITY_FIRM = "authenticated_room_area_with_rcp_ceiling_finish"

_RECORD_SEAL = object()


def _clean(value: object) -> str:
    return str(value or "").strip()


def _ceiling_id(room: LiveCanonicalRoomObject) -> str:
    return stable_contract_id(
        "physical_room_ceiling_surface",
        {
            "document_id": room.document_id,
            "physical_room_id": room.physical_room_id,
            "surface_role": "ceiling",
        },
        digest_chars=32,
    )


def _quantity_value(quantity: QuantityEvidence) -> Optional[float]:
    if (
        quantity.abstained or quantity.value is None
        or type(quantity.value) not in (int, float)
    ):
        return None
    try:
        value = float(quantity.value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value


def _source_figured_dimension_ids(metadata: Mapping) -> Optional[tuple[str, ...]]:
    """Require actual source-ID tokens; strings are NOT collections of IDs.

    The upstream documented room area must own two distinct native figured
    receipts. A bare string such as "HV" must never count as two observations.
    Non-string items are not source observation identities.
    """
    raw = metadata.get("figured_dimension_ids")
    if not isinstance(raw, (tuple, list)):
        return None
    if (
        len(raw) != 2
        or any(type(item) is not str or not item or item != item.strip() for item in raw)
        or len(set(raw)) != 2
    ):
        return None
    return tuple(sorted(raw))


def _valid_room_area_quantity(
    room: LiveCanonicalRoomObject,
    *,
    entity: EntityEvidence,
    quantity: QuantityEvidence,
) -> bool:
    if (
        entity.status is not EvidenceResolutionStatus.CORROBORATED
        or quantity.family != "room_area"
        or _clean(quantity.status) != AuthorityStatus.FIRM.value
        or _clean(quantity.unit).lower() not in {"m2", "m²"}
        or quantity.blocking_reasons
        or not quantity.evidence_ids
        or not isinstance(quantity.evidence_ids, (tuple, list))
        or any(type(item) is not str or not item.strip() for item in quantity.evidence_ids)
        or len(set(quantity.evidence_ids)) != len(quantity.evidence_ids)
        or type(quantity.confidence) not in (int, float)
        or not math.isfinite(float(quantity.confidence))
        or not 0.0 <= float(quantity.confidence) <= 1.0
        or _clean(quantity.authority)
        != MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
        or _quantity_value(quantity) is None
        or len(quantity.input_entity_ids) != 1
        or quantity.input_entity_ids[0] != entity.candidate_entity_id
        or room.source_room_face_record_id not in tuple(entity.evidence_ids or ())
    ):
        return False

    entity_meta = entity.metadata if isinstance(entity.metadata, Mapping) else {}
    quantity_meta = (
        quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    )
    if _source_figured_dimension_ids(quantity_meta) is None:
        return False

    # Some documented dimension bridges carry explicit physical-room ownership
    # receipts in addition to the support-sheet snapshot. When present these
    # must agree with the canonical room, not just the page and revision.
    room_snapshot_id = _clean(quantity_meta.get("room_snapshot_id"))
    source_face_id = _clean(quantity_meta.get("source_room_face_record_id"))
    if (
        room_snapshot_id and room_snapshot_id != _clean(room.snapshot_id)
    ) or (
        source_face_id and source_face_id != _clean(room.source_room_face_record_id)
    ):
        return False

    if (
        _clean(entity_meta.get("source_sha256")).lower()
        != room.source_sha256.lower()
        or _clean(entity_meta.get("revision_id")) != room.revision_id
        or _clean(entity_meta.get("page_id")) != _clean(room.page_id)
        or _clean(quantity_meta.get("source_sha256")).lower()
        != room.source_sha256.lower()
        or _clean(quantity_meta.get("revision_id")) != room.revision_id
        or _clean(quantity_meta.get("page_no")) != _clean(room.page_id)
        or not _clean(quantity_meta.get("viewport_id"))
        or not _clean(entity_meta.get("source_room_index_id"))
    ):
        return False
    return True


@dataclass(frozen=True)
class CrossViewCeilingQuantityRecord:
    canonical_ceiling_id: str
    physical_ceiling_surface_id: str
    physical_room_id: str
    canonical_room_id: str
    source_room_face_record_id: str
    room_label: str
    finish_code: str
    semantic_finish: str
    support_page_id: str
    support_viewport_id: str
    upstream_room_area_quantity_id: str
    canonical_ceiling: LiveCanonicalCeilingSurfaceObject
    quantity: QuantityEvidence
    schema_version: str = CROSS_VIEW_CEILING_QUANTITY_SCHEMA_VERSION
    _seal: object = None

    def __post_init__(self) -> None:
        if self._seal is not _RECORD_SEAL:
            raise TypeError("CrossViewCeilingQuantityRecord is producer-owned")


@dataclass(frozen=True)
class CrossViewCeilingQuantityResult:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    records: tuple[CrossViewCeilingQuantityRecord, ...]
    unresolved_physical_room_ids: tuple[str, ...]
    schema_version: str = CROSS_VIEW_CEILING_QUANTITY_SCHEMA_VERSION

    @property
    def quantities(self) -> tuple[QuantityEvidence, ...]:
        return tuple(record.quantity for record in self.records)

    @property
    def canonical_ceilings(self) -> tuple[LiveCanonicalCeilingSurfaceObject, ...]:
        return tuple(record.canonical_ceiling for record in self.records)

    @property
    def records_by_ceiling_id(
        self,
    ) -> Mapping[str, CrossViewCeilingQuantityRecord]:
        return MappingProxyType(
            {record.canonical_ceiling_id: record for record in self.records}
        )


def publish_cross_view_ceiling_quantities(
    *,
    rooms: LiveCanonicalRoomComposition,
    room_area_bridges: Sequence[SourceRoomAreaBridgeResult],
    finishes: CrossViewCeilingFinishResult,
) -> CrossViewCeilingQuantityResult:
    if type(rooms) is not LiveCanonicalRoomComposition:
        raise TypeError("rooms must be LiveCanonicalRoomComposition")
    if type(finishes) is not CrossViewCeilingFinishResult:
        raise TypeError("finishes must be CrossViewCeilingFinishResult")
    if any(type(item) is not SourceRoomAreaBridgeResult for item in room_area_bridges):
        raise TypeError(
            "room_area_bridges must contain SourceRoomAreaBridgeResult"
        )

    rooms_by_physical: dict[str, list[LiveCanonicalRoomObject]] = {}
    for room in rooms.rooms:
        physical_id = _clean(room.physical_room_id)
        if physical_id:
            rooms_by_physical.setdefault(physical_id, []).append(room)

    finishes_by_physical: dict[str, list[CrossViewCeilingFinishRecord]] = {}
    for record in finishes.records:
        physical_id = _clean(record.physical_room_id)
        if physical_id:
            finishes_by_physical.setdefault(physical_id, []).append(record)

    # A single exact source material occurrence cannot be owned by multiple
    # distinct physical rooms. Quarantine *all* owners rather than allowing
    # individually unique per-room rows to publish duplicated ceiling areas.
    occurrence_owners: dict[str, set[str]] = {}
    for finish_record in finishes.records:
        occurrence_id = _clean(finish_record.occurrence_record_id)
        physical_id = _clean(finish_record.physical_room_id)
        if occurrence_id and physical_id:
            occurrence_owners.setdefault(occurrence_id, set()).add(physical_id)
    conflicting_occurrence_ids = {
        occurrence_id
        for occurrence_id, owners in occurrence_owners.items()
        if len(owners) > 1
    }

    bridge_pairs: list[tuple[EntityEvidence, QuantityEvidence]] = []
    for bridge in room_area_bridges:
        if bridge.status is not EvidenceResolutionStatus.CORROBORATED:
            continue
        # The same source-room identity cannot resolve to competing entity
        # receipts. Never allow a dict comprehension to select the last one.
        entities: dict[str, EntityEvidence] = {}
        contradictory_entity_ids: set[str] = set()
        for entity in bridge.entities:
            entity_id = _clean(entity.candidate_entity_id)
            if not entity_id or entity_id in contradictory_entity_ids:
                continue
            prior = entities.get(entity_id)
            if prior is not None and prior != entity:
                entities.pop(entity_id, None)
                contradictory_entity_ids.add(entity_id)
                continue
            entities[entity_id] = entity
        for quantity in bridge.quantities:
            if len(quantity.input_entity_ids) != 1:
                continue
            entity = entities.get(_clean(quantity.input_entity_ids[0]))
            if entity is not None:
                bridge_pairs.append((entity, quantity))

    records: list[CrossViewCeilingQuantityRecord] = []
    unresolved: set[str] = set()
    conflict = False

    all_physical_ids = set(rooms_by_physical) | set(finishes_by_physical)
    for physical_id in sorted(all_physical_ids):
        room_rows = rooms_by_physical.get(physical_id, ())
        finish_rows = finishes_by_physical.get(physical_id, ())
        if len(room_rows) != 1 or len(finish_rows) != 1:
            unresolved.add(physical_id)
            if len(room_rows) > 1 or len(finish_rows) > 1:
                conflict = True
            continue

        room = room_rows[0]
        finish = finish_rows[0]
        if (
            not _clean(finish.occurrence_record_id)
            or not _clean(finish.definition_record_id)
            or _clean(finish.occurrence_record_id) in conflicting_occurrence_ids
        ):
            unresolved.add(physical_id)
            if _clean(finish.occurrence_record_id) in conflicting_occurrence_ids:
                conflict = True
            continue
        area_candidates = [
            (entity, quantity)
            for entity, quantity in bridge_pairs
            if _valid_room_area_quantity(
                room,
                entity=entity,
                quantity=quantity,
            )
        ]
        deduped: dict[str, tuple[EntityEvidence, QuantityEvidence]] = {}
        contradictory_ids: set[str] = set()
        for entity, quantity in area_candidates:
            qid = _clean(quantity.quantity_id)
            if not qid or qid in contradictory_ids:
                continue
            pair = (entity, quantity)
            earlier = deduped.get(qid)
            if earlier is not None and earlier != pair:
                # Quantity IDs are an identity contract, not a last-writer-wins
                # map. A replay with changed area or provenance must revoke
                # the room's ceiling measurement instead of selecting either.
                contradictory_ids.add(qid)
                deduped.pop(qid, None)
                continue
            deduped[qid] = pair
        area_candidates = list(deduped.values())

        if contradictory_ids or len(area_candidates) != 1:
            unresolved.add(physical_id)
            if contradictory_ids or len(area_candidates) > 1:
                conflict = True
            continue

        entity, area_quantity = area_candidates[0]
        area_value = _quantity_value(area_quantity)
        if area_value is None:
            unresolved.add(physical_id)
            continue
        area_meta = (
            area_quantity.metadata
            if isinstance(area_quantity.metadata, Mapping)
            else {}
        )
        entity_meta = entity.metadata if isinstance(entity.metadata, Mapping) else {}
        figured_dimension_ids = _source_figured_dimension_ids(area_meta)
        source_room_index_id = _clean(entity_meta.get("source_room_index_id"))
        area_viewport_id = _clean(area_meta.get("viewport_id"))
        try:
            source_page = int(area_meta.get("page_no"))
        except (TypeError, ValueError, OverflowError):
            unresolved.add(physical_id)
            continue

        if (
            not room.geometry_complete
            or len(room.polygon_pdf_pts) < 3
            or figured_dimension_ids is None
            or not source_room_index_id
            or not area_viewport_id
            or not _clean(room.canonical_room_id)
            or not _clean(room.source_room_face_record_id)
            or finish.source_room_face_record_id != room.source_room_face_record_id
            or finish.canonical_room_id != room.canonical_room_id
            or _clean(finish.room_label).casefold()
            != _clean(room.room_label).casefold()
            or finish.definition_evidence_ids == ()
            or not _clean(finish.occurrence_evidence_id)
            or not _clean(finish.support_snapshot_id)
        ):
            unresolved.add(physical_id)
            continue

        canonical_ceiling_id = _ceiling_id(room)
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *(
                        _clean(item)
                        for item in room.evidence_ids
                        if _clean(item)
                    ),
                    *(
                        _clean(item)
                        for item in room.room_label_evidence_ids
                        if _clean(item)
                    ),
                    *(
                        _clean(item)
                        for item in area_quantity.evidence_ids
                        if _clean(item)
                    ),
                    finish.occurrence_evidence_id,
                    *(
                        _clean(item)
                        for item in finish.definition_evidence_ids
                        if _clean(item)
                    ),
                )
            )
        )
        quantity_payload = {
            "family": "ceiling_lining",
            "canonical_ceiling_id": canonical_ceiling_id,
            "upstream_room_area_quantity_id": area_quantity.quantity_id,
            "finish_occurrence_record_id": finish.occurrence_record_id,
            "finish_definition_record_id": finish.definition_record_id,
            "value_m2": round(area_value, 6),
        }
        quantity_id = stable_contract_id(
            "qty_ceiling_lining_area",
            quantity_payload,
            digest_chars=32,
        )
        quantity = QuantityEvidence(
            quantity_id=quantity_id,
            family="ceiling_lining",
            semantic_key=(
                f"ceiling_lining:{canonical_ceiling_id}:"
                f"{finish.finish_code}:{finish.semantic_finish}"
            ),
            value=round(area_value, 6),
            unit="m2",
            input_entity_ids=(canonical_ceiling_id,),
            formula="reuse_firm_documented_room_area_with_authenticated_rcp_finish",
            formula_version=CROSS_VIEW_CEILING_QUANTITY_SCHEMA_VERSION,
            evidence_ids=evidence_ids,
            authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            status=AuthorityStatus.FIRM.value,
            confidence=min(float(area_quantity.confidence), 1.0),
            abstained=False,
            reason_codes=(CROSS_VIEW_CEILING_QUANTITY_FIRM,),
            metadata={
                "document_id": room.document_id,
                "snapshot_id": room.snapshot_id,
                "source_sha256": room.source_sha256,
                "revision_id": room.revision_id,
                "page_no": source_page,
                "viewport_id": area_viewport_id,
                "support_page_id": finish.support_page_id,
                "support_viewport_id": finish.support_viewport_id,
                "support_snapshot_id": finish.support_snapshot_id,
                "support_source_partition_id": finish.support_source_partition_id,
                "support_block_no": finish.support_block_no,
                "room_label": room.room_label,
                "physical_room_id": room.physical_room_id,
                "canonical_room_id": room.canonical_room_id,
                "canonical_ceiling_id": canonical_ceiling_id,
                "physical_ceiling_surface_id": canonical_ceiling_id,
                "source_room_face_record_id": room.source_room_face_record_id,
                "source_room_index_id": source_room_index_id,
                "upstream_room_area_entity_id": entity.candidate_entity_id,
                "upstream_room_area_quantity_id": area_quantity.quantity_id,
                "room_area_quantity_id": area_quantity.quantity_id,
                "measurement_authority": MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                "figured_dimension_ids": list(figured_dimension_ids),
                "finish_code": finish.finish_code,
                "semantic_finish": finish.semantic_finish,
                "finish_definition_record_id": finish.definition_record_id,
                "finish_occurrence_record_id": finish.occurrence_record_id,
                "finish_occurrence_evidence_id": finish.occurrence_evidence_id,
                "finish_occurrence_bbox_pdf_pts": list(
                    finish.occurrence_bbox_pdf_pts
                ),
                "commercial_projection_allowed": True,
                "section": "Internal",
                "element": "Ceiling lining area",
                "location": room.room_label,
                "substrate": "Other",
                "finish_system": finish.semantic_finish,
                "inclusion_status": "INCLUSION",
                "row_role": "ceiling_area",
            },
        )
        canonical_ceiling = LiveCanonicalCeilingSurfaceObject(
            canonical_ceiling_id=canonical_ceiling_id,
            document_id=room.document_id,
            snapshot_id=room.snapshot_id,
            room_entity_id=room.canonical_room_id,
            source_page=source_page,
            viewport_id=area_viewport_id,
            source_sha256=room.source_sha256,
            revision_id=room.revision_id,
            polygon_pdf_pts=tuple(
                (float(point[0]), float(point[1]))
                for point in room.polygon_pdf_pts
            ),
            area_m2=round(area_value, 6),
            finish_descriptor=finish.semantic_finish,
            room_area_quantity_id=area_quantity.quantity_id,
            ceiling_quantity_id=quantity_id,
            source_room_index_id=source_room_index_id,
            evidence_ids=evidence_ids,
            physical_scale_record_id="",
            measurement_authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            figured_dimension_ids=figured_dimension_ids,
            geometry_complete=True,
            metric_area_complete=True,
            metric_geometry_complete=False,
        )
        records.append(
            CrossViewCeilingQuantityRecord(
                canonical_ceiling_id=canonical_ceiling_id,
                physical_ceiling_surface_id=canonical_ceiling_id,
                physical_room_id=physical_id,
                canonical_room_id=room.canonical_room_id,
                source_room_face_record_id=room.source_room_face_record_id,
                room_label=_clean(room.room_label),
                finish_code=finish.finish_code,
                semantic_finish=finish.semantic_finish,
                support_page_id=finish.support_page_id,
                support_viewport_id=finish.support_viewport_id,
                upstream_room_area_quantity_id=area_quantity.quantity_id,
                canonical_ceiling=canonical_ceiling,
                quantity=quantity,
                _seal=_RECORD_SEAL,
            )
        )

    # This producer publishes FIRM RCP quantities directly, before the
    # downstream canonical area publisher's duplicate-area guard. A single
    # source-owned whole-room area receipt may never be independently
    # republished for two physical ceiling surfaces. Quarantine *both*
    # physical owners, not whichever record happens to be visited second.
    source_area_owners: dict[str, set[str]] = {}
    canonical_room_owners: dict[str, set[str]] = {}
    for record in records:
        source_area_owners.setdefault(
            record.upstream_room_area_quantity_id, set()
        ).add(record.physical_room_id)
        # Different source receipt IDs do not justify publishing the same
        # canonical room's full ceiling through two physical room identities.
        canonical_room_owners.setdefault(
            record.canonical_room_id, set()
        ).add(record.physical_room_id)
    contested_source_ids = {
        source_id for source_id, owners in source_area_owners.items()
        if len(owners) > 1
    }
    contested_canonical_room_ids = {
        canonical_id for canonical_id, owners in canonical_room_owners.items()
        if len(owners) > 1
    }
    if contested_source_ids or contested_canonical_room_ids:
        rejected = [
            record for record in records
            if (
                record.upstream_room_area_quantity_id in contested_source_ids
                or record.canonical_room_id in contested_canonical_room_ids
            )
        ]
        unresolved.update(record.physical_room_id for record in rejected)
        records = [
            record for record in records
            if (
                record.upstream_room_area_quantity_id not in contested_source_ids
                and record.canonical_room_id not in contested_canonical_room_ids
            )
        ]
        conflict = True

    records.sort(key=lambda record: record.canonical_ceiling_id)
    unresolved_ids = tuple(sorted(unresolved))
    if records and not unresolved_ids and not conflict:
        status = EvidenceResolutionStatus.CORROBORATED
        reasons = (CROSS_VIEW_CEILING_QUANTITY_RESOLVED,)
    elif records:
        status = EvidenceResolutionStatus.CANDIDATE
        reasons = (CROSS_VIEW_CEILING_QUANTITY_PARTIAL,)
    elif conflict:
        status = EvidenceResolutionStatus.CONFLICT
        reasons = (CROSS_VIEW_CEILING_QUANTITY_CONFLICT,)
    else:
        status = EvidenceResolutionStatus.ABSTAINED
        reasons = (CROSS_VIEW_CEILING_QUANTITY_UNAVAILABLE,)

    return CrossViewCeilingQuantityResult(
        status=status,
        reason_codes=reasons,
        records=tuple(records),
        unresolved_physical_room_ids=unresolved_ids,
    )


__all__ = [
    "CROSS_VIEW_CEILING_QUANTITY_CONFLICT",
    "CROSS_VIEW_CEILING_QUANTITY_FIRM",
    "CROSS_VIEW_CEILING_QUANTITY_LINEAGE_CONFLICT",
    "CROSS_VIEW_CEILING_QUANTITY_PARTIAL",
    "CROSS_VIEW_CEILING_QUANTITY_RESOLVED",
    "CROSS_VIEW_CEILING_QUANTITY_SCHEMA_VERSION",
    "CROSS_VIEW_CEILING_QUANTITY_UNAVAILABLE",
    "CrossViewCeilingQuantityRecord",
    "CrossViewCeilingQuantityResult",
    "publish_cross_view_ceiling_quantities",
]
