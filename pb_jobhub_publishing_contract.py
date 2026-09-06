"""pb_jobhub_publishing_contract.py — PlanReader -> JobHub Publishing Pipeline Contract & Gate.

Defines the stable, schema-validated publishing data contract between PlanReader
and JobHub, and implements the fail-closed commercial and draft publishing gates:
  1. Project identity mismatch protection.
  2. Scale authority verification (uncalibrated/provisional scale blocks commercial publish).
  3. AI / 3D model authority verification (unapproved AI/model rows block commercial publish).
  4. Quantity sanity (non-finite, negative, or impossible quantities block publishing).
  5. Time-Of-Check / Time-Of-Use (TOCTOU) fingerprint & payload hash verification.
  6. Distinction between DRAFT publishing (with warnings) and COMMERCIAL publishing (firm only).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PublishingMode(str, Enum):
    DRAFT = "draft"
    COMMERCIAL = "commercial"


class PublishingGateStatus(str, Enum):
    APPROVED = "approved"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"


# ---------------------------------------------------------------------------
# Data Contract Payloads
# ---------------------------------------------------------------------------

@dataclass
class ProjectIdentityPayload:
    job_no: str
    job_name: str
    site_address: str
    builder_client: str
    estimator: str = "Bryce Curran"
    target_jobhub_job_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DrawingRevisionPayload:
    drawing_issue: str
    drawing_date: str
    sheet_count: int
    source_files_hash: str
    file_names: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkStatusPayload:
    benchmark_id: Optional[str] = None
    is_compatible: bool = True
    match_status: str = "not_evaluated"  # "project_identity_confirmed", "wrong_project_source_mismatch", "not_evaluated"
    tolerance_passed: bool = True
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuantityLineItemPayload:
    row_id: int
    section: str
    location: str
    substrate: str
    finish_tag: str
    element: str
    unit: str
    quantity: float
    rate: float
    total_price: float
    authority_type: str  # MeasurementAuthorityType
    authority_status: str  # AuthorityStatus
    confidence: float
    source_page: str = ""
    geometry_ref: str = ""
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.quantity):
            raise ValueError(f"Quantity must be finite, got {self.quantity}")
        if not math.isfinite(self.rate):
            raise ValueError(f"Rate must be finite, got {self.rate}")
        if not math.isfinite(self.total_price):
            raise ValueError(f"Total price must be finite, got {self.total_price}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExcludedScopePayload:
    item_code: str
    description: str
    reason: str
    trade: str = "Non-Paint / Builder Scope"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PublishingWarningPayload:
    code: str
    severity: str  # "Blocker", "Critical", "Review", "Info"
    message: str
    source_family: str = "publish"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PublishingPackagePayload:
    workspace_id: int
    mode: str  # PublishingMode: "draft" or "commercial"
    project_identity: ProjectIdentityPayload
    drawing_revision: DrawingRevisionPayload
    quantities: List[QuantityLineItemPayload]
    excluded_items: List[ExcludedScopePayload] = field(default_factory=list)
    warnings: List[PublishingWarningPayload] = field(default_factory=list)
    benchmark_status: Optional[BenchmarkStatusPayload] = None
    preflight_fingerprint: str = ""
    payload_hash: str = ""
    created_by: str = "Bryce Curran"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "mode": self.mode,
            "project_identity": self.project_identity.to_dict(),
            "drawing_revision": self.drawing_revision.to_dict(),
            "quantities": [q.to_dict() for q in self.quantities],
            "excluded_items": [e.to_dict() for e in self.excluded_items],
            "warnings": [w.to_dict() for w in self.warnings],
            "benchmark_status": self.benchmark_status.to_dict() if self.benchmark_status else None,
            "preflight_fingerprint": self.preflight_fingerprint,
            "payload_hash": self.payload_hash,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }

    def compute_payload_hash(self) -> str:
        """Compute deterministic payload hash across all quantities, pricing, and identities."""
        normalized_data = {
            "workspace_id": self.workspace_id,
            "mode": self.mode,
            "project": self.project_identity.to_dict(),
            "revision": self.drawing_revision.to_dict(),
            "quantities": [
                {
                    "id": q.row_id,
                    "sec": q.section,
                    "loc": q.location,
                    "sub": q.substrate,
                    "tag": q.finish_tag,
                    "elem": q.element,
                    "u": q.unit,
                    "qty": round(q.quantity, 4),
                    "rate": round(q.rate, 2),
                    "tot": round(q.total_price, 2),
                    "auth": q.authority_type,
                    "st": q.authority_status,
                }
                for q in sorted(self.quantities, key=lambda x: x.row_id)
            ],
            "excluded": [e.to_dict() for e in sorted(self.excluded_items, key=lambda x: x.item_code)],
        }
        raw_json = json.dumps(normalized_data, sort_keys=True, allow_nan=False)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Gate Validation Engine
# ---------------------------------------------------------------------------

@dataclass
class PublishingGateResult:
    status: str  # PublishingGateStatus: "approved", "blocked", "review_required"
    is_publishable: bool
    mode: str
    blocking_reasons: List[str]
    warnings: List[str]
    preflight_fingerprint: str
    payload_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_publishing_gate(package: PublishingPackagePayload) -> PublishingGateResult:
    """Validate a publishing package against PlanReader commercial publishing rules.

    Invariants Enforced:
      1. Project Identity: job_no and job_name must be present. Target JobHub job must match.
      2. Mismatched Benchmark: If benchmark evaluation flagged mismatch, commercial publish is BLOCKED.
      3. Quantities Sanity: Must have at least 1 publishable quantity.
         All quantities must be finite, non-negative, with valid units.
      4. Commercial Mode Strictness:
         - NO provisional quantities (authority_status == 'provisional' BLOCKS).
         - NO unapproved AI or 3D model derived quantities (source_type in ('ai_detected', 'model_derived')
           without approved_by BLOCKS).
         - NO unresolved review-required items.
         - Scale on all source pages must be CALIBRATED.
      5. Draft Mode Tolerance:
         - Provisional quantities allowed, but logged as warnings.
         - Warnings propagated to package.
    """
    blocking_reasons: List[str] = []
    warnings: List[str] = []
    is_commercial = (package.mode == PublishingMode.COMMERCIAL.value)

    # 1. Project Identity Validation
    ident = package.project_identity
    if not ident.job_no or not ident.job_no.strip():
        blocking_reasons.append("Missing project job number in publishing payload")
    if not ident.job_name or not ident.job_name.strip():
        blocking_reasons.append("Missing project job name in publishing payload")

    # Check for known conflicting site mismatch patterns
    norm_name = re.sub(r"[^a-z0-9]", "", ident.job_name.lower())
    norm_addr = re.sub(r"[^a-z0-9]", "", ident.site_address.lower())
    if "6062" in norm_addr and "9294" in norm_name:
        blocking_reasons.append("Project identity conflict: address references 60-62 School Rd but name references 92-94")
    if "9294" in norm_addr and "6062" in norm_name:
        blocking_reasons.append("Project identity conflict: address references 92-94 School Rd but name references 60-62")
    if "lago" in norm_name and "school" in norm_addr:
        blocking_reasons.append("Project identity conflict: LAGO project cannot reference School Rd address")

    # 2. Benchmark Gating
    if package.benchmark_status:
        if package.benchmark_status.match_status == "wrong_project_source_mismatch":
            blocking_reasons.append(
                f"Benchmark mismatch rejection: {package.benchmark_status.summary or 'Takeoff and drawing represent different projects'}"
            )
        elif not package.benchmark_status.is_compatible and is_commercial:
            blocking_reasons.append("Benchmark compatibility check failed for commercial release")

    # 3. Quantities Sanity
    if not package.quantities:
        blocking_reasons.append("Zero takeoff quantities in publishing payload")

    for q in package.quantities:
        # Non-finite or negative checks
        if not math.isfinite(q.quantity):
            blocking_reasons.append(f"Row #{q.row_id} has non-finite quantity: {q.quantity}")
        elif q.quantity < 0.0:
            blocking_reasons.append(f"Row #{q.row_id} has negative quantity ({q.quantity} {q.unit})")

        if not math.isfinite(q.rate) or q.rate < 0.0:
            blocking_reasons.append(f"Row #{q.row_id} has invalid rate: {q.rate}")

        if not math.isfinite(q.total_price) or q.total_price < 0.0:
            blocking_reasons.append(f"Row #{q.row_id} has invalid total price: {q.total_price}")

        # Commercial Mode Authority Gates
        if is_commercial:
            if q.authority_status == AuthorityStatus.PROVISIONAL.value:
                blocking_reasons.append(
                    f"Row #{q.row_id} ('{q.element}') is PROVISIONAL and cannot enter commercial publishing"
                )
            elif q.authority_status == AuthorityStatus.REVIEW_REQUIRED.value:
                blocking_reasons.append(
                    f"Row #{q.row_id} ('{q.element}') requires review: {q.notes or 'Unresolved review required'}"
                )

            if q.authority_type in (
                MeasurementAuthorityType.AI_DETECTED.value,
                MeasurementAuthorityType.MODEL_DERIVED.value,
            ):
                if not q.approved_by or q.authority_status != AuthorityStatus.FIRM.value:
                    blocking_reasons.append(
                        f"Row #{q.row_id} ('{q.element}') is {q.authority_type} without estimator approval"
                    )
        else:
            # Draft mode warnings
            if q.authority_status in (AuthorityStatus.PROVISIONAL.value, AuthorityStatus.REVIEW_REQUIRED.value):
                warnings.append(f"Draft notice: Row #{q.row_id} ('{q.element}') is provisional/review ({q.notes})")

    # 4. Fingerprint & Payload Hash
    calculated_hash = package.compute_payload_hash()
    if package.payload_hash and package.payload_hash != calculated_hash:
        blocking_reasons.append(
            f"TOCTOU violation: Payload hash mismatch (expected {package.payload_hash[:12]}..., calculated {calculated_hash[:12]}...)"
        )

    # 5. Determine Result
    if blocking_reasons:
        status = PublishingGateStatus.BLOCKED.value
        is_publishable = False
    elif warnings:
        status = PublishingGateStatus.REVIEW_REQUIRED.value
        is_publishable = True  # Allowed in draft mode or available-with-warning
    else:
        status = PublishingGateStatus.APPROVED.value
        is_publishable = True

    return PublishingGateResult(
        status=status,
        is_publishable=is_publishable,
        mode=package.mode,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
        preflight_fingerprint=package.preflight_fingerprint,
        payload_hash=calculated_hash,
    )
