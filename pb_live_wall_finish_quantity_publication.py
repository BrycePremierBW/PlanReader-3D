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
    SourceBoundWallFinishQuantitySelector,
    SOURCE_BOUND_WALL_FINISH_QUANTITY_SCHEMA_VERSION,
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

    # The record is producer-sealed, but immutable replay/copy operations can
    # still carry emptied source or physical identities. They must never
    # become a commercially publishable quantity with an orphan surface ID.
    if (
        any(
            not str(value or "").strip()
            for value in (
                record.record_id,
                record.document_id,
                record.revision_id,
                record.source_sha256,
                record.snapshot_id,
                record.trade_scope_id,
                record.finish_material,
            )
        )
        or not record.physical_face_ids
        or not record.physical_wall_ids
        or any(
            not str(value or "").strip()
            for group in (
                record.physical_face_ids,
                record.physical_wall_ids,
                record.physical_surface_ids,
            )
            for value in group
        )
    ):
        raise ValueError("resolved wall-finish quantity lacks physical/source identity")

    # A corroborated record cannot mint a commercial finish quantity if its
    # scope, bindings, or net-wall evidence receipts are absent or blank.
    if (
        not str(record.finish_scope_record_id).strip()
        or not record.finish_binding_ids
        or not record.net_wall_record_ids
        or any(not str(value).strip() for value in record.finish_binding_ids)
        or any(not str(value).strip() for value in record.net_wall_record_ids)
    ):
        raise ValueError("resolved wall-finish quantity lacks source lineage receipts")

    # The upstream source producer seals an exact selector, membership and
    # net-area aggregate into record_id. Frozen dataclass objects can still
    # be copied and altered at the final publication boundary; rederive that
    # seal so a stale or forged material/face/area cannot inherit authority.
    if (
        record.schema_version != SOURCE_BOUND_WALL_FINISH_QUANTITY_SCHEMA_VERSION
        or type(record.quantity_m2) not in (int, float)
        or not math.isfinite(float(record.quantity_m2))
        or record.quantity_m2 <= 0.0
        or any(
            type(value) is not str or not value or value != value.strip()
            for value in (
                record.page_id, record.viewport_id, record.decision_scope_id,
                record.document_id, record.revision_id, record.snapshot_id,
                record.trade_scope_id, record.finish_material, record.record_id,
                record.finish_scope_record_id,
            )
        )
        or type(record.source_sha256) is not str
        or len(record.source_sha256) != 64
        or any(ch not in "0123456789abcdefABCDEF" for ch in record.source_sha256)
        or any(
            not isinstance(group, (tuple, list))
            or not group
            or any(type(value) is not str or not value or value != value.strip() for value in group)
            or len(set(group)) != len(group)
            for group in (
                record.physical_face_ids, record.physical_surface_ids,
                record.physical_wall_ids, record.finish_binding_ids,
                record.net_wall_record_ids,
            )
        )
        or len(record.physical_surface_ids) != len(record.physical_face_ids)
    ):
        raise ValueError("wall-finish source quantity receipts or area are invalid")
    selector = SourceBoundWallFinishQuantitySelector(
        document_id=record.document_id,
        revision_id=record.revision_id,
        source_sha256=record.source_sha256,
        snapshot_id=record.snapshot_id,
        page_id=record.page_id,
        viewport_id=record.viewport_id,
        decision_scope_id=record.decision_scope_id,
        trade_scope_id=record.trade_scope_id,
        finish_material=record.finish_material,
    )
    producer_payload = {
        "selector": selector.key,
        "finish_scope_record_id": record.finish_scope_record_id,
        "physical_face_ids": tuple(record.physical_face_ids),
        "physical_wall_ids": tuple(record.physical_wall_ids),
        "physical_surface_ids": tuple(record.physical_surface_ids),
        "finish_binding_ids": tuple(record.finish_binding_ids),
        "net_wall_record_ids": tuple(record.net_wall_record_ids),
        "quantity_m2": round(float(record.quantity_m2), 12),
        "schema_version": SOURCE_BOUND_WALL_FINISH_QUANTITY_SCHEMA_VERSION,
    }
    expected_source_record_id = stable_contract_id(
        "source_bound_wall_finish_quantity", producer_payload, digest_chars=32,
    )
    if record.record_id != expected_source_record_id:
        raise ValueError("wall-finish source quantity record seal mismatch")

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
