"""Gold-free shadow quantity provider for door/window schedule counts.

SOURCE PDF
    → GenericScheduleTableExtractor + explicit tag observations
    → F.07 viewports / DrawingViewClassifier
    → F.12 DrawingEvidenceBindingEngine
    → EntityEvidence + optional type-level CanonicalOpening
    → QuantityEvidence (shadow only)

This provider does not read expected BOQ files, benchmark IDs, mappings, or
tolerances.  It does not change GenericPlanReaderExtractor.  It does not switch
family authority away from legacy.  It does not project commercial takeoff rows.

OPENING TYPE COUNT is not VERIFIED PHYSICAL INSTANCE reconstruction.
A schedule row ``W1 Qty 6`` may justify a type-count QuantityEvidence of 6.
It does not create six spatially reconstructed openings.
Dimension-only geometry never becomes a W/D identity.
Ambiguous ``WD`` marks abstain unless F.28 already resolved window semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence

import fitz

from pb_canonical_building import CanonicalOpening, ObjectType, Provenance, ReviewState
from pb_drawing_evidence_binding import (
    DrawingViewClassifier,
    DrawingViewType,
    EvidenceGraph,
    EvidenceOccurrence,
    ReconciliationStatus,
    ScheduleSpecification,
)
from pb_drawing_ocr_evidence_layer import DrawingEvidenceParser, EvidenceMethod
from pb_migration_contracts import (
    EntityEvidence,
    EvidenceResolutionStatus,
    QuantityEvidence,
    stable_contract_id,
)
from pb_opening_tag_normalization import (
    NormalizedOpeningTag,
    find_explicit_opening_tags,
    normalize_opening_tag,
)
from pb_raster_schedule_extractor import GenericScheduleTableExtractor, ScheduleRow
from pb_shadow_opening_count_gate import OPENING_COUNT_FAMILIES
from pb_shadow_opening_evidence import (
    assess_opening_schedule_authority,
    derive_family_totals,
    group_ocr_tokens_into_lines,
    is_ambiguous_ocr_mark,
    is_work_section_or_nrm_code,
    make_shadow_ocr_engine,
    native_tag_context_allowed,
    nearby_word_text,
    ocr_mark_is_usable,
    page_is_opening_schedule_sheet,
    page_looks_like_bill_or_nrm,
    iter_complete_opening_schedule_rows,
    schedule_line_is_authoritative,
    viewport_is_opening_schedule_candidate,
)
from pb_viewport_segmentation import assign_bbox_to_viewport, segment_page_viewports


PROVIDER_ENGINE_ID = "shadow_opening_count"
PROVIDER_ENGINE_VERSION = "1.1.0"
FORMULA_VERSION = "1.0.0"
RASTER_OCR_DPI = 150

_DETAIL_OR_LEGEND = {
    DrawingViewType.DETAIL.value,
    DrawingViewType.LEGEND.value,
    DrawingViewType.SPECIFICATION.value,
    DrawingViewType.REPEATED_OR_REFERENCE.value,
}

_F28_WD_TAG_RE = re.compile(r"^WD\s*[-_]?\s*0*(?P<number>\d{1,3})$", re.IGNORECASE)
_WD_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])WD(?:\s*[-_]?\s*0*(?P<number>\d{1,3}))?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_OPENING_PAGE_PROBE_RE = re.compile(
    r"(?is)(?:window\s+schedule|door\s+schedule|schedule\s+of\s+(?:doors|windows)|"
    r"overall\s+quantity|ground\s+floor\s+plan|floor\s+plan|"
    r"(?<![A-Za-z0-9])(?:WINDOW|WIN|W|DOOR|DR|D|WD)\s*[-_]?\s*\d{1,3}(?![A-Za-z0-9]))"
)
_SCHEDULE_TITLE_RE = re.compile(
    r"(?i)(?:window\s+schedule|door\s+schedule|schedule\s+of\s+(?:doors|windows))"
)
_BILL_PAGE_RE = re.compile(
    r"(?is)(?:\bbills?\s+of\s+quantities\b|"
    r"\bbuilder'?s\s+work\b|"
    r"\bitem\b.{0,160}\bdescription\b.{0,160}\b(?:qty|quantity)\b.{0,80}\bunit\b.{0,80}\brate\b|"
    r"\bitem\b.{0,160}\bdescription\b.{0,160}\bunit\b.{0,160}\b(?:qty|quantity)\b.{0,80}\brate\b|"
    r"\bref\.\s*.{0,80}\bdescription\b.{0,80}\bquantity\b.{0,80}\bunit\b.{0,80}\brate\b|"
    r"\bparticular\s+preliminaries\b|"
    r"\bpricing\s+preamble\b|"
    r"\b[a-z]\d{2}\s+excavating\b)"
)
_NON_OPENING_CONTEXT_RE = re.compile(
    r"(?i)(?:excavating\s+and\s+filling|in\s+situ\s+concrete|site\s+preparation|"
    r"mechanical\s+works|hardcore)"
)


def _family_for_trade(trade_type: str) -> str:
    if trade_type == "windows":
        return "window_count"
    if trade_type == "doors":
        return "door_count"
    return "opening_count"


def _round_bbox(bbox: Sequence[float] | None) -> tuple[float, ...]:
    if not bbox or len(bbox) < 4:
        return ()
    values = tuple(round(float(v), 1) for v in bbox[:4])
    if values == (0.0, 0.0, 0.0, 0.0):
        return ()
    return values


def _bbox_near(
    left: Sequence[float],
    right: Sequence[float],
    *,
    tol: float = 24.0,
) -> bool:
    if len(left) < 4 or len(right) < 4:
        return False
    return (
        abs(float(left[0]) - float(right[0])) <= tol
        and abs(float(left[1]) - float(right[1])) <= tol
    )


def page_is_bill_of_quantities(text: str) -> bool:
    """Bill/BOQ pages are not drawing or opening-schedule evidence."""
    return bool(_BILL_PAGE_RE.search(text or ""))


def page_has_opening_evidence(text: str) -> bool:
    """Cheap gold-free probe: skip pages with no opening-like drawing text."""
    raw = text or ""
    if page_is_bill_of_quantities(raw):
        return False
    return bool(_OPENING_PAGE_PROBE_RE.search(raw))


def probe_opening_evidence_pages(doc: fitz.Document, pages: Optional[Sequence[int]] = None) -> list[int]:
    """Return 0-based page indexes that contain opening-like drawing evidence."""
    target = list(pages) if pages is not None else list(range(len(doc)))
    found: list[int] = []
    for pno in target:
        if pno < 0 or pno >= len(doc):
            continue
        if page_has_opening_evidence(doc[pno].get_text("text") or ""):
            found.append(pno)
    return found


def resolve_opening_identity(
    tag: str,
    *,
    evidence_text: str = "",
    trade_type: str = "",
) -> Optional[NormalizedOpeningTag]:
    """Normalize an explicit W/D mark. Accept F.28 WD{n} only when already window-resolved."""
    context = f"{tag or ''} {evidence_text or ''}"
    if _NON_OPENING_CONTEXT_RE.search(context):
        return None
    if is_work_section_or_nrm_code(tag, evidence_text):
        return None
    if is_ambiguous_ocr_mark(tag):
        return None
    norm = normalize_opening_tag(tag)
    if norm is not None:
        return norm
    match = _F28_WD_TAG_RE.fullmatch((tag or "").strip())
    if match is None:
        return None
    number = int(match.group("number"))
    if number <= 0:
        return None
    evidence = f"{evidence_text or ''} {trade_type or ''}".lower()
    if "window fields" in evidence or trade_type == "windows":
        return NormalizedOpeningTag(
            tag=f"WD{number}",
            trade_type="windows",
            raw_text=tag,
        )
    return None


def _classify_page_view(
    page: fitz.Page,
    page_number: int,
    bbox: Sequence[float] | None,
    viewports: Sequence[Any],
) -> tuple[str, str]:
    if bbox and len(bbox) >= 4 and _round_bbox(bbox):
        owned = assign_bbox_to_viewport(bbox, viewports)
        if owned is not None:
            return owned.view_type, owned.view_id
    page_type = DrawingViewClassifier.classify_text(page.get_text("text") or "")
    return page_type.value, f"page_{page_number}_main"


def _is_schedule_type_row(row: ScheduleRow, view_type: str) -> bool:
    """Type-count rows are schedule/card totals, not a single plan callout."""
    evidence = f"{row.evidence_text or ''} {row.description or ''}".lower()
    if "overall quantity" in evidence:
        return True
    if view_type == DrawingViewType.SCHEDULE.value:
        if row.quantity is not None and row.quantity >= 2:
            return True
        if row.dimensions is not None:
            return True
        return False
    return row.quantity is not None and row.quantity >= 2


def _specs_conflict(existing: ScheduleSpecification, quantity: Optional[float], dimensions: Optional[Sequence[float]]) -> bool:
    if existing.scheduled_quantity is not None and quantity is not None:
        if abs(float(existing.scheduled_quantity) - float(quantity)) > 1e-9:
            return True
    if existing.dimensions and dimensions and len(existing.dimensions) >= 2 and len(dimensions) >= 2:
        if (
            abs(float(existing.dimensions[0]) - float(dimensions[0])) > 50
            or abs(float(existing.dimensions[1]) - float(dimensions[1])) > 50
        ):
            return True
    return False


@dataclass
class OpeningCountBundle:
    """Shadow artifacts for one source. Not commercially authoritative."""

    quantities: tuple[QuantityEvidence, ...]
    entity_evidence: tuple[EntityEvidence, ...]
    canonical_openings: tuple[CanonicalOpening, ...]
    conflicts: tuple[dict[str, Any], ...]
    ambiguous_marks: tuple[str, ...]
    duplicate_observations: int
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantities": [item.to_dict() for item in self.quantities],
            "entity_evidence": [item.to_dict() for item in self.entity_evidence],
            "canonical_openings": [item.to_dict() for item in self.canonical_openings],
            "conflicts": list(self.conflicts),
            "ambiguous_marks": list(self.ambiguous_marks),
            "duplicate_observations": self.duplicate_observations,
            "diagnostics": dict(self.diagnostics),
        }


class ShadowOpeningCountProvider:
    """ShadowQuantityEngine for door/window type counts."""

    engine_id = PROVIDER_ENGINE_ID
    engine_version = PROVIDER_ENGINE_VERSION

    def __init__(
        self,
        *,
        ocr_lines_by_page: Optional[Mapping[int, Sequence[Mapping[str, Any]]]] = None,
        enable_raster_ocr: bool = True,
        raster_ocr_dpi: int = RASTER_OCR_DPI,
    ) -> None:
        self._ocr_lines_by_page = {
            int(page): tuple(lines) for page, lines in (ocr_lines_by_page or {}).items()
        }
        self._enable_raster_ocr = bool(enable_raster_ocr)
        self._raster_ocr_dpi = int(raster_ocr_dpi)
        self._ocr_engine: Any = None

    def extract_quantities(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> tuple[QuantityEvidence, ...]:
        return self.extract_bundle(pdf_path, pages=pages).quantities

    def extract_bundle(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> OpeningCountBundle:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found at: {path}")
        doc = fitz.open(path)
        try:
            return self._extract_open_document(doc, path=path, pages=pages)
        finally:
            doc.close()

    def _extract_open_document(
        self,
        doc: fitz.Document,
        *,
        path: Path,
        pages: Optional[Sequence[int]],
    ) -> OpeningCountBundle:
        requested = list(pages) if pages is not None else list(range(len(doc)))
        target = probe_opening_evidence_pages(doc, requested)
        if self._ocr_lines_by_page:
            for page_number in self._ocr_lines_by_page:
                pno = int(page_number) - 1
                if pno in requested and pno not in target:
                    target.append(pno)
            target.sort()

        extractor = GenericScheduleTableExtractor()
        graph = EvidenceGraph()
        schedule_conflicts: list[dict[str, Any]] = []
        ambiguous: list[str] = []
        seen_physical: set[tuple[str, int, tuple[float, ...]]] = set()
        duplicate_holder = [0]
        schedule_bboxes: set[tuple[int, tuple[float, ...]]] = set()
        viewport_ids_by_tag: dict[str, str] = {}
        raster_pages: list[int] = []
        raster_rejected: list[str] = []

        viewports_by_page: dict[int, list[Any]] = {}
        for pno in target:
            page = doc[pno]
            page_number = pno + 1
            viewports_by_page[page_number] = segment_page_viewports(page, page_number=page_number)

        raw_rows: list[ScheduleRow] = []
        for pno in target:
            raw_rows.extend(extractor.extract_from_page(doc[pno], pno + 1))

        for row in raw_rows:
            norm = resolve_opening_identity(
                row.tag,
                evidence_text=row.evidence_text or row.description,
                trade_type=row.trade_type,
            )
            if norm is None:
                continue
            viewports = viewports_by_page.get(row.source_page, [])
            page = doc[row.source_page - 1]
            view_type, view_id = _classify_page_view(page, row.source_page, row.bbox, viewports)
            bbox = list(row.bbox) if row.bbox and _round_bbox(row.bbox) else None
            evidence_id = stable_contract_id(
                "ev",
                {
                    "kind": "schedule_row",
                    "tag": norm.tag,
                    "page": row.source_page,
                    "bbox": _round_bbox(row.bbox),
                    "qty": row.quantity,
                    "dims": row.dimensions,
                },
            )
            if _is_schedule_type_row(row, view_type):
                existing = graph.schedule_specs.get(norm.tag)
                if existing is not None:
                    if _specs_conflict(existing, row.quantity, row.dimensions):
                        schedule_conflicts.append(
                            {
                                "type": "duplicate_schedule_conflict",
                                "tag": norm.tag,
                                "first": existing.scheduled_quantity,
                                "second": row.quantity,
                            }
                        )
                        continue
                    if existing.scheduled_quantity is not None and row.quantity is None:
                        duplicate_holder[0] += 1
                        continue
                    if (
                        existing.scheduled_quantity == row.quantity
                        and (existing.dimensions == row.dimensions or not row.dimensions or not existing.dimensions)
                    ):
                        duplicate_holder[0] += 1
                        continue
                graph.add_schedule_spec(
                    ScheduleSpecification(
                        tag=norm.tag,
                        trade_type=norm.trade_type,
                        description=row.description,
                        dimensions=list(row.dimensions) if row.dimensions else None,
                        scheduled_quantity=float(row.quantity) if row.quantity is not None else None,
                        source_page=row.source_page,
                        bounding_box=bbox,
                        confidence=row.confidence,
                        extraction_method="schedule",
                        evidence_id=evidence_id,
                    )
                )
                graph.add_observation(
                    EvidenceOccurrence(
                        occurrence_id=evidence_id,
                        tag=norm.tag,
                        trade_type=norm.trade_type,
                        view_type=DrawingViewType.SCHEDULE.value,
                        source_page=row.source_page,
                        bounding_box=bbox,
                        raw_text=row.evidence_text or row.description,
                        dimensions=list(row.dimensions) if row.dimensions else None,
                        confidence=row.confidence,
                        extraction_method="schedule",
                    ).to_observation()
                )
                if _round_bbox(row.bbox):
                    schedule_bboxes.add((row.source_page, _round_bbox(row.bbox)))
                if view_id:
                    viewport_ids_by_tag.setdefault(norm.tag, view_id)
            elif view_type == DrawingViewType.FLOOR_PLAN.value and (row.quantity is None or row.quantity == 1):
                self._add_physical_observation(
                    graph=graph,
                    seen_physical=seen_physical,
                    duplicate_holder=duplicate_holder,
                    tag=norm.tag,
                    trade_type=norm.trade_type,
                    page_number=row.source_page,
                    bbox=bbox,
                    text=row.evidence_text or row.description,
                    dimensions=list(row.dimensions) if row.dimensions else None,
                    view_type=DrawingViewType.FLOOR_PLAN.value,
                    method="native",
                    confidence=row.confidence,
                )

        for pno in target:
            page = doc[pno]
            page_number = pno + 1
            viewports = viewports_by_page.get(page_number, [])
            self._ingest_explicit_tags(
                page,
                page_number=page_number,
                viewports=viewports,
                graph=graph,
                seen_physical=seen_physical,
                schedule_bboxes=schedule_bboxes,
                duplicate_holder=duplicate_holder,
            )
            self._ingest_ocr_lines(
                page_number=page_number,
                graph=graph,
                schedule_conflicts=schedule_conflicts,
                duplicate_holder=duplicate_holder,
                viewport_ids_by_tag=viewport_ids_by_tag,
                ambiguous=ambiguous,
            )
            raster_used = self._ingest_raster_schedule_viewports(
                page,
                page_number=page_number,
                viewports=viewports,
                graph=graph,
                schedule_conflicts=schedule_conflicts,
                duplicate_holder=duplicate_holder,
                viewport_ids_by_tag=viewport_ids_by_tag,
                ambiguous=ambiguous,
                rejected=raster_rejected,
            )
            if raster_used:
                raster_pages.append(page_number)
            self._note_ambiguous_marks(page, page_number, viewports, graph, ambiguous)

        conflicting_tags = {str(item["tag"]) for item in schedule_conflicts if item.get("tag")}
        reconciled = graph.reconcile_all()
        quantities: list[QuantityEvidence] = []
        entities: list[EntityEvidence] = []
        openings: list[CanonicalOpening] = []
        visible_conflicts: list[dict[str, Any]] = list(schedule_conflicts)
        suppressed = len(graph.suppressed_duplicates) + duplicate_holder[0]

        for tag, group in sorted(reconciled.items(), key=lambda item: item[0]):
            evidence_ids = self._group_evidence_ids(group, graph)
            plan_count = int(group.metadata.get("plan_count") or 0)
            schedule_qty = group.metadata.get("schedule_count")
            has_schedule = schedule_qty is not None
            elev_only_mismatch = (
                group.status == ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value
                and has_schedule
                and plan_count == 0
                and any(c.get("type") == "schedule_vs_plan_count_mismatch" for c in group.conflicts)
            )
            if elev_only_mismatch:
                # Elevation/section appearances are supporting evidence, not a second count.
                group.conflicts = [
                    c for c in group.conflicts if c.get("type") != "schedule_vs_plan_count_mismatch"
                ]
                group.status = ReconciliationStatus.CONFIRMED.value
                group.final_quantity = float(schedule_qty)
            visible_conflicts.extend(group.conflicts)
            if tag in conflicting_tags:
                quantities.append(
                    self._abstain(
                        tag=tag,
                        trade=group.trade_type,
                        path=path,
                        reasons=("duplicate_schedule_conflict",),
                        evidence_ids=evidence_ids,
                    )
                )
                continue
            if any(c.get("type") == "dimension_conflict" for c in group.conflicts):
                quantities.append(
                    self._abstain(
                        tag=tag,
                        trade=group.trade_type,
                        path=path,
                        reasons=("conflicting_dimensions",),
                        evidence_ids=evidence_ids,
                    )
                )
                continue
            if group.status == ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value:
                reasons = tuple(
                    str(c.get("type") or "conflict_manual_review") for c in group.conflicts
                ) or ("conflict_manual_review",)
                quantities.append(
                    self._abstain(
                        tag=tag,
                        trade=group.trade_type,
                        path=path,
                        reasons=reasons,
                        evidence_ids=evidence_ids,
                    )
                )
                continue
            if group.final_quantity is None:
                quantities.append(
                    self._abstain(
                        tag=tag,
                        trade=group.trade_type,
                        path=path,
                        reasons=("missing_quantity",),
                        evidence_ids=evidence_ids,
                    )
                )
                continue
            if not evidence_ids:
                quantities.append(
                    self._abstain(
                        tag=tag,
                        trade=group.trade_type,
                        path=path,
                        reasons=("missing_identity_evidence",),
                    )
                )
                continue
            if has_schedule and plan_count == 0:
                formula = "explicit_schedule_count"
                authority = "schedule_extracted"
                status = "provisional"
            elif has_schedule and plan_count > 0:
                formula = "schedule_plan_corroborated"
                authority = "schedule_extracted"
                status = "firm"
            elif plan_count > 0:
                formula = "plan_tag_count"
                authority = "provisional"
                status = "provisional"
            else:
                quantities.append(
                    self._abstain(
                        tag=tag,
                        trade=group.trade_type,
                        path=path,
                        reasons=("supporting_view_only",),
                        evidence_ids=evidence_ids,
                    )
                )
                continue

            type_entity_id = stable_contract_id(
                "ent",
                {"kind": "opening_type", "tag": tag, "source": str(path)},
            )
            entity_status = (
                EvidenceResolutionStatus.CORROBORATED
                if formula == "schedule_plan_corroborated"
                else EvidenceResolutionStatus.CANDIDATE
            )
            entities.append(
                EntityEvidence(
                    candidate_entity_id=type_entity_id,
                    candidate_type="opening_type",
                    evidence_ids=evidence_ids,
                    status=entity_status,
                    confidence=0.9 if status == "firm" else 0.6,
                    reason_codes=(formula,),
                    metadata={
                        "mark": tag,
                        "trade_type": group.trade_type,
                        "count_kind": "opening_type_count",
                        "scheduled_quantity": schedule_qty,
                        "plan_instance_count": plan_count,
                        "spatially_reconstructed": False,
                    },
                )
            )
            for occ in group.occurrences_by_view.get(DrawingViewType.FLOOR_PLAN.value, []):
                if not occ.bounding_box:
                    continue
                phys_id = stable_contract_id(
                    "ent",
                    {
                        "kind": "opening_instance",
                        "tag": tag,
                        "page": occ.source_page,
                        "bbox": _round_bbox(occ.bounding_box),
                    },
                )
                entities.append(
                    EntityEvidence(
                        candidate_entity_id=phys_id,
                        candidate_type="opening_instance",
                        evidence_ids=(occ.occurrence_id,),
                        status=EvidenceResolutionStatus.CANDIDATE,
                        confidence=float(occ.confidence),
                        reason_codes=("plan_tag_observation",),
                        metadata={
                            "mark": tag,
                            "count_kind": "physical_instance_candidate",
                            "source_page": occ.source_page,
                            "spatially_reconstructed": False,
                        },
                    )
                )

            width_m = height_m = None
            if group.dimensions and len(group.dimensions) >= 2:
                width_m = group.dimensions[0] / 1000.0 if group.dimensions[0] > 50 else group.dimensions[0]
                height_m = group.dimensions[1] / 1000.0 if group.dimensions[1] > 50 else group.dimensions[1]
            spec = graph.schedule_specs.get(tag)
            openings.append(
                CanonicalOpening(
                    id=stable_contract_id("open", {"tag": tag, "kind": "type", "source": str(path)}),
                    name=f"{tag} opening type",
                    opening_type="WINDOW" if group.trade_type == "windows" else "DOOR",
                    mark=tag,
                    width_m=width_m,
                    height_m=height_m,
                    object_type=ObjectType.WINDOW if group.trade_type == "windows" else ObjectType.DOOR,
                    review_state=ReviewState.REVIEW_REQUIRED,
                    takeoff_eligible=False,
                    deduction_authority=False,
                    provenance=Provenance(
                        source_pdf=str(path),
                        page_number=spec.source_page if spec else None,
                        producer_module=PROVIDER_ENGINE_ID,
                        producer_version=PROVIDER_ENGINE_VERSION,
                        contributing_evidence=list(evidence_ids),
                    ),
                    metadata={
                        "count_kind": "opening_type",
                        "type_count": group.final_quantity,
                        "spatially_reconstructed": False,
                        "physical_instance_count_not_implied": True,
                    },
                )
            )
            quantities.append(
                QuantityEvidence(
                    quantity_id=stable_contract_id(
                        "qty",
                        {
                            "family": _family_for_trade(group.trade_type),
                            "tag": tag,
                            "value": group.final_quantity,
                            "formula": formula,
                            "version": FORMULA_VERSION,
                        },
                    ),
                    family=_family_for_trade(group.trade_type),
                    semantic_key=tag,
                    value=float(group.final_quantity),
                    unit="ea",
                    input_entity_ids=(type_entity_id,),
                    formula=formula,
                    formula_version=FORMULA_VERSION,
                    evidence_ids=evidence_ids,
                    authority=authority,
                    status=status,
                    confidence=0.9 if status == "firm" else 0.55,
                    abstained=False,
                    reason_codes=(formula, group.status),
                    metadata={
                        "count_kind": "opening_type_count",
                        "spatially_reconstructed": False,
                        "plan_instance_count": plan_count,
                        "schedule_count": schedule_qty,
                        "trade_type": group.trade_type,
                        "source_page": spec.source_page if spec else None,
                        "source_sheet": None,
                        "description": group.description,
                        "viewport_id": viewport_ids_by_tag.get(tag),
                        "view_types": sorted(
                            view
                            for view, occs in group.occurrences_by_view.items()
                            if occs
                        ),
                    },
                )
            )

        for mark in sorted(set(ambiguous)):
            quantities.append(
                self._abstain(
                    tag=mark,
                    trade="openings",
                    path=path,
                    reasons=("ambiguous_opening_identity",),
                    family="opening_count",
                )
            )

        quantities = self._prefer_abstention(tuple(quantities))
        quantities = tuple(quantities) + derive_family_totals(
            quantities,
            formula_version=FORMULA_VERSION,
        )
        quantities = tuple(
            sorted(quantities, key=lambda item: (item.family, item.semantic_key, item.quantity_id))
        )
        return OpeningCountBundle(
            quantities=quantities,
            entity_evidence=tuple(entities),
            canonical_openings=tuple(openings),
            conflicts=tuple(visible_conflicts),
            ambiguous_marks=tuple(sorted(set(ambiguous))),
            duplicate_observations=suppressed,
            diagnostics={
                "engine_id": self.engine_id,
                "engine_version": self.engine_version,
                "families": sorted(OPENING_COUNT_FAMILIES),
                "authoritative": False,
                "authority_state": "new_shadow",
                "gold_consulted": False,
                "pages_considered": target,
                "type_count_is_not_physical_reconstruction": True,
                "raster_schedule_pages": raster_pages,
                "raster_authority_rejections": raster_rejected,
                "family_aggregates_emitted": [
                    item.semantic_key
                    for item in quantities
                    if item.metadata.get("count_kind") == "family_aggregate"
                ],
            },
        )

    def _add_physical_observation(
        self,
        *,
        graph: EvidenceGraph,
        seen_physical: set[tuple[str, int, tuple[float, ...]]],
        duplicate_holder: list[int],
        tag: str,
        trade_type: str,
        page_number: int,
        bbox: Optional[Sequence[float]],
        text: str,
        dimensions: Optional[list[float]],
        view_type: str,
        method: str,
        confidence: float = 1.0,
        legend: bool = False,
        view_id: str = "",
    ) -> None:
        rounded = _round_bbox(bbox)
        for existing_tag, existing_page, existing_bbox in seen_physical:
            if existing_tag == tag and existing_page == page_number and (
                existing_bbox == rounded or (rounded and existing_bbox and _bbox_near(existing_bbox, rounded))
            ):
                duplicate_holder[0] += 1
                return
        seen_physical.add((tag, page_number, rounded))
        occ_id = stable_contract_id(
            "ev",
            {"kind": "physical_tag", "tag": tag, "page": page_number, "bbox": rounded, "text": text},
        )
        observation = EvidenceOccurrence(
            occurrence_id=occ_id,
            tag=tag,
            trade_type=trade_type,
            view_type=view_type,
            source_page=page_number,
            bounding_box=list(bbox) if bbox else None,
            raw_text=text,
            dimensions=dimensions,
            is_legend_or_typical=legend,
            confidence=confidence,
            extraction_method=method,
        ).to_observation()
        observation.view_id = view_id
        observation.metadata = {
            **dict(observation.metadata or {}),
            "is_legend_or_typical": legend,
            "viewport_id": view_id,
        }
        graph.add_observation(observation)

    def _ingest_explicit_tags(
        self,
        page: fitz.Page,
        *,
        page_number: int,
        viewports: Sequence[Any],
        graph: EvidenceGraph,
        seen_physical: set[tuple[str, int, tuple[float, ...]]],
        schedule_bboxes: set[tuple[int, tuple[float, ...]]],
        duplicate_holder: list[int],
    ) -> None:
        words = page.get_text("words") or []
        for word in words:
            text = str(word[4])
            tags = find_explicit_opening_tags(text)
            if not tags:
                continue
            bbox = (float(word[0]), float(word[1]), float(word[2]), float(word[3]))
            if (page_number, _round_bbox(bbox)) in schedule_bboxes:
                continue
            view_type, view_id = _classify_page_view(page, page_number, bbox, viewports)
            if view_type == DrawingViewType.SCHEDULE.value:
                continue
            nearby = nearby_word_text(
                words,
                ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0),
            )
            if not native_tag_context_allowed(text, nearby):
                continue
            if view_type in _DETAIL_OR_LEGEND or view_type in {
                DrawingViewType.SECTION.value,
                DrawingViewType.UNKNOWN.value,
                DrawingViewType.ADJACENT_SCOPE.value,
            }:
                continue
            if view_type == DrawingViewType.ELEVATION.value:
                role_view = DrawingViewType.ELEVATION.value
            elif view_type in {DrawingViewType.FLOOR_PLAN.value, DrawingViewType.ROOF_PLAN.value}:
                role_view = view_type
            else:
                continue
            for norm in tags:
                if is_work_section_or_nrm_code(norm.tag, nearby):
                    continue
                self._add_physical_observation(
                    graph=graph,
                    seen_physical=seen_physical,
                    duplicate_holder=duplicate_holder,
                    tag=norm.tag,
                    trade_type=norm.trade_type,
                    page_number=page_number,
                    bbox=bbox,
                    text=text,
                    dimensions=None,
                    view_type=role_view,
                    method="native",
                    legend=False,
                    view_id=view_id,
                )

    def _ingest_ocr_lines(
        self,
        *,
        page_number: int,
        graph: EvidenceGraph,
        schedule_conflicts: list[dict[str, Any]],
        duplicate_holder: list[int],
        viewport_ids_by_tag: dict[str, str],
        ambiguous: list[str],
        view_id: str = "",
    ) -> None:
        raw_lines = list(self._ocr_lines_by_page.get(page_number, ()))
        lines = group_ocr_tokens_into_lines(raw_lines) if raw_lines else []
        if not lines:
            lines = [dict(line) for line in raw_lines]
        for line in lines:
            self._ingest_one_ocr_schedule_line(
                line,
                page_number=page_number,
                graph=graph,
                schedule_conflicts=schedule_conflicts,
                duplicate_holder=duplicate_holder,
                viewport_ids_by_tag=viewport_ids_by_tag,
                ambiguous=ambiguous,
                view_id=view_id,
                min_confidence=0.55,
            )

    def _ingest_one_ocr_schedule_line(
        self,
        line: Mapping[str, Any],
        *,
        page_number: int,
        graph: EvidenceGraph,
        schedule_conflicts: list[dict[str, Any]],
        duplicate_holder: list[int],
        viewport_ids_by_tag: dict[str, str],
        ambiguous: list[str],
        view_id: str = "",
        min_confidence: float = 0.55,
    ) -> None:
        text = str(line.get("text") or "")
        if page_looks_like_bill_or_nrm(text):
            return
        bbox = line.get("bounding_box") or line.get("bbox")
        confidence = float(line.get("confidence") or 0.8)
        if confidence < min_confidence:
            return
        record = DrawingEvidenceParser.parse_schedule_line(
            text,
            source_page=page_number,
            bbox=list(bbox) if bbox else None,
            confidence=confidence,
            method=EvidenceMethod.RASTER_OCR.value,
        )
        if record is None:
            return
        if is_ambiguous_ocr_mark(record.tag):
            ambiguous.append(record.tag)
            return
        if not ocr_mark_is_usable(record.tag):
            return
        if not schedule_line_is_authoritative(text, tag=record.tag, quantity=record.quantity):
            return
        norm = resolve_opening_identity(
            record.tag,
            evidence_text=text,
            trade_type="windows" if str(record.tag).upper().startswith("W") else "doors",
        )
        if norm is None:
            return
        existing = graph.schedule_specs.get(norm.tag)
        if existing is not None:
            if _specs_conflict(existing, record.quantity, record.dimensions):
                schedule_conflicts.append(
                    {
                        "type": "duplicate_schedule_conflict",
                        "tag": norm.tag,
                        "first": existing.scheduled_quantity,
                        "second": record.quantity,
                    }
                )
                return
            if existing.scheduled_quantity is not None:
                duplicate_holder[0] += 1
                return
        if record.quantity is None:
            return
        evidence_id = stable_contract_id(
            "ev",
            {"kind": "ocr_schedule", "tag": norm.tag, "page": page_number, "text": text},
        )
        graph.add_schedule_spec(
            ScheduleSpecification(
                tag=norm.tag,
                trade_type=norm.trade_type,
                description=record.description,
                dimensions=record.dimensions,
                scheduled_quantity=record.quantity,
                source_page=page_number,
                bounding_box=record.bounding_box,
                confidence=record.confidence,
                extraction_method="ocr",
                evidence_id=evidence_id,
            )
        )
        observation = EvidenceOccurrence(
            occurrence_id=evidence_id,
            tag=norm.tag,
            trade_type=norm.trade_type,
            view_type=DrawingViewType.SCHEDULE.value,
            source_page=page_number,
            bounding_box=record.bounding_box,
            raw_text=text,
            dimensions=record.dimensions,
            confidence=record.confidence,
            extraction_method="ocr",
        ).to_observation()
        observation.view_id = view_id
        observation.metadata = {**dict(observation.metadata or {}), "viewport_id": view_id}
        graph.add_observation(observation)
        if view_id:
            viewport_ids_by_tag.setdefault(norm.tag, view_id)

    def _shadow_ocr_engine(self) -> Any:
        if self._ocr_engine is None:
            self._ocr_engine = make_shadow_ocr_engine()
        return self._ocr_engine

    def _ingest_raster_schedule_viewports(
        self,
        page: fitz.Page,
        *,
        page_number: int,
        viewports: Sequence[Any],
        graph: EvidenceGraph,
        schedule_conflicts: list[dict[str, Any]],
        duplicate_holder: list[int],
        viewport_ids_by_tag: dict[str, str],
        ambiguous: list[str],
        rejected: list[str],
    ) -> bool:
        if not self._enable_raster_ocr:
            return False
        page_text = page.get_text("text") or ""
        if page_is_bill_of_quantities(page_text) or page_looks_like_bill_or_nrm(page_text):
            return False
        native_qty_on_page = any(
            spec.source_page == page_number and spec.scheduled_quantity is not None
            for spec in graph.schedule_specs.values()
        )
        if native_qty_on_page:
            return False
        candidates = [
            viewport
            for viewport in viewports
            if viewport_is_opening_schedule_candidate(viewport, page_text)
        ]
        if not candidates and page_is_opening_schedule_sheet(page_text):
            rect = page.rect
            candidates = [
                type(
                    "WholePageSchedule",
                    (),
                    {
                        "view_id": f"page_{page_number}_schedule",
                        "view_type": DrawingViewType.SCHEDULE.value,
                        "label": "WINDOW SCHEDULE" if "window" in page_text.lower() else "DOOR SCHEDULE",
                        "title": "opening schedule",
                        "bounding_box": (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                    },
                )()
            ]
        if not candidates:
            return False
        used = False
        engine = self._shadow_ocr_engine()
        page_rect = page.rect
        for viewport in candidates:
            bbox = getattr(viewport, "bounding_box", None)
            if not bbox or len(bbox) < 4:
                bbox = (
                    float(page_rect.x0),
                    float(page_rect.y0),
                    float(page_rect.x1),
                    float(page_rect.y1),
                )
            try:
                clip = fitz.Rect(bbox)
                tokens = engine.recognize_page_rect(page, clip_rect=clip, dpi=self._raster_ocr_dpi)
            except Exception:
                rejected.append(f"{getattr(viewport, 'view_id', '')}:ocr_failed")
                continue
            lines = group_ocr_tokens_into_lines(tokens)
            body = " ".join(str(line.get("text") or "") for line in lines)
            title = str(getattr(viewport, "label", "") or getattr(viewport, "title", "") or "")
            marks = re.findall(r"\b([WwDd])\s*[-_]?\s*(\d{1,3})\b", f"{title} {body}")
            authority = assess_opening_schedule_authority(
                title=title,
                body_text=body,
                mark_hits=len(marks),
                distinct_marks=len({f"{a.upper()}{b}" for a, b in marks}),
            )
            if not authority.accepted:
                rejected.append(
                    f"{getattr(viewport, 'view_id', 'viewport')}:{','.join(authority.reasons)}"
                )
                continue
            view_id = str(getattr(viewport, "view_id", "") or "")
            for line in lines:
                self._ingest_one_ocr_schedule_line(
                    line,
                    page_number=page_number,
                    graph=graph,
                    schedule_conflicts=schedule_conflicts,
                    duplicate_holder=duplicate_holder,
                    viewport_ids_by_tag=viewport_ids_by_tag,
                    ambiguous=ambiguous,
                    view_id=view_id,
                    min_confidence=0.30,
                )
            for row in iter_complete_opening_schedule_rows(body):
                self._ingest_one_ocr_schedule_line(
                    {
                        "text": row["text"],
                        "bbox": list(bbox),
                        "confidence": 0.72,
                    },
                    page_number=page_number,
                    graph=graph,
                    schedule_conflicts=schedule_conflicts,
                    duplicate_holder=duplicate_holder,
                    viewport_ids_by_tag=viewport_ids_by_tag,
                    ambiguous=ambiguous,
                    view_id=view_id,
                    min_confidence=0.30,
                )
            used = True
        return used

    def _note_ambiguous_marks(
        self,
        page: fitz.Page,
        page_number: int,
        viewports: Sequence[Any],
        graph: EvidenceGraph,
        ambiguous: list[str],
    ) -> None:
        text = page.get_text("text") or ""
        view_type, _ = _classify_page_view(page, page_number, None, viewports)
        if view_type != DrawingViewType.SCHEDULE.value and not _SCHEDULE_TITLE_RE.search(text):
            return
        resolved_wd = {tag for tag in graph.schedule_specs if _F28_WD_TAG_RE.fullmatch(tag)}
        for match in _WD_TOKEN_RE.finditer(text):
            number = match.group("number")
            key = f"WD{int(number)}" if number else "WD"
            if key in resolved_wd or (key == "WD" and resolved_wd):
                continue
            if normalize_opening_tag(match.group(0)) is not None:
                continue
            ambiguous.append(key)

    def _group_evidence_ids(self, group: Any, graph: EvidenceGraph) -> tuple[str, ...]:
        ids: list[str] = []
        spec = graph.schedule_specs.get(group.tag)
        if spec and spec.evidence_id:
            ids.append(spec.evidence_id)
        for occs in group.occurrences_by_view.values():
            for occ in occs:
                if occ.occurrence_id:
                    ids.append(occ.occurrence_id)
        unique: list[str] = []
        for item in ids:
            if item not in unique:
                unique.append(item)
        return tuple(unique)

    def _prefer_abstention(self, quantities: Sequence[QuantityEvidence]) -> tuple[QuantityEvidence, ...]:
        by_key: dict[str, QuantityEvidence] = {}
        for quantity in quantities:
            previous = by_key.get(quantity.semantic_key)
            if previous is None:
                by_key[quantity.semantic_key] = quantity
                continue
            if quantity.abstained or previous.abstained:
                by_key[quantity.semantic_key] = quantity if quantity.abstained else previous
        return tuple(
            sorted(by_key.values(), key=lambda item: (item.family, item.semantic_key, item.quantity_id))
        )

    def _abstain(
        self,
        *,
        tag: str,
        trade: str,
        path: Path,
        reasons: tuple[str, ...],
        family: Optional[str] = None,
        evidence_ids: tuple[str, ...] = (),
    ) -> QuantityEvidence:
        chosen_family = family or _family_for_trade(trade)
        return QuantityEvidence(
            quantity_id=stable_contract_id(
                "qty",
                {"family": chosen_family, "tag": tag, "abstained": True, "reasons": list(reasons)},
            ),
            family=chosen_family,
            semantic_key=tag,
            value=None,
            unit="ea",
            evidence_ids=evidence_ids,
            authority="blocked",
            status="blocked",
            confidence=0.0,
            abstained=True,
            blocking_reasons=reasons,
            reason_codes=reasons,
            metadata={
                "count_kind": "opening_type_count",
                "spatially_reconstructed": False,
                "source_pdf": str(path),
            },
        )
