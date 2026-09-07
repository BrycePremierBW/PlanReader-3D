"""pb_editable_3d_quantity_recalculation.py — Corrected Quantity Recalculation.

When geometry changes, marking the old quantity stale is not enough — the affected
quantity must be recalculated from the corrected geometry and produced as a new,
separate current candidate. The old quantity is preserved for audit; the new one is
never auto-published (correction is not approval — see pb_editable_3d_model.py PR D.2).

Only geometry the codebase already knows how to measure gets a real recalculated
number. Anything else (unmapped object/field combinations, malformed geometry)
returns manual_review_required rather than a guessed value.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pb_geometry_takeoff_model import Opening, calculate_wall_takeoff, classify_finish_tag
from pb_editable_3d_correction_model import (
    CorrectionField,
    Editable3DCorrectionEvent,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    invalidate_stale_quantities_for_corrections,
)
from pb_takeoff_output_authority import TakeoffOutputRow, TakeoffSourceType, create_takeoff_output_row


# ---------------------------------------------------------------------------
# Recalculation targets
# ---------------------------------------------------------------------------

class RecalculationTarget(str, Enum):
    WALL_LENGTH = "wall_length"
    WALL_GROSS_AREA = "wall_gross_area"
    WALL_NET_AREA = "wall_net_area"
    OPENING_AREA = "opening_area"
    ROOM_FLOOR_AREA = "room_floor_area"
    ROOM_PERIMETER = "room_perimeter"
    CEILING_AREA = "ceiling_area"
    SURFACE_AREA = "surface_area"
    FINISH_QUANTITY = "finish_quantity"
    SOFFIT_AREA = "soffit_area"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


# Explicit geometry-object -> affected-derived-quantities dependency graph.
# Keyed by (object_type, corrected field). FINISH_TAG is handled separately below
# since it applies uniformly across object types.
_DEPENDENCY_GRAPH: Dict[Tuple[str, str], List[str]] = {
    (EditableObjectType.WALL.value, CorrectionField.LENGTH.value): [
        RecalculationTarget.WALL_LENGTH.value,
        RecalculationTarget.WALL_GROSS_AREA.value,
        RecalculationTarget.WALL_NET_AREA.value,
    ],
    (EditableObjectType.WALL.value, CorrectionField.HEIGHT.value): [
        RecalculationTarget.WALL_GROSS_AREA.value,
        RecalculationTarget.WALL_NET_AREA.value,
    ],
    (EditableObjectType.OPENING.value, CorrectionField.OPENING_WIDTH.value): [
        RecalculationTarget.OPENING_AREA.value,
    ],
    (EditableObjectType.OPENING.value, CorrectionField.OPENING_HEIGHT.value): [
        RecalculationTarget.OPENING_AREA.value,
    ],
    (EditableObjectType.ROOM.value, CorrectionField.COORDINATES.value): [
        RecalculationTarget.ROOM_FLOOR_AREA.value,
        RecalculationTarget.ROOM_PERIMETER.value,
    ],
    (EditableObjectType.CEILING.value, CorrectionField.AREA.value): [
        RecalculationTarget.CEILING_AREA.value,
    ],
    (EditableObjectType.SURFACE.value, CorrectionField.AREA.value): [
        RecalculationTarget.SURFACE_AREA.value,
    ],
    (EditableObjectType.SOFFIT.value, CorrectionField.AREA.value): [
        RecalculationTarget.SOFFIT_AREA.value,
    ],
}


def get_affected_targets(object_type: str, field: str) -> List[str]:
    """Deterministic lookup of which derived quantities a correction affects.

    FINISH_TAG applies uniformly regardless of object type. Anything not explicitly
    mapped returns [MANUAL_REVIEW_REQUIRED] rather than guessing.
    """
    if field == CorrectionField.FINISH_TAG.value:
        return [RecalculationTarget.FINISH_QUANTITY.value]
    targets = _DEPENDENCY_GRAPH.get((object_type, field))
    if targets is None:
        return [RecalculationTarget.MANUAL_REVIEW_REQUIRED.value]
    return list(targets)


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------

@dataclass
class QuantityRecalculationResult:
    correction_id: str
    object_id: str
    target: str  # RecalculationTarget
    status: str  # "recalculated" | "manual_review_required"
    old_value: Optional[float]
    new_value: Optional[float]
    unit: str
    old_row: Optional[TakeoffOutputRow]
    new_row: Optional[TakeoffOutputRow]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correction_id": self.correction_id,
            "object_id": self.object_id,
            "target": self.target,
            "status": self.status,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "unit": self.unit,
            "old_row": self.old_row.to_dict() if self.old_row is not None else None,
            "new_row": self.new_row.to_dict() if self.new_row is not None else None,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Per-target geometry formulas — real math only, no guessed numbers
# ---------------------------------------------------------------------------

def _require_finite_positive(value: Any, label: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric, got {value!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"{label} must be finite, got {v}")
    if v <= 0.0:
        raise ValueError(f"{label} must be strictly positive, got {v}")
    return v


def _wall_openings(obj: EditableGeometryObject) -> List[Opening]:
    raw = obj.coordinates_or_measurements.get("openings") or []
    result = []
    for o in raw:
        width = float(o["width_m"])
        height = float(o["height_m"])
        result.append(Opening(
            opening_id=str(o.get("opening_id", "OP")),
            opening_type=str(o.get("opening_type", "door")),
            width_m=width,
            height_m=height,
            area_m2=float(o.get("area_m2", width * height)),
            deducts=bool(o.get("deducts", True)),
        ))
    return result


def _formula_wall_gross(obj: EditableGeometryObject) -> float:
    length = _require_finite_positive(obj.coordinates_or_measurements.get("length"), "Wall length")
    height = _require_finite_positive(obj.coordinates_or_measurements.get("height"), "Wall height")
    gross, _, _ = calculate_wall_takeoff(length_m=length, height_m=height, openings=_wall_openings(obj))
    return gross


def _formula_wall_net(obj: EditableGeometryObject) -> float:
    length = _require_finite_positive(obj.coordinates_or_measurements.get("length"), "Wall length")
    height = _require_finite_positive(obj.coordinates_or_measurements.get("height"), "Wall height")
    _, _, net = calculate_wall_takeoff(length_m=length, height_m=height, openings=_wall_openings(obj))
    return net


def _formula_wall_length(obj: EditableGeometryObject) -> float:
    return _require_finite_positive(obj.coordinates_or_measurements.get("length"), "Wall length")


def _formula_opening_area(obj: EditableGeometryObject) -> float:
    width = _require_finite_positive(
        obj.coordinates_or_measurements.get("opening_width", obj.coordinates_or_measurements.get("width_m")),
        "Opening width",
    )
    height = _require_finite_positive(
        obj.coordinates_or_measurements.get("opening_height", obj.coordinates_or_measurements.get("height_m")),
        "Opening height",
    )
    return width * height


def _room_polygon(obj: EditableGeometryObject) -> Tuple[float, float]:
    pts = obj.coordinates_or_measurements.get("coordinates")
    if not pts or len(pts) < 3:
        raise ValueError("Room polygon requires at least 3 coordinate points")
    n = len(pts)
    shoelace = 0.0
    perimeter = 0.0
    for i in range(n):
        x1, y1 = float(pts[i][0]), float(pts[i][1])
        x2, y2 = float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
            raise ValueError("Room polygon coordinates must be finite")
        shoelace += (x1 * y2) - (x2 * y1)
        perimeter += math.hypot(x2 - x1, y2 - y1)
    area = abs(shoelace) / 2.0
    if area <= 0.0:
        raise ValueError("Room polygon area must be strictly positive (degenerate/collinear points)")
    return area, perimeter


def _formula_room_floor_area(obj: EditableGeometryObject) -> float:
    return _room_polygon(obj)[0]


def _formula_room_perimeter(obj: EditableGeometryObject) -> float:
    return _room_polygon(obj)[1]


def _formula_direct_area(obj: EditableGeometryObject) -> float:
    return _require_finite_positive(obj.coordinates_or_measurements.get("area"), "Area")


def _formula_finish_quantity(obj: EditableGeometryObject) -> float:
    tag = str(obj.coordinates_or_measurements.get("finish_tag") or "")
    if not tag:
        raise ValueError("finish_tag is required to recalculate finish quantity")
    classify_finish_tag(tag)  # validates the tag resolves to a known/heuristic classification
    return _require_finite_positive(obj.coordinates_or_measurements.get("area"), "Finish area")


_FORMULAS: Dict[str, Callable[[EditableGeometryObject], float]] = {
    RecalculationTarget.WALL_LENGTH.value: _formula_wall_length,
    RecalculationTarget.WALL_GROSS_AREA.value: _formula_wall_gross,
    RecalculationTarget.WALL_NET_AREA.value: _formula_wall_net,
    RecalculationTarget.OPENING_AREA.value: _formula_opening_area,
    RecalculationTarget.ROOM_FLOOR_AREA.value: _formula_room_floor_area,
    RecalculationTarget.ROOM_PERIMETER.value: _formula_room_perimeter,
    RecalculationTarget.CEILING_AREA.value: _formula_direct_area,
    RecalculationTarget.SURFACE_AREA.value: _formula_direct_area,
    RecalculationTarget.SOFFIT_AREA.value: _formula_direct_area,
    RecalculationTarget.FINISH_QUANTITY.value: _formula_finish_quantity,
}

_UNIT_FOR_TARGET = {
    RecalculationTarget.WALL_LENGTH.value: "m",
    RecalculationTarget.WALL_GROSS_AREA.value: "m²",
    RecalculationTarget.WALL_NET_AREA.value: "m²",
    RecalculationTarget.OPENING_AREA.value: "m²",
    RecalculationTarget.ROOM_FLOOR_AREA.value: "m²",
    RecalculationTarget.ROOM_PERIMETER.value: "m",
    RecalculationTarget.CEILING_AREA.value: "m²",
    RecalculationTarget.SURFACE_AREA.value: "m²",
    RecalculationTarget.FINISH_QUANTITY.value: "m²",
    RecalculationTarget.SOFFIT_AREA.value: "m²",
}

_TARGET_KEYWORDS: Dict[str, List[str]] = {
    RecalculationTarget.WALL_LENGTH.value: ["length"],
    RecalculationTarget.WALL_GROSS_AREA.value: ["gross area", "gross"],
    RecalculationTarget.WALL_NET_AREA.value: ["net area", "net"],
    RecalculationTarget.OPENING_AREA.value: ["opening area", "opening"],
    RecalculationTarget.ROOM_FLOOR_AREA.value: ["floor area"],
    RecalculationTarget.ROOM_PERIMETER.value: ["perimeter"],
    RecalculationTarget.CEILING_AREA.value: ["ceiling area", "ceiling"],
    RecalculationTarget.SURFACE_AREA.value: ["surface area", "surface"],
    RecalculationTarget.FINISH_QUANTITY.value: ["finish"],
    RecalculationTarget.SOFFIT_AREA.value: ["soffit area", "soffit"],
}


def _match_old_row(target: str, candidates: List[TakeoffOutputRow]) -> Optional[TakeoffOutputRow]:
    """Match an existing row to a recalculation target by description keyword, so a
    single old row (e.g. 'gross area') is never mistakenly paired with a different
    target (e.g. 'length') just because it happened to be first in the list."""
    keywords = _TARGET_KEYWORDS.get(target, [])
    for row in candidates:
        desc = row.description.lower()
        if any(kw in desc for kw in keywords):
            return row
    return None


def _reconstruct_before(obj_after: EditableGeometryObject, event: Editable3DCorrectionEvent) -> Optional[EditableGeometryObject]:
    """The object's state immediately before this one correction, reconstructed by
    rolling back only the field the event changed. Used to compute a real (not
    guessed) old_value from geometry when no existing row supplies one."""
    if event.old_value is None:
        return None
    measurements = dict(obj_after.coordinates_or_measurements)
    measurements[event.field] = event.old_value
    return replace(obj_after, coordinates_or_measurements=measurements)


def _build_new_row(
    *,
    target: str,
    object_id: str,
    obj: EditableGeometryObject,
    event: Editable3DCorrectionEvent,
    value: float,
    old_row: Optional[TakeoffOutputRow],
    description_suffix: str = "",
) -> TakeoffOutputRow:
    base_qid = old_row.quantity_id if old_row is not None else f"{object_id}-{target}"
    new_qid = f"{base_qid}-REV-{event.correction_id}"
    label = target.replace("_", " ").title()
    trade = old_row.trade if old_row is not None else "general"
    description = f"{obj.object_type.title()} {object_id} — {label} (corrected)" + description_suffix

    return create_takeoff_output_row(
        quantity_id=new_qid,
        description=description,
        value=value,
        unit=_UNIT_FOR_TARGET.get(target, "m²"),
        trade=trade,
        source_type=TakeoffSourceType.USER_CORRECTED,
        source_page=obj.source_page,
        source_sheet=obj.source_sheet,
        geometry_ref=object_id,
        revision_hash=event.new_revision_hash,
        correction_id=event.correction_id,
        allow_zero=False,
    )


# ---------------------------------------------------------------------------
# Main recalculation entry point
# ---------------------------------------------------------------------------

def recalculate_quantities_for_correction(
    event: Editable3DCorrectionEvent,
    obj_after: EditableGeometryObject,
    existing_rows: Sequence[TakeoffOutputRow] = (),
    ledger: Optional[Editable3DCorrectionLedger] = None,
) -> List[QuantityRecalculationResult]:
    """Recalculate every quantity affected by one correction event.

    Existing rows linked to obj_after.object_id (via geometry_ref) are staled first
    (delegating to the existing D.1 bridge — never reimplemented here), then matched
    to targets by description keyword so a single old row is never mispaired with an
    unrelated target. For each affected target, a real formula is applied when the
    geometry supports it; when it doesn't (unmapped combination, or malformed/
    non-finite/non-positive geometry), the result is manual_review_required with no
    fabricated new_row.

    If `ledger` is given, every successfully recalculated row's quantity_id is
    automatically linked as a dependent quantity of the object (D.4's
    link_dependent_quantities(), not reimplemented — additive and deduplicating).
    Omitting `ledger` (the default) preserves the exact prior behaviour with no
    auto-linking, so every existing call site is unaffected.
    """
    object_id = obj_after.object_id
    targets = get_affected_targets(obj_after.object_type, event.field)

    staled = invalidate_stale_quantities_for_corrections(existing_rows, corrected_object_ids=[object_id])
    candidates = [r.new_row for r in staled if r.old_row.geometry_ref == object_id]

    before_obj = _reconstruct_before(obj_after, event)
    results: List[QuantityRecalculationResult] = []

    for target in targets:
        old_row = _match_old_row(target, candidates)
        if old_row is not None:
            candidates = [c for c in candidates if c is not old_row]

        formula = _FORMULAS.get(target)
        if formula is None:
            results.append(QuantityRecalculationResult(
                correction_id=event.correction_id,
                object_id=object_id,
                target=RecalculationTarget.MANUAL_REVIEW_REQUIRED.value,
                status="manual_review_required",
                old_value=old_row.value if old_row is not None else None,
                new_value=None,
                unit="",
                old_row=old_row,
                new_row=None,
                reason=(
                    f"No recalculation formula mapped for object_type={obj_after.object_type!r}, "
                    f"field={event.field!r}"
                ),
            ))
            continue

        try:
            new_value = formula(obj_after)
        except (ValueError, KeyError, TypeError) as exc:
            results.append(QuantityRecalculationResult(
                correction_id=event.correction_id,
                object_id=object_id,
                target=target,
                status="manual_review_required",
                old_value=old_row.value if old_row is not None else None,
                new_value=None,
                unit=_UNIT_FOR_TARGET.get(target, ""),
                old_row=old_row,
                new_row=None,
                reason=str(exc),
            ))
            continue

        old_value = old_row.value if old_row is not None else None
        if old_value is None and before_obj is not None:
            try:
                old_value = formula(before_obj)
            except (ValueError, KeyError, TypeError):
                old_value = None

        description_suffix = ""
        if target == RecalculationTarget.FINISH_QUANTITY.value:
            tag = obj_after.coordinates_or_measurements.get("finish_tag")
            record = classify_finish_tag(str(tag)) if tag else None
            if record is not None:
                description_suffix = f" [{tag}: {record.scope_disposition}]"

        new_row = _build_new_row(
            target=target, object_id=object_id, obj=obj_after, event=event,
            value=new_value, old_row=old_row, description_suffix=description_suffix,
        )

        results.append(QuantityRecalculationResult(
            correction_id=event.correction_id,
            object_id=object_id,
            target=target,
            status="recalculated",
            old_value=old_value,
            new_value=new_value,
            unit=_UNIT_FOR_TARGET.get(target, "m²"),
            old_row=old_row,
            new_row=new_row,
        ))

    if ledger is not None:
        new_quantity_ids = [r.new_row.quantity_id for r in results if r.new_row is not None]
        if new_quantity_ids:
            ledger.link_dependent_quantities(object_id, new_quantity_ids)

    return results
