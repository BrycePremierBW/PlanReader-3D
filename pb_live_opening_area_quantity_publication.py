"""Source-closed opening-area quantity publication.

Consumes only typed LiveCanonicalOpeningObject instances. It never discovers an
opening, reads benchmark truth, or repairs missing measurement evidence. A
quantity is published only when the canonical physical identity is present,
door/window semantic kind is resolved, a positive area exists, and the exact
measurement evidence backing that area is retained on the object.
"""
from __future__ import annotations

import math

from pb_live_physical_opening_void_composition import (
    LiveCanonicalOpeningObject,
    LivePhysicalOpeningVoidComposition,
)
from pb_migration_contracts import QuantityEvidence, stable_contract_id


LIVE_OPENING_AREA_QUANTITY_SCHEMA_VERSION = "1.0.0"
LIVE_OPENING_AREA_QUANTITY_RESOLVED = "live_opening_area_quantity_resolved"
LIVE_OPENING_FIGURED_AREA_QUANTITY_AUTHORITY = (
    "pb_opening_label_dimension_authority.figured_opening_label_area"
)
LIVE_OPENING_GEOMETRY_AREA_QUANTITY_AUTHORITY = (
    "pb_live_physical_opening_void_composition.resolved_opening_geometry_area"
)
LIVE_OPENING_FRAME_SCHEDULE_AREA_QUANTITY_AUTHORITY = (
    "pb_schedule_opening_instance_binding_authority.authenticated_figured_frame_area"
)
LIVE_OPENING_ELEVATION_FRAME_AREA_QUANTITY_AUTHORITY = (
    "pb_opening_elevation_frame_area_authority.authenticated_elevation_frame_area"
)


def _opening_quantity(
    opening: LiveCanonicalOpeningObject,
) -> QuantityEvidence | None:
    if type(opening) is not LiveCanonicalOpeningObject:
        raise TypeError("opening must be LiveCanonicalOpeningObject")

    canonical_id = str(opening.canonical_opening_id or "").strip()
    physical_id = str(opening.physical_opening_id or "").strip()
    viewport_id = str(opening.viewport_id or "").strip()
    host_wall_id = str(opening.host_wall_id or "").strip()
    host_binding_record_id = str(opening.host_binding_record_id or "").strip()
    host_frame_record_id = str(opening.host_frame_record_id or "").strip()
    opening_kind = str(opening.opening_kind or "").strip().lower()
    basis = str(opening.area_basis or "").strip()
    if (
        not canonical_id
        or canonical_id != physical_id
        or not all(
            str(value or "").strip()
            for value in (
                opening.document_id,
                opening.revision_id,
                opening.source_sha256,
                opening.snapshot_id,
                opening.page_id,
                opening.representative_observation_id,
            )
        )
        or not viewport_id
        or not host_wall_id
        or not (host_binding_record_id or host_frame_record_id)
        or opening_kind not in {"door", "window"}
        or not basis
        or opening.area_m2 is None
    ):
        return None

    if type(opening.area_m2) not in (int, float):
        # A source replay with True must not become 1.0 m².
        return None
    try:
        value = float(opening.area_m2)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None

    # Do not turn malformed original source receipts into a cleaner universe
    # by string coercion, blank suppression or set deduplication.
    original_receipts = opening.evidence_ids
    if (
        not isinstance(original_receipts, (tuple, list))
        or not original_receipts
        or any(type(item) is not str or not item.strip()
               for item in original_receipts)
        or len(set(original_receipts)) != len(original_receipts)
    ):
        return None
    evidence_ids = tuple(sorted(original_receipts))
    if not evidence_ids:
        return None
    # A caller-replayed host string alone cannot certify the physical opening
    # owner. The composer retains each authenticated host binding/frame record
    # on canonical evidence; require that receipt at quantity publication.
    if any(
        receipt_id and receipt_id not in evidence_ids
        for receipt_id in (host_binding_record_id, host_frame_record_id)
    ):
        return None

    measurement_record_id = None
    quantity_authority = None
    if basis == "figured_opening_label":
        measurement_record_id = str(opening.figured_area_record_id or "").strip()
        if not measurement_record_id or measurement_record_id not in evidence_ids:
            return None
        quantity_authority = LIVE_OPENING_FIGURED_AREA_QUANTITY_AUTHORITY
    elif basis == "resolved_opening_geometry":
        measurement_record_id = str(opening.opening_void_record_id or "").strip()
        if not measurement_record_id or measurement_record_id not in evidence_ids:
            return None
        quantity_authority = LIVE_OPENING_GEOMETRY_AREA_QUANTITY_AUTHORITY
    elif basis == "authenticated_elevation_frame":
        measurement_record_id = str(opening.figured_area_record_id or "").strip()
        if not measurement_record_id or measurement_record_id not in evidence_ids:
            return None
        quantity_authority = LIVE_OPENING_ELEVATION_FRAME_AREA_QUANTITY_AUTHORITY
    elif basis == "authenticated_frame_schedule":
        measurement_record_id = str(opening.schedule_binding_record_id or "").strip()
        if (
            not measurement_record_id
            or measurement_record_id not in evidence_ids
            or str(opening.schedule_row_dimension_basis or "").strip().lower()
            != "frame"
        ):
            return None
        quantity_authority = LIVE_OPENING_FRAME_SCHEDULE_AREA_QUANTITY_AUTHORITY
    else:
        # Unknown area bases cannot silently become commercial quantities.
        return None

    payload = {
        "schema_version": LIVE_OPENING_AREA_QUANTITY_SCHEMA_VERSION,
        "canonical_opening_id": canonical_id,
        "opening_kind": opening_kind,
        "area_m2": value,
        "area_basis": basis,
        "measurement_record_id": measurement_record_id,
        "source_sha256": opening.source_sha256,
        "revision_id": opening.revision_id,
    }
    quantity_id = stable_contract_id(
        "opening_area",
        payload,
        digest_chars=32,
    )
    return QuantityEvidence(
        quantity_id=quantity_id,
        family="opening_area",
        semantic_key=f"{opening_kind}_area:{canonical_id}",
        value=value,
        unit="m2",
        input_entity_ids=(canonical_id,),
        formula=(
            "authenticated figured opening-label dimension product"
            if basis == "figured_opening_label"
            else (
                "authenticated figured elevation outer-frame dimension product"
                if basis == "authenticated_elevation_frame"
                else (
                    "authenticated outer-frame schedule width * height"
                    if basis == "authenticated_frame_schedule"
                    else "authenticated physical opening width * height"
                )
            )
        ),
        formula_version=LIVE_OPENING_AREA_QUANTITY_SCHEMA_VERSION,
        evidence_ids=evidence_ids,
        authority=quantity_authority,
        status="corroborated",
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=(LIVE_OPENING_AREA_QUANTITY_RESOLVED,),
        metadata={
            "document_id": opening.document_id,
            "revision_id": opening.revision_id,
            "source_sha256": opening.source_sha256,
            "snapshot_id": opening.snapshot_id,
            "page_no": opening.page_id,
            "viewport_id": viewport_id,
            "canonical_opening_id": canonical_id,
            "physical_opening_id": physical_id,
            "host_wall_id": host_wall_id,
            "host_binding_record_id": host_binding_record_id or None,
            "host_frame_record_id": host_frame_record_id or None,
            "opening_kind": opening_kind,
            "area_basis": basis,
            "measurement_record_id": measurement_record_id,
            "schedule_row_dimension_basis": (
                opening.schedule_row_dimension_basis or None
            ),
            "schedule_row_basis_source": (
                opening.schedule_row_basis_source or None
            ),
            "commercial_projection_allowed": True,
            "section": "Openings",
            "element": f"{opening_kind.title()} area",
            "location": str(opening.type_mark or "").strip() or opening_kind.title(),
            "substrate": "Other",
            "inclusion_status": "PROVISIONAL",
            "row_role": "",
        },
    )


def publish_live_opening_area_quantities(
    composition: LivePhysicalOpeningVoidComposition,
) -> tuple[QuantityEvidence, ...]:
    """Publish one deterministic area quantity per source-proven opening."""
    if type(composition) is not LivePhysicalOpeningVoidComposition:
        raise TypeError(
            "composition must be LivePhysicalOpeningVoidComposition"
        )

    # Check the *whole producer-owned canonical inventory* before narrowing
    # it to quantities. If an unsupported/ABSTAIN opening reuses the physical
    # identity of a FIRM opening, filtering first would silently publish the
    # favourable member and conceal contradictory identity lineage.
    canonical_ids: set[str] = set()
    physical_ids: set[str] = set()
    for opening in composition.canonical_openings:
        if type(opening) is not LiveCanonicalOpeningObject:
            raise TypeError("canonical_openings must contain LiveCanonicalOpeningObject")
        # A stale foreign-revision member cannot be filtered out as
        # unsupported while the favourable member becomes a commercial
        # quantity. The canonical composition is revision-scoped.
        if str(opening.revision_id or "").strip() != str(composition.revision_id or "").strip():
            raise ValueError(
                "canonical opening revision conflicts with quantity composition"
            )
        canonical_id = str(opening.canonical_opening_id or "").strip()
        physical_id = str(opening.physical_opening_id or "").strip()
        if canonical_id and canonical_id in canonical_ids:
            raise ValueError(
                f"duplicate canonical opening identity in quantity publication: {canonical_id}"
            )
        if physical_id and physical_id in physical_ids:
            raise ValueError(
                f"duplicate physical opening identity in quantity publication: {physical_id}"
            )
        if canonical_id:
            canonical_ids.add(canonical_id)
        if physical_id:
            physical_ids.add(physical_id)

    quantities: list[QuantityEvidence] = []
    seen_quantity_ids: set[str] = set()
    for opening in sorted(
        composition.canonical_openings,
        key=lambda item: item.canonical_opening_id,
    ):
        quantity = _opening_quantity(opening)
        if quantity is None:
            continue
        if quantity.quantity_id in seen_quantity_ids:
            raise ValueError(
                f"duplicate opening quantity id: {quantity.quantity_id}"
            )
        seen_quantity_ids.add(quantity.quantity_id)
        quantities.append(quantity)
    return tuple(quantities)


__all__ = [
    "LIVE_OPENING_FIGURED_AREA_QUANTITY_AUTHORITY",
    "LIVE_OPENING_GEOMETRY_AREA_QUANTITY_AUTHORITY",
    "LIVE_OPENING_FRAME_SCHEDULE_AREA_QUANTITY_AUTHORITY",
    "LIVE_OPENING_ELEVATION_FRAME_AREA_QUANTITY_AUTHORITY",
    "LIVE_OPENING_AREA_QUANTITY_RESOLVED",
    "LIVE_OPENING_AREA_QUANTITY_SCHEMA_VERSION",
    "publish_live_opening_area_quantities",
]
