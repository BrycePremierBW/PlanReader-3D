"""pb_opening_deduction_pipeline.py — Generic Opening Deduction Pipeline.

PR F.9: Deducts evidenced door and window opening areas from walling and wall finishes.

CRITICAL ARCHITECTURAL BOUNDARY:
- Strictly generic, deterministic geometry and schedule evidence.
- Zero knowledge of benchmark IDs, ground truth BOQs, or project-specific answers.
- Inputs must come ONLY from:
  1. parsed wall geometry (length, perimeter, height)
  2. parsed opening width/height (figured dimensions or schedule dimensions)
  3. counted schedule / tag quantities
  4. wall/opening spatial binding or envelope membership
  5. valid drawing scale.
- FAIL CLOSED:
  1. If opening height or width is unknown: deduction is 0.0, marked unresolved. Do not guess.
  2. If opening cannot be bound to a wall: deduction is 0.0, marked provisional/unbound.
  3. Zero generic fenestration percentages (never assume 10%, 15%, etc.).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


class OpeningDeductionStatus(str, Enum):
    """Lifecycle status for opening deduction processing."""

    APPLIED = "applied"
    PROVISIONAL_UNBOUND = "provisional_unbound"
    UNRESOLVED_MISSING_DIMENSIONS = "unresolved_missing_dimensions"
    INVALID_DIMENSIONS = "invalid_dimensions"


@dataclass
class OpeningInstance:
    """An individual opening or opening group (e.g. W1, D1) from schedule/callouts."""

    opening_id: str
    trade_type: str = "windows"  # "windows", "doors", "opening"
    width_m: Optional[float] = None
    height_m: Optional[float] = None
    quantity: float = 1.0
    bound_wall_id: Optional[str] = None
    source_page: Optional[int] = None
    bounding_box: Optional[List[float]] = None
    status: OpeningDeductionStatus = OpeningDeductionStatus.PROVISIONAL_UNBOUND
    notes: str = ""

    @property
    def single_area_m2(self) -> Optional[float]:
        """Gross area of a single opening in square meters."""
        if (
            self.width_m is not None
            and self.height_m is not None
            and self.width_m > 0.0
            and self.height_m > 0.0
        ):
            return round(self.width_m * self.height_m, 4)
        return None

    @property
    def total_area_m2(self) -> Optional[float]:
        """Total area of this opening type across its quantity in square meters."""
        s = self.single_area_m2
        if s is not None and self.quantity > 0:
            return round(s * self.quantity, 4)
        return None

    @property
    def is_valid_deduction(self) -> bool:
        """True only if dimensions are strictly positive and wall binding exists."""
        return (
            self.width_m is not None
            and self.height_m is not None
            and self.width_m > 0.0
            and self.height_m > 0.0
            and self.quantity > 0.0
            and self.bound_wall_id is not None
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opening_id": self.opening_id,
            "trade_type": self.trade_type,
            "width_m": self.width_m,
            "height_m": self.height_m,
            "quantity": self.quantity,
            "bound_wall_id": self.bound_wall_id,
            "single_area_m2": self.single_area_m2,
            "total_area_m2": self.total_area_m2,
            "status": self.status.value,
            "source_page": self.source_page,
            "bounding_box": self.bounding_box,
            "notes": self.notes,
        }


@dataclass
class WallInstance:
    """A wall element or aggregate perimeter walling envelope."""

    wall_id: str
    length_m: Optional[float] = None
    height_m: Optional[float] = None
    gross_area_m2: float = 0.0
    bounding_box: Optional[List[float]] = None
    trade_type: str = "walls"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "length_m": self.length_m,
            "height_m": self.height_m,
            "gross_area_m2": round(self.gross_area_m2, 2),
            "bounding_box": self.bounding_box,
            "trade_type": self.trade_type,
        }


@dataclass
class WallDeductionResult:
    """Comprehensive deduction result for a wall, including audit breakdown."""

    wall_id: str
    gross_area_m2: float
    total_deducted_area_m2: float
    net_area_m2: float
    applied_openings: List[Dict[str, Any]] = field(default_factory=list)
    unresolved_openings: List[Dict[str, Any]] = field(default_factory=list)
    unbound_openings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "gross_area_m2": round(self.gross_area_m2, 2),
            "total_deducted_area_m2": round(self.total_deducted_area_m2, 2),
            "net_area_m2": round(self.net_area_m2, 2),
            "applied_openings": self.applied_openings,
            "unresolved_openings": self.unresolved_openings,
            "unbound_openings": self.unbound_openings,
        }


class GenericOpeningDeductionPipeline:
    """Orchestrates opening-to-wall binding, opening area computation, and net wall area derivation."""

    def __init__(self) -> None:
        pass

    def bind_openings_to_walls(
        self,
        openings: Sequence[OpeningInstance],
        walls: Sequence[WallInstance],
    ) -> None:
        """Bind openings to walls based on explicit target ID, envelope context, or spatial proximity.

        Mutates opening.bound_wall_id and opening.status.
        """
        wall_ids = {w.wall_id for w in walls}

        for op in openings:
            # 1. Explicit valid binding
            if op.bound_wall_id and op.bound_wall_id in wall_ids:
                continue

            # 2. Envelope binding: if exactly one external/perimeter wall exists and opening is external
            if len(walls) == 1:
                op.bound_wall_id = walls[0].wall_id
                continue

            # 3. Spatial bounding box containment if both have valid bboxes
            if op.bounding_box and len(op.bounding_box) == 4:
                ox0, oy0, ox1, oy1 = op.bounding_box
                best_wall = None
                for w in walls:
                    if w.bounding_box and len(w.bounding_box) == 4:
                        wx0, wy0, wx1, wy1 = w.bounding_box
                        # Bounding box intersection check
                        if not (ox1 < wx0 or ox0 > wx1 or oy1 < wy0 or oy0 > wy1):
                            best_wall = w.wall_id
                            break
                if best_wall:
                    op.bound_wall_id = best_wall
                    continue

            # 4. Fallback: fail-closed provisional unbound
            op.bound_wall_id = None
            op.status = OpeningDeductionStatus.PROVISIONAL_UNBOUND
            op.notes = "Opening could not be deterministically bound to any wall instance."

    def calculate_wall_deductions(
        self,
        wall: WallInstance,
        openings: Sequence[OpeningInstance],
    ) -> WallDeductionResult:
        """Calculate total opening deductions and net wall area for a specific wall.

        Enforces strict fail-closed behavior:
        - Unknown width or height -> 0.0 deduction, recorded as UNRESOLVED_MISSING_DIMENSIONS.
        - Non-positive dimensions -> 0.0 deduction, recorded as INVALID_DIMENSIONS.
        - Unbound openings -> 0.0 deduction, recorded as PROVISIONAL_UNBOUND.
        """
        applied: List[Dict[str, Any]] = []
        unresolved: List[Dict[str, Any]] = []
        unbound: List[Dict[str, Any]] = []
        total_deduction = 0.0

        for op in openings:
            if op.bound_wall_id != wall.wall_id:
                if op.bound_wall_id is None:
                    op.status = OpeningDeductionStatus.PROVISIONAL_UNBOUND
                    unbound.append(op.to_dict())
                continue

            # Fail-closed check: missing dimensions
            if op.width_m is None or op.height_m is None:
                op.status = OpeningDeductionStatus.UNRESOLVED_MISSING_DIMENSIONS
                op.notes = "Missing figured width or height; fail-closed without guessing deduction."
                unresolved.append(op.to_dict())
                continue

            # Fail-closed check: non-positive dimensions
            if op.width_m <= 0.0 or op.height_m <= 0.0 or op.quantity <= 0.0:
                op.status = OpeningDeductionStatus.INVALID_DIMENSIONS
                op.notes = "Non-positive dimension or quantity; deduction rejected."
                unresolved.append(op.to_dict())
                continue

            # Valid evidenced opening
            op.status = OpeningDeductionStatus.APPLIED
            op_area = op.total_area_m2 or 0.0
            total_deduction += op_area
            applied.append(op.to_dict())

        total_deduction = round(total_deduction, 2)
        net_area = round(max(0.0, wall.gross_area_m2 - total_deduction), 2)

        return WallDeductionResult(
            wall_id=wall.wall_id,
            gross_area_m2=round(wall.gross_area_m2, 2),
            total_deducted_area_m2=total_deduction,
            net_area_m2=net_area,
            applied_openings=applied,
            unresolved_openings=unresolved,
            unbound_openings=unbound,
        )

    def deduct_openings_for_all_walls(
        self,
        walls: Sequence[WallInstance],
        openings: Sequence[OpeningInstance],
    ) -> Dict[str, WallDeductionResult]:
        """Perform opening-to-wall binding and compute deduction results for all walls."""
        self.bind_openings_to_walls(openings, walls)
        results: Dict[str, WallDeductionResult] = {}
        for w in walls:
            results[w.wall_id] = self.calculate_wall_deductions(w, openings)
        return results

    def propagate_to_predictions(
        self,
        predictions: Sequence[Any],
        results: Dict[str, WallDeductionResult],
    ) -> List[Any]:
        """Propagate net wall area and audit metadata to walling and wall finish predictions.

        Propagates to:
        - perimeter_walling (or masonry/block walling)
        - internal_plaster
        - internal_paint
        - external_key_pointing
        - external_render
        """
        # Collect primary envelope wall deduction result (if available)
        primary_res = (
            results.get("perimeter_walling")
            or results.get("external_walling")
            or (list(results.values())[0] if results else None)
        )

        if not primary_res:
            return list(predictions)

        out_preds = []
        for p in predictions:
            p_tag = p.tag if hasattr(p, "tag") else p.get("tag", "")
            p_trade = p.trade_type if hasattr(p, "trade_type") else p.get("trade_type", "")

            is_walling = p_tag in ("perimeter_walling", "external_walling", "masonry_walling", "block_walling")
            is_wall_finish = p_tag in (
                "internal_plaster",
                "internal_paint",
                "external_key_pointing",
                "external_render",
            )

            if is_walling or is_wall_finish:
                gross_val = p.quantity if hasattr(p, "quantity") else p.get("quantity", 0.0)
                net_val = primary_res.net_area_m2

                meta = p.metadata if hasattr(p, "metadata") else p.get("metadata", {})
                meta["gross_area_m2"] = primary_res.gross_area_m2
                meta["total_deducted_opening_area_m2"] = primary_res.total_deducted_area_m2
                meta["net_area_m2"] = net_val
                meta["applied_openings"] = primary_res.applied_openings
                meta["unresolved_openings"] = primary_res.unresolved_openings
                meta["unbound_openings"] = primary_res.unbound_openings

                if hasattr(p, "quantity"):
                    p.quantity = net_val
                    p.metadata = meta
                    out_preds.append(p)
                else:
                    p["quantity"] = net_val
                    p["metadata"] = meta
                    out_preds.append(p)
            else:
                out_preds.append(p)

        return out_preds
