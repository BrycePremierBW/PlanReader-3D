"""pb_takeoff_output_authority.py — Measurement Authority Metadata Across Takeoff Outputs.

Ensures PlanReader emits complete, traceable, and tamper-resistant takeoff rows with
explicit authority metadata, confidence scoring, scale/dimension references, approval
state, and publishability gating.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from pb_geometry_takeoff_model import AuthorityStatus
from pb_page_scale_calibration_authority import ScaleCalibrationStatus


# ---------------------------------------------------------------------------
# Source Types
# ---------------------------------------------------------------------------

class TakeoffSourceType(str, Enum):
    DOCUMENTED_DIMENSION = "documented_dimension"
    SCHEDULE_EXTRACTED = "schedule_extracted"
    PDF_SCALED = "pdf_scaled"
    AI_DETECTED = "ai_detected"
    MODEL_DERIVED = "model_derived"
    USER_CORRECTED = "user_corrected"
    USER_APPROVED = "user_approved"
    EXCLUDED = "excluded"
    REFERENCE_ONLY = "reference_only"
    BLOCKED = "blocked"
    MANUAL = "manual"


_KNOWN_SOURCE_TYPES = {t.value for t in TakeoffSourceType}
_KNOWN_AUTHORITY_STATUSES = {s.value for s in AuthorityStatus}
_UNRELIABLE_SCALE_STATUSES = {
    ScaleCalibrationStatus.UNKNOWN.value,
    ScaleCalibrationStatus.CONFLICTING.value,
    ScaleCalibrationStatus.MANUAL_REQUIRED.value,
    ScaleCalibrationStatus.BLOCKED.value,
}


# ---------------------------------------------------------------------------
# Core Takeoff Output Row
# ---------------------------------------------------------------------------

@dataclass
class TakeoffOutputRow:
    """Standardized commercial takeoff row with complete authority metadata."""
    quantity_id: str
    description: str
    value: float
    unit: str
    trade: str = "general"
    source_type: str = TakeoffSourceType.DOCUMENTED_DIMENSION.value
    authority_status: str = AuthorityStatus.FIRM.value
    confidence: float = 1.0
    source_page: Optional[Union[int, str]] = None
    source_sheet: Optional[str] = None
    geometry_ref: Optional[str] = None
    scale_id: Optional[str] = None
    dimension_text_id: Optional[str] = None
    benchmark_status: Optional[str] = None
    is_publishable: bool = False
    warnings: List[str] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    revision_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError(f"Takeoff value must be finite, got {self.value}")
        if self.value < 0.0:
            raise ValueError(f"Takeoff value cannot be negative, got {self.value}")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")

    def compute_fingerprint(self) -> str:
        """Compute tamper-evident SHA-256 fingerprint over core commercial fields."""
        payload = {
            "quantity_id": str(self.quantity_id),
            "description": str(self.description),
            "value": round(float(self.value), 4),
            "unit": str(self.unit),
            "source_type": str(self.source_type),
            "authority_status": str(self.authority_status),
            "source_page": str(self.source_page or ""),
            "revision_hash": str(self.revision_hash or ""),
            "approved_by": str(self.approved_by or ""),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["fingerprint"] = self.compute_fingerprint()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TakeoffOutputRow":
        clean = {
            "quantity_id": str(data.get("quantity_id") or ""),
            "description": str(data.get("description") or ""),
            "value": float(data.get("value") or 0.0),
            "unit": str(data.get("unit") or ""),
            "trade": str(data.get("trade") or "general"),
            "source_type": str(data.get("source_type") or TakeoffSourceType.DOCUMENTED_DIMENSION.value),
            "authority_status": str(data.get("authority_status") or AuthorityStatus.FIRM.value),
            "confidence": float(data.get("confidence") if data.get("confidence") is not None else 1.0),
            "source_page": data.get("source_page"),
            "source_sheet": data.get("source_sheet"),
            "geometry_ref": data.get("geometry_ref"),
            "scale_id": data.get("scale_id"),
            "dimension_text_id": data.get("dimension_text_id"),
            "benchmark_status": data.get("benchmark_status"),
            "is_publishable": bool(data.get("is_publishable", False)),
            "warnings": list(data.get("warnings") or []),
            "blocking_reasons": list(data.get("blocking_reasons") or []),
            "approved_by": data.get("approved_by"),
            "approved_at": data.get("approved_at"),
            "revision_hash": data.get("revision_hash"),
        }
        return cls(**clean)


# ---------------------------------------------------------------------------
# Factory with Complete Policy Matrix
# ---------------------------------------------------------------------------

def create_takeoff_output_row(
    quantity_id: str,
    description: str,
    value: float,
    unit: str,
    trade: str = "general",
    source_type: Union[TakeoffSourceType, str] = TakeoffSourceType.DOCUMENTED_DIMENSION,
    authority_status: Optional[Union[AuthorityStatus, str]] = None,
    confidence: float = 1.0,
    source_page: Optional[Union[int, str]] = None,
    source_sheet: Optional[str] = None,
    geometry_ref: Optional[str] = None,
    scale_id: Optional[str] = None,
    dimension_text_id: Optional[str] = None,
    benchmark_status: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    blocking_reasons: Optional[List[str]] = None,
    approved_by: Optional[str] = None,
    approved_at: Optional[str] = None,
    revision_hash: Optional[str] = None,
    current_revision_hash: Optional[str] = None,
    project_identity_confirmed: Optional[bool] = None,
    scale_calibration_status: Optional[str] = None,
    allow_zero: bool = True,
) -> TakeoffOutputRow:
    """Construct TakeoffOutputRow applying the complete commercial authority and publishability matrix."""
    # Fail-closed numeric check
    if not math.isfinite(value):
        raise ValueError(f"Quantity value must be finite, got {value}")
    if value < 0.0:
        raise ValueError(f"Quantity value cannot be negative, got {value}")

    s_type = source_type.value if isinstance(source_type, TakeoffSourceType) else str(source_type).lower()
    a_status = authority_status.value if isinstance(authority_status, AuthorityStatus) else (str(authority_status).lower() if authority_status else None)

    warn_list: List[str] = list(warnings or [])
    block_list: List[str] = list(blocking_reasons or [])

    # Fail closed on any authority metadata this module does not recognize, rather
    # than letting an unrecognized label silently pass through to downstream consumers.
    if a_status is not None and a_status not in _KNOWN_AUTHORITY_STATUSES:
        block_list.append(f"Unknown authority_status: {a_status!r}")
        a_status = AuthorityStatus.BLOCKED.value

    if s_type not in _KNOWN_SOURCE_TYPES:
        block_list.append(f"Unknown source_type: {s_type!r}")
        a_status = AuthorityStatus.BLOCKED.value

    if not allow_zero and value == 0.0:
        a_status = AuthorityStatus.BLOCKED.value
        block_list.append("Zero quantity is invalid for physical takeoff element")

    # Scale Calibration Gating
    if scale_calibration_status:
        sc_status = str(scale_calibration_status).lower()
        if sc_status in _UNRELIABLE_SCALE_STATUSES:
            a_status = AuthorityStatus.BLOCKED.value
            block_list.append(f"Unreliable scale for scaled geometry (calibration status: {sc_status})")
        elif sc_status == ScaleCalibrationStatus.PROVISIONAL.value:
            warn_list.append("Associated scale calibration is provisional")
            if s_type == TakeoffSourceType.PDF_SCALED.value:
                a_status = AuthorityStatus.PROVISIONAL.value

    # Revision Freshness Check
    is_stale = False
    if revision_hash and current_revision_hash and revision_hash != current_revision_hash:
        is_stale = True
        block_list.append("Stale revision: drawing revision was superseded after measurement/approval")

    # Determine default authority status and publishability per source type
    is_publishable = False

    if s_type == TakeoffSourceType.DOCUMENTED_DIMENSION.value:
        has_trace = bool(source_page is not None or source_sheet)
        if not has_trace:
            block_list.append("Untraceable: documented dimension missing source page and sheet")
        if not dimension_text_id:
            block_list.append("Missing figured-dimension trace for documented dimension quantity")
        if a_status is None:
            a_status = AuthorityStatus.FIRM.value if (has_trace and dimension_text_id and not is_stale) else AuthorityStatus.REVIEW_REQUIRED.value
        if a_status == AuthorityStatus.FIRM.value and has_trace and dimension_text_id and not is_stale and len(block_list) == 0:
            is_publishable = True

    elif s_type == TakeoffSourceType.SCHEDULE_EXTRACTED.value:
        has_trace = bool(source_page is not None or source_sheet)
        if not has_trace:
            block_list.append("Missing source schedule trace")
        if project_identity_confirmed is False:
            block_list.append("Project identity unconfirmed or mismatched")
            a_status = AuthorityStatus.BLOCKED.value
        elif project_identity_confirmed is None:
            warn_list.append("Project identity not explicitly verified")
            block_list.append("Project identity not confirmed for schedule-extracted quantity")
            if a_status is None:
                a_status = AuthorityStatus.REVIEW_REQUIRED.value
        else:
            if a_status is None:
                a_status = AuthorityStatus.FIRM.value

        if a_status == AuthorityStatus.FIRM.value and project_identity_confirmed is True and has_trace and not is_stale and len(block_list) == 0:
            is_publishable = True

    elif s_type == TakeoffSourceType.PDF_SCALED.value:
        if a_status is None:
            a_status = AuthorityStatus.PROVISIONAL.value
        warn_list.append("Scaled geometry is provisional/draft only and requires estimator verification")
        if not scale_id:
            block_list.append("Missing scale reference for scaled geometry")
        is_publishable = False

    elif s_type == TakeoffSourceType.AI_DETECTED.value:
        if a_status is None:
            a_status = AuthorityStatus.PROVISIONAL.value
        warn_list.append("AI detected quantity is provisional/draft only and requires estimator review")
        block_list.append("AI-detected quantity is not approved for commercial publication")
        is_publishable = False

    elif s_type == TakeoffSourceType.MODEL_DERIVED.value:
        if approved_by:
            if a_status is None:
                a_status = AuthorityStatus.USER_APPROVED.value
            if not is_stale and len(block_list) == 0:
                is_publishable = True
        else:
            if a_status is None:
                a_status = AuthorityStatus.PROVISIONAL.value
            warn_list.append("3D model-derived quantity is provisional until approved by estimator")
            block_list.append("Model-derived quantity is not approved for commercial publication")
            is_publishable = False

    elif s_type == TakeoffSourceType.USER_CORRECTED.value:
        if approved_by:
            if a_status is None:
                a_status = AuthorityStatus.USER_APPROVED.value
            if not is_stale and len(block_list) == 0:
                is_publishable = True
        else:
            a_status = AuthorityStatus.REVIEW_REQUIRED.value
            block_list.append("User corrected quantity requires explicit approval before publication")
            is_publishable = False

    elif s_type == TakeoffSourceType.USER_APPROVED.value:
        if a_status is None:
            a_status = AuthorityStatus.USER_APPROVED.value
        if not approved_by:
            block_list.append("User approved row missing approved_by estimator attribution")
        if not is_stale and approved_by and len(block_list) == 0:
            is_publishable = True
        else:
            is_publishable = False

    elif s_type == TakeoffSourceType.EXCLUDED.value:
        a_status = AuthorityStatus.EXCLUDED.value
        block_list.append("Item is explicitly excluded from commercial scope")
        is_publishable = False

    elif s_type == TakeoffSourceType.REFERENCE_ONLY.value:
        a_status = AuthorityStatus.REFERENCE_ONLY.value
        block_list.append("Quantity is reference only and excluded from commercial pricing")
        is_publishable = False

    elif s_type == TakeoffSourceType.BLOCKED.value or a_status == AuthorityStatus.BLOCKED.value:
        a_status = AuthorityStatus.BLOCKED.value
        is_publishable = False
        if not block_list:
            block_list.append("Takeoff row is blocked from commercial publication")

    else:
        # Fallback default
        if a_status is None:
            a_status = AuthorityStatus.PROVISIONAL.value
        is_publishable = False

    # Deduplicate lists while preserving order
    def _dedup(seq: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    final_warnings = _dedup(warn_list)
    final_blocking = _dedup(block_list)

    if len(final_blocking) > 0:
        is_publishable = False

    return TakeoffOutputRow(
        quantity_id=quantity_id,
        description=description,
        value=value,
        unit=unit,
        trade=trade,
        source_type=s_type,
        authority_status=a_status or AuthorityStatus.PROVISIONAL.value,
        confidence=confidence,
        source_page=source_page,
        source_sheet=source_sheet,
        geometry_ref=geometry_ref,
        scale_id=scale_id,
        dimension_text_id=dimension_text_id,
        benchmark_status=benchmark_status,
        is_publishable=is_publishable,
        warnings=final_warnings,
        blocking_reasons=final_blocking,
        approved_by=approved_by,
        approved_at=approved_at,
        revision_hash=revision_hash,
    )


# ---------------------------------------------------------------------------
# Approval Workflow Helper
# ---------------------------------------------------------------------------

def approve_takeoff_output_row(
    row: TakeoffOutputRow,
    approved_by: str,
    approved_at: Optional[str] = None,
    current_revision_hash: Optional[str] = None,
) -> TakeoffOutputRow:
    """Approve a provisional, model-derived, or user-corrected row for publication."""
    stamp = approved_at or datetime.now(timezone.utc).isoformat()
    return create_takeoff_output_row(
        quantity_id=row.quantity_id,
        description=row.description,
        value=row.value,
        unit=row.unit,
        trade=row.trade,
        source_type=TakeoffSourceType.USER_APPROVED,
        authority_status=AuthorityStatus.USER_APPROVED,
        confidence=1.0,
        source_page=row.source_page,
        source_sheet=row.source_sheet,
        geometry_ref=row.geometry_ref,
        scale_id=row.scale_id,
        dimension_text_id=row.dimension_text_id,
        benchmark_status=row.benchmark_status,
        warnings=row.warnings,
        blocking_reasons=[
            r for r in row.blocking_reasons
            if "approv" not in r.lower() and "review" not in r.lower()
        ],
        approved_by=approved_by,
        approved_at=stamp,
        revision_hash=row.revision_hash,
        current_revision_hash=current_revision_hash or row.revision_hash,
    )


# ---------------------------------------------------------------------------
# Conversion / Ingestion Helpers
# ---------------------------------------------------------------------------

def from_database_row(row_dict: Mapping[str, Any]) -> TakeoffOutputRow:
    """Hydrate a sqlite takeoff_rows record into a complete TakeoffOutputRow."""
    qid = str(row_dict.get("id") or "")
    elem = str(row_dict.get("element") or "Takeoff Item")
    sec = str(row_dict.get("section") or "")
    desc = f"{sec} - {elem}" if sec and sec != elem else elem
    val = float(row_dict.get("quantity") or 0.0)
    unit = str(row_dict.get("unit") or "m²")

    # Detect trade from section or element
    trade = "general"
    lower_text = f"{sec} {elem} {row_dict.get('notes') or ''}".lower()
    if any(k in lower_text for k in ("cladding", "weatherboard", "matrix")):
        trade = "cladding"
    elif any(k in lower_text for k in ("plasterboard", "gyprock", "lining")):
        trade = "plasterboard"
    elif any(k in lower_text for k in ("render", "texture", "acratex")):
        trade = "rendering"
    elif any(k in lower_text for k in ("paint", "enamel", "acrylic", "internal wall")):
        trade = "painting"
    elif any(k in lower_text for k in ("window", "glazing", "door")):
        trade = "glazing"

    # Detect source type and authority status
    role = str(row_dict.get("row_role") or "").lower()
    origin = str(row_dict.get("origin") or "").lower()
    q_status = str(row_dict.get("quantity_status") or "").lower()
    inc_status = str(row_dict.get("inclusion_status") or "").lower()

    if inc_status in ("exclude", "excluded", "exclusion"):
        src = TakeoffSourceType.EXCLUDED
        auth = AuthorityStatus.EXCLUDED
    elif role == "floor_area" or "reference" in lower_text:
        src = TakeoffSourceType.REFERENCE_ONLY
        auth = AuthorityStatus.REFERENCE_ONLY
    elif origin in ("ai", "ai_draft") or "ai draft" in lower_text:
        src = TakeoffSourceType.AI_DETECTED
        auth = AuthorityStatus.PROVISIONAL
    elif role == "model_surface" or "3d" in lower_text:
        src = TakeoffSourceType.MODEL_DERIVED
        auth = AuthorityStatus.PROVISIONAL
    elif "scaled" in q_status:
        src = TakeoffSourceType.PDF_SCALED
        auth = AuthorityStatus.PROVISIONAL
    else:
        src = TakeoffSourceType.DOCUMENTED_DIMENSION
        auth = AuthorityStatus.FIRM

    auth_status_field = row_dict.get("commercial_authority_status")
    if auth_status_field:
        auth = str(auth_status_field).lower()

    approved_by = row_dict.get("commercial_authority_reviewed_by")
    approved_at = row_dict.get("commercial_authority_reviewed_at")

    return create_takeoff_output_row(
        quantity_id=qid,
        description=desc,
        value=val,
        unit=unit,
        trade=trade,
        source_type=src,
        authority_status=auth,
        source_page=row_dict.get("source_page"),
        source_sheet=str(row_dict.get("source_reference") or ""),
        approved_by=approved_by,
        approved_at=approved_at,
    )


def from_wall_takeoff(
    wall_id: str,
    description: str,
    net_area_m2: float,
    source_page: Union[int, str],
    source_sheet: str,
    scale_id: Optional[str] = None,
    figured_dimension_mm: Optional[float] = None,
    dimension_text_id: Optional[str] = None,
    trade: str = "general",
    warnings: Optional[List[str]] = None,
    blocking_reasons: Optional[List[str]] = None,
    revision_hash: Optional[str] = None,
) -> TakeoffOutputRow:
    """Create TakeoffOutputRow from wall takeoff result."""
    src = TakeoffSourceType.DOCUMENTED_DIMENSION if figured_dimension_mm is not None else TakeoffSourceType.PDF_SCALED
    auth = AuthorityStatus.FIRM if figured_dimension_mm is not None else AuthorityStatus.PROVISIONAL

    return create_takeoff_output_row(
        quantity_id=f"WALL-{wall_id}",
        description=description,
        value=net_area_m2,
        unit="m²",
        trade=trade,
        source_type=src,
        authority_status=auth,
        source_page=source_page,
        source_sheet=source_sheet,
        geometry_ref=wall_id,
        scale_id=scale_id,
        dimension_text_id=dimension_text_id,
        warnings=warnings,
        blocking_reasons=blocking_reasons,
        revision_hash=revision_hash,
    )


def from_ai_draft_row(ai_row: Any) -> TakeoffOutputRow:
    """Create TakeoffOutputRow from an AIDraftTakeoffRow."""
    return create_takeoff_output_row(
        quantity_id=f"AI-{getattr(ai_row, 'draft_id', 'draft')}",
        description=f"{getattr(ai_row, 'element', 'Element')} ({getattr(ai_row, 'location', 'Location')})",
        value=float(getattr(ai_row, "detected_quantity", 0.0)),
        unit=str(getattr(ai_row, "unit", "m²")),
        trade=str(getattr(ai_row, "section", "general")),
        source_type=TakeoffSourceType.AI_DETECTED,
        authority_status=AuthorityStatus.PROVISIONAL,
        confidence=float(getattr(ai_row, "confidence", 0.5)),
        source_page=getattr(ai_row, "source_page", None),
        warnings=list(getattr(ai_row, "uncertainty_flags", [])),
    )


def from_surface_record(rec: Mapping[str, Any]) -> TakeoffOutputRow:
    """Create TakeoffOutputRow from a 3D surface record."""
    surf_id = str(rec.get("surface_id") or "SURF")
    area = float(rec.get("area_m2") or 0.0)
    label = str(rec.get("face_label") or rec.get("face") or "Face")
    sub = str(rec.get("substrate") or "Substrate")
    return create_takeoff_output_row(
        quantity_id=f"SURF-{surf_id}",
        description=f"3D {label} · {sub}",
        value=area,
        unit="m²",
        trade="painting",
        source_type=TakeoffSourceType.MODEL_DERIVED,
        authority_status=AuthorityStatus.PROVISIONAL,
        source_page=rec.get("source_reference") or "3D model",
        geometry_ref=surf_id,
    )


# ---------------------------------------------------------------------------
# Reporting & Aggregation Helpers
# ---------------------------------------------------------------------------

def partition_takeoff_rows(rows: Sequence[TakeoffOutputRow]) -> Dict[str, List[TakeoffOutputRow]]:
    """Partition takeoff rows into discrete commercial authority groups."""
    groups: Dict[str, List[TakeoffOutputRow]] = {
        "publishable": [],
        "provisional": [],
        "review_required": [],
        "blocked": [],
        "excluded": [],
        "reference_only": [],
    }

    for r in rows:
        if r.is_publishable:
            groups["publishable"].append(r)
        elif r.authority_status == AuthorityStatus.EXCLUDED.value:
            groups["excluded"].append(r)
        elif r.authority_status == AuthorityStatus.REFERENCE_ONLY.value:
            groups["reference_only"].append(r)
        elif r.authority_status == AuthorityStatus.BLOCKED.value or (len(r.blocking_reasons) > 0 and r.authority_status not in (AuthorityStatus.PROVISIONAL.value, AuthorityStatus.REVIEW_REQUIRED.value)):
            groups["blocked"].append(r)
        elif r.authority_status == AuthorityStatus.REVIEW_REQUIRED.value:
            groups["review_required"].append(r)
        else:
            groups["provisional"].append(r)

    return groups


def generate_takeoff_authority_summary(rows: Sequence[TakeoffOutputRow]) -> Dict[str, Any]:
    """Calculate summary statistics and readiness metrics over takeoff rows."""
    groups = partition_takeoff_rows(rows)
    total = len(rows)
    pub_count = len(groups["publishable"])
    readiness = round((pub_count / total * 100.0), 1) if total > 0 else 0.0

    return {
        "total_count": total,
        "publishable_count": pub_count,
        "provisional_count": len(groups["provisional"]),
        "review_required_count": len(groups["review_required"]),
        "blocked_count": len(groups["blocked"]),
        "excluded_count": len(groups["excluded"]),
        "reference_only_count": len(groups["reference_only"]),
        "commercial_readiness_pct": readiness,
    }

