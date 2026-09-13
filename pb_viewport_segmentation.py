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
- page borders, crop boxes, title-block panels, and table grids are not viewports;
- scale is associated only after viewport ownership; conflicting scales remain
  unresolved;
- viewport IDs are provenance only, never semantic prediction features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import statistics
from typing import Any, Iterable, Optional, Sequence

from pb_drawing_evidence_binding import DrawingViewClassifier, DrawingViewRegion, DrawingViewType


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

    @property
    def center(self) -> tuple[float, float]:
        return _bbox_center(self.bbox)


_SCALE_RE = re.compile(r"\b(?:SCALE\s*)?(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\b", re.I)
_TITLE_BLOCK_LABEL_RE = re.compile(
    r"\b(?:drawing\s+(?:title|no\.?|number)|rev(?:ision)?|checked by|drawn by|approved|"
    r"consultant|client|date)\b",
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
_TITLE_SHAPE_RE = re.compile(
    r"^\s*(?:"
    r"(?:GROUND|FIRST|SECOND|THIRD|UPPER|LOWER|LEVEL\s*[A-Z0-9.-]+)?\s*FLOOR\s+PLAN|"
    r"LAYOUT\s+PLAN|ROOF(?:ING)?\s+(?:LAYOUT\s+)?PLAN|"
    r"(?:NORTH|SOUTH|EAST|WEST|FRONT|REAR|SIDE)?\s*ELEV(?:ATION)?(?:\s+[A-Z0-9.-]+)?|"
    r"SECTION(?:\s+[A-Z0-9.-]+)?|CROSS\s+SECTION|LONGITUDINAL\s+SECTION|"
    r"(?:WINDOW|DOOR|FINISH(?:ES)?)\s+SCHEDULE|SCHEDULE\s+OF\s+(?:WINDOWS|DOORS|FINISHES)|"
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


def _frame_looks_like_table(
    frame: Sequence[float],
    page: Any,
) -> bool:
    cells = 0
    frame_area = _bbox_area(frame)
    if frame_area <= 0:
        return False
    for drawing in page.get_drawings() or []:
        for item in drawing.get("items", []) or []:
            if not item or item[0] != "re" or len(item) < 2:
                continue
            rect = item[1]
            cell = _normalized_bbox(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
            if not _bbox_contains(frame, cell, margin=1.0):
                continue
            if _bbox_area(cell) < 0.15 * frame_area and _bbox_area(cell) > 4.0:
                cells += 1
            if cells >= _TABLE_CELL_COUNT:
                return True
    return False


def _rejected_ownership_frame(
    page: Any,
    frame: Sequence[float],
    calibration: ViewportLayoutCalibration,
    fragments: Sequence[tuple[tuple[float, float, float, float], str]],
) -> bool:
    if _is_page_or_crop_border(frame, calibration):
        return True
    if _frame_has_title_block_labels(frame, fragments, calibration):
        return True
    if _frame_looks_like_table(frame, page):
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
        data = page.get_text("dict") or {}
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
        for block in page.get_text("blocks") or []:
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
    rect = page.rect
    width = float(rect.width); height = float(rect.height)
    word_heights = [
        float(w[3]) - float(w[1])
        for w in page.get_text("words")
        if float(w[3]) > float(w[1])
    ]
    median_h = statistics.median(word_heights) if word_heights else max(min(width, height) / 80.0, 1.0)
    return ViewportLayoutCalibration(
        median_word_height_pt=median_h,
        title_frame_gap_pt=max(median_h * 4.0, 2.0),
        minimum_frame_span_pt=max(median_h * 8.0, min(width, height) / 12.0),
        title_separation_pt=max(median_h * 6.0, 4.0),
        page_width_pt=width,
        page_height_pt=height,
    )


def extract_view_title_anchors(page: Any) -> list[_TitleAnchor]:
    candidates: list[_TitleAnchor] = []
    for bbox, text in _text_fragments(page):
        if not _TITLE_SHAPE_RE.match(text):
            continue
        view_type = DrawingViewClassifier.classify_text(_strip_scale_suffix(text)).value
        if view_type == DrawingViewType.UNKNOWN.value:
            continue
        candidates.append(_TitleAnchor(text=text, bbox=bbox, view_type=view_type))

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
    for drawing in page.get_drawings() or []:
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
    anchor: _TitleAnchor,
    frames: Sequence[tuple[float, float, float, float]],
    calibration: ViewportLayoutCalibration,
    anchors: Sequence[_TitleAnchor] = (),
) -> list[tuple[float, float, float, float]]:
    candidates: list[tuple[float, float, float, float]] = []
    title_center = anchor.center
    for frame in frames:
        if _bbox_contains(frame, anchor.bbox, margin=calibration.median_word_height_pt * 0.25):
            candidates.append(frame)
            continue
        if _title_horizontal_overlap_fraction(anchor, frame) < _TITLE_HORIZONTAL_OVERLAP_FRACTION:
            continue
        if not (frame[0] <= title_center[0] <= frame[2]):
            continue
        gap = anchor.bbox[1] - frame[3]
        if not (0 <= gap <= _max_title_below_frame_gap(frame, calibration)):
            continue
        if _other_title_in_title_gap(anchor, frame, anchors):
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
        candidates = _frame_candidates_for_title(anchor, frames, calibration, anchors=anchors)
        usable = [
            frame for frame in candidates
            if not _rejected_ownership_frame(page, frame, calibration, fragments)
        ]
        usable = _collapse_nested_band_frames(usable)
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


def _derived_partitions(
    page: Any,
    anchors: Sequence[_TitleAnchor],
    unresolved_indices: Sequence[int],
    calibration: ViewportLayoutCalibration,
    *,
    page_number: int,
) -> list[SegmentedViewport]:
    if len(unresolved_indices) < 2:
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
    if any(abs(coords[i + 1] - coords[i]) < calibration.title_separation_pt for i in range(len(coords) - 1)):
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
    calibration = calibrate_viewport_layout(page)
    anchors = extract_view_title_anchors(page)
    if not anchors:
        return []
    frames = extract_vector_frames(page, calibration)
    framed, consumed = _frame_resolved_viewports(page, anchors, frames, calibration, page_number=page_number)
    unresolved = [i for i in range(len(anchors)) if i not in consumed]
    derived = _derived_partitions(page, anchors, unresolved, calibration, page_number=page_number) if unresolved else []
    return sorted(framed + derived, key=lambda v: (v.title_bbox[1], v.title_bbox[0], v.view_id))


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
