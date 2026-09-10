"""Deterministic room/floor-area QuantityEvidence from W5/W10 room topology.

This is a benchmark-independent measurement layer. It consumes existing
``RoomCandidate`` geometry and the existing page-scale authority. Explicit area
labels may be used only when backed by owned, corroborated EvidenceAtom records.
No commercial authority is enabled here.
"""
from __future__ import annotations

import hashlib
import math
from typing import Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_measurement_input_authority import scale_calibration_fingerprint
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    canonical_contract_json,
    stable_contract_id,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import (
    check_calibration_freshness,
    measurement_authority_for_page_scale,
)
from pb_wall_room_topology_contracts import RoomCandidate

ROOM_AREA_FAMILY = "room_area"
ROOM_AREA_FORMULA_VERSION = "1.0.0"


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _canonical_ring(points: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    """Canonical cyclic/reversal invariant signature for exact duplicate detection."""
    pts = tuple((round(float(x), 8), round(float(y), 8)) for x, y in points)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return ()
    rotations = [pts[i:] + pts[:i] for i in range(len(pts))]
    rev = tuple(reversed(pts))
    rotations.extend(rev[i:] + rev[:i] for i in range(len(rev)))
    return min(rotations)


def _area_evidence_fingerprint(evidence: EvidenceAtom) -> str:
    return hashlib.sha256(canonical_contract_json(evidence.to_dict()).encode("utf-8")).hexdigest()


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
    if room.status != EvidenceResolutionStatus.CORROBORATED:
        blockers.append("room_topology_not_corroborated")
    if room.room_ref != entity.candidate_entity_id:
        blockers.append("room_entity_identity_mismatch")
    if room.document_id != context.document_id or document.document_id != context.document_id:
        blockers.append("document_id_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append("source_sha256_mismatch")
    if room.viewport_id != viewport.viewport_id:
        blockers.append("room_viewport_mismatch")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append("viewport_not_owned")
    if page_no not in context.trusted_page_numbers():
        blockers.append("page_not_owned")
    mapped_page = context.page_for_viewport(viewport.viewport_id)
    if mapped_page is not None and mapped_page != page_no:
        blockers.append("viewport_page_mismatch")
    if room.source_page and int(room.source_page) != page_no:
        blockers.append("room_source_page_mismatch")
    if not set(entity.evidence_ids).issubset(set(document.evidence_ids)):
        blockers.append("entity_evidence_not_owned_by_document")
    if entity.status in (EvidenceResolutionStatus.CONFLICT, EvidenceResolutionStatus.ABSTAINED):
        blockers.append("entity_unresolved")
    if room.area_conflict:
        blockers.append("room_area_conflict")
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
    """Build one room-area quantity or explicit abstention.

    ``has_voids=True`` fails closed unless an authoritative explicit area label is
    supplied, because RoomCandidate currently does not expose the actual hole rings
    needed to independently reproduce a net polygon area.
    """
    blockers = list(
        _validate_common(
            room=room,
            entity=entity,
            context=context,
            document=document,
            viewport=viewport,
            page_no=page_no,
        )
    )
    if blockers:
        return _abstention(room=room, entity=entity, context=context, blockers=tuple(blockers))

    explicit_value: Optional[float] = None
    explicit_fp: Optional[str] = None
    if explicit_area_evidence is not None:
        exp_blockers: list[str] = []
        if explicit_area_evidence.evidence_id not in document.evidence_ids:
            exp_blockers.append("explicit_area_evidence_not_owned_by_document")
        if explicit_area_evidence.evidence_id not in entity.evidence_ids:
            exp_blockers.append("explicit_area_evidence_not_owned_by_entity")
        if explicit_area_evidence.document_id != document.document_id:
            exp_blockers.append("explicit_area_document_mismatch")
        if explicit_area_evidence.page_id != viewport.page_id:
            exp_blockers.append("explicit_area_page_mismatch")
        if explicit_area_evidence.viewport_id not in (None, viewport.viewport_id):
            exp_blockers.append("explicit_area_viewport_mismatch")
        if explicit_area_evidence.status != EvidenceResolutionStatus.CORROBORATED:
            exp_blockers.append("explicit_area_not_corroborated")
        if explicit_area_evidence.normalized_value is None:
            exp_blockers.append("explicit_area_missing_normalized_value")
        elif not math.isfinite(float(explicit_area_evidence.normalized_value)) or float(explicit_area_evidence.normalized_value) <= 0.0:
            exp_blockers.append("explicit_area_invalid")
        if explicit_area_evidence.unit not in ("m2", "m²"):
            exp_blockers.append("explicit_area_unit_not_m2")
        if exp_blockers:
            return _abstention(
                room=room,
                entity=entity,
                context=context,
                blockers=tuple(exp_blockers),
                authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            )
        explicit_value = float(explicit_area_evidence.normalized_value)
        explicit_fp = _area_evidence_fingerprint(explicit_area_evidence)

    polygon_area_page = _polygon_area(room.polygon_pdf_pts)
    polygon_area_m2: Optional[float] = None
    scale_fp: Optional[str] = None
    if scale_calibration is not None:
        if scale_calibration.page_no != page_no:
            if explicit_value is None:
                return _abstention(
                    room=room,
                    entity=entity,
                    context=context,
                    blockers=("scale_page_mismatch",),
                    authority=MeasurementAuthorityType.PDF_SCALED.value,
                )
        else:
            fresh = check_calibration_freshness(scale_calibration, context.current_revision_id)
            if measurement_authority_for_page_scale(fresh) == AuthorityStatus.FIRM.value and fresh.px_per_m > 0.0 and math.isfinite(fresh.px_per_m):
                polygon_area_m2 = polygon_area_page / (fresh.px_per_m ** 2)
                scale_fp = scale_calibration_fingerprint(fresh)
            elif explicit_value is None:
                return _abstention(
                    room=room,
                    entity=entity,
                    context=context,
                    blockers=("scale_not_firm",),
                    authority=MeasurementAuthorityType.PDF_SCALED.value,
                    metadata={"scale_fingerprint": scale_calibration_fingerprint(fresh)},
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
            "room_id": room.room_ref,
            "value_m2": value,
            "explicit_area_evidence_fingerprint": explicit_fp,
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
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
            confidence=min(float(room.geometry_confidence), float(entity.confidence), float(explicit_area_evidence.confidence if explicit_area_evidence else 1.0)),
            abstained=False,
            metadata={
                "source_sha256": context.source_sha256,
                "revision_id": context.current_revision_id,
                "page_no": page_no,
                "viewport_id": viewport.viewport_id,
                "explicit_area_evidence_id": explicit_area_evidence.evidence_id if explicit_area_evidence else None,
                "explicit_area_evidence_fingerprint": explicit_fp,
                "scale_fingerprint": scale_fp,
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
    if polygon_area_m2 is None:
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=("no_authoritative_area_input",),
            authority=MeasurementAuthorityType.PDF_SCALED.value,
        )
    if polygon_area_page <= 0.0 or polygon_area_m2 <= 0.0:
        return _abstention(
            room=room,
            entity=entity,
            context=context,
            blockers=("room_polygon_area_invalid",),
            authority=MeasurementAuthorityType.PDF_SCALED.value,
        )

    value = round(polygon_area_m2, 6)
    payload = {
        "room_id": room.room_ref,
        "value_m2": value,
        "scale_fingerprint": scale_fp,
        "ring": _canonical_ring(room.polygon_pdf_pts),
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
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
            "ring_signature": hashlib.sha256(canonical_contract_json(_canonical_ring(room.polygon_pdf_pts)).encode("utf-8")).hexdigest(),
            "has_voids": False,
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
    """Batch builder that fails closed on duplicate room IDs or identical faces."""
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

    out: list[QuantityEvidence] = []
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
            out.append(
                _abstention(
                    room=room,
                    entity=entity,
                    context=context,
                    blockers=tuple(blockers),
                )
            )
            continue
        out.append(
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
    return tuple(out)
