"""Evidence-backed drawing viewport segmentation (PlanReader Phase F.07).

This module turns drawing-title observations into spatial viewport ownership.
The previous :func:`DrawingViewClassifier.partition_sheet_views` API classifies
view-title text, but its region bbox is only the title text bbox.  That is useful
for classification, not for deciding which dimensions, scales, openings, or
references belong to which drawing view.

F.07 deliberately separates three states:

* ``RESOLVED``: a title is tied to an enclosing/adjacent native vector frame.
* ``DERIVED``: multiple unframed title anchors support a non-overlapping page
  partition.  This is lower authority and is never allowed to overlap another
  derived viewport.
* ``AMBIGUOUS`` / ``UNSUPPORTED``: ownership is not guessed.

Safety invariants:
- project name, filename, path, benchmark identity, hashes, and expected outputs
  are not inputs;
- thresholds are expressed relative to page typography or page extent;
- a word such as "elevation" inside prose is not enough to create a viewport;
- one vector frame shared by multiple classified titles is ambiguous;
- scale text is associated only after viewport ownership; conflicting scales
  remain unresolved;
- viewport IDs are provenance only and never semantic prediction features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
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
    """Spatial tolerances derived from the current page's typography/extent."""

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

# These patterns describe the *shape* of a drawing title.  They intentionally
# require the block itself to look like a title rather than merely containing a
# view word in prose.
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
    x0 = max(float(a[0]), float(b[0]))
    y0 = max(float(a[1]), float(b[1]))
    x1 = min(float(a[2]), float(b[2]))
    y1 = min(float(a[3]), float(b[3]))
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def calibrate_viewport_layout(page: Any) -> ViewportLayoutCalibration:
    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)
    word_heights = [
        float(w[3]) - float(w[1])
        for w in page.get_text("words")
        if float(w[3]) > float(w[1])
    ]
    median_h = statistics.median(word_heights) if word_heights else max(min(width, height) / 80.0, 1.0)
    return ViewportLayoutCalibration(
        median_word_height_pt=median_h,
        # Titles frequently sit immediately inside or beneath a drawing frame.
        title_frame_gap_pt=max(median_h * 4.0, 2.0),
        # A view frame must be materially larger than text/title decoration.
        minimum_frame_span_pt=max(median_h * 8.0, min(width, height) / 12.0),
        # Separate title anchors need real visual separation before deriving a
        # partition in the absence of frames.
        title_separation_pt=max(median_h * 6.0, 4.0),
        page_width_pt=width,
        page_height_pt=height,
    )


def _normalise_title_text(text: str) -> str:
    return " ".join(str(text or "").replace("\n", " ").split()).strip()


def _strip_scale_suffix(text: str) -> str:
    return re.sub(r"\s*(?:[-–—]\s*)?(?:SCALE\s*)?\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*$", "", text, flags=re.I).strip()


def _is_title_like(text: str) -> bool:
    normalized = _normalise_title_text(text)
    if not normalized:
        return False
    return bool(_TITLE_SHAPE_RE.match(normalized))


def extract_view_title_anchors(page: Any) -> list[_TitleAnchor]:
    anchors: list[_TitleAnchor] = []
    for block in page.get_text("blocks") or []:
        if len(block) < 5:
            continue
        text = _normalise_title_text(str(block[4]))
        if not _is_title_like(text):
            continue
        view_type = DrawingViewClassifier.classify_text(_strip_scale_suffix(text)).value
        if view_type == DrawingViewType.UNKNOWN.value:
            continue
        bbox = (float(block[0]), float(block[1]), float(block[2]), float(block[3]))
        anchors.append(_TitleAnchor(text=text, bbox=bbox, view_type=view_type))
    anchors.sort(key=lambda a: (a.center[1], a.center[0], a.text))
    return anchors


def _xy(point: Any) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    return float(point[0]), float(point[1])


def extract_vector_frames(page: Any, calibration: ViewportLayoutCalibration) -> list[tuple[float, float, float, float]]:
    """Extract plausible native vector rectangles that can delimit viewports."""
    page_area = calibration.page_width_pt * calibration.page_height_pt
    frames: list[tuple[float, float, float, float]] = []
    for drawing in page.get_drawings() or []:
        for item in drawing.get("items", []) or []:
            if not item or item[0] != "re" or len(item) < 2:
                continue
            rect = item[1]
            bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            if width < calibration.minimum_frame_span_pt or height < calibration.minimum_frame_span_pt:
                continue
            area = _bbox_area(bbox)
            # The sheet border is not a viewport.  This is a normalized page
            # extent check, independent of paper size or project identity.
            if page_area > 0 and area / page_area >= 0.95:
                continue
            frames.append(bbox)
    # Stable deduplication for exporters that repeat the same rectangle path.
    unique: list[tuple[float, float, float, float]] = []
    eps = max(calibration.median_word_height_pt * 0.1, 0.25)
    for frame in sorted(frames, key=lambda b: (_bbox_area(b), b)):
        if any(all(abs(frame[i] - other[i]) <= eps for i in range(4)) for other in unique):
            continue
        unique.append(frame)
    return unique


def _frame_candidates_for_title(
    anchor: _TitleAnchor,
    frames: Sequence[tuple[float, float, float, float]],
    calibration: ViewportLayoutCalibration,
) -> list[tuple[float, float, float, float]]:
    candidates: list[tuple[float, float, float, float]] = []
    title_center = anchor.center
    for frame in frames:
        if _bbox_contains(frame, anchor.bbox, margin=calibration.median_word_height_pt * 0.25):
            candidates.append(frame)
            continue
        # Common convention: title immediately below its drawing frame.
        horizontally_aligned = frame[0] <= title_center[0] <= frame[2]
        gap = anchor.bbox[1] - frame[3]
        if horizontally_aligned and 0 <= gap <= calibration.title_frame_gap_pt:
            candidates.append(frame)
    return sorted(candidates, key=lambda b: (_bbox_area(b), b))


def _extract_scales_for_bbox(page: Any, bbox: Sequence[float]) -> tuple[Optional[str], Optional[float], bool, list[str]]:
    seen: list[tuple[str, float]] = []
    for block in page.get_text("blocks") or []:
        if len(block) < 5:
            continue
        block_bbox = (float(block[0]), float(block[1]), float(block[2]), float(block[3]))
        if not _point_in_bbox(_bbox_center(block_bbox), bbox):
            continue
        text = _normalise_title_text(str(block[4]))
        for match in _SCALE_RE.finditer(text):
            numerator = float(match.group(1))
            denominator = float(match.group(2))
            if numerator <= 0 or denominator <= 0:
                continue
            normalized_denominator = denominator / numerator
            seen.append((match.group(0), normalized_denominator))
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
    selected: dict[int, tuple[float, float, float, float]] = {}
    for index, anchor in enumerate(anchors):
        candidates = _frame_candidates_for_title(anchor, frames, calibration)
        if candidates:
            selected[index] = candidates[0]

    # One physical frame cannot authoritatively belong to two different view
    # titles.  Mark both ambiguous rather than choosing by list order.
    frame_to_indices: dict[tuple[float, float, float, float], list[int]] = {}
    for index, frame in selected.items():
        frame_to_indices.setdefault(frame, []).append(index)

    out: list[SegmentedViewport] = []
    consumed: set[int] = set()
    for frame, indices in frame_to_indices.items():
        if len(indices) > 1:
            for index in indices:
                anchor = anchors[index]
                out.append(
                    SegmentedViewport(
                        view_id=f"view_p{page_number}_{index + 1}",
                        page_number=page_number,
                        view_type=anchor.view_type,
                        label=anchor.text,
                        title_bbox=anchor.bbox,
                        bounding_box=None,
                        status=ViewportSegmentationStatus.AMBIGUOUS.value,
                        boundary_source=ViewportBoundarySource.NONE.value,
                        confidence=0.0,
                        notes=["multiple classified titles resolve to the same vector frame"],
                        provenance={"candidate_frame": frame},
                    )
                )
                consumed.add(index)
            continue
        index = indices[0]
        anchor = anchors[index]
        raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(page, frame)
        out.append(
            SegmentedViewport(
                view_id=f"view_p{page_number}_{index + 1}",
                page_number=page_number,
                view_type=anchor.view_type,
                label=anchor.text,
                title_bbox=anchor.bbox,
                bounding_box=frame,
                status=ViewportSegmentationStatus.RESOLVED.value,
                boundary_source=ViewportBoundarySource.VECTOR_FRAME.value,
                confidence=1.0,
                scale_raw=raw,
                scale_denominator=denominator,
                scale_conflict=scale_conflict,
                notes=scale_notes,
                provenance={"frame_bbox": frame, "title_bbox": anchor.bbox},
            )
        )
        consumed.add(index)
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
        return [
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
                notes=["single unframed title does not prove viewport extent"],
            )
            for index in unresolved_indices
        ]

    centers = [anchors[i].center for i in unresolved_indices]
    x_spread = max(p[0] for p in centers) - min(p[0] for p in centers)
    y_spread = max(p[1] for p in centers) - min(p[1] for p in centers)
    normalized_x = x_spread / max(calibration.page_width_pt, 1.0)
    normalized_y = y_spread / max(calibration.page_height_pt, 1.0)
    axis = 0 if normalized_x >= normalized_y else 1
    ordered = sorted(unresolved_indices, key=lambda i: (anchors[i].center[axis], anchors[i].center[1 - axis]))
    coords = [anchors[i].center[axis] for i in ordered]
    if any(abs(coords[i + 1] - coords[i]) < calibration.title_separation_pt for i in range(len(coords) - 1)):
        return [
            SegmentedViewport(
                view_id=f"view_p{page_number}_{index + 1}",
                page_number=page_number,
                view_type=anchors[index].view_type,
                label=anchors[index].text,
                title_bbox=anchors[index].bbox,
                bounding_box=None,
                status=ViewportSegmentationStatus.AMBIGUOUS.value,
                boundary_source=ViewportBoundarySource.NONE.value,
                confidence=0.0,
                notes=["unframed title anchors are not spatially separable"],
            )
            for index in unresolved_indices
        ]

    bounds = [0.0]
    bounds.extend((coords[i] + coords[i + 1]) / 2.0 for i in range(len(coords) - 1))
    bounds.append(calibration.page_width_pt if axis == 0 else calibration.page_height_pt)

    out: list[SegmentedViewport] = []
    for position, index in enumerate(ordered):
        if axis == 0:
            bbox = (bounds[position], 0.0, bounds[position + 1], calibration.page_height_pt)
        else:
            bbox = (0.0, bounds[position], calibration.page_width_pt, bounds[position + 1])
        anchor = anchors[index]
        raw, denominator, scale_conflict, scale_notes = _extract_scales_for_bbox(page, bbox)
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
                confidence=0.5,
                scale_raw=raw,
                scale_denominator=denominator,
                scale_conflict=scale_conflict,
                notes=["viewport boundary derived from non-overlapping title partition", *scale_notes],
                provenance={"partition_axis": "x" if axis == 0 else "y", "title_bbox": anchor.bbox},
            )
        )
    return out


def segment_page_viewports(page: Any, *, page_number: int) -> list[SegmentedViewport]:
    """Segment one native PDF page into evidence-backed drawing viewports."""
    calibration = calibrate_viewport_layout(page)
    anchors = extract_view_title_anchors(page)
    if not anchors:
        return []
    frames = extract_vector_frames(page, calibration)
    framed, consumed = _frame_resolved_viewports(
        page, anchors, frames, calibration, page_number=page_number
    )
    unresolved = [i for i in range(len(anchors)) if i not in consumed]
    derived = _derived_partitions(
        page, anchors, unresolved, calibration, page_number=page_number
    ) if unresolved else []
    return sorted(framed + derived, key=lambda v: (v.title_bbox[1], v.title_bbox[0], v.view_id))


def assign_bbox_to_viewport(
    bbox: Sequence[float],
    viewports: Iterable[SegmentedViewport],
    *,
    allow_derived: bool = True,
) -> Optional[SegmentedViewport]:
    """Return a unique viewport owning the bbox centre, else fail closed."""
    center = _bbox_center(bbox)
    allowed_status = {ViewportSegmentationStatus.RESOLVED.value}
    if allow_derived:
        allowed_status.add(ViewportSegmentationStatus.DERIVED.value)
    matches = [
        viewport
        for viewport in viewports
        if viewport.status in allowed_status
        and viewport.bounding_box is not None
        and _point_in_bbox(center, viewport.bounding_box)
    ]
    if len(matches) != 1:
        return None
    # Guard against a malformed caller-provided viewport set with overlapping
    # boundaries; semantic ownership must be unique.
    return matches[0]


def validate_non_overlapping_viewports(viewports: Sequence[SegmentedViewport]) -> bool:
    usable = [v for v in viewports if v.bounding_box is not None and v.status in (
        ViewportSegmentationStatus.RESOLVED.value,
        ViewportSegmentationStatus.DERIVED.value,
    )]
    for i, left in enumerate(usable):
        for right in usable[i + 1:]:
            overlap = _bbox_overlap_area(left.bounding_box, right.bounding_box)
            if overlap > 1e-6:
                # Touching boundaries have zero area and are valid.
                return False
    return True
