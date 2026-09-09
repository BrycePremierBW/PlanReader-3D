"""Corroborated support-count evidence for named secondary plan areas.

This module resolves a support count only from a deliberately strong spatial
pattern on an architectural plan:

1. two independent, parallel figured-dimension chains describe the same
   repeated bay sequence and therefore the same N+1 support count;
2. a named secondary area (currently a verandah/veranda) sits spatially
   between those two chains; and
3. a short, explicit support specification (pole/column/pillar/post/pier)
   sits adjacent to the corroborating chain pair in the same horizontal band.

A page-wide support keyword or a flat repeated-number run is insufficient.
Conflicting chains, missing semantic labels, structural-note prose, or
ambiguous candidates fail closed. No benchmark IDs, expected counts, project
names, or project-specific dimensions are used here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Iterable, Optional, Sequence, Tuple

from pb_dimension_chain_evidence_extractor import extract_dimension_chains_from_page
from pb_structural_bay_pillar_count import derive_support_count_from_bay_chain


BBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class SecondaryAreaSupportEvidence:
    """Resolved, spatially corroborated support evidence."""

    zone_type: str
    support_kind: str
    support_count: int
    bay_count: int
    bay_spans_m: Tuple[float, ...]
    source_pages: Tuple[int, ...]
    chain_ids: Tuple[str, ...]
    zone_bbox: BBox
    support_bbox: BBox
    zone_text: str
    support_text: str
    confidence: float = 0.94


@dataclass(frozen=True)
class _TextBlock:
    text: str
    bbox: BBox


@dataclass(frozen=True)
class _BayChain:
    chain_id: str
    support_count: int
    bay_count: int
    bay_spans_m: Tuple[float, ...]
    bbox: BBox


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2.0


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2.0


def _horizontal_overlap(a: BBox, b: BBox) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _chain_bbox(chain: Any) -> Optional[BBox]:
    boxes = [obs.bbox for obs in chain.observations if obs.bbox is not None]
    if not boxes:
        return None
    return (
        min(float(b[0]) for b in boxes),
        min(float(b[1]) for b in boxes),
        max(float(b[2]) for b in boxes),
        max(float(b[3]) for b in boxes),
    )


def _text_blocks(page: Any) -> list[_TextBlock]:
    records: list[_TextBlock] = []
    for block in page.get_text("blocks") or []:
        text = " ".join(str(block[4]).split()).strip()
        if not text:
            continue
        records.append(
            _TextBlock(
                text=text,
                bbox=tuple(float(v) for v in block[:4]),
            )
        )
    return records


def _zone_type(text: str) -> Optional[str]:
    if re.search(r"\bveranda(?:h)?\b", text, re.IGNORECASE):
        return "verandah"
    return None


def _support_kind(text: str) -> Optional[str]:
    """Return a support noun only for a short explicit support specification.

    Numbered structural notes such as ``02. 40mm to columns above ground`` are
    intentionally rejected. A genuine support label must be short and carry
    either material/section language or a figured size.
    """
    normalized = " ".join(text.split())
    if len(normalized.split()) > 12:
        return None
    if re.match(r"^\s*\d{1,2}\s*[.)]", normalized):
        return None

    noun_match = re.search(
        r"\b(poles?|columns?|pillars?|posts?|piers?)\b",
        normalized,
        re.IGNORECASE,
    )
    if noun_match is None:
        return None

    has_spec = bool(
        re.search(
            r"\b(?:RHS|SHS|CHS|G\.?\s*I\.?|steel|timber|concrete|masonry)\b|"
            r"\b\d+(?:\.\d+)?\s*mm\b",
            normalized,
            re.IGNORECASE,
        )
    )
    if not has_spec:
        return None

    noun = noun_match.group(1).lower()
    if noun.endswith("s"):
        noun = noun[:-1]
    return noun


def _bay_chains(dimension_chains: Sequence[Any]) -> list[_BayChain]:
    resolved: list[_BayChain] = []
    for chain in dimension_chains:
        if str(getattr(chain, "orientation", "")).lower() != "horizontal":
            continue
        values = tuple(float(obs.value_m) for obs in chain.observations if obs.value_m > 0)
        # This authority-sensitive path deliberately requires at least three
        # bays. Two equal dimensions are too easy to encounter coincidentally.
        bay_result = derive_support_count_from_bay_chain(values, min_bays=3)
        if bay_result.status != "resolved" or bay_result.support_count is None:
            continue
        bbox = _chain_bbox(chain)
        if bbox is None:
            continue
        resolved.append(
            _BayChain(
                chain_id=str(chain.chain_id),
                support_count=int(bay_result.support_count),
                bay_count=int(bay_result.bay_count or len(values)),
                bay_spans_m=tuple(float(v) for v in bay_result.bay_spans_m),
                bbox=bbox,
            )
        )
    return resolved


def _same_repeated_bays(a: _BayChain, b: _BayChain) -> bool:
    if a.support_count != b.support_count or a.bay_count != b.bay_count:
        return False
    if len(a.bay_spans_m) != len(b.bay_spans_m):
        return False
    for av, bv in zip(a.bay_spans_m, b.bay_spans_m):
        mean = (abs(av) + abs(bv)) / 2.0
        if mean <= 0 or abs(av - bv) / mean > 0.03:
            return False

    aw = a.bbox[2] - a.bbox[0]
    bw = b.bbox[2] - b.bbox[0]
    if aw <= 0 or bw <= 0:
        return False
    overlap = _horizontal_overlap(a.bbox, b.bbox)
    if overlap / min(aw, bw) < 0.80:
        return False
    width_ratio = aw / bw
    return 0.80 <= width_ratio <= 1.25


def _candidate_evidence(
    *,
    page_height: float,
    zone: _TextBlock,
    zone_type: str,
    support: _TextBlock,
    support_kind: str,
    a: _BayChain,
    b: _BayChain,
    source_page: int,
) -> Optional[SecondaryAreaSupportEvidence]:
    upper, lower = sorted((a, b), key=lambda chain: _center_y(chain.bbox))
    if not _same_repeated_bays(upper, lower):
        return None

    vertical_gap = lower.bbox[1] - upper.bbox[3]
    if vertical_gap <= 0 or vertical_gap > max(95.0, page_height * 0.20):
        return None

    shared_x0 = max(upper.bbox[0], lower.bbox[0])
    shared_x1 = min(upper.bbox[2], lower.bbox[2])
    if shared_x1 <= shared_x0:
        return None

    # The named secondary area must actually sit between the corroborating
    # chain rows and within their common horizontal extent.
    zone_cx = _center_x(zone.bbox)
    zone_cy = _center_y(zone.bbox)
    if not (upper.bbox[3] <= zone_cy <= lower.bbox[1]):
        return None
    if not (shared_x0 <= zone_cx <= shared_x1):
        return None

    # The support specification must be adjacent to either chain in the same
    # horizontal band. This excludes remote general notes containing words like
    # "columns" from lending semantic authority to the bay geometry.
    support_cx = _center_x(support.bbox)
    if not (shared_x0 <= support_cx <= shared_x1 + (shared_x1 - shared_x0) * 0.10):
        return None
    vertical_distance = min(
        abs(support.bbox[1] - upper.bbox[3]),
        abs(support.bbox[3] - upper.bbox[1]),
        abs(support.bbox[1] - lower.bbox[3]),
        abs(support.bbox[3] - lower.bbox[1]),
    )
    if vertical_distance > max(35.0, page_height * 0.08):
        return None

    return SecondaryAreaSupportEvidence(
        zone_type=zone_type,
        support_kind=support_kind,
        support_count=upper.support_count,
        bay_count=upper.bay_count,
        bay_spans_m=upper.bay_spans_m,
        source_pages=(source_page,),
        chain_ids=(upper.chain_id, lower.chain_id),
        zone_bbox=zone.bbox,
        support_bbox=support.bbox,
        zone_text=zone.text,
        support_text=support.text,
    )


def extract_secondary_area_support_evidence_from_page(
    page: Any,
    *,
    source_page: int,
    dimension_chains: Optional[Sequence[Any]] = None,
) -> Optional[SecondaryAreaSupportEvidence]:
    """Resolve one unambiguous corroborated secondary-area support line."""
    blocks = _text_blocks(page)
    zones = [(block, zt) for block in blocks if (zt := _zone_type(block.text))]
    supports = [
        (block, kind)
        for block in blocks
        if (kind := _support_kind(block.text)) is not None
    ]
    if not zones or not supports:
        return None

    chains = list(dimension_chains) if dimension_chains is not None else extract_dimension_chains_from_page(
        page,
        page_num=source_page,
        view_id=f"page_{source_page}",
    )
    bays = _bay_chains(chains)
    if len(bays) < 2:
        return None

    page_height = float(page.rect.height)
    candidates: list[SecondaryAreaSupportEvidence] = []
    for i, first in enumerate(bays):
        for second in bays[i + 1 :]:
            if not _same_repeated_bays(first, second):
                continue
            for zone, zt in zones:
                for support, kind in supports:
                    evidence = _candidate_evidence(
                        page_height=page_height,
                        zone=zone,
                        zone_type=zt,
                        support=support,
                        support_kind=kind,
                        a=first,
                        b=second,
                        source_page=source_page,
                    )
                    if evidence is not None:
                        candidates.append(evidence)

    if not candidates:
        return None

    # Multiple geometric pairings that all encode the same physical support
    # line can arise from duplicated annotation rows. They are harmless only
    # when they agree on semantic zone and count. Any conflicting count or zone
    # is genuine ambiguity and must fail closed.
    semantic_keys = {(c.zone_type, c.support_count) for c in candidates}
    if len(semantic_keys) != 1:
        return None

    # Prefer the candidate whose two chain rows are vertically closest to the
    # zone/support labels; this selects the local duplicated pair without using
    # a project-specific coordinate or expected quantity.
    def proximity(candidate: SecondaryAreaSupportEvidence) -> float:
        chain_lookup = {b.chain_id: b for b in bays}
        chain_pair = [chain_lookup[cid] for cid in candidate.chain_ids]
        return sum(abs(_center_y(c.bbox) - _center_y(candidate.zone_bbox)) for c in chain_pair)

    return min(candidates, key=proximity)


def resolve_document_secondary_area_support_evidence(
    evidences: Iterable[SecondaryAreaSupportEvidence],
) -> Optional[SecondaryAreaSupportEvidence]:
    """Resolve repeated page evidence only when all pages agree.

    A multi-building package can legitimately contain different verandah
    support counts. Such a document is ambiguous for the current single-tag
    takeoff model and therefore remains unresolved rather than choosing one.
    """
    rows = list(evidences)
    if not rows:
        return None
    keys = {(row.zone_type, row.support_count) for row in rows}
    if len(keys) != 1:
        return None

    chosen = rows[0]
    pages = tuple(sorted({page for row in rows for page in row.source_pages}))
    chain_ids = tuple(dict.fromkeys(cid for row in rows for cid in row.chain_ids))
    return replace(chosen, source_pages=pages, chain_ids=chain_ids)
