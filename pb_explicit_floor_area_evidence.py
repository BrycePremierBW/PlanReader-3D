"""Explicit drawing floor-area evidence for PlanReader.

This module reads only drawing text.  It deliberately knows nothing about
benchmarks, projects, BOQs, expected quantities, or downstream score targets.

An architect's figured ``FLOOR AREA`` annotation is stronger quantity evidence
than reconstructing an area from a coarse outer-envelope heuristic.  The
resolver is intentionally narrow and fail-closed:

* the page must identify itself as a floor-plan / floor-layout drawing;
* the value must be explicitly labelled ``FLOOR AREA`` and carry square-metre
  units (``m2``, ``m²``, ``sqm`` or ``sq m``);
* multiple materially different floor-area annotations on one page are
  ambiguous and yield no evidence;
* multiple pages may corroborate the same area, but disagreeing pages make the
  document-level result unresolved.

Room-area labels, drawing scales, unlabelled numbers, schedules and BOQ text do
not satisfy this contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Optional, Tuple


_PLAN_CONTEXT_RE = re.compile(
    r"\b(?:floor\s+plan|floor\s+layout|ground\s+floor\s+plan|"
    r"design\s+scheme\s*\(\s*plan\s*\)|general\s+[^\n]{0,40}\s+floor\s+plan)\b",
    re.IGNORECASE,
)

# Keep the label-to-value window deliberately short.  It is long enough for
# line-broken title-block formatting such as ``AREA in M2 / FLOOR AREA / - /
# 162.69M2`` but short enough not to wander into unrelated schedule values.
_FLOOR_AREA_RE = re.compile(
    r"\bfloor\s+area\b[^\d]{0,48}"
    r"(?P<value>\d{1,6}(?:[.,]\d{1,3})?)\s*"
    r"(?P<unit>m\s*(?:2|²)|sq\.?\s*m|sqm)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExplicitFloorAreaEvidence:
    """Resolved explicit overall floor area from one or more drawing pages."""

    area_m2: float
    source_pages: Tuple[int, ...]
    raw_evidence: Tuple[str, ...]
    authority: str = "explicit_drawing_floor_area"


def _normalise_text(text: str) -> str:
    return " ".join(str(text or "").replace("\u00a0", " ").split())


def extract_explicit_floor_area_evidence(
    page_text: str,
    *,
    source_page: int,
) -> Optional[ExplicitFloorAreaEvidence]:
    """Extract one unambiguous labelled overall floor area from a plan page."""

    normalized = _normalise_text(page_text)
    if not normalized or not _PLAN_CONTEXT_RE.search(normalized):
        return None

    matches = []
    for match in _FLOOR_AREA_RE.finditer(normalized):
        try:
            value = float(match.group("value").replace(",", "."))
        except ValueError:
            continue
        # Only reject physically impossible / parser-noise values.  These are
        # broad domain sanity bounds, not project-specific tuning constants.
        if not (0.1 <= value <= 1_000_000.0):
            continue
        matches.append((round(value, 3), match.group(0).strip()))

    if not matches:
        return None

    distinct = {value for value, _raw in matches}
    if len(distinct) != 1:
        return None

    area = next(iter(distinct))
    raw = tuple(dict.fromkeys(raw_text for _value, raw_text in matches))
    return ExplicitFloorAreaEvidence(
        area_m2=area,
        source_pages=(int(source_page),),
        raw_evidence=raw,
    )


def resolve_explicit_floor_area_evidence(
    evidence: Iterable[ExplicitFloorAreaEvidence],
) -> Optional[ExplicitFloorAreaEvidence]:
    """Resolve corroborating pages; any disagreement fails closed."""

    items = list(evidence)
    if not items:
        return None

    distinct = {round(item.area_m2, 3) for item in items}
    if len(distinct) != 1:
        return None

    pages = tuple(sorted({p for item in items for p in item.source_pages}))
    raw = tuple(dict.fromkeys(raw for item in items for raw in item.raw_evidence))
    return ExplicitFloorAreaEvidence(
        area_m2=next(iter(distinct)),
        source_pages=pages,
        raw_evidence=raw,
    )
