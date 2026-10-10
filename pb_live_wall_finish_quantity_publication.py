"""QuantityEvidence projection for source-bound wall-finish quantities.

This adapter never measures or rebinds geometry. It reissues only an already
CORROBORATED SourceBoundWallFinishQuantityRecord and preserves its exact
physical finish-surface identities for downstream coverage/publication.
"""
from __future__ import annotations

import math

from pb_bound_wall_finish_quantity_authority import (
    FINISH_QUANTITY_RESOLVED,
    SourceBoundWallFinishQuantityRecord,
)
from pb_migration_contracts import EvidenceResolutionStatus, QuantityEvidence, stable_contract_id


LIVE_WALL_FINISH_QUANTITY_SCHEMA_VERSION = "1.0.0"
LIVE_WALL_FINISH_QUANTITY_AUTHORITY = (
    "pb_bound_wall_finish_quantity_authority.source_bound_wall_finish_quantity"
)


def publish_bound_wall_finish_quantity(
    record: SourceBoundWallFinishQuantityRecord,
) -> QuantityEvidence:
    if type(record) is not SourceBoundWallFinishQuantityRecord:
        raise TypeError("record must be SourceBoundWallFinishQuantityRecord")
    if (
        record.status is not EvidenceResolutionStatus.CORROBORATED
        or FINISH_QUANTITY_RESOLVED not in record.reason_codes
    ):
        raise ValueError("record must be a resolved corroborated wall-finish quantity")
    if not record.physical_surface_ids:
        raise ValueError("resolved wall-finish quantity lacks physical surface identities")

    # Resolve every structural and scalar identity before hashing/deduplicating:
    # dataclass replacement can otherwise smuggle lists, integers or None into
    # source receipt tuples, leading to TypeError or stringified fake receipts.
    source_fields = (
        record.record_id, record.document_id, record.revision_id,
        record.source_sha256, record.snapshot_id, record.page_id,
        record.viewport_id, record.decision_scope_id, record.trade_scope_id,
        record.finish_material,
    )
    if any(type(value) is not str or not value.strip() for value in source_fields):
        raise ValueError("resolved wall-finish quantity lacks physical/source identity")

    groups = (
        record.physical_surface_ids, record.physical_face_ids,
        record.physical_wall_ids, record.finish_binding_ids,
        record.net_wall_record_ids,
    )
    if any(
        not isinstance(group, (tuple, list)) or not group
        or any(type(value) is not str or not value.strip() for value in group)
        for group in groups
    ):
        raise ValueError("resolved wall-finish quantity lacks physical/source identity")
    if any(len(set(group)) != len(group) for group in groups):
        raise ValueError("resolved wall-finish quantity has duplicate identity receipts")
    if (
        type(record.finish_scope_record_id) is not str
        or not record.finish_scope_record_id.strip()
    ):
        raise ValueError("resolved wall-finish quantity lacks source lineage receipts")

    # Producer authority is required, but the final projection must still
    # reject replayed non-finite, non-positive or boolean metric quantities.
    if (
        type(record.quantity_m2) not in (int, float)
        or not math.isfinite(record.quantity_m2)
        or record.quantity_m2 <= 0
    ):
        raise ValueError("resolved wall-finish quantity has invalid metric area")

    # The record is already source-resolved; distinct classes of source receipt
    # must not collapse into the same evidence ID during commercial projection.
    raw_evidence_ids = (
        record.finish_scope_record_id,
        *record.finish_binding_ids,
        *record.net_wall_record_ids,
    )
    if len(raw_evidence_ids) != len(set(raw_evidence_ids)):
        raise ValueError("resolved wall-finish quantity has aliased source receipts")

    evidence_ids = tuple(
        dict.fromkeys(
            (
                record.finish_scope_record_id,
                *record.finish_binding_ids,
                *record.net_wall_record_ids,
            )
        )
    )
    payload = {
        "schema_version": LIVE_WALL_FINISH_QUANTITY_SCHEMA_VERSION,
        "source_record_id": record.record_id,
        "physical_surface_ids": tuple(record.physical_surface_ids),
        "quantity_m2": float(record.quantity_m2),
        "document_id": record.document_id,
        "revision_id": record.revision_id,
        "source_sha256": record.source_sha256,
        "snapshot_id": record.snapshot_id,
    }
    quantity_id = stable_contract_id(
        "wall_finish_quantity",
        payload,
        digest_chars=32,
    )
    return QuantityEvidence(
        quantity_id=quantity_id,
        family="wall_finish_area",
        semantic_key=(
            f"wall_finish_area:{record.trade_scope_id}:{record.finish_material}"
        ),
        value=float(record.quantity_m2),
        unit="m2",
        input_entity_ids=tuple(record.physical_surface_ids),
        formula="sum authenticated net wall area for complete source-owned finish-face scope",
        formula_version=LIVE_WALL_FINISH_QUANTITY_SCHEMA_VERSION,
        evidence_ids=evidence_ids,
        authority=LIVE_WALL_FINISH_QUANTITY_AUTHORITY,
        status=EvidenceResolutionStatus.CORROBORATED.value,
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=(FINISH_QUANTITY_RESOLVED,),
        metadata={
            "document_id": record.document_id,
            "revision_id": record.revision_id,
            "source_sha256": record.source_sha256,
            "snapshot_id": record.snapshot_id,
            "page_no": record.page_id,
            "viewport_id": record.viewport_id,
            "decision_scope_id": record.decision_scope_id,
            "trade_scope_id": record.trade_scope_id,
            "finish_material": record.finish_material,
            "source_quantity_record_id": record.record_id,
            "physical_surface_ids": tuple(record.physical_surface_ids),
            "physical_face_ids": tuple(record.physical_face_ids),
            "physical_wall_ids": tuple(record.physical_wall_ids),
            "commercial_projection_allowed": True,
            "section": "Wall finishes",
            "element": record.finish_material,
            "row_role": "wall_finish",
        },
    )


__all__ = [
    "LIVE_WALL_FINISH_QUANTITY_AUTHORITY",
    "LIVE_WALL_FINISH_QUANTITY_SCHEMA_VERSION",
    "publish_bound_wall_finish_quantity",
]
