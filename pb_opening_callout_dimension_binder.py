"""Bind unique opening-size callouts onto already identified openings.

Architectural elevations often print ``1,000mm x 2,100mm timber batten
door`` next to an unlabeled plan identity that was counted from a swing
or stamp.  Phase F.9 can only deduct an opening when *both* width and
height are known.  This module never mints W/D tags from those callouts;
it only attaches a size when every door callout agrees on one pair and
exactly one door identity is still missing two dimensions.

Window callouts are parsed so they can be rejected: two disagreeing
window sizes must not be invented as W1/W2, and a unique window size is
not applied to a door.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from pb_opening_tag_normalization import normalize_opening_tag

_SIZE_RE = re.compile(
    r"(?P<width>\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*[xX×]\s*"
    r"(?P<height>\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm",
    re.IGNORECASE,
)
_DOOR_RE = re.compile(r"\bdoors?\b", re.I)
_WINDOW_RE = re.compile(r"\bwindows?\b", re.I)
_MIN_OPENING_MM = 400.0
_MAX_OPENING_MM = 6000.0
_TAIL_CHARS = 80


@dataclass(frozen=True)
class OpeningSizeCallout:
    kind: str  # "door" or "window"
    width_mm: float
    height_mm: float
    evidence_text: str


def _to_mm(raw: str) -> float:
    return float(raw.replace(",", "").replace(".", ""))


def parse_opening_size_callouts(text: str) -> List[OpeningSizeCallout]:
    """Return WxH callouts whose tail names a door or a window, not both."""
    if not text:
        return []
    collapsed = re.sub(r"\s+", " ", text)
    found: List[OpeningSizeCallout] = []
    for match in _SIZE_RE.finditer(collapsed):
        width_mm = _to_mm(match.group("width"))
        height_mm = _to_mm(match.group("height"))
        if not (
            _MIN_OPENING_MM <= width_mm <= _MAX_OPENING_MM
            and _MIN_OPENING_MM <= height_mm <= _MAX_OPENING_MM
        ):
            continue
        tail = collapsed[match.end(): match.end() + _TAIL_CHARS]
        nxt = _SIZE_RE.search(tail)
        if nxt is not None:
            tail = tail[: nxt.start()]
        has_door = bool(_DOOR_RE.search(tail))
        has_window = bool(_WINDOW_RE.search(tail))
        if has_door == has_window:
            continue
        found.append(
            OpeningSizeCallout(
                kind="door" if has_door else "window",
                width_mm=width_mm,
                height_mm=height_mm,
                evidence_text=(match.group(0) + tail).strip(),
            )
        )
    return found


def unique_door_size_mm(callouts: Sequence[OpeningSizeCallout]) -> Optional[Tuple[float, float]]:
    """Return one (width, height) when every door callout agrees; else None."""
    door_sizes = {
        (round(item.width_mm), round(item.height_mm))
        for item in callouts
        if item.kind == "door"
    }
    if len(door_sizes) != 1:
        return None
    width_mm, height_mm = next(iter(door_sizes))
    return float(width_mm), float(height_mm)


def _dimension_mm(value: float) -> float:
    return value * 1000.0 if 0 < value <= 50.0 else value


def _missing_two_dimensions(dimensions: Optional[Sequence[float]]) -> bool:
    usable = [value for value in (dimensions or []) if value is not None and value > 0]
    return len(usable) < 2


def _conflicts_with_existing(dimensions: Optional[Sequence[float]], width_mm: float, height_mm: float) -> bool:
    usable = [_dimension_mm(value) for value in (dimensions or []) if value is not None and value > 0]
    if not usable:
        return False
    existing = usable[0]
    return abs(existing - width_mm) > 2.0 and abs(existing - height_mm) > 2.0


def bind_unique_door_callout_dimensions(
    predictions: Sequence[object],
    texts: Iterable[str],
) -> int:
    """Attach a unique door WxH callout onto exactly one dimensionless D# identity.

    Mutates matching prediction objects in place.  Returns how many identities
    were bound (0 or 1).  Window callouts never mint identities and never bind
    onto doors.  Two door identities, two disagreeing door sizes, a lumped
    ``doors_complete`` total, or a conflicting already-bound width all fail
    closed.
    """
    callouts = parse_opening_size_callouts("\n".join(texts))
    size = unique_door_size_mm(callouts)
    if size is None:
        return 0
    width_mm, height_mm = size

    candidates: List[object] = []
    for pred in predictions:
        tag = str(getattr(pred, "tag", "") or "")
        trade = str(getattr(pred, "trade_type", "") or "")
        if trade != "doors":
            continue
        norm = normalize_opening_tag(tag)
        if norm is None or norm.trade_type != "doors":
            continue
        if not _missing_two_dimensions(getattr(pred, "dimensions", None)):
            continue
        if _conflicts_with_existing(getattr(pred, "dimensions", None), width_mm, height_mm):
            return 0
        candidates.append(pred)

    if len(candidates) != 1:
        return 0

    pred = candidates[0]
    pred.dimensions = [width_mm, height_mm]
    metadata = getattr(pred, "metadata", None)
    if isinstance(metadata, dict):
        metadata["callout_dimension_binding"] = "unique_door_wxh"
    return 1
