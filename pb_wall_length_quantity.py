"""Deterministic wall-length QuantityEvidence from W1-W10 topology.

This module consumes existing WallCandidate topology plus the trusted measurement
input seam. It does not read benchmark gold, does not publish commercial takeoff,
and does not introduce a migration family authority state.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_measurement_input_authority import resolve_linear_measurement_input
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    stable_contract_id,
)
from pb_migration_provider_envelope import ProviderContext
from pb_wall_room_topology_contracts import WallCandidate

WALL_LENGTH_FAMILY = "wall_length"
WALL_LENGTH_FORMULA_VERSION = "1.0.0"


def _polyline_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )


def _wall_source_segment_ids(wall: WallCandidate) -> frozenset[str]:
    ids = set(wall.face_a_segment_ids)
    if wall.face_b_segment_ids:
        ids.update(wall.face_b_segment_ids)
    return frozenset(ids)


def _abstention(
    *,
    wall: WallCandidate,
    entity: EntityEvidence,
    context: ProviderContext,
    page_no: int,
    blockers: tuple[str, ...],
    authority: str = "unresolved",
    metadata: Optional[dict[str, object]] = None,
) -> QuantityEvidence:
    payload = {
        "family": WALL_LENGTH_FAMILY,
        "wall_id": wall.candidate_id,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "page_no": page_no,
        "viewport_id": wall.viewport_id,
        "blockers": list(blockers),
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=WALL_LENGTH_FAMILY,
        semantic_key=f"wall_length:{wall.candidate_id}",
        value=None,
        unit="m",
        input_entity_ids=(wall.candidate_id,),
        formula="polyline_length / trusted_px_per_m OR authoritative_figured_dimension",
        formula_version=WALL_LENGTH_FORMULA_VERSION,
        evidence_ids=tuple(entity.evidence_ids),
        authority=authority,
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=blockers,
        reason_codes=blockers,
        metadata=metadata or {},
    )


def build_wall_length_quantity(
    *,
    wall: WallCandidate,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    entity: EntityEvidence,
    page_no: int,
    scale_calibration: Optional[ScaleCalibration] = None,
    figured_evidence: Optional[EvidenceAtom] = None,
) -> QuantityEvidence:
    """Build one wall-length quantity, abstaining unless topology+measurement are safe."""
    topology_blockers: list[str] = []
    if wall.status != EvidenceResolutionStatus.CORROBORATED:
        topology_blockers.append("wall_topology_not_corroborated")
    if wall.viewport_id != viewport.viewport_id:
        topology_blockers.append("wall_viewport_mismatch")
    if wall.candidate_id != entity.candidate_entity_id:
        topology_blockers.append("wall_entity_identity_mismatch")
    if len(wall.centerline_pts) < 2:
        topology_blockers.append("wall_centerline_unresolved")
    page_length = _polyline_length(wall.centerline_pts)
    if not math.isfinite(page_length) or page_length <= 0.0:
        topology_blockers.append("wall_centerline_length_invalid")
    if topology_blockers:
        return _abstention(
            wall=wall,
            entity=entity,
            context=context,
            page_no=page_no,
            blockers=tuple(topology_blockers),
        )

    resolved = resolve_linear_measurement_input(
        context=context,
        document=document,
        viewport=viewport,
        entity=entity,
        page_no=page_no,
        scaled_length_page_units=page_length if scale_calibration is not None else None,
        scale_calibration=scale_calibration,
        figured_evidence=figured_evidence,
    )
    if resolved.abstained:
        return _abstention(
            wall=wall,
            entity=entity,
            context=context,
            page_no=page_no,
            blockers=resolved.blocking_reasons or ("measurement_input_abstained",),
            authority=resolved.source_type or "unresolved",
            metadata={
                "measurement_input_fingerprint": resolved.fingerprint(),
                "source_sha256": resolved.source_sha256,
                "revision_id": resolved.revision_id,
                "page_no": resolved.page_no,
                "viewport_id": resolved.viewport_id,
                "scale_fingerprint": resolved.scale_fingerprint,
                "figured_evidence_id": resolved.figured_evidence_id,
                "notes": resolved.notes,
            },
        )

    payload = {
        "family": WALL_LENGTH_FAMILY,
        "wall_id": wall.candidate_id,
        "measurement_input_fingerprint": resolved.fingerprint(),
        "value_m": resolved.value_m,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=WALL_LENGTH_FAMILY,
        semantic_key=f"wall_length:{wall.candidate_id}",
        value=resolved.value_m,
        unit="m",
        input_entity_ids=(wall.candidate_id,),
        formula="authoritative_figured_dimension" if resolved.source_type == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value else "polyline_length / trusted_px_per_m",
        formula_version=WALL_LENGTH_FORMULA_VERSION,
        evidence_ids=tuple(entity.evidence_ids),
        authority=resolved.source_type or "unresolved",
        status=AuthorityStatus.FIRM.value,
        confidence=min(float(wall.confidence), float(entity.confidence)),
        abstained=False,
        reason_codes=(),
        metadata={
            "measurement_input_fingerprint": resolved.fingerprint(),
            "source_sha256": resolved.source_sha256,
            "revision_id": resolved.revision_id,
            "page_no": resolved.page_no,
            "viewport_id": resolved.viewport_id,
            "scale_fingerprint": resolved.scale_fingerprint,
            "figured_evidence_id": resolved.figured_evidence_id,
            "source_segment_ids": sorted(_wall_source_segment_ids(wall)),
            "topology_schema_version": wall.schema_version,
        },
    )


def build_wall_length_quantities(
    *,
    walls: Sequence[WallCandidate],
    entities_by_wall_id: dict[str, EntityEvidence],
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
    scale_calibration: Optional[ScaleCalibration] = None,
    figured_evidence_by_wall_id: Optional[dict[str, EvidenceAtom]] = None,
) -> tuple[QuantityEvidence, ...]:
    """Batch builder with fail-closed duplicate representation protection.

    Duplicate candidate identities or overlapping source-segment ownership mean two
    wall records could represent the same physical geometry. Every affected claim
    abstains rather than silently summing fragmented/duplicated representations.
    """
    figured = figured_evidence_by_wall_id or {}
    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    for wall in walls:
        if wall.candidate_id in seen_ids:
            duplicate_ids.add(wall.candidate_id)
        seen_ids.add(wall.candidate_id)

    overlapping_ids: set[str] = set()
    for i, left in enumerate(walls):
        left_segments = _wall_source_segment_ids(left)
        for right in walls[i + 1 :]:
            if left.candidate_id == right.candidate_id:
                continue
            if left_segments & _wall_source_segment_ids(right):
                overlapping_ids.add(left.candidate_id)
                overlapping_ids.add(right.candidate_id)

    output: list[QuantityEvidence] = []
    for wall in walls:
        entity = entities_by_wall_id.get(wall.candidate_id)
        if entity is None:
            # QuantityEvidence requires an evidence-bearing EntityEvidence for this path.
            # Construct no synthetic entity: skip impossible binding as a deterministic
            # explicit error rather than fabricating provenance.
            raise ValueError(f"missing EntityEvidence for wall {wall.candidate_id!r}")
        blockers: list[str] = []
        if wall.candidate_id in duplicate_ids:
            blockers.append("duplicate_wall_identity")
        if wall.candidate_id in overlapping_ids:
            blockers.append("overlapping_wall_source_segments")
        if blockers:
            output.append(
                _abstention(
                    wall=wall,
                    entity=entity,
                    context=context,
                    page_no=page_no,
                    blockers=tuple(blockers),
                    metadata={"source_segment_ids": sorted(_wall_source_segment_ids(wall))},
                )
            )
            continue
        output.append(
            build_wall_length_quantity(
                wall=wall,
                context=context,
                document=document,
                viewport=viewport,
                entity=entity,
                page_no=page_no,
                scale_calibration=scale_calibration,
                figured_evidence=figured.get(wall.candidate_id),
            )
        )
    return tuple(output)
