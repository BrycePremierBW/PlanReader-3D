"""pb_editable_3d_model.py — PlanReader Editable 3D Correction Workflow & Data Model.

Implements:
  1. Complete 2D-to-3D hierarchical data model:
     BuildingModel -> LevelModel -> UnitModel, RoomModel, WallModel, OpeningModel, SurfaceModel, RoofModel, SoffitModel.
  2. Strict traceability: All 3D objects maintain bidirectional links to source PDF page,
     scale calibration, figured dimension, and revision hash. No orphan 3D geometry can become commercial.
  3. Commercial Wall Height Authority: Enforces height precedence and fail-closed rules
     (documented/user-approved height may publish; model-estimated is provisional; unknown height blocks publication;
     raked/stair walls require review).
  4. Correction Event Pipeline: Structured event logging (CorrectionEvent), dynamic quantity
     recalculation, authority transitions (user_corrected, user_approved), revision hashing, and
     preflight staleness invalidation.
  5. Massing preview generator from extracted level polygons.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from pb_geometry_takeoff_model import (
    AuthorityStatus,
    MeasurementAuthorityType,
    MeasurementRecord,
    Opening,
    calculate_wall_takeoff,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WallHeightAuthority(str, Enum):
    DOCUMENTED_CEILING_HEIGHT = "documented_ceiling_height"
    FIGURED_DIMENSION = "figured_dimension"
    SECTION_DERIVED = "section_derived"
    SCHEDULE_DERIVED = "schedule_derived"
    MODEL_ESTIMATED = "model_estimated"
    USER_ENTERED = "user_entered"
    USER_APPROVED = "user_approved"
    RAKED_WALL = "raked_wall"
    STAIR_WALL = "stair_wall"
    UNKNOWN_HEIGHT = "unknown_height"


def resolve_wall_height_from_figured_dimension(text: str) -> float:
    """Convert figured-dimension height text (e.g. "2700mm", "2.7m") to metres.

    Reuses pb_figured_dimension_authority's already-validated parser rather than
    reimplementing unit parsing — malformed/negative/zero/non-finite text raises
    DimensionParseError, same as any other figured dimension in the codebase.
    """
    from pb_figured_dimension_authority import parse_figured_dimension_mm
    return parse_figured_dimension_mm(text) / 1000.0


class CorrectionAction(str, Enum):
    MOVE_WALL = "move_wall"
    SPLIT_WALL = "split_wall"
    MERGE_WALL = "merge_wall"
    DELETE_WALL = "delete_wall"
    ADD_WALL = "add_wall"
    ASSIGN_ROOM = "assign_room"
    CHANGE_HEIGHT = "change_height"
    ADD_OPENING = "add_opening"
    DELETE_OPENING = "delete_opening"
    CHANGE_FINISH = "change_finish"
    EXCLUDE_ITEM = "exclude_item"
    APPROVE_QUANTITY = "approve_quantity"
    REJECT_QUANTITY = "reject_quantity"


# ---------------------------------------------------------------------------
# 2D-to-3D Domain Objects
# ---------------------------------------------------------------------------

@dataclass
class FinishModel:
    finish_id: str
    tag: str
    description: str
    trade_scope: str  # "paintable_included", "excluded_factory", "provisional_render"
    substrate: str = "Plasterboard"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OpeningModel:
    opening_id: str
    wall_id: str
    opening_type: str  # "door", "window", "void"
    width_m: float
    height_m: float
    area_m2: float
    deducts: bool = True
    source_page_no: int = 1
    source_sheet_label: str = ""
    approval_status: str = AuthorityStatus.PROVISIONAL.value
    revision_hash: str = ""
    # Real recorded position along the wall (offset_x_m, from its start_pt) and
    # vertically from the wall base (offset_z_m) — None means "not recorded",
    # never a guessed position (PR D.11C).
    offset_x_m: Optional[float] = None
    offset_z_m: Optional[float] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.width_m) or not math.isfinite(self.height_m) or not math.isfinite(self.area_m2):
            raise ValueError("Opening dimensions must be finite numbers")
        if self.width_m < 0.0 or self.height_m < 0.0 or self.area_m2 < 0.0:
            raise ValueError("Opening dimensions cannot be negative")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SurfaceModel:
    surface_id: str
    wall_id: str
    face: str  # "internal", "external", "top", "bottom"
    substrate: str
    finish_tag: str
    area_m2: float
    authority_status: str = AuthorityStatus.PROVISIONAL.value
    approved_by: Optional[str] = None
    revision_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WallModel:
    wall_id: str
    level_id: str
    start_pt: Tuple[float, float]
    end_pt: Tuple[float, float]
    length_m: float
    height_m: float
    height_authority: str  # WallHeightAuthority
    wall_type: str = "standard"  # "standard", "raked", "stair", "parapet"
    height_start_m: Optional[float] = None
    height_end_m: Optional[float] = None
    gross_area_m2: float = 0.0
    net_area_m2: float = 0.0
    openings: List[OpeningModel] = field(default_factory=list)
    surfaces: List[SurfaceModel] = field(default_factory=list)
    source_page_no: int = 1
    source_sheet_label: str = ""
    height_source_sheet: Optional[str] = None
    height_source_level: Optional[str] = None
    scale_ratio: str = "1:100"
    authority_status: str = AuthorityStatus.PROVISIONAL.value
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    revision_hash: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.length_m) or not math.isfinite(self.height_m):
            raise ValueError("Wall dimensions must be finite numbers")
        if self.length_m < 0.0 or self.height_m < 0.0:
            raise ValueError("Wall dimensions cannot be negative")
        self.recalculate_areas()

    def _has_valid_raked_trapezoid(self) -> bool:
        """True only when both endpoint heights are present and give a real
        trapezoid calculation to work with — not a guess."""
        if self.wall_type != "raked":
            return False
        if self.height_start_m is None or self.height_end_m is None:
            return False
        for v in (self.height_start_m, self.height_end_m):
            if not math.isfinite(v) or v <= 0.0:
                return False
        return True

    def _enforce_height_authority(self) -> None:
        """height_authority sets a ceiling on authority_status, not just a label —
        a caller can always request something more conservative, but can never
        claim firm commercial authority for a height source that doesn't support it.
        """
        if self.height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value:
            # An unknown height source is untrustworthy regardless of whether the
            # numeric height_m value itself happens to look plausible.
            self.gross_area_m2 = 0.0
            self.net_area_m2 = 0.0
            self.authority_status = AuthorityStatus.BLOCKED.value
            self.compute_revision_hash()
            return

        if (
            self.height_authority == WallHeightAuthority.MODEL_ESTIMATED.value
            and self.authority_status == AuthorityStatus.FIRM.value
            and not self.approved_by
        ):
            # A model estimate alone can never claim firm — but an explicit
            # approver (a human overriding the estimate) may promote it, same as
            # the raked/stair guard below.
            self.authority_status = AuthorityStatus.PROVISIONAL.value
            self.compute_revision_hash()

        # A raked wall with both endpoint heights documented gets a genuine
        # trapezoid calculation (see recalculate_areas) — the formula now actually
        # matches the geometry, so it's governed by height_authority like any other
        # wall, not force-downgraded. Without real endpoint data (or for stair
        # walls, which have no formula at all yet), the flat-formula estimate can
        # still never silently claim firm authority on its own.
        needs_guard = self.wall_type == "stair" or (self.wall_type == "raked" and not self._has_valid_raked_trapezoid())
        if (
            needs_guard
            and self.authority_status == AuthorityStatus.FIRM.value
            and not self.approved_by
        ):
            self.authority_status = AuthorityStatus.REVIEW_REQUIRED.value
            self.compute_revision_hash()

    def recalculate_areas(self) -> None:
        """Recalculate gross and net wall area based on AS 4041 opening rules."""
        if self._has_valid_raked_trapezoid():
            # Trapezoid: area = length * average(height_start, height_end). The
            # average height is also a correct, real height_m for AS4041 opening
            # deduction purposes (calculate_wall_takeoff deducts by each opening's
            # own area_m2, not by re-deriving it from height_m).
            self.height_m = (self.height_start_m + self.height_end_m) / 2.0

        if self.length_m <= 0.0 or self.height_m <= 0.0:
            self.gross_area_m2 = 0.0
            self.net_area_m2 = 0.0
            self._enforce_height_authority()
            return

        op_objs = [
            Opening(
                opening_id=op.opening_id,
                opening_type=op.opening_type,
                width_m=op.width_m,
                height_m=op.height_m,
                area_m2=op.area_m2,
                deducts=op.deducts,
            )
            for op in self.openings
        ]
        gross, _, net = calculate_wall_takeoff(
            length_m=self.length_m,
            height_m=self.height_m,
            openings=op_objs,
        )
        self.gross_area_m2 = gross
        self.net_area_m2 = net
        self.compute_revision_hash()
        self._enforce_height_authority()

    def compute_revision_hash(self) -> str:
        s = f"{self.wall_id}:{self.length_m}:{self.height_m}:{self.gross_area_m2}:{self.net_area_m2}:{self.authority_status}"
        self.revision_hash = hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
        return self.revision_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "level_id": self.level_id,
            "start_pt": list(self.start_pt),
            "end_pt": list(self.end_pt),
            "length_m": round(self.length_m, 4),
            "height_m": round(self.height_m, 4),
            "height_authority": self.height_authority,
            "height_start_m": round(self.height_start_m, 4) if self.height_start_m is not None else None,
            "height_end_m": round(self.height_end_m, 4) if self.height_end_m is not None else None,
            "wall_type": self.wall_type,
            "gross_area_m2": round(self.gross_area_m2, 4),
            "net_area_m2": round(self.net_area_m2, 4),
            "openings": [op.to_dict() for op in self.openings],
            "surfaces": [sf.to_dict() for sf in self.surfaces],
            "source_page_no": self.source_page_no,
            "source_sheet_label": self.source_sheet_label,
            "height_source_sheet": self.height_source_sheet,
            "height_source_level": self.height_source_level,
            "scale_ratio": self.scale_ratio,
            "authority_status": self.authority_status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "revision_hash": self.revision_hash,
        }


@dataclass
class RoomModel:
    room_id: str
    level_id: str
    name: str
    floor_area_m2: float
    perimeter_m: float
    wall_ids: List[str] = field(default_factory=list)
    finish_tag: str = "PB01"
    source_page_no: int = 1
    source_sheet_label: str = ""
    authority_status: str = AuthorityStatus.PROVISIONAL.value
    revision_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnitModel:
    unit_id: str
    unit_number: str
    level_id: str
    gfa_m2: float
    room_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RoofModel:
    roof_id: str
    roof_type: str
    pitch_deg: float
    area_m2: float
    finish_tag: str = "COLORBOND"
    authority_status: str = AuthorityStatus.EXCLUDED.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SoffitModel:
    soffit_id: str
    level_id: str
    location: str
    area_m2: float
    finish_tag: str = "EC02"
    authority_status: str = AuthorityStatus.PROVISIONAL.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LevelModel:
    level_id: str
    name: str
    elevation_m: float
    ceiling_height_m: float
    units: List[UnitModel] = field(default_factory=list)
    rooms: List[RoomModel] = field(default_factory=list)
    walls: List[WallModel] = field(default_factory=list)
    soffits: List[SoffitModel] = field(default_factory=list)
    boundary_polygon: List[Tuple[float, float]] = field(default_factory=list)
    source_sheet_label: str = ""
    revision_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level_id": self.level_id,
            "name": self.name,
            "elevation_m": round(self.elevation_m, 3),
            "ceiling_height_m": round(self.ceiling_height_m, 3),
            "units": [u.to_dict() for u in self.units],
            "rooms": [r.to_dict() for r in self.rooms],
            "walls": [w.to_dict() for w in self.walls],
            "soffits": [s.to_dict() for s in self.soffits],
            "boundary_polygon": [list(pt) for pt in self.boundary_polygon],
            "source_sheet_label": self.source_sheet_label,
            "revision_hash": self.revision_hash,
        }


@dataclass
class BuildingModel:
    building_id: str
    name: str
    levels: List[LevelModel] = field(default_factory=list)
    roofs: List[RoofModel] = field(default_factory=list)
    revision_hash: str = ""
    source_sheet: str = ""

    def compute_building_revision_hash(self) -> str:
        level_hashes = [lvl.revision_hash for lvl in self.levels]
        raw = f"{self.building_id}:{self.name}:" + ":".join(level_hashes)
        self.revision_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return self.revision_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_id": self.building_id,
            "name": self.name,
            "levels": [lvl.to_dict() for lvl in self.levels],
            "roofs": [r.to_dict() for r in self.roofs],
            "revision_hash": self.revision_hash,
            "source_sheet": self.source_sheet,
        }


# ---------------------------------------------------------------------------
# Correction Event Pipeline
# ---------------------------------------------------------------------------

@dataclass
class CorrectionEvent:
    correction_id: str
    object_id: str
    object_type: str  # "wall", "opening", "room", "level"
    action: str  # CorrectionAction
    field_name: str
    old_value: Any
    new_value: Any
    reason: str
    actor: str = "Bryce Curran"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "3d_editor"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuantityRecalculation:
    object_id: str
    object_type: str
    old_gross_m2: float
    new_gross_m2: float
    old_net_m2: float
    new_net_m2: float
    authority_status: str
    is_preflight_invalidated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def apply_correction_event(
    building: BuildingModel,
    event: CorrectionEvent,
) -> Tuple[BuildingModel, List[QuantityRecalculation]]:
    """Apply a user correction event to the 3D model, recalculating quantities and updating authority.

    Guarantees:
      1. A geometry correction (CHANGE_HEIGHT, MOVE_WALL, ADD_OPENING, ...) always
         leaves the object at REVIEW_REQUIRED with no approver — correction is not
         approval, so it never sets FIRM/approved_by/approved_at itself, and it
         clears any prior approval the object held (a further correction always
         demands re-review, even of previously-approved geometry).
      2. Only an explicit APPROVE_QUANTITY event can set FIRM + approved_by +
         approved_at; REJECT_QUANTITY clears both back out.
      3. Quantities are dynamically recalculated with AS 4041 opening rules.
      4. Object, level, and building revision hashes mutate.
      5. Preflight is explicitly marked invalidated/stale.
    """
    recalculations: List[QuantityRecalculation] = []

    for level in building.levels:
        for wall in level.walls:
            if wall.wall_id == event.object_id:
                old_gross = wall.gross_area_m2
                old_net = wall.net_area_m2

                # Apply action
                if event.action == CorrectionAction.CHANGE_HEIGHT.value:
                    val = float(event.new_value)
                    if not math.isfinite(val) or val <= 0.0:
                        raise ValueError(f"Wall height must be positive finite number, got {val}")
                    wall.height_m = val
                    wall.height_authority = WallHeightAuthority.USER_ENTERED.value
                    wall.authority_status = AuthorityStatus.REVIEW_REQUIRED.value
                    wall.approved_by = None
                    wall.approved_at = None

                elif event.action == CorrectionAction.MOVE_WALL.value:
                    # new_value should be (length_m, (start_pt, end_pt)) or length_m
                    if isinstance(event.new_value, (int, float)):
                        wall.length_m = float(event.new_value)
                    elif isinstance(event.new_value, (list, tuple)) and len(event.new_value) >= 3:
                        wall.length_m = float(event.new_value[0])
                        wall.start_pt = tuple(event.new_value[1])
                        wall.end_pt = tuple(event.new_value[2])
                    wall.authority_status = AuthorityStatus.REVIEW_REQUIRED.value
                    wall.approved_by = None
                    wall.approved_at = None

                elif event.action == CorrectionAction.ADD_OPENING.value:
                    # new_value is an OpeningModel or dict
                    if isinstance(event.new_value, OpeningModel):
                        wall.openings.append(event.new_value)
                    elif isinstance(event.new_value, dict):
                        wall.openings.append(
                            OpeningModel(
                                opening_id=event.new_value["opening_id"],
                                wall_id=wall.wall_id,
                                opening_type=event.new_value.get("opening_type", "door"),
                                width_m=float(event.new_value["width_m"]),
                                height_m=float(event.new_value["height_m"]),
                                area_m2=float(event.new_value.get("area_m2", event.new_value["width_m"] * event.new_value["height_m"])),
                                deducts=event.new_value.get("deducts", True),
                                approval_status=AuthorityStatus.REVIEW_REQUIRED.value,
                            )
                        )
                    wall.authority_status = AuthorityStatus.REVIEW_REQUIRED.value
                    wall.approved_by = None
                    wall.approved_at = None

                elif event.action == CorrectionAction.APPROVE_QUANTITY.value:
                    # Same source-trace floor as approve_corrected_geometry() (D.2):
                    # untraceable geometry can never become commercial, regardless
                    # of which approval path is used to grant FIRM authority.
                    if not wall.source_sheet_label:
                        raise ValueError(
                            f"Cannot approve {wall.wall_id!r}: missing source_sheet_label trace"
                        )
                    wall.authority_status = AuthorityStatus.FIRM.value
                    wall.approved_by = event.actor
                    wall.approved_at = datetime.now(timezone.utc).isoformat()

                elif event.action == CorrectionAction.REJECT_QUANTITY.value:
                    wall.authority_status = AuthorityStatus.REVIEW_REQUIRED.value
                    wall.approved_by = None
                    wall.approved_at = None

                # Recalculate
                wall.recalculate_areas()
                recalculations.append(
                    QuantityRecalculation(
                        object_id=wall.wall_id,
                        object_type="wall",
                        old_gross_m2=old_gross,
                        new_gross_m2=wall.gross_area_m2,
                        old_net_m2=old_net,
                        new_net_m2=wall.net_area_m2,
                        authority_status=wall.authority_status,
                        is_preflight_invalidated=True,
                    )
                )

                # Mutate level revision hash
                wall_hashes = [w.revision_hash for w in level.walls]
                level.revision_hash = hashlib.sha256(":".join(wall_hashes).encode("utf-8")).hexdigest()[:16]

    # Mutate building hash
    building.compute_building_revision_hash()
    return building, recalculations


def _find_wall(building: BuildingModel, wall_id: str) -> Tuple[Optional["WallModel"], Optional["LevelModel"]]:
    for level in building.levels:
        for wall in level.walls:
            if wall.wall_id == wall_id:
                return wall, level
    return None, None


def approve_corrected_geometry(
    building: BuildingModel,
    object_id: str,
    current_revision_hash: str,
    approved_by: str,
    approved_at: Optional[str] = None,
) -> BuildingModel:
    """Explicitly approve a wall at a specific revision — the only way this module
    ever sets authority_status=FIRM alongside approved_by/approved_at.

    This is deliberately a separate act from apply_correction_event(): a correction
    never approves itself. Approval must target the exact revision it was reviewed
    against, so it fails closed (ValueError) if:
      - object_id/approved_by/current_revision_hash are missing,
      - the object cannot be found in the building,
      - the object's current revision_hash no longer matches current_revision_hash
        (a further correction landed since this revision was reviewed),
      - the object has no recorded source_sheet_label (untraceable geometry cannot
        be approved for commercial release).
    """
    if not object_id:
        raise ValueError("object_id is required to approve corrected geometry")
    if not approved_by:
        raise ValueError("approved_by is required to approve corrected geometry")
    if not current_revision_hash:
        raise ValueError("current_revision_hash is required to approve corrected geometry")

    wall, level = _find_wall(building, object_id)
    if wall is None:
        raise ValueError(f"Unknown object_id: {object_id!r} not found in building")

    if wall.revision_hash != current_revision_hash:
        raise ValueError(
            f"Cannot approve stale revision for {object_id!r}: object is at "
            f"{wall.revision_hash!r}, approval targets {current_revision_hash!r}"
        )

    if not wall.source_sheet_label:
        raise ValueError(f"Cannot approve {object_id!r}: missing source_sheet_label trace")

    wall.authority_status = AuthorityStatus.FIRM.value
    wall.approved_by = approved_by
    wall.approved_at = approved_at or datetime.now(timezone.utc).isoformat()

    # Approval changes authority_status, which is part of the wall's hash input, so
    # it deliberately produces a new hash: "approved at this exact geometry state"
    # is itself a distinct, traceable revision from "corrected but unreviewed".
    wall.compute_revision_hash()
    wall_hashes = [w.revision_hash for w in level.walls]
    level.revision_hash = hashlib.sha256(":".join(wall_hashes).encode("utf-8")).hexdigest()[:16]
    building.compute_building_revision_hash()

    return building


# ---------------------------------------------------------------------------
# 3D Massing Preview Generator
# ---------------------------------------------------------------------------

def generate_massing_model_from_levels(levels: List[LevelModel]) -> Dict[str, Any]:
    """Generate lightweight 3D massing preview mesh from level boundary footprints."""
    meshes: List[Dict[str, Any]] = []
    total_volume_m3 = 0.0
    total_facade_m2 = 0.0

    for idx, lvl in enumerate(levels):
        pts = lvl.boundary_polygon
        if len(pts) < 3:
            continue

        base_z = lvl.elevation_m
        top_z = base_z + lvl.ceiling_height_m

        # Compute 2D footprint area and perimeter
        shoelace = 0.0
        perim = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            shoelace += (x1 * y2) - (x2 * y1)
            dx = x2 - x1
            dy = y2 - y1
            perim += math.sqrt(dx * dx + dy * dy)

        area_m2 = round(abs(shoelace) / 2.0, 3)
        vol_m3 = round(area_m2 * lvl.ceiling_height_m, 3)
        facade_m2 = round(perim * lvl.ceiling_height_m, 3)

        total_volume_m3 += vol_m3
        total_facade_m2 += facade_m2

        meshes.append({
            "level_id": lvl.level_id,
            "level_name": lvl.name,
            "base_elevation_m": base_z,
            "top_elevation_m": top_z,
            "floor_area_m2": area_m2,
            "facade_area_m2": facade_m2,
            "volume_m3": vol_m3,
            "vertices_count": len(pts) * 2,
            "faces_count": len(pts) + 2,
            "is_generated_massing": True,
            "is_source_render_sheet": False,
        })

    return {
        "massing_levels_count": len(meshes),
        "total_volume_m3": round(total_volume_m3, 2),
        "total_facade_m2": round(total_facade_m2, 2),
        "meshes": meshes,
        "is_generated_preview": True,
        "authority_status": AuthorityStatus.PROVISIONAL.value,
    }
