"""Project graph QuantityEvidence into the existing commercial takeoff authority.

This adapter does not invent a second commercial output model.  It only gathers
already-present QuantityEvidence / caller traces and hands a complete argument
set to ``create_takeoff_output_row``.  Missing authority stays missing.

High extraction confidence is never treated as estimator approval.  Abstentions
emit no ``TakeoffOutputRow`` (including no zero-valued row).  Duplicate
semantic keys fail closed.  Source SHA / project mismatches refuse projection
into the wrong commercial context.

The adapter is gold-free: it has no benchmark IDs, expected quantities,
mappings, tolerances, or holdout inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from typing import Any, Mapping, Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus
from pb_migration_contracts import QuantityEvidence, canonical_contract_json
from pb_page_scale_calibration_authority import ScaleCalibrationStatus
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    create_takeoff_output_row,
)


COMMERCIAL_ADAPTER_VERSION = "1.0.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_KNOWN_COMMERCIAL_UNITS = {
    "ea",
    "each",
    "no",
    "nr",
    "m",
    "lm",
    "m2",
    "m²",
    "sqm",
    "m3",
    "m³",
}

_UNRELIABLE_SCALE_STATUSES = {
    ScaleCalibrationStatus.UNKNOWN.value,
    ScaleCalibrationStatus.CONFLICTING.value,
    ScaleCalibrationStatus.MANUAL_REQUIRED.value,
    ScaleCalibrationStatus.BLOCKED.value,
}

_AUTHORITY_TO_SOURCE_TYPE = {
    TakeoffSourceType.DOCUMENTED_DIMENSION.value: TakeoffSourceType.DOCUMENTED_DIMENSION,
    TakeoffSourceType.SCHEDULE_EXTRACTED.value: TakeoffSourceType.SCHEDULE_EXTRACTED,
    TakeoffSourceType.PDF_SCALED.value: TakeoffSourceType.PDF_SCALED,
    TakeoffSourceType.AI_DETECTED.value: TakeoffSourceType.AI_DETECTED,
    TakeoffSourceType.MODEL_DERIVED.value: TakeoffSourceType.MODEL_DERIVED,
    TakeoffSourceType.USER_CORRECTED.value: TakeoffSourceType.USER_CORRECTED,
    TakeoffSourceType.USER_APPROVED.value: TakeoffSourceType.USER_APPROVED,
    TakeoffSourceType.EXCLUDED.value: TakeoffSourceType.EXCLUDED,
    TakeoffSourceType.REFERENCE_ONLY.value: TakeoffSourceType.REFERENCE_ONLY,
    TakeoffSourceType.BLOCKED.value: TakeoffSourceType.BLOCKED,
    TakeoffSourceType.MANUAL.value: TakeoffSourceType.MANUAL,
}

_KNOWN_AUTHORITY_STATUSES = {status.value for status in AuthorityStatus}


class CommercialProjectionAmbiguityError(RuntimeError):
    """Raised when more than one emitted quantity claims one semantic key."""


class CommercialProjectionIdentityError(RuntimeError):
    """Raised when a quantity's project/source identity disagrees with the target context."""


def _json_copy(value: Any) -> Any:
    return json.loads(canonical_contract_json(value))


def _require_sha256(value: str, field_name: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(f"{field_name} must be a 64-character lowercase SHA-256 hex digest")
    return digest


def _optional_sha256(value: Any, field_name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_sha256(str(value), field_name)


def _metadata_get(quantity: QuantityEvidence, key: str, default: Any = None) -> Any:
    metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
    return metadata.get(key, default)


def commercial_unit_is_known(unit: str) -> bool:
    clean = str(unit or "").strip()
    if not clean:
        return False
    return clean.lower().replace(" ", "") in {item.lower() for item in _KNOWN_COMMERCIAL_UNITS}


@dataclass(frozen=True)
class CommercialProjectionContext:
    """Target commercial project/document binding. Never inferred from gold."""

    project_id: str
    source_sha256: str
    current_revision_hash: Optional[str] = None
    current_scale_revision_id: Optional[str] = None

    def __post_init__(self) -> None:
        project_id = str(self.project_id or "").strip()
        if not project_id:
            raise ValueError("project_id must be a non-empty string")
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "source_sha256", _require_sha256(self.source_sha256, "source_sha256"))
        current_revision = str(self.current_revision_hash or "").strip() or None
        object.__setattr__(self, "current_revision_hash", current_revision)
        scale_revision = str(self.current_scale_revision_id or "").strip() or None
        object.__setattr__(self, "current_scale_revision_id", scale_revision)


@dataclass(frozen=True)
class CommercialSourceTrace:
    """Optional explicit commercial traces supplied by an evidence resolver.

    The adapter copies these onto existing ``TakeoffOutputRow`` fields.  It does
    not invent a parallel provenance record.
    """

    source_page: Optional[int] = None
    source_sheet: Optional[str] = None
    geometry_ref: Optional[str] = None
    scale_id: Optional[str] = None
    dimension_text_id: Optional[str] = None
    viewport_id: Optional[str] = None
    document_id: Optional[str] = None
    page_id: Optional[str] = None
    revision_hash: Optional[str] = None
    project_id: Optional[str] = None
    source_sha256: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    scale_calibration_status: Optional[str] = None
    scale_revision_id: Optional[str] = None
    source_type: Optional[str] = None
    description: Optional[str] = None
    trade: Optional[str] = None
    measurement_conflict: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_page is not None:
            if isinstance(self.source_page, bool) or int(self.source_page) <= 0:
                raise ValueError("source_page must be a positive 1-based integer when supplied")
            object.__setattr__(self, "source_page", int(self.source_page))
        if self.source_sha256 is not None:
            object.__setattr__(
                self,
                "source_sha256",
                _optional_sha256(self.source_sha256, "source_sha256"),
            )
        object.__setattr__(self, "metadata", _json_copy(self.metadata))


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _resolve_source_page(
    quantity: QuantityEvidence,
    trace: Optional[CommercialSourceTrace],
) -> tuple[Optional[int], list[str]]:
    blockers: list[str] = []
    raw = None if trace is None else trace.source_page
    if raw is None:
        raw = _metadata_get(quantity, "source_page")
    if raw is None or raw == "":
        return None, blockers
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        blockers.append("invalid source page")
        return None, blockers
    try:
        page = int(raw)
    except (TypeError, ValueError):
        blockers.append("invalid source page")
        return None, blockers
    if page <= 0:
        blockers.append("invalid source page")
        return None, blockers
    return page, blockers


def _resolve_source_type(
    quantity: QuantityEvidence,
    trace: Optional[CommercialSourceTrace],
) -> tuple[TakeoffSourceType, list[str]]:
    raw = _first_text(
        None if trace is None else trace.source_type,
        _metadata_get(quantity, "source_type"),
        quantity.authority,
    )
    if raw is None:
        return TakeoffSourceType.BLOCKED, ["unresolved measurement authority"]
    key = raw.strip().lower()
    mapped = _AUTHORITY_TO_SOURCE_TYPE.get(key)
    if mapped is None:
        return TakeoffSourceType.BLOCKED, [f"unresolved measurement authority: {raw!r}"]
    return mapped, []


def _bind_identity(
    quantity: QuantityEvidence,
    context: CommercialProjectionContext,
    trace: Optional[CommercialSourceTrace],
) -> tuple[Optional[bool], list[str]]:
    quantity_project = _first_text(
        None if trace is None else trace.project_id,
        _metadata_get(quantity, "project_id"),
    )
    quantity_sha = _first_text(
        None if trace is None else trace.source_sha256,
        _metadata_get(quantity, "source_sha256"),
    )
    if quantity_project and quantity_project != context.project_id:
        raise CommercialProjectionIdentityError(
            f"quantity {quantity.quantity_id!r} project {quantity_project!r} "
            f"does not match context project {context.project_id!r}"
        )
    if quantity_sha:
        try:
            quantity_sha = _require_sha256(quantity_sha, "quantity source_sha256")
        except ValueError as exc:
            raise CommercialProjectionIdentityError(str(exc)) from exc
        if quantity_sha != context.source_sha256:
            raise CommercialProjectionIdentityError(
                f"quantity {quantity.quantity_id!r} source SHA does not match the target document"
            )
        return True, []
    if quantity_project == context.project_id:
        return None, ["project identity not confirmed by source SHA"]
    return None, ["project identity not confirmed"]


def quantity_evidence_to_takeoff_row(
    quantity: QuantityEvidence,
    context: CommercialProjectionContext,
    *,
    trace: Optional[CommercialSourceTrace] = None,
) -> Optional[TakeoffOutputRow]:
    """Project one quantity through existing commercial authority gates.

    Abstentions emit no row.  The factory is never asked to invent a zero.
    """
    if not isinstance(quantity, QuantityEvidence):
        raise TypeError("quantity must be a QuantityEvidence record")
    if not isinstance(context, CommercialProjectionContext):
        raise TypeError("context must be a CommercialProjectionContext")
    if quantity.abstained:
        return None

    extra_blockers: list[str] = []
    extra_warnings: list[str] = []

    identity_confirmed, identity_blockers = _bind_identity(quantity, context, trace)
    extra_blockers.extend(identity_blockers)

    source_type, source_type_blockers = _resolve_source_type(quantity, trace)
    extra_blockers.extend(source_type_blockers)

    source_page, page_blockers = _resolve_source_page(quantity, trace)
    extra_blockers.extend(page_blockers)

    if not commercial_unit_is_known(quantity.unit):
        extra_blockers.append("incompatible or unknown unit")

    if not quantity.evidence_ids:
        extra_blockers.append("missing evidence reference")
    if not quantity.input_entity_ids:
        extra_blockers.append("missing canonical entity reference")

    source_sheet = _first_text(
        None if trace is None else trace.source_sheet,
        _metadata_get(quantity, "source_sheet"),
    )
    viewport_id = _first_text(
        None if trace is None else trace.viewport_id,
        _metadata_get(quantity, "viewport_id"),
    )
    document_id = _first_text(
        None if trace is None else trace.document_id,
        _metadata_get(quantity, "document_id"),
    )
    page_id = _first_text(
        None if trace is None else trace.page_id,
        _metadata_get(quantity, "page_id"),
    )
    if source_page is None and not source_sheet and not page_id:
        extra_blockers.append("missing source page")

    dimension_text_id = _first_text(
        None if trace is None else trace.dimension_text_id,
        _metadata_get(quantity, "dimension_text_id"),
        _metadata_get(quantity, "figured_dimension_id"),
    )
    scale_id = _first_text(
        None if trace is None else trace.scale_id,
        _metadata_get(quantity, "scale_id"),
    )
    scale_status = _first_text(
        None if trace is None else trace.scale_calibration_status,
        _metadata_get(quantity, "scale_calibration_status"),
    )
    scale_revision = _first_text(
        None if trace is None else trace.scale_revision_id,
        _metadata_get(quantity, "scale_revision_id"),
    )
    geometry_ref = _first_text(
        None if trace is None else trace.geometry_ref,
        _metadata_get(quantity, "geometry_ref"),
        quantity.input_entity_ids[0] if quantity.input_entity_ids else None,
    )
    revision_hash = _first_text(
        None if trace is None else trace.revision_hash,
        _metadata_get(quantity, "revision_hash"),
    )
    approved_by = _first_text(
        None if trace is None else trace.approved_by,
        _metadata_get(quantity, "approved_by"),
    )
    approved_at = _first_text(
        None if trace is None else trace.approved_at,
        _metadata_get(quantity, "approved_at"),
    )
    # Confidence never becomes estimator attribution.
    if approved_by and approved_by.lower() in {"auto", "model", "extractor", "engine"}:
        extra_blockers.append("automated attribution is not estimator approval")
        approved_by = None
        approved_at = None

    measurement_conflict = bool(
        (trace.measurement_conflict if trace is not None else False)
        or _metadata_get(quantity, "figured_scaled_conflict")
        or _metadata_get(quantity, "measurement_authority_conflict")
        or "figured_scaled_conflict" in quantity.reason_codes
        or "measurement_authority_conflict" in quantity.reason_codes
    )
    if measurement_conflict:
        extra_blockers.append("figured/scaled measurement conflict")

    if source_type == TakeoffSourceType.PDF_SCALED and not scale_id:
        extra_blockers.append("missing scale when scale is required")
    if scale_status in _UNRELIABLE_SCALE_STATUSES:
        extra_blockers.append(f"unreliable scale status: {scale_status}")
    if (
        scale_revision
        and context.current_scale_revision_id
        and scale_revision != context.current_scale_revision_id
    ):
        extra_blockers.append("stale scale")
        scale_status = ScaleCalibrationStatus.BLOCKED.value

    if revision_hash is None:
        extra_blockers.append("unknown revision")
    if (
        revision_hash
        and context.current_revision_hash
        and revision_hash != context.current_revision_hash
    ):
        extra_blockers.append("stale revision")

    provenance_sha = _first_text(
        None if trace is None else trace.source_sha256,
        _metadata_get(quantity, "source_sha256"),
    )
    if provenance_sha:
        try:
            _require_sha256(provenance_sha, "provenance source_sha256")
        except ValueError:
            extra_blockers.append("corrupted provenance")
    if document_id is None and viewport_id is None and page_id is None and source_page is None:
        extra_blockers.append("corrupted provenance")

    description = _first_text(
        None if trace is None else trace.description,
        _metadata_get(quantity, "description"),
        quantity.semantic_key,
    ) or quantity.semantic_key
    trade = _first_text(
        None if trace is None else trace.trade,
        _metadata_get(quantity, "trade"),
        _metadata_get(quantity, "trade_type"),
        quantity.family,
    ) or quantity.family

    authority_status = str(quantity.status or "").strip().lower() or None
    if authority_status == AuthorityStatus.REVIEW_REQUIRED.value:
        extra_blockers.append("explicit review required")
    if authority_status is not None and authority_status not in _KNOWN_AUTHORITY_STATUSES:
        extra_blockers.append(f"unresolved measurement authority: {authority_status!r}")
        authority_status = AuthorityStatus.BLOCKED.value

    if extra_blockers and authority_status in {None, AuthorityStatus.FIRM.value}:
        if authority_status == AuthorityStatus.FIRM.value:
            extra_warnings.append("firm quantity status demoted; commercial gates are incomplete")
        authority_status = AuthorityStatus.BLOCKED.value

    return create_takeoff_output_row(
        quantity_id=quantity.quantity_id,
        description=description,
        value=float(quantity.value),
        unit=str(quantity.unit),
        trade=trade,
        source_type=source_type,
        authority_status=authority_status,
        confidence=float(quantity.confidence),
        source_page=source_page,
        source_sheet=source_sheet,
        geometry_ref=geometry_ref,
        scale_id=scale_id,
        dimension_text_id=dimension_text_id,
        benchmark_status=None,
        warnings=extra_warnings,
        blocking_reasons=extra_blockers,
        approved_by=approved_by,
        approved_at=approved_at,
        revision_hash=revision_hash,
        current_revision_hash=context.current_revision_hash,
        project_identity_confirmed=identity_confirmed,
        scale_calibration_status=scale_status,
        allow_zero=True,
    )


def quantity_evidence_to_takeoff_output_row(
    quantity: QuantityEvidence,
    context: CommercialProjectionContext,
    *,
    trace: Optional[CommercialSourceTrace] = None,
) -> Optional[TakeoffOutputRow]:
    """M5 contract name used by the migration control plane."""
    return quantity_evidence_to_takeoff_row(quantity, context, trace=trace)


def quantities_to_takeoff_output_rows(
    quantities: Sequence[QuantityEvidence],
    context: CommercialProjectionContext,
    *,
    traces_by_quantity_id: Optional[Mapping[str, CommercialSourceTrace]] = None,
) -> list[TakeoffOutputRow]:
    """M5 contract name used by the migration control plane."""
    return quantities_to_takeoff_rows(
        quantities,
        context,
        traces_by_quantity_id=traces_by_quantity_id,
    )


CommercialTakeoffSourceTrace = CommercialSourceTrace


def quantities_to_takeoff_rows(
    quantities: Sequence[QuantityEvidence],
    context: CommercialProjectionContext,
    *,
    traces_by_quantity_id: Optional[Mapping[str, CommercialSourceTrace]] = None,
) -> list[TakeoffOutputRow]:
    """Project a quantity bundle, failing closed on duplicate emitted semantic keys."""
    traces = traces_by_quantity_id or {}
    seen_semantic_keys: set[str] = set()
    rows: list[TakeoffOutputRow] = []
    for quantity in quantities:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("quantities must contain only QuantityEvidence records")
        row = quantity_evidence_to_takeoff_row(
            quantity,
            context,
            trace=traces.get(quantity.quantity_id),
        )
        if row is None:
            continue
        if quantity.semantic_key in seen_semantic_keys:
            raise CommercialProjectionAmbiguityError(
                f"multiple emitted quantities claim semantic key {quantity.semantic_key!r}"
            )
        seen_semantic_keys.add(quantity.semantic_key)
        rows.append(row)
    return rows


def _revision_status(
    revision_hash: Optional[str],
    current_revision_hash: Optional[str],
) -> str:
    if not revision_hash:
        return "unknown"
    if current_revision_hash and revision_hash != current_revision_hash:
        return "stale"
    if current_revision_hash and revision_hash == current_revision_hash:
        return "current"
    return "present"


def _approval_status(row: Optional[TakeoffOutputRow], quantity: QuantityEvidence) -> str:
    if row is not None and row.approved_by:
        return "estimator_approved"
    if quantity.status == AuthorityStatus.REVIEW_REQUIRED.value:
        return "review_required"
    return "approval_absent"


def quantity_evidence_to_commercial_diagnostic(
    quantity: QuantityEvidence,
    context: CommercialProjectionContext,
    *,
    trace: Optional[CommercialSourceTrace] = None,
) -> dict[str, Any]:
    """Shadow/debug view of commercial projection. Never production-authoritative."""
    if quantity.abstained:
        return {
            "quantity_id": quantity.quantity_id,
            "family": quantity.family,
            "semantic_key": quantity.semantic_key,
            "value": None,
            "unit": quantity.unit,
            "commercial_row_created": False,
            "publishable": False,
            "review_required": True,
            "blockers": list(quantity.blocking_reasons),
            "authority": quantity.authority,
            "source_trace": {
                "quantity_id": quantity.quantity_id,
                "input_entity_ids": list(quantity.input_entity_ids),
                "evidence_ids": list(quantity.evidence_ids),
                "viewport_id": _metadata_get(quantity, "viewport_id"),
                "page_id": _metadata_get(quantity, "page_id"),
                "source_page": _metadata_get(quantity, "source_page"),
                "document_id": _metadata_get(quantity, "document_id"),
                "source_sha256": context.source_sha256,
            },
            "scale_status": _metadata_get(quantity, "scale_calibration_status"),
            "revision_status": "unknown",
            "approval_status": "approval_absent",
            "authoritative": False,
            "adapter_version": COMMERCIAL_ADAPTER_VERSION,
        }

    row = quantity_evidence_to_takeoff_row(quantity, context, trace=trace)
    created = row is not None
    return {
        "quantity_id": quantity.quantity_id,
        "family": quantity.family,
        "semantic_key": quantity.semantic_key,
        "value": None if row is None else row.value,
        "unit": quantity.unit,
        "commercial_row_created": created,
        "publishable": bool(row.is_publishable) if row is not None else False,
        "review_required": (
            True
            if row is None
            else row.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
            or any("review" in reason.lower() for reason in row.blocking_reasons)
        ),
        "blockers": [] if row is None else list(row.blocking_reasons),
        "authority": None if row is None else row.authority_status,
        "source_type": None if row is None else row.source_type,
        "source_trace": {
            "quantity_id": quantity.quantity_id,
            "input_entity_ids": list(quantity.input_entity_ids),
            "evidence_ids": list(quantity.evidence_ids),
            "geometry_ref": None if row is None else row.geometry_ref,
            "viewport_id": _first_text(
                None if trace is None else trace.viewport_id,
                _metadata_get(quantity, "viewport_id"),
            ),
            "page_id": _first_text(
                None if trace is None else trace.page_id,
                _metadata_get(quantity, "page_id"),
            ),
            "source_page": None if row is None else row.source_page,
            "source_sheet": None if row is None else row.source_sheet,
            "document_id": _first_text(
                None if trace is None else trace.document_id,
                _metadata_get(quantity, "document_id"),
            ),
            "dimension_text_id": None if row is None else row.dimension_text_id,
            "scale_id": None if row is None else row.scale_id,
            "source_sha256": context.source_sha256,
            "project_id": context.project_id,
        },
        "scale_status": None if row is None else (
            _first_text(
                None if trace is None else trace.scale_calibration_status,
                _metadata_get(quantity, "scale_calibration_status"),
            )
        ),
        "revision_status": _revision_status(
            None if row is None else row.revision_hash,
            context.current_revision_hash,
        ),
        "approval_status": _approval_status(row, quantity),
        "authoritative": False,
        "adapter_version": COMMERCIAL_ADAPTER_VERSION,
        "takeoff_row": None if row is None else row.to_dict(),
    }


def quantities_to_commercial_diagnostics(
    quantities: Sequence[QuantityEvidence],
    context: CommercialProjectionContext,
    *,
    traces_by_quantity_id: Optional[Mapping[str, CommercialSourceTrace]] = None,
) -> list[dict[str, Any]]:
    """Diagnostic commercial projection for shadow/debug. Does not score benchmarks."""
    traces = traces_by_quantity_id or {}
    # Duplicate detection still fail-closes: diagnostics must not hide conflicts.
    quantities_to_takeoff_rows(quantities, context, traces_by_quantity_id=traces)
    return [
        quantity_evidence_to_commercial_diagnostic(
            quantity,
            context,
            trace=traces.get(quantity.quantity_id),
        )
        for quantity in quantities
    ]


def shadow_commercial_projection_artifact(
    quantities: Sequence[QuantityEvidence],
    context: CommercialProjectionContext,
    *,
    traces_by_quantity_id: Optional[Mapping[str, CommercialSourceTrace]] = None,
) -> dict[str, Any]:
    """Optional shadow payload: QuantityEvidence → commercial state, not authoritative."""
    return {
        "schema_version": COMMERCIAL_ADAPTER_VERSION,
        "producer": "pb_quantity_commercial_adapter.shadow_commercial_projection_artifact",
        "authoritative": False,
        "influences_benchmark_scoring": False,
        "project_id": context.project_id,
        "source_sha256": context.source_sha256,
        "diagnostics": quantities_to_commercial_diagnostics(
            quantities,
            context,
            traces_by_quantity_id=traces_by_quantity_id,
        ),
    }
