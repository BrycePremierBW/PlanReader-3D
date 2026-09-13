"""Dependency-safe gross wall-area QuantityEvidence.

Consumes existing FIRM wall-length and wall-height QuantityEvidence for the same
physical wall. This module is a deterministic quantity derivation only: it does
not resolve scale, infer height, bind openings, read benchmark gold, or enable
commercial/migration authority.
"""
from __future__ import annotations

import hashlib
import math
from typing import Mapping, Optional

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_migration_contracts import QuantityEvidence, canonical_contract_json, stable_contract_id

GROSS_WALL_AREA_FAMILY = "wall_gross_area"
GROSS_WALL_AREA_FORMULA_VERSION = "1.0.0"
_LENGTH_FAMILY = "wall_length"
_HEIGHT_FAMILY = "wall_height"


def quantity_evidence_fingerprint(quantity: QuantityEvidence) -> str:
    return hashlib.sha256(
        canonical_contract_json(quantity.to_dict()).encode("utf-8")
    ).hexdigest()


def _metadata(quantity: QuantityEvidence) -> Mapping[str, object]:
    return quantity.metadata if isinstance(quantity.metadata, Mapping) else {}


def _single_wall_id(quantity: QuantityEvidence) -> Optional[str]:
    if len(quantity.input_entity_ids) != 1:
        return None
    return str(quantity.input_entity_ids[0])


def _source_tuple(quantity: QuantityEvidence) -> tuple[object, object, object]:
    meta = _metadata(quantity)
    return (
        meta.get("source_sha256"),
        meta.get("revision_id"),
        meta.get("viewport_id"),
    )


def _abstain(
    *,
    wall_id: str,
    length: QuantityEvidence,
    height: QuantityEvidence,
    blockers: tuple[str, ...],
) -> QuantityEvidence:
    length_fp = quantity_evidence_fingerprint(length)
    height_fp = quantity_evidence_fingerprint(height)
    payload = {
        "family": GROSS_WALL_AREA_FAMILY,
        "wall_id": wall_id,
        "length_quantity_id": length.quantity_id,
        "height_quantity_id": height.quantity_id,
        "length_fingerprint": length_fp,
        "height_fingerprint": height_fp,
        "blockers": list(blockers),
    }
    evidence_ids = tuple(dict.fromkeys((*length.evidence_ids, *height.evidence_ids)))
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=GROSS_WALL_AREA_FAMILY,
        semantic_key=f"wall_gross_area:{wall_id}",
        value=None,
        unit="m2",
        input_entity_ids=(wall_id,),
        formula="firm_wall_length_m * firm_wall_height_m",
        formula_version=GROSS_WALL_AREA_FORMULA_VERSION,
        evidence_ids=evidence_ids,
        authority="derived_from_firm_measurements",
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=blockers,
        reason_codes=blockers,
        metadata={
            "dependency_quantity_ids": [length.quantity_id, height.quantity_id],
            "dependency_fingerprints": [length_fp, height_fp],
        },
    )


def build_gross_wall_area_quantity(
    *,
    wall_id: str,
    wall_length: QuantityEvidence,
    wall_height: QuantityEvidence,
) -> QuantityEvidence:
    """Multiply only mutually consistent FIRM wall length and wall height evidence."""
    blockers: list[str] = []

    if wall_length.family != _LENGTH_FAMILY:
        blockers.append("invalid_wall_length_family")
    if wall_height.family != _HEIGHT_FAMILY:
        blockers.append("invalid_wall_height_family")
    if wall_length.unit != "m":
        blockers.append("invalid_wall_length_unit")
    if wall_height.unit != "m":
        blockers.append("invalid_wall_height_unit")

    length_wall = _single_wall_id(wall_length)
    height_wall = _single_wall_id(wall_height)
    if length_wall != wall_id:
        blockers.append("wall_length_identity_mismatch")
    if height_wall != wall_id:
        blockers.append("wall_height_identity_mismatch")

    if wall_length.abstained or wall_length.value is None:
        blockers.append("wall_length_abstained")
    if wall_height.abstained or wall_height.value is None:
        blockers.append("wall_height_abstained")
    if wall_length.status != AuthorityStatus.FIRM.value:
        blockers.append("wall_length_not_firm")
    if wall_height.status != AuthorityStatus.FIRM.value:
        blockers.append("wall_height_not_firm")

    if wall_length.authority not in {
        MeasurementAuthorityType.PDF_SCALED.value,
        MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        MeasurementAuthorityType.USER_APPROVED.value,
    }:
        blockers.append("wall_length_authority_not_trusted")
    if wall_height.authority not in {
        MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        MeasurementAuthorityType.USER_APPROVED.value,
    }:
        blockers.append("wall_height_authority_not_trusted")

    length_source = _source_tuple(wall_length)
    height_source = _source_tuple(wall_height)
    if not all(length_source):
        blockers.append("wall_length_provenance_incomplete")
    if not all(height_source):
        blockers.append("wall_height_provenance_incomplete")
    if length_source[0] != height_source[0]:
        blockers.append("dependency_source_sha_mismatch")
    if length_source[1] != height_source[1]:
        blockers.append("dependency_revision_mismatch")
    if length_source[2] != height_source[2]:
        blockers.append("dependency_viewport_mismatch")

    for quantity, prefix in ((wall_length, "wall_length"), (wall_height, "wall_height")):
        if quantity.value is not None:
            value = float(quantity.value)
            if not math.isfinite(value) or value <= 0.0:
                blockers.append(f"{prefix}_value_invalid")

    if blockers:
        return _abstain(
            wall_id=wall_id,
            length=wall_length,
            height=wall_height,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    assert wall_length.value is not None and wall_height.value is not None
    value_m2 = round(float(wall_length.value) * float(wall_height.value), 6)
    if not math.isfinite(value_m2) or value_m2 <= 0.0:
        return _abstain(
            wall_id=wall_id,
            length=wall_length,
            height=wall_height,
            blockers=("gross_wall_area_invalid",),
        )

    length_fp = quantity_evidence_fingerprint(wall_length)
    height_fp = quantity_evidence_fingerprint(wall_height)
    payload = {
        "family": GROSS_WALL_AREA_FAMILY,
        "wall_id": wall_id,
        "value_m2": value_m2,
        "length_quantity_id": wall_length.quantity_id,
        "height_quantity_id": wall_height.quantity_id,
        "length_fingerprint": length_fp,
        "height_fingerprint": height_fp,
    }
    evidence_ids = tuple(dict.fromkeys((*wall_length.evidence_ids, *wall_height.evidence_ids)))
    length_meta = _metadata(wall_length)
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=GROSS_WALL_AREA_FAMILY,
        semantic_key=f"wall_gross_area:{wall_id}",
        value=value_m2,
        unit="m2",
        input_entity_ids=(wall_id,),
        formula="firm_wall_length_m * firm_wall_height_m",
        formula_version=GROSS_WALL_AREA_FORMULA_VERSION,
        evidence_ids=evidence_ids,
        authority="derived_from_firm_measurements",
        status=AuthorityStatus.FIRM.value,
        confidence=min(float(wall_length.confidence), float(wall_height.confidence)),
        abstained=False,
        metadata={
            "source_sha256": length_meta.get("source_sha256"),
            "revision_id": length_meta.get("revision_id"),
            "viewport_id": length_meta.get("viewport_id"),
            "page_no": length_meta.get("page_no"),
            "dependency_quantity_ids": [wall_length.quantity_id, wall_height.quantity_id],
            "dependency_fingerprints": [length_fp, height_fp],
        },
    )
