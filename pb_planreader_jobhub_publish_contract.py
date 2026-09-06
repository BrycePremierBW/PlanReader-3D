"""pb_planreader_jobhub_publish_contract.py — PlanReader -> JobHub Publishing Contract & Gate.

Defines the safe, attributable payload contract and fail-closed preflight gate for
publishing PlanReader takeoff datasets to JobHub.
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
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    generate_takeoff_authority_summary,
)


# ---------------------------------------------------------------------------
# Publish Modes
# ---------------------------------------------------------------------------

class PublishMode(str, Enum):
    DRAFT_PUBLISH = "draft_publish"
    COMMERCIAL_PUBLISH = "commercial_publish"


# ---------------------------------------------------------------------------
# Per-Row JobHub Quantity Contract
# ---------------------------------------------------------------------------

@dataclass
class PlanReaderJobHubQuantityRow:
    """Individual takeoff row carrying full measurement authority and SHA-256 fingerprint."""
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
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = self.compute_row_fingerprint()

    def compute_row_fingerprint(self) -> str:
        """Compute tamper-evident SHA-256 fingerprint over core commercial fields."""
        payload = {
            "quantity_id": str(self.quantity_id),
            "description": str(self.description),
            "value": round(float(self.value), 4),
            "unit": str(self.unit),
            "trade": str(self.trade),
            "source_type": str(self.source_type),
            "authority_status": str(self.authority_status),
            "source_page": str(self.source_page or ""),
            "source_sheet": str(self.source_sheet or ""),
            "revision_hash": str(self.revision_hash or ""),
            "approved_by": str(self.approved_by or ""),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint or self.compute_row_fingerprint()
        return d

    @classmethod
    def from_takeoff_output_row(cls, row: TakeoffOutputRow) -> "PlanReaderJobHubQuantityRow":
        return cls(
            quantity_id=row.quantity_id,
            description=row.description,
            value=row.value,
            unit=row.unit,
            trade=row.trade,
            source_type=row.source_type,
            authority_status=row.authority_status,
            confidence=row.confidence,
            source_page=row.source_page,
            source_sheet=row.source_sheet,
            geometry_ref=row.geometry_ref,
            scale_id=row.scale_id,
            dimension_text_id=row.dimension_text_id,
            benchmark_status=row.benchmark_status,
            is_publishable=row.is_publishable,
            warnings=list(row.warnings),
            blocking_reasons=list(row.blocking_reasons),
            approved_by=row.approved_by,
            approved_at=row.approved_at,
            revision_hash=row.revision_hash,
            fingerprint=row.compute_fingerprint(),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanReaderJobHubQuantityRow":
        return cls(
            quantity_id=str(data.get("quantity_id") or ""),
            description=str(data.get("description") or ""),
            value=float(data.get("value") or 0.0),
            unit=str(data.get("unit") or ""),
            trade=str(data.get("trade") or "general"),
            source_type=str(data.get("source_type") or TakeoffSourceType.DOCUMENTED_DIMENSION.value),
            authority_status=str(data.get("authority_status") or AuthorityStatus.FIRM.value),
            confidence=float(data.get("confidence") if data.get("confidence") is not None else 1.0),
            source_page=data.get("source_page"),
            source_sheet=data.get("source_sheet"),
            geometry_ref=data.get("geometry_ref"),
            scale_id=data.get("scale_id"),
            dimension_text_id=data.get("dimension_text_id"),
            benchmark_status=data.get("benchmark_status"),
            is_publishable=bool(data.get("is_publishable", False)),
            warnings=list(data.get("warnings") or []),
            blocking_reasons=list(data.get("blocking_reasons") or []),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
            revision_hash=data.get("revision_hash"),
            fingerprint=str(data.get("fingerprint") or ""),
        )


# ---------------------------------------------------------------------------
# Top-Level JobHub Payload Contract
# ---------------------------------------------------------------------------

@dataclass
class PlanReaderJobHubPayload:
    """Safe, immutable publishing contract delivered to JobHub."""
    project_identity: Dict[str, Any]
    drawing_revision: Dict[str, Any]
    authority_summary: Dict[str, Any]
    quantities: List[PlanReaderJobHubQuantityRow]
    excluded_items: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    created_at: str = ""
    created_by: str = ""
    publish_mode: str = PublishMode.COMMERCIAL_PUBLISH.value
    benchmark_status: Optional[Dict[str, Any]] = None
    payload_fingerprint: str = ""
    is_commercial_ready: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.payload_fingerprint:
            self.payload_fingerprint = self.compute_payload_fingerprint()

    def compute_payload_fingerprint(self) -> str:
        """Compute top-level SHA-256 fingerprint over all payload attributes."""
        canonical = {
            "project_identity": self.project_identity,
            "drawing_revision": self.drawing_revision,
            "publish_mode": self.publish_mode,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "source_files": sorted(self.source_files),
            "quantities": [
                {
                    "id": q.quantity_id,
                    "val": round(q.value, 4),
                    "unit": q.unit,
                    "auth": q.authority_status,
                    "fp": q.fingerprint or q.compute_row_fingerprint(),
                }
                for q in self.quantities
            ],
            "excluded_items": self.excluded_items,
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_identity": self.project_identity,
            "drawing_revision": self.drawing_revision,
            "benchmark_status": self.benchmark_status,
            "authority_summary": self.authority_summary,
            "quantities": [q.to_dict() for q in self.quantities],
            "excluded_items": self.excluded_items,
            "warnings": self.warnings,
            "blocking_reasons": self.blocking_reasons,
            "source_files": self.source_files,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "publish_mode": self.publish_mode,
            "payload_fingerprint": self.payload_fingerprint or self.compute_payload_fingerprint(),
            "is_commercial_ready": self.is_commercial_ready,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanReaderJobHubPayload":
        quantities = [
            PlanReaderJobHubQuantityRow.from_dict(q)
            for q in (data.get("quantities") or [])
        ]
        return cls(
            project_identity=dict(data.get("project_identity") or {}),
            drawing_revision=dict(data.get("drawing_revision") or {}),
            authority_summary=dict(data.get("authority_summary") or {}),
            quantities=quantities,
            excluded_items=list(data.get("excluded_items") or []),
            warnings=list(data.get("warnings") or []),
            blocking_reasons=list(data.get("blocking_reasons") or []),
            source_files=list(data.get("source_files") or []),
            created_at=str(data.get("created_at") or ""),
            created_by=str(data.get("created_by") or ""),
            publish_mode=str(data.get("publish_mode") or PublishMode.COMMERCIAL_PUBLISH.value),
            benchmark_status=data.get("benchmark_status"),
            payload_fingerprint=str(data.get("payload_fingerprint") or ""),
            is_commercial_ready=bool(data.get("is_commercial_ready", False)),
            notes=str(data.get("notes") or ""),
        )


# ---------------------------------------------------------------------------
# Preflight Result
# ---------------------------------------------------------------------------

@dataclass
class PublishPreflightResult:
    """Outcome of publish preflight gate validation."""
    is_valid: bool
    publish_mode: str
    publishable_row_count: int
    blocked_row_count: int
    provisional_row_count: int
    blocking_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    payload_fingerprint: Optional[str] = None


# ---------------------------------------------------------------------------
# Partitioning Helper
# ---------------------------------------------------------------------------

def partition_publishable_rows(
    rows: Sequence[Union[TakeoffOutputRow, PlanReaderJobHubQuantityRow]]
) -> Dict[str, List[Any]]:
    """Partition rows into commercial publishable, draft-only, and unpublishable."""
    groups: Dict[str, List[Any]] = {
        "publishable": [],
        "draft_only": [],
        "unpublishable": [],
    }

    for r in rows:
        auth_status = getattr(r, "authority_status", "").lower()
        is_pub = bool(getattr(r, "is_publishable", False))

        if auth_status in (AuthorityStatus.EXCLUDED.value, AuthorityStatus.REFERENCE_ONLY.value, AuthorityStatus.BLOCKED.value):
            groups["unpublishable"].append(r)
        elif is_pub:
            groups["publishable"].append(r)
        else:
            groups["draft_only"].append(r)

    return groups


def compute_payload_fingerprint(payload_data: Mapping[str, Any]) -> str:
    """Compute deterministic SHA-256 fingerprint for arbitrary payload data."""
    raw = json.dumps(payload_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Preflight Gate Runner
# ---------------------------------------------------------------------------

def run_jobhub_publish_preflight(
    rows: Sequence[Union[TakeoffOutputRow, PlanReaderJobHubQuantityRow, Dict[str, Any]]],
    project_identity: Mapping[str, Any],
    drawing_revision: Mapping[str, Any],
    mode: Union[PublishMode, str] = PublishMode.COMMERCIAL_PUBLISH,
) -> PublishPreflightResult:
    """Execute complete fail-closed preflight gate validation prior to JobHub payload construction."""
    p_mode = mode.value if isinstance(mode, PublishMode) else str(mode).lower()
    is_commercial = (p_mode == PublishMode.COMMERCIAL_PUBLISH.value)

    blocking_reasons: List[str] = []
    warnings: List[str] = []

    # 1. Project Identity Validation
    if not project_identity or not project_identity.get("project_id"):
        blocking_reasons.append("Missing or invalid project identity")
    elif project_identity.get("identity_confirmed") is False:
        reason = project_identity.get("mismatch_reason") or "Project identity unconfirmed or mismatched"
        blocking_reasons.append(f"Project identity mismatch rejected: {reason}")

    # 2. Drawing Revision Validation
    curr_rev_hash = str(drawing_revision.get("revision_hash") or "")
    if not drawing_revision or not curr_rev_hash:
        if is_commercial:
            blocking_reasons.append("Missing or invalid drawing revision hash")
        else:
            warnings.append("Drawing revision hash is unrecorded")

    # 3. Row-by-Row Gate Validation
    publishable_count = 0
    blocked_count = 0
    provisional_count = 0

    for idx, raw_row in enumerate(rows):
        qid = getattr(raw_row, "quantity_id", None) or (raw_row.get("quantity_id") if isinstance(raw_row, dict) else f"ROW-{idx}")
        
        # Check basic authority metadata
        if isinstance(raw_row, dict):
            if "authority_status" not in raw_row or "source_type" not in raw_row:
                blocking_reasons.append(f"Row {qid}: missing measurement authority metadata")
                blocked_count += 1
                continue
            row_obj = PlanReaderJobHubQuantityRow.from_dict(raw_row)
        elif isinstance(raw_row, TakeoffOutputRow):
            row_obj = PlanReaderJobHubQuantityRow.from_takeoff_output_row(raw_row)
        elif isinstance(raw_row, PlanReaderJobHubQuantityRow):
            row_obj = raw_row
        else:
            blocking_reasons.append(f"Row {qid}: unsupported row type")
            blocked_count += 1
            continue

        # Check numeric validity
        val = row_obj.value
        if not math.isfinite(val) or val < 0.0:
            blocking_reasons.append(f"Row {qid}: non-finite or negative quantity ({val})")
            blocked_count += 1
            continue

        # Check invalid zeroes
        if val == 0.0 and any("zero" in r.lower() for r in row_obj.blocking_reasons):
            blocking_reasons.append(f"Row {qid}: zero quantity is invalid for element")
            blocked_count += 1
            continue

        auth_status = row_obj.authority_status.lower()

        # Check revision staleness
        if row_obj.revision_hash and curr_rev_hash and row_obj.revision_hash != curr_rev_hash:
            if is_commercial:
                blocking_reasons.append(f"Row {qid}: stale revision hash ({row_obj.revision_hash} != {curr_rev_hash})")
                blocked_count += 1
                continue
            else:
                warnings.append(f"Row {qid}: measured on superseded revision {row_obj.revision_hash}")

        # Evaluate against mode
        if is_commercial:
            if auth_status in (AuthorityStatus.EXCLUDED.value, AuthorityStatus.REFERENCE_ONLY.value, AuthorityStatus.BLOCKED.value):
                blocking_reasons.append(f"Row {qid}: item with status '{auth_status}' cannot enter commercial release")
                blocked_count += 1
            elif not row_obj.is_publishable:
                reasons = ", ".join(row_obj.blocking_reasons) if row_obj.blocking_reasons else f"unapproved status '{auth_status}'"
                blocking_reasons.append(f"Row {qid}: unpublishable item ({reasons})")
                blocked_count += 1
            else:
                publishable_count += 1
        else:
            # Draft publish
            if auth_status in (AuthorityStatus.PROVISIONAL.value, AuthorityStatus.REVIEW_REQUIRED.value):
                provisional_count += 1
                warnings.append(f"Row {qid}: provisional item ({row_obj.source_type}) included in draft")
            elif row_obj.is_publishable:
                publishable_count += 1
            else:
                blocked_count += 1

    # In draft mode, add explicit non-commercial warning
    if not is_commercial:
        warnings.append("Draft publish payload: contains non-commercial quantities; NOT approved JobHub cost data")

    # Deduplicate reasons and warnings
    def _dedup(seq: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    final_blocking = _dedup(blocking_reasons)
    final_warnings = _dedup(warnings)

    is_valid = (len(final_blocking) == 0)

    return PublishPreflightResult(
        is_valid=is_valid,
        publish_mode=p_mode,
        publishable_row_count=publishable_count,
        blocked_row_count=blocked_count,
        provisional_row_count=provisional_count,
        blocking_reasons=final_blocking,
        warnings=final_warnings,
    )


# ---------------------------------------------------------------------------
# Payload Builder
# ---------------------------------------------------------------------------

def build_jobhub_payload(
    rows: Sequence[Union[TakeoffOutputRow, PlanReaderJobHubQuantityRow, Dict[str, Any]]],
    project_identity: Mapping[str, Any],
    drawing_revision: Mapping[str, Any],
    source_files: Optional[List[str]] = None,
    created_by: str = "",
    created_at: Optional[str] = None,
    publish_mode: Union[PublishMode, str] = PublishMode.COMMERCIAL_PUBLISH,
    benchmark_status: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> PlanReaderJobHubPayload:
    """Construct a verified PlanReaderJobHubPayload enforcing commercial preflight invariants."""
    p_mode = publish_mode.value if isinstance(publish_mode, PublishMode) else str(publish_mode).lower()
    is_commercial = (p_mode == PublishMode.COMMERCIAL_PUBLISH.value)

    preflight = run_jobhub_publish_preflight(
        rows=rows,
        project_identity=project_identity,
        drawing_revision=drawing_revision,
        mode=p_mode,
    )

    if is_commercial and not preflight.is_valid:
        raise ValueError(f"Cannot build commercial payload: {'; '.join(preflight.blocking_reasons)}")

    # Convert rows to PlanReaderJobHubQuantityRow
    converted_rows: List[PlanReaderJobHubQuantityRow] = []
    excluded_items: List[Dict[str, Any]] = []

    for r in rows:
        if isinstance(r, dict):
            row_obj = PlanReaderJobHubQuantityRow.from_dict(r)
        elif isinstance(r, TakeoffOutputRow):
            row_obj = PlanReaderJobHubQuantityRow.from_takeoff_output_row(r)
        elif isinstance(r, PlanReaderJobHubQuantityRow):
            row_obj = r
        else:
            continue

        if row_obj.authority_status == AuthorityStatus.EXCLUDED.value:
            excluded_items.append({
                "quantity_id": row_obj.quantity_id,
                "description": row_obj.description,
                "trade": row_obj.trade,
                "reason": "Explicitly excluded scope item",
            })
            if not is_commercial:
                converted_rows.append(row_obj)
        else:
            converted_rows.append(row_obj)

    # Authority summary calculation
    takeoff_row_objects: List[TakeoffOutputRow] = []
    for q in converted_rows:
        takeoff_row_objects.append(
            TakeoffOutputRow(
                quantity_id=q.quantity_id,
                description=q.description,
                value=q.value,
                unit=q.unit,
                trade=q.trade,
                source_type=q.source_type,
                authority_status=q.authority_status,
                confidence=q.confidence,
                source_page=q.source_page,
                source_sheet=q.source_sheet,
                geometry_ref=q.geometry_ref,
                scale_id=q.scale_id,
                dimension_text_id=q.dimension_text_id,
                benchmark_status=q.benchmark_status,
                is_publishable=q.is_publishable,
                warnings=q.warnings,
                blocking_reasons=q.blocking_reasons,
                approved_by=q.approved_by,
                approved_at=q.approved_at,
                revision_hash=q.revision_hash,
            )
        )

    summary = generate_takeoff_authority_summary(takeoff_row_objects)

    return PlanReaderJobHubPayload(
        project_identity=dict(project_identity),
        drawing_revision=dict(drawing_revision),
        authority_summary=summary,
        quantities=converted_rows,
        excluded_items=excluded_items,
        warnings=list(preflight.warnings),
        blocking_reasons=list(preflight.blocking_reasons),
        source_files=list(source_files or []),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        created_by=created_by,
        publish_mode=p_mode,
        benchmark_status=benchmark_status,
        is_commercial_ready=is_commercial and preflight.is_valid,
        notes=notes,
    )
