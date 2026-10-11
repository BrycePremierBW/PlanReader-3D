"""Canonical ceiling-area QuantityEvidence publication.

This module does not extract ceilings, derive finish semantics, measure geometry,
or create customer rows. It only reissues an already source-owned canonical
ceiling area when the live ceiling integration has proven exact canonical
identity plus a FIRM upstream measurement authority.

The shadow ceiling-lining producer remains unchanged and provisional. This
adapter is a distinct canonical -> quantity authority boundary.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_live_ceiling_lining_integration import (
    LiveCanonicalCeilingSurfaceObject,
    LiveCeilingLiningResult,
)
from pb_migration_contracts import QuantityEvidence, stable_contract_id


LIVE_CEILING_AREA_QUANTITY_SCHEMA_VERSION = "1.0.0"
LIVE_CEILING_AREA_QUANTITY_RESOLVED = "live_ceiling_area_quantity_resolved"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _source_quantities(
    result: LiveCeilingLiningResult,
) -> dict[str, QuantityEvidence]:
    out: dict[str, QuantityEvidence] = {}
    contradictory_ids: set[str] = set()
    for quantity in result.quantity_evidence:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("quantity_evidence must contain QuantityEvidence")
        qid = _clean(quantity.quantity_id)
        if not qid:
            continue
        if qid in contradictory_ids:
            continue
        prior = out.get(qid)
        if prior is not None:
            if prior != quantity:
                # Source ID collisions are untrustworthy even when one
                # candidate happens to equal a canonical ceiling's area.
                # Never choose the first or last replay as a winner.
                out.pop(qid, None)
                contradictory_ids.add(qid)
            continue
        out[qid] = quantity
    return out


def _publish_one(
    ceiling: LiveCanonicalCeilingSurfaceObject,
    source: QuantityEvidence,
) -> QuantityEvidence | None:
    if type(ceiling) is not LiveCanonicalCeilingSurfaceObject:
        raise TypeError(
            "canonical_ceilings must contain LiveCanonicalCeilingSurfaceObject"
        )
    canonical_id = _clean(ceiling.canonical_ceiling_id)
    if not canonical_id:
        return None
    if (
        not ceiling.geometry_complete
        or not ceiling.metric_area_complete
        or not _clean(ceiling.room_entity_id)
        or not _clean(ceiling.room_area_quantity_id)
        or not _clean(ceiling.ceiling_quantity_id)
    ):
        return None

    try:
        area = float(ceiling.area_m2)
        source_value = float(source.value)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(area)
        or area <= 0.0
        or not math.isfinite(source_value)
        or abs(area - source_value) > 1e-9
    ):
        return None

    meta = source.metadata if isinstance(source.metadata, Mapping) else {}
    if (
        source.abstained
        or source.value is None
        or source.blocking_reasons
        or _clean(source.quantity_id) != _clean(ceiling.ceiling_quantity_id)
        or _clean(source.family) != "ceiling_lining"
        or _clean(source.unit).lower() not in {"m2", "m²"}
        or _clean(source.status) != AuthorityStatus.PROVISIONAL.value
        or _clean(source.authority) != MeasurementAuthorityType.MODEL_DERIVED.value
        or tuple(source.input_entity_ids) != (_clean(ceiling.room_entity_id),)
        or meta.get("shadow_only") is not True
        or meta.get("commercial_projection_allowed") is not False
    ):
        return None

    # Retain the actual source evidence receipt universe before projecting
    # the canonical ceiling.  Set-based subset tests alone erase empty and
    # duplicate upstream receipts and can make corrupted source look complete.
    for receipts in (ceiling.evidence_ids, source.evidence_ids):
        if (
            not isinstance(receipts, (tuple, list))
            or not receipts
            or any(type(value) is not str or not value.strip() for value in receipts)
            or len(set(receipts)) != len(receipts)
        ):
            return None
    # Optional source-owned identity metadata is authoritative when recorded.
    # A shadow ceiling from another source document or physical-room snapshot
    # must not be replayed onto this canonical ceiling.
    if (
        meta.get("document_id") is not None
        and _clean(meta["document_id"]) != _clean(ceiling.document_id)
    ):
        return None
    if (
        meta.get("room_snapshot_id") is not None
        and _clean(meta["room_snapshot_id"]) != _clean(ceiling.snapshot_id)
    ):
        return None
    if (
        _clean(meta.get("upstream_area_quantity_id"))
        != _clean(ceiling.room_area_quantity_id)
        or _clean(meta.get("source_sha256")).lower()
        != _clean(ceiling.source_sha256).lower()
        or _clean(meta.get("revision_id")) != _clean(ceiling.revision_id)
        or _clean(meta.get("viewport_id")) != _clean(ceiling.viewport_id)
        or _clean(meta.get("page_no")) != str(ceiling.source_page)
        or not ceiling.evidence_ids
        or not source.evidence_ids
        or not set(ceiling.evidence_ids).issubset(set(source.evidence_ids))
    ):
        return None

    measurement_authority = _clean(ceiling.measurement_authority)
    if measurement_authority == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value:
        # Do not count characters from one malformed string as multiple
        # independent original figured-dimension observations. This final
        # QuantityEvidence boundary must fail closed even when canonical
        # objects come from other producers or test/imported records.
        raw_figured_ids = ceiling.figured_dimension_ids
        if (
            not isinstance(raw_figured_ids, (tuple, list))
            or not all(isinstance(value, str) for value in raw_figured_ids)
        ):
            return None
        figured_ids = tuple(
            sorted({_clean(value) for value in raw_figured_ids if _clean(value)})
        )
        # Exactly one orthogonal source-owned dimension pair is required.
        # Additional distinct source systems are ambiguous, not extra
        # permission to resolve area from whichever pair happens to fit.
        if len(figured_ids) != 2:
            return None
        resolved_scale_id = None
    elif measurement_authority == MeasurementAuthorityType.PDF_SCALED.value:
        figured_ids = ()
        resolved_scale_id = _clean(ceiling.physical_scale_record_id)
        if not resolved_scale_id:
            return None
    else:
        return None

    payload = {
        "schema_version": LIVE_CEILING_AREA_QUANTITY_SCHEMA_VERSION,
        "canonical_ceiling_id": canonical_id,
        "room_area_quantity_id": ceiling.room_area_quantity_id,
        "shadow_ceiling_quantity_id": ceiling.ceiling_quantity_id,
        "value_m2": area,
        "measurement_authority": measurement_authority,
        "source_sha256": ceiling.source_sha256,
        "revision_id": ceiling.revision_id,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("canonical_ceiling_area_quantity", payload),
        family="ceiling_lining",
        semantic_key=f"ceiling_lining:{canonical_id}",
        value=area,
        unit="m2",
        input_entity_ids=(canonical_id,),
        formula=(
            "reuse exact firm documented room area on canonical ceiling"
            if measurement_authority
            == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
            else "reuse exact firm scaled room area on canonical ceiling"
        ),
        formula_version=LIVE_CEILING_AREA_QUANTITY_SCHEMA_VERSION,
        evidence_ids=tuple(ceiling.evidence_ids),
        authority=measurement_authority,
        status=AuthorityStatus.FIRM.value,
        confidence=float(source.confidence),
        abstained=False,
        blocking_reasons=(),
        reason_codes=(LIVE_CEILING_AREA_QUANTITY_RESOLVED,),
        metadata={
            "document_id": ceiling.document_id,
            "snapshot_id": ceiling.snapshot_id,
            "source_sha256": ceiling.source_sha256,
            "revision_id": ceiling.revision_id,
            "page_no": ceiling.source_page,
            "viewport_id": ceiling.viewport_id,
            "canonical_ceiling_id": canonical_id,
            "room_entity_id": ceiling.room_entity_id,
            "room_area_quantity_id": ceiling.room_area_quantity_id,
            "shadow_ceiling_quantity_id": ceiling.ceiling_quantity_id,
            "finish_descriptor": ceiling.finish_descriptor,
            "source_room_index_id": ceiling.source_room_index_id,
            "measurement_authority": measurement_authority,
            "figured_dimension_ids": figured_ids,
            "resolved_scale_id": resolved_scale_id,
            "commercial_projection_allowed": False,
            "quantity_handoff_only": True,
            "row_role": "ceiling_area",
        },
    )


def publish_live_ceiling_area_quantities(
    result: LiveCeilingLiningResult,
) -> tuple[QuantityEvidence, ...]:
    """Publish stable canonical-ceiling QuantityEvidence only.

    The function deliberately creates no customer rows. A caller may hand these
    typed quantities to downstream sealing/output code after its own policy gate.
    """
    if type(result) is not LiveCeilingLiningResult:
        raise TypeError("result must be LiveCeilingLiningResult")

    # Validate the complete producer-owned ceiling universe before filtering
    # unsupported candidates. Otherwise one FIRM ceiling can publish while a
    # second ABSTAIN/CONFLICT candidate secretly reuses its canonical identity.
    # This mirrors the source-closed opening identity quarantine boundary.
    canonical_ids: set[str] = set()
    for ceiling in result.canonical_ceilings:
        if type(ceiling) is not LiveCanonicalCeilingSurfaceObject:
            raise TypeError(
                "canonical_ceilings must contain LiveCanonicalCeilingSurfaceObject"
            )
        ceiling_id = _clean(ceiling.canonical_ceiling_id)
        if ceiling_id and ceiling_id in canonical_ids:
            raise ValueError(
                f"duplicate canonical ceiling identity in quantity publication: {ceiling_id}"
            )
        if ceiling_id:
            canonical_ids.add(ceiling_id)

    source_by_id = _source_quantities(result)
    # Run the existing canonical/source measurement authorization FIRST.
    # An unrelated, unmeasured/ABSTAIN ceiling with no approved source cannot
    # revoke another ceiling's previously authenticated FIRM quantity.
    approved: list[tuple[LiveCanonicalCeilingSurfaceObject, QuantityEvidence]] = []
    for ceiling in sorted(
        result.canonical_ceilings,
        key=lambda item: item.canonical_ceiling_id,
    ):
        source = source_by_id.get(_clean(ceiling.ceiling_quantity_id))
        if source is None:
            continue
        quantity = _publish_one(ceiling, source)
        if quantity is not None:
            approved.append((ceiling, quantity))

    # Conversely, two independently publishable FULL-area ceiling claims
    # cannot both reissue the SAME original room-area QuantityEvidence source.
    # Quarantine both rather than first/last-writer-wins or double count.
    approved_area_owners: dict[str, set[str]] = {}
    approved_room_owners: dict[str, set[str]] = {}
    for ceiling, _quantity in approved:
        ceiling_id = _clean(ceiling.canonical_ceiling_id)
        approved_area_owners.setdefault(
            _clean(ceiling.room_area_quantity_id), set()
        ).add(ceiling_id)
        # A second source quantity ID is not an independent physical room.
        # This adapter republishes the *whole* documented room area, never a
        # proven ceiling sub-area. Two whole-area ceilings owned by one room
        # would double count even with different source quantity IDs.
        approved_room_owners.setdefault(
            _clean(ceiling.room_entity_id), set()
        ).add(ceiling_id)
    contested_area_sources = {
        source_id for source_id, owners in approved_area_owners.items()
        if len(owners) > 1
    }
    contested_rooms = {
        room_id for room_id, owners in approved_room_owners.items()
        if len(owners) > 1
    }

    out: list[QuantityEvidence] = []
    seen_entity_ids: set[str] = set()
    seen_quantity_ids: set[str] = set()
    for ceiling, quantity in approved:
        if (_clean(ceiling.room_area_quantity_id) in contested_area_sources
                or _clean(ceiling.room_entity_id) in contested_rooms):
            continue
        entity_id = quantity.input_entity_ids[0]
        if entity_id in seen_entity_ids:
            raise ValueError(
                f"duplicate canonical ceiling identity in quantity publication: {entity_id}"
            )
        if quantity.quantity_id in seen_quantity_ids:
            raise ValueError(
                f"duplicate canonical ceiling quantity id: {quantity.quantity_id}"
            )
        seen_entity_ids.add(entity_id)
        seen_quantity_ids.add(quantity.quantity_id)
        out.append(quantity)

    return tuple(out)


__all__ = [
    "LIVE_CEILING_AREA_QUANTITY_RESOLVED",
    "LIVE_CEILING_AREA_QUANTITY_SCHEMA_VERSION",
    "publish_live_ceiling_area_quantities",
]
