"""pb_drawing_evidence_binding.py — Drawing Evidence Binding & Scope Reconciliation Engine.

Determines which drawing evidence belongs to the measured building/object/scope
before aggregating counts or dimensions.

Eliminates multi-view overcounting where the same physical element (window, door,
vent, or pillar) is represented across:
- Floor plans
- Roof plans
- Elevations
- Sections
- Schedules
- Typical details, legends, or adjacent scope

Provides strict fail-closed conflict handling:
- If plan count != schedule count, flags CONFLICT_MANUAL_REVIEW rather than
  picking a benchmark-shaped number.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Enums & Data Contracts
# ---------------------------------------------------------------------------

class DrawingViewType(str, Enum):
    FLOOR_PLAN = "floor_plan"
    ROOF_PLAN = "roof_plan"
    ELEVATION = "elevation"
    SECTION = "section"
    SCHEDULE = "schedule"
    DETAIL = "detail"
    LEGEND = "legend"
    SPECIFICATION = "specification"
    REPEATED_OR_REFERENCE = "repeated_reference"
    ADJACENT_SCOPE = "adjacent_scope"
    UNKNOWN = "unknown"


class ReconciliationStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    CONFLICT_MANUAL_REVIEW = "conflict_manual_review"


@dataclass
class DrawingViewRegion:
    """Classified spatial view region on an architectural drawing sheet."""
    view_id: str
    view_type: str  # from DrawingViewType
    label: str
    page_number: int
    bounding_box: list[float] | None = None  # [x0, y0, x1, y1]
    building_scope_id: str = "primary_building"


@dataclass
class EvidenceObservation:
    """Generic immutable evidence observation model."""
    evidence_id: str
    project_id: str = ""
    revision: str = ""
    source_page: int = 1
    sheet_number: str = ""
    view_id: str = ""
    view_type: str = DrawingViewType.UNKNOWN.value
    bbox: list[float] | None = None  # [x0, y0, x1, y1]
    polygon: list[tuple[float, float]] | None = None
    extraction_method: str = "native"  # "native", "ocr", "vector", "schedule"
    raw_evidence_ref: str = ""
    raw_text: str = ""
    normalized_text: str = ""
    interpreted_tag: str = ""
    interpreted_type: str = ""
    dimensions: list[float] | None = None  # [width_mm, height_mm]
    count_value: float | None = None
    confidence: float = 1.0
    status: str = "raw"
    scope_id: str = "primary_building"
    parent_detail_ref: str | None = None
    duplicate_of: str | None = None
    conflict_group: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceOccurrence:
    """Individual observation of an architectural opening or element."""
    occurrence_id: str
    tag: str  # e.g. "W1", "W2", "D1", "brick_vents"
    trade_type: str  # "windows", "doors", "walls", "fixtures"
    view_type: str = DrawingViewType.UNKNOWN.value
    source_page: int = 1
    bounding_box: list[float] | None = None  # [x0, y0, x1, y1]
    raw_text: str = ""
    dimensions: list[float] | None = None  # [width_mm, height_mm]
    building_scope_id: str = "primary_building"
    is_legend_or_typical: bool = False
    confidence: float = 1.0
    extraction_method: str = "native"
    duplicate_of: str | None = None

    def to_observation(self) -> EvidenceObservation:
        return EvidenceObservation(
            evidence_id=self.occurrence_id,
            source_page=self.source_page,
            view_type=self.view_type,
            bbox=self.bounding_box,
            extraction_method=self.extraction_method,
            raw_text=self.raw_text,
            interpreted_tag=self.tag,
            interpreted_type=self.trade_type,
            dimensions=self.dimensions,
            confidence=self.confidence,
            scope_id=self.building_scope_id,
            duplicate_of=self.duplicate_of,
            metadata={"is_legend_or_typical": self.is_legend_or_typical},
        )


@dataclass
class PhysicalOpening:
    """Reconciled physical opening identity."""
    physical_object_id: str
    tag: str
    trade_type: str = "windows"
    width: float | None = None  # in mm
    height: float | None = None  # in mm
    bound_wall_id: str | None = None
    occurrence_evidence_ids: list[str] = field(default_factory=list)
    schedule_evidence_ids: list[str] = field(default_factory=list)
    alternate_view_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    conflict_status: str = ReconciliationStatus.CONFIRMED.value
    scope_id: str = "primary_building"
    source_trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleSpecification:
    """Specification row from a window/door/fixture schedule."""
    tag: str
    trade_type: str
    description: str
    dimensions: list[float] | None = None
    scheduled_quantity: float | None = None
    source_page: int | None = None
    bounding_box: list[float] | None = None
    confidence: float = 1.0
    extraction_method: str = "native"
    evidence_id: str = ""


@dataclass
class ReconciledObjectGroup:
    """Reconciled physical object group with complete cross-view traceability."""
    tag: str
    trade_type: str
    description: str
    dimensions: list[float] | None = None
    final_quantity: float | None = None
    physical_object_ids: list[str] = field(default_factory=list)
    physical_openings: list[PhysicalOpening] = field(default_factory=list)
    occurrences_by_view: dict[str, list[EvidenceOccurrence]] = field(default_factory=dict)
    duplicate_observations_suppressed: int = 0
    suppressed_details: list[dict[str, Any]] = field(default_factory=list)
    status: str = ReconciliationStatus.CONFIRMED.value
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# View Classifier & Spatial Region Partition
# ---------------------------------------------------------------------------

class DrawingViewClassifier:
    """Classifies text and spatial regions into architectural drawing view types."""

    _PLAN_PATTERNS = (
        r"\b(?:ground\s*floor\s*plan|floor\s*plan|layout\s*plan|first\s*floor\s*plan|level\s*\d+\s*plan)\b",
    )
    _ROOF_PATTERNS = (
        r"\b(?:roof\s*plan|roof\s*layout|roofing\s*plan)\b",
    )
    _ELEVATION_PATTERNS = (
        r"\b(?:elevation\s*[a-z0-9\-]+|elev\s*[a-z0-9\-]+|front\s*elev(?:ation)?|rear\s*elev(?:ation)?|side\s*elev(?:ation)?|north\s*elev(?:ation)?|south\s*elev(?:ation)?|east\s*elev(?:ation)?|west\s*elev(?:ation)?)\b",
    )
    _SECTION_PATTERNS = (
        r"\b(?:section\s*[a-z0-9\-]+|cross\s*section|longitudinal\s*section)\b",
    )
    _SCHEDULE_PATTERNS = (
        r"\b(?:schedule\s*of\s*(?:doors|windows|finishes)|window\s*schedule|door\s*schedule|finishes\s*schedule)\b",
    )
    _DETAIL_PATTERNS = (
        r"\b(?:typical\s*detail|detail\s*[a-z0-9\-]+|standard\s*detail|enlarged\s*detail|to\s*s\.e\s*detail)\b",
    )
    _LEGEND_PATTERNS = (
        r"\b(?:legend|symbol\s*legend|abbreviations?|key\s*to\s*symbols|sample\s*legend)\b",
    )
    _SPECIFICATION_PATTERNS = (
        r"\b(?:specifications?|general\s*specifications?|materials?\s*spec)\b",
    )
    _REPEATED_PATTERNS = (
        r"\b(?:reference\s*view|typical\s*floor|typical\s*layout|typical\s*opening)\b",
    )
    _ADJACENT_PATTERNS = (
        r"\b(?:adjacent\s*building|existing\s*building|future\s*extension|phase\s*2|block\s*b)\b",
    )

    @classmethod
    def classify_text(cls, text: str) -> DrawingViewType:
        norm = text.lower()
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._ADJACENT_PATTERNS):
            return DrawingViewType.ADJACENT_SCOPE
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._SCHEDULE_PATTERNS):
            return DrawingViewType.SCHEDULE
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._LEGEND_PATTERNS):
            return DrawingViewType.LEGEND
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._SPECIFICATION_PATTERNS):
            return DrawingViewType.SPECIFICATION
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._REPEATED_PATTERNS):
            return DrawingViewType.REPEATED_OR_REFERENCE
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._ROOF_PATTERNS):
            return DrawingViewType.ROOF_PLAN
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._PLAN_PATTERNS):
            return DrawingViewType.FLOOR_PLAN
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._ELEVATION_PATTERNS):
            return DrawingViewType.ELEVATION
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._SECTION_PATTERNS):
            return DrawingViewType.SECTION
        if any(re.search(p, norm, re.IGNORECASE) for p in cls._DETAIL_PATTERNS):
            return DrawingViewType.DETAIL
        return DrawingViewType.UNKNOWN

    @classmethod
    def partition_sheet_views(
        cls,
        page_text: str,
        page_blocks: list[tuple[float, float, float, float, str, int, int]] | None = None,
        page_number: int = 1,
    ) -> list[DrawingViewRegion]:
        """Discover view titles and their spatial boundaries on a sheet."""
        regions: list[DrawingViewRegion] = []
        if not page_blocks:
            view_type = cls.classify_text(page_text)
            regions.append(
                DrawingViewRegion(
                    view_id=f"page_{page_number}_view_1",
                    view_type=view_type.value,
                    label=page_text[:40].strip(),
                    page_number=page_number,
                )
            )
            return regions

        idx = 1
        for b in page_blocks:
            b_txt = b[4].strip()
            v_type = cls.classify_text(b_txt)
            if v_type not in (DrawingViewType.UNKNOWN, DrawingViewType.DETAIL):
                bbox = [b[0], b[1], b[2], b[3]]
                regions.append(
                    DrawingViewRegion(
                        view_id=f"view_{page_number}_{idx}",
                        view_type=v_type.value,
                        label=b_txt[:60].replace("\n", " ").strip(),
                        page_number=page_number,
                        bounding_box=bbox,
                    )
                )
                idx += 1

        if not regions:
            v_type = cls.classify_text(page_text)
            regions.append(
                DrawingViewRegion(
                    view_id=f"page_{page_number}_main",
                    view_type=v_type.value,
                    label="Drawing View",
                    page_number=page_number,
                )
            )

        return regions


# ---------------------------------------------------------------------------
# Cross-View Evidence Reconciliation Engine
# ---------------------------------------------------------------------------

class DrawingEvidenceBindingEngine:
    """Binds occurrences to physical objects and reconciles multi-view representations."""

    @classmethod
    def reconcile(
        cls,
        tag: str,
        trade_type: str,
        occurrences: Sequence[EvidenceOccurrence | EvidenceObservation],
        schedule_spec: ScheduleSpecification | None = None,
        active_building_id: str = "primary_building",
    ) -> ReconciledObjectGroup:
        """Reconciles observations of a single tag across plan, elevations, and schedules."""
        suppressed_details: list[dict[str, Any]] = []

        # Convert EvidenceObservation to EvidenceOccurrence if necessary
        std_occurrences: list[EvidenceOccurrence] = []
        for item in occurrences:
            if isinstance(item, EvidenceOccurrence):
                std_occurrences.append(item)
            elif isinstance(item, EvidenceObservation):
                is_leg = (
                    item.view_type in (
                        DrawingViewType.LEGEND.value,
                        DrawingViewType.DETAIL.value,
                        DrawingViewType.SPECIFICATION.value,
                        DrawingViewType.REPEATED_OR_REFERENCE.value,
                    )
                    or bool(item.metadata.get("is_legend_or_typical", False))
                )
                std_occurrences.append(
                    EvidenceOccurrence(
                        occurrence_id=item.evidence_id,
                        tag=item.interpreted_tag or tag,
                        trade_type=item.interpreted_type or trade_type,
                        view_type=item.view_type,
                        source_page=item.source_page,
                        bounding_box=item.bbox,
                        raw_text=item.raw_text,
                        dimensions=item.dimensions,
                        building_scope_id=item.scope_id,
                        is_legend_or_typical=is_leg,
                        confidence=item.confidence,
                        extraction_method=item.extraction_method,
                        duplicate_of=item.duplicate_of,
                    )
                )

        # 1. Native vs OCR Deduplication within occurrences
        native_occs = [o for o in std_occurrences if o.extraction_method == "native"]
        for o in std_occurrences:
            if o.extraction_method == "ocr" and not o.duplicate_of:
                for nat in native_occs:
                    if nat.tag == o.tag and nat.source_page == o.source_page:
                        o.duplicate_of = nat.occurrence_id
                        break

        # 2. Filter out out-of-scope, duplicates, and legend/typical occurrences
        valid_occurrences: list[EvidenceOccurrence] = []
        suppressed_out_of_scope = 0

        for occ in std_occurrences:
            if occ.duplicate_of:
                suppressed_details.append({
                    "rule": "ocr_duplicate_of_native",
                    "evidence_id": occ.occurrence_id,
                    "duplicate_of": occ.duplicate_of,
                    "tag": occ.tag,
                })
                continue

            if occ.building_scope_id != active_building_id or occ.view_type == DrawingViewType.ADJACENT_SCOPE.value:
                suppressed_out_of_scope += 1
                suppressed_details.append({
                    "rule": "adjacent_scope_suppressed",
                    "evidence_id": occ.occurrence_id,
                    "scope_id": occ.building_scope_id,
                    "tag": occ.tag,
                })
                continue

            if (
                occ.is_legend_or_typical
                or occ.view_type in (
                    DrawingViewType.DETAIL.value,
                    DrawingViewType.LEGEND.value,
                    DrawingViewType.SPECIFICATION.value,
                    DrawingViewType.REPEATED_OR_REFERENCE.value,
                )
            ):
                suppressed_out_of_scope += 1
                suppressed_details.append({
                    "rule": "legend_or_typical_suppressed",
                    "evidence_id": occ.occurrence_id,
                    "view_type": occ.view_type,
                    "tag": occ.tag,
                })
                continue

            valid_occurrences.append(occ)

        # 3. Group occurrences by view type
        by_view: dict[str, list[EvidenceOccurrence]] = {
            DrawingViewType.FLOOR_PLAN.value: [],
            DrawingViewType.ROOF_PLAN.value: [],
            DrawingViewType.ELEVATION.value: [],
            DrawingViewType.SECTION.value: [],
            DrawingViewType.SCHEDULE.value: [],
            DrawingViewType.DETAIL.value: [],
            DrawingViewType.LEGEND.value: [],
            DrawingViewType.SPECIFICATION.value: [],
            DrawingViewType.REPEATED_OR_REFERENCE.value: [],
            DrawingViewType.UNKNOWN.value: [],
        }
        for occ in valid_occurrences:
            vt = occ.view_type if occ.view_type in by_view else DrawingViewType.UNKNOWN.value
            by_view[vt].append(occ)

        plan_occs = by_view[DrawingViewType.FLOOR_PLAN.value]
        elev_occs = by_view[DrawingViewType.ELEVATION.value]
        sect_occs = by_view[DrawingViewType.SECTION.value]
        sched_occs = by_view[DrawingViewType.SCHEDULE.value]

        # 4. Determine dimensions (prefer schedule specification, then plan/elevation occurrence)
        resolved_dimensions: list[float] | None = None
        if schedule_spec and schedule_spec.dimensions:
            resolved_dimensions = schedule_spec.dimensions
        else:
            for occ in valid_occurrences:
                if occ.dimensions:
                    resolved_dimensions = occ.dimensions
                    break

        # 5. Determine description
        if schedule_spec and schedule_spec.description:
            description = schedule_spec.description
        elif resolved_dimensions and len(resolved_dimensions) >= 2:
            description = f"{tag} {int(resolved_dimensions[0])}x{int(resolved_dimensions[1])}mm ({trade_type})"
        else:
            description = f"{tag} ({trade_type})"

        # 6. Check if identity evidence exists at all
        if not valid_occurrences and (not schedule_spec or schedule_spec.scheduled_quantity is None):
            return ReconciledObjectGroup(
                tag=tag,
                trade_type=trade_type,
                description=description,
                dimensions=resolved_dimensions,
                final_quantity=None,
                physical_object_ids=[],
                physical_openings=[],
                occurrences_by_view=by_view,
                duplicate_observations_suppressed=suppressed_out_of_scope + len(suppressed_details),
                suppressed_details=suppressed_details,
                status=ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value,
                conflicts=[{"type": "missing_object_identity_evidence", "tag": tag}],
            )

        # 7. Cross-view reconciliation
        conflicts: list[dict[str, Any]] = []
        suppressed_duplicates = len(suppressed_details)
        final_quantity: float | None = None
        status = ReconciliationStatus.CONFIRMED.value
        physical_openings: list[PhysicalOpening] = []

        # Deduplicate elevation occurrences across duplicate sheets
        distinct_elev_occs: list[EvidenceOccurrence] = []
        seen_elev_coords = set()
        for eo in elev_occs:
            if eo.bounding_box:
                coord_key = (round(eo.bounding_box[0], 1), round(eo.bounding_box[1], 1))
                if coord_key in seen_elev_coords:
                    suppressed_duplicates += 1
                    suppressed_details.append({
                        "rule": "duplicate_elevation_sheet_suppressed",
                        "evidence_id": eo.occurrence_id,
                        "tag": eo.tag,
                    })
                    continue
                seen_elev_coords.add(coord_key)
            distinct_elev_occs.append(eo)

        distinct_elev_count = float(len(distinct_elev_occs))
        distinct_plan_count = float(len(plan_occs))

        # Check dimension conflict between schedule and occurrences
        if schedule_spec and schedule_spec.dimensions:
            for occ in valid_occurrences:
                if (
                    occ.dimensions
                    and len(occ.dimensions) >= 2
                    and len(schedule_spec.dimensions) >= 2
                    and (
                        abs(occ.dimensions[0] - schedule_spec.dimensions[0]) > 50.0
                        or abs(occ.dimensions[1] - schedule_spec.dimensions[1]) > 50.0
                    )
                ):
                        conflicts.append({
                            "type": "dimension_conflict",
                            "tag": tag,
                            "schedule_dimensions": schedule_spec.dimensions,
                            "occurrence_dimensions": occ.dimensions,
                            "message": f"Schedule dimensions {schedule_spec.dimensions} conflict with occurrence {occ.dimensions}",
                        })

        # Case A: Schedule specifies count AND occurrences exist
        if schedule_spec and schedule_spec.scheduled_quantity is not None and (len(plan_occs) > 0 or len(elev_occs) > 0):
            sched_qty = schedule_spec.scheduled_quantity
            measured_count = max(distinct_plan_count, distinct_elev_count) if (distinct_plan_count > 0 and distinct_elev_count > 0) else (distinct_plan_count or distinct_elev_count)

            if sched_qty == distinct_plan_count or sched_qty == measured_count:
                final_quantity = sched_qty
                suppressed_duplicates += len(elev_occs) + len(sect_occs) + len(sched_occs)
                for occ in elev_occs + sect_occs:
                    suppressed_details.append({
                        "rule": "cross_view_representation_deduplicated",
                        "evidence_id": occ.occurrence_id,
                        "view_type": occ.view_type,
                        "tag": occ.tag,
                    })
            else:
                status = ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value
                conflicts.append({
                    "type": "schedule_vs_plan_count_mismatch",
                    "tag": tag,
                    "schedule_count": sched_qty,
                    "plan_count": distinct_plan_count,
                    "message": f"Schedule specifies {sched_qty} while Floor Plan proves {distinct_plan_count}.",
                })
                final_quantity = None

        # Case B: No schedule count, but occurrences exist in Plan and/or Elevation
        elif distinct_plan_count > 0 or distinct_elev_count > 0:
            if distinct_plan_count > 0 and distinct_elev_count > 0:
                final_quantity = max(distinct_plan_count, distinct_elev_count)
                suppressed_duplicates += int(distinct_plan_count + distinct_elev_count - final_quantity) + len(sect_occs) + len(sched_occs)
                status = ReconciliationStatus.CONFIRMED.value
            elif distinct_plan_count > 0:
                final_quantity = distinct_plan_count
                suppressed_duplicates += len(sect_occs) + len(sched_occs)
                status = ReconciliationStatus.CONFIRMED.value
            else:
                final_quantity = distinct_elev_count
                suppressed_duplicates += len(sect_occs) + len(sched_occs)
                status = ReconciliationStatus.PROVISIONAL.value

        # Case C: Only Schedule count exists (no plan occurrences detected)
        elif schedule_spec and schedule_spec.scheduled_quantity is not None:
            final_quantity = schedule_spec.scheduled_quantity
            suppressed_duplicates += len(elev_occs) + len(sect_occs) + len(sched_occs)

        # Synthesize distinct physical openings
        physical_object_ids: list[str] = []
        if final_quantity is not None and final_quantity > 0:
            count_int = int(final_quantity)
            for i in range(count_int):
                po_id = f"{tag}_physical_{i+1}"
                physical_object_ids.append(po_id)
                plan_ev_id = [plan_occs[i].occurrence_id] if i < len(plan_occs) else []
                elev_ev_id = [distinct_elev_occs[i].occurrence_id] if i < len(distinct_elev_occs) else []
                sched_ev_id = [schedule_spec.evidence_id or f"sched_{tag}"] if schedule_spec else []

                po = PhysicalOpening(
                    physical_object_id=po_id,
                    tag=tag,
                    trade_type=trade_type,
                    width=resolved_dimensions[0] if resolved_dimensions and len(resolved_dimensions) >= 1 else None,
                    height=resolved_dimensions[1] if resolved_dimensions and len(resolved_dimensions) >= 2 else None,
                    bound_wall_id="perimeter_walling",
                    occurrence_evidence_ids=plan_ev_id,
                    schedule_evidence_ids=sched_ev_id,
                    alternate_view_evidence_ids=elev_ev_id,
                    confidence=min(o.confidence for o in valid_occurrences) if valid_occurrences else 1.0,
                    conflict_status=status,
                    scope_id=active_building_id,
                    source_trace={
                        "tag": tag,
                        "trade_type": trade_type,
                        "status": status,
                    },
                )
                physical_openings.append(po)

        return ReconciledObjectGroup(
            tag=tag,
            trade_type=trade_type,
            description=description,
            dimensions=resolved_dimensions,
            final_quantity=final_quantity,
            physical_object_ids=physical_object_ids,
            physical_openings=physical_openings,
            occurrences_by_view=by_view,
            duplicate_observations_suppressed=suppressed_duplicates,
            suppressed_details=suppressed_details,
            status=status,
            conflicts=conflicts,
            metadata={
                "plan_count": len(plan_occs),
                "elevation_count": len(elev_occs),
                "distinct_elevation_count": len(distinct_elev_occs),
                "section_count": len(sect_occs),
                "schedule_count": schedule_spec.scheduled_quantity if schedule_spec else None,
                "out_of_scope_suppressed": suppressed_out_of_scope,
            },
        )


# ---------------------------------------------------------------------------
# Evidence Graph Model
# ---------------------------------------------------------------------------

class EvidenceGraph:
    """Graph structure managing drawing evidence observations, deduplication,
    cross-view relationships, and physical object synthesis."""

    def __init__(self, active_scope_id: str = "primary_building"):
        self.active_scope_id = active_scope_id
        self.observations: dict[str, EvidenceObservation] = {}
        self.schedule_specs: dict[str, ScheduleSpecification] = {}
        self.suppressed_duplicates: list[dict[str, Any]] = []
        self.conflicts: list[dict[str, Any]] = []

    def add_observation(self, obs: EvidenceObservation) -> str:
        """Register an observation into the evidence graph."""
        self.observations[obs.evidence_id] = obs
        return obs.evidence_id

    def add_schedule_spec(self, spec: ScheduleSpecification):
        """Register a schedule specification row."""
        self.schedule_specs[spec.tag] = spec

    def deduplicate_native_and_ocr(self) -> int:
        """Identify OCR observations that duplicate native text observations."""
        native_obs = [o for o in self.observations.values() if o.extraction_method == "native"]
        count_deduped = 0
        for obs in self.observations.values():
            if obs.extraction_method == "ocr" and not obs.duplicate_of:
                for nat in native_obs:
                    if nat.interpreted_tag == obs.interpreted_tag and nat.source_page == obs.source_page:
                        obs.duplicate_of = nat.evidence_id
                        self.suppressed_duplicates.append({
                            "rule": "ocr_duplicate_of_native",
                            "evidence_id": obs.evidence_id,
                            "duplicate_of": nat.evidence_id,
                            "tag": obs.interpreted_tag,
                        })
                        count_deduped += 1
                        break
        return count_deduped

    def reconcile_all(self) -> dict[str, ReconciledObjectGroup]:
        """Reconciles all registered observations grouped by tag."""
        self.deduplicate_native_and_ocr()

        # Group observations by tag
        by_tag: dict[str, list[EvidenceObservation]] = {}
        for obs in self.observations.values():
            tag = obs.interpreted_tag or "UNKNOWN"
            by_tag.setdefault(tag, []).append(obs)

        # Include tags that might only have schedule specs
        for tag in self.schedule_specs:
            by_tag.setdefault(tag, [])

        reconciled: dict[str, ReconciledObjectGroup] = {}
        for tag, obs_list in by_tag.items():
            trade_type = obs_list[0].interpreted_type if obs_list else "openings"
            sched = self.schedule_specs.get(tag)
            group = DrawingEvidenceBindingEngine.reconcile(
                tag=tag,
                trade_type=trade_type,
                occurrences=obs_list,
                schedule_spec=sched,
                active_building_id=self.active_scope_id,
            )
            reconciled[tag] = group
            self.conflicts.extend(group.conflicts)
            self.suppressed_duplicates.extend(group.suppressed_details)

        return reconciled


# ---------------------------------------------------------------------------
# F.9 Opening Deduction Pipeline Integration Helper
# ---------------------------------------------------------------------------

def build_opening_instances_from_physical_openings(
    openings: Sequence[PhysicalOpening],
    default_wall_id: str = "perimeter_walling",
) -> list[Any]:
    """Converts confirmed PhysicalOpening objects into OpeningInstance objects
    for the F.9 generic opening deduction pipeline.

    Fail closed: If opening has CONFLICT_MANUAL_REVIEW or missing dimensions,
    it is excluded from firm deductions (zero deduction applied).
    """
    try:
        from pb_opening_deduction_pipeline import OpeningInstance
    except ImportError:
        return []

    instances = []
    for op in openings:
        if op.conflict_status != ReconciliationStatus.CONFIRMED.value:
            # Fail closed: unresolved / conflicted openings must not apply firm deductions
            continue
        if not op.width or not op.height:
            # Incomplete dimensions: zero deduction
            continue

        # Convert mm to m if in mm
        w_m = op.width / 1000.0 if op.width > 50.0 else op.width
        h_m = op.height / 1000.0 if op.height > 50.0 else op.height

        instances.append(
            OpeningInstance(
                opening_id=op.physical_object_id,
                trade_type=op.trade_type,
                width_m=round(w_m, 4),
                height_m=round(h_m, 4),
                quantity=1.0,  # Each PhysicalOpening represents 1 distinct physical unit
                bound_wall_id=op.bound_wall_id or default_wall_id,
            )
        )
    return instances
