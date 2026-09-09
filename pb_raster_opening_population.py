"""Resolve aggregate opening populations from explicit raster floor-plan tags.

This module is deliberately independent of benchmark identities, expected
quantities, BOQ content, and project-specific drawing layouts.

A commercial-style aggregate is only produced when one and only one OCR page
is semantically identified as a floor plan. Explicit W/D placement evidence on
other views remains evidence-only and is never summed into that population.
Multiple candidate floor-plan views fail closed because they may be duplicated,
partial, alternate, or multi-level plans.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Sequence, Tuple

from pb_portable_raster_ocr import RasterOpeningInstanceEvidence


_FLOOR_PLAN_RE = re.compile(r"\bfloor\s+plan\b", re.IGNORECASE)


@dataclass(frozen=True)
class RasterOpeningPopulationEvidence:
    trade_type: str
    quantity: int
    source_page: int
    confidence: float
    component_tags: Tuple[str, ...]
    component_counts: Tuple[Tuple[str, int], ...]


def ocr_lines_indicate_floor_plan(
    lines: Sequence[dict],
    *,
    minimum_confidence: float = 0.60,
) -> bool:
    """Return whether OCR text explicitly identifies the view as a floor plan."""
    for line in lines:
        confidence = float(line.get("confidence", 0.0))
        if confidence < minimum_confidence:
            continue
        text = " ".join(str(line.get("text", "")).split()).strip()
        if text and _FLOOR_PLAN_RE.search(text):
            return True
    return False


def resolve_single_floor_plan_opening_populations(
    evidence: Sequence[RasterOpeningInstanceEvidence],
    floor_plan_pages: Iterable[int],
) -> List[RasterOpeningPopulationEvidence]:
    """Aggregate explicit opening placements from exactly one floor-plan page.

    The supplied instance evidence is already spatially de-duplicated per tag.
    This resolver merely sums those distinct tag populations *within the one
    semantically identified floor-plan view*. It never sums across pages.
    """
    pages = sorted({int(p) for p in floor_plan_pages})
    if len(pages) != 1:
        return []
    source_page = pages[0]

    on_plan = [item for item in evidence if item.source_page == source_page]
    if not on_plan:
        return []

    grouped: dict[str, list[RasterOpeningInstanceEvidence]] = {}
    for item in on_plan:
        if item.quantity <= 0 or item.trade_type not in ("windows", "doors"):
            continue
        grouped.setdefault(item.trade_type, []).append(item)

    out: List[RasterOpeningPopulationEvidence] = []
    for trade_type, items in sorted(grouped.items()):
        # Duplicate canonical tags on the same page would make the population
        # ambiguous. The upstream extractor normally emits one record per tag,
        # but fail closed here as a second line of defence.
        tags = [item.tag for item in items]
        if len(tags) != len(set(tags)):
            continue
        component_counts = tuple(sorted((item.tag, int(item.quantity)) for item in items))
        quantity = sum(count for _, count in component_counts)
        if quantity <= 0:
            continue
        out.append(
            RasterOpeningPopulationEvidence(
                trade_type=trade_type,
                quantity=quantity,
                source_page=source_page,
                confidence=min(float(item.confidence) for item in items),
                component_tags=tuple(tag for tag, _ in component_counts),
                component_counts=component_counts,
            )
        )
    return out
