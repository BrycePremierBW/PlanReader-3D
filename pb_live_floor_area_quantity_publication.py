"""Canonical-floor QuantityEvidence from already-FIRM live room-area authority.

This adapter does not measure floor area. It reissues a room-area quantity only
when the live claim already proves that exact quantity maps one-to-one to one
canonical floor and the floor retains the same value, authority, source lineage
and evidence.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_live_canonical_floor_surface import LiveCanonicalFloorSurfaceObject
from pb_live_canonical_room_composition import LiveCanonicalRoomObject
from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim
from pb_migration_contracts import QuantityEvidence, stable_contract_id


LIVE_FLOOR_AREA_QUANTITY_SCHEMA_VERSION = "1.0.0"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _canonical_rooms_by_id(
    claim: LivePhysicalNetWallClaim,
) -> dict[str, LiveCanonicalRoomObject]:
    rooms: dict[str, LiveCanonicalRoomObject] = {}
    for room in claim.canonical_rooms:
        if type(room) is not LiveCanonicalRoomObject:
            raise TypeError("canonical_rooms must contain LiveCanonicalRoomObject")
        room_id = _clean(room.canonical_room_id)
        if not room_id:
            continue
        if room_id in rooms:
            raise ValueError(f"duplicate canonical room identity: {room_id}")
        rooms[room_id] = room
    return rooms


def publish_live_floor_area_quantities(
    claim: LivePhysicalNetWallClaim,
) -> tuple[QuantityEvidence, ...]:
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    source_quantities: dict[str, QuantityEvidence] = {}
    conflicting_quantity_ids: set[str] = set()
    for quantity in claim.room_area_quantity_evidence:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("room_area_quantity_evidence must contain QuantityEvidence")
        if (
            quantity.family != "room_area"
            or quantity.abstained
            or quantity.value is None
            or _clean(quantity.status).lower() != AuthorityStatus.FIRM.value
            or _clean(quantity.unit).lower() not in {"m2", "m²"}
            or quantity.blocking_reasons
            or _clean(quantity.authority) not in {
                MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                MeasurementAuthorityType.PDF_SCALED.value,
            }
        ):
            continue
        qid = _clean(quantity.quantity_id)
        if not qid:
            continue
        if qid in conflicting_quantity_ids:
            continue
        previous = source_quantities.get(qid)
        if previous is not None:
            if previous != quantity:
                # The same identity cannot denote two independently different
                # FIRM measurements or provenance records. Quarantine it; a
                # later replay of either claim must not restore publication.
                source_quantities.pop(qid, None)
                conflicting_quantity_ids.add(qid)
            # Exact producer-owned replays are idempotent.
            continue
        source_quantities[qid] = quantity

    floors_by_quantity: dict[str, list[LiveCanonicalFloorSurfaceObject]] = {}
    # Identity uniqueness belongs to the entire producer-owned floor universe,
    # not just the subset already carrying FIRM area source quantity IDs. An
    # unresolved/ABSTAIN replay of the same floor can otherwise be hidden by
    # filtering and allow one conflicting floor owner to publish commercially.
    canonical_ids: Counter[str] = Counter()
    physical_ids: Counter[str] = Counter()
    # Whole-room floor-area quantities cannot be published twice merely by
    # minting two canonical floor IDs or two upstream quantity IDs for one
    # canonical room/source face. Count *every* original floor object, even
    # unmeasured/ABSTAIN rows, before selecting a FIRM published quantity.
    canonical_room_ids: Counter[str] = Counter()
    source_face_ids: Counter[str] = Counter()
    for floor in claim.canonical_floors:
        if type(floor) is not LiveCanonicalFloorSurfaceObject:
            raise TypeError("canonical_floors must contain LiveCanonicalFloorSurfaceObject")
        canonical_id = _clean(floor.canonical_floor_id)
        physical_id = _clean(floor.physical_floor_surface_id)
        if canonical_id:
            canonical_ids[canonical_id] += 1
        if physical_id:
            physical_ids[physical_id] += 1
        room_id = _clean(floor.room_entity_id)
        face_id = _clean(floor.source_room_face_record_id)
        if room_id:
            canonical_room_ids[room_id] += 1
        if face_id:
            source_face_ids[face_id] += 1
        qid = _clean(floor.metric_area_quantity_id)
        if qid:
            floors_by_quantity.setdefault(qid, []).append(floor)

    # A canonical surface cannot carry competing room-area source identities,
    # even when each individual source ID appears on exactly one floor row.
    # Quarantine the complete physical floor rather than selecting a winner.
    physical_floor_claim_ids: dict[str, set[str]] = {}
    for source_id, associated_floors in floors_by_quantity.items():
        for candidate_floor in associated_floors:
            physical_id = _clean(candidate_floor.physical_floor_surface_id)
            if physical_id:
                physical_floor_claim_ids.setdefault(physical_id, set()).add(source_id)

    out: list[QuantityEvidence] = []
    for source_id, quantity in sorted(source_quantities.items()):
        floors = floors_by_quantity.get(source_id, ())
        if len(floors) != 1:
            continue
        floor = floors[0]
        if not floor.physical_floor_surface_identity_resolved:
            continue
        if not floor.physical_floor_surface_id or not floor.canonical_floor_id:
            continue
        if (
            canonical_ids[_clean(floor.canonical_floor_id)] != 1
            or physical_ids[_clean(floor.physical_floor_surface_id)] != 1
            or not _clean(floor.room_entity_id)
            or not _clean(floor.source_room_face_record_id)
            or canonical_room_ids[_clean(floor.room_entity_id)] != 1
            or source_face_ids[_clean(floor.source_room_face_record_id)] != 1
        ):
            continue
        if len(physical_floor_claim_ids.get(_clean(floor.physical_floor_surface_id), ())) != 1:
            continue
        try:
            qvalue = float(quantity.value)
            fvalue = float(floor.metric_area_m2)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            not math.isfinite(qvalue)
            or qvalue <= 0.0
            or not math.isfinite(fvalue)
            or abs(qvalue - fvalue) > 1e-9
        ):
            continue
        if _clean(floor.metric_area_authority) != _clean(quantity.authority):
            continue

        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        # Reject malformed source evidence instead of allowing an empty or
        # repeated receipt to pass set-based lineage membership.  A room-area
        # quantity without a positive source-owning entity is not a floor-area
        # measurement, even when its numeric area happens to match.
        if (
            not isinstance(quantity.input_entity_ids, (tuple, list))
            or not quantity.input_entity_ids
            or any(type(value) is not str or not value.strip()
                   for value in quantity.input_entity_ids)
            or len(set(quantity.input_entity_ids)) != len(quantity.input_entity_ids)
            or not isinstance(quantity.evidence_ids, (tuple, list))
            or not quantity.evidence_ids
            or any(type(value) is not str or not value.strip()
                   for value in quantity.evidence_ids)
            or len(set(quantity.evidence_ids)) != len(quantity.evidence_ids)
            or not isinstance(floor.evidence_ids, (tuple, list))
            or any(type(value) is not str or not value.strip()
                   for value in floor.evidence_ids)
            or len(set(floor.evidence_ids)) != len(floor.evidence_ids)
        ):
            continue
        # Some upstream source-area producers retain the original document
        # identity in metadata. When present it cannot be replayed onto a
        # different canonical-floor document.
        source_document_id = metadata.get("document_id")
        if source_document_id is not None and _clean(source_document_id) != floor.document_id:
            continue
        if _clean(metadata.get("source_sha256")).lower() != floor.source_sha256.lower():
            continue
        if _clean(metadata.get("revision_id")) != floor.revision_id:
            continue
        # Figured same/cross-view room-area claims carry the identity of the
        # source ROOM snapshot, which must agree with the canonical floor's
        # source room. Dimension-support snapshots can legitimately differ.
        # Do not use a measurement from another room-face snapshot even if
        # its revision, quantity value and viewport happen to match.
        room_snapshot_id = _clean(metadata.get("room_snapshot_id"))
        if room_snapshot_id and room_snapshot_id != floor.snapshot_id:
            continue
        source_room_face_id = _clean(
            metadata.get("source_room_face_record_id")
        )
        if (
            source_room_face_id
            and source_room_face_id != floor.source_room_face_record_id
        ):
            continue
        if _clean(metadata.get("page_no")) != str(floor.page_id):
            continue
        q_viewport = _clean(metadata.get("viewport_id"))
        if not q_viewport:
            continue
        if floor.viewport_id and _clean(floor.viewport_id) != q_viewport:
            continue
        # Empty receipts must not vacuously pass the source lineage subset
        # test and become commercially publishable metric quantities.
        if not quantity.evidence_ids or not floor.evidence_ids:
            continue
        if not set(quantity.evidence_ids).issubset(set(floor.evidence_ids)):
            continue

        payload = {
            "schema_version": LIVE_FLOOR_AREA_QUANTITY_SCHEMA_VERSION,
            "upstream_room_area_quantity_id": source_id,
            "canonical_floor_id": floor.canonical_floor_id,
            "physical_floor_surface_id": floor.physical_floor_surface_id,
            "value_m2": qvalue,
            "authority": quantity.authority,
            "source_sha256": floor.source_sha256,
            "revision_id": floor.revision_id,
        }
        out.append(
            QuantityEvidence(
                quantity_id=stable_contract_id("floor_area_quantity", payload),
                family="floor_area",
                semantic_key=f"floor_area:{floor.physical_floor_surface_id}",
                value=qvalue,
                unit="m2",
                input_entity_ids=(floor.physical_floor_surface_id,),
                formula="reuse exact firm room-area authority for its one-to-one canonical floor",
                formula_version=LIVE_FLOOR_AREA_QUANTITY_SCHEMA_VERSION,
                evidence_ids=tuple(quantity.evidence_ids),
                authority=quantity.authority,
                status=AuthorityStatus.FIRM.value,
                confidence=float(quantity.confidence),
                abstained=False,
                blocking_reasons=(),
                reason_codes=tuple(quantity.reason_codes),
                metadata={
                    **dict(metadata),
                    "upstream_room_area_quantity_id": source_id,
                    "canonical_floor_id": floor.canonical_floor_id,
                    "physical_floor_surface_id": floor.physical_floor_surface_id,
                    "room_entity_id": floor.room_entity_id,
                    "source_room_face_record_id": floor.source_room_face_record_id,
                    "commercial_projection_allowed": True,
                    "row_role": "floor_area",
                },
            )
        )
    return tuple(sorted(out, key=lambda item: item.quantity_id))


def publish_live_canonical_room_area_quantities(
    claim: LivePhysicalNetWallClaim,
) -> tuple[QuantityEvidence, ...]:
    """Reissue already-FIRM room area onto exact canonical room identity."""
    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")

    rooms = _canonical_rooms_by_id(claim)
    # Full canonical universe identity must be checked *before* filtering to
    # the conveniently measured room. Competing physical/source-face owners
    # cannot be resolved by first/last-writer-wins selection.
    physical_owner_counts: dict[str, int] = {}
    source_face_owner_counts: dict[str, int] = {}
    for candidate in claim.canonical_rooms:
        physical_id = _clean(candidate.physical_room_id)
        source_face_id = _clean(candidate.source_room_face_record_id)
        if physical_id:
            physical_owner_counts[physical_id] = (
                physical_owner_counts.get(physical_id, 0) + 1
            )
        if source_face_id:
            source_face_owner_counts[source_face_id] = (
                source_face_owner_counts.get(source_face_id, 0) + 1
            )
    floor_quantities = publish_live_floor_area_quantities(claim)
    # The source ID is allowed to appear in ABSTAIN/provisional replays,
    # but an untrusted later replay must not override the exact FIRM source
    # that already passed the canonical floor quantity gate. The former
    # last-write-wins dictionary could silently reissue a provisional source
    # evidence set as FIRM canonical room output depending on input order.
    source_by_id: dict[str, QuantityEvidence] = {}
    conflicting_firm_ids: set[str] = set()
    for source in claim.room_area_quantity_evidence:
        if not isinstance(source, QuantityEvidence):
            raise TypeError("room_area_quantity_evidence must contain QuantityEvidence")
        if (
            source.family != "room_area"
            or source.abstained
            or source.value is None
            or _clean(source.status).lower() != AuthorityStatus.FIRM.value
            or _clean(source.unit).lower() not in {"m2", "m²"}
            or source.blocking_reasons
            or _clean(source.authority) not in {
                MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                MeasurementAuthorityType.PDF_SCALED.value,
            }
        ):
            continue
        qid = _clean(source.quantity_id)
        if not qid or qid in conflicting_firm_ids:
            continue
        previous = source_by_id.get(qid)
        if previous is not None and previous != source:
            source_by_id.pop(qid, None)
            conflicting_firm_ids.add(qid)
        elif previous is None:
            source_by_id[qid] = source

    out: list[QuantityEvidence] = []
    for floor_quantity in floor_quantities:
        metadata = (
            floor_quantity.metadata
            if isinstance(floor_quantity.metadata, Mapping)
            else {}
        )
        room_id = _clean(metadata.get("room_entity_id"))
        source_id = _clean(metadata.get("upstream_room_area_quantity_id"))
        room = rooms.get(room_id)
        source = source_by_id.get(source_id)
        if room is None or source is None:
            continue
        # Reuse the *same* valid upstream room-area evidence that was promoted
        # to the canonical floor. Never create a different FIRM claim by
        # selecting another source row with the same nominal quantity ID.
        if (
            tuple(source.evidence_ids) != tuple(floor_quantity.evidence_ids)
            or _clean(source.authority) != _clean(floor_quantity.authority)
        ):
            continue
        try:
            same_area = (
                math.isfinite(float(source.value))
                and abs(float(source.value) - float(floor_quantity.value)) <= 1e-9
            )
        except (TypeError, ValueError, OverflowError):
            same_area = False
        if not same_area:
            continue
        if not room.physical_room_id or not room.canonical_room_id:
            continue
        if (
            physical_owner_counts.get(_clean(room.physical_room_id), 0) != 1
            or source_face_owner_counts.get(_clean(room.source_room_face_record_id), 0) != 1
        ):
            continue
        if _clean(room.source_room_face_record_id) != _clean(
            metadata.get("source_room_face_record_id")
        ):
            continue
        if room.source_sha256.lower() != floor_quantity.metadata.get(
            "source_sha256", ""
        ).lower():
            continue
        if room.revision_id != _clean(
            floor_quantity.metadata.get("revision_id")
        ):
            continue
        # Room source identity is independent of a cross-view dimension
        # snapshot. An explicitly declared physical room snapshot must not
        # reissue its area onto another canonical room snapshot.
        source_room_snapshot = _clean(metadata.get("room_snapshot_id"))
        if source_room_snapshot and source_room_snapshot != room.snapshot_id:
            continue
        source_viewport = _clean(metadata.get("viewport_id"))
        if room.viewport_id and source_viewport and _clean(room.viewport_id) != source_viewport:
            continue
        if str(room.page_id) != _clean(
            floor_quantity.metadata.get("page_no")
        ):
            continue
        # Metric-area evidence is deliberately attached to the canonical floor
        # during enrichment. The canonical room is linked through the exact
        # source-room-face identity above; requiring the room object itself to
        # duplicate cross-view dimension evidence would create a false dropout.
        payload = {
            "schema_version": LIVE_FLOOR_AREA_QUANTITY_SCHEMA_VERSION,
            "upstream_room_area_quantity_id": source_id,
            "canonical_room_id": room.canonical_room_id,
            "physical_room_id": room.physical_room_id,
            "value_m2": float(floor_quantity.value),
            "authority": floor_quantity.authority,
            "source_sha256": room.source_sha256,
            "revision_id": room.revision_id,
        }
        out.append(
            QuantityEvidence(
                quantity_id=stable_contract_id(
                    "canonical_room_area_quantity",
                    payload,
                ),
                family="room_area",
                semantic_key=f"room_area:{room.physical_room_id}",
                value=float(floor_quantity.value),
                unit="m2",
                input_entity_ids=(room.physical_room_id,),
                formula=(
                    "reuse exact firm room-area authority for its one-to-one "
                    "canonical room"
                ),
                formula_version=LIVE_FLOOR_AREA_QUANTITY_SCHEMA_VERSION,
                evidence_ids=tuple(source.evidence_ids),
                authority=source.authority,
                status=AuthorityStatus.FIRM.value,
                confidence=float(source.confidence),
                abstained=False,
                blocking_reasons=(),
                reason_codes=tuple(source.reason_codes),
                metadata={
                    **(
                        dict(source.metadata)
                        if isinstance(source.metadata, Mapping)
                        else {}
                    ),
                    "upstream_room_area_quantity_id": source_id,
                    "canonical_room_id": room.canonical_room_id,
                    "physical_room_id": room.physical_room_id,
                    "source_room_face_record_id": room.source_room_face_record_id,
                    "commercial_projection_allowed": True,
                    "row_role": "floor_area",
                },
            )
        )
    return tuple(sorted(out, key=lambda item: item.quantity_id))


__all__ = [
    "LIVE_FLOOR_AREA_QUANTITY_SCHEMA_VERSION",
    "publish_live_canonical_room_area_quantities",
    "publish_live_floor_area_quantities",
]
