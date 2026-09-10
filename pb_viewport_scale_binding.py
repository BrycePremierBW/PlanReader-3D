"""Viewport-owned scale calibration for mixed-scale drawing sheets.

F.07 already associates scale *text* with a segmented viewport.  Page-scale
authority still emits one ``ScaleCalibration`` per page.  On mixed-scale sheets
that page-level record is either conflicting or silently wrong for one of the
views.

This module does not invent a second scale authority.  It reuses
``resolve_page_scale_calibration`` / ``measurement_authority_for_page_scale``
and the existing measurement-input fingerprint seam, scoped to one owned
viewport.

Safety:
- project/file/benchmark identity is never an input to scale semantics;
- inferred scale is never emitted;
- graphic scale-bar evidence is never invented here;
- ordinary viewport-owned textual ratio evidence is never classified as
  ``SCALE_BAR`` and therefore cannot become FIRM merely by spatial ownership;
- title-block / textual scale stays provisional (not FIRM);
- ``scale_raw`` and ``scale_denominator`` must agree when both are present;
- missing ``revision_id`` fail-closes locally and does not attach
  ``resolved_scale_id``;
- conflicting scales inside one viewport fail closed;
- sibling-viewport scale text cannot leak into another binding;
- ambiguous/unsupported viewports cannot receive a resolved scale id.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
from typing import Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus, ScaleCalibration
from pb_measurement_input_authority import scale_calibration_fingerprint
from pb_migration_contracts import ViewportEvidence, ViewportResolutionStatus
from pb_page_scale_calibration_authority import (
    ScaleCalibrationStatus,
    ScaleSourceReading,
    ScaleSourceType,
    measurement_authority_for_page_scale,
    resolve_page_scale_calibration,
)
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportSegmentationStatus,
)

VIEWPORT_SCALE_BINDING_SCHEMA_VERSION = "1.0.0"

# Textual ratio evidence uses TITLE_BLOCK so the unmodified
# ``measurement_authority_for_page_scale`` mapper keeps it provisional.
# VALID SCALE_BAR is FIRM; this producer must not emit SCALE_BAR without
# independently corroborated graphic scale-bar evidence (not in this slice).
_TEXTUAL_SCALE_SOURCE = ScaleSourceType.TITLE_BLOCK.value

# Tight, deterministic agreement between scale_raw and scale_denominator.
# This is not the page-scale 5% reconciler tolerance.
VIEWPORT_SCALE_RATIO_REL_TOL = 1e-9
VIEWPORT_SCALE_RATIO_ABS_TOL = 1e-9

_SCALE_RE = re.compile(r"\b(?:SCALE\s*)?(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\b", re.I)
_CONFLICT_NOTE_RE = re.compile(r"conflicting viewport scales:\s*(.+)", re.I)

_USABLE_VIEWPORT_STATUS = {
    ViewportSegmentationStatus.RESOLVED.value,
    ViewportSegmentationStatus.DERIVED.value,
}


class ViewportScaleBindingError(ValueError):
    """Raised when a caller pairs a binding with the wrong viewport."""


@dataclass(frozen=True)
class ViewportScaleBinding:
    """One viewport-scoped reuse of the existing page-scale calibration record."""

    viewport_id: str
    page_no: int
    source_sha256: str
    revision_id: Optional[str]
    calibration: ScaleCalibration
    scale_fingerprint: str
    measurement_authority: str
    blocking_reasons: tuple[str, ...] = ()
    schema_version: str = VIEWPORT_SCALE_BINDING_SCHEMA_VERSION

    @property
    def abstained(self) -> bool:
        return bool(self.blocking_reasons) or self.measurement_authority != AuthorityStatus.FIRM.value


def classify_viewport_scale_source(*, label: str, scale_raw: Optional[str]) -> str:
    """Classify explicit viewport scale *text*. Never inferred, never SCALE_BAR.

    F.07 spatial ownership of scale text is not graphic scale-bar corroboration.
    Title-embedded and isolated callouts are both textual; TITLE_BLOCK is the
    existing source type that stays provisional under the unmodified mapper.
    ``label`` is accepted for call-site compatibility and does not promote
    authority.
    """
    del label
    raw = " ".join(str(scale_raw or "").upper().split())
    if not raw:
        return ScaleSourceType.UNKNOWN.value
    return _TEXTUAL_SCALE_SOURCE


def _normalize_revision_id(revision_id: Optional[str]) -> Optional[str]:
    if revision_id is None:
        return None
    text = str(revision_id).strip()
    return text or None


def _parse_ratio_from_raw(scale_raw: Optional[str]) -> Optional[float]:
    if not scale_raw:
        return None
    match = _SCALE_RE.search(str(scale_raw))
    if not match:
        return None
    numerator = float(match.group(1))
    denominator = float(match.group(2))
    if numerator <= 0.0 or denominator <= 0.0:
        return None
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return None
    return denominator / numerator


def _valid_denominator(scale_denominator: Optional[float]) -> Optional[float]:
    if scale_denominator is None:
        return None
    value = float(scale_denominator)
    if math.isfinite(value) and value > 0.0:
        return value
    return None


def _ratios_agree(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=VIEWPORT_SCALE_RATIO_REL_TOL,
        abs_tol=VIEWPORT_SCALE_RATIO_ABS_TOL,
    )


def _raw_text(scale_raw: Optional[str]) -> str:
    return str(scale_raw or "").strip()


def scale_representation_mismatch_reason(viewport: SegmentedViewport) -> Optional[str]:
    """If both representations exist, they must agree. Never prefer one."""
    raw_present = bool(_raw_text(viewport.scale_raw))
    denominator_present = viewport.scale_denominator is not None
    if not (raw_present and denominator_present):
        return None
    parsed = _parse_ratio_from_raw(viewport.scale_raw)
    denominator = _valid_denominator(viewport.scale_denominator)
    if parsed is None or denominator is None or not _ratios_agree(parsed, denominator):
        return "viewport_scale_ratio_mismatch"
    return None


def _agreed_textual_ratio(viewport: SegmentedViewport) -> Optional[float]:
    if scale_representation_mismatch_reason(viewport) is not None:
        return None
    parsed = _parse_ratio_from_raw(viewport.scale_raw)
    denominator = _valid_denominator(viewport.scale_denominator)
    if parsed is not None:
        return parsed
    return denominator


def _conflict_ratios(notes: Sequence[str]) -> tuple[float, ...]:
    found: list[float] = []
    for note in notes:
        match = _CONFLICT_NOTE_RE.search(str(note))
        if not match:
            continue
        for token in match.group(1).split(","):
            try:
                value = float(token.strip())
            except ValueError:
                continue
            if math.isfinite(value) and value > 0.0:
                found.append(value)
    unique = tuple(sorted({round(value, 9) for value in found}))
    return unique


def viewport_scale_readings(viewport: SegmentedViewport) -> tuple[ScaleSourceReading, ...]:
    """Build existing ``ScaleSourceReading`` rows from one segmented viewport.

    Mismatched ``scale_raw`` / ``scale_denominator`` emit no usable reading so
    a contradictory representation cannot win silently. Unparseable conflicts
    also emit no invented ratios; ``bind_viewport_scale`` carries the blocker.
    """
    if scale_representation_mismatch_reason(viewport) is not None:
        return ()
    if viewport.scale_conflict:
        ratios = _conflict_ratios(viewport.notes)
        if len(ratios) >= 2:
            return tuple(
                ScaleSourceReading(
                    source_type=_TEXTUAL_SCALE_SOURCE,
                    scale_text=f"1:{ratio:g}",
                    ratio=ratio,
                    confidence=0.5,
                )
                for ratio in ratios
            )
        return ()
    source = classify_viewport_scale_source(label=viewport.label, scale_raw=viewport.scale_raw)
    ratio = _agreed_textual_ratio(viewport)
    if ratio is not None and source == ScaleSourceType.UNKNOWN.value:
        # Denominator-only evidence is still a textual ratio, not a scale bar.
        source = _TEXTUAL_SCALE_SOURCE
    if ratio is None:
        text = _raw_text(viewport.scale_raw)
        return (
            ScaleSourceReading(
                source_type=source,
                scale_text=text,
                ratio=None,
                confidence=0.0,
            ),
        ) if text else ()
    text = _raw_text(viewport.scale_raw) or f"1:{ratio:g}"
    return (
        ScaleSourceReading(
            source_type=source,
            scale_text=text,
            ratio=ratio,
            confidence=float(viewport.confidence) if math.isfinite(float(viewport.confidence)) else 0.0,
        ),
    )


def _sheet_label_for_viewport(sheet_label: str, viewport_id: str) -> str:
    base = str(sheet_label or "").strip()
    marker = f"viewport:{viewport_id}"
    if not base:
        return marker
    return f"{base}#{marker}"


def bind_viewport_scale(
    viewport: SegmentedViewport,
    *,
    page_no: int,
    revision_id: Optional[str] = None,
    sheet_label: str = "",
    source_sha256: str = "",
) -> ViewportScaleBinding:
    """Reconcile one viewport's scale evidence through the existing page-scale authority."""
    reasons: list[str] = []
    normalized_revision = _normalize_revision_id(revision_id)
    if int(viewport.page_number) != int(page_no):
        reasons.append("scale_page_mismatch")
    if viewport.status not in _USABLE_VIEWPORT_STATUS:
        reasons.append("viewport_unresolved")
    if viewport.bounding_box is None and viewport.status in _USABLE_VIEWPORT_STATUS:
        reasons.append("viewport_extent_missing")
    if normalized_revision is None:
        reasons.append("scale_revision_unbound")

    mismatch_reason = scale_representation_mismatch_reason(viewport)
    if mismatch_reason is not None:
        reasons.append(mismatch_reason)

    readings = viewport_scale_readings(viewport)
    calibration = resolve_page_scale_calibration(
        page_no=page_no,
        sheet_label=_sheet_label_for_viewport(sheet_label, viewport.view_id),
        readings=list(readings),
        revision_id=normalized_revision,
    )
    authority = measurement_authority_for_page_scale(calibration)
    fingerprint = scale_calibration_fingerprint(calibration)

    if viewport.scale_conflict:
        reasons.append("viewport_scale_conflict")
    if not readings and mismatch_reason is None and not viewport.scale_conflict:
        reasons.append("viewport_scale_missing")
    if authority != AuthorityStatus.FIRM.value:
        reasons.append("scale_not_firm")
    if calibration.status in {
        ScaleCalibrationStatus.CONFLICTING.value,
        ScaleCalibrationStatus.MANUAL_REQUIRED.value,
        ScaleCalibrationStatus.BLOCKED.value,
        ScaleCalibrationStatus.UNKNOWN.value,
    }:
        if "viewport_scale_conflict" not in reasons and viewport.scale_conflict:
            reasons.append("viewport_scale_conflict")
        if (
            calibration.status == ScaleCalibrationStatus.UNKNOWN.value
            and "viewport_scale_missing" not in reasons
            and mismatch_reason is None
            and not viewport.scale_conflict
        ):
            reasons.append("viewport_scale_missing")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return ViewportScaleBinding(
        viewport_id=viewport.view_id,
        page_no=page_no,
        source_sha256=str(source_sha256 or ""),
        revision_id=normalized_revision,
        calibration=calibration,
        scale_fingerprint=fingerprint,
        measurement_authority=authority,
        blocking_reasons=unique_reasons,
    )


def bind_page_viewport_scales(
    viewports: Sequence[SegmentedViewport],
    *,
    page_no: int,
    revision_id: Optional[str] = None,
    sheet_label: str = "",
    source_sha256: str = "",
) -> tuple[ViewportScaleBinding, ...]:
    """Bind every viewport independently so mixed-scale sheets cannot share a page scale."""
    return tuple(
        bind_viewport_scale(
            viewport,
            page_no=page_no,
            revision_id=revision_id,
            sheet_label=sheet_label,
            source_sha256=source_sha256,
        )
        for viewport in viewports
    )


def assert_binding_matches_viewport(binding: ViewportScaleBinding, viewport_id: str) -> None:
    if binding.viewport_id != viewport_id:
        raise ViewportScaleBindingError(
            f"scale binding for {binding.viewport_id!r} cannot be applied to {viewport_id!r}"
        )


def viewport_evidence_with_bound_scale(
    evidence: ViewportEvidence,
    binding: ViewportScaleBinding,
) -> ViewportEvidence:
    """Attach ``resolved_scale_id`` only when the binding is locally usable and FIRM."""
    assert_binding_matches_viewport(binding, evidence.viewport_id)
    if evidence.status in (ViewportResolutionStatus.AMBIGUOUS, ViewportResolutionStatus.UNSUPPORTED):
        return evidence
    if binding.revision_id is None or "scale_revision_unbound" in binding.blocking_reasons:
        return replace(evidence, resolved_scale_id=None)
    if binding.abstained:
        return replace(evidence, resolved_scale_id=None)
    return replace(evidence, resolved_scale_id=binding.scale_fingerprint)
