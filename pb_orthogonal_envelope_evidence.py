"""Resolve a rectangular plan envelope from orthogonal figured dimensions.

This is a source-evidence layer, not a generic "pick the biggest numbers"
heuristic.  A candidate envelope is accepted only when:

* both horizontal and vertical dimension text directions are explicit in the
  native PDF text geometry;
* each dimension line is itself only a figured dimension (not a number found
  inside prose, a standard reference, drawing number, or date); and
* the resulting footprint is independently corroborated by an explicit drawing
  floor-area annotation.  When a separately evidenced secondary-area width is
  supplied (for example an open verandah running along the main length), that
  area is included in the corroboration calculation.

Ambiguity fails closed.  The module knows nothing about benchmark identities,
BOQ quantities, project names, or expected answers.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, Optional, Sequence, Tuple

import fitz


_DIMENSION_LINE_RE = re.compile(
    r"^\s*(?P<major>\d{1,2})[,.]?(?P<minor>\d{3})\s*(?:mm)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OrientedDimensionObservation:
    value_m: float
    orientation: str  # "horizontal" or "vertical"
    raw_text: str
    bbox: Tuple[float, float, float, float]
    direction: Tuple[float, float]


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
    authority: str = "orthogonal_figured_dimensions_corroborated_by_explicit_floor_area"


def _parse_standalone_dimension(text: str) -> Optional[float]:
    match = _DIMENSION_LINE_RE.fullmatch(text or "")
    if match is None:
        return None
    value = float(match.group("major")) + float(match.group("minor")) / 1000.0
    if not math.isfinite(value) or not (3.0 <= value <= 35.0):
        return None
    return round(value, 3)


def extract_oriented_dimension_observations(
    page: fitz.Page,
) -> list[OrientedDimensionObservation]:
    """Extract standalone native figured dimensions with text orientation.

    PyMuPDF exposes each native text line's direction vector.  Horizontal and
    90-degree rotated dimension strings therefore remain distinct even on a
    dense sheet containing many dimension chains.  Diagonal / uncertain text
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
    envelope length.  When ``secondary_width_m`` is supplied, the independent
    area check is therefore::

        main_length * main_width + main_length * secondary_width

    If no secondary width is supplied the check is simply ``length * width``.
    More than one distinct envelope satisfying the source evidence is
    ambiguous and returns ``None``.
    """
    try:
        explicit_area = float(explicit_floor_area_m2)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(explicit_area) or explicit_area <= 0:
        return None

    secondary: Optional[float]
    if secondary_width_m is None:
        secondary = None
    else:
        try:
            secondary = float(secondary_width_m)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(secondary) or secondary <= 0 or secondary > 10.0:
            return None

    if not math.isfinite(relative_area_tolerance) or not (0 < relative_area_tolerance <= 0.05):
        return None

    observations = extract_oriented_dimension_observations(page)
    horizontal = _unique_by_value(
        obs for obs in observations if obs.orientation == "horizontal"
    )
    vertical = _unique_by_value(
        obs for obs in observations if obs.orientation == "vertical"
    )
    if not horizontal or not vertical:
        return None

    matches: dict[tuple[float, float], OrthogonalEnvelopeEvidence] = {}
    for h_obs in horizontal:
        for v_obs in vertical:
            length_m = max(h_obs.value_m, v_obs.value_m)
            width_m = min(h_obs.value_m, v_obs.value_m)
            main_area = length_m * width_m
            if not (15.0 <= main_area <= 600.0):
                continue

            corroborated_area = main_area
            if secondary is not None:
                corroborated_area += length_m * secondary

            relative_error = abs(corroborated_area - explicit_area) / explicit_area
            if relative_error > relative_area_tolerance:
                continue

            key = (round(length_m, 3), round(width_m, 3))
            matches[key] = OrthogonalEnvelopeEvidence(
                length_m=key[0],
                width_m=key[1],
                horizontal_m=h_obs.value_m,
                vertical_m=v_obs.value_m,
                explicit_floor_area_m2=round(explicit_area, 4),
                corroborated_area_m2=round(corroborated_area, 4),
                relative_area_error=round(relative_error, 6),
                secondary_width_m=round(secondary, 4) if secondary is not None else None,
                horizontal_evidence=h_obs,
                vertical_evidence=v_obs,
            )

    if len(matches) != 1:
        return None
    return next(iter(matches.values()))
