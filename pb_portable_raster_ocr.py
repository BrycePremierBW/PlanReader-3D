"""Portable raster OCR helpers for drawing evidence recovery.

This module is source-evidence only. It never reads benchmark definitions,
expected quantities, project identities, or BOQ content.

Two deliberately separate concerns live here:
1. a lazy RapidOCR backend for platforms where Windows OCR is unavailable;
2. spatial de-duplication / counting of *explicit* W/D tag detections.

Opening-instance counting is intentionally conservative. A page is eligible
only when at least one explicit tag repeats after spatial de-duplication,
which distinguishes placement-rich drawing views from a simple legend or
schedule listing each type once. Counts from multiple pages are never summed:
they must agree or the tag stays unresolved.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image

from pb_opening_tag_normalization import normalize_opening_tag

try:
    import numpy as np
    from rapidocr import RapidOCR
    _HAS_RAPIDOCR = True
except Exception:
    np = None  # type: ignore[assignment]
    RapidOCR = None  # type: ignore[assignment]
    _HAS_RAPIDOCR = False


@dataclass(frozen=True)
class RasterOCRDetection:
    text: str
    bounding_box: Tuple[float, float, float, float]
    confidence: float
    source_page: int = 1


@dataclass(frozen=True)
class RasterOpeningInstanceEvidence:
    tag: str
    trade_type: str
    quantity: int
    source_page: int
    confidence: float
    bounding_boxes: Tuple[Tuple[float, float, float, float], ...]


_rapidocr_engine: Any = None
_TAG_ONLY_RE = re.compile(
    r"^\s*(?:WINDOW|WIN|W|DOOR|DR|D)\s*[-_.]?\s*0*\d{1,3}\s*$",
    re.IGNORECASE,
)


def portable_ocr_available() -> bool:
    return _HAS_RAPIDOCR


def _get_rapidocr_engine() -> Any:
    global _rapidocr_engine
    if not _HAS_RAPIDOCR or RapidOCR is None:
        return None
    if _rapidocr_engine is None:
        _rapidocr_engine = RapidOCR()
    return _rapidocr_engine


def recognize_pil_with_rapidocr(image: Image.Image) -> List[Dict[str, Any]]:
    """Return RapidOCR detections in the DrawingOCREngine line schema.

    Import/model initialization is lazy so installations that use Windows OCR
    do not pay the portable backend startup cost. Any backend error fails
    closed by returning no evidence.
    """
    engine = _get_rapidocr_engine()
    if engine is None or np is None:
        return []
    try:
        result = engine(np.asarray(image.convert("RGB")))
        texts = getattr(result, "txts", None) or []
        scores = getattr(result, "scores", None) or []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        out: List[Dict[str, Any]] = []
        for idx, raw in enumerate(texts):
            text = " ".join(str(raw).split()).strip()
            if not text or idx >= len(boxes):
                continue
            pts = boxes[idx].tolist() if hasattr(boxes[idx], "tolist") else boxes[idx]
            if not pts:
                continue
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            if not xs or not ys:
                continue
            confidence = float(scores[idx]) if idx < len(scores) else 0.0
            out.append({
                "text": text,
                "bounding_box": [min(xs), min(ys), max(xs), max(ys)],
                "confidence": max(0.0, min(1.0, confidence)),
            })
        return out
    except Exception:
        return []


def _bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax0, ay0, ax1, ay1 = map(float, a[:4])
    bx0, by0, bx1, by1 = map(float, b[:4])
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


def deduplicate_tiled_ocr_lines(
    lines: Sequence[Dict[str, Any]],
    *,
    overlap_iou: float = 0.35,
) -> List[Dict[str, Any]]:
    """Remove duplicate OCR detections created by overlapping raster tiles.

    De-duplication requires the same normalized text plus substantial spatial
    overlap (or virtually identical centres). Separate physical placements of
    the same W/D tag therefore remain separate evidence.
    """
    kept: List[Dict[str, Any]] = []
    ordered = sorted(lines, key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
    for line in ordered:
        text = " ".join(str(line.get("text", "")).split()).strip()
        bbox = line.get("bounding_box")
        if not text or not bbox or len(bbox) < 4:
            continue
        x0, y0, x1, y1 = map(float, bbox[:4])
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        duplicate = False
        for prior in kept:
            if text.casefold() != str(prior.get("text", "")).casefold():
                continue
            pb = prior["bounding_box"]
            pcx = (float(pb[0]) + float(pb[2])) / 2.0
            pcy = (float(pb[1]) + float(pb[3])) / 2.0
            if _bbox_iou((x0, y0, x1, y1), pb) >= overlap_iou or (
                abs(cx - pcx) <= 5.0 and abs(cy - pcy) <= 5.0
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append({
                "text": text,
                "bounding_box": [x0, y0, x1, y1],
                "confidence": float(line.get("confidence", 0.0)),
            })
    return kept


def extract_opening_instance_evidence(
    lines: Sequence[Dict[str, Any]],
    *,
    source_page: int,
    minimum_confidence: float = 0.80,
) -> List[RasterOpeningInstanceEvidence]:
    """Count distinct explicit W/D placements on one raster drawing page.

    Only short tag-only OCR detections are counted. Schedule rows containing a
    figured quantity remain the responsibility of DrawingEvidenceParser.
    A page must contain at least one repeated canonical tag after spatial
    de-duplication; otherwise it is indistinguishable from a type legend and
    no instance quantity is emitted.
    """
    deduped = deduplicate_tiled_ocr_lines(lines)
    grouped: Dict[str, List[RasterOCRDetection]] = {}
    trades: Dict[str, str] = {}

    for line in deduped:
        text = str(line.get("text", "")).strip()
        confidence = float(line.get("confidence", 0.0))
        bbox = line.get("bounding_box")
        if confidence < minimum_confidence or not bbox or len(bbox) < 4:
            continue
        if not _TAG_ONLY_RE.fullmatch(text):
            continue
        normalized = normalize_opening_tag(text)
        if normalized is None:
            continue
        grouped.setdefault(normalized.tag, []).append(
            RasterOCRDetection(
                text=text,
                bounding_box=tuple(map(float, bbox[:4])),
                confidence=confidence,
                source_page=source_page,
            )
        )
        trades[normalized.tag] = normalized.trade_type

    if not grouped or max(len(v) for v in grouped.values()) < 2:
        return []

    out: List[RasterOpeningInstanceEvidence] = []
    for tag, detections in sorted(grouped.items()):
        out.append(
            RasterOpeningInstanceEvidence(
                tag=tag,
                trade_type=trades[tag],
                quantity=len(detections),
                source_page=source_page,
                confidence=min(d.confidence for d in detections),
                bounding_boxes=tuple(d.bounding_box for d in detections),
            )
        )
    return out


def resolve_cross_page_opening_instances(
    evidence: Sequence[RasterOpeningInstanceEvidence],
) -> List[RasterOpeningInstanceEvidence]:
    """Resolve per-page instance counts without ever summing across views.

    A tag seen on one eligible page is usable. If the same tag appears on
    multiple pages, every page must independently agree on its count; otherwise
    the tag is omitted (manual-review/fail-closed behavior).
    """
    grouped: Dict[str, List[RasterOpeningInstanceEvidence]] = {}
    for item in evidence:
        grouped.setdefault(item.tag, []).append(item)

    resolved: List[RasterOpeningInstanceEvidence] = []
    for tag, group in sorted(grouped.items()):
        quantities = {item.quantity for item in group}
        trades = {item.trade_type for item in group}
        if len(quantities) != 1 or len(trades) != 1:
            continue
        best = max(group, key=lambda item: item.confidence)
        resolved.append(best)
    return resolved
