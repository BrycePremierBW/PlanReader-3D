"""Source-structure classifier for raster drawing OCR candidates.

A rasterized architectural sheet may expose only a small title-block text layer,
so native-text drawing keywords alone are not a safe prerequisite for OCR.
This helper does *not* declare a page commercially authoritative. It only says
that the page has enough raster structure to justify running the downstream OCR
evidence pipeline, whose explicit-tag, confidence, conflict, and reconciliation
rules remain fail-closed.
"""
from __future__ import annotations

import re
from typing import Any

import fitz


_BOQ_TEXT_RE = re.compile(
    r"bills?\s*of\s*quantit|rate\s*amount|\bamount\s*\(?kshs?\)?|"
    r"\bpriced\s+bill\b|\bunit\s+rate\b",
    re.IGNORECASE,
)


def _rect_area(rect: fitz.Rect) -> float:
    return max(0.0, float(rect.width)) * max(0.0, float(rect.height))


def is_sparse_raster_ocr_candidate(
    page: Any,
    page_text: str,
    *,
    max_native_chars: int = 320,
    min_single_image_area_ratio: float = 0.20,
    min_total_image_area_ratio: float = 0.35,
    min_image_count: int = 4,
) -> bool:
    """Return whether source structure justifies OCR despite weak native text.

    The defaults are deliberately broad document-structure thresholds, not
    opening dimensions or benchmark-shaped values. A page qualifies only when:
    - native text is sparse;
    - it does not look like a BOQ/pricing page; and
    - raster content is structurally significant (one large image, substantial
      cumulative image coverage, or several image tiles).

    Qualifying here never creates a takeoff quantity by itself.
    """
    text = page_text or ""
    if len(text.strip()) > max_native_chars:
        return False
    if _BOQ_TEXT_RE.search(text.lower()):
        return False

    try:
        page_rect = fitz.Rect(page.rect)
        page_area = _rect_area(page_rect)
        if page_area <= 0:
            return False

        infos = list(page.get_image_info(xrefs=True) or [])
        if not infos:
            images = list(page.get_images(full=True) or [])
            return len(images) >= min_image_count

        image_areas = []
        for info in infos:
            bbox = info.get("bbox") if isinstance(info, dict) else None
            if not bbox:
                continue
            try:
                clipped = fitz.Rect(bbox) & page_rect
            except Exception:
                continue
            image_areas.append(_rect_area(clipped))

        if not image_areas:
            return len(infos) >= min_image_count

        max_ratio = max(image_areas) / page_area
        total_ratio = min(1.0, sum(image_areas) / page_area)
        return (
            max_ratio >= min_single_image_area_ratio
            or total_ratio >= min_total_image_area_ratio
            or len(infos) >= min_image_count
        )
    except Exception:
        return False
