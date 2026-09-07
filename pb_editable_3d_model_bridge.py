"""pb_editable_3d_model_bridge.py — Bridge Between the Two Editable 3D Object Models.

pb_editable_3d_model.WallModel (#147, hardened in D.2/D.5/D.7) and
pb_editable_3d_correction_model.EditableGeometryObject (D.1, hardened in D.4/D.8)
are two separate object models, documented as a known limitation since D.1.

This module does not merge or replace either one — that would mean re-deriving
WallModel's real, tested accuracy logic (height-authority enforcement, the raked-
wall trapezoid formula) on the generic object model or discarding it, which is
exactly the kind of large, high-risk architectural change every prior PR in this
series was told to avoid. Instead, it provides a tested, bidirectional conversion
so a wall can move between the two pipelines: a WallModel's already-enforced state
converts into the unified shape for D.1/D.3/D.6/D.8's ledger/recalculation/JobHub
machinery, and converting back re-runs WallModel.__post_init__ — which re-applies
D.5/D.7's real safety logic rather than trusting whatever authority_status the
unified object happened to be carrying.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pb_editable_3d_correction_model import EditableGeometryObject, EditableObjectType
from pb_editable_3d_model import OpeningModel, WallHeightAuthority, WallModel


def wall_model_to_editable_geometry_object(wall: WallModel) -> EditableGeometryObject:
    """Convert a WallModel (with its D.2/D.5/D.7-derived state already applied)
    into the unified EditableGeometryObject shape."""
    measurements: Dict[str, Any] = {
        "length": wall.length_m,
        "height": wall.height_m,
        "height_authority": wall.height_authority,
        "wall_type": wall.wall_type,
        "height_start_m": wall.height_start_m,
        "height_end_m": wall.height_end_m,
        "height_source_sheet": wall.height_source_sheet,
        "height_source_level": wall.height_source_level,
        "scale_ratio": wall.scale_ratio,
        "start_pt": list(wall.start_pt),
        "end_pt": list(wall.end_pt),
        "gross_area_m2": wall.gross_area_m2,
        "net_area_m2": wall.net_area_m2,
        "openings": [op.to_dict() for op in wall.openings],
    }
    return EditableGeometryObject(
        object_id=wall.wall_id,
        object_type=EditableObjectType.WALL.value,
        source_page=wall.source_page_no,
        source_sheet=wall.source_sheet_label or None,
        original_geometry_ref=wall.wall_id,
        geometry_ref=wall.wall_id,
        level_id=wall.level_id or None,
        coordinates_or_measurements=measurements,
        authority_status=wall.authority_status,
        revision_hash=wall.revision_hash,
        approved_by=wall.approved_by,
        approved_at=wall.approved_at,
    )


def editable_geometry_object_to_wall_model(obj: EditableGeometryObject) -> WallModel:
    """Convert a wall-typed EditableGeometryObject back into a WallModel.

    Reconstruction runs WallModel.__post_init__, which re-derives gross/net area
    and re-applies height-authority enforcement (D.5) and the raked-wall trapezoid
    formula (D.7) from the measurements — the round trip can never silently carry
    over an authority_status that the reconstructed geometry doesn't actually
    support. Fails closed on missing data: an absent height_authority defaults to
    "unknown_height" (blocking), never a guessed trusted source.
    """
    if obj.object_type != EditableObjectType.WALL.value:
        raise ValueError(
            f"Cannot convert object_type {obj.object_type!r} to WallModel — expected "
            f"{EditableObjectType.WALL.value!r}"
        )

    m = obj.coordinates_or_measurements

    def _opt_float(key: str):
        v = m.get(key)
        return float(v) if v is not None else None

    openings_raw: List[Dict[str, Any]] = m.get("openings") or []
    known_opening_fields = {
        "opening_id", "wall_id", "opening_type", "width_m", "height_m",
        "area_m2", "deducts", "source_page_no", "source_sheet_label",
        "approval_status", "revision_hash", "offset_x_m", "offset_z_m",
    }
    openings = [
        OpeningModel(**{k: v for k, v in op.items() if k in known_opening_fields})
        for op in openings_raw
    ]

    start_pt = tuple(m.get("start_pt") or (0.0, 0.0))
    end_pt = tuple(m.get("end_pt") or (0.0, 0.0))

    source_page = obj.source_page
    source_page_no = source_page if isinstance(source_page, int) else 1

    return WallModel(
        wall_id=obj.object_id,
        level_id=obj.level_id or "",
        start_pt=start_pt,
        end_pt=end_pt,
        length_m=float(m.get("length") or 0.0),
        height_m=float(m.get("height") or 0.0),
        height_authority=m.get("height_authority") or WallHeightAuthority.UNKNOWN_HEIGHT.value,
        wall_type=m.get("wall_type") or "standard",
        height_start_m=_opt_float("height_start_m"),
        height_end_m=_opt_float("height_end_m"),
        openings=openings,
        source_page_no=source_page_no,
        source_sheet_label=obj.source_sheet or "",
        height_source_sheet=m.get("height_source_sheet"),
        height_source_level=m.get("height_source_level"),
        scale_ratio=m.get("scale_ratio") or "1:100",
        authority_status=obj.authority_status,
        approved_by=obj.approved_by,
        approved_at=obj.approved_at,
    )
