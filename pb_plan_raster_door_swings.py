"""Interior and exterior door-swing symbols on inverted CAD floor-plan rasters.

Some laboratory plans are scanned as a dark CAD raster.

- Internal flush doors are drawn as a tight pair of concentric circular
  arcs (a thin squarish banana after a small morphological close).
- External double-leaf doors are drawn as a wide pointed arch of two
  opposing quarter-circles in the verandah wall. After one such symbol
  is recovered, the same raster is searched for repeats of that stamp
  along the wall band.

This module never reads opening tags, figured sizes, or BOQ identities.
The caller may emit ``D2`` from the interior cluster and ``D1`` from
repeated double-leaf stamps when no typed identity already occupies
that tag.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import fitz
import numpy as np

from pb_opening_tag_normalization import normalize_opening_tag
from pb_plan_door_swing_geometry import page_is_floor_plan

_DARK_MEAN_MAX = 50.0
_MIN_COUNT = 2
_MAX_COUNT = 6
_MIN_AREA = 100.0
_MAX_AREA = 450.0
_MIN_RADIUS = 28.0
_MAX_RADIUS = 48.0
_MIN_ASPECT = 0.75
_MIN_OCC_DEG = 160
_MAX_OCC_DEG = 220
_RADIUS_RATIO_MAX = 1.35
_DOUBLE_LEAF_MATCH = 0.55
_DOUBLE_LEAF_MIN = 2
_DOUBLE_LEAF_MAX = 4


@dataclass(frozen=True)
class RasterInteriorDoorSwings:
    count: int
    source_page: int
    evidence_text: str
    radii: Tuple[float, ...]


@dataclass(frozen=True)
class RasterExteriorDoorSwings:
    count: int
    source_page: int
    evidence_text: str


def _rgb_from_pixmap(pix: fitz.Pixmap) -> Optional[np.ndarray]:
    try:
        if pix.n - pix.alpha > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.n < 3:
            return None
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        return arr[:, :, :3].copy()
    except Exception:
        return None


def _occupancy_deg(points: np.ndarray, cx: float, cy: float) -> int:
    bins = np.zeros(36, dtype=int)
    for px, py in points:
        ang = math.atan2(py - cy, px - cx)
        bins[int((ang + math.pi) / (2 * math.pi) * 36) % 36] += 1
    return int((bins > 0).sum()) * 10


def interior_door_swings_from_raster(rgb: np.ndarray) -> List[Tuple[float, float, float]]:
    """Return (x, y, radius) for inverted-CAD interior door-swing symbols."""
    if rgb is None or rgb.size == 0:
        return []
    if float(np.mean(rgb)) > _DARK_MEAN_MAX:
        return []
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ink = (gray > 140).astype(np.uint8) * 255
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    hits: List[Tuple[float, float, float]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < _MIN_AREA or area > _MAX_AREA:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        if radius < _MIN_RADIUS or radius > _MAX_RADIUS:
            continue
        _x, _y, width, height = cv2.boundingRect(contour)
        aspect = min(width, height) / max(width, height)
        if aspect < _MIN_ASPECT:
            continue
        points = contour.reshape(-1, 2).astype(float)
        occ = _occupancy_deg(points, float(cx), float(cy))
        if occ < _MIN_OCC_DEG or occ > _MAX_OCC_DEG:
            continue
        hits.append((float(cx), float(cy), float(radius)))
    hits.sort(key=lambda item: -item[2])
    kept: List[Tuple[float, float, float]] = []
    for hit in hits:
        if any(
            math.hypot(hit[0] - other[0], hit[1] - other[1])
            < 0.7 * max(hit[2], other[2])
            for other in kept
        ):
            continue
        kept.append(hit)
    return kept


def similar_radius_cluster(radii: Sequence[float]) -> bool:
    if not radii:
        return False
    return (max(radii) / max(min(radii), 1e-6)) <= _RADIUS_RATIO_MAX


def should_emit_interior_door_total(
    count: int,
    radii: Sequence[float],
    existing_tags: Iterable[str],
) -> bool:
    if count < _MIN_COUNT or count > _MAX_COUNT:
        return False
    if not similar_radius_cluster(radii):
        return False
    for tag in existing_tags:
        norm = normalize_opening_tag(tag)
        if norm is not None and norm.trade_type == "doors":
            return False
    return True


def extract_interior_plan_door_swings(
    doc: fitz.Document,
    pages: Sequence[int],
) -> Optional[RasterInteriorDoorSwings]:
    """Return interior unlabeled door-swing counts from inverted CAD plans."""
    best: Optional[RasterInteriorDoorSwings] = None
    best_n = 0
    for pno in pages:
        if pno < 0 or pno >= len(doc):
            continue
        page = doc[pno]
        text = page.get_text("text") or ""
        if not page_is_floor_plan(text):
            continue
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            infos = []
        for info in infos:
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            if width * height < 400 * 200:
                continue
            try:
                pix = fitz.Pixmap(doc, info["xref"])
            except Exception:
                continue
            rgb = _rgb_from_pixmap(pix)
            if rgb is None:
                continue
            hits = interior_door_swings_from_raster(rgb)
            radii = [hit[2] for hit in hits]
            if not should_emit_interior_door_total(len(hits), radii, []):
                continue
            if len(hits) < best_n:
                continue
            evidence = "; ".join(
                f"r={hit[2]:.1f}@({hit[0]:.1f},{hit[1]:.1f})" for hit in hits[:8]
            )
            best = RasterInteriorDoorSwings(
                count=len(hits),
                source_page=pno + 1,
                evidence_text=evidence,
                radii=tuple(radii),
            )
            best_n = len(hits)
    return best


def _dark_ink(rgb: np.ndarray) -> Optional[np.ndarray]:
    if rgb is None or rgb.size == 0:
        return None
    if float(np.mean(rgb)) > _DARK_MEAN_MAX:
        return None
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return (gray > 140).astype(np.uint8) * 255


def double_leaf_seed_boxes(ink: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Wide pointed-arch contours used as external double-leaf door seeds."""
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    boxes: List[Tuple[int, int, int, int]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < 120 or area > 900:
            continue
        (_cx, _cy), radius = cv2.minEnclosingCircle(contour)
        if radius < 26 or radius > 50:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if width <= height:
            continue
        aspect = min(width, height) / max(width, height)
        if aspect < 0.48 or aspect > 0.75:
            continue
        occ = _occupancy_deg(contour.reshape(-1, 2).astype(float), float(_cx), float(_cy))
        if occ < 170 or occ > 240:
            continue
        boxes.append((int(x), int(y), int(width), int(height)))
    return boxes


def _repeat_peaks(
    ink: np.ndarray,
    box: Tuple[int, int, int, int],
    min_score: float = _DOUBLE_LEAF_MATCH,
) -> List[Tuple[float, float, float]]:
    x, y, width, height = box
    pad = 4
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(ink.shape[1], x + width + pad)
    y1 = min(ink.shape[0], y + height + pad)
    template = ink[y0:y1, x0:x1]
    if template.size == 0 or template.shape[0] < 8 or template.shape[1] < 8:
        return []
    band0 = max(0, y - height)
    band1 = min(ink.shape[0], y + 2 * height)
    band = ink[band0:band1, :]
    if band.shape[0] <= template.shape[0] or band.shape[1] <= template.shape[1]:
        return []
    response = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(response >= min_score)
    peaks = [
        (
            float(response[py, px]),
            float(px + template.shape[1] / 2.0),
            float(band0 + py + template.shape[0] / 2.0),
        )
        for py, px in zip(ys, xs)
    ]
    peaks.sort(reverse=True)
    kept: List[Tuple[float, float, float]] = []
    min_dx = 0.8 * template.shape[1]
    for peak in peaks:
        if any(abs(peak[1] - other[1]) < min_dx and abs(peak[2] - other[2]) < height for other in kept):
            continue
        kept.append(peak)
    return kept


def exterior_double_leaf_swings_from_raster(
    rgb: np.ndarray,
) -> List[Tuple[float, float, float]]:
    """Return (score, x, y) for repeated double-leaf door stamps."""
    ink = _dark_ink(rgb)
    if ink is None:
        return []
    peaks: List[Tuple[float, float, float]] = []
    for box in double_leaf_seed_boxes(ink):
        peaks.extend(_repeat_peaks(ink, box))
    peaks.sort(reverse=True)
    kept: List[Tuple[float, float, float]] = []
    for peak in peaks:
        if any(math.hypot(peak[1] - other[1], peak[2] - other[2]) < 28 for other in kept):
            continue
        kept.append(peak)
    return kept


def should_emit_exterior_door_total(
    count: int,
    existing_tags: Iterable[str],
) -> bool:
    if count < _DOUBLE_LEAF_MIN or count > _DOUBLE_LEAF_MAX:
        return False
    for tag in existing_tags:
        norm = normalize_opening_tag(tag)
        if norm is not None and norm.tag == "D1":
            return False
    return True


def extract_exterior_plan_door_swings(
    doc: fitz.Document,
    pages: Sequence[int],
) -> Optional[RasterExteriorDoorSwings]:
    """Return repeated verandah double-leaf door counts from inverted CAD plans."""
    best: Optional[RasterExteriorDoorSwings] = None
    best_n = 0
    for pno in pages:
        if pno < 0 or pno >= len(doc):
            continue
        page = doc[pno]
        text = page.get_text("text") or ""
        if not page_is_floor_plan(text):
            continue
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            infos = []
        for info in infos:
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            if width * height < 400 * 200:
                continue
            try:
                pix = fitz.Pixmap(doc, info["xref"])
            except Exception:
                continue
            rgb = _rgb_from_pixmap(pix)
            if rgb is None:
                continue
            hits = exterior_double_leaf_swings_from_raster(rgb)
            if not should_emit_exterior_door_total(len(hits), []):
                continue
            if len(hits) < best_n:
                continue
            evidence = "; ".join(
                f"{hit[0]:.2f}@({hit[1]:.1f},{hit[2]:.1f})" for hit in hits[:8]
            )
            best = RasterExteriorDoorSwings(
                count=len(hits),
                source_page=pno + 1,
                evidence_text=evidence,
            )
            best_n = len(hits)
    return best
