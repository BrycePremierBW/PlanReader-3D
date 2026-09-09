"""Viewport-scoped figured-dimension evidence binding (F.07 -> F.13 bridge).

F.13 can read and bind figured dimensions, but page-wide binding cannot safely
answer which view owns a vertical or mixed-scale dimension on a multi-viewport
sheet. F.07 supplies that missing spatial ownership.

This bridge scopes *raw* native words, vector segments, and OCR candidates to a
viewport before F.13 performs anchor binding. That ordering is intentional: a
line from a neighbouring elevation must never make a plan dimension ambiguous,
and an elevation dimension must never enter a plan chain merely because both
occur on the same PDF page.

Authority defaults are conservative. Only ``RESOLVED`` (vector-frame-backed)
viewports are consumed unless ``allow_derived=True`` is explicitly requested.
For authority-sensitive ownership, text bboxes must be fully contained and
vector segments must have both endpoints inside the viewport; midpoint-only
ownership is deliberately rejected for boundary-crossing evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from pb_dimension_graph_constraint_engine import DimensionObservation
from pb_figured_dimension_evidence import (
    DimensionAnchorBinding,
    DimensionEvidenceBundle,
    ObservedGeometrySegment,
    apply_anchor_binding,
    bind_observation_to_vector_geometry,
    build_chains_from_bound_observations,
    calibrate_dimension_layout,
    extract_native_dimension_observations,
    extract_vector_segments,
)
from pb_viewport_segmentation import SegmentedViewport, ViewportSegmentationStatus


@dataclass
class ViewportDimensionBindingResult:
    bundles: dict[str, DimensionEvidenceBundle] = field(default_factory=dict)
    skipped_viewports: dict[str, str] = field(default_factory=dict)
    unassigned_ocr_ids: list[str] = field(default_factory=list)


def _bbox_fully_inside(inner: Sequence[float], outer: Sequence[float]) -> bool:
    return (
        float(inner[0]) >= float(outer[0])
        and float(inner[1]) >= float(outer[1])
        and float(inner[2]) <= float(outer[2])
        and float(inner[3]) <= float(outer[3])
    )


def _point_in_bbox(point: tuple[float, float], bbox: Sequence[float]) -> bool:
    return float(bbox[0]) <= point[0] <= float(bbox[2]) and float(bbox[1]) <= point[1] <= float(bbox[3])


def _observation_in_viewport(observation: DimensionObservation, bbox: Sequence[float]) -> bool:
    return observation.bbox is not None and _bbox_fully_inside(observation.bbox, bbox)


def _segment_in_viewport(segment: ObservedGeometrySegment, bbox: Sequence[float]) -> bool:
    return _point_in_bbox(segment.start, bbox) and _point_in_bbox(segment.end, bbox)


def _eligible(viewport: SegmentedViewport, *, allow_derived: bool) -> bool:
    if viewport.bounding_box is None:
        return False
    if viewport.status == ViewportSegmentationStatus.RESOLVED.value:
        return True
    return allow_derived and viewport.status == ViewportSegmentationStatus.DERIVED.value


def extract_dimension_evidence_by_viewport(
    page: Any,
    *,
    page_num: int,
    viewports: Sequence[SegmentedViewport],
    sheet: str = "",
    ocr_candidates: Iterable[DimensionObservation] = (),
    allow_derived: bool = False,
) -> ViewportDimensionBindingResult:
    """Build independent F.13 evidence bundles for uniquely owned viewports."""
    result = ViewportDimensionBindingResult()
    layout = calibrate_dimension_layout(page)
    ocr_candidates = list(ocr_candidates)
    assigned_ocr: set[str] = set()

    for viewport in viewports:
        if not _eligible(viewport, allow_derived=allow_derived):
            result.skipped_viewports[viewport.view_id] = (
                f"viewport status={viewport.status!r} does not provide permitted spatial authority"
            )
            continue
        assert viewport.bounding_box is not None
        bbox = viewport.bounding_box

        # Extract with the owning view ID first, then spatially filter before
        # any anchor association takes place.
        segments = [
            segment
            for segment in extract_vector_segments(page, page_num=page_num, view_id=viewport.view_id)
            if _segment_in_viewport(segment, bbox)
        ]
        native = [
            observation
            for observation in extract_native_dimension_observations(
                page,
                page_num=page_num,
                sheet=sheet,
                view_id=viewport.view_id,
                view_type=viewport.view_type,
            )
            if _observation_in_viewport(observation, bbox)
        ]

        bindings: list[DimensionAnchorBinding] = []
        bound_native: list[DimensionObservation] = []
        for observation in native:
            binding = bind_observation_to_vector_geometry(observation, segments, layout)
            bindings.append(binding)
            bound_native.append(apply_anchor_binding(observation, binding))

        scoped_ocr: list[DimensionObservation] = []
        for candidate in ocr_candidates:
            if candidate.bbox is None or not _observation_in_viewport(candidate, bbox):
                continue
            # Overlap safety: an OCR candidate may only be assigned when this
            # viewport is the unique eligible owner of its complete bbox.
            owners = [
                other
                for other in viewports
                if _eligible(other, allow_derived=allow_derived)
                and other.bounding_box is not None
                and _bbox_fully_inside(candidate.bbox, other.bounding_box)
            ]
            if len(owners) != 1 or owners[0].view_id != viewport.view_id:
                continue
            scoped_ocr.append(
                replace(
                    candidate,
                    view_id=viewport.view_id,
                    view_type=viewport.view_type,
                    sheet=sheet or candidate.sheet,
                )
            )
            assigned_ocr.add(candidate.dimension_id)

        chains = build_chains_from_bound_observations(bound_native, calibration=layout)
        result.bundles[viewport.view_id] = DimensionEvidenceBundle(
            observations=bound_native + scoped_ocr,
            observed_geometry=segments,
            bindings=bindings,
            chains=chains,
        )

    result.unassigned_ocr_ids = [
        candidate.dimension_id for candidate in ocr_candidates if candidate.dimension_id not in assigned_ocr
    ]
    return result
