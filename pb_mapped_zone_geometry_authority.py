"""PlanReader Mapped-Zone Geometry Authority.

Enforces geometric authority for Plan Mapper zones and measurements:
1. Real polygon and compound geometry (L-shapes, stepped shapes, internal voids)
   is preserved and calculated with true net shoelace area.
2. An L-shaped, stepped, or internally voided area never becomes a rectangular
   bounding-box quantity marked Measured.
3. Approximations are classified as Provisional/REVIEW so they cannot enter firm pricing.
4. Measured is permitted ONLY when an evidence-backed exact rectangle is proven.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def parse_point_sequence(raw_points: Any) -> List[Tuple[float, float]]:
    """Parse a sequence of points into [(x, y), ...], sanitizing non-finite values."""
    if not isinstance(raw_points, (list, tuple)):
        return []
    cleaned: List[Tuple[float, float]] = []
    for item in raw_points:
        if isinstance(item, dict):
            x = _safe_float(item.get("x"))
            y = _safe_float(item.get("y"))
            cleaned.append((x, y))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x = _safe_float(item[0])
            y = _safe_float(item[1])
            cleaned.append((x, y))

    # Strip duplicate closing vertex if present
    if len(cleaned) >= 4:
        first, last = cleaned[0], cleaned[-1]
        if math.isclose(first[0], last[0], abs_tol=1e-4) and math.isclose(first[1], last[1], abs_tol=1e-4):
            cleaned = cleaned[:-1]

    return cleaned


def parse_zone_geometry(raw_geom: Any) -> Dict[str, Any]:
    """Parse polygon_json or geometry into canonical representation.

    Supports:
    - Simple polygon: [[x, y], ...] or [{"x": x, "y": y}, ...]
    - Compound polygon with voids: {"outer": [...], "voids": [[[...]]]} or {"boundary": [...], "holes": [...]}
    - GeoJSON style polygon: [ [outer_ring], [void_1_ring], ... ]
    - Approximation dict: {"approximation": True, ...} or list containing {"approximation": True}
    """
    if raw_geom is None:
        return {"kind": "empty", "outer": [], "voids": [], "is_approximation": False, "has_voids": False, "raw": None}

    if isinstance(raw_geom, str):
        text = raw_geom.strip()
        if not text:
            return {"kind": "empty", "outer": [], "voids": [], "is_approximation": False, "has_voids": False, "raw": None}
        try:
            parsed_data = json.loads(text)
        except Exception:
            return {"kind": "empty", "outer": [], "voids": [], "is_approximation": False, "has_voids": False, "raw": raw_geom}
    else:
        parsed_data = raw_geom

    is_approx = False
    outer: List[Tuple[float, float]] = []
    voids: List[List[Tuple[float, float]]] = []

    if isinstance(parsed_data, dict):
        if parsed_data.get("approximation") or parsed_data.get("is_approximation"):
            is_approx = True
        outer_raw = parsed_data.get("outer") or parsed_data.get("boundary") or parsed_data.get("points")
        if outer_raw:
            outer = parse_point_sequence(outer_raw)
        voids_raw = parsed_data.get("voids") or parsed_data.get("holes")
        if isinstance(voids_raw, (list, tuple)):
            for v in voids_raw:
                v_pts = parse_point_sequence(v)
                if len(v_pts) >= 3:
                    voids.append(v_pts)

    elif isinstance(parsed_data, (list, tuple)):
        # Check if first element is an approximation dict
        if len(parsed_data) > 0 and isinstance(parsed_data[0], dict) and (parsed_data[0].get("approximation") or parsed_data[0].get("is_approximation")):
            is_approx = True
            # Might also have a bounding box or outer points
            bbox = parsed_data[0].get("bounding_box") or parsed_data[0].get("bbox")
            if bbox and len(bbox) >= 4:
                x, y, w, h = map(_safe_float, bbox[:4])
                outer = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        # Check if nested list of rings: GeoJSON [ [outer], [void1], ... ]
        elif len(parsed_data) > 0 and isinstance(parsed_data[0], (list, tuple)) and len(parsed_data[0]) >= 3 and isinstance(parsed_data[0][0], (list, tuple, dict)):
            outer = parse_point_sequence(parsed_data[0])
            for hole in parsed_data[1:]:
                h_pts = parse_point_sequence(hole)
                if len(h_pts) >= 3:
                    voids.append(h_pts)
        else:
            outer = parse_point_sequence(parsed_data)

    has_voids = len(voids) > 0
    kind = "empty"
    if is_approx:
        kind = "approximation"
    elif has_voids:
        kind = "compound"
    elif len(outer) >= 3:
        kind = "polygon"

    return {
        "kind": kind,
        "outer": outer,
        "voids": voids,
        "is_approximation": is_approx,
        "has_voids": has_voids,
        "raw": parsed_data,
    }


def calculate_polygon_shoelace_area(points: Sequence[Tuple[float, float]]) -> float:
    """Calculate 2D shoelace area of a polygon in its coordinate space."""
    if len(points) < 3:
        return 0.0
    n = len(points)
    twice_area = 0.0
    for i in range(n):
        j = (i + 1) % n
        twice_area += points[i][0] * points[j][1] - points[j][0] * points[i][1]
    return abs(twice_area) / 2.0


def calculate_zone_net_area_m2(
    geometry: Any,
    px_per_m: float = 1.0,
    w_px: float = 0.0,
    h_px: float = 0.0,
) -> float:
    """Calculate true net metric area (shoelace minus voids), or bounding box if no points."""
    pxpm = _safe_float(px_per_m)
    if pxpm <= 0:
        return 0.0

    parsed = parse_zone_geometry(geometry)
    if parsed["outer"] and len(parsed["outer"]) >= 3:
        outer_px2 = calculate_polygon_shoelace_area(parsed["outer"])
        voids_px2 = sum(calculate_polygon_shoelace_area(v) for v in parsed["voids"])
        net_px2 = max(0.0, outer_px2 - voids_px2)
        return round(net_px2 / (pxpm * pxpm), 3)

    width = _safe_float(w_px)
    height = _safe_float(h_px)
    if width > 0 and height > 0:
        return round((width * height) / (pxpm * pxpm), 3)

    return 0.0


def is_proven_exact_rectangle(
    geometry: Any,
    w_px: float = 0.0,
    h_px: float = 0.0,
    is_approximation: bool = False,
    tolerance: float = 0.02,
) -> bool:
    """Return True only if evidence strictly proves an exact unvoided rectangle.

    An L-shaped area (6 vertices), stepped shape (8+ vertices), internally voided area,
    or approximation is NEVER an exact rectangle.
    """
    if is_approximation:
        return False

    parsed = parse_zone_geometry(geometry)
    if parsed["is_approximation"] or parsed["has_voids"]:
        return False

    outer = parsed["outer"]
    if outer:
        # A rectangle MUST have exactly 4 vertices
        if len(outer) != 4:
            return False

        p0, p1, p2, p3 = outer
        # Vectors
        e0 = (p1[0] - p0[0], p1[1] - p0[1])
        e1 = (p2[0] - p1[0], p2[1] - p1[1])
        e2 = (p3[0] - p2[0], p3[1] - p2[1])
        e3 = (p0[0] - p3[0], p0[1] - p3[1])

        l0 = math.hypot(*e0)
        l1 = math.hypot(*e1)
        l2 = math.hypot(*e2)
        l3 = math.hypot(*e3)

        if min(l0, l1, l2, l3) <= 1e-4:
            return False

        # Opposite sides must have equal length
        if abs(l0 - l2) > tolerance * max(l0, l2):
            return False
        if abs(l1 - l3) > tolerance * max(l1, l3):
            return False

        # Adjacent edges must be perpendicular (dot product ~ 0)
        dot01 = e0[0] * e1[0] + e0[1] * e1[1]
        dot12 = e1[0] * e2[0] + e1[1] * e2[1]
        if abs(dot01) / (l0 * l1) > tolerance:
            return False
        if abs(dot12) / (l1 * l2) > tolerance:
            return False

        # Diagonals must be equal
        d1 = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
        d2 = math.hypot(p3[0] - p1[0], p3[1] - p1[1])
        if abs(d1 - d2) > tolerance * max(d1, d2):
            return False

        return True

    # No polygon provided; only w_px and h_px
    # If no explicit polygon is provided, we can only accept if w_px > 0, h_px > 0
    # and no approximation flags are present.
    return _safe_float(w_px) > 0 and _safe_float(h_px) > 0 and not is_approximation


def is_geometric_approximation(
    zone_or_row: Mapping[str, Any],
    parsed_geometry: Optional[Dict[str, Any]] = None,
) -> bool:
    """Detect if a zone or row represents an unverified geometric approximation."""
    if parsed_geometry is None:
        parsed_geometry = parse_zone_geometry(zone_or_row.get("polygon_json"))

    if parsed_geometry.get("is_approximation"):
        return True

    # Check text indicators
    ref = str(zone_or_row.get("source_reference") or "").lower()
    notes = str(zone_or_row.get("notes") or "").lower()
    label = str(zone_or_row.get("name") or zone_or_row.get("location") or "").lower()

    approx_tokens = ("approx", "bounding_box", "rough", "unverified_box", "placeholder")
    for token in approx_tokens:
        if token in ref or token in notes or token in label:
            return True

    return False


def classify_mapped_zone_authority(
    zone: Mapping[str, Any],
    px_per_m: float = 0.0,
) -> Dict[str, Any]:
    """Classify mapped zone geometry and enforce authority gating.

    Rules:
    - Real polygon and compound geometry (outer rings and voids) is computed using net shoelace area.
    - If only an approximation exists, or if the zone is non-rectangular without exact proof,
      it is classified as Provisional/REVIEW.
    - Measured is permitted ONLY when an evidence-backed exact rectangle is proven.
    """
    pxpm = _safe_float(px_per_m) or _safe_float(zone.get("px_per_m")) or _safe_float(zone.get("page_px_per_m"))
    raw_polygon = zone.get("polygon_json")
    w_px = _safe_float(zone.get("w_px"))
    h_px = _safe_float(zone.get("h_px"))

    parsed = parse_zone_geometry(raw_polygon)
    is_approx = is_geometric_approximation(zone, parsed)
    is_exact_rect = is_proven_exact_rectangle(raw_polygon, w_px, h_px, is_approximation=is_approx)

    # Calculate true net area
    area_m2 = calculate_zone_net_area_m2(raw_polygon, pxpm, w_px, h_px)
    if area_m2 <= 0:
        area_m2 = max(0.0, _safe_float(zone.get("area_m2")))

    # Classification logic
    raw_status = str(zone.get("quantity_status") or "").strip()
    calibrated = pxpm > 0

    if is_approx:
        quantity_status = "Provisional measured"
        confidence = "To review"
        inclusion_status = "PROVISIONAL"
        reason = "Approximation only; cannot enter firm pricing until verified"
    elif parsed["has_voids"]:
        # Compound shape with voids
        # Real geometry is preserved! Net area is exact net shoelace area.
        # However, unapproved compound shapes require estimator review before firm pricing.
        quantity_status = "Provisional measured" if not is_exact_rect else "Measured"
        confidence = "To review" if not is_exact_rect else "Measured"
        inclusion_status = "PROVISIONAL" if not is_exact_rect else "INCLUSION"
        reason = f"Compound geometry with {len(parsed['voids'])} internal void(s); net area {area_m2:.2f} m² preserved"
    elif len(parsed["outer"]) > 4:
        # Non-rectangular polygon (L-shape, stepped, etc.)
        # Real polygon geometry is preserved! Net area is true polygon area.
        # But non-rectangular drafted shapes must be verified by estimator before firm pricing.
        quantity_status = "Provisional measured"
        confidence = "To review"
        inclusion_status = "PROVISIONAL"
        reason = f"Non-rectangular polygon ({len(parsed['outer'])} vertices); real area {area_m2:.2f} m² preserved"
    elif is_exact_rect and calibrated:
        quantity_status = "Measured"
        confidence = "Measured"
        inclusion_status = "INCLUSION"
        reason = "Proven evidence-backed exact rectangle"
    else:
        quantity_status = "Provisional measured" if area_m2 > 0 else "To measure"
        confidence = "To review"
        inclusion_status = "PROVISIONAL"
        reason = "Uncalibrated or unverified zone geometry"

    return {
        "area_m2": area_m2,
        "quantity_status": quantity_status,
        "confidence": confidence,
        "inclusion_status": inclusion_status,
        "is_exact_rectangle": is_exact_rect,
        "is_approximation": is_approx,
        "has_voids": parsed["has_voids"],
        "vertex_count": len(parsed["outer"]),
        "parsed_geometry": parsed,
        "reason": reason,
    }
