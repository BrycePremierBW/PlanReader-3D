"""pb_structural_bay_pillar_count.py — Generic Structural Bay-to-Support Count.

A row of N equal (or near-equal) structural bays between two end supports
requires N+1 support points (columns, pillars, posts, or piers) — a
standard, generic structural fact, not specific to any building type or
project. This module detects a genuine repeated-bay dimension pattern and
derives the resulting support count from it — never from a single
dimension, a building's overall size, or any convenience default.

This addresses a real, generic failure class found independently across
two unrelated real projects during development diagnostics: pillar/
column/pier counts were entirely unextracted (0% coverage), not merely
inaccurate. Nothing in this module reads or targets any project's
expected count — it only recognizes the structural relationship between
a repeated bay pattern and the support count it implies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass
class BayCountResult:
    """Resolved (or explicitly unresolved) support count derived from a
    candidate sequence of bay-span values."""
    status: str = "unresolved"  # "resolved" | "unresolved"
    bay_count: Optional[int] = None
    support_count: Optional[int] = None
    bay_spans_m: List[float] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def derive_support_count_from_bay_chain(
    span_values_m: Sequence[float],
    min_bays: int = 2,
    relative_tolerance: float = 0.08,
) -> BayCountResult:
    """Detect a genuine repeated-bay pattern in a sequence of adjacent
    dimension values (already grouped as one collinear chain by the
    caller — this function does not itself decide chain membership) and
    derive the resulting support (column/pillar/post/pier) count.

    Requires at least `min_bays` segments whose values are all within
    `relative_tolerance` of their own mean — a real, near-uniform bay
    spacing, not a coincidental one-off value. A single segment, too few
    segments, or a sequence with genuinely dissimilar spans is
    UNRESOLVED — never guessed. `support_count = bay_count + 1`, the
    standard structural relationship for a row of equal bays between two
    end supports.
    """
    result = BayCountResult(status="unresolved")
    values = [v for v in span_values_m if v > 0]

    if len(values) < min_bays:
        result.notes.append(
            f"Only {len(values)} positive span(s) provided; at least "
            f"{min_bays} required to treat this as a repeated bay pattern."
        )
        return result

    mean_span = sum(values) / len(values)
    if mean_span <= 0:
        result.notes.append("Non-positive mean span — cannot evaluate uniformity.")
        return result

    max_relative_deviation = max(abs(v - mean_span) / mean_span for v in values)
    if max_relative_deviation > relative_tolerance:
        result.notes.append(
            f"Spans are not uniform enough to treat as repeated structural "
            f"bays (max relative deviation {max_relative_deviation:.1%} "
            f"exceeds {relative_tolerance:.1%} tolerance): {values}"
        )
        return result

    result.status = "resolved"
    result.bay_count = len(values)
    result.support_count = len(values) + 1
    result.bay_spans_m = list(values)
    return result


def find_uniform_bay_runs(
    values_m: Sequence[float],
    min_bays: int = 2,
    relative_tolerance: float = 0.08,
    bay_span_range_m: tuple[float, float] = (1.0, 8.0),
) -> List[BayCountResult]:
    """Scan a flat, ordered sequence of parsed dimension values (as a real
    extractor would produce from one page's dimension text, in the order
    they were read) for maximal contiguous runs that qualify as a
    repeated-bay pattern under `derive_support_count_from_bay_chain`,
    restricted to a broad, generic plausible bay-span range (1.0-8.0m by
    default — a structural bay smaller than 1m or larger than 8m is
    implausible for ordinary columns/pillars/posts, but this is a
    plausibility bound, not an exact-value lookup). Only maximal runs are
    returned — a run already covered by a longer run is not reported
    separately.
    """
    lo, hi = bay_span_range_m
    candidates = [v for v in values_m if lo <= v <= hi]
    if len(candidates) < min_bays:
        return []

    runs: List[BayCountResult] = []
    i = 0
    n = len(candidates)
    while i < n:
        # A window shorter than min_bays is always "unresolved" by
        # definition (see derive_support_count_from_bay_chain), so start
        # growth at the smallest window that could possibly resolve.
        j = i + min_bays
        best_end = i
        best_result: Optional[BayCountResult] = None
        while j <= n:
            window = candidates[i:j]
            res = derive_support_count_from_bay_chain(
                window, min_bays=min_bays, relative_tolerance=relative_tolerance,
            )
            if res.status == "resolved":
                best_end = j
                best_result = res
                j += 1
            else:
                break
        if best_result is not None:
            runs.append(best_result)
            i = best_end
        else:
            i += 1
    return runs
