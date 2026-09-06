"""pb_page_scale_calibration_authority.py — Per-Page Scale Calibration Status & Conflict Handling.

Makes PlanReader's scale system page-specific, explicit, and fail-closed: every page
gets its own isolated ScaleCalibration record (pb_geometry_takeoff_model.ScaleCalibration),
disagreeing scale sources escalate to a status that requires human resolution instead of
guessing, and unknown/invalid/stale scale always blocks commercial geometry rather than
silently producing wrong measurements.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
from typing import Dict, List, Optional

from pb_geometry_takeoff_model import AuthorityStatus, ScaleCalibration

# PDF native resolution is 72 points/inch; 1 metre = 39.3701 inches.
# At true 1:1 scale, one real-world metre spans this many PDF points.
POINTS_PER_METRE_AT_1_1 = 72.0 * 39.3700787401575


class ScaleSourceType(str, Enum):
    TITLE_BLOCK = "title_block"
    SCALE_BAR = "scale_bar"
    MANUAL = "manual"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ScaleCalibrationStatus(str, Enum):
    VALID = "valid"
    PROVISIONAL = "provisional"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    MANUAL_REQUIRED = "manual_required"
    USER_APPROVED = "user_approved"
    BLOCKED = "blocked"


# Sources whose disagreement is serious enough to require manual estimator resolution
# rather than just being flagged for review.
_AUTHORITATIVE_SOURCES = {ScaleSourceType.TITLE_BLOCK.value, ScaleSourceType.SCALE_BAR.value, ScaleSourceType.MANUAL.value}


def px_per_m_from_ratio(ratio: float) -> float:
    """Convert a drawing scale ratio denominator (e.g. 100 for "1:100") to px/m.

    Matches the established PlanReader convention (~28.35 px/m at 1:100).
    """
    if not math.isfinite(ratio) or ratio <= 0.0:
        raise ValueError(f"Scale ratio must be finite and strictly positive, got {ratio}")
    return POINTS_PER_METRE_AT_1_1 / ratio


@dataclass
class ScaleSourceReading:
    """A single raw scale detection for a page, before reconciliation."""
    source_type: str  # from ScaleSourceType
    scale_text: str
    ratio: Optional[float]  # drawing ratio denominator, e.g. 100.0 for "1:100"; None if unparseable
    confidence: float = 1.0


def unknown_calibration(page_no: int, sheet_label: str = "") -> ScaleCalibration:
    """A placeholder calibration for a page with no scale detection at all."""
    return ScaleCalibration(
        page_no=page_no,
        ratio_str="UNKNOWN",
        px_per_m=0.0,
        method="UNKNOWN",
        is_verified=False,
        confidence=0.0,
        sheet_label=sheet_label,
        scale_text="",
        source_type=ScaleSourceType.UNKNOWN.value,
        status=ScaleCalibrationStatus.UNKNOWN.value,
        issues=["No scale detected on this page"],
    )


def _valid_readings(readings: List[ScaleSourceReading]) -> List[ScaleSourceReading]:
    return [r for r in readings if r.ratio is not None and math.isfinite(r.ratio) and r.ratio > 0.0]


def _invalid_reading_issues(readings: List[ScaleSourceReading]) -> List[str]:
    issues = []
    for r in readings:
        if r.ratio is None or not math.isfinite(r.ratio) or r.ratio <= 0.0:
            issues.append(f"Rejected non-finite/non-positive scale reading from {r.source_type}: {r.ratio!r} ({r.scale_text!r})")
    return issues


def _best_single_reading_status(reading: ScaleSourceReading) -> str:
    if reading.source_type == ScaleSourceType.INFERRED.value:
        return ScaleCalibrationStatus.PROVISIONAL.value
    if reading.source_type == ScaleSourceType.UNKNOWN.value:
        return ScaleCalibrationStatus.UNKNOWN.value
    # TITLE_BLOCK, SCALE_BAR, and MANUAL single readings are all internally "valid"
    # (nothing to conflict with); measurement_authority_for_page_scale() is what
    # still caps TITLE_BLOCK-only calibrations to a provisional measurement.
    return ScaleCalibrationStatus.VALID.value


def resolve_page_scale_calibration(
    page_no: int,
    sheet_label: str,
    readings: List[ScaleSourceReading],
    revision_id: Optional[str] = None,
    max_delta_ratio: float = 0.05,
) -> ScaleCalibration:
    """Reconcile all scale detections for one page into a single authoritative record.

    Each call produces an independent ScaleCalibration scoped to `page_no` — nothing
    here reads or writes any other page's state, so there is no mechanism for scale to
    leak between pages.
    """
    issues = _invalid_reading_issues(readings)
    valid = _valid_readings(readings)

    if not readings:
        calib = unknown_calibration(page_no=page_no, sheet_label=sheet_label)
        return replace(calib, revision_id=revision_id)

    if not valid:
        return ScaleCalibration(
            page_no=page_no,
            ratio_str="UNKNOWN",
            px_per_m=0.0,
            method="UNKNOWN",
            is_verified=False,
            confidence=0.0,
            sheet_label=sheet_label,
            scale_text=readings[0].scale_text if readings else "",
            source_type=readings[0].source_type if readings else ScaleSourceType.UNKNOWN.value,
            status=ScaleCalibrationStatus.BLOCKED.value,
            issues=issues or ["All scale readings for this page were invalid"],
            revision_id=revision_id,
        )

    if len(valid) == 1:
        reading = valid[0]
        status = _best_single_reading_status(reading)
        px_per_m = px_per_m_from_ratio(reading.ratio)
        return ScaleCalibration(
            page_no=page_no,
            ratio_str=reading.scale_text,
            px_per_m=px_per_m,
            method=reading.source_type.upper(),
            is_verified=status == ScaleCalibrationStatus.VALID.value,
            confidence=reading.confidence,
            sheet_label=sheet_label,
            scale_text=reading.scale_text,
            source_type=reading.source_type,
            status=status,
            issues=issues,
            revision_id=revision_id,
        )

    # Multiple valid readings: check pairwise agreement against the max ratio delta.
    ratios = [r.ratio for r in valid]
    lo, hi = min(ratios), max(ratios)
    delta_ratio = (hi - lo) / lo if lo > 0 else float("inf")

    if delta_ratio > max_delta_ratio:
        sources_in_conflict = {r.source_type for r in valid}
        conflict_issue = (
            f"Scale sources disagree beyond tolerance ({delta_ratio * 100:.1f}% > "
            f"{max_delta_ratio * 100:.1f}%): "
            + ", ".join(f"{r.source_type}=1:{r.ratio:g}" for r in valid)
        )
        status = (
            ScaleCalibrationStatus.MANUAL_REQUIRED.value
            if sources_in_conflict & _AUTHORITATIVE_SOURCES
            else ScaleCalibrationStatus.CONFLICTING.value
        )
        return ScaleCalibration(
            page_no=page_no,
            ratio_str="UNKNOWN",
            px_per_m=0.0,
            method="CONFLICT",
            is_verified=False,
            confidence=0.0,
            sheet_label=sheet_label,
            scale_text=" vs ".join(r.scale_text for r in valid),
            source_type=max(valid, key=lambda r: r.confidence).source_type,
            status=status,
            issues=issues + [conflict_issue],
            revision_id=revision_id,
        )

    # Agreement within tolerance: trust the highest-confidence reading.
    best = max(valid, key=lambda r: r.confidence)
    status = _best_single_reading_status(best)
    return ScaleCalibration(
        page_no=page_no,
        ratio_str=best.scale_text,
        px_per_m=px_per_m_from_ratio(best.ratio),
        method=best.source_type.upper(),
        is_verified=status == ScaleCalibrationStatus.VALID.value,
        confidence=best.confidence,
        sheet_label=sheet_label,
        scale_text=best.scale_text,
        source_type=best.source_type,
        status=status,
        issues=issues,
        revision_id=revision_id,
    )


def check_calibration_freshness(calibration: ScaleCalibration, current_revision_id: Optional[str]) -> ScaleCalibration:
    """Blocks a calibration captured under a revision that no longer matches the page's current one.

    Staleness can only be determined when both revisions are known; if either side is
    unknown, the calibration is passed through unchanged rather than guessed at.
    """
    if calibration.revision_id is None or current_revision_id is None:
        return calibration
    if calibration.revision_id == current_revision_id:
        return calibration

    return replace(
        calibration,
        status=ScaleCalibrationStatus.BLOCKED.value,
        is_verified=False,
        issues=calibration.issues + [
            f"Stale calibration: captured under revision {calibration.revision_id!r}, "
            f"current revision is {current_revision_id!r}"
        ],
    )


def approve_page_scale_calibration(
    calibration: ScaleCalibration,
    approved_ratio: float,
    approved_by: str,
    approved_at: Optional[str] = None,
) -> ScaleCalibration:
    """Estimator sign-off on a manual/conflicting/provisional calibration.

    The original issue list is preserved (not cleared) so downstream publish gates and
    audit trails can still see what needed resolving, even after approval.
    """
    if not math.isfinite(approved_ratio) or approved_ratio <= 0.0:
        raise ValueError(f"Approved scale ratio must be finite and strictly positive, got {approved_ratio}")
    if not approved_by:
        raise ValueError("approved_by is required to approve a scale calibration")

    scale_text = f"1:{approved_ratio:g}"
    return replace(
        calibration,
        ratio_str=scale_text,
        scale_text=scale_text,
        px_per_m=px_per_m_from_ratio(approved_ratio),
        method="MANUAL",
        source_type=ScaleSourceType.MANUAL.value,
        status=ScaleCalibrationStatus.USER_APPROVED.value,
        is_verified=True,
        confidence=1.0,
        approved_by=approved_by,
        approved_at=approved_at,
        issues=calibration.issues + [f"Resolved via manual approval by {approved_by}"],
    )


def measurement_authority_for_page_scale(calibration: ScaleCalibration) -> str:
    """Maps a page's scale calibration status to the AuthorityStatus usable for its measurements.

    Fails closed: any status not explicitly recognized as usable blocks rather than
    defaulting to something permissive.
    """
    if calibration.status == ScaleCalibrationStatus.USER_APPROVED.value:
        return AuthorityStatus.FIRM.value

    if calibration.status == ScaleCalibrationStatus.VALID.value:
        if calibration.source_type == ScaleSourceType.TITLE_BLOCK.value:
            # A title-block-only reading is internally consistent but never
            # corroborated — never firm on its own, matching prior PlanReader policy.
            return AuthorityStatus.PROVISIONAL.value
        return AuthorityStatus.FIRM.value

    if calibration.status == ScaleCalibrationStatus.PROVISIONAL.value:
        return AuthorityStatus.PROVISIONAL.value

    # unknown, conflicting, manual_required, blocked -> fail closed.
    return AuthorityStatus.BLOCKED.value


@dataclass
class PageScaleCalibrationRegistry:
    """Per-workspace collection of page-scoped scale calibrations.

    A plain dict keyed by page_no already guarantees isolation — there is no shared
    "current scale" or fallback lookup that could leak one page's calibration into
    another's measurements.
    """
    _by_page: Dict[int, ScaleCalibration] = field(default_factory=dict)

    def set(self, page_no: int, calibration: ScaleCalibration) -> None:
        self._by_page[page_no] = calibration

    def get(self, page_no: int) -> Optional[ScaleCalibration]:
        return self._by_page.get(page_no)

    def all_issues(self) -> Dict[int, List[str]]:
        return {page_no: calib.issues for page_no, calib in self._by_page.items() if calib.issues}
