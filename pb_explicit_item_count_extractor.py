"""Generic explicit architectural item-count extraction (Phase F.16).

Parses counts that are *printed explicitly* in drawing notes or schedules,
such as ``7 No. steel columns`` or ``casement windows W3 - 11 Nos``.
It deliberately does not infer counts from dimensions, repeated symbols, or
project/BOQ context.  A quantity is returned only when an integer is joined
to an unambiguous ``No/No./Nos`` marker in the same short text clause as a
supported physical-item phrase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class ExplicitItemCount:
    tag: str
    trade_type: str
    quantity: int
    item_text: str
    evidence_text: str
    character_span: Tuple[int, int]


_ITEM_PATTERNS: Sequence[Tuple[re.Pattern[str], str, str]] = (
    (re.compile(r"\b(?:chs|rhs|shs|steel|concrete|r\.?c\.?)?\s*columns?\b", re.I), "structural_columns", "structure"),
    (re.compile(r"\b(?:chs|rhs|shs|steel|concrete|verandah)?\s*pillars?\b", re.I), "verandah_pillars", "structure"),
    (re.compile(r"\b(?:masonry|brick|stone|concrete)?\s*piers?\b", re.I), "masonry_piers", "structure"),
    (re.compile(r"\b(?:steel|timber|roof)?\s*trusses?\b", re.I), "roof_trusses", "structure"),
    (re.compile(r"\b(?:steel\s+casement|aluminium|aluminum|timber|fixed|sliding)?\s*windows?\b", re.I), "windows", "windows"),
    (re.compile(r"\b(?:steel\s+casement|flush|panelled|paneled|timber|steel|double|single)?\s*doors?\b", re.I), "doors", "doors"),
)

_COUNT_PATTERN = re.compile(r"(?<![\d.])(?P<count>\d{1,3})\s*(?:No\.?s?|NOS?)(?![A-Za-z])", re.I)
_TAG_PATTERN = re.compile(r"\b(?P<tag>[WD])\s*[-.]?\s*(?P<number>\d{1,3})(?!\d)", re.I)
_CLAUSE_SPLIT = re.compile(r"[\n;|]+")

# A count adjacent to hardware/fitting terms (e.g. "door with 3 nos. butt
# hinges") is a fitting quantity, not an item count, and must never be
# read as one -- found against a real project PDF whose PyMuPDF text
# block was itself truncated to "...batten door with 3 nos. butt" (the
# word "hinges" fell into a separate block), so "butt" alone must be
# enough to disqualify a clause; requiring "butt hinge"/"hinge" together
# would miss this real case.
_HARDWARE_PATTERN = re.compile(
    r"\bbutt\b|\bhinge\b|\bfastener\b|\blever\s*lock\b|\bironmongery\b|\bscrew\b|\bbolt\b|\bcleat\b",
    re.I,
)


def _specific_tag(default_tag: str, clause: str) -> str:
    """Preserve a printed W/D mark when its trade agrees with the item."""
    match = _TAG_PATTERN.search(clause)
    if not match:
        return default_tag
    prefix = match.group("tag").upper()
    if (default_tag == "windows" and prefix == "W") or (default_tag == "doors" and prefix == "D"):
        return f"{prefix}{int(match.group('number'))}"
    return default_tag


def extract_explicit_item_counts(text: str, *, max_item_distance: int = 96) -> List[ExplicitItemCount]:
    """Return directly stated item counts from short drawing-note clauses.

    Ambiguous clauses fail closed: they are ignored when they contain more
    than one count marker or more than one distinct supported item class.
    Counts must be positive, and an item phrase must be spatially close in
    text to the count marker.  Results are deduplicated by tag and quantity;
    contradictory quantities for the same tag are removed entirely.
    """
    candidates: List[ExplicitItemCount] = []
    offset = 0
    for raw_clause in _CLAUSE_SPLIT.split(text or ""):
        clause = re.sub(r"\s+", " ", raw_clause).strip()
        clause_start = text.find(raw_clause, offset) if raw_clause else offset
        if clause_start < 0:
            clause_start = offset
        offset = clause_start + len(raw_clause)
        if not clause:
            continue
        if _HARDWARE_PATTERN.search(clause):
            continue

        counts = list(_COUNT_PATTERN.finditer(clause))
        item_hits = [(m, tag, trade) for pattern, tag, trade in _ITEM_PATTERNS for m in pattern.finditer(clause)]
        distinct_items = {(tag, trade) for _, tag, trade in item_hits}
        if len(counts) != 1 or len(distinct_items) != 1:
            continue

        count_match = counts[0]
        item_match, default_tag, trade_type = min(
            item_hits,
            key=lambda hit: min(abs(hit[0].start() - count_match.end()), abs(count_match.start() - hit[0].end())),
        )
        distance = max(0, item_match.start() - count_match.end(), count_match.start() - item_match.end())
        quantity = int(count_match.group("count"))
        if quantity <= 0 or distance > max_item_distance:
            continue

        tag = _specific_tag(default_tag, clause)
        candidates.append(ExplicitItemCount(
            tag=tag,
            trade_type=trade_type,
            quantity=quantity,
            item_text=item_match.group(0).strip(),
            evidence_text=clause,
            character_span=(clause_start + min(count_match.start(), item_match.start()),
                            clause_start + max(count_match.end(), item_match.end())),
        ))

    grouped: dict[str, List[ExplicitItemCount]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.tag, []).append(candidate)

    resolved: List[ExplicitItemCount] = []
    for group in grouped.values():
        quantities = {candidate.quantity for candidate in group}
        if len(quantities) == 1:
            resolved.append(group[0])
    return resolved
