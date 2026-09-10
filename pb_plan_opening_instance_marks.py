"""Recover hyphenated W-# / D-# instance marks on scanned floor plans.

Some drawing packages never print a schedule total. They stamp each opening
on the plan as ``W-1``, ``W-2``, ``D-1``. Native PDF text is empty on those
sheets because the labels live in the raster overlay.

This module:

- Isolates dark, non-chromatic ink so hatch and service colour do not OCR.
- Accepts only hyphenated marks (``W-1``), so grid letters plus grid numbers
  cannot become ``D1``.
- Assembles a nearby ``W-`` + digit fragment. A lone ``-N`` is promoted to
  ``W-N`` only when it sits on the same band as other window marks.
- Counts an unmatched ``W-`` / ``D-`` prefix on that band as one extra
  instance (OCR dropped the digit) toward an *aggregate* total only.
- Across duplicate service overlays of the same plan, keeps the single
  richest page rather than summing.

Typed schedule rows (W1=n from a table/card/chain) remain authoritative.
When those already exist, this layer stays silent. When several window
identities are present as plan stamps and the package documents a casement
window system, the caller may emit ``steel_casement_windows`` as the stamp
count — not the individual W1/W2 tags, which would hallucinate against a
lumped BOQ item.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image

from pb_opening_tag_normalization import normalize_opening_tag

_FULL_RE = re.compile(r"^([WD])-([0-9]{1,2})$")
_FRAG_RE = re.compile(r"^(?:[WD]|[WD]-|-[0-9]{1,2}|[0-9]{1,2}|-)$")
_CASEMENT_RE = re.compile(
    r"\bcasement\b|\bwindows?\s+complete\b|\bsteel\s+casement\b",
    re.I,
)
_DOOR_SYSTEM_RE = re.compile(
    r"\bdoors?\s+complete\b|\bflush\s+doors?\b|\bcasement\s+doors?\b",
    re.I,
)
_MIN_WINDOW_TYPES = 2
_MIN_WINDOW_INSTANCES = 3
_MAX_MARK_INDEX = 12


@dataclass(frozen=True)
class PlanInstanceMark:
    tag: str
    trade: str
    conf: float
    x: float
    y: float
    raw: str
    page: int
    complete: bool


@dataclass(frozen=True)
class PlanInstanceOpeningTotals:
    window_count: int
    door_count: int
    window_types: Tuple[str, ...]
    door_types: Tuple[str, ...]
    source_page: int
    evidence_text: str


def package_documents_casement_windows(texts: Iterable[str]) -> bool:
    blob = "\n".join(texts)
    return bool(_CASEMENT_RE.search(blob))


def package_documents_door_system(texts: Iterable[str]) -> bool:
    blob = "\n".join(texts)
    return bool(_DOOR_SYSTEM_RE.search(blob))


def _isolate_ink(rgb: np.ndarray, dark: int = 130, sat: int = 32) -> np.ndarray:
    red = rgb[:, :, 0].astype(int)
    green = rgb[:, :, 1].astype(int)
    blue = rgb[:, :, 2].astype(int)
    chromatic = (
        np.maximum(np.maximum(red, green), blue)
        - np.minimum(np.minimum(red, green), blue)
    ) > sat
    ink = (red < dark) & (green < dark) & (blue < dark) & ~chromatic
    canvas = np.full(red.shape, 255, np.uint8)
    canvas[ink] = 0
    return 255 - cv2.morphologyEx(
        255 - canvas, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8)
    )


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


def _ocr_parts(rgb: np.ndarray, min_conf: float = 20.0) -> List[dict]:
    ink = _isolate_ink(rgb)
    data = pytesseract.image_to_data(
        Image.fromarray(ink),
        output_type=pytesseract.Output.DICT,
        config="--psm 11 -c tessedit_char_whitelist=WD-0123456789",
    )
    parts: List[dict] = []
    for i, raw in enumerate(data["text"]):
        token = (raw or "").strip()
        if not token or not (_FULL_RE.fullmatch(token) or _FRAG_RE.fullmatch(token)):
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if conf < min_conf:
            continue
        parts.append(
            {
                "t": token,
                "conf": conf,
                "x": float(data["left"][i]),
                "y": float(data["top"][i]),
                "w": float(data["width"][i]),
                "h": float(data["height"][i]),
            }
        )
    return parts


def _emit_mark(
    marks: List[PlanInstanceMark],
    tag: str,
    conf: float,
    x: float,
    y: float,
    raw: str,
    page: int,
    complete: bool,
) -> None:
    match = re.search(r"(\d+)", tag)
    if match is None:
        return
    number = int(match.group(1))
    if number < 1 or number > _MAX_MARK_INDEX:
        return
    trade = "windows" if tag.startswith("W") else "doors"
    marks.append(
        PlanInstanceMark(
            tag=tag,
            trade=trade,
            conf=conf,
            x=x,
            y=y,
            raw=raw,
            page=page,
            complete=complete,
        )
    )


def _assemble(
    parts: Sequence[dict],
    *,
    origin_x: float,
    origin_y: float,
    scale_x: float,
    scale_y: float,
    page: int,
    max_dx_px: float = 50.0,
    max_dy_px: float = 16.0,
) -> List[PlanInstanceMark]:
    """Turn OCR pieces into hyphenated marks. Grid D + 1 never joins."""
    ordered = sorted(parts, key=lambda part: (part["y"], part["x"]))
    used = set()
    marks: List[PlanInstanceMark] = []
    leftovers: List[dict] = []

    def to_page(px: float, py: float) -> Tuple[float, float]:
        return origin_x + px * scale_x, origin_y + py * scale_y

    for i, part in enumerate(ordered):
        if i in used:
            continue
        full = _FULL_RE.fullmatch(part["t"])
        if full:
            used.add(i)
            cx, cy = to_page(part["x"] + part["w"] / 2.0, part["y"] + part["h"] / 2.0)
            _emit_mark(
                marks,
                f"{full.group(1).upper()}{int(full.group(2))}",
                part["conf"],
                cx,
                cy,
                part["t"],
                page,
                True,
            )
            continue

        cluster = [part]
        used.add(i)
        end = part["x"] + part["w"]
        mid_y = part["y"] + part["h"] / 2.0
        for j, other in enumerate(ordered):
            if j in used:
                continue
            other_y = other["y"] + other["h"] / 2.0
            if abs(other_y - mid_y) > max_dy_px:
                continue
            if 0.0 <= other["x"] - end <= max_dx_px:
                cluster.append(other)
                used.add(j)
                end = max(end, other["x"] + other["w"])
        text = "".join(item["t"] for item in sorted(cluster, key=lambda item: item["x"]))
        text = text.replace("--", "-")
        joined = re.search(r"([WD])-([0-9]{1,2})", text)
        if joined:
            cx, cy = to_page(
                sum(item["x"] + item["w"] / 2.0 for item in cluster) / len(cluster),
                sum(item["y"] + item["h"] / 2.0 for item in cluster) / len(cluster),
            )
            _emit_mark(
                marks,
                f"{joined.group(1).upper()}{int(joined.group(2))}",
                min(item["conf"] for item in cluster),
                cx,
                cy,
                text,
                page,
                True,
            )
        else:
            leftovers.extend(cluster)

    window_marks = [mark for mark in marks if mark.trade == "windows" and mark.complete]
    if window_marks:
        ys = np.array([mark.y for mark in window_marks], dtype=float)
        y_med = float(np.median(ys))
        band = max(10.0, 2.5 * float(np.std(ys) + 4.0))
        for part in leftovers:
            dropped = re.fullmatch(r"-([0-9]{1,2})", part["t"])
            if not dropped:
                continue
            _, py = to_page(part["x"] + part["w"] / 2.0, part["y"] + part["h"] / 2.0)
            if abs(py - y_med) > band:
                continue
            cx, cy = to_page(part["x"] + part["w"] / 2.0, part["y"] + part["h"] / 2.0)
            _emit_mark(
                marks,
                f"W{int(dropped.group(1))}",
                part["conf"],
                cx,
                cy,
                part["t"],
                page,
                False,
            )

    for part in leftovers:
        if part["t"] not in {"W-", "D-"}:
            continue
        cx, cy = to_page(part["x"] + part["w"] / 2.0, part["y"] + part["h"] / 2.0)
        if any(abs(cx - mark.x) < 25.0 and abs(cy - mark.y) < 18.0 for mark in marks):
            continue
        prefix = part["t"][0]
        trade = "windows" if prefix == "W" else "doors"
        marks.append(
            PlanInstanceMark(
                tag=f"{prefix}?",
                trade=trade,
                conf=part["conf"],
                x=cx,
                y=cy,
                raw=part["t"],
                page=page,
                complete=False,
            )
        )
    return marks


def _nms(marks: Sequence[PlanInstanceMark], dist: float = 12.0) -> List[PlanInstanceMark]:
    ordered = sorted(marks, key=lambda mark: (-mark.conf, -int(mark.complete)))
    kept: List[PlanInstanceMark] = []
    for mark in ordered:
        if any(abs(mark.x - other.x) < dist and abs(mark.y - other.y) < dist for other in kept):
            continue
        kept.append(mark)
    return kept


def extract_marks_from_page(page: fitz.Page, page_num: int) -> List[PlanInstanceMark]:
    hits: List[PlanInstanceMark] = []
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        infos = []
    for info in infos:
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if width * height < 400 * 180:
            continue
        try:
            pix = fitz.Pixmap(page.parent, info["xref"])
        except Exception:
            continue
        rgb = _rgb_from_pixmap(pix)
        if rgb is None:
            continue
        bbox = info["bbox"]
        scale_x = (bbox[2] - bbox[0]) / max(rgb.shape[1], 1)
        scale_y = (bbox[3] - bbox[1]) / max(rgb.shape[0], 1)
        hits.extend(
            _assemble(
                _ocr_parts(rgb),
                origin_x=float(bbox[0]),
                origin_y=float(bbox[1]),
                scale_x=scale_x,
                scale_y=scale_y,
                page=page_num,
            )
        )

    # Two render scales recover marks that a single downsample drops
    # (a neighbouring W-3 / W-1 pair is a typical example).
    for dpi in (200, 240):
        try:
            pix = page.get_pixmap(dpi=dpi)
            rgb = _rgb_from_pixmap(pix)
        except Exception:
            rgb = None
        if rgb is None:
            continue
        scale_x = page.rect.width / max(rgb.shape[1], 1)
        scale_y = page.rect.height / max(rgb.shape[0], 1)
        hits.extend(
            _assemble(
                _ocr_parts(rgb),
                origin_x=0.0,
                origin_y=0.0,
                scale_x=scale_x,
                scale_y=scale_y,
                page=page_num,
            )
        )
    return _nms(hits, dist=12.0)


def extract_plan_instance_opening_totals(
    doc: fitz.Document,
    pages: Sequence[int],
) -> Optional[PlanInstanceOpeningTotals]:
    """Return aggregate window/door stamp counts from the richest plan page."""
    by_page: dict[int, List[PlanInstanceMark]] = {}
    for pno in pages:
        if pno < 0 or pno >= len(doc):
            continue
        page = doc[pno]
        try:
            has_large_raster = any(
                int(image[2] or 0) * int(image[3] or 0) >= 400 * 200
                for image in page.get_images()
            )
        except Exception:
            has_large_raster = False
        if not has_large_raster:
            continue
        native = page.get_text("text") or ""
        # Stamp labels live on scanned overlays whose native text is the
        # title block only. Dense vector note sheets are skipped.
        if len(native.strip()) > 400:
            continue
        marks = extract_marks_from_page(page, pno + 1)
        if marks:
            by_page[pno + 1] = marks
    if not by_page:
        return None

    def richness(item: Tuple[int, List[PlanInstanceMark]]) -> Tuple[int, int]:
        marks = item[1]
        windows = sum(1 for mark in marks if mark.trade == "windows")
        return windows, len(marks)

    source_page, marks = max(by_page.items(), key=richness)
    windows = [mark for mark in marks if mark.trade == "windows"]
    doors = [mark for mark in marks if mark.trade == "doors"]
    window_types = tuple(sorted({mark.tag for mark in windows if mark.complete}))
    door_types = tuple(sorted({mark.tag for mark in doors if mark.complete}))
    evidence = "; ".join(
        f"{mark.tag}:{mark.raw}@{mark.page}" for mark in marks[:24]
    )
    return PlanInstanceOpeningTotals(
        window_count=len(windows),
        door_count=len(doors),
        window_types=window_types,
        door_types=door_types,
        source_page=source_page,
        evidence_text=evidence,
    )


def should_emit_casement_window_total(
    totals: PlanInstanceOpeningTotals,
    existing_tags: Iterable[str],
) -> bool:
    """True when plan stamps should become a lumped casement-window total."""
    if any(normalize_opening_tag(tag) for tag in existing_tags):
        return False
    if len(totals.window_types) < _MIN_WINDOW_TYPES:
        return False
    if totals.window_count < _MIN_WINDOW_INSTANCES:
        return False
    return True
