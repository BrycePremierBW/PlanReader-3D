"""pb_editable_3d_workspace_hydration.py — Real Workspace Geometry -> WallModel (PR D.11B).

Converts real PlanReader workspace geometry (the `model_masses` / `model_openings`
SQLite tables that already back the "3D Building Model" page) into
pb_editable_3d_model.WallModel instances, so the D.1-D.10 editable-3D backend and
the D.11A inspector panel can operate on real geometry instead of only the D.11A
demo scenario.

This module is deliberately a pure, DB-free function: `hydrate_masses_to_wall_models`
takes already-fetched rows (plain dicts, e.g. from sqlite3.Row) and returns
WallModel instances plus a fail-closed skip list. It does not import Streamlit, does
not open a database connection, and does not write anything anywhere — callers
(the Streamlit app) are responsible for querying `model_masses`/`model_openings`
scoped by workspace_id and passing the rows in. No DB migration, no new table, no
new column: this reads the existing schema exactly as-is.

Why this mapping is honest rather than fabricated
---------------------------------------------------
`model_masses` has no wall-specific vocabulary (no wall_id, no start/end points, no
height_authority, no scale_ratio, no page number) — it stores an axis-aligned box
(x, y, z, width, depth, height) plus a free-text `source_reference` and a
`confidence` label ("Measured" / "Verified" / "Derived" / "Assumed" / "To review").
Rather than inventing wall semantics the schema doesn't carry, this adapter:

  - derives wall length from the box's own longer horizontal edge (max(width, depth)) —
    a real, deterministic, reproducible number taken directly from recorded
    dimensions, never a guessed value;
  - maps `confidence` (a label the app already asks the user to set) onto
    WallHeightAuthority: "Measured" -> USER_ENTERED, "Verified" -> USER_APPROVED,
    "Derived" -> MODEL_ESTIMATED, and everything else — including "Assumed" and "To
    review", which are literally the app's own labels for a guessed/unverified
    height — maps to UNKNOWN_HEIGHT. WallModel's own `_enforce_height_authority()`
    then does the rest: UNKNOWN_HEIGHT always zeroes gross/net area and forces
    authority_status=BLOCKED, regardless of what numeric height happens to be
    stored (the DB column defaults every write to 2.7m — see below — so a numeric
    height alone is never trusted as evidence the height is actually known);
  - never assigns authority_status=FIRM. Hydration is not an approval: nobody has
    run this specific object through approve_corrected_geometry(). Every hydrated
    wall starts at REVIEW_REQUIRED (or BLOCKED, if UNKNOWN_HEIGHT forces it down),
    with approved_by/approved_at left None, exactly like a fresh correction (D.1/
    D.2's "correction is never an approval" invariant, applied here to "hydration
    is never an approval" too);
  - skips (rather than fabricates) geometry that can't produce a real wall: a mass
    with no finite, positive width or depth contributes no wall at all, and an
    opening with a non-finite/negative width or height is dropped from its wall
    (the wall itself is still hydrated) rather than clamped to a made-up minimum.

Known impedance mismatch (documented, not silently papered over): every write path
to `model_masses.height` in pb_planreader_3d_app.py defaults to 2.7m
(`to_float(row.get("height"), 2.7)` / `row.get("height", 2.7)`), so the column is
realistically never NULL even when nobody actually measured the wall — that's why
`confidence`, not the presence of a numeric height, is what this module trusts to
decide whether a height is real. There is also no existing foreign key from
`model_masses`/`model_openings` to `takeoff_rows` anywhere in the schema (the only
FK involving take-off rows is the reverse one, `measurement_lines.takeoff_row_id`),
so hydrated walls always have empty `dependent_quantity_ids` — there is nothing
real to link yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pb_editable_3d_model import OpeningModel, WallHeightAuthority, WallModel
from pb_geometry_takeoff_model import AuthorityStatus

_CONFIDENCE_TO_HEIGHT_AUTHORITY: Dict[str, str] = {
    "measured": WallHeightAuthority.USER_ENTERED.value,
    "verified": WallHeightAuthority.USER_APPROVED.value,
    "derived": WallHeightAuthority.MODEL_ESTIMATED.value,
    # "assumed", "to review", "", and anything unrecognized fall through to
    # UNKNOWN_HEIGHT via the .get(..., UNKNOWN_HEIGHT) default below — these are
    # the app's own labels for a guessed or unverified dimension.
}


def _safe_float(value: Any) -> Optional[float]:
    """Parse a DB value to a finite float, or None if it isn't one. Never raises,
    never fabricates a fallback number."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf check without math import
        return None
    return v


@dataclass
class HydrationSkip:
    """One piece of real geometry that was deliberately left out of hydration,
    with the exact reason — fail-closed, not silently dropped."""
    kind: str  # "mass" | "opening"
    source_id: Any
    label: str
    reason: str


@dataclass
class HydrationResult:
    walls: List[WallModel]
    skipped: List[HydrationSkip]


def _height_authority_for_confidence(confidence: Any) -> str:
    key = str(confidence or "").strip().lower()
    return _CONFIDENCE_TO_HEIGHT_AUTHORITY.get(key, WallHeightAuthority.UNKNOWN_HEIGHT.value)


def _hydrate_openings(
    mass_id: Any,
    wall_id: str,
    opening_rows: Sequence[Mapping[str, Any]],
    skipped: List[HydrationSkip],
) -> List[OpeningModel]:
    openings: List[OpeningModel] = []
    for row in opening_rows:
        width = _safe_float(row.get("width"))
        height = _safe_float(row.get("height"))
        opening_label = str(row.get("label") or row.get("opening_type") or "Opening")
        if width is None or height is None or width < 0.0 or height < 0.0:
            skipped.append(HydrationSkip(
                kind="opening", source_id=row.get("id"), label=opening_label,
                reason=f"non-finite or negative width/height (width={row.get('width')!r}, height={row.get('height')!r})",
            ))
            continue
        count = _safe_float(row.get("count"))
        multiplier = count if count is not None and count > 0 else 1.0
        openings.append(OpeningModel(
            opening_id=f"OPENING-{row.get('id')}",
            wall_id=wall_id,
            opening_type=str(row.get("opening_type") or "unknown"),
            width_m=width,
            height_m=height,
            area_m2=width * height * multiplier,
            deducts=True,
            source_page_no=0,
            source_sheet_label=str(row.get("source_reference") or ""),
            # Real recorded position, preserved as-is — None (not a guessed 0)
            # when the row doesn't have it, so a 3D viewer can tell "positioned
            # at the wall start" apart from "position not recorded".
            offset_x_m=_safe_float(row.get("offset_x")),
            offset_z_m=_safe_float(row.get("offset_z")),
        ))
    return openings


def hydrate_masses_to_wall_models(
    mass_rows: Sequence[Mapping[str, Any]],
    opening_rows: Sequence[Mapping[str, Any]],
) -> HydrationResult:
    """Convert real `model_masses`/`model_openings` rows into WallModel instances.

    Pure and deterministic: the same input rows always produce the same walls
    (same wall_id, same computed length/area/authority) — no randomness, no
    session state, no caching. Callers should re-run this against fresh rows on
    every read so the result always reflects the live DB state.
    """
    openings_by_mass: Dict[Any, List[Mapping[str, Any]]] = {}
    for row in opening_rows:
        openings_by_mass.setdefault(row.get("mass_id"), []).append(row)

    walls: List[WallModel] = []
    skipped: List[HydrationSkip] = []

    for row in mass_rows:
        mass_id = row.get("id")
        label = str(row.get("label") or f"Mass {mass_id}")
        width = _safe_float(row.get("width"))
        depth = _safe_float(row.get("depth"))
        valid_edges = [e for e in (width, depth) if e is not None and e > 0.0]
        if not valid_edges:
            skipped.append(HydrationSkip(
                kind="mass", source_id=mass_id, label=label,
                reason=f"no finite, positive width or depth to derive a wall length from (width={row.get('width')!r}, depth={row.get('depth')!r})",
            ))
            continue
        length_m = max(valid_edges)

        x = _safe_float(row.get("x")) or 0.0
        y = _safe_float(row.get("y")) or 0.0
        if width is not None and width >= (depth or 0.0):
            start_pt, end_pt = (x, y), (x + length_m, y)
        else:
            start_pt, end_pt = (x, y), (x, y + length_m)

        wall_id = f"MASS-{mass_id}"

        height_authority = _height_authority_for_confidence(row.get("confidence"))
        height_m = _safe_float(row.get("height"))
        if height_m is None or height_m < 0.0:
            # A malformed/missing height can never be trusted, regardless of the
            # confidence label recorded for it.
            height_authority = WallHeightAuthority.UNKNOWN_HEIGHT.value
            height_m = 0.0

        source_sheet_label = str(row.get("source_reference") or "")

        openings = _hydrate_openings(mass_id, wall_id, openings_by_mass.get(mass_id, []), skipped)

        walls.append(WallModel(
            wall_id=wall_id,
            level_id=str(row.get("level_name") or ""),
            start_pt=start_pt,
            end_pt=end_pt,
            length_m=length_m,
            height_m=height_m,
            height_authority=height_authority,
            wall_type="standard",  # the schema has no raked/stair concept to read
            openings=openings,
            source_page_no=0,  # model_masses has no page-number column — 0 is an
                                # explicit "not tracked by this schema" sentinel,
                                # never a guessed page.
            source_sheet_label=source_sheet_label,
            scale_ratio="unknown",  # no scale/calibration data exists for a mass
            # Hydration is never an approval: nobody has run this object through
            # approve_corrected_geometry(). REVIEW_REQUIRED here mirrors D.1/D.2's
            # "a correction is never automatically an approval" invariant — the
            # UNKNOWN_HEIGHT branch of __post_init__'s enforcement will force this
            # down to BLOCKED where the height itself isn't trustworthy.
            authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
            approved_by=None,
            approved_at=None,
        ))

    return HydrationResult(walls=walls, skipped=skipped)
