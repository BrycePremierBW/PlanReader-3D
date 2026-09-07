"""pb_dimension_chain_evidence_extractor.py — Spatial Dimension-Chain
Reconstruction from Real PDF Word Positions (Phase F.15).

F.13 (pb_dimension_graph_constraint_engine.py) resolves geometry from
DimensionChain evidence, but its own docstring flags an explicit scope
limit: it "operates on already-tokenized DimensionObservation records, not
on raw PDF bytes" — wiring a real extractor to emit those records was
left as a separate, later PR. This module is that wiring, for the text
layer (native PDF text, not vector/OCR).

The reason this needs real *positional* reconstruction, not another flat
text-order regex pass: a real drawing sheet often stacks several distinct
dimension lines (an overall dimension, several room-by-room dimension
strings, a structural grid) at different heights on the page. PyMuPDF's
plain reading-order text interleaves all of them into one token stream —
verified directly against a real project PDF, where a genuine
"150 / 9,850 / 150" wall-enclosed room span was hopelessly jumbled
together with several *other* unrelated dimension lines in flat text
order. Grouping words by row position (`page.get_text("words")`, y-band
clustering) untangles this correctly, because collinear figures on one
leader line are, physically, at the same page height.

Corroboration requirement: a single chain's own classify_chain_segments()
can mistake a coincidental plausible-range endpoint pair for a genuine
wall-thickness bracket — found during development, an elevation's
window-bay spacing row ("325 / 2,900 / 350 / 3,000 / 360 / 2,900 / 315")
independently satisfies F.13's wall-thickness plausibility range at both
ends purely by coincidence, despite not being a wall at all.
resolve_corroborated_wall_thickness_m() therefore requires the same
thickness value to be independently produced by at least two distinct
row-derived chains before treating it as resolved — a real reliability
check on top of what F.13 already does per chain, not a tuned threshold.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pb_dimension_graph_constraint_engine import (
    DimensionChain,
    DimensionObservation,
    DimensionOrientation,
    _PLAUSIBLE_DIMENSION_RANGE_MM,
    _YEAR_PATTERN,
    classify_chain_segments,
)

_DIM_WORD_RE = re.compile(r"^\d{1,2}[,.]?\d{3}$|^\d{2,4}$")


def _parse_dimension_word_mm(word: str) -> Optional[float]:
    """Parse one already-shape-matched word token to a millimetre value,
    or None if it fails the plausibility range or reads as a bare year."""
    cleaned = word.replace(",", "").replace(".", "")
    if _YEAR_PATTERN.match(cleaned):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    lo, hi = _PLAUSIBLE_DIMENSION_RANGE_MM
    if lo <= value <= hi:
        return value
    return None


def extract_dimension_chains_from_page(
    page: Any,
    *,
    page_num: int,
    view_id: str = "",
    y_tolerance_pt: float = 3.0,
) -> List[DimensionChain]:
    """Reconstruct genuine collinear DimensionChains from one PDF page's
    word bounding boxes. Words are grouped into rows by y-position (a
    small, fixed point tolerance — a physical-layout property of how
    tightly figures align on one leader line, not tuned to any project),
    then each row is sorted left-to-right into one chain. A row with no
    dimension-shaped words contributes no chain."""
    words = page.get_text("words")

    rows: Dict[float, List[Tuple[Any, float]]] = {}
    for w in words:
        token = w[4]
        if not _DIM_WORD_RE.match(token):
            continue
        value_mm = _parse_dimension_word_mm(token)
        if value_mm is None:
            continue
        key = round(w[1] / y_tolerance_pt) * y_tolerance_pt
        rows.setdefault(key, []).append((w, value_mm))

    chains: List[DimensionChain] = []
    for idx, y_key in enumerate(sorted(rows)):
        row = sorted(rows[y_key], key=lambda item: item[0][0])
        observations = [
            DimensionObservation(
                dimension_id=f"dimword_p{page_num}_{idx}_{seq}",
                source_page=page_num,
                view_id=view_id,
                bbox=(w[0], w[1], w[2], w[3]),
                raw_text=w[4],
                value=value_mm,
                unit="mm",
                orientation=DimensionOrientation.HORIZONTAL.value,
            )
            for seq, (w, value_mm) in enumerate(row)
        ]
        chains.append(DimensionChain(
            chain_id=f"chain_p{page_num}_{idx}",
            view_id=view_id,
            source_page=page_num,
            orientation=DimensionOrientation.HORIZONTAL.value,
            observations=observations,
        ))
    return chains


def _is_degenerate_repeat(chain: DimensionChain) -> bool:
    """A chain whose segments are all numerically identical (e.g. a
    repeated "200 200 200" rebar-spacing or fill-thickness callout on a
    structural detail sheet) is not a wall-span-wall bracket — a genuine
    wall-enclosed room dimension has a *distinct* span between two
    thickness values, not three-or-more copies of the same figure. Found
    against a real project PDF: a Section F-F reinforcement detail's
    repeated "200" spacing callouts independently satisfied the
    wall-thickness plausibility range at both ends of a 6-segment run."""
    values = {round(o.value_m, 4) for o in chain.observations}
    return len(values) <= 1


def resolve_corroborated_wall_thickness_m(
    chains: Sequence[DimensionChain],
    *,
    agreement_tolerance_m: float = 0.02,
) -> Optional[float]:
    """Resolve a genuine wall thickness only when at least two
    independent chain-derived candidates agree within tolerance. Never
    trusts a single chain's classify_chain_segments() result alone."""
    candidates: List[float] = []
    for chain in chains:
        if _is_degenerate_repeat(chain):
            continue
        thickness = classify_chain_segments(chain).get("wall_thickness_m")
        if thickness is None:
            continue
        first_v, last_v = thickness
        if abs(first_v - last_v) <= agreement_tolerance_m:
            candidates.append((first_v + last_v) / 2.0)
        else:
            candidates.append(first_v)
            candidates.append(last_v)

    if len(candidates) < 2:
        return None

    best_cluster: List[float] = []
    for c in candidates:
        cluster = [x for x in candidates if abs(x - c) <= agreement_tolerance_m]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) < 2:
        return None
    return round(sum(best_cluster) / len(best_cluster), 4)
