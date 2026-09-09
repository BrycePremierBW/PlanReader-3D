"""Spatial evidence for combined ``WD`` opening-card identities.

Some CAD exports visually show a combined opening identity such as ``WD 01``
while splitting the glyphs into separate native text runs (for example a
``W 01`` block plus an adjacent ``D`` word).  ``WD`` is deliberately *not*
globally interpreted as window or door: the identity is emitted only when the
same card independently contains multiple window-specific field labels and no
conflicting door-field label.

This module is source-evidence only.  It knows nothing about benchmark IDs,
project names, expected quantities, BOQs, or score targets.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Optional, Tuple

import fitz


BBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class ContextualWDCardEvidence:
    """One resolved literal WD card identity with an explicit total."""

    tag: str
    quantity: float
    source_page: int
    bbox: BBox
    raw_tag: str
    witnesses: Tuple[str, ...]

    @property
    def evidence_text(self) -> str:
        return (
            f"{self.raw_tag}; Overall Quantity: {self.quantity:g}; "
            f"window fields: {', '.join(self.witnesses)}"
        )


def _center(bb: BBox) -> Tuple[float, float]:
    return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)


def _height(bb: BBox) -> float:
    return max(1.0, bb[3] - bb[1])


def _union(*bbs: BBox) -> BBox:
    return (
        min(bb[0] for bb in bbs),
        min(bb[1] for bb in bbs),
        max(bb[2] for bb in bbs),
        max(bb[3] for bb in bbs),
    )


def _intersects(a: BBox, b: BBox) -> bool:
    return (
        min(a[2], b[2]) > max(a[0], b[0])
        and min(a[3], b[3]) > max(a[1], b[1])
    )


def _block_records(page: fitz.Page) -> List[Tuple[str, BBox, int]]:
    records: List[Tuple[str, BBox, int]] = []
    for block in page.get_text("blocks") or []:
        text = " ".join(str(block[4]).split()).strip()
        if not text:
            continue
        records.append(
            (
                text,
                tuple(float(v) for v in block[:4]),
                int(block[5]) if len(block) > 5 else -1,
            )
        )
    return records


def _quantity_candidates(records: List[Tuple[str, BBox, int]]) -> List[Tuple[float, BBox]]:
    quantities: List[Tuple[float, BBox]] = []
    for text, bbox, _block_no in records:
        lower = text.lower()
        if "overall" not in lower or "quantity" not in lower:
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*$", text)
        if not match:
            continue
        value = float(match.group(1))
        if value > 0:
            quantities.append((value, bbox))
    return quantities


def _direct_wd_candidates(records: List[Tuple[str, BBox, int]]) -> List[Tuple[str, BBox, str]]:
    candidates: List[Tuple[str, BBox, str]] = []
    for text, bbox, _block_no in records:
        if len(text) > 16:
            continue
        match = re.fullmatch(
            r"\s*W\s*D\s*[-_. ]?\s*0*(\d{1,3})\s*",
            text,
            re.IGNORECASE,
        )
        if match and int(match.group(1)) > 0:
            candidates.append((f"WD{int(match.group(1))}", bbox, text))
    return candidates


def _fragmented_wd_candidates(page: fitz.Page) -> List[Tuple[str, BBox, str]]:
    """Reconstruct visually contiguous W + D + number text fragments."""
    token_words: List[Tuple[str, BBox]] = [
        (
            str(word[4]).strip(),
            (float(word[0]), float(word[1]), float(word[2]), float(word[3])),
        )
        for word in (page.get_text("words") or [])
    ]
    candidates: List[Tuple[str, BBox, str]] = []
    for w_text, w_bbox in token_words:
        if w_text.upper() != "W":
            continue
        w_cy = _center(w_bbox)[1]
        for d_text, d_bbox in token_words:
            if d_text.upper() != "D":
                continue
            scale = max(_height(w_bbox), _height(d_bbox))
            if abs(_center(d_bbox)[1] - w_cy) > max(2.0, 0.35 * scale):
                continue
            gap_wd = d_bbox[0] - w_bbox[2]
            if gap_wd < -0.20 * scale or gap_wd > 1.20 * scale:
                continue
            for number_text, number_bbox in token_words:
                if not re.fullmatch(r"0*\d{1,3}", number_text):
                    continue
                number = int(number_text)
                if number <= 0:
                    continue
                scale_all = max(scale, _height(number_bbox))
                if abs(_center(number_bbox)[1] - w_cy) > max(2.0, 0.35 * scale_all):
                    continue
                gap_dn = number_bbox[0] - d_bbox[2]
                if gap_dn < -0.20 * scale_all or gap_dn > 1.60 * scale_all:
                    continue
                candidates.append(
                    (
                        f"WD{number}",
                        _union(w_bbox, d_bbox, number_bbox),
                        f"W D {number_text}",
                    )
                )
    return candidates


_WINDOW_WITNESS_PATTERNS = {
    "panel": re.compile(r"\bwindow\s+panel\b", re.IGNORECASE),
    "frame": re.compile(r"\bwindow\s+frame\b", re.IGNORECASE),
    "leaf": re.compile(r"\bwindow\s+leaf\s+type\b", re.IGNORECASE),
    "stay": re.compile(r"\bwindow\s+stay\s+type\b", re.IGNORECASE),
}
_DOOR_CONFLICT_RE = re.compile(
    r"\bdoor\s+(?:panel|frame|leaf\s+type)\b",
    re.IGNORECASE,
)


def _window_witnesses(
    records: List[Tuple[str, BBox, int]],
    tag_bbox: BBox,
    quantity_bbox: BBox,
) -> Optional[Tuple[str, ...]]:
    tag_h = _height(tag_bbox)
    tag_w = max(1.0, tag_bbox[2] - tag_bbox[0])
    region = (
        min(tag_bbox[0], quantity_bbox[0]) - max(2.0 * tag_h, 0.5 * tag_w),
        tag_bbox[1] - max(1.5 * tag_h, 4.0),
        max(tag_bbox[2], quantity_bbox[2]) + max(2.0 * tag_h, 0.5 * tag_w),
        quantity_bbox[3] + max(tag_h, 4.0),
    )
    witnesses = set()
    door_conflict = False
    for text, bbox, _block_no in records:
        if not _intersects(bbox, region):
            continue
        if _DOOR_CONFLICT_RE.search(text):
            door_conflict = True
        for name, pattern in _WINDOW_WITNESS_PATTERNS.items():
            if pattern.search(text):
                witnesses.add(name)
    if door_conflict or len(witnesses) < 2:
        return None
    return tuple(sorted(witnesses))


def _association_score(tag_bbox: BBox, quantity_bbox: BBox) -> Optional[float]:
    tx0, _ty0, tx1, ty1 = tag_bbox
    _qx0, qy0, _qx1, _qy1 = quantity_bbox
    if ty1 > qy0:
        return None
    tag_h = _height(tag_bbox)
    tag_w = max(1.0, tx1 - tx0)
    vertical_gap = qy0 - ty1
    if vertical_gap > max(12.0 * tag_h, 4.0 * tag_w):
        return None
    tag_cx, _ = _center(tag_bbox)
    quantity_cx, _ = _center(quantity_bbox)
    horizontal_delta = abs(quantity_cx - tag_cx)
    if horizontal_delta > max(12.0 * tag_h, 8.0 * tag_w):
        return None
    return vertical_gap + 0.25 * horizontal_delta


def extract_contextual_wd_card_evidence(
    page: fitz.Page,
    *,
    source_page: int,
) -> List[ContextualWDCardEvidence]:
    """Return unambiguous literal WD cards proven by same-card window fields."""
    records = _block_records(page)
    quantities = _quantity_candidates(records)
    raw_candidates = _direct_wd_candidates(records) + _fragmented_wd_candidates(page)

    candidates: List[Tuple[str, BBox, str]] = []
    seen = set()
    for tag, bbox, raw in raw_candidates:
        cx, cy = _center(bbox)
        key = (tag, round(cx, 1), round(cy, 1))
        if key in seen:
            continue
        seen.add(key)
        candidates.append((tag, bbox, raw))

    resolved: List[ContextualWDCardEvidence] = []
    for quantity, quantity_bbox in quantities:
        matches = []
        for tag, tag_bbox, raw_tag in candidates:
            score = _association_score(tag_bbox, quantity_bbox)
            if score is None:
                continue
            witnesses = _window_witnesses(records, tag_bbox, quantity_bbox)
            if witnesses is None:
                continue
            matches.append((score, tag, tag_bbox, raw_tag, witnesses))
        matches.sort(key=lambda item: item[0])
        if not matches:
            continue
        if len(matches) > 1:
            first, second = matches[0], matches[1]
            if abs(second[0] - first[0]) <= max(2.0, 0.15 * max(first[0], 1.0)):
                continue
        _score, tag, _tag_bbox, raw_tag, witnesses = matches[0]
        resolved.append(
            ContextualWDCardEvidence(
                tag=tag,
                quantity=quantity,
                source_page=int(source_page),
                bbox=quantity_bbox,
                raw_tag=raw_tag,
                witnesses=witnesses,
            )
        )
    return resolved
