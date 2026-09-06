"""pb_geometry_takeoff_model.py — PlanReader Geometry and Measurement Authority Model.

Defines standardized geometry objects, measurement authority types, wall takeoff
formulas, figured-dimension precedence, opening deductions, and finish tag mapping.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import math
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Measurement Authority Types
# ---------------------------------------------------------------------------

class MeasurementAuthorityType(str, Enum):
    DOCUMENTED_DIMENSION = "documented_dimension"
    SCHEDULE_EXTRACTED = "schedule_extracted"
    PDF_SCALED = "pdf_scaled"
    AI_DETECTED = "ai_detected"
    USER_CORRECTED = "user_corrected"
    USER_APPROVED = "user_approved"
    MODEL_DERIVED = "model_derived"
    PROVISIONAL = "provisional"
    EXCLUDED = "excluded"
    REFERENCE_ONLY = "reference_only"


class AuthorityStatus(str, Enum):
    FIRM = "firm"
    PROVISIONAL = "provisional"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    EXCLUDED = "excluded"
    REFERENCE_ONLY = "reference_only"


@dataclass
class MeasurementRecord:
    """Standard measurement contract carrying full traceable authority."""
    value: float
    unit: str  # "m", "m2", "m3", "ea", "mm"
    source_type: str  # from MeasurementAuthorityType
    confidence: float
    sheet: str
    page: int
    scale: str
    geometry_ref: str
    authority_status: str  # from AuthorityStatus
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    scaled_delta_mm: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError(f"Measurement value must be finite, got {self.value}")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Standard Geometry Domain Model Objects
# ---------------------------------------------------------------------------

@dataclass
class RevisionRef:
    revision_id: str
    hash: str
    description: str
    timestamp: str


@dataclass
class ScaleCalibration:
    page_no: int
    ratio_str: str  # "1:50", "1:100", "1:200", "UNKNOWN"
    px_per_m: float
    method: str  # "KNOWN_CALIBRATED", "GRAPHIC_SCALE_BAR", "OCR_TEXT", "UNKNOWN"
    is_verified: bool
    confidence: float
    sheet_label: str = ""
    scale_text: str = ""
    source_type: str = "unknown"  # from pb_page_scale_calibration_authority.ScaleSourceType
    status: str = "unknown"  # from pb_page_scale_calibration_authority.ScaleCalibrationStatus
    issues: List[str] = field(default_factory=list)
    revision_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    def is_usable_for_firm_measurement(self) -> bool:
        return self.is_verified and self.px_per_m > 0.0 and math.isfinite(self.px_per_m)


@dataclass
class PlanPage:
    page_id: int
    page_no: int
    sheet_label: str
    canonical_role: str
    scale_calibration: Optional[ScaleCalibration] = None
    revision_ref: Optional[RevisionRef] = None


@dataclass
class Opening:
    opening_id: str
    opening_type: str  # "door", "window", "skylight", "void"
    width_m: float
    height_m: float
    area_m2: float
    coordinates: List[Tuple[float, float]] = field(default_factory=list)
    deducts: bool = True
    authority: Optional[MeasurementRecord] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.width_m) or not math.isfinite(self.height_m) or not math.isfinite(self.area_m2):
            raise ValueError("Opening dimensions must be finite numbers")
        if self.width_m < 0.0 or self.height_m < 0.0 or self.area_m2 < 0.0:
            raise ValueError("Opening dimensions and area cannot be negative")


@dataclass
class Door:
    opening: Opening
    door_code: str
    paint_treatment: str
    is_entry: bool = False
    is_excluded: bool = False

    @property
    def area_m2(self) -> float:
        return self.opening.area_m2


@dataclass
class Window:
    opening: Opening
    window_code: str
    glazing_type: str = "clear"
    is_obscure: bool = False

    @property
    def area_m2(self) -> float:
        return self.opening.area_m2


@dataclass
class WallSegment:
    wall_id: str
    length_m: float
    height_m: float
    gross_area_m2: float
    net_area_m2: float
    openings: List[Opening] = field(default_factory=list)
    start_pt: Tuple[float, float] = (0.0, 0.0)
    end_pt: Tuple[float, float] = (0.0, 0.0)
    figured_dimension_mm: Optional[float] = None
    scaled_delta_mm: Optional[float] = None
    authority: Optional[MeasurementRecord] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.length_m) or not math.isfinite(self.height_m):
            raise ValueError("Wall dimensions must be finite numbers")
        if self.length_m < 0.0 or self.height_m < 0.0:
            raise ValueError("Wall dimensions cannot be negative")


@dataclass
class Room:
    room_id: str
    room_name: str
    floor_area_m2: float
    perimeter_m: float
    ceiling_height_m: float
    wall_ids: List[str] = field(default_factory=list)
    authority: Optional[MeasurementRecord] = None


@dataclass
class Surface:
    surface_id: str
    surface_type: str  # "internal_wall", "external_facade", "ceiling", "soffit"
    substrate: str
    finish_tag: str
    gross_area_m2: float
    deduction_area_m2: float
    net_area_m2: float
    authority: Optional[MeasurementRecord] = None


@dataclass
class Ceiling:
    ceiling_id: str
    room_name: str
    area_m2: float
    void_deductions_m2: float
    net_area_m2: float
    rcp_sheet: str
    authority: Optional[MeasurementRecord] = None


@dataclass
class FloorArea:
    floor_id: str
    level_name: str
    gfa_m2: float
    internal_area_m2: float
    authority: Optional[MeasurementRecord] = None


@dataclass
class ElevationSurface:
    elevation_id: str
    facade_side: str  # "East", "West", "North", "South"
    block: str
    finish_tag: str
    gross_area_m2: float
    deduction_area_m2: float
    net_area_m2: float
    authority: Optional[MeasurementRecord] = None


@dataclass
class Soffit:
    soffit_id: str
    location: str
    area_m2: float
    finish_tag: str
    authority: Optional[MeasurementRecord] = None


@dataclass
class ExclusionZone:
    exclusion_id: str
    reason: str
    coordinates: List[Tuple[float, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Wall Takeoff Formulas & Deduction Invariants
# ---------------------------------------------------------------------------

def calculate_wall_takeoff(
    length_m: float,
    height_m: float,
    openings: Optional[List[Opening]] = None,
    standard: str = "AS4041",
    deduction_threshold_m2: float = 0.5,
) -> Tuple[float, float, float]:
    """Calculate gross wall area, opening deductions, and net wall area.

    Invariants:
      1. length_m > 0 and height_m > 0, strictly finite numbers.
      2. gross_area = length_m * height_m.
      3. Openings > deduction_threshold_m2 (0.5 m² under AS 4041) deduct.
      4. Openings <= 0.5 m² do not deduct unless deducts=True explicitly.
      5. Total opening deductions cannot exceed gross wall area.
      6. net_area = gross_area - total_deductions >= 0.0.
    """
    if not math.isfinite(length_m) or not math.isfinite(height_m):
        raise ValueError("Wall length and height must be finite numbers")
    if length_m <= 0.0 or height_m <= 0.0:
        raise ValueError("Wall length and height must be strictly positive")

    gross_area = round(length_m * height_m, 4)
    total_deductions = 0.0

    if openings:
        for op in openings:
            if not math.isfinite(op.area_m2) or op.area_m2 < 0.0:
                raise ValueError(f"Invalid opening area: {op.area_m2}")

            # AS 4041 Australian Takeoff Standard rule
            if op.deducts and (op.area_m2 > deduction_threshold_m2 or standard != "AS4041"):
                total_deductions += op.area_m2

    total_deductions = round(total_deductions, 4)

    if total_deductions > gross_area:
        raise ValueError(
            f"Total opening deductions ({total_deductions} m²) exceed gross wall area ({gross_area} m²)"
        )

    net_area = round(gross_area - total_deductions, 4)
    return gross_area, total_deductions, net_area


# ---------------------------------------------------------------------------
# Figured Dimension vs Scaled Geometry Precedence
# ---------------------------------------------------------------------------

def reconcile_figured_and_scaled(
    figured_mm: Optional[float],
    scaled_mm: Optional[float],
    max_delta_ratio: float = 0.05,
) -> Tuple[float, str, Optional[float], str]:
    """Apply the precedence rule: Figured dimensions beat scaled geometry.

    Returns:
        (resolved_length_m: float, authority_status: str, scaled_delta_mm: Optional[float], notes: str)
    """
    if figured_mm is not None and math.isfinite(figured_mm) and figured_mm > 0.0:
        length_m = round(figured_mm / 1000.0, 4)
        if scaled_mm is not None and math.isfinite(scaled_mm) and scaled_mm > 0.0:
            delta_mm = round(abs(figured_mm - scaled_mm), 2)
            delta_ratio = delta_mm / figured_mm
            if delta_ratio > max_delta_ratio:
                return (
                    length_m,
                    AuthorityStatus.REVIEW_REQUIRED.value,
                    delta_mm,
                    f"Warning: Large discrepancy ({delta_mm}mm, {delta_ratio*100:.1f}%) between figured dimension and scaled geometry",
                )
            return (
                length_m,
                AuthorityStatus.FIRM.value,
                delta_mm,
                f"Figured dimension precedence applied (scaled delta: {delta_mm}mm)",
            )
        return (
            length_m,
            AuthorityStatus.FIRM.value,
            None,
            "Figured dimension applied without scaled comparison",
        )

    if scaled_mm is not None and math.isfinite(scaled_mm) and scaled_mm > 0.0:
        length_m = round(scaled_mm / 1000.0, 4)
        return (
            length_m,
            AuthorityStatus.PROVISIONAL.value,
            None,
            "Scaled geometry applied as provisional (no figured dimension available)",
        )

    raise ValueError("Neither figured dimension nor scaled geometry provided")


# ---------------------------------------------------------------------------
# Finish Tag Database & Classification
# ---------------------------------------------------------------------------

@dataclass
class FinishTagRecord:
    tag: str
    description: str
    paintable_status: str  # "PAINTABLE_INCLUDED", "EXCLUDED_FACTORY", "PROVISIONAL_RENDER", "REVIEW_REQUIRED"
    substrate: str
    scope_disposition: str  # "included", "excluded", "provisional", "review_required"
    notes: str


KNOWN_FINISH_TAGS: Dict[str, FinishTagRecord] = {
    # External Cladding & Finishes
    "EC01": FinishTagRecord("EC01", "NRG Greenboard External Wall", "PAINTABLE_INCLUDED", "EIFS / Greenboard", "included", "External paint system Dulux Light Rice"),
    "EC02": FinishTagRecord("EC02", "JH Fine Texture Cladding", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "External paint system Dulux Light Rice"),
    "EC03": FinishTagRecord("EC03", "James Hardie EasyLap Cladding", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "External paint system Lexicon Half"),
    "EC04": FinishTagRecord("EC04", "FC Feature Cladding", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "External feature cladding Dulux Colorbond Monument"),
    "EC1": FinishTagRecord("EC1", "External Cladding Type 1", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "Paintable external cladding"),
    "EC2": FinishTagRecord("EC2", "External Cladding Type 2", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "Paintable external cladding"),
    "EC3": FinishTagRecord("EC3", "External Cladding Type 3", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "Paintable external cladding"),
    "EC4": FinishTagRecord("EC4", "External Cladding Type 4", "PAINTABLE_INCLUDED", "Fibre Cement", "included", "Paintable external cladding"),
    "XF01": FinishTagRecord("XF01", "External Finish Dulux Lexicon Half", "PAINTABLE_INCLUDED", "FC Cladding", "included", "Paintable external finish"),
    "XF02": FinishTagRecord("XF02", "External Finish Dulux Light Rice", "PAINTABLE_INCLUDED", "Greenboard", "included", "Paintable external finish"),
    "XF03": FinishTagRecord("XF03", "External Feature Dulux Monument", "PAINTABLE_INCLUDED", "FC Feature", "included", "Paintable feature finish"),
    "XP01": FinishTagRecord("XP01", "External Paint Standard", "PAINTABLE_INCLUDED", "Substrate as noted", "included", "External paint system"),

    # Render & Bagged Masonry (Provisional pending specific finish specification)
    "RBL": FinishTagRecord("RBL", "Render / Bagged Linework", "PROVISIONAL_RENDER", "Masonry Render", "provisional", "Provisional until verified in finishes schedule"),

    # Plasterboard & Internal Finishes
    "P": FinishTagRecord("P", "Internal Paint Standard", "PAINTABLE_INCLUDED", "Plasterboard", "included", "Internal walls and ceilings"),
    "PB01": FinishTagRecord("PB01", "Plasterboard Walls Paint Finish", "PAINTABLE_INCLUDED", "Plasterboard", "included", "Internal walls"),
    "PB02": FinishTagRecord("PB02", "Plasterboard Ceilings Paint Finish", "PAINTABLE_INCLUDED", "Plasterboard", "included", "Internal ceilings"),
    "PB04": FinishTagRecord("PB04", "Plasterboard Wet Area Paint Finish", "PAINTABLE_INCLUDED", "Villaboard", "included", "Wet areas"),
    "PB05": FinishTagRecord("PB05", "Bulkhead Paint Finish", "PAINTABLE_INCLUDED", "Plasterboard", "included", "Bulkheads and drops"),
    "SHD": FinishTagRecord("SHD", "Sheet Lining", "PAINTABLE_INCLUDED", "FC Sheet", "included", "Internal sheet lining"),

    # Excluded Items (Factory finishes, metal, non-paintable)
    "SL": FinishTagRecord("SL", "Joint Sealant / Mastic", "EXCLUDED_FACTORY", "Polyurethane", "excluded", "Caulking / sealant non-paint scope"),
    "SCR": FinishTagRecord("SCR", "Floor Screed", "EXCLUDED_FACTORY", "Cement Screed", "excluded", "Tiling / floor trade scope"),
    "PPT": FinishTagRecord("PPT", "Pre-painted Timber", "EXCLUDED_FACTORY", "Factory Finished Timber", "excluded", "Factory pre-finished substrate"),
    "COLORBOND": FinishTagRecord("COLORBOND", "Colorbond Steel", "EXCLUDED_FACTORY", "Pre-finished Steel", "excluded", "Factory pre-finished roofing / gutter"),
    "ALUM": FinishTagRecord("ALUM", "Aluminium Window Frame", "EXCLUDED_FACTORY", "Powdercoated Aluminium", "excluded", "Factory powdercoated joinery"),
}


def classify_finish_tag(tag: str) -> FinishTagRecord:
    """Classify a finish tag into paintable scope disposition."""
    norm = tag.strip().upper()
    if norm in KNOWN_FINISH_TAGS:
        return KNOWN_FINISH_TAGS[norm]

    # Keyword heuristics for factory powdercoat or colorbond
    if any(k in norm for k in ["COLORBOND", "MONUMENT ROOF", "GUTTER", "FASCIA"]):
        return FinishTagRecord(norm, "Colorbond / Metal", "EXCLUDED_FACTORY", "Metal", "excluded", "Factory pre-finished metal")
    if any(k in norm for k in ["POWDERCOAT", "ANODISED", "GLAZING", "GLASS"]):
        return FinishTagRecord(norm, "Glazing / Powdercoat", "EXCLUDED_FACTORY", "Aluminium / Glass", "excluded", "Factory finish joinery")

    # Unknown tag fails closed to review_required
    return FinishTagRecord(
        tag=tag,
        description="Unrecognised Finish Tag",
        paintable_status="REVIEW_REQUIRED",
        substrate="Unknown",
        scope_disposition="review_required",
        notes="Unrecognised finish tag requires estimator manual confirmation",
    )
