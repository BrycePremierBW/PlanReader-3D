"""QuantityEvidence publication for already-resolved canonical slab area.

This adapter never measures slab geometry. A positive quantity can only be
reissued from a LiveCanonicalSlabObject that already passed the source-bound
metric boundary and lineage gates in pb_live_canonical_slab_projection.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from pb_live_canonical_slab_projection import (
    LIVE_CANONICAL_SLAB_SCHEMA_VERSION,
    LiveCanonicalSlabObject,
    _canonical_polygon_identity,
    _verified_metric_slab_polygon_area,
)
from pb_migration_contracts import QuantityEvidence, stable_contract_id


LIVE_SLAB_AREA_QUANTITY_SCHEMA_VERSION = "1.0.0"
LIVE_SLAB_AREA_QUANTITY_AUTHORITY = (
    "pb_live_canonical_slab_projection.resolved_metric_boundary_area"
)


def publish_live_slab_area_quantity(
    slab: LiveCanonicalSlabObject,
) -> QuantityEvidence | None:
    if type(slab) is not LiveCanonicalSlabObject:
        raise TypeError("slab must be LiveCanonicalSlabObject")
    if (
        slab.schema_version != LIVE_CANONICAL_SLAB_SCHEMA_VERSION
        or slab.coordinate_space != "metres"
        or slab.geometry_complete is not True
        or type(slab.source_page) is not int
        or slab.source_page < 0
        or any(
            type(value) is not str or not value or value != value.strip()
            for value in (
                slab.canonical_slab_id, slab.physical_slab_id, slab.document_id,
                slab.revision_id, slab.snapshot_id, slab.boundary_id, slab.slab_id,
            )
        )
        or slab.canonical_slab_id != slab.physical_slab_id
        or type(slab.source_sha256) is not str
        or len(slab.source_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in slab.source_sha256)
        or type(slab.area_m2) is bool
    ):
        return None
    try:
        value = float(slab.area_m2)
    except (TypeError, ValueError, OverflowError):
        return None
    metric_area = _verified_metric_slab_polygon_area(slab.polygon_m)
    if (
        not math.isfinite(value) or value <= 0.0
        or metric_area is None
        or not math.isclose(value, metric_area, rel_tol=1e-9, abs_tol=1e-6)
    ):
        return None

    # Canonical identities encode the exact source-owned metre polygon, page
    # and document. A replay can mutate an object's vertices while retaining
    # an old ID; that must never mint an area under the old physical owner.
    expected_physical_id = stable_contract_id(
        "physical_slab",
        {
            "document_id": slab.document_id,
            "source_page": slab.source_page,
            "polygon_m": _canonical_polygon_identity(slab.polygon_m),
        },
        digest_chars=32,
    )
    if expected_physical_id != slab.physical_slab_id:
        return None

    provenance = slab.provenance if isinstance(slab.provenance, Mapping) else {}
    raw_boundary_id = provenance.get("boundary_id")
    if type(raw_boundary_id) is not str or raw_boundary_id != slab.boundary_id:
        return None
    source_page = provenance.get("annotation_source_page")
    if source_page is not None:
        if type(source_page) not in (int, str):
            return None
        try:
            if int(source_page) != slab.source_page:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    for optional_receipt in ("annotation_id", "dimension_evidence_id"):
        receipt = provenance.get(optional_receipt)
        if receipt is not None and (
            type(receipt) is not str or not receipt or receipt != receipt.strip()
        ):
            return None

    evidence_ids = tuple(
        dict.fromkeys(
            value
            for value in (
                slab.boundary_id,
                slab.slab_id,
                str(provenance.get("annotation_id") or "").strip(),
                str(provenance.get("dimension_evidence_id") or "").strip(),
            )
            if value
        )
    )
    if not evidence_ids:
        return None

    payload = {
        "schema_version": LIVE_SLAB_AREA_QUANTITY_SCHEMA_VERSION,
        "physical_slab_id": slab.physical_slab_id,
        "boundary_id": slab.boundary_id,
        "value_m2": value,
        "source_sha256": slab.source_sha256,
        "revision_id": slab.revision_id,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("slab_area_quantity", payload),
        family="slab_area",
        semantic_key=f"slab_area:{slab.physical_slab_id}",
        value=value,
        unit="m2",
        input_entity_ids=(slab.physical_slab_id,),
        formula="resolved canonical slab metric boundary area",
        formula_version=LIVE_SLAB_AREA_QUANTITY_SCHEMA_VERSION,
        evidence_ids=evidence_ids,
        authority=LIVE_SLAB_AREA_QUANTITY_AUTHORITY,
        status="corroborated",
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=("live_slab_area_quantity_resolved",),
        metadata={
            "document_id": slab.document_id,
            "revision_id": slab.revision_id,
            "source_sha256": slab.source_sha256,
            "snapshot_id": slab.snapshot_id,
            "page_no": slab.source_page,
            "canonical_slab_id": slab.canonical_slab_id,
            "physical_slab_id": slab.physical_slab_id,
            "boundary_id": slab.boundary_id,
            "slab_type": slab.slab_type,
            "commercial_projection_allowed": False,
        },
    )


__all__ = [
    "LIVE_SLAB_AREA_QUANTITY_AUTHORITY",
    "LIVE_SLAB_AREA_QUANTITY_SCHEMA_VERSION",
    "publish_live_slab_area_quantity",
]
