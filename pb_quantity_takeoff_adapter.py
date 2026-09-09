"""Safe QuantityEvidence -> commercial takeoff-row projection for migration M5.

This module does not create commercial authority.  It projects graph quantities
into the existing takeoff-row mapping consumed by ``pb_takeoff_authority_v164``
and deliberately leaves every automated row as an unreviewed AI draft.  Existing
publishability/pricing/JobHub gates remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Mapping, Optional, Sequence

from pb_migration_contracts import QuantityEvidence, canonical_contract_json


COMMERCIAL_TAKEOFF_ADAPTER_VERSION = "1.0.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SENTINELS = {"", "nan", "none", "null"}
_VALID_COMMERCIAL_UNITS = {
    "ea", "each", "no", "nr",
    "m", "lm",
    "m2", "m²", "sqm",
    "m3", "m³",
}
_RESOLVED_SCALE_STATES = {"resolved", "verified", "authoritative", "calibrated"}


class CommercialTakeoffProjectionError(RuntimeError):
    """Base error for a fail-closed commercial projection."""


class MissingCommercialAuthorityError(CommercialTakeoffProjectionError):
    """Required project/source/measurement authority is missing or stale."""


class CommercialTakeoffConflictError(CommercialTakeoffProjectionError):
    """Conflicting or duplicate quantity claims cannot be projected commercially."""


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _norm(value: Any) -> str:
    return _clean(value).lower().replace("-", "_").replace(" ", "_")


def _required(value: Any, name: str) -> str:
    clean = _clean(value)
    if clean.lower() in _SENTINELS:
        raise MissingCommercialAuthorityError(f"{name} is required for commercial projection")
    return clean


def _json_copy(value: Any) -> Any:
    return json.loads(canonical_contract_json(value))


def _unit_is_valid(unit: str) -> bool:
    return _clean(unit).lower().replace(" ", "") in _VALID_COMMERCIAL_UNITS


@dataclass(frozen=True)
class CommercialTakeoffSourceTrace:
    """Exact project/document/revision/spatial trace owned by an evidence resolver."""

    workspace_id: int
    project_id: str
    document_id: str
    source_sha256: str
    source_page: str
    viewport_id: str
    revision_id: str
    current_revision_id: str
    evidence_ids: tuple[str, ...] = ()
    canonical_entity_ids: tuple[str, ...] = ()
    source_bbox: Optional[tuple[float, float, float, float]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.workspace_id, bool):
            raise MissingCommercialAuthorityError("workspace_id must be a positive integer")
        try:
            workspace_id = int(self.workspace_id)
        except (TypeError, ValueError, OverflowError) as exc:
            raise MissingCommercialAuthorityError("workspace_id must be a positive integer") from exc
        if workspace_id <= 0:
            raise MissingCommercialAuthorityError("workspace_id must be a positive integer")
        object.__setattr__(self, "workspace_id", workspace_id)

        for name in (
            "project_id", "document_id", "source_page", "viewport_id",
            "revision_id", "current_revision_id",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))

        source_sha = _clean(self.source_sha256).lower()
        if not _SHA256_RE.fullmatch(source_sha):
            raise MissingCommercialAuthorityError(
                "source_sha256 must be an exact lowercase 64-character SHA-256 digest"
            )
        object.__setattr__(self, "source_sha256", source_sha)

        if self.revision_id != self.current_revision_id:
            raise MissingCommercialAuthorityError(
                "revision_id is stale; commercial projection requires the current revision"
            )

        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise CommercialTakeoffConflictError("source trace contains duplicate evidence_ids")
        if len(set(self.canonical_entity_ids)) != len(self.canonical_entity_ids):
            raise CommercialTakeoffConflictError("source trace contains duplicate canonical_entity_ids")

        if self.source_bbox is not None:
            if len(self.source_bbox) != 4:
                raise MissingCommercialAuthorityError("source_bbox must contain four coordinates")
            try:
                bbox = tuple(float(v) for v in self.source_bbox)
            except (TypeError, ValueError) as exc:
                raise MissingCommercialAuthorityError("source_bbox must contain numeric coordinates") from exc
            if not all(math.isfinite(v) for v in bbox):
                raise MissingCommercialAuthorityError("source_bbox must be finite")
            x0, y0, x1, y1 = bbox
            if x1 < x0 or y1 < y0:
                raise MissingCommercialAuthorityError("source_bbox must satisfy x1 >= x0 and y1 >= y0")
            object.__setattr__(self, "source_bbox", bbox)

        object.__setattr__(self, "metadata", _json_copy(self.metadata))


@dataclass(frozen=True)
class CommercialMeasurementAuthority:
    """Projection-time proof of figured or scaled quantity authority.

    This is not estimator approval.  It only proves that the automated quantity
    was derived from an acceptable measurement source before it is allowed to
    become an *unreviewed* commercial takeoff row.
    """

    method: str
    figured_dimension_ids: tuple[str, ...] = ()
    resolved_scale_id: Optional[str] = None
    scale_status: str = ""
    scale_conflicts: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        method = _norm(self.method)
        if method not in {"figured_dimension", "scaled_geometry", "direct_evidence"}:
            raise MissingCommercialAuthorityError(
                "measurement method must be figured_dimension, scaled_geometry, or direct_evidence"
            )
        object.__setattr__(self, "method", method)

        if len(set(self.figured_dimension_ids)) != len(self.figured_dimension_ids):
            raise CommercialTakeoffConflictError("duplicate figured_dimension_ids are not authoritative")
        if len(set(self.scale_conflicts)) != len(self.scale_conflicts):
            object.__setattr__(self, "scale_conflicts", tuple(dict.fromkeys(self.scale_conflicts)))

        if method == "figured_dimension" and not self.figured_dimension_ids:
            raise MissingCommercialAuthorityError(
                "figured_dimension authority requires at least one figured_dimension_id"
            )
        if method == "scaled_geometry":
            scale_id = _required(self.resolved_scale_id, "resolved_scale_id")
            object.__setattr__(self, "resolved_scale_id", scale_id)
            if _norm(self.scale_status) not in _RESOLVED_SCALE_STATES:
                raise MissingCommercialAuthorityError(
                    "scaled_geometry authority requires a resolved/verified scale status"
                )
            if self.scale_conflicts:
                raise CommercialTakeoffConflictError(
                    "scaled_geometry quantity has unresolved scale conflicts"
                )

        object.__setattr__(self, "metadata", _json_copy(self.metadata))


def _metadata_identity_matches(quantity: QuantityEvidence, trace: CommercialTakeoffSourceTrace) -> None:
    """Reject explicit QuantityEvidence identity metadata that disagrees with source authority."""
    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    expected = {
        "workspace_id": trace.workspace_id,
        "project_id": trace.project_id,
        "document_id": trace.document_id,
        "source_sha256": trace.source_sha256,
        "revision_id": trace.revision_id,
    }
    for key, authoritative in expected.items():
        if key not in metadata or metadata.get(key) is None:
            continue
        candidate = metadata.get(key)
        if key == "workspace_id":
            try:
                candidate = int(candidate)
            except (TypeError, ValueError, OverflowError):
                pass
        if str(candidate).strip() != str(authoritative).strip():
            raise CommercialTakeoffConflictError(
                f"QuantityEvidence {key} does not match commercial source trace"
            )


def _validate_quantity_trace(
    quantity: QuantityEvidence,
    trace: CommercialTakeoffSourceTrace,
    authority: CommercialMeasurementAuthority,
) -> None:
    if quantity.blocking_reasons:
        raise MissingCommercialAuthorityError(
            "QuantityEvidence carries publication blockers: " + ", ".join(quantity.blocking_reasons)
        )
    status = _norm(quantity.status)
    reasons = {_norm(reason) for reason in quantity.reason_codes}
    if "conflict" in status or any("conflict" in reason for reason in reasons):
        raise CommercialTakeoffConflictError("conflicting QuantityEvidence cannot enter commercial projection")
    if not _unit_is_valid(quantity.unit):
        raise MissingCommercialAuthorityError(
            f"unit {quantity.unit!r} is not valid for the commercial takeoff projection"
        )

    missing_evidence = set(quantity.evidence_ids) - set(trace.evidence_ids)
    if missing_evidence:
        raise MissingCommercialAuthorityError(
            "commercial source trace is missing QuantityEvidence evidence IDs: "
            + ", ".join(sorted(missing_evidence))
        )
    missing_entities = set(quantity.input_entity_ids) - set(trace.canonical_entity_ids)
    if missing_entities:
        raise MissingCommercialAuthorityError(
            "commercial source trace is missing canonical entity IDs: "
            + ", ".join(sorted(missing_entities))
        )
    if not trace.evidence_ids and not trace.canonical_entity_ids:
        raise MissingCommercialAuthorityError(
            "commercial source trace requires evidence or canonical entity trace"
        )

    q_authority = _norm(quantity.authority)
    if authority.method == "figured_dimension" and "figured" not in q_authority:
        raise MissingCommercialAuthorityError(
            "figured_dimension projection requires figured QuantityEvidence authority"
        )
    if authority.method == "scaled_geometry" and not (
        "scale" in q_authority or "geometry" in q_authority
    ):
        raise MissingCommercialAuthorityError(
            "scaled_geometry projection requires scaled/geometry QuantityEvidence authority"
        )

    _metadata_identity_matches(quantity, trace)


def _projection_provenance(
    quantity: QuantityEvidence,
    trace: CommercialTakeoffSourceTrace,
    authority: CommercialMeasurementAuthority,
) -> dict[str, Any]:
    return {
        "adapter": "commercial_takeoff",
        "adapter_version": COMMERCIAL_TAKEOFF_ADAPTER_VERSION,
        "quantity": quantity.to_dict(),
        "source_trace": {
            "workspace_id": trace.workspace_id,
            "project_id": trace.project_id,
            "document_id": trace.document_id,
            "source_sha256": trace.source_sha256,
            "source_page": trace.source_page,
            "viewport_id": trace.viewport_id,
            "revision_id": trace.revision_id,
            "current_revision_id": trace.current_revision_id,
            "evidence_ids": list(trace.evidence_ids),
            "canonical_entity_ids": list(trace.canonical_entity_ids),
            "source_bbox": list(trace.source_bbox) if trace.source_bbox is not None else None,
            "metadata": _json_copy(trace.metadata),
        },
        "measurement_authority": {
            "method": authority.method,
            "figured_dimension_ids": list(authority.figured_dimension_ids),
            "resolved_scale_id": authority.resolved_scale_id,
            "scale_status": authority.scale_status,
            "scale_conflicts": list(authority.scale_conflicts),
            "metadata": _json_copy(authority.metadata),
        },
    }


def compute_commercial_projection_fingerprint(
    quantity: QuantityEvidence,
    *,
    trace: CommercialTakeoffSourceTrace,
    authority: CommercialMeasurementAuthority,
) -> str:
    """Content-bind quantity, source identity, revision and measurement authority."""
    payload = _projection_provenance(quantity, trace, authority)
    return hashlib.sha256(canonical_contract_json(payload).encode("utf-8")).hexdigest()


def quantity_evidence_to_takeoff_output_row(
    quantity: QuantityEvidence,
    *,
    trace: Optional[CommercialTakeoffSourceTrace],
    authority: Optional[CommercialMeasurementAuthority],
) -> Optional[dict[str, Any]]:
    """Project one quantity into the existing commercial takeoff-row shape.

    ``None`` is the only commercial projection for an abstention.  Non-abstained
    quantities require complete source + measurement authority.  The returned
    row is always an unreviewed AI row, so existing commercial gates must reject
    it until an estimator performs the established review transition.
    """
    if not isinstance(quantity, QuantityEvidence):
        raise TypeError("quantity must be a QuantityEvidence record")
    if quantity.abstained:
        return None
    if trace is None:
        raise MissingCommercialAuthorityError("commercial source trace is required")
    if authority is None:
        raise MissingCommercialAuthorityError("commercial measurement authority is required")

    _validate_quantity_trace(quantity, trace, authority)
    provenance = _projection_provenance(quantity, trace, authority)
    fingerprint = hashlib.sha256(canonical_contract_json(provenance).encode("utf-8")).hexdigest()

    qmeta = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    element = _clean(qmeta.get("element") or qmeta.get("description") or quantity.semantic_key)
    source_reference = (
        f"QuantityEvidence {quantity.quantity_id}; document={trace.document_id}; "
        f"sha256={trace.source_sha256}; viewport={trace.viewport_id}; revision={trace.revision_id}"
    )

    # Existing takeoff_rows fields consumed by commercial authority. Extra trace
    # fields are also canonicalized into notes/source_reference, which are bound
    # by the existing commercial-authority fingerprint after estimator review.
    return {
        "workspace_id": trace.workspace_id,
        "project_id": trace.project_id,
        "section": _clean(qmeta.get("section")),
        "element": element,
        "location": _clean(qmeta.get("location")),
        "substrate": _clean(qmeta.get("substrate")),
        "finish_system": _clean(qmeta.get("finish_system")),
        "quantity": float(quantity.value),
        "unit": quantity.unit,
        "quantity_status": "To review",
        "source_page": trace.source_page,
        "source_reference": source_reference,
        "inclusion_status": _clean(qmeta.get("inclusion_status") or "INCLUSION"),
        "confidence": float(quantity.confidence),
        "notes": canonical_contract_json(provenance),
        "row_role": _clean(qmeta.get("row_role") or "work"),
        "origin": "AI",
        "ai_baseline_quantity": float(quantity.value),
        "quantity_id": quantity.quantity_id,
        "semantic_key": quantity.semantic_key,
        "quantity_family": quantity.family,
        "quantity_authority": quantity.authority,
        "document_id": trace.document_id,
        "source_sha256": trace.source_sha256,
        "revision_id": trace.revision_id,
        "viewport_id": trace.viewport_id,
        "source_bbox": list(trace.source_bbox) if trace.source_bbox is not None else None,
        "evidence_ids": list(trace.evidence_ids),
        "canonical_entity_ids": list(trace.canonical_entity_ids),
        "measurement_method": authority.method,
        "figured_dimension_ids": list(authority.figured_dimension_ids),
        "resolved_scale_id": authority.resolved_scale_id,
        "scale_status": authority.scale_status,
        "scale_conflicts": list(authority.scale_conflicts),
        "commercial_projection_fingerprint": fingerprint,
        "commercial_projection_provenance": provenance,
    }


def quantities_to_takeoff_output_rows(
    quantities: Sequence[QuantityEvidence],
    *,
    traces_by_quantity_id: Mapping[str, CommercialTakeoffSourceTrace],
    authorities_by_quantity_id: Mapping[str, CommercialMeasurementAuthority],
) -> list[dict[str, Any]]:
    """Project a bundle, failing closed on duplicate/conflicting semantic claims."""
    seen: dict[str, tuple[float, str]] = {}
    output: list[dict[str, Any]] = []
    for quantity in quantities:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("quantities must contain only QuantityEvidence records")
        row = quantity_evidence_to_takeoff_output_row(
            quantity,
            trace=traces_by_quantity_id.get(quantity.quantity_id),
            authority=authorities_by_quantity_id.get(quantity.quantity_id),
        )
        if row is None:
            continue
        key = quantity.semantic_key
        claim = (float(quantity.value), _norm(quantity.unit))
        if key in seen:
            prior = seen[key]
            detail = "conflicting" if prior != claim else "duplicate"
            raise CommercialTakeoffConflictError(
                f"{detail} emitted commercial quantities claim semantic key {key!r}"
            )
        seen[key] = claim
        output.append(row)
    return output


def existing_commercial_gate_results(row: Mapping[str, Any]) -> dict[str, tuple[bool, str]]:
    """Run the projected row through the existing commercial gates, unchanged."""
    from pb_takeoff_authority_v164 import (
        is_jobhub_eligible_row,
        takeoff_row_pricing_authority,
        takeoff_row_publishability,
    )

    return {
        "publishability": takeoff_row_publishability(row),
        "pricing": takeoff_row_pricing_authority(row),
        "jobhub": is_jobhub_eligible_row(row),
    }
