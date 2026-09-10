"""Deterministic room/floor-area QuantityEvidence from W5-W10 room topology.

This development-only measurement layer consumes existing ``RoomCandidate``
geometry, M1 evidence contracts, and the shared trusted scale-binding seam from
``pb_measurement_input_authority``. It does not read benchmark gold, create a
second scale authority, or enable commercial quantity authority.

A numeric room area is emitted only from either:
- owned CORROBORATED explicit area EvidenceAtom in square metres; or
- an owned CORROBORATED room polygon with a current FIRM scale bound to the
  exact page/viewport.

Prefilled ``RoomCandidate.floor_area_m2`` and ``explicit_area_label_m2`` fields
are deliberately not treated as authority by themselves.
"""
from __future__ import annotations

import hashlib
import math
from typing import Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_measurement_input_authority import validate_scale_binding
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    ViewportResolutionStatus,
    canonical_contract_json,
    stable_contract_id,
)
from pb_migration_provider_envelope import ProviderContext
from pb_wall_room_topology_contracts import RoomCandidate

ROOM_AREA_FAMILY = "room_area"
ROOM_AREA_FORMULA_VERSION = "1.1.0"


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += float(x1) * float(y2) - float(x2) * float(y1)
    return abs(total) / 2.0


def _canonical_ring(points: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    """Cyclic/reversal-invariant signature used only for duplicate protection."""
    pts = tuple((round(float(x), 8), round(float(y), 8)) for x, y in points)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return ()
    rotations = [pts[i:] + pts[:i] for i in range(len(pts))]
    rev = tuple(reversed(pts))
    rotations.extend(rev[i:] + rev[:i] for i in range(len(rev)))
    return min(rotations)


def _evidence_fingerprint(evidence: EvidenceAtom) -> str:
    return hashlib.sha256(
        canonical_contract_json(evidence.to_dict()).encode("utf-8")
    ).hexdigest()


def _abstention(
    *,
    room: RoomCandidate,
    entity: EntityEvidence,
    context: ProviderContext,
    blockers: tuple[str, ...],
    authority: str = "unresolved",
    metadata: Optional[dict[str, object]] = None,
) -> QuantityEvidence:
    payload = {
        "family": ROOM_AREA_FAMILY,
        "room_id": room.room_ref,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "viewport_id": room.viewport_id,
        "blockers": list(blockers),
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=ROOM_AREA_FAMILY,
        semantic_key=f"room_area:{room.room_ref}",
        value=None,
        unit="m2",
        input_entity_ids=(room.room_ref,),
        formula="owned_explicit_area OR polygon_area / trusted_px_per_m^2",
        formula_version=ROOM_AREA_FORMULA_VERSION,
        evidence_ids=tuple(entity.evidence_ids),
        authority=authority,
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=blockers,
        reason_codes=blockers,
        metadata=metadata or {},
    )


def _validate_common(
    *,
    room: RoomCandidate,
    entity: EntityEvidence,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not context.revision_id or not context.current_revision_id:
        blockers.append("revision_unbound")
    elif context.revision_id != context.current_revision_id:
        blockers.append("stale_revision")
    if room.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("room_topology_not_corroborated")
    if entity.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("entity_unresolved")
    if room.room_ref != entity.candidate_entity_id:
        blockers.append("room_entity_identity_mismatch")
    if room.document_id != context.document_id or document.document_id != context.document_id:
        blockers.append("document_id_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append("source_sha256_mismatch")
    if viewport.document_id != context.document_id:
        blockers.append("viewport_document_mismatch")
    if document.page_ids and viewport.page_id not in document.page_ids:
        blockers.append("viewport_page_not_owned_by_document")
    if room.viewport_id != viewport.viewport_id:
        blockers.append("room_viewport_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append("viewport_not_owned")
    if viewport.status not in (
        ViewportResolutionStatus.RESOLVED,
        ViewportResolutionStatus.DERIVED,
    ):
        blockers.append("viewport_unresolved")
    if page_no not in context.trusted_page_numbers():
        blockers.append("page_not_owned")
    mapped_page = context.page_for_viewport(viewport.viewport_id)
    if mapped_page is not None and int(mapped_page) != int(page_no):
        blockers.append("viewport_page_mismatch")
    if room.source_page and int(room.source_page) != int(page_no):
        blockers.append("room_source_page_mismatch")
    if not set(entity.evidence_ids).issubset(set(document.evidence_ids)):
        blockers.append("entity_evidence_not_owned_by_document")
    if room.evidence and not set(room.evidence).issubset(set(document.evidence_ids)):
        blockers.append("room_evidence_not_owned_by_document")
    if room.area_conflict:
        blockers.append("room_area_conflict")
    return tuple(blockers)


def _validate_explicit_area(
    evidence: EvidenceAtom,
    *,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if evidence.evidence_id not in document.evidence_ids:
        blockers.append("explicit_area_evidence_not_owned_by_document")
    if evidence.evidence_id not in entity.evidence_ids:
        blockers.append("explicit_area_evidence_not_owned_by_entity")
    if evidence.document_id != document.document_id:
        blockers.append("explicit_area_document_mismatch")
    if evidence.page_id != viewport.page_id:
        blockers.append("explicit_area_page_mismatch")
    if evidence.viewport_id not in (None, viewport.viewport_id):
        blockers.append("explicit_area_viewport_mismatch")
    if evidence.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("explicit_area_not_corroborated")
    if evidence.normalized_value is None:
        blockers.append("explicit_area_missing_normalized_value")
    else:
        try:
            value = float(evidence.normalized_value)
        except (TypeError, ValueError):
            blockers.append("explicit_area_invalid")
        else:
            if not math.isfinite(value) or value <= 0.0:
                blockers.append("explicit_area_invalid")
    if str(evidence.unit or "").strip().lower() not in {"m2", "m²"}:
        blockers.append("explicit_area_unit_not_m2")
    return tuple(blockers)


def build_room_area_quantity(
    *,
    room: RoomCandidate,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
    page_no: int,
    scale_calibration: Optional[ScaleCalibration] = None,
    explicit_area_evidence: Optional[EvidenceAtom] = None,
    max_delta_ratio: float = 0.05,
) -> QuantityEvidence:
    """Build one room area or an explicit fail-closed abstention."""
    blockers = _validate_common(
        room=room,
        entity=entity,
        context=context,
        document=document,
        viewport=viewport,
        page_no=page_no,
    )
    if blockers:
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=blockers,
        )

    explicit_value: Optional[float] = None
    explicit_fp: Optional[str] = None
    if explicit_area_evidence is not None:
        explicit_blockers = _validate_explicit_area(
            explicit_area_evidence,
            document=document,
            viewport=viewport,
            entity=entity,
        )
        if explicit_blockers:
            return _abstention(
                room=room,
                entity=entity,
                context=context,
                blockers=explicit_blockers,
                authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            )
        explicit_value = float(explicit_area_evidence.normalized_value)
        explicit_fp = _evidence_fingerprint(explicit_area_evidence)

    polygon_area_page = _polygon_area(room.polygon_pdf_pts)
    polygon_area_m2: Optional[float] = None
    scale_fp: Optional[str] = None
    scale_blockers: tuple[str, ...] = ()
    if scale_calibration is not None:
        scale_blockers, fresh, candidate_fp = validate_scale_binding(
            context=context,
            viewport=viewport,
            page_no=page_no,
            calibration=scale_calibration,
        )
        scale_fp = candidate_fp
        if not scale_blockers:
            if polygon_area_page <= 0.0:
                if explicit_value is None:
                    return _abstention(
                        room=room,
                        entity=entity,
                        context=context,
                        blockers=("room_polygon_area_invalid",),
                        authority=MeasurementAuthorityType.PDF_SCALED.value,
                        metadata={"scale_fingerprint": scale_fp},
                    )
            else:
                polygon_area_m2 = polygon_area_page / (fresh.px_per_m ** 2)
        elif explicit_value is None:
            return _abstention(
                room=room,
                entity=entity,
                context=context,
                blockers=scale_blockers,
                authority=MeasurementAuthorityType.PDF_SCALED.value,
                metadata={"scale_fingerprint": scale_fp},
            )

    if explicit_value is not None:
        if polygon_area_m2 is not None and polygon_area_m2 > 0.0:
            delta_ratio = abs(explicit_value - polygon_area_m2) / explicit_value
            if delta_ratio > max_delta_ratio:
                return _abstention(
                    room=room,
                    entity=entity,
                    context=context,
                    blockers=("explicit_vs_scaled_area_conflict",),
                    authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
                    metadata={
                        "explicit_area_m2": explicit_value,
                        "polygon_area_m2": round(polygon_area_m2, 6),
                        "delta_ratio": delta_ratio,
                        "explicit_area_evidence_fingerprint": explicit_fp,
                        "scale_fingerprint": scale_fp,
                    },
                )
        value = round(explicit_value, 6)
        payload = {
            "family": ROOM_AREA_FAMILY,
            "room_id": room.room_ref,
            "value_m2": value,
            "explicit_area_evidence_fingerprint": explicit_fp,
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "viewport_id": viewport.viewport_id,
        }
        return QuantityEvidence(
            quantity_id=stable_contract_id("qty", payload),
            family=ROOM_AREA_FAMILY,
            semantic_key=f"room_area:{room.room_ref}",
            value=value,
            unit="m2",
            input_entity_ids=(room.room_ref,),
            formula="authoritative_explicit_area",
            formula_version=ROOM_AREA_FORMULA_VERSION,
            evidence_ids=tuple(entity.evidence_ids),
            authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            status=AuthorityStatus.FIRM.value,
            confidence=min(
                float(room.geometry_confidence),
                float(entity.confidence),
                float(explicit_area_evidence.confidence),
            ),
            abstained=False,
            metadata={
                "source_sha256": context.source_sha256,
                "revision_id": context.current_revision_id,
                "page_no": page_no,
                "viewport_id": viewport.viewport_id,
                "explicit_area_evidence_id": explicit_area_evidence.evidence_id,
                "explicit_area_evidence_fingerprint": explicit_fp,
                "scale_fingerprint": scale_fp,
                "ignored_prefilled_floor_area_m2": room.floor_area_m2,
                "ignored_prefilled_explicit_area_label_m2": room.explicit_area_label_m2,
            },
        )

    if room.has_voids:
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=("room_void_geometry_not_explicit",),
            authority=MeasurementAuthorityType.PDF_SCALED.value,
        )
    if scale_calibration is None:
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=("no_authoritative_area_input",),
            authority=MeasurementAuthorityType.PDF_SCALED.value,
        )
    if scale_blockers:
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=scale_blockers,
            authority=MeasurementAuthorityType.PDF_SCALED.value,
            metadata={"scale_fingerprint": scale_fp},
        )
    if polygon_area_m2 is None or polygon_area_m2 <= 0.0 or not math.isfinite(polygon_area_m2):
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=("room_polygon_area_invalid",),
            authority=MeasurementAuthorityType.PDF_SCALED.value,
        )

    value = round(polygon_area_m2, 6)
    ring = _canonical_ring(room.polygon_pdf_pts)
    payload = {
        "family": ROOM_AREA_FAMILY,
        "room_id": room.room_ref,
        "value_m2": value,
        "scale_fingerprint": scale_fp,
        "ring": ring,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "viewport_id": viewport.viewport_id,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=ROOM_AREA_FAMILY,
        semantic_key=f"room_area:{room.room_ref}",
        value=value,
        unit="m2",
        input_entity_ids=(room.room_ref,),
        formula="shoelace_polygon_area / trusted_px_per_m^2",
        formula_version=ROOM_AREA_FORMULA_VERSION,
        evidence_ids=tuple(entity.evidence_ids),
        authority=MeasurementAuthorityType.PDF_SCALED.value,
        status=AuthorityStatus.FIRM.value,
        confidence=min(float(room.geometry_confidence), float(entity.confidence)),
        abstained=False,
        metadata={
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "page_no": page_no,
            "viewport_id": viewport.viewport_id,
            "scale_fingerprint": scale_fp,
            "ring_signature": hashlib.sha256(
                canonical_contract_json(ring).encode("utf-8")
            ).hexdigest(),
            "has_voids": False,
            "ignored_prefilled_floor_area_m2": room.floor_area_m2,
            "ignored_prefilled_explicit_area_label_m2": room.explicit_area_label_m2,
        },
    )


def build_room_area_quantities(
    *,
    rooms: Sequence[RoomCandidate],
    entities_by_room_id: dict[str, EntityEvidence],
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
    scale_calibration: Optional[ScaleCalibration] = None,
    explicit_area_evidence_by_room_id: Optional[dict[str, EvidenceAtom]] = None,
) -> tuple[QuantityEvidence, ...]:
    """Batch builder that abstains on duplicate identities or duplicate faces."""
    explicit = explicit_area_evidence_by_room_id or {}
    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    rings: dict[tuple[tuple[float, float], ...], list[str]] = {}
    for room in rooms:
        if room.room_ref in seen_ids:
            duplicate_ids.add(room.room_ref)
        seen_ids.add(room.room_ref)
        rings.setdefault(_canonical_ring(room.polygon_pdf_pts), []).append(room.room_ref)
    duplicate_face_ids = {
        room_id
        for ids in rings.values()
        if len(ids) > 1
        for room_id in ids
    }

    output: list[QuantityEvidence] = []
    for room in rooms:
        entity = entities_by_room_id.get(room.room_ref)
        if entity is None:
            raise ValueError(f"missing EntityEvidence for room {room.room_ref!r}")
        blockers: list[str] = []
        if room.room_ref in duplicate_ids:
            blockers.append("duplicate_room_identity")
        if room.room_ref in duplicate_face_ids:
            blockers.append("duplicate_room_face")
        if blockers:
            output.append(
                _abstention(
                    room=room,
                    entity=entity,
                    context=context,
                    blockers=tuple(blockers),
                )
            )
            continue
        output.append(
            build_room_area_quantity(
                room=room,
                context=context,
                document=document,
                viewport=viewport,
                entity=entity,
                page_no=page_no,
                scale_calibration=scale_calibration,
                explicit_area_evidence=explicit.get(room.room_ref),
            )
        )
    return tuple(output)
