"""Shared commercial-authority policy for PlanReader take-off rows.

The legacy take-off table contains rows from several producers.  Ordinary
estimator-authored rows retain their existing behaviour, but 3D model-surface
rows are derived geometry and therefore require explicit, attributable review
before they can enter pricing, quotation, or JobHub publication paths.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from typing import Any, Dict, Mapping, Tuple


MODEL_SURFACE_ROLE = "model_surface"
MODEL_SURFACE_SOURCE_PREFIX = "pb 3d surface editor "
FLOOR_REFERENCE_ROLE = "floor_area"
AI_DRAFT_ORIGIN = "ai"
AI_REVIEWED_ORIGIN = "ai_reviewed"

AUTHORITY_REVIEW_REQUIRED = "REVIEW_REQUIRED"
AUTHORITY_APPROVED = "APPROVED"

AUTHORITY_STATUS_FIELD = "commercial_authority_status"
AUTHORITY_SOURCE_FIELD = "commercial_authority_source"
AUTHORITY_REVIEWED_BY_FIELD = "commercial_authority_reviewed_by"
AUTHORITY_REVIEWED_AT_FIELD = "commercial_authority_reviewed_at"
AUTHORITY_FINGERPRINT_FIELD = "commercial_authority_fingerprint"

_EXCLUDED_SCOPE_VALUES = {"exclude", "excluded", "exclusion"}
_CLARIFICATION_SCOPE_VALUES = {
    "clarification",
    "clarification_only",
    "rfi",
    "query",
    "to_clarify",
    "clarify",
    "unresolved",
    "disputed",
}

_PROVISIONAL_STATUS_VALUES = {
    "provisional",
    "provisional_measured",
    "to_measure",
    "to_review",
    "unmeasured",
    "not_applicable",
    "approximate",
    "estimated",
}

_PROVISIONAL_INCLUSION_VALUES = {
    "provisional",
    "provisional_sum",
    "provisional_item",
    "prov",
    "separate_item",
    "separate",
    "optional",
    "variation",
    "client_variation",
    "allowance_only",
    "tbd",
    "pending",
    "unconfirmed",
}

_INCLUDED_SCOPE_VALUES = {
    "",
    "inclusion",
    "include",
    "included",
    "base_contract",
    "base_scope",
}

_AI_REVIEWED_CONFIDENCE_VALUES = {
    "approved",
    "checked",
    "confirmed",
    "estimator_verified",
    "manual_verified",
    "manually_verified",
    "reviewed",
    "verified",
}

_AI_CONFIRMED_QUANTITY_STATUS_VALUES = {"allowance", "mapped", "measured"}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _normalised(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def is_model_surface_row(row: Mapping[str, Any]) -> bool:
    role_matches = _normalised(row.get("row_role")) == MODEL_SURFACE_ROLE
    norm_source = _normalised(row.get("source_reference"))
    source_matches = (
        norm_source.startswith("pb_3d_surface_editor")
        or _text(row.get("source_reference")).lower().startswith(MODEL_SURFACE_SOURCE_PREFIX)
        or "3d_surface_editor" in norm_source
    )
    page_matches = _normalised(row.get("source_page")) in {"3d_model", "3d", "model_surface"}
    # Sticky provenance: once a row carries model authority provenance or fingerprint,
    # it cannot be laundered into an ordinary row by mutating or erasing row_role.
    # Sentinels ('nan', 'none', 'null', '') do not count as authority markers.
    sentinels = {"", "nan", "none", "null"}
    authority_markers = bool(
        (_text(row.get(AUTHORITY_FINGERPRINT_FIELD)).lower() not in sentinels)
        or (_text(row.get(AUTHORITY_SOURCE_FIELD)).lower() not in sentinels)
        or (_normalised(row.get(AUTHORITY_STATUS_FIELD)) == AUTHORITY_APPROVED.lower())
    )
    return role_matches or source_matches or page_matches or authority_markers


def is_floor_reference_row(row: Mapping[str, Any]) -> bool:
    return _normalised(row.get("row_role")) == FLOOR_REFERENCE_ROLE


def is_excluded_takeoff_row(row: Mapping[str, Any]) -> bool:
    """Recognise explicit exclusion in either legacy scope/status field."""
    return (
        _normalised(row.get("inclusion_status")) in _EXCLUDED_SCOPE_VALUES
        or _normalised(row.get("quantity_status")) in _EXCLUDED_SCOPE_VALUES
    )


def is_ai_takeoff_row(row: Mapping[str, Any]) -> bool:
    """Recognise AI-derived quantities even after a legacy partial round-trip.

    ``origin`` and ``ai_baseline_quantity`` are the canonical persisted markers.
    Older rows may only retain the explanatory text added by the production AI
    importer, so those exact legacy markers remain sticky as a fail-closed
    compatibility boundary.
    """
    if _normalised(row.get("origin")) in {AI_DRAFT_ORIGIN, AI_REVIEWED_ORIGIN}:
        return True

    baseline = row.get("ai_baseline_quantity")
    if baseline is not None:
        if not (isinstance(baseline, float) and math.isnan(baseline)):
            if _text(baseline).lower() not in {"", "nan", "none", "null"}:
                return True

    provenance_text = " ".join(
        _text(row.get(field)).lower()
        for field in ("source_reference", "notes")
    )
    # Strip explicit no-ai markers so rules-based no-AI generators are not misidentified as AI drafts
    cleaned_provenance = re.sub(r"\bno[- ]ai\b", "", provenance_text)
    return any(
        re.search(rf"\b{re.escape(marker)}\b", cleaned_provenance)
        for marker in ("ai draft", "ai plan review", "ai-generated", "ai generated")
    )


def ai_takeoff_authority(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Require explicit estimator confirmation before AI quantities are commercial."""
    if not is_ai_takeoff_row(row):
        return True, "NOT_AI_DRAFT"

    if _normalised(row.get("origin")) != AI_REVIEWED_ORIGIN:
        return False, "AI draft has not been explicitly reviewed by an estimator"

    status = _normalised(row.get("quantity_status"))
    if status not in _AI_CONFIRMED_QUANTITY_STATUS_VALUES:
        return False, "AI draft quantity has not been explicitly confirmed by an estimator"

    confidence = _normalised(row.get("confidence"))
    if confidence not in _AI_REVIEWED_CONFIDENCE_VALUES:
        return False, "AI draft has no explicit estimator verification"

    return True, "ESTIMATOR_VERIFIED"


def prepare_ai_takeoff_editor_save(
    prior: Mapping[str, Any], edited: Mapping[str, Any]
) -> Dict[str, Any]:
    """Preserve AI provenance and make review mutation-sensitive.

    A legacy AI row cannot self-authorise trusted-looking model fields. Likewise,
    an already reviewed AI row cannot carry that review across a consequential
    commercial edit unless the estimator explicitly changes quantity status or
    confidence as part of the same save. Unchanged reviewed rows remain reviewed.
    """
    merged = {**dict(prior), **dict(edited)}
    if not (is_ai_takeoff_row(prior) or is_ai_takeoff_row(merged)):
        return merged

    status = _normalised(merged.get("quantity_status"))
    confidence = _normalised(merged.get("confidence"))
    prior_origin = _normalised(prior.get("origin"))
    review_fields_changed = (
        status != _normalised(prior.get("quantity_status"))
        or confidence != _normalised(prior.get("confidence"))
    )
    bound_state_changed = any(
        _canonical_value(prior.get(field)) != _canonical_value(merged.get(field))
        for field in _AUTHORITY_BOUND_FIELDS
    )
    valid_review_fields = (
        status in _AI_CONFIRMED_QUANTITY_STATUS_VALUES
        and confidence in _AI_REVIEWED_CONFIDENCE_VALUES
    )
    explicit_review = valid_review_fields and (
        review_fields_changed
        or (prior_origin == AI_REVIEWED_ORIGIN and not bound_state_changed)
    )
    merged["origin"] = "AI_REVIEWED" if explicit_review else "AI"
    return merged


def takeoff_row_scope_authority(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Require resolved, commercially active scope before pricing or publication."""
    if is_excluded_takeoff_row(row):
        return False, "EXCLUDED"

    inclusion = _normalised(row.get("inclusion_status"))
    if inclusion in _CLARIFICATION_SCOPE_VALUES:
        return False, "CLARIFICATION"
    if inclusion in _PROVISIONAL_INCLUSION_VALUES:
        return False, "PROVISIONAL"
    if inclusion not in _INCLUDED_SCOPE_VALUES:
        return False, "UNRESOLVED_SCOPE"

    quantity_status = _normalised(row.get("quantity_status"))
    if quantity_status in _PROVISIONAL_STATUS_VALUES:
        return False, "PROVISIONAL"

    from pb_mapped_zone_geometry_authority import is_geometric_approximation
    if is_geometric_approximation(row):
        return False, "PROVISIONAL"

    qty_raw = row.get("quantity")
    if qty_raw is not None:
        try:
            qty = float(qty_raw)
            if math.isfinite(qty) and qty < 0.0:
                return False, "NEGATIVE_QUANTITY"
        except (TypeError, ValueError):
            pass

    return True, "SCOPE_AUTHORISED"


def compute_takeoff_row_fingerprint(row: Mapping[str, Any]) -> str:
    """Bind a takeoff row approval to every consequential field."""
    return compute_model_surface_authority_fingerprint(row)


def is_commercial_floor_reference_row(row: Mapping[str, Any]) -> bool:
    """Return whether a floor reference has resolved scope and model authority."""
    if not is_floor_reference_row(row):
        return False
    scope_approved, _ = takeoff_row_scope_authority(row)
    if not scope_approved:
        return False
    ai_approved, _ = ai_takeoff_authority(row)
    if not ai_approved:
        return False
    if is_model_surface_row(row):
        approved, _ = model_surface_authority(row)
        if not approved:
            return False
    if "quantity" in row and row.get("quantity") is not None:
        try:
            qty = float(row.get("quantity"))
            if math.isfinite(qty) and qty <= 0.0:
                return False
        except (TypeError, ValueError):
            return False
    return True


_AUTHORITY_BOUND_FIELDS = (
    "workspace_id",
    "section",
    "element",
    "location",
    "substrate",
    "finish_system",
    "quantity",
    "unit",
    "quantity_status",
    "source_page",
    "source_reference",
    "inclusion_status",
    "coats",
    "coverage_m2_per_litre",
    "productivity_m2_per_hour",
    "rate_per_unit",
    "confidence",
    "notes",
    "row_role",
    AUTHORITY_SOURCE_FIELD,
    AUTHORITY_REVIEWED_BY_FIELD,
    AUTHORITY_REVIEWED_AT_FIELD,
)


def _canonical_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return _text(value)


def compute_model_surface_authority_fingerprint(row: Mapping[str, Any]) -> str:
    """Bind a model-surface approval to every consequential row field."""
    payload = {
        field: _canonical_value(row.get(field)) for field in _AUTHORITY_BOUND_FIELDS
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def approve_model_surface_row(
    row: Mapping[str, Any], *, source: Any, reviewed_by: Any, reviewed_at: Any
) -> Dict[str, Any]:
    """Create a complete approval record for the current immutable row state."""
    if not is_model_surface_row(row):
        raise ValueError("Only a 3D model-surface row can receive model authority.")
    workspace_id = row.get("workspace_id")
    if isinstance(workspace_id, bool):
        raise ValueError("A positive workspace identity is required for model authority.")
    try:
        valid_workspace_id = int(workspace_id) > 0
    except (TypeError, ValueError, OverflowError):
        valid_workspace_id = False
    if not valid_workspace_id:
        raise ValueError("A positive workspace identity is required for model authority.")
    source_text = _text(source)
    reviewer_text = _text(reviewed_by)
    reviewed_at_text = _text(reviewed_at)
    sentinels = {"nan", "none", "null"}
    if (
        not source_text
        or _normalised(source_text) in sentinels
        or not reviewer_text
        or _normalised(reviewer_text) in sentinels
        or not reviewed_at_text
        or _normalised(reviewed_at_text) in sentinels
    ):
        raise ValueError("Source evidence, reviewer identity, and review timestamp are required.")
    approved = dict(row)
    approved["workspace_id"] = int(workspace_id)
    approved[AUTHORITY_STATUS_FIELD] = AUTHORITY_APPROVED
    approved[AUTHORITY_SOURCE_FIELD] = source_text
    approved[AUTHORITY_REVIEWED_BY_FIELD] = reviewer_text
    approved[AUTHORITY_REVIEWED_AT_FIELD] = reviewed_at_text
    approved[AUTHORITY_FINGERPRINT_FIELD] = compute_model_surface_authority_fingerprint(
        approved
    )
    return approved


def model_surface_authority(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Return whether a model surface has a complete row-level approval record.

    An approval label on its own is not authority.  The source evidence,
    reviewer identity, and review timestamp must all be present as well.
    """
    if not is_model_surface_row(row):
        return True, "NOT_MODEL_SURFACE"

    # Status must be a string strictly matching 'APPROVED' (case-insensitive, whitespace-trimmed)
    raw_status = row.get(AUTHORITY_STATUS_FIELD)
    if not isinstance(raw_status, str):
        return False, "3D model surface has not received commercial approval"
    if raw_status.strip().upper() != AUTHORITY_APPROVED:
        return False, "3D model surface has not received commercial approval"

    # Workspace binding: row must carry a valid positive workspace identity
    workspace_id = row.get("workspace_id")
    if isinstance(workspace_id, bool):
        return False, "3D model surface approval requires a positive workspace identity"
    try:
        valid_workspace_id = int(workspace_id) > 0
    except (TypeError, ValueError, OverflowError):
        valid_workspace_id = False
    if not valid_workspace_id:
        return False, "3D model surface approval requires a positive workspace identity"

    # Provenance fields must be non-empty and not sentinel strings
    sentinels = {"nan", "none", "null"}
    source_val = _text(row.get(AUTHORITY_SOURCE_FIELD))
    if not source_val or _normalised(source_val) in sentinels:
        return False, "3D model surface approval has no source evidence reference"

    reviewer_val = _text(row.get(AUTHORITY_REVIEWED_BY_FIELD))
    if not reviewer_val or _normalised(reviewer_val) in sentinels:
        return False, "3D model surface approval has no reviewer identity"

    reviewed_at_val = _text(row.get(AUTHORITY_REVIEWED_AT_FIELD))
    if not reviewed_at_val or _normalised(reviewed_at_val) in sentinels:
        return False, "3D model surface approval has no review timestamp"

    fingerprint = _text(row.get(AUTHORITY_FINGERPRINT_FIELD))
    expected = compute_model_surface_authority_fingerprint(row)
    if not fingerprint or not hmac.compare_digest(fingerprint, expected):
        return False, "3D model surface approval no longer matches the current row"
    return True, "APPROVED"


def takeoff_row_publishability(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Return whether a row can enter commercial preflight review."""
    if is_excluded_takeoff_row(row):
        return False, "EXCLUDED"
    if is_floor_reference_row(row):
        return False, "FLOOR_REFERENCE"
    ai_approved, ai_reason = ai_takeoff_authority(row)
    if not ai_approved:
        return False, ai_reason
    approved, reason = model_surface_authority(row)
    if not approved:
        return False, reason
    return True, "PUBLISHABLE"


def takeoff_row_pricing_authority(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Return whether a resolved row may affect firm pricing or active work."""
    publishable, reason = takeoff_row_publishability(row)
    if not publishable:
        return False, reason
    scope_approved, scope_reason = takeoff_row_scope_authority(row)
    if not scope_approved:
        return False, scope_reason
    return True, "PRICING_AUTHORISED"


def is_provisional_takeoff_row(row: Mapping[str, Any]) -> bool:
    """Return whether a row is provisional (unmeasured, to-measure, or provisional inclusion)."""
    if _normalised(row.get("inclusion_status")) in _PROVISIONAL_INCLUSION_VALUES:
        return True
    if _normalised(row.get("quantity_status")) in _PROVISIONAL_STATUS_VALUES:
        return True
    if is_model_surface_row(row):
        approved, _ = model_surface_authority(row)
        if not approved:
            return True
    return False


def is_progress_eligible_row(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Determine whether a takeoff row is eligible for progress claims.

    Ineligible rows:
    - Excluded rows (EXCLUDED)
    - Floor reference rows (FLOOR_REFERENCE)
    - Unreviewed AI drafts or unapproved/tampered model surfaces
    - Provisional rows (PROVISIONAL)
    - Non-positive or non-finite quantities (ZERO_OR_INVALID_QUANTITY)
    """
    publishable, reason = takeoff_row_publishability(row)
    if not publishable:
        return False, reason
    if is_provisional_takeoff_row(row):
        return False, "PROVISIONAL"
    qty_raw = row.get("quantity")
    if qty_raw is None:
        return False, "ZERO_OR_INVALID_QUANTITY"
    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return False, "ZERO_OR_INVALID_QUANTITY"
    if not math.isfinite(qty) or qty <= 0.0:
        return False, "ZERO_OR_INVALID_QUANTITY"
    return True, "ELIGIBLE"


def is_jobhub_eligible_row(row: Mapping[str, Any]) -> Tuple[bool, str]:
    """Determine whether a takeoff row is eligible for JobHub export / publication.

    Ineligible rows:
    - Excluded rows (EXCLUDED)
    - Floor reference rows (FLOOR_REFERENCE)
    - Clarification-only or provisional rows
    - Unreviewed AI drafts or unapproved/tampered model surfaces
    - Non-positive or non-finite quantities (ZERO_OR_INVALID_QUANTITY)
    """
    pricing_approved, reason = takeoff_row_pricing_authority(row)
    if not pricing_approved:
        return False, reason
    qty_raw = row.get("quantity")
    if qty_raw is None:
        return False, "ZERO_OR_INVALID_QUANTITY"
    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return False, "ZERO_OR_INVALID_QUANTITY"
    if not math.isfinite(qty) or qty <= 0.0:
        return False, "ZERO_OR_INVALID_QUANTITY"
    return True, "ELIGIBLE"

