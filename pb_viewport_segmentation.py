"""Evidence-backed drawing viewport segmentation (PlanReader Phase F.07).

The legacy ``DrawingViewClassifier.partition_sheet_views`` classifies view-title
text but its bbox is only the title text bbox.  F.07 turns title evidence into
spatial ownership for dimensions, scales, openings and references.

Authority states:
- RESOLVED: title is tied to exactly one native vector frame.
- DERIVED: multiple unframed titles support a non-overlapping page partition.
- AMBIGUOUS / UNSUPPORTED: ownership is not guessed.

A native frame may be a rectangle item, an axis-aligned quad, or one closed
four-line path. Independent wall lines are not assembled into a frame.
Largest/smallest/nearest rectangle is never a default owner.

Safety invariants:
- project/file/path/benchmark identity is never an input;
- spatial tolerances are derived from page typography or the candidate frame;
- prose mentioning a view is not accepted as a drawing title;
- one frame shared by multiple titles is ambiguous;
- two equivalent frames competing for one title are ambiguous;
- page borders, crop boxes, and title-block panels are not viewports;
- table grids are not drawing viewports; a table-like frame is admissible only
  for an independently classified schedule/legend/specification title;
- scale is associated only after viewport ownership; conflicting scales remain
  unresolved;
- viewport IDs are provenance only, never semantic prediction features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
import statistics
from typing import Any, Iterable, Optional, Sequence

import fitz

from pb_drawing_evidence_binding import DrawingViewClassifier, DrawingViewRegion, DrawingViewType
from pb_native_page_frame import NativePageFrameUnresolved, native_page_frame
import pb_page_title_authority as _title_authority


_PAGE_PARSE_CACHE_ATTR = "_pb_viewport_segmentation_page_parse_cache"


def _page_parse_cache(page: Any) -> Optional[dict[str, Any]]:
    try:
        cache = getattr(page, _PAGE_PARSE_CACHE_ATTR, None)
    except Exception:
        cache = None
    if isinstance(cache, dict):
        return cache
    cache = {}
    try:
        setattr(page, _PAGE_PARSE_CACHE_ATTR, cache)
    except Exception:
        return None
    return cache


def _page_drawings(page: Any) -> tuple:
    cache = _page_parse_cache(page)
    if isinstance(cache, dict) and "drawings" in cache:
        return cache["drawings"]
    drawings = tuple(page.get_drawings() or ())
    if isinstance(cache, dict):
        cache["drawings"] = drawings
    return drawings


def _page_text(page: Any, mode: str):
    cache = _page_parse_cache(page)
    key = f"text:{mode}"
    if isinstance(cache, dict) and key in cache:
        return cache[key]
    value = page.get_text(mode)
    if isinstance(cache, dict):
        cache[key] = value
    return value


class ViewportSegmentationStatus(str, Enum):
    RESOLVED = "resolved"
    DERIVED = "derived"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class ViewportBoundarySource(str, Enum):
    VECTOR_FRAME = "vector_frame"
    TITLE_PARTITION = "title_partition"
    NONE = "none"


@dataclass(frozen=True)
class ViewportLayoutCalibration:
    median_word_height_pt: float
    title_frame_gap_pt: float
    minimum_frame_span_pt: float
    title_separation_pt: float
    page_width_pt: float
    page_height_pt: float


@dataclass
class SegmentedViewport:
    view_id: str
    page_number: int
    view_type: str
    label: str
    title_bbox: tuple[float, float, float, float]
    bounding_box: Optional[tuple[float, float, float, float]]
    status: str
    boundary_source: str
    confidence: float
    scale_raw: Optional[str] = None
    scale_denominator: Optional[float] = None
    scale_conflict: bool = False
    notes: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    _producer_token: Any = field(default=None, repr=False, compare=False)
    _producer_fingerprint: str = field(default="", repr=False, compare=False)

    def to_drawing_view_region(self) -> DrawingViewRegion:
        return DrawingViewRegion(
            view_id=self.view_id,
            view_type=self.view_type,
            label=self.label,
            page_number=self.page_number,
            bounding_box=list(self.bounding_box) if self.bounding_box else None,
        )


@dataclass(frozen=True)
class _TitleAnchor:
    text: str
    bbox: tuple[float, float, float, float]
    view_type: str
    # Native text advance direction from the producer-owned PDF line.  This is
    # retained only for spatial ownership; it never changes semantic view type.
    direction: tuple[float, float] = (1.0, 0.0)

    @property
    def center(self) -> tuple[float, float]:
        return _bbox_center(self.bbox)


_SCALE_RE = re.compile(r"\b(?:SCALE\s*)?(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\b", re.I)
_TITLE_BLOCK_LABEL_RE = re.compile(
    r"\b(?:drawing\s+(?:title|no\.?|number)|rev(?:ision)?|checked by|drawn by|approved|"
    r"consultant|client|date)\b",
    re.I,
)
_SHEET_METADATA_LABEL_RE = re.compile(
    r"\b(?:drawing\s+(?:name|title|no\.?|number)|project\s+title|"
    r"rev(?:ision)?|client|scale|drawn|checked|approved|date)\b",
    re.I,
)
_MAX_FRAME_PAGE_FRACTION = 0.95
_CROP_EDGE_FRACTION = 0.03
_MAX_FRAME_ASPECT_RATIO = 8.0
_TITLE_BELOW_FRAME_HEIGHT_FRACTION = 0.25
_TITLE_HORIZONTAL_OVERLAP_FRACTION = 0.5
_NESTED_BAND_SPAN_FRACTION = 0.35
_TITLE_BLOCK_AREA_FRACTION = 0.20
_TABLE_CELL_COUNT = 8
_TABLE_GRID_OCCUPANCY_FRACTION = 0.75
_TABLE_GRID_FRAME_COVERAGE_FRACTION = 0.20
_TABLE_CELL_DIMENSION_ROUND_DIGITS = 3
_SEMANTIC_TABLE_VIEW_TYPES = frozenset(
    {
        DrawingViewType.SCHEDULE.value,
        DrawingViewType.LEGEND.value,
        DrawingViewType.SPECIFICATION.value,
    }
)

# Private in-process producer token. Migration authority must not be minted from
# caller-copied provenance dictionaries. Only segment_page_viewports stamps this
# token after F.07 has completed ownership resolution for the whole page.
_SEGMENT_PAGE_VIEWPORTS_PRODUCER_TOKEN = object()


def _producer_fingerprint_payload(viewport: SegmentedViewport) -> dict[str, Any]:
    return {
        "view_id": str(viewport.view_id),
        "page_number": int(viewport.page_number),
        "view_type": str(viewport.view_type),
        "label": str(viewport.label),
        "title_bbox": tuple(float(v) for v in viewport.title_bbox),
        "bounding_box": (
            None
            if viewport.bounding_box is None
            else tuple(float(v) for v in viewport.bounding_box)
        ),
        "status": str(viewport.status),
        "boundary_source": str(viewport.boundary_source),
        "confidence": float(viewport.confidence),
        "scale_raw": viewport.scale_raw,
        "scale_denominator": viewport.scale_denominator,
        "scale_conflict": bool(viewport.scale_conflict),
        "notes": list(viewport.notes),
        "provenance": dict(viewport.provenance),
    }


def segmented_viewport_producer_fingerprint(viewport: SegmentedViewport) -> str:
    """Stable fingerprint of the exact F.07 ownership record.

    This is an integrity fingerprint, not an authority token. Authority also
    requires the private producer token stamped by segment_page_viewports.
    """
    if not isinstance(viewport, SegmentedViewport):
        raise TypeError("viewport must be SegmentedViewport")
    canonical = json.dumps(
        _producer_fingerprint_payload(viewport),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_segment_page_viewports_product(viewport: Any) -> bool:
    """True only for an unmodified viewport stamped by segment_page_viewports."""
    if not isinstance(viewport, SegmentedViewport):
        return False
    if getattr(viewport, "_producer_token", None) is not _SEGMENT_PAGE_VIEWPORTS_PRODUCER_TOKEN:
        return False
    fingerprint = str(getattr(viewport, "_producer_fingerprint", "") or "")
    return bool(
        fingerprint
        and fingerprint == segmented_viewport_producer_fingerprint(viewport)
    )


def _stamp_segment_page_viewports_product(
    viewports: Sequence[SegmentedViewport],
) -> list[SegmentedViewport]:
    stamped = list(viewports)
    for viewport in stamped:
        viewport._producer_token = _SEGMENT_PAGE_VIEWPORTS_PRODUCER_TOKEN
        viewport._producer_fingerprint = segmented_viewport_producer_fingerprint(viewport)
    return stamped


_TITLE_SHAPE_RE = re.compile(
    r"^\s*(?:"
    r"(?:(?:PROP(?:OSED)?\.?)|(?:GROUND|FIRST|SECOND|THIRD|UPPER|LOWER|LEVEL\s*[A-Z0-9.-]+))?\s*FLOOR\s+PLAN|"
    r"(?:(?:PROP(?:OSED)?\.?)\s*)?FLOOR\s+FINISH(?:ES)?(?:\s*&\s*PARTITIONS?)?\s+PLAN|"
    r"(?:(?:PROP(?:OSED)?\.?)\s*)?REFLECTED\s+CEILING\s+PLAN|R\.?C\.?P\.?|"
    r"PLAN\s*:\s*FLOOR\s+LAYOUT|FLOOR\s+LAYOUT|LAYOUT\s+PLAN|ROOF(?:ING)?\s+(?:LAYOUT\s+)?PLAN|"
    r"(?:NORTH|SOUTH|EAST|WEST|FRONT|REAR|SIDE)?\s*ELEV(?:ATION)?(?:\s+[A-Z0-9.-]+)?|"
    r"SECTION(?:\s+[A-Z0-9.-]+)?|CROSS\s+SECTION|LONGITUDINAL\s+SECTION|"
    r"(?:WINDOW|DOOR|(?:(?:INTERNAL|EXTERNAL|CEILING|FLOOR)\s+)?FINISH(?:ES)?)\s+SCHEDULE|SCHEDULE\s+OF\s+(?:WINDOWS|DOORS|FINISHES)|"
    r"(?:TYPICAL|STANDARD|ENLARGED)?\s*DETAIL(?:\s+[A-Z0-9./-]+)?|"
    r"LEGEND|SYMBOL\s+LEGEND|GENERAL\s+SPECIFICATIONS?"
    r")\s*(?:[-–—]\s*)?(?:SCALE\s*)?\d*(?:\.\d+)?\s*(?::\s*\d+(?:\.\d+)?)?\s*$",
    re.I,
)


def _bbox_center(bbox: Sequence[float]) -> tuple[float, float]:
    return (float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0


def _bbox_area(bbox: Sequence[float]) -> float:
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))


def _bbox_contains(outer: Sequence[float], inner: Sequence[float], *, margin: float = 0.0) -> bool:
    return (
        float(outer[0]) - margin <= float(inner[0])
        and float(outer[1]) - margin <= float(inner[1])
        and float(outer[2]) + margin >= float(inner[2])
        and float(outer[3]) + margin >= float(inner[3])
    )


def _point_in_bbox(point: tuple[float, float], bbox: Sequence[float], *, margin: float = 0.0) -> bool:
    return (
        float(bbox[0]) - margin <= point[0] <= float(bbox[2]) + margin
        and float(bbox[1]) - margin <= point[1] <= float(bbox[3]) + margin
    )


def _bbox_overlap_area(a: Sequence[float], b: Sequence[float]) -> float:
    x0 = max(float(a[0]), float(b[0])); y0 = max(float(a[1]), float(b[1]))
    x1 = min(float(a[2]), float(b[2])); y1 = min(float(a[3]), float(b[3]))
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _normalized_bbox(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _cluster_values(values: Sequence[float], tol: float) -> list[float]:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return []
    groups: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if abs(value - groups[-1][-1]) <= tol:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def _axis_aligned_quad_bbox(quad: Any, *, tol: float) -> Optional[tuple[float, float, float, float]]:
    points: list[tuple[float, float]] = []
    if hasattr(quad, "ul") and hasattr(quad, "ur") and hasattr(quad, "ll") and hasattr(quad, "lr"):
        for point in (quad.ul, quad.ur, quad.ll, quad.lr):
            points.append((float(point.x), float(point.y)))
    elif hasattr(quad, "x0") and hasattr(quad, "y0") and hasattr(quad, "x1") and hasattr(quad, "y1"):
        return _normalized_bbox(float(quad.x0), float(quad.y0), float(quad.x1), float(quad.y1))
    else:
        return None
    xs = _cluster_values([p[0] for p in points], tol)
    ys = _cluster_values([p[1] for p in points], tol)
    if len(xs) != 2 or len(ys) != 2:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _closed_four_line_rect(
    items: Sequence[Any],
    *,
    tol: float,
) -> Optional[tuple[float, float, float, float]]:
    if len(items) != 4:
        return None
    horiz: list[tuple[float, float, float]] = []
    vert: list[tuple[float, float, float]] = []
    for item in items:
        if not item or item[0] != "l" or len(item) < 3:
            return None
        start, end = item[1], item[2]
        x0, y0, x1, y1 = float(start.x), float(start.y), float(end.x), float(end.y)
        if abs(y0 - y1) <= tol and abs(x0 - x1) > tol:
            horiz.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2.0))
        elif abs(x0 - x1) <= tol and abs(y0 - y1) > tol:
            vert.append((min(y0, y1), max(y0, y1), (x0 + x1) / 2.0))
        else:
            return None
    if len(horiz) != 2 or len(vert) != 2:
        return None
    if abs(horiz[0][2] - horiz[1][2]) <= tol or abs(vert[0][2] - vert[1][2]) <= tol:
        return None
    bbox = (min(vert[0][2], vert[1][2]), min(horiz[0][2], horiz[1][2]),
            max(vert[0][2], vert[1][2]), max(horiz[0][2], horiz[1][2]))
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    if width <= tol or height <= tol:
        return None
    if any((span[1] - span[0]) < 0.8 * width for span in horiz):
        return None
    if any((span[1] - span[0]) < 0.8 * height for span in vert):
        return None
    return bbox


def _is_page_or_crop_border(
    frame: Sequence[float],
    calibration: ViewportLayoutCalibration,
) -> bool:
    page_area = calibration.page_width_pt * calibration.page_height_pt
    if page_area > 0 and _bbox_area(frame) / page_area >= _MAX_FRAME_PAGE_FRACTION:
        return True
    margin_x = calibration.page_width_pt * _CROP_EDGE_FRACTION
    margin_y = calibration.page_height_pt * _CROP_EDGE_FRACTION
    return (
        float(frame[0]) <= margin_x
        and float(frame[1]) <= margin_y
        and float(frame[2]) >= calibration.page_width_pt - margin_x
        and float(frame[3]) >= calibration.page_height_pt - margin_y
    )


def _frame_aspect_ratio(frame: Sequence[float]) -> float:
    width = max(0.0, float(frame[2]) - float(frame[0]))
    height = max(0.0, float(frame[3]) - float(frame[1]))
    shorter = max(min(width, height), 1e-6)
    return max(width, height) / shorter


def _title_horizontal_overlap_fraction(anchor: _TitleAnchor, frame: Sequence[float]) -> float:
    overlap = min(float(frame[2]), anchor.bbox[2]) - max(float(frame[0]), anchor.bbox[0])
    width = max(anchor.bbox[2] - anchor.bbox[0], 1e-6)
    return max(0.0, overlap) / width


def _max_title_below_frame_gap(frame: Sequence[float], calibration: ViewportLayoutCalibration) -> float:
    frame_height = max(0.0, float(frame[3]) - float(frame[1]))
    return max(calibration.title_frame_gap_pt, _TITLE_BELOW_FRAME_HEIGHT_FRACTION * frame_height)


def _other_title_in_title_gap(
    anchor: _TitleAnchor,
    frame: Sequence[float],
    anchors: Sequence[_TitleAnchor],
) -> bool:
    gap_box = (float(frame[0]), float(frame[3]), float(frame[2]), float(anchor.bbox[1]))
    if gap_box[3] <= gap_box[1]:
        return False
    return any(
        other is not anchor and _point_in_bbox(other.center, gap_box)
        for other in anchors
    )


def _collapse_nested_band_frames(
    frames: Sequence[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    kept: list[tuple[float, float, float, float]] = []
    for frame in frames:
        width = float(frame[2]) - float(frame[0])
        height = float(frame[3]) - float(frame[1])
        nested_band = False
        for other in frames:
            if other == frame:
                continue
            if not _bbox_contains(other, frame, margin=1.0):
                continue
            other_w = float(other[2]) - float(other[0])
            other_h = float(other[3]) - float(other[1])
            if height <= _NESTED_BAND_SPAN_FRACTION * other_h or width <= _NESTED_BAND_SPAN_FRACTION * other_w:
                nested_band = True
                break
        if not nested_band:
            kept.append(frame)
    return kept


def _collapse_equivalent_nested_frames(
    frames: Sequence[tuple[float, float, float, float]],
    calibration: ViewportLayoutCalibration,
) -> list[tuple[float, float, float, float]]:
    """Collapse only source rectangles that are duplicate backing borders.

    Two genuinely distinct nested viewports remain separate. The outer frame is
    discarded only when it fully contains another candidate, three sides align
    within ordinary source-coordinate tolerance, and the remaining side differs
    by no more than one calibrated text height. This captures double/background
    border strokes without inventing an averaged boundary.
    """

    edge_tol = max(calibration.median_word_height_pt * 0.1, 0.75)
    band_tol = max(calibration.median_word_height_pt, edge_tol)
    kept: list[tuple[float, float, float, float]] = []
    for frame in frames:
        duplicate_outer = False
        for other in frames:
            if other == frame:
                continue
            if not _bbox_contains(frame, other, margin=edge_tol):
                continue
            deltas = [
                abs(float(frame[index]) - float(other[index]))
                for index in range(4)
            ]
            aligned = sum(delta <= edge_tol for delta in deltas)
            differing = [delta for delta in deltas if delta > edge_tol]
            if (
                aligned == 3
                and len(differing) == 1
                and differing[0] <= band_tol
                and _bbox_area(other) < _bbox_area(frame)
            ):
                duplicate_outer = True
                break
        if not duplicate_outer:
            kept.append(frame)
    return kept


def _collapse_source_repeated_plan_border_pair(
    page: Any,
    frames: Sequence[tuple[float, float, float, float]],
    calibration: ViewportLayoutCalibration,
    fragments: Sequence[tuple[tuple[float, float, float, float], str]],
) -> list[tuple[float, float, float, float]]:
    """Conservatively identify one native double border of a floor plan.

    This extension beyond the ordinary one-text-height duplicate-border rule
    requires positive native-source evidence, not a guessed page margin:
    exactly two nested source frames; three aligned sides; a narrow fourth-side
    strip containing no text and only source line geometries each drawn twice
    with identical paint style. All foreign rectangles/curves and any stroke
    materially crossing the inner frame revoke the collapse. Choose the INNER
    authenticated source frame; this cannot enlarge the owned drawing region.
    """

    if len(frames) != 2:
        return list(frames)
    ordered = sorted(frames, key=_bbox_area)
    inner, outer = ordered
    edge_tol = max(calibration.median_word_height_pt * 0.1, 0.75)
    if not _bbox_contains(outer, inner, margin=edge_tol):
        return list(frames)
    delta = [abs(float(outer[i]) - float(inner[i])) for i in range(4)]
    aligned = [i for i, value in enumerate(delta) if value <= edge_tol]
    if len(aligned) != 3:
        return list(frames)
    side = next(i for i in range(4) if i not in aligned)
    gap = delta[side]
    inner_span = min(float(inner[2]) - float(inner[0]),
                     float(inner[3]) - float(inner[1]))
    # Ordinary 1x-height duplicate frames are already handled upstream. Only
    # modest source-border margins qualify; large nested regions stay distinct.
    if (
        gap <= max(calibration.median_word_height_pt, edge_tol)
        or gap > max(2.0 * calibration.median_word_height_pt, edge_tol)
        or gap > 0.02 * inner_span
    ):
        return list(frames)

    if side == 0:
        strip = (outer[0], outer[1], inner[0], outer[3])
    elif side == 1:
        strip = (outer[0], outer[1], outer[2], inner[1])
    elif side == 2:
        strip = (inner[2], outer[1], outer[2], outer[3])
    else:
        strip = (outer[0], inner[3], outer[2], outer[3])
    strip = _normalized_bbox(*strip)
    if _bbox_area(strip) <= 0:
        return list(frames)
    if any(_bbox_overlap_area(box, strip) > 1e-6 for box, _ in fragments):
        return list(frames)

    repetitions: dict[tuple[object, ...], set[int]] = {}
    # Opaque source-native WHITE fill-only background masks can be visually
    # empty canvas rather than independent stroked geometry. They may be
    # discounted ONLY if the native drawing order proves they were painted
    # BEFORE every repeated physical border stroke. Opaque fills drawn
    # later, nonwhite or translucent fills, or any stroke remain blockers.
    white_background_mask_seqnos: list[int] = []
    protrusion_tol = max(0.25, calibration.median_word_height_pt * 0.05)
    for path_index, drawing in enumerate(_page_drawings(page)):
        seqno = drawing.get("seqno", path_index)
        try:
            seqno = int(seqno)
        except (TypeError, ValueError):
            return list(frames)
        style = (
            str(drawing.get("type") or ""),
            str(drawing.get("color") or ""),
            round(float(drawing.get("width") or 0.0), 3),
            round(float(drawing.get("stroke_opacity") or 1.0), 3),
        )
        for item in drawing.get("items", ()) or ():
            if not item:
                continue
            if item[0] == "re" and len(item) >= 2:
                rect = item[1]
                bbox = _normalized_bbox(
                    float(rect.x0), float(rect.y0),
                    float(rect.x1), float(rect.y1),
                )
                if _bbox_overlap_area(bbox, strip) > 1e-6 and not any(
                    all(abs(bbox[i]-frame[i]) <= edge_tol for i in range(4))
                    for frame in (inner, outer)
                ):
                    fill = drawing.get("fill")
                    only_white_background = (
                        drawing.get("type") == "f"
                        and len(drawing.get("items", ()) or ()) == 1
                        and drawing.get("color") is None
                        and isinstance(fill, (tuple, list))
                        and len(fill) == 3
                        and all(abs(float(v) - 1.0) <= 1e-6 for v in fill)
                        and abs(float(drawing.get("fill_opacity", 0) or 0) - 1.0) <= 1e-6
                    )
                    if not only_white_background:
                        return list(frames)
                    white_background_mask_seqnos.append(seqno)
                continue
            if item[0] != "l" or len(item) < 3:
                # Non-line primitives may be physical symbols. Refuse
                # overlapping curves/quads, and refuse UNKNOWN geometry,
                # rather than treating missing coordinates as empty space.
                if item[0] == "qu":
                    if len(item) < 2:
                        return list(frames)
                    quad_bbox = _axis_aligned_quad_bbox(item[1], tol=edge_tol)
                    if quad_bbox is None or _bbox_overlap_area(
                        quad_bbox, strip
                    ) > 1e-6:
                        return list(frames)
                elif item[0] == "c":
                    points = [
                        p for p in item[1:]
                        if hasattr(p, "x") and hasattr(p, "y")
                    ]
                    if len(points) != len(item) - 1:
                        return list(frames)
                    if points and _bbox_overlap_area(_normalized_bbox(
                        min(float(p.x) for p in points),
                        min(float(p.y) for p in points),
                        max(float(p.x) for p in points),
                        max(float(p.y) for p in points),
                    ), strip) > 1e-6:
                        return list(frames)
                continue
            a, b = item[1], item[2]
            x0,y0,x1,y1 = float(a.x),float(a.y),float(b.x),float(b.y)
            if (
                max(x0,x1) < strip[0] or min(x0,x1) > strip[2]
                or max(y0,y1) < strip[1] or min(y0,y1) > strip[3]
            ):
                continue
            # Retain only exact source border strokes, not arbitrary nearby
            # source geometry, as harmless frame edges.
            if side in (0,2) and abs(x0-x1) <= .25 and (
                abs(x0-outer[side]) <= .25 or abs(x0-inner[side]) <= .25
            ):
                continue
            if side in (1,3) and abs(y0-y1) <= .25 and (
                abs(y0-outer[side]) <= .25 or abs(y0-inner[side]) <= .25
            ):
                continue
            interior = float(inner[side])
            if side in (0,2):
                crosses = min(x0,x1) < interior < max(x0,x1)
                penetration = max(x0,x1)-interior if side == 0 else interior-min(x0,x1)
            else:
                crosses = min(y0,y1) < interior < max(y0,y1)
                penetration = max(y0,y1)-interior if side == 1 else interior-min(y0,y1)
            if crosses and penetration > protrusion_tol:
                return list(frames)
            first = (round(x0,3),round(y0,3))
            second = (round(x1,3),round(y1,3))
            geometry = tuple(sorted((first,second)))
            repetitions.setdefault((geometry,style),set()).add(seqno)

    # There must be independent *positive* repeated source artwork and no
    # unmatched/solo source strokes. This is not a global margin tolerance.
    if len(repetitions) < 2 or any(len(paths) != 2 for paths in repetitions.values()):
        return list(frames)
    first_repeated_border_seqno = min(
        seqno for source_paths in repetitions.values() for seqno in source_paths
    )
    if any(mask_seqno >= first_repeated_border_seqno
           for mask_seqno in white_background_mask_seqnos):
        return list(frames)
    return [inner]


def _frame_has_title_block_labels(
    frame: Sequence[float],
    fragments: Sequence[tuple[tuple[float, float, float, float], str]],
    calibration: ViewportLayoutCalibration,
) -> bool:
    labels = 0
    for bbox, text in fragments:
        if not _point_in_bbox(_bbox_center(bbox), frame):
            continue
        if _TITLE_BLOCK_LABEL_RE.search(text):
            labels += 1
    if labels < 2:
        return False
    page_area = calibration.page_width_pt * calibration.page_height_pt
    if page_area <= 0 or _bbox_area(frame) / page_area > _TITLE_BLOCK_AREA_FRACTION:
        return False
    center_x, center_y = _bbox_center(frame)
    in_side_band = center_x >= 0.65 * calibration.page_width_pt or center_x <= 0.35 * calibration.page_width_pt
    in_lower_band = center_y >= 0.60 * calibration.page_height_pt
    return in_side_band and in_lower_band


def _page_rectangle_primitives(page: Any) -> tuple[tuple[float, float, float, float], ...]:
    """Return normalized source rectangle primitives once per immutable page.

    Table-frame rejection evaluates many candidate frames on dense CAD sheets.
    The rectangle universe is page-invariant, so decode/normalise it once and
    keep the frame-specific containment and area predicates unchanged.
    """
    cache = _page_parse_cache(page)
    if isinstance(cache, dict) and "rectangle_primitives" in cache:
        return cache["rectangle_primitives"]
    rectangles: list[tuple[float, float, float, float]] = []
    for drawing in _page_drawings(page):
        for item in drawing.get("items", []) or []:
            if not item or item[0] != "re" or len(item) < 2:
                continue
            rect = item[1]
            rectangles.append(
                _normalized_bbox(
                    float(rect.x0),
                    float(rect.y0),
                    float(rect.x1),
                    float(rect.y1),
                )
            )
    result = tuple(rectangles)
    if isinstance(cache, dict):
        cache["rectangle_primitives"] = result
    return result


def _frame_looks_like_line_grid_table(
    frame: Sequence[float],
    page: Any,
    calibration: ViewportLayoutCalibration,
) -> bool:
    """Prove a table from repeated source horizontal/vertical grid lines.

    CAD schedules are often emitted as independent line primitives rather than
    rectangle cells. This is a second positive table proof, not a relaxation:
    both axis families must contain repeated, long source lines; their clustered
    extents must span a meaningful fraction of the candidate frame; and most
    horizontal/vertical pairs must geometrically cross.
    """
    frame_area = _bbox_area(frame)
    frame_width = max(0.0, float(frame[2]) - float(frame[0]))
    frame_height = max(0.0, float(frame[3]) - float(frame[1]))
    if frame_area <= 0.0 or frame_width <= 0.0 or frame_height <= 0.0:
        return False

    tol = max(
        calibration.median_word_height_pt * 0.15,
        min(frame_width, frame_height) * 0.001,
        0.75,
    )
    minimum_horizontal_span = max(
        calibration.median_word_height_pt * 4.0,
        frame_width * 0.35,
    )
    minimum_vertical_span = max(
        calibration.median_word_height_pt * 4.0,
        frame_height * 0.35,
    )

    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    for drawing in _page_drawings(page):
        for item in drawing.get("items", []) or []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            x0, y0 = float(start.x), float(start.y)
            x1, y1 = float(end.x), float(end.y)
            midpoint = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            if not _point_in_bbox(midpoint, frame, margin=tol):
                continue
            if abs(y1 - y0) <= tol and abs(x1 - x0) >= minimum_horizontal_span:
                horizontal.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2.0))
            elif abs(x1 - x0) <= tol and abs(y1 - y0) >= minimum_vertical_span:
                vertical.append(((x0 + x1) / 2.0, min(y0, y1), max(y0, y1)))

    if len(horizontal) < 3 or len(vertical) < 3:
        return False

    cluster_tol = max(calibration.median_word_height_pt * 0.5, 1.0)
    y_clusters = _cluster_values([line[2] for line in horizontal], cluster_tol)
    x_clusters = _cluster_values([line[0] for line in vertical], cluster_tol)
    if len(y_clusters) < 3 or len(x_clusters) < 3:
        return False

    def horizontal_extent(y: float) -> tuple[float, float] | None:
        owned = [
            line for line in horizontal
            if abs(line[2] - y) <= cluster_tol
        ]
        if not owned:
            return None
        return min(line[0] for line in owned), max(line[1] for line in owned)

    def vertical_extent(x: float) -> tuple[float, float] | None:
        owned = [
            line for line in vertical
            if abs(line[0] - x) <= cluster_tol
        ]
        if not owned:
            return None
        return min(line[1] for line in owned), max(line[2] for line in owned)

    horizontal_major = [
        (y, extent)
        for y in y_clusters
        for extent in (horizontal_extent(y),)
        if extent is not None
        and extent[1] - extent[0] >= frame_width * 0.5
    ]
    vertical_major = [
        (x, extent)
        for x in x_clusters
        for extent in (vertical_extent(x),)
        if extent is not None
        and extent[1] - extent[0] >= frame_height * 0.5
    ]
    if len(horizontal_major) < 3 or len(vertical_major) < 3:
        return False

    crossing = 0
    possible = len(horizontal_major) * len(vertical_major)
    for y, (hx0, hx1) in horizontal_major:
        for x, (vy0, vy1) in vertical_major:
            if (
                hx0 - tol <= x <= hx1 + tol
                and vy0 - tol <= y <= vy1 + tol
            ):
                crossing += 1
    if possible <= 0 or crossing / possible < 0.6:
        return False

    grid_bbox = (
        min(extent[0] for _, extent in horizontal_major),
        min(extent[0] for _, extent in vertical_major),
        max(extent[1] for _, extent in horizontal_major),
        max(extent[1] for _, extent in vertical_major),
    )
    return (
        _bbox_area(grid_bbox) / frame_area
        >= _TABLE_GRID_FRAME_COVERAGE_FRACTION
    )


def _frame_looks_like_table(
    frame: Sequence[float],
    page: Any,
    calibration: ViewportLayoutCalibration,
) -> bool:
    """Return True only for positive repeated table-grid structure.

    A dense architectural drawing can legitimately contain hundreds or
    thousands of rectangle primitives. Rectangle count alone is therefore not
    table evidence. A table requires a repeated same-size cell family arranged
    as a substantially occupied row/column grid spanning a meaningful fraction
    of the candidate frame.
    """

    frame_area = _bbox_area(frame)
    frame_width = max(0.0, float(frame[2]) - float(frame[0]))
    frame_height = max(0.0, float(frame[3]) - float(frame[1]))
    if frame_area <= 0.0 or frame_width <= 0.0 or frame_height <= 0.0:
        return False

    cells: list[tuple[float, float, float, float]] = []
    for cell in _page_rectangle_primitives(page):
        if not _bbox_contains(frame, cell, margin=1.0):
            continue
        area = _bbox_area(cell)
        if 4.0 < area < 0.15 * frame_area:
            cells.append(cell)

    # Group by scale-invariant cell dimensions. Real table cells repeat their
    # shape; unrelated CAD rectangles should not be pooled merely because they
    # coexist in one drawing frame.
    by_dimensions: dict[
        tuple[float, float],
        list[tuple[float, float, float, float]],
    ] = {}
    for cell in cells:
        key = (
            round(
                (cell[2] - cell[0]) / frame_width,
                _TABLE_CELL_DIMENSION_ROUND_DIGITS,
            ),
            round(
                (cell[3] - cell[1]) / frame_height,
                _TABLE_CELL_DIMENSION_ROUND_DIGITS,
            ),
        )
        by_dimensions.setdefault(key, []).append(cell)

    cluster_tol = max(
        calibration.median_word_height_pt * 0.5,
        min(frame_width, frame_height) * 0.002,
        1.0,
    )
    for family in by_dimensions.values():
        if len(family) < _TABLE_CELL_COUNT:
            continue

        centers_x = [(cell[0] + cell[2]) / 2.0 for cell in family]
        centers_y = [(cell[1] + cell[3]) / 2.0 for cell in family]
        x_clusters = _cluster_values(centers_x, cluster_tol)
        y_clusters = _cluster_values(centers_y, cluster_tol)
        if len(x_clusters) < 2 or len(y_clusters) < 2:
            continue

        occupied: set[tuple[int, int]] = set()
        for x, y in zip(centers_x, centers_y):
            x_index = min(
                range(len(x_clusters)),
                key=lambda index: abs(x - x_clusters[index]),
            )
            y_index = min(
                range(len(y_clusters)),
                key=lambda index: abs(y - y_clusters[index]),
            )
            occupied.add((x_index, y_index))

        if len(occupied) < _TABLE_CELL_COUNT:
            continue
        occupancy = len(occupied) / (len(x_clusters) * len(y_clusters))
        if occupancy < _TABLE_GRID_OCCUPANCY_FRACTION:
            continue

        grid_bbox = (
            min(cell[0] for cell in family),
            min(cell[1] for cell in family),
            max(cell[2] for cell in family),
            max(cell[3] for cell in family),
        )
        if (
            _bbox_area(grid_bbox) / frame_area
            < _TABLE_GRID_FRAME_COVERAGE_FRACTION
        ):
            continue
        return True

    return _frame_looks_like_line_grid_table(frame, page, calibration)


def _rejected_ownership_frame(
    page: Any,
    frame: Sequence[float],
    calibration: ViewportLayoutCalibration,
    fragments: Sequence[tuple[tuple[float, float, float, float], str]],
    *,
    view_type: str,
) -> bool:
    if _is_page_or_crop_border(frame, calibration):
        return True
    if _frame_has_title_block_labels(frame, fragments, calibration):
        return True
    if (
        _frame_looks_like_table(frame, page, calibration)
        and str(view_type) not in _SEMANTIC_TABLE_VIEW_TYPES
    ):
        return True
    return False


def _normalise_text(text: str) -> str:
    return " ".join(str(text or "").replace("\n", " ").split()).strip()


def _strip_scale_suffix(text: str) -> str:
    return re.sub(
        r"\s*(?:[-–—]\s*)?(?:SCALE\s*)?\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*$",
        "",
        text,
        flags=re.I,
    ).strip()


def _text_fragments(page: Any) -> list[tuple[tuple[float, float, float, float], str]]:
    """Return span and line text evidence without block-level over-merging.

    CAD PDFs commonly place two distant titles on the same baseline. PyMuPDF may
    merge them into one block or line, while preserving separate spans. We keep
    span evidence and line evidence, then deduplicate equivalent fragments.
    """
    fragments: list[tuple[tuple[float, float, float, float], str]] = []
    try:
        data = _page_text(page, "dict") or {}
    except Exception:
        data = {}
    for block in data.get("blocks", []) or []:
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []) or []:
            spans = line.get("spans", []) or []
            for span in spans:
                text = _normalise_text(span.get("text", ""))
                bbox = span.get("bbox")
                if text and bbox and len(bbox) >= 4:
                    fragments.append(((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])), text))
            line_text = _normalise_text(" ".join(str(span.get("text", "")) for span in spans))
            line_bbox = line.get("bbox")
            if line_text and line_bbox and len(line_bbox) >= 4:
                fragments.append(((float(line_bbox[0]), float(line_bbox[1]), float(line_bbox[2]), float(line_bbox[3])), line_text))

    # Fallback for mock/page objects exposing blocks but not dict output.
    if not fragments:
        for block in _page_text(page, "blocks") or []:
            if len(block) >= 5:
                text = _normalise_text(block[4])
                if text:
                    fragments.append(((float(block[0]), float(block[1]), float(block[2]), float(block[3])), text))

    unique: list[tuple[tuple[float, float, float, float], str]] = []
    seen: set[tuple[float, float, float, float, str]] = set()
    for bbox, text in fragments:
        key = (round(bbox[0], 2), round(bbox[1], 2), round(bbox[2], 2), round(bbox[3], 2), text)
        if key in seen:
            continue
        seen.add(key); unique.append((bbox, text))
    return unique


def calibrate_viewport_layout(page: Any) -> ViewportLayoutCalibration:
    """Calibrate viewport geometry in the page's source coordinate space.

    Real PyMuPDF pages must resolve through the native page-frame contract.
    Lightweight synthetic test doubles have no PDF page tree, so they retain
    the historical unrotated page.rect calibration without weakening the
    production fail-closed path.
    """

    try:
        frame = native_page_frame(page)
        width = float(frame.native_width); height = float(frame.native_height)
        rotation = int(frame.rotation) % 360
    except NativePageFrameUnresolved:
        if isinstance(page, fitz.Page):
            raise
        rect = page.rect
        width = float(rect.width); height = float(rect.height)
        rotation = 0
    # Text orientation is a native PDF line property, independent of the
    # sheet's /Rotate flag.  On vertically advancing CAD text, the long Y
    # extent is word LENGTH, not glyph height.  Prefer the perpendicular
    # source glyph thickness from actual text lines; do not infer that an
    # arbitrary tall word necessarily has a vertical text baseline.
    glyph_heights = []
    try:
        text_dict = _page_text(page, "dict") or {}
    except (ValueError, RuntimeError, TypeError):
        text_dict = {}
    for block in text_dict.get("blocks", []) or []:
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []) or []:
            direction = _normalised_direction(line.get("dir") or (1.0, 0.0))
            vertical = abs(direction[1]) > abs(direction[0])
            for span in line.get("spans", []) or []:
                bbox = span.get("bbox") or ()
                if len(bbox) < 4 or not str(span.get("text") or "").strip():
                    continue
                cross_span = (
                    float(bbox[2]) - float(bbox[0])
                    if vertical else float(bbox[3]) - float(bbox[1])
                )
                if math.isfinite(cross_span) and cross_span > 0.0:
                    glyph_heights.append(cross_span)
    if not glyph_heights:
        # Preserve the existing source-verified /Rotate 90/270 behaviour
        # for lightweight producer doubles that have only word observations.
        for word in _page_text(page, "words"):
            native_width = float(word[2]) - float(word[0])
            native_height = float(word[3]) - float(word[1])
            if native_height <= 0.0:
                continue
            if (
                rotation in (90, 270)
                and native_width > 0.0
                and native_height > native_width * 1.25
            ):
                glyph_heights.append(native_width)
            else:
                glyph_heights.append(native_height)
    word_heights = glyph_heights
    median_h = statistics.median(word_heights) if word_heights else max(min(width, height) / 80.0, 1.0)
    return ViewportLayoutCalibration(
        median_word_height_pt=median_h,
        title_frame_gap_pt=max(median_h * 4.0, 2.0),
        minimum_frame_span_pt=max(median_h * 8.0, min(width, height) / 12.0),
        title_separation_pt=max(median_h * 6.0, 4.0),
        page_width_pt=width,
        page_height_pt=height,
    )


def _title_field_owned_regions(page: Any) -> list[tuple[float, float, float, float]]:
    """Regions ``pb_page_title_authority`` positively shows as title-field values.

    Reuses the page-title authority (native text only, no OCR) and nothing else:

    - the value box of a drawing-title field bound by an *explicit* title label
      ("Drawing name", "Drawing title", "Sheet title", ...), whether or not a
      title-block region is demonstrated;
    - when a title block *is* demonstrated (a cluster of drawing title-block
      field labels): that region and the bound values of fields inside it.

    A bare ``TITLE`` label, a weak label cluster, or an absent title block
    contribute nothing.  Regions are in the page's visual orientation, in page
    points.
    """
    try:
        rect = page.rect
        width = float(rect.width); height = float(rect.height)
        analysis = _title_authority.analyse_cells(
            _title_authority.page_cells(page), width, height, 0, "native"
        )
    except Exception:
        return []
    if width <= 0 or height <= 0:
        return []
    regions: list[tuple[float, float, float, float]] = []
    block = analysis.title_block
    if block is not None:
        regions.append(tuple(float(v) for v in block))
    for candidate in analysis.candidates:
        if candidate.kind != "label" or candidate.rejected or not candidate.text:
            continue
        explicit = candidate.label_strength == "title_explicit"
        in_block = block is not None and candidate.region == "title block"
        if not (explicit or in_block):
            continue
        box = candidate.box
        regions.append((box[0] * width, box[1] * height, box[2] * width, box[3] * height))
    return regions


def _proven_title_block_region(
    page: Any,
) -> Optional[tuple[float, float, float, float]]:
    """Return only a page-title-authority-proven native title-block region."""
    try:
        rect = page.rect
        width = float(rect.width)
        height = float(rect.height)
        analysis = _title_authority.analyse_cells(
            _title_authority.page_cells(page), width, height, 0, "native"
        )
    except Exception:
        return None
    block = analysis.title_block
    if block is None or width <= 0.0 or height <= 0.0:
        return None
    bbox = tuple(float(value) for value in block)
    if (
        len(bbox) != 4
        or bbox[2] <= bbox[0]
        or bbox[3] <= bbox[1]
        or bbox[0] < -1e-6
        or bbox[1] < -1e-6
        or bbox[2] > width + 1e-6
        or bbox[3] > height + 1e-6
    ):
        return None
    return bbox


def _drawing_vector_primitive_count(
    page: Any,
    bbox: Sequence[float],
    calibration: ViewportLayoutCalibration,
) -> int:
    """Count nontrivial native drawing primitives spatially owned by the bbox.

    This is a presence gate only. It never classifies walls/openings and never
    performs pairwise geometry work, so it stays linear in source primitives.
    """
    minimum_span = max(calibration.median_word_height_pt * 2.0, 4.0)
    count = 0
    try:
        drawings = _page_drawings(page)
    except Exception:
        drawings = []
    for drawing in drawings:
        for item in drawing.get("items", []) or []:
            if not item:
                continue
            primitive_bbox: Optional[tuple[float, float, float, float]] = None
            if item[0] == "l" and len(item) >= 3:
                start, end = item[1], item[2]
                primitive_bbox = _normalized_bbox(
                    float(start.x), float(start.y), float(end.x), float(end.y)
                )
                if math.hypot(
                    float(end.x) - float(start.x),
                    float(end.y) - float(start.y),
                ) < minimum_span:
                    continue
            elif item[0] == "re" and len(item) >= 2:
                rect = item[1]
                primitive_bbox = _normalized_bbox(
                    float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
                )
                if max(
                    primitive_bbox[2] - primitive_bbox[0],
                    primitive_bbox[3] - primitive_bbox[1],
                ) < minimum_span:
                    continue
            elif item[0] == "qu" and len(item) >= 2:
                primitive_bbox = _axis_aligned_quad_bbox(
                    item[1],
                    tol=max(calibration.median_word_height_pt * 0.15, 0.75),
                )
                if primitive_bbox is None:
                    continue
            if (
                primitive_bbox is not None
                and _point_in_bbox(_bbox_center(primitive_bbox), bbox)
            ):
                count += 1
    return count


@dataclass(frozen=True)
class _NativeLine:
    bbox: tuple[float, float, float, float]
    text: str
    size: float
    bold: bool
    horizontal: bool


_WRAP_MAX_GAP_SIZE_FRACTION = 0.6
_WRAP_MAX_OVERLAP_INTRUSION = 0.3
_WRAP_SIZE_TOLERANCE = 0.1
_WRAP_MIN_ALIGNED_OVERLAP = 0.4
_PDF_BOLD_FLAG = 16


def _native_line(line: dict[str, Any]) -> Optional[_NativeLine]:
    spans = line.get("spans", []) or []
    bbox = line.get("bbox")
    if not spans or not bbox or len(bbox) < 4:
        return None
    text = _normalise_text(" ".join(str(span.get("text", "")) for span in spans))
    if not text:
        return None
    direction = list(line.get("dir") or (1.0, 0.0)) + [0.0, 0.0]
    horizontal = abs(direction[1]) <= 0.2 * max(abs(direction[0]), 1e-9)
    return _NativeLine(
        bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        text=text,
        size=max(float(span.get("size", 0.0) or 0.0) for span in spans),
        bold=all(int(span.get("flags", 0) or 0) & _PDF_BOLD_FLAG for span in spans),
        horizontal=horizontal,
    )


def _wrapped_continuation(previous: _NativeLine, current: _NativeLine) -> bool:
    """``current`` continues ``previous`` as a wrapped line of the same text.

    Contiguous (leading within a fraction of the type size), aligned
    (horizontal overlap), of comparable type size, and not independently
    dominant (not bold where the previous line is not).
    """
    if not (previous.horizontal and current.horizontal) or previous.size <= 0 or current.size <= 0:
        return False
    gap = current.bbox[1] - previous.bbox[3]
    previous_height = previous.bbox[3] - previous.bbox[1]
    if gap > _WRAP_MAX_GAP_SIZE_FRACTION * previous.size or gap < -_WRAP_MAX_OVERLAP_INTRUSION * previous_height:
        return False
    if abs(current.size - previous.size) > _WRAP_SIZE_TOLERANCE * previous.size:
        return False
    if current.bold and not previous.bold:
        return False
    overlap = min(current.bbox[2], previous.bbox[2]) - max(current.bbox[0], previous.bbox[0])
    smaller = min(current.bbox[2] - current.bbox[0], previous.bbox[2] - previous.bbox[0])
    return smaller > 0 and overlap >= _WRAP_MIN_ALIGNED_OVERLAP * smaller


def _wrapped_title_fragments(
    page: Any,
) -> list[tuple[tuple[float, float, float, float], str]]:
    """Return only positively title-shaped wrapped native-line runs."""
    try:
        data = _page_text(page, "dict") or {}
    except Exception:
        return []

    fragments: list[tuple[tuple[float, float, float, float], str]] = []
    for block in data.get("blocks", []) or []:
        if int(block.get("type", 0)) != 0:
            continue
        lines = [
            line
            for line in (
                _native_line(item) for item in block.get("lines", []) or []
            )
            if line is not None
        ]
        runs: list[list[int]] = []
        for index, line in enumerate(lines):
            if index and _wrapped_continuation(lines[index - 1], line):
                runs[-1].append(index)
            else:
                runs.append([index])
        for run in runs:
            if len(run) < 2:
                continue
            merged = _normalise_text(" ".join(lines[index].text for index in run))
            if not _TITLE_SHAPE_RE.match(merged):
                continue
            view_type = DrawingViewClassifier.classify_text(
                _strip_scale_suffix(merged)
            ).value
            if view_type == DrawingViewType.UNKNOWN.value:
                continue
            bbox = (
                min(lines[index].bbox[0] for index in run),
                min(lines[index].bbox[1] for index in run),
                max(lines[index].bbox[2] for index in run),
                max(lines[index].bbox[3] for index in run),
            )
            fragments.append((bbox, merged))
    return fragments


def _wrapped_note_tail_lines(page: Any) -> list[tuple[tuple[float, float, float, float], str]]:
    """Lines (box, text) that are the wrapped tail of a note in the same native text block.

    A run of contiguous, aligned, comparably typeset lines inside one native
    PDF text block whose merged text the page-title authority rejects as a
    title (a sentence, too long, a list item, ...) owns its non-first lines:
    they are the tail of that note, never a standalone drawing title.  A
    stacked multi-line heading merges to a title-shaped text and is untouched;
    so is any first line of a run, and any line with independent typographic
    dominance (larger, or bold where the run is not).
    """
    try:
        data = _page_text(page, "dict") or {}
    except Exception:
        return []
    tails: list[tuple[tuple[float, float, float, float], str]] = []
    for block in data.get("blocks", []) or []:
        if int(block.get("type", 0)) != 0:
            continue
        lines = [ln for ln in (_native_line(line) for line in block.get("lines", []) or []) if ln is not None]
        runs: list[list[int]] = []
        for index, line in enumerate(lines):
            if index and _wrapped_continuation(lines[index - 1], line):
                runs[-1].append(index)
            else:
                runs.append([index])
        for run in runs:
            if len(run) < 2:
                continue
            merged = _normalise_text(" ".join(lines[i].text for i in run))
            if _title_authority.title_shape(merged, bound=False)[0] == 0.0:
                tails.extend((lines[i].bbox, lines[i].text) for i in run[1:])
    return tails


def _to_visual_bbox(page: Any, bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Express a text-dict bbox in the page's visual orientation."""
    if not int(getattr(page, "rotation", 0) or 0):
        return bbox
    try:
        import fitz  # a rotated page object implies PyMuPDF is present
        rotated = fitz.Rect(bbox) * page.rotation_matrix
        return (float(rotated.x0), float(rotated.y0), float(rotated.x1), float(rotated.y1))
    except Exception:
        return bbox


def _normalised_direction(value: object) -> tuple[float, float]:
    try:
        parts = tuple(float(item) for item in value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return (1.0, 0.0)
    if len(parts) < 2:
        return (1.0, 0.0)
    dx, dy = parts[0], parts[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 1e-9:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _bbox_in_text_basis(
    bbox: Sequence[float],
    direction: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Project one native bbox into a title-local reading coordinate system.

    Local +X follows text advance. Local +Y is the corresponding visual
    "below" direction. For ordinary text direction (1, 0), this is identical
    to native PDF coordinates. For vertical text this turns native left/right
    into above/below without guessing from bbox aspect ratio.
    """

    dx, dy = _normalised_direction(direction)
    vx, vy = -dy, dx
    corners = (
        (float(bbox[0]), float(bbox[1])),
        (float(bbox[2]), float(bbox[1])),
        (float(bbox[0]), float(bbox[3])),
        (float(bbox[2]), float(bbox[3])),
    )
    local_x = tuple(x * dx + y * dy for x, y in corners)
    local_y = tuple(x * vx + y * vy for x, y in corners)
    return (
        min(local_x),
        min(local_y),
        max(local_x),
        max(local_y),
    )


def _fragment_native_direction(
    page: Any,
    *,
    bbox: Sequence[float],
    text: str,
) -> tuple[float, float]:
    """Recover a unique producer-owned text direction for one title fragment."""

    target = _normalise_text(text)
    if not target:
        return (1.0, 0.0)
    try:
        data = _page_text(page, "dict") or {}
    except Exception:
        return (1.0, 0.0)

    candidates: list[tuple[float, float]] = []
    target_box = tuple(float(value) for value in bbox[:4])
    target_area = max(_bbox_area(target_box), 1e-9)
    for block in data.get("blocks", []) or []:
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []) or []:
            line_bbox = line.get("bbox") or ()
            if len(line_bbox) < 4:
                continue
            line_box = tuple(float(value) for value in line_bbox[:4])
            line_text = _normalise_text(
                " ".join(
                    str(span.get("text", ""))
                    for span in line.get("spans", []) or []
                )
            )
            possible_boxes: list[tuple[float, float, float, float]] = []
            if line_text == target:
                possible_boxes.append(line_box)
            for span in line.get("spans", []) or []:
                if _normalise_text(str(span.get("text", ""))) != target:
                    continue
                span_bbox = span.get("bbox") or ()
                if len(span_bbox) >= 4:
                    possible_boxes.append(
                        tuple(float(value) for value in span_bbox[:4])
                    )
            if not possible_boxes:
                continue
            if not any(
                _bbox_overlap_area(target_box, candidate)
                / min(target_area, max(_bbox_area(candidate), 1e-9))
                >= 0.8
                for candidate in possible_boxes
            ):
                continue
            candidates.append(
                _normalised_direction(line.get("dir") or (1.0, 0.0))
            )

    unique = {
        (round(direction[0], 6), round(direction[1], 6))
        for direction in candidates
    }
    if len(unique) != 1:
        return (1.0, 0.0)
    dx, dy = next(iter(unique))
    return _normalised_direction((dx, dy))


def _to_native_bbox(
    page: Any,
    bbox: tuple[float, float, float, float],
) -> Optional[tuple[float, float, float, float]]:
    """Map one visual/display bbox back into native page user space."""

    if not int(getattr(page, "rotation", 0) or 0):
        return _normalized_bbox(*bbox)
    try:
        import fitz

        native = fitz.Rect(bbox) * page.derotation_matrix
        result = _normalized_bbox(
            float(native.x0),
            float(native.y0),
            float(native.x1),
            float(native.y1),
        )
    except Exception:
        return None
    if (
        result[2] <= result[0]
        or result[3] <= result[1]
        or not all(math.isfinite(value) for value in result)
    ):
        return None
    return result


def extract_view_title_anchors(page: Any) -> list[_TitleAnchor]:
    candidates: list[_TitleAnchor] = []
    owned: Optional[list[tuple[float, float, float, float]]] = None
    tails: Optional[list[tuple[tuple[float, float, float, float], str]]] = None
    title_fragments = [
        *_text_fragments(page),
        *_wrapped_title_fragments(page),
    ]
    for bbox, text in title_fragments:
        if not _TITLE_SHAPE_RE.match(text):
            continue
        view_type = DrawingViewClassifier.classify_text(_strip_scale_suffix(text)).value
        if view_type == DrawingViewType.UNKNOWN.value:
            continue
        if owned is None:
            owned = _title_field_owned_regions(page)
        if owned and any(_point_in_bbox(_bbox_center(_to_visual_bbox(page, bbox)), region) for region in owned):
            continue  # a title-field value, not a drawing-view title
        if tails is None:
            tails = _wrapped_note_tail_lines(page)
        if tails and any(text in tail_text and _point_in_bbox(_bbox_center(bbox), tail_bbox) for tail_bbox, tail_text in tails):
            continue  # the wrapped tail of a note, not a drawing-view title
        candidates.append(
            _TitleAnchor(
                text=text,
                bbox=bbox,
                view_type=view_type,
                direction=_fragment_native_direction(
                    page,
                    bbox=bbox,
                    text=text,
                ),
            )
        )

    # Prefer the tighter span when a line-level fragment duplicates it.
    candidates.sort(key=lambda a: (_bbox_area(a.bbox), a.bbox[1], a.bbox[0], a.text))
    anchors: list[_TitleAnchor] = []
    for candidate in candidates:
        duplicate = any(
            existing.text == candidate.text
            and abs(existing.center[0] - candidate.center[0]) <= 1.0
            and abs(existing.center[1] - candidate.center[1]) <= 1.0
            for existing in anchors
        )
        if not duplicate:
            anchors.append(candidate)
    anchors.sort(key=lambda a: (a.center[1], a.center[0], a.text))
    return anchors


def extract_vector_frames(page: Any, calibration: ViewportLayoutCalibration) -> list[tuple[float, float, float, float]]:
    frames: list[tuple[float, float, float, float]] = []
    tol = max(calibration.median_word_height_pt * 0.15, 0.75)
    for drawing in _page_drawings(page):
        items = drawing.get("items", []) or []
        closed = _closed_four_line_rect(items, tol=tol)
        if closed is not None:
            frames.append(closed)
        for item in items:
            if not item:
                continue
            bbox = None
            if item[0] == "re" and len(item) >= 2:
                rect = item[1]
                bbox = _normalized_bbox(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
            elif item[0] == "qu" and len(item) >= 2:
                bbox = _axis_aligned_quad_bbox(item[1], tol=tol)
            if bbox is None:
                continue
            frames.append(bbox)
    usable: list[tuple[float, float, float, float]] = []
    for bbox in frames:
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width < calibration.minimum_frame_span_pt or height < calibration.minimum_frame_span_pt:
            continue
        if _frame_aspect_ratio(bbox) > _MAX_FRAME_ASPECT_RATIO:
            continue
        if _is_page_or_crop_border(bbox, calibration):
            continue
        usable.append(bbox)
    unique: list[tuple[float, float, float, float]] = []
    eps = max(calibration.median_word_height_pt * 0.1, 0.25)
    for frame in sorted(usable, key=lambda b: (_bbox_area(b), b)):
        if any(all(abs(frame[i] - other[i]) <= eps for i in range(4)) for other in unique):
            continue
        unique.append(frame)
    return unique


def _frame_candidates_for_title(
    page: Any,
    anchor: _TitleAnchor,
    frames: Sequence[tuple[float, float, float, float]],
    calibration: ViewportLayoutCalibration,
    anchors: Sequence[_TitleAnchor] = (),
) -> list[tuple[float, float, float, float]]:
    """Bind native vector frames to drawing titles in visual orientation.

    The source frame and returned viewport bbox remain in native page user
    space. A title may be inside that frame directly. For the common
    "title-below-frame" convention, however, below/overlap are visual-layout
    relationships, so both title and frame are explicitly transformed into
    display orientation before evaluating that relation. This is essential on
    /Rotate 90 pages, where visual "below" is native "to the right".
    """

    candidates: list[tuple[float, float, float, float]] = []
    direction = _normalised_direction(anchor.direction)
    title_is_native_vertical = (
        str(anchor.view_type) in _SEMANTIC_TABLE_VIEW_TYPES
        and abs(direction[1]) > abs(direction[0])
    )
    visual_anchor_bbox = (
        _bbox_in_text_basis(anchor.bbox, direction)
        if title_is_native_vertical
        else _to_visual_bbox(page, anchor.bbox)
    )
    visual_title_center = _bbox_center(visual_anchor_bbox)
    for frame in frames:
        if _bbox_contains(
            frame,
            anchor.bbox,
            margin=calibration.median_word_height_pt * 0.25,
        ):
            candidates.append(frame)
            continue

        visual_frame = (
            _bbox_in_text_basis(frame, direction)
            if title_is_native_vertical
            else _to_visual_bbox(page, frame)
        )
        overlap = min(visual_frame[2], visual_anchor_bbox[2]) - max(
            visual_frame[0], visual_anchor_bbox[0]
        )
        title_width = max(
            visual_anchor_bbox[2] - visual_anchor_bbox[0],
            1e-6,
        )
        if max(0.0, overlap) / title_width < _TITLE_HORIZONTAL_OVERLAP_FRACTION:
            continue
        if not (
            visual_frame[0]
            <= visual_title_center[0]
            <= visual_frame[2]
        ):
            continue

        gap = visual_anchor_bbox[1] - visual_frame[3]
        if not (
            0
            <= gap
            <= _max_title_below_frame_gap(visual_frame, calibration)
        ):
            continue

        gap_box = (
            visual_frame[0],
            visual_frame[3],
            visual_frame[2],
            visual_anchor_bbox[1],
        )
        if any(
            other is not anchor
            and _point_in_bbox(
                _bbox_center(
                    _bbox_in_text_basis(other.bbox, direction)
                    if title_is_native_vertical
                    else _to_visual_bbox(page, other.bbox)
                ),
                gap_box,
            )
            for other in anchors
        ):
            continue
        candidates.append(frame)
    return candidates


def _extract_scales_for_bbox(page: Any, bbox: Sequence[float]) -> tuple[Optional[str], Optional[float], bool, list[str]]:
    seen: list[tuple[str, float]] = []
    for text_bbox, text in _text_fragments(page):
        if not _point_in_bbox(_bbox_center(text_bbox), bbox):
            continue
        for match in _SCALE_RE.finditer(text):
            numerator = float(match.group(1)); denominator = float(match.group(2))
            if numerator <= 0 or denominator <= 0:
                continue
            seen.append((match.group(0), denominator / numerator))
    unique = sorted({round(value, 9) for _, value in seen})
    if not unique:
        return None, None, False, []
    if len(unique) > 1:
        return None, None, True, [f"conflicting viewport scales: {', '.join(str(v) for v in unique)}"]
    value = unique[0]
    raw = next(raw for raw, denominator in seen if round(denominator, 9) == value)
    return raw, value, False, []


def _frame_resolved_viewports(
    page: Any,
    anchors: Sequence[_TitleAnchor],
    frames: Sequence[tuple[float, float, float, float]],
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> tuple[list[SegmentedViewport], set[int]]:
    fragments = _text_fragments(page)
    selected: dict[int, tuple[float, float, float, float]] = {}
    out: list[SegmentedViewport] = []; consumed: set[int] = set()
    for index, anchor in enumerate(anchors):
        candidates = _frame_candidates_for_title(
            page,
            anchor,
            frames,
            calibration,
            anchors=anchors,
        )
        if str(anchor.view_type) in _SEMANTIC_TABLE_VIEW_TYPES:
            table_candidates = [
                frame
                for frame in candidates
                if _frame_looks_like_table(frame, page, calibration)
            ]
            if table_candidates:
                candidates = table_candidates
        usable = [
            frame for frame in candidates
            if not _rejected_ownership_frame(
                page,
                frame,
                calibration,
                fragments,
                view_type=anchor.view_type,
            )
        ]
        usable = _collapse_nested_band_frames(usable)
        usable = _collapse_equivalent_nested_frames(usable, calibration)
        if len(usable) > 1 and anchor.view_type == DrawingViewType.FLOOR_PLAN.value:
            usable = _collapse_source_repeated_plan_border_pair(
                page, usable, calibration, fragments
            )
        if len(usable) > 1:
            out.append(SegmentedViewport(
                view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
                view_type=anchor.view_type, label=anchor.text, title_bbox=anchor.bbox,
                bounding_box=None, status=ViewportSegmentationStatus.AMBIGUOUS.value,
                boundary_source=ViewportBoundarySource.NONE.value, confidence=0.0,
                notes=["multiple equivalent vector frames compete for this title"],
                provenance={"candidate_frames": list(usable)},
            ))
            consumed.add(index)
            continue
        if len(usable) == 1:
            selected[index] = usable[0]

    frame_to_indices: dict[tuple[float, float, float, float], list[int]] = {}
    for index, frame in selected.items():
        frame_to_indices.setdefault(frame, []).append(index)

    for frame, indices in frame_to_indices.items():
        if len(indices) > 1:
            for index in indices:
                anchor = anchors[index]
                out.append(SegmentedViewport(
                    view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
                    view_type=anchor.view_type, label=anchor.text, title_bbox=anchor.bbox,
                    bounding_box=None, status=ViewportSegmentationStatus.AMBIGUOUS.value,
                    boundary_source=ViewportBoundarySource.NONE.value, confidence=0.0,
                    notes=["multiple classified titles resolve to the same vector frame"],
                    provenance={"candidate_frame": frame},
                )); consumed.add(index)
            continue
        index = indices[0]; anchor = anchors[index]
        raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(page, frame)
        out.append(SegmentedViewport(
            view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
            view_type=anchor.view_type, label=anchor.text, title_bbox=anchor.bbox,
            bounding_box=frame, status=ViewportSegmentationStatus.RESOLVED.value,
            boundary_source=ViewportBoundarySource.VECTOR_FRAME.value, confidence=1.0,
            scale_raw=raw, scale_denominator=denominator, scale_conflict=scale_conflict,
            notes=scale_notes, provenance={"frame_bbox": frame, "title_bbox": anchor.bbox},
        )); consumed.add(index)
    return out, consumed



_AUTHORITATIVE_DERIVED_PARTITION_MODE = "columnar_title_grid"
_ROTATED_SEMANTIC_FRAME_BAND_MODE = "rotated_semantic_frame_band"
_PLAN_VIEW_TYPES = frozenset({DrawingViewType.FLOOR_PLAN.value, DrawingViewType.FLOOR_FINISH_PLAN.value, DrawingViewType.REFLECTED_CEILING_PLAN.value})
_SINGLE_FLOOR_PLAN_PARTITION_MODE = "single_floor_plan_printable_area"
_SINGLE_FLOOR_PLAN_SHEET_FRAME_MODE = "single_floor_plan_sheet_frame"
_SINGLE_FLOOR_FINISH_PARTITION_MODE = "single_floor_finish_plan_printable_area"
_SINGLE_FLOOR_FINISH_SHEET_FRAME_MODE = "single_floor_finish_plan_sheet_frame"
_SINGLE_REFLECTED_CEILING_PARTITION_MODE = "single_reflected_ceiling_printable_area"
_SINGLE_REFLECTED_CEILING_SHEET_FRAME_MODE = "single_reflected_ceiling_sheet_frame"


def is_authoritative_derived_viewport(viewport: Any) -> bool:
    """Return True only for producer-proven strict derived ownership modes."""
    provenance = getattr(viewport, "provenance", {}) or {}
    if not (
        getattr(viewport, "status", None) == ViewportSegmentationStatus.DERIVED.value
        and getattr(viewport, "boundary_source", None)
        == ViewportBoundarySource.TITLE_PARTITION.value
        and getattr(viewport, "bounding_box", None) is not None
    ):
        return False
    mode = provenance.get("partition_mode")
    if mode == _AUTHORITATIVE_DERIVED_PARTITION_MODE:
        return provenance.get("grid_validated") is True
    if mode == _ROTATED_SEMANTIC_FRAME_BAND_MODE:
        return bool(provenance.get("visual_band_validated") is True and int(provenance.get("rotation", 0) or 0) in (90, 270) and str(provenance.get("separator_view_id") or "") and int(provenance.get("plan_title_count_in_band", 0) or 0) == 1 and int(provenance.get("drawing_vector_primitive_count", 0) or 0) >= 2)
    if mode in (
        _SINGLE_FLOOR_PLAN_PARTITION_MODE,
        _SINGLE_FLOOR_FINISH_PARTITION_MODE,
        _SINGLE_REFLECTED_CEILING_PARTITION_MODE,
    ):
        return bool(
            provenance.get("single_view_validated") is True
            and provenance.get("title_block_bbox")
            and int(provenance.get("drawing_vector_primitive_count", 0) or 0) >= 2
        )
    if mode in (
        _SINGLE_FLOOR_PLAN_SHEET_FRAME_MODE,
        _SINGLE_FLOOR_FINISH_SHEET_FRAME_MODE,
        _SINGLE_REFLECTED_CEILING_SHEET_FRAME_MODE,
    ):
        return bool(
            provenance.get("single_view_validated") is True
            and int(provenance.get("metadata_label_count", 0) or 0) >= 2
            and int(provenance.get("drawing_vector_primitive_count", 0) or 0) >= 2
        )
    return False


def _title_identity(anchor: _TitleAnchor) -> tuple[str, str]:
    return (
        re.sub(r"\s+", " ", str(anchor.text).strip().upper()),
        str(anchor.view_type),
    )


def _cluster_title_columns(
    anchors: Sequence[_TitleAnchor],
    indices: Sequence[int],
    *,
    tolerance: float,
) -> list[list[int]]:
    """Cluster title anchors by X only; callers still prove Y separation."""
    ordered = sorted(indices, key=lambda i: anchors[i].center[0])
    clusters: list[list[int]] = []
    for index in ordered:
        x = anchors[index].center[0]
        if not clusters:
            clusters.append([index])
            continue
        center = statistics.median(anchors[i].center[0] for i in clusters[-1])
        if abs(x - center) <= tolerance:
            clusters[-1].append(index)
        else:
            clusters.append([index])
    return clusters


def _columnar_title_grid_partitions(
    page: Any,
    anchors: Sequence[_TitleAnchor],
    unresolved_indices: Sequence[int],
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> Optional[list[SegmentedViewport]]:
    """Derive a strict non-overlapping 2-D title grid.

    This fallback exists for CAD sheets whose views form independent vertical
    columns. It is deliberately stricter than the ordinary one-axis title
    partition:

    - at least two independently separated columns are required;
    - every column must contain at least two distinct view-title rows;
    - distinct row titles in one column must be separated by at least one
      minimum plausible viewport span;
    - exact same-label near-duplicates may collapse to one canonical anchor,
      but different labels that collide remain ambiguous;
    - every resulting cell must itself meet the minimum viewport span and
      contain its canonical title;
    - cells are page-partition rectangles and therefore cannot overlap.

    The resulting viewports remain DERIVED, but carry producer-owned provenance
    allowing downstream code to distinguish this validated grid from looser
    diagnostic title partitions.
    """
    if len(unresolved_indices) < 4:
        return None

    x_clusters = _cluster_title_columns(
        anchors,
        unresolved_indices,
        tolerance=calibration.title_separation_pt,
    )
    if len(x_clusters) < 2:
        return None

    column_rows: list[dict[str, Any]] = []
    duplicate_indices: list[tuple[int, int]] = []

    for cluster in x_clusters:
        ordered = sorted(cluster, key=lambda i: anchors[i].center[1])
        groups: list[list[int]] = []
        for index in ordered:
            if not groups:
                groups.append([index])
                continue
            previous_group = groups[-1]
            previous_y = statistics.median(
                anchors[i].center[1] for i in previous_group
            )
            y = anchors[index].center[1]
            if abs(y - previous_y) < calibration.title_separation_pt:
                identities = {_title_identity(anchors[i]) for i in previous_group}
                if identities == {_title_identity(anchors[index])}:
                    previous_group.append(index)
                    continue
                # Two different titles too close to own separate viewports.
                return None
            groups.append([index])

        canonical: list[int] = []
        for group in groups:
            # Preserve the strongest text anchor and explicitly mark exact
            # near-duplicates as non-owning evidence.
            winner = max(
                group,
                key=lambda i: (
                    _bbox_area(anchors[i].bbox),
                    anchors[i].center[1],
                    -anchors[i].center[0],
                ),
            )
            canonical.append(winner)
            duplicate_indices.extend((i, winner) for i in group if i != winner)

        canonical.sort(key=lambda i: anchors[i].center[1])
        if len(canonical) < 2:
            return None
        row_centers = [anchors[i].center[1] for i in canonical]
        if any(
            row_centers[i + 1] - row_centers[i] < calibration.minimum_frame_span_pt
            for i in range(len(row_centers) - 1)
        ):
            return None

        column_rows.append(
            {
                "indices": canonical,
                "center_x": statistics.median(
                    anchors[i].center[0] for i in canonical
                ),
                "row_centers": row_centers,
            }
        )

    column_rows.sort(key=lambda item: item["center_x"])
    column_centers = [float(item["center_x"]) for item in column_rows]
    if any(
        column_centers[i + 1] - column_centers[i]
        < calibration.minimum_frame_span_pt
        for i in range(len(column_centers) - 1)
    ):
        return None

    x_bounds = [0.0]
    x_bounds.extend(
        (column_centers[i] + column_centers[i + 1]) / 2.0
        for i in range(len(column_centers) - 1)
    )
    x_bounds.append(calibration.page_width_pt)

    out: list[SegmentedViewport] = []
    for column_position, column in enumerate(column_rows):
        row_indices = list(column["indices"])
        row_centers = list(column["row_centers"])
        y_bounds = [0.0]
        y_bounds.extend(
            (row_centers[i] + row_centers[i + 1]) / 2.0
            for i in range(len(row_centers) - 1)
        )
        y_bounds.append(calibration.page_height_pt)

        for row_position, index in enumerate(row_indices):
            bbox = (
                float(x_bounds[column_position]),
                float(y_bounds[row_position]),
                float(x_bounds[column_position + 1]),
                float(y_bounds[row_position + 1]),
            )
            if (
                bbox[2] - bbox[0] < calibration.minimum_frame_span_pt
                or bbox[3] - bbox[1] < calibration.minimum_frame_span_pt
            ):
                return None
            anchor = anchors[index]
            if not _bbox_contains(bbox, anchor.bbox):
                return None
            raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(
                page, bbox
            )
            duplicates = [
                anchors[dup].bbox
                for dup, owner in duplicate_indices
                if owner == index
            ]
            out.append(
                SegmentedViewport(
                    view_id=f"view_p{page_number}_{index + 1}",
                    page_number=page_number,
                    view_type=anchor.view_type,
                    label=anchor.text,
                    title_bbox=anchor.bbox,
                    bounding_box=bbox,
                    status=ViewportSegmentationStatus.DERIVED.value,
                    boundary_source=ViewportBoundarySource.TITLE_PARTITION.value,
                    confidence=0.75,
                    scale_raw=raw,
                    scale_denominator=denominator,
                    scale_conflict=scale_conflict,
                    notes=[
                        "viewport boundary derived from validated non-overlapping columnar title grid",
                        *scale_notes,
                    ],
                    provenance={
                        "partition_mode": _AUTHORITATIVE_DERIVED_PARTITION_MODE,
                        "grid_validated": True,
                        "column_index": column_position,
                        "column_count": len(column_rows),
                        "row_index": row_position,
                        "row_count": len(row_indices),
                        "title_bbox": anchor.bbox,
                        "duplicate_title_bboxes": duplicates,
                    },
                )
            )

    # Preserve duplicate source titles as non-owning diagnostic evidence rather
    # than minting a second viewport over the same region.
    for duplicate, owner in duplicate_indices:
        anchor = anchors[duplicate]
        out.append(
            SegmentedViewport(
                view_id=f"view_p{page_number}_{duplicate + 1}",
                page_number=page_number,
                view_type=anchor.view_type,
                label=anchor.text,
                title_bbox=anchor.bbox,
                bounding_box=None,
                status=ViewportSegmentationStatus.AMBIGUOUS.value,
                boundary_source=ViewportBoundarySource.NONE.value,
                confidence=0.0,
                notes=["near-duplicate same-label title collapsed into validated grid owner"],
                provenance={
                    "duplicate_of_view_id": f"view_p{page_number}_{owner + 1}",
                    "duplicate_title_bbox": anchor.bbox,
                },
            )
        )

    usable = [
        viewport for viewport in out
        if viewport.bounding_box is not None
    ]
    if len(usable) < 4 or not validate_non_overlapping_viewports(usable):
        return None
    return out


def _axis_aligned_long_source_lines(
    page: Any,
    calibration: ViewportLayoutCalibration,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[float, float, float], ...],
]:
    """Collect only long native horizontal/vertical line primitives in O(N)."""
    tolerance = max(calibration.median_word_height_pt * 0.15, 0.75)
    min_horizontal = calibration.page_width_pt * 0.55
    min_vertical = calibration.page_height_pt * 0.55
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    try:
        drawings = _page_drawings(page)
    except Exception:
        drawings = []
    for drawing in drawings:
        for item in drawing.get("items", []) or []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            x0, y0 = float(start.x), float(start.y)
            x1, y1 = float(end.x), float(end.y)
            if abs(y1 - y0) <= tolerance and abs(x1 - x0) >= min_horizontal:
                horizontal.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2.0))
            elif abs(x1 - x0) <= tolerance and abs(y1 - y0) >= min_vertical:
                vertical.append(((x0 + x1) / 2.0, min(y0, y1), max(y0, y1)))
    return tuple(horizontal), tuple(vertical)


def _sheet_metadata_label_count_outside(
    page: Any,
    bbox: Sequence[float],
) -> int:
    labels: set[str] = set()
    for text_bbox, text in _text_fragments(page):
        if _point_in_bbox(_bbox_center(text_bbox), bbox):
            continue
        match = _SHEET_METADATA_LABEL_RE.search(text)
        if match:
            labels.add(_normalise_text(match.group(0)).upper())
    return len(labels)


def _single_view_sheet_drawing_frames(
    page: Any,
    anchor: _TitleAnchor,
    calibration: ViewportLayoutCalibration,
) -> list[tuple[tuple[float, float, float, float], int, int]]:
    """Find closed large sheet drawing frames without full-source pair scans.

    Long source lines are bucketed by their endpoint spans. Adjacent horizontal
    boundaries are checked only against the matching vertical-span bucket, so
    work remains linear/log-linear in source primitive count.
    """
    horizontal, vertical = _axis_aligned_long_source_lines(page, calibration)
    if len(horizontal) < 2 or len(vertical) < 2:
        return []

    tolerance = max(calibration.median_word_height_pt * 0.2, 0.75)

    def bucket(value: float) -> int:
        return int(round(float(value) / tolerance))

    horizontal_by_span: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    for line in horizontal:
        horizontal_by_span.setdefault(
            (bucket(line[0]), bucket(line[1])),
            [],
        ).append(line)

    vertical_by_span: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    for line in vertical:
        vertical_by_span.setdefault(
            (bucket(line[1]), bucket(line[2])),
            [],
        ).append(line)

    candidates: list[tuple[tuple[float, float, float, float], int, int]] = []
    for rows in horizontal_by_span.values():
        ordered = sorted(rows, key=lambda line: line[2])
        for top, bottom in zip(ordered, ordered[1:]):
            x0 = (top[0] + bottom[0]) / 2.0
            x1 = (top[1] + bottom[1]) / 2.0
            y0, y1 = top[2], bottom[2]
            bbox = (x0, y0, x1, y1)
            width = x1 - x0
            height = y1 - y0
            if (
                width < calibration.page_width_pt * 0.60
                or height < calibration.page_height_pt * 0.55
                or _bbox_area(bbox)
                < calibration.page_width_pt * calibration.page_height_pt * 0.45
                or _is_page_or_crop_border(bbox, calibration)
                or not _bbox_contains(
                    bbox,
                    anchor.bbox,
                    margin=calibration.median_word_height_pt * 0.25,
                )
            ):
                continue

            span_key = (bucket(y0), bucket(y1))
            columns: list[tuple[float, float, float]] = []
            for dy0 in (-1, 0, 1):
                for dy1 in (-1, 0, 1):
                    columns.extend(
                        vertical_by_span.get(
                            (span_key[0] + dy0, span_key[1] + dy1),
                            (),
                        )
                    )
            if not columns:
                continue
            has_left = any(abs(column[0] - x0) <= tolerance for column in columns)
            has_right = any(abs(column[0] - x1) <= tolerance for column in columns)
            if not (has_left and has_right):
                continue

            metadata_count = _sheet_metadata_label_count_outside(page, bbox)
            if metadata_count < 2:
                continue

            margin = max(calibration.median_word_height_pt * 2.0, 2.0)
            interior = (
                bbox[0] + margin,
                bbox[1] + margin,
                bbox[2] - margin,
                bbox[3] - margin,
            )
            primitive_count = _drawing_vector_primitive_count(
                page,
                interior,
                calibration,
            )
            if primitive_count < 2:
                continue
            candidates.append((bbox, metadata_count, primitive_count))
    return candidates


def _single_floor_plan_sheet_frame_partition(
    page: Any,
    anchor: _TitleAnchor,
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> Optional[SegmentedViewport]:
    if anchor.view_type not in (
        DrawingViewType.FLOOR_PLAN.value,
        DrawingViewType.FLOOR_FINISH_PLAN.value,
        DrawingViewType.REFLECTED_CEILING_PLAN.value,
    ):
        return None
    candidates = _single_view_sheet_drawing_frames(page, anchor, calibration)
    if len(candidates) != 1:
        return None
    bbox, metadata_count, primitive_count = candidates[0]
    raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(
        page, bbox
    )
    return SegmentedViewport(
        view_id=f"view_p{page_number}_1",
        page_number=page_number,
        view_type=anchor.view_type,
        label=anchor.text,
        title_bbox=anchor.bbox,
        bounding_box=bbox,
        status=ViewportSegmentationStatus.DERIVED.value,
        boundary_source=ViewportBoundarySource.TITLE_PARTITION.value,
        confidence=0.95,
        scale_raw=raw,
        scale_denominator=denominator,
        scale_conflict=scale_conflict,
        notes=[
            (
                "single floor plan owns closed native sheet drawing frame with separate metadata band"
                if anchor.view_type == DrawingViewType.FLOOR_PLAN.value
                else (
                    "single floor finish plan owns closed native sheet drawing frame with separate metadata band"
                    if anchor.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
                    else "single reflected ceiling plan owns closed native sheet drawing frame with separate metadata band"
                )
            ),
            *scale_notes,
        ],
        provenance={
            "partition_mode": (
                _SINGLE_FLOOR_PLAN_SHEET_FRAME_MODE
                if anchor.view_type == DrawingViewType.FLOOR_PLAN.value
                else (
                    _SINGLE_FLOOR_FINISH_SHEET_FRAME_MODE
                    if anchor.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
                    else _SINGLE_REFLECTED_CEILING_SHEET_FRAME_MODE
                )
            ),
            "single_view_validated": True,
            "metadata_label_count": metadata_count,
            "drawing_vector_primitive_count": primitive_count,
            "title_bbox": anchor.bbox,
            "sheet_frame_bbox": bbox,
        },
    )


def _single_floor_plan_printable_partition(
    page: Any,
    anchor: _TitleAnchor,
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> Optional[SegmentedViewport]:
    """Resolve one unframed semantic plan from page ownership, fail-closed."""
    if anchor.view_type not in (
        DrawingViewType.FLOOR_PLAN.value,
        DrawingViewType.FLOOR_FINISH_PLAN.value,
        DrawingViewType.REFLECTED_CEILING_PLAN.value,
    ):
        return None
    # pb_page_title_authority deliberately works in visual/display space.
    # Until that title-block rectangle has an explicit display->native bridge,
    # do not compare it with native viewport geometry on a rotated page. The
    # independent native vector-frame route above remains available.
    try:
        if native_page_frame(page).rotation != 0:
            return None
    except NativePageFrameUnresolved:
        return None
    title_block = _proven_title_block_region(page)
    if title_block is None:
        return None

    width = calibration.page_width_pt
    height = calibration.page_height_pt
    # Title blocks are often inset from the crop edge by a normal drawing
    # margin. Require ownership of an outer page band rather than literal edge
    # contact, while rejecting central tables/panels.
    occupies_outer_band = (
        title_block[0] <= width * 0.25
        or title_block[2] >= width * 0.75
        or title_block[1] <= height * 0.25
        or title_block[3] >= height * 0.75
    )
    if not occupies_outer_band:
        return None

    gap = max(calibration.median_word_height_pt * 0.5, 1.0)
    candidates: list[tuple[float, float, float, float]] = []
    if title_block[0] - gap >= calibration.minimum_frame_span_pt:
        candidates.append((0.0, 0.0, title_block[0] - gap, height))
    if width - (title_block[2] + gap) >= calibration.minimum_frame_span_pt:
        candidates.append((title_block[2] + gap, 0.0, width, height))
    if title_block[1] - gap >= calibration.minimum_frame_span_pt:
        candidates.append((0.0, 0.0, width, title_block[1] - gap))
    if height - (title_block[3] + gap) >= calibration.minimum_frame_span_pt:
        candidates.append((0.0, title_block[3] + gap, width, height))

    valid: list[tuple[tuple[float, float, float, float], int]] = []
    for bbox in candidates:
        if not _bbox_contains(
            bbox,
            anchor.bbox,
            margin=calibration.median_word_height_pt * 0.25,
        ):
            continue
        primitive_count = _drawing_vector_primitive_count(page, bbox, calibration)
        if primitive_count < 2:
            continue
        valid.append((bbox, primitive_count))
    if not valid:
        return None

    bbox, primitive_count = max(
        valid,
        key=lambda item: (_bbox_area(item[0]), item[1]),
    )
    raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(
        page, bbox
    )
    return SegmentedViewport(
        view_id=f"view_p{page_number}_1",
        page_number=page_number,
        view_type=anchor.view_type,
        label=anchor.text,
        title_bbox=anchor.bbox,
        bounding_box=bbox,
        status=ViewportSegmentationStatus.DERIVED.value,
        boundary_source=ViewportBoundarySource.TITLE_PARTITION.value,
        confidence=0.9,
        scale_raw=raw,
        scale_denominator=denominator,
        scale_conflict=scale_conflict,
        notes=[
            (
                "single floor plan owns proven printable area outside native title block"
                if anchor.view_type == DrawingViewType.FLOOR_PLAN.value
                else (
                    "single floor finish plan owns proven printable area outside native title block"
                    if anchor.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
                    else "single reflected ceiling plan owns proven printable area outside native title block"
                )
            ),
            *scale_notes,
        ],
        provenance={
            "partition_mode": (
                _SINGLE_FLOOR_PLAN_PARTITION_MODE
                if anchor.view_type == DrawingViewType.FLOOR_PLAN.value
                else (
                    _SINGLE_FLOOR_FINISH_PARTITION_MODE
                    if anchor.view_type == DrawingViewType.FLOOR_FINISH_PLAN.value
                    else _SINGLE_REFLECTED_CEILING_PARTITION_MODE
                )
            ),
            "single_view_validated": True,
            "title_block_bbox": title_block,
            "drawing_vector_primitive_count": primitive_count,
            "title_bbox": anchor.bbox,
        },
    )


def _rotated_semantic_frame_band_partitions(
    page: Any,
    anchors: Sequence[_TitleAnchor],
    unresolved_indices: Sequence[int],
    framed: Sequence[SegmentedViewport],
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> tuple[list[SegmentedViewport], set[int]]:
    """Derive plan bands on rotated sheets from an authenticated table frame.

    This is intentionally much narrower than generic title partitioning.
    A resolved semantic-table frame may act as a physical separator only when
    exactly one unresolved plan title owns one side band, no resolved viewport
    overlaps that band, and the band contains real drawing primitives.  All
    reasoning is performed in display orientation; the published viewport bbox
    is converted back to native PDF user space.
    """

    try:
        rotation = int(native_page_frame(page).rotation) % 360
    except NativePageFrameUnresolved:
        return [], set()
    if rotation not in (90, 270):
        return [], set()

    separators = [
        viewport
        for viewport in framed
        if (
            viewport.bounding_box is not None
            and viewport.status == ViewportSegmentationStatus.RESOLVED.value
            and viewport.view_type in _SEMANTIC_TABLE_VIEW_TYPES
        )
    ]
    plan_indices = [
        index
        for index in unresolved_indices
        if anchors[index].view_type in _PLAN_VIEW_TYPES
    ]
    if not separators or not plan_indices:
        return [], set()

    try:
        visual_width = float(page.rect.width)
        visual_height = float(page.rect.height)
    except Exception:
        return [], set()
    if visual_width <= 0.0 or visual_height <= 0.0:
        return [], set()

    visual_anchor_boxes = {
        index: _to_visual_bbox(page, anchors[index].bbox)
        for index in plan_indices
    }
    framed_visual = [
        (
            viewport,
            _to_visual_bbox(page, viewport.bounding_box),
        )
        for viewport in framed
        if viewport.bounding_box is not None
    ]
    gap = max(calibration.median_word_height_pt * 0.25, 0.5)
    candidates_by_index: dict[
        int,
        list[
            tuple[
                tuple[float, float, float, float],
                tuple[float, float, float, float],
                str,
                str,
                int,
            ]
        ],
    ] = {}

    for separator in separators:
        assert separator.bounding_box is not None
        visual_separator = _to_visual_bbox(
            page,
            separator.bounding_box,
        )
        side_bands = (
            (
                "left",
                (
                    0.0,
                    0.0,
                    max(0.0, visual_separator[0] - gap),
                    visual_height,
                ),
            ),
            (
                "right",
                (
                    min(visual_width, visual_separator[2] + gap),
                    0.0,
                    visual_width,
                    visual_height,
                ),
            ),
            (
                "top",
                (
                    0.0,
                    0.0,
                    visual_width,
                    max(0.0, visual_separator[1] - gap),
                ),
            ),
            (
                "bottom",
                (
                    0.0,
                    min(visual_height, visual_separator[3] + gap),
                    visual_width,
                    visual_height,
                ),
            ),
        )
        for side, visual_band in side_bands:
            if (
                visual_band[2] - visual_band[0]
                < calibration.minimum_frame_span_pt
                or visual_band[3] - visual_band[1]
                < calibration.minimum_frame_span_pt
            ):
                continue

            owning_plan_indices = [
                index
                for index in plan_indices
                if _bbox_contains(
                    visual_band,
                    visual_anchor_boxes[index],
                    margin=calibration.median_word_height_pt * 0.1,
                )
            ]
            if len(owning_plan_indices) != 1:
                continue
            # A competing title of ANY classified drawing kind makes this
            # physical band ambiguous, not merely another plan title.
            if sum(
                1 for other in anchors
                if _bbox_contains(
                    visual_band,
                    _to_visual_bbox(page, other.bbox),
                    margin=calibration.median_word_height_pt * 0.1,
                )
            ) != 1:
                continue
            index = owning_plan_indices[0]

            if any(
                _bbox_overlap_area(visual_band, other_visual) > 1e-6
                for other, other_visual in framed_visual
            ):
                continue

            native_band = _to_native_bbox(page, visual_band)
            if native_band is None or not _bbox_contains(
                native_band,
                anchors[index].bbox,
                margin=calibration.median_word_height_pt * 0.1,
            ):
                continue

            primitive_count = _drawing_vector_primitive_count(
                page,
                native_band,
                calibration,
            )
            if primitive_count < 2:
                continue
            candidates_by_index.setdefault(index, []).append(
                (
                    visual_band,
                    native_band,
                    separator.view_id,
                    side,
                    primitive_count,
                )
            )

    out: list[SegmentedViewport] = []
    consumed: set[int] = set()
    for index in sorted(candidates_by_index):
        unique: dict[
            tuple[float, float, float, float],
            tuple[
                tuple[float, float, float, float],
                tuple[float, float, float, float],
                str,
                str,
                int,
            ],
        ] = {}
        if len(candidates_by_index[index]) != 1:
            continue
        for candidate in candidates_by_index[index]:
            key = tuple(round(value, 6) for value in candidate[1])
            unique[key] = candidate
        if len(unique) != 1:
            continue
        (
            visual_band,
            native_band,
            separator_view_id,
            side,
            primitive_count,
        ) = next(iter(unique.values()))
        anchor = anchors[index]
        raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(
            page,
            native_band,
        )
        out.append(
            SegmentedViewport(
                view_id=f"view_p{page_number}_{index + 1}",
                page_number=page_number,
                view_type=anchor.view_type,
                label=anchor.text,
                title_bbox=anchor.bbox,
                bounding_box=native_band,
                status=ViewportSegmentationStatus.DERIVED.value,
                boundary_source=ViewportBoundarySource.TITLE_PARTITION.value,
                confidence=0.9,
                scale_raw=raw,
                scale_denominator=denominator,
                scale_conflict=scale_conflict,
                notes=[
                    (
                        "rotated plan viewport owned by non-overlapping "
                        "semantic-frame side band"
                    ),
                    *scale_notes,
                ],
                provenance={
                    "partition_mode": _ROTATED_SEMANTIC_FRAME_BAND_MODE,
                    "visual_band_validated": True,
                    "rotation": rotation,
                    "separator_view_id": separator_view_id,
                    "separator_side": side,
                    "visual_band_bbox": visual_band,
                    "plan_title_count_in_band": 1,
                    "drawing_vector_primitive_count": primitive_count,
                    "title_bbox": anchor.bbox,
                },
            )
        )
        consumed.add(index)

    if not validate_non_overlapping_viewports([*framed, *out]):
        return [], set()
    return out, consumed


def _derived_partitions(
    page: Any,
    anchors: Sequence[_TitleAnchor],
    unresolved_indices: Sequence[int],
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> list[SegmentedViewport]:
    if len(unresolved_indices) < 2:
        if len(unresolved_indices) == 1 and len(anchors) == 1:
            index = unresolved_indices[0]
            single = _single_floor_plan_sheet_frame_partition(
                page,
                anchors[index],
                calibration,
                page_number=page_number,
            )
            if single is None:
                single = _single_floor_plan_printable_partition(
                    page,
                    anchors[index],
                    calibration,
                    page_number=page_number,
                )
            if single is not None:
                return [single]
        return [SegmentedViewport(
            view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
            view_type=anchors[index].view_type, label=anchors[index].text,
            title_bbox=anchors[index].bbox, bounding_box=None,
            status=ViewportSegmentationStatus.UNSUPPORTED.value,
            boundary_source=ViewportBoundarySource.NONE.value, confidence=0.0,
            notes=["single unframed title does not prove viewport extent"],
        ) for index in unresolved_indices]

    centers = [anchors[i].center for i in unresolved_indices]
    x_spread = max(p[0] for p in centers) - min(p[0] for p in centers)
    y_spread = max(p[1] for p in centers) - min(p[1] for p in centers)
    axis = 0 if x_spread / max(calibration.page_width_pt, 1.0) >= y_spread / max(calibration.page_height_pt, 1.0) else 1
    ordered = sorted(unresolved_indices, key=lambda i: (anchors[i].center[axis], anchors[i].center[1 - axis]))
    coords = [anchors[i].center[axis] for i in ordered]
    close = any(abs(coords[i + 1] - coords[i]) < calibration.title_separation_pt for i in range(len(coords) - 1))
    if close:
        grid = _columnar_title_grid_partitions(
            page,
            anchors,
            unresolved_indices,
            calibration,
            page_number=page_number,
        )
        if grid is not None:
            return grid

    # The same title text and view type more than once, unframed and not a
    # validated title grid: nothing positively separates that group into
    # independent drawing views, so no partition is manufactured for it.  Only
    # the duplicate group is quarantined; unrelated anchors go on through their
    # own evidence path.
    identity_counts: dict[tuple[str, str], int] = {}
    for index in unresolved_indices:
        identity = _title_identity(anchors[index])
        identity_counts[identity] = identity_counts.get(identity, 0) + 1
    duplicated = [i for i in unresolved_indices if identity_counts[_title_identity(anchors[i])] > 1]
    if duplicated:
        quarantined = [SegmentedViewport(
            view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
            view_type=anchors[index].view_type, label=anchors[index].text,
            title_bbox=anchors[index].bbox, bounding_box=None,
            status=ViewportSegmentationStatus.AMBIGUOUS.value,
            boundary_source=ViewportBoundarySource.NONE.value, confidence=0.0,
            notes=["unframed same-identity titles are not proven independent views"],
        ) for index in duplicated]
        remaining = [i for i in unresolved_indices if i not in set(duplicated)]
        return quarantined + _derived_partitions(
            page, anchors, remaining, calibration, page_number=page_number,
        )

    if close:
        return [SegmentedViewport(
            view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
            view_type=anchors[index].view_type, label=anchors[index].text,
            title_bbox=anchors[index].bbox, bounding_box=None,
            status=ViewportSegmentationStatus.AMBIGUOUS.value,
            boundary_source=ViewportBoundarySource.NONE.value, confidence=0.0,
            notes=["unframed title anchors are not spatially separable"],
        ) for index in unresolved_indices]

    bounds = [0.0]
    bounds.extend((coords[i] + coords[i + 1]) / 2.0 for i in range(len(coords) - 1))
    bounds.append(calibration.page_width_pt if axis == 0 else calibration.page_height_pt)
    out: list[SegmentedViewport] = []
    for position, index in enumerate(ordered):
        bbox = (
            (bounds[position], 0.0, bounds[position + 1], calibration.page_height_pt)
            if axis == 0 else
            (0.0, bounds[position], calibration.page_width_pt, bounds[position + 1])
        )
        anchor = anchors[index]
        raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(page, bbox)
        out.append(SegmentedViewport(
            view_id=f"view_p{page_number}_{index + 1}", page_number=page_number,
            view_type=anchor.view_type, label=anchor.text, title_bbox=anchor.bbox,
            bounding_box=bbox, status=ViewportSegmentationStatus.DERIVED.value,
            boundary_source=ViewportBoundarySource.TITLE_PARTITION.value, confidence=0.5,
            scale_raw=raw, scale_denominator=denominator, scale_conflict=scale_conflict,
            notes=["viewport boundary derived from non-overlapping title partition", *scale_notes],
            provenance={"partition_axis": "x" if axis == 0 else "y", "title_bbox": anchor.bbox},
        ))
    return out


def segment_page_viewports(page: Any, *, page_number: int) -> list[SegmentedViewport]:
    try:
        calibration = calibrate_viewport_layout(page)
    except NativePageFrameUnresolved:
        # Unvalidated real-page rotations remain non-authoritative, but retain
        # the historical diagnostic title rows rather than disappearing.
        anchors = extract_view_title_anchors(page)
        rotation = getattr(page, "rotation", None)
        if not anchors or not isinstance(rotation, int) or isinstance(rotation, bool):
            return []
        rotation %= 360
        if rotation not in (180, 270):
            return []
        return _stamp_segment_page_viewports_product([
            SegmentedViewport(
                view_id=f"view_p{page_number}_{index + 1}",
                page_number=page_number,
                view_type=anchor.view_type,
                label=anchor.text,
                title_bbox=anchor.bbox,
                bounding_box=None,
                status=ViewportSegmentationStatus.UNSUPPORTED.value,
                boundary_source=ViewportBoundarySource.NONE.value,
                confidence=0.0,
                notes=["page rotation is not promoted for viewport authority"],
                provenance={
                    "rotation": rotation,
                    "derived_partition_disabled": True,
                },
            )
            for index, anchor in enumerate(anchors)
        ])
    anchors = extract_view_title_anchors(page)
    if not anchors:
        return []
    frames = extract_vector_frames(page, calibration)
    framed, consumed = _frame_resolved_viewports(
        page,
        anchors,
        frames,
        calibration,
        page_number=page_number,
    )
    unresolved = [i for i in range(len(anchors)) if i not in consumed]
    try:
        page_rotation = native_page_frame(page).rotation
    except NativePageFrameUnresolved:
        return []
    if unresolved and page_rotation != 0:
        rotated_derived, rotated_consumed = _rotated_semantic_frame_band_partitions(
            page, anchors, unresolved, framed, calibration,
            page_number=page_number,
        )
        remaining_unresolved = [
            index for index in unresolved if index not in rotated_consumed
        ]
        derived = [
            *rotated_derived,
            *[
                SegmentedViewport(
                    view_id=f"view_p{page_number}_{index + 1}",
                    page_number=page_number,
                    view_type=anchors[index].view_type,
                    label=anchors[index].text,
                    title_bbox=anchors[index].bbox,
                    bounding_box=None,
                    status=ViewportSegmentationStatus.UNSUPPORTED.value,
                    boundary_source=ViewportBoundarySource.NONE.value,
                    confidence=0.0,
                    notes=["rotated page lacks unique producer-owned frame/band ownership"],
                    provenance={"rotation": page_rotation, "derived_partition_disabled": True},
                )
                for index in remaining_unresolved
            ],
        ]
    else:
        derived = (
            _derived_partitions(
                page,
                anchors,
                unresolved,
                calibration,
                page_number=page_number,
            )
            if unresolved
            else []
        )
    ordered = sorted(
        framed + derived,
        key=lambda v: (v.title_bbox[1], v.title_bbox[0], v.view_id),
    )
    return _stamp_segment_page_viewports_product(ordered)


def _source_image_placement_groups(page: Any) -> tuple[dict[str, Any], ...]:
    """Inspect producer image placements without synthesizing drawing frames.

    Repeated XObjects are evidence of raster tiling, not of a drawing viewport.
    Retain independent xref identity and physical placement coordinates.  This
    function deliberately cannot create an authenticated SegmentedViewport.
    """
    get_images = getattr(page, "get_images", None)
    get_rects = getattr(page, "get_image_rects", None)
    if not callable(get_images) or not callable(get_rects):
        return ()
    try:
        images = get_images(full=True)
    except (RuntimeError, ValueError, TypeError):
        return ()
    groups = []
    for image in images:
        if not image:
            continue
        xref = image[0]
        try:
            placements = get_rects(xref)
        except (RuntimeError, ValueError, TypeError):
            continue
        boxes = sorted({
            tuple(float(v) for v in (r.x0, r.y0, r.x1, r.y1))
            for r in placements
            if float(r.x1) > float(r.x0) and float(r.y1) > float(r.y0)
        })
        if not boxes:
            continue
        groups.append({
            "xref": int(xref),
            "placements": len(boxes),
            "native_bboxes": tuple(boxes),
            "source_region_complete": False,
        })
    return tuple(sorted(groups, key=lambda row: row["xref"]))


def _raster_placement_components(groups: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Group touching source raster placements, without declaring plan ownership."""
    tiles = sorted(
        (tuple(float(v) for v in box), int(group["xref"]))
        for group in groups for box in group["native_bboxes"]
    )
    parent = list(range(len(tiles)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (a, _xref) in enumerate(tiles):
        for j in range(i + 1, len(tiles)):
            b = tiles[j][0]
            if b[0] > a[2] + 0.25:
                break
            overlap_x = min(a[2], b[2]) - max(a[0], b[0])
            overlap_y = min(a[3], b[3]) - max(a[1], b[1])
            if overlap_x < -0.25 or overlap_y < -0.25:
                continue
            if overlap_x <= 0 and overlap_y <= 0:
                continue  # corner contact is not connected coverage
            ri, rj = root(i), root(j)
            if ri != rj:
                parent[rj] = ri

    components: dict[int, list[int]] = {}
    for i in range(len(tiles)):
        components.setdefault(root(i), []).append(i)
    result = []
    for indices in components.values():
        boxes = [tiles[i][0] for i in indices]
        result.append({
            "native_bbox": (
                min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes),
            ),
            "placement_count": len(indices),
            "image_xrefs": tuple(sorted({tiles[i][1] for i in indices})),
            "authenticated_viewport": False,
        })
    return tuple(sorted(result, key=lambda component: component["native_bbox"]))


def assign_bbox_to_viewport(
    bbox: Sequence[float],
    viewports: Iterable[SegmentedViewport],
    *,
    allow_derived: bool = True,
) -> Optional[SegmentedViewport]:
    center = _bbox_center(bbox)
    allowed = {ViewportSegmentationStatus.RESOLVED.value}
    if allow_derived:
        allowed.add(ViewportSegmentationStatus.DERIVED.value)
    matches = [v for v in viewports if v.status in allowed and v.bounding_box is not None and _point_in_bbox(center, v.bounding_box)]
    return matches[0] if len(matches) == 1 else None


def validate_non_overlapping_viewports(viewports: Sequence[SegmentedViewport]) -> bool:
    usable = [v for v in viewports if v.bounding_box is not None and v.status in (
        ViewportSegmentationStatus.RESOLVED.value,
        ViewportSegmentationStatus.DERIVED.value,
    )]
    for i, left in enumerate(usable):
        for right in usable[i + 1:]:
            if _bbox_overlap_area(left.bounding_box, right.bounding_box) > 1e-6:
                return False
    return True
