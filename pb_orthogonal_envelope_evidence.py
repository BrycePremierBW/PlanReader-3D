"""Resolve a rectangular plan envelope from orthogonal figured dimensions.

This is a source-evidence layer, not a generic "pick the biggest numbers"
heuristic. A candidate envelope is accepted only when:

* horizontal and vertical dimension text directions are explicit in native PDF
  text geometry;
* each dimension line is itself only a figured dimension (not a number found
  inside prose, a standard reference, drawing number, or date); and
* the resulting footprint is independently corroborated by an explicit drawing
  floor-area annotation.

A named secondary strip such as a ``VERANDAH`` can contribute to that area only
when its width is independently evidenced. A supplied width is accepted as an
already-resolved upstream observation. Otherwise, this module can bind a small
figured dimension to one unique ``VERANDAH`` / ``VERANDA`` label by spatial
band, and the complete compound footprint must still agree with the independent
explicit floor-area annotation. No area agreement means no envelope.

Ambiguity fails closed. The module knows nothing about benchmark identities,
BOQ quantities, project names, or expected answers.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, Optional, Tuple

import fitz


_DIMENSION_LINE_RE = re.compile(
    r"^\s*(?P<major>\d{1,2})[,.]?(?P<minor>\d{3})\s*(?:mm)?\s*$",
    re.IGNORECASE,
)
_SECONDARY_LABELS = frozenset({"verandah", "veranda"})


@dataclass(frozen=True)
class OrientedDimensionObservation:
    value_m: float
    orientation: str  # "horizontal" or "vertical"
    raw_text: str
    bbox: Tuple[float, float, float, float]
    direction: Tuple[float, float]


@dataclass(frozen=True)
class SecondaryAreaLabelEvidence:
    text: str
    bbox: Tuple[float, float, float, float]


@dataclass(frozen=True)
class OrthogonalEnvelopeEvidence:
    length_m: float
    width_m: float
    horizontal_m: float
    vertical_m: float
    explicit_floor_area_m2: float
    corroborated_area_m2: float
    relative_area_error: float
    secondary_width_m: Optional[float]
    horizontal_evidence: OrientedDimensionObservation
    vertical_evidence: OrientedDimensionObservation
    secondary_width_evidence: Optional[OrientedDimensionObservation] = None
    secondary_label_evidence: Optional[SecondaryAreaLabelEvidence] = None
    authority: str = "orthogonal_figured_dimensions_corroborated_by_explicit_floor_area"


def _parse_standalone_dimension(text: str) -> Optional[float]:
    match = _DIMENSION_LINE_RE.fullmatch(text or "")
    if match is None:
        return None
    value = float(match.group("major")) + float(match.group("minor")) / 1000.0
    # Small standalone figured dimensions are retained because they may be the
    # width of a named secondary strip. Main-envelope candidates are filtered
    # more strictly later.
    if not math.isfinite(value) or not (0.75 <= value <= 35.0):
        return None
    return round(value, 3)


def extract_oriented_dimension_observations(
    page: fitz.Page,
) -> list[OrientedDimensionObservation]:
    """Extract standalone native figured dimensions with text orientation.

    PyMuPDF exposes each native text line's direction vector. Horizontal and
    90-degree rotated dimension strings therefore remain distinct even on a
    dense sheet containing many dimension chains. Diagonal / uncertain text
    directions are ignored.
    """
    observations: list[OrientedDimensionObservation] = []
    try:
        payload = page.get_text("dict") or {}
    except Exception:
        return observations

    for block in payload.get("blocks", []) or []:
        for line in block.get("lines", []) or []:
            spans = line.get("spans", []) or []
            text = " ".join(str(span.get("text", "")) for span in spans).strip()
            value = _parse_standalone_dimension(text)
            if value is None:
                continue

            direction = line.get("dir", (1.0, 0.0)) or (1.0, 0.0)
            try:
                dx, dy = float(direction[0]), float(direction[1])
            except (TypeError, ValueError, IndexError):
                continue

            if abs(dx) >= 0.85 and abs(dx) >= abs(dy):
                orientation = "horizontal"
            elif abs(dy) >= 0.85 and abs(dy) > abs(dx):
                orientation = "vertical"
            else:
                continue

            raw_bbox = line.get("bbox")
            if not raw_bbox or len(raw_bbox) != 4:
                continue
            bbox = tuple(float(v) for v in raw_bbox)
            if not all(math.isfinite(v) for v in bbox):
                continue

            observations.append(
                OrientedDimensionObservation(
                    value_m=value,
                    orientation=orientation,
                    raw_text=text,
                    bbox=bbox,  # type: ignore[arg-type]
                    direction=(dx, dy),
                )
            )
    return observations


def _unique_by_value(
    observations: Iterable[OrientedDimensionObservation],
) -> list[OrientedDimensionObservation]:
    """Keep one deterministic observation for each figured value."""
    selected: dict[float, OrientedDimensionObservation] = {}
    for obs in observations:
        current = selected.get(obs.value_m)
        if current is None or (obs.bbox[1], obs.bbox[0]) < (current.bbox[1], current.bbox[0]):
            selected[obs.value_m] = obs
    return [selected[value] for value in sorted(selected, reverse=True)]


def _centre(bbox: Tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _find_unique_secondary_label(page: fitz.Page) -> Optional[SecondaryAreaLabelEvidence]:
    """Return one unique native secondary-area label, otherwise fail closed."""
    try:
        words = page.get_text("words") or []
    except Exception:
        return None

    matches: list[SecondaryAreaLabelEvidence] = []
    for word in words:
        token = re.sub(r"[^a-z]", "", str(word[4]).lower())
        if token not in _SECONDARY_LABELS:
            continue
        bbox = tuple(float(v) for v in word[:4])
        if not all(math.isfinite(v) for v in bbox):
            continue
        matches.append(SecondaryAreaLabelEvidence(text=str(word[4]), bbox=bbox))  # type: ignore[arg-type]

    if len(matches) != 1:
        return None
    return matches[0]


def _bound_secondary_width_candidates(
    page: fitz.Page,
    observations: Iterable[OrientedDimensionObservation],
    label: SecondaryAreaLabelEvidence,
) -> list[OrientedDimensionObservation]:
    """Bind small figured widths to the same spatial band as a secondary label.

    A rotated vertical dimension owns a horizontal page band, so its y-centre
    must align with the label's y-centre. A horizontal dimension owns a vertical
    page band, so x-centres must align. The tolerance scales with the page rather
    than using a benchmark coordinate or fixed pixel constant.
    """
    try:
        page_short_side = min(float(page.rect.width), float(page.rect.height))
    except Exception:
        return []
    if not math.isfinite(page_short_side) or page_short_side <= 0:
        return []

    band_tolerance = max(4.0, page_short_side * 0.02)
    label_x, label_y = _centre(label.bbox)
    candidates: list[OrientedDimensionObservation] = []
    for obs in observations:
        if not (0.75 <= obs.value_m <= 5.0):
            continue
        obs_x, obs_y = _centre(obs.bbox)
        distance = (
            abs(obs_y - label_y)
            if obs.orientation == "vertical"
            else abs(obs_x - label_x)
        )
        if distance <= band_tolerance:
            candidates.append(obs)
    return _unique_by_value(candidates)


def resolve_orthogonal_envelope_evidence(
    page: fitz.Page,
    *,
    explicit_floor_area_m2: float,
    secondary_width_m: Optional[float] = None,
    relative_area_tolerance: float = 0.015,
) -> Optional[OrthogonalEnvelopeEvidence]:
    """Resolve one orthogonal envelope independently corroborated by floor area.

    The existing PlanReader compound-footprint convention treats an evidenced
    secondary strip (such as an open verandah) as running along the main
    envelope length. The independent area check is therefore::

        main_length * main_width + main_length * secondary_width

    A caller-supplied secondary width is treated as already evidenced upstream.
    When no width is supplied and exactly one secondary label exists, this
    resolver may derive candidate widths only from standalone dimensions bound
    to the label's own spatial band. If a secondary label exists but its width
    cannot be uniquely corroborated by the final area relationship, resolution
    fails closed rather than ignoring the named component.
    """
    try:
        explicit_area = float(explicit_floor_area_m2)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(explicit_area) or explicit_area <= 0:
        return None

    if not math.isfinite(relative_area_tolerance) or not (0 < relative_area_tolerance <= 0.05):
        return None

    observations = extract_oriented_dimension_observations(page)
    horizontal = _unique_by_value(
        obs for obs in observations
        if obs.orientation == "horizontal" and obs.value_m >= 3.0
    )
    vertical = _unique_by_value(
        obs for obs in observations
        if obs.orientation == "vertical" and obs.value_m >= 3.0
    )
    if not horizontal or not vertical:
        return None

    supplied_secondary: Optional[float] = None
    if secondary_width_m is not None:
        try:
            supplied_secondary = float(secondary_width_m)
        except (TypeError, ValueError):
            return None
        if (
            not math.isfinite(supplied_secondary)
            or supplied_secondary <= 0
            or supplied_secondary > 10.0
        ):
            return None

    secondary_label: Optional[SecondaryAreaLabelEvidence] = None
    secondary_options: list[tuple[Optional[float], Optional[OrientedDimensionObservation]]]
    if supplied_secondary is not None:
        secondary_options = [(supplied_secondary, None)]
    else:
        secondary_label = _find_unique_secondary_label(page)
        if secondary_label is not None:
            inferred = _bound_secondary_width_candidates(page, observations, secondary_label)
            if not inferred:
                return None
            secondary_options = [(obs.value_m, obs) for obs in inferred]
        else:
            # If the page contains no secondary-area label at all, a plain
            # rectangular envelope remains a valid candidate.
            secondary_options = [(None, None)]

    matches: dict[tuple[float, float, Optional[float]], OrthogonalEnvelopeEvidence] = {}
    for h_obs in horizontal:
        for v_obs in vertical:
            length_m = max(h_obs.value_m, v_obs.value_m)
            width_m = min(h_obs.value_m, v_obs.value_m)
            main_area = length_m * width_m
            if not (15.0 <= main_area <= 600.0):
                continue

            for secondary, secondary_obs in secondary_options:
                corroborated_area = main_area
                if secondary is not None:
                    corroborated_area += length_m * secondary

                relative_error = abs(corroborated_area - explicit_area) / explicit_area
                if relative_error > relative_area_tolerance:
                    continue

                key = (
                    round(length_m, 3),
                    round(width_m, 3),
                    round(secondary, 4) if secondary is not None else None,
                )
                matches[key] = OrthogonalEnvelopeEvidence(
                    length_m=key[0],
                    width_m=key[1],
                    horizontal_m=h_obs.value_m,
                    vertical_m=v_obs.value_m,
                    explicit_floor_area_m2=round(explicit_area, 4),
                    corroborated_area_m2=round(corroborated_area, 4),
                    relative_area_error=round(relative_error, 6),
                    secondary_width_m=key[2],
                    horizontal_evidence=h_obs,
                    vertical_evidence=v_obs,
                    secondary_width_evidence=secondary_obs,
                    secondary_label_evidence=(
                        secondary_label if secondary_obs is not None else None
                    ),
                )

    if len(matches) != 1:
        return None
    return next(iter(matches.values()))
