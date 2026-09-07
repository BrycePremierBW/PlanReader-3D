"""pb_level_datum_extraction.py — Roof/Floor Level Datum Parsing (Phase F.14).

Sections and elevations conventionally annotate vertical datums directly on
the drawing: a roof/ceiling/beam level and a floor/ground level, each given
as a signed value relative to a shared reference (e.g. "Roof Level +3,325",
"Ground floor +175"). Together, two such datums are a real figured
measurement of wall/room height — genuine drawing evidence, not a
convenience assumption.

This module only recognizes that annotation pattern (a level-type label
immediately followed by a signed numeric value) and turns it into
pb_dimension_graph_constraint_engine.LevelMarker records, which
resolve_wall_height() (F.13, already merged) turns into a resolved height —
or leaves unresolved when the evidence does not constrain it. Nothing here
invents a value: a page with no level annotation yields no markers, and no
default height is ever substituted.

Deliberately label-then-value only, never value-then-label: a value that
merely precedes a level label somewhere later in flat reading order is not
reliably the value *for* that label — real drawings pack unrelated
dimension strings and level annotations onto the same line, and a
value-then-label scan was found (against real project PDFs) to attribute
an unrelated nearby dimension chain value to the label purely because it
happened to sit right before it in text order. Every genuine occurrence
observed in real drawings so far is label-then-value; requiring that
direction only trades recall for correctness deliberately.

Number format follows the same convention already used throughout this
extractor's other dimension parsing (pb_dimension_graph_constraint_engine.
parse_dimension_tokens_from_text, GenericPlanReaderExtractor's own
parsed_dims_m): a comma is a thousands separator on a millimetre value
(e.g. "3,325" = 3325mm), never a decimal point. A level value additionally
carries an explicit sign relative to the datum (e.g. "+3,325", "-150"). A
level string that does not match this convention (a bare decimal like
"+3.325") is deliberately not recognized here rather than guessed at.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from pb_dimension_graph_constraint_engine import LevelMarker

# marker_type -> the label phrase(s) that identify that datum. Kept as
# separate keywords (not lumped into one "roof-like"/"floor-like" pattern)
# so the resulting LevelMarker.marker_type reflects which label was
# actually printed on the drawing, not a guess.
_LEVEL_LABELS: Dict[str, Tuple[str, ...]] = {
    "roof": (r"roof\s*level",),
    "ceiling": (r"ceiling\s*level",),
    "beam": (r"beam\s*level",),
    "floor": (r"floor\s*level",),
    # "ground floor" is excluded when followed by "plan" -- "GROUND FLOOR
    # PLAN" is a view title (like "ROOF PLAN"), not a level datum.
    "ground": (r"ground\s*level", r"ground\s*floor(?!\s*plan\b)"),
}

# The trailing negative lookahead rejects a decimal-point value (e.g.
# "+3.325") outright rather than silently mis-parsing its leading digits
# (e.g. capturing just "+3") -- a format this module does not recognize
# must yield no marker, never a wrong one.
_LEVEL_VALUE = r"([+\-]?\d{1,3}(?:,\d{3})?)(?!\.\d)"


def _parse_level_value_m(raw: str) -> float:
    """Convert a signed, comma-grouped millimetre level string to metres."""
    stripped = raw.strip()
    sign = -1.0 if stripped.startswith("-") else 1.0
    digits = stripped.lstrip("+-").replace(",", "")
    return sign * float(digits) / 1000.0


def find_level_markers(
    page_text: str,
    *,
    source_page: int,
    view_id: str = "",
) -> List[LevelMarker]:
    """Parse roof/ceiling/beam/floor/ground level datum annotations
    ("Roof Level +3,325", "Ground floor +175") from one page's text.
    Returns one LevelMarker per match; a page with no such annotation
    returns an empty list."""
    norm = re.sub(r"\s+", " ", page_text)
    markers: List[LevelMarker] = []
    seq = 0

    for marker_type, label_patterns in _LEVEL_LABELS.items():
        for label_pat in label_patterns:
            # Only ":" is an optional label/value separator -- "-" is not,
            # since it would otherwise be ambiguously consumed as that
            # separator instead of as a negative value's sign.
            for m in re.finditer(rf"{label_pat}\s*:?\s*{_LEVEL_VALUE}", norm, re.I):
                markers.append(LevelMarker(
                    marker_id=f"level_p{source_page}_{marker_type}_{seq}",
                    level_m=_parse_level_value_m(m.group(1)),
                    raw_text=m.group(0).strip(),
                    marker_type=marker_type,
                    view_id=view_id,
                    source_page=source_page,
                    scope_id=None,
                ))
                seq += 1

    return markers
