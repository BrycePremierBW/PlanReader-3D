"""pb_editable_3d_workspace_viewer.py — Read-Only 3D Viewer for Real Workspace Geometry (PR D.11C).

Builds a Plotly 3D figure from hydrated WallModel instances (see
pb_editable_3d_workspace_hydration.py, D.11B) so the real building geometry the
D.11A/B inspector already exposes as data can also be *seen* — orbit, pan, and
zoom come for free from Plotly's own 3D scene controls when rendered via
st.plotly_chart(). Object *selection* is deliberately left to the inspector's
own dropdown, not to clicking inside this 3D canvas — see the "Object
identification" note below for why.

This module is pure and DB-free: it takes already-hydrated WallModel instances
(and, optionally, already-fetched `mapped_zones` rows) and returns a
`plotly.graph_objects.Figure`. It writes nothing anywhere and calls no
correction/approval function — purely a read-only rendering of state the
backend already computed.

Design choices, and why they're honest rather than decorative:

  - Walls are rendered as flat vertical quads (footprint line extruded
    straight up to the wall's height), not solid boxes. model_masses has no
    wall-thickness concept once D.11B derives a single `length_m` from the
    longer of its two plan dimensions — drawing a box would mean inventing a
    thickness the data doesn't support. A quad is exactly the geometry the
    data actually has: a line, extruded vertically.

  - "Authoritative wall heights only": a wall is only extruded to its real
    height_m when its WallHeightAuthority isn't UNKNOWN_HEIGHT (equivalently,
    authority_status isn't BLOCKED — pb_editable_3d_model.py's existing
    _enforce_height_authority already guarantees these move together). A wall
    with an untrustworthy height is drawn as a flat, dashed footprint outline
    at z=0 instead — its real plan position is still shown, but it is never
    drawn as if its height were known when it isn't.

  - Door/window openings are drawn as small overlay quads positioned using
    each OpeningModel's real offset_x_m/offset_z_m (D.11C also adds these
    fields, populated from model_openings.offset_x/offset_z — real recorded
    values the schema already had but D.11B wasn't yet carrying through). An
    opening whose position wasn't recorded is centered on the wall instead of
    guessed at a specific spot, and rendered at lower opacity with a hover
    note saying so — the distinction is visible, not hidden.

  - Room/floor footprints reuse the exact same x_px/y_px/w_px/h_px-over-
    px_per_m rectangle conversion the existing "3D Building Model" page
    already applies to `mapped_zones` as its own concept-mass fallback (see
    pb_planreader_3d_app.build_3d_figure) — not a new approximation.

  - Object identification, not click-selection: every wall gets a small
    Scatter3d marker (offset off the wall's own face, so it isn't hidden
    behind the mesh panel) whose hover text names the wall_id. Wiring this to
    Streamlit's on_select="rerun" was tried and confirmed, empirically, not
    to work: Plotly.js does not fire click/selection events for 3D scatter
    traces in this environment — hover works reliably, click never reaches
    Streamlit. Rather than ship a "click to select" affordance that silently
    does nothing, the marker stays a hover-only identification aid, and the
    inspector panel's own dropdown (outside this module) is the real
    selection control. customdata is still attached to each marker (harmless,
    and future-proof if upstream 3D click-selection support ever lands).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

import plotly.graph_objects as go

from pb_editable_3d_model import OpeningModel, WallHeightAuthority, WallModel
from pb_geometry_takeoff_model import AuthorityStatus

_AUTHORITY_COLORS = {
    AuthorityStatus.FIRM.value: "#2E8B57",
    AuthorityStatus.USER_APPROVED.value: "#2E8B57",
    AuthorityStatus.PROVISIONAL.value: "#D7A21B",
    AuthorityStatus.REVIEW_REQUIRED.value: "#D7A21B",
    AuthorityStatus.BLOCKED.value: "#B33A3A",
}
_DEFAULT_AUTHORITY_COLOR = "#808080"

_OPENING_COLORS = {"door": "#8B5A2B", "window": "#4A90D9"}
_DEFAULT_OPENING_COLOR = "#666666"

_ZONE_VIEW_TYPES = {"floor plan", "plan", "room footprint", "building footprint"}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def _authority_color(authority_status: str) -> str:
    return _AUTHORITY_COLORS.get(authority_status, _DEFAULT_AUTHORITY_COLOR)


def _has_authoritative_height(wall: WallModel) -> bool:
    """A wall may only be drawn at its real height when its height source is
    trusted — mirrors, rather than re-derives, the guarantee
    WallModel._enforce_height_authority() already enforces (UNKNOWN_HEIGHT
    always implies authority_status == BLOCKED)."""
    return (
        wall.height_authority != WallHeightAuthority.UNKNOWN_HEIGHT.value
        and wall.authority_status != AuthorityStatus.BLOCKED.value
    )


def _wall_unit_and_normal(wall: WallModel) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    x0, y0 = wall.start_pt
    x1, y1 = wall.end_pt
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return (0.0, 0.0), (0.0, 0.0)
    ux, uy = dx / length, dy / length
    return (ux, uy), (-uy, ux)


def _add_wall(fig: go.Figure, wall: WallModel) -> None:
    x0, y0 = wall.start_pt
    x1, y1 = wall.end_pt
    color = _authority_color(wall.authority_status)
    authoritative = _has_authoritative_height(wall) and wall.height_m > 0.0

    if authoritative:
        fig.add_trace(go.Mesh3d(
            x=[x0, x1, x1, x0], y=[y0, y1, y1, y0], z=[0, 0, wall.height_m, wall.height_m],
            i=[0, 0], j=[1, 2], k=[2, 3],
            color=color, opacity=0.75,
            name=wall.wall_id,
            hovertext=(
                f"{wall.wall_id}<br>length={wall.length_m:.2f} m, height={wall.height_m:.2f} m"
                f"<br>authority={wall.authority_status}, height_authority={wall.height_authority}"
            ),
            hoverinfo="text", showscale=False, showlegend=False,
        ))
        marker_z = wall.height_m / 2.0
        for opening in wall.openings:
            _add_opening(fig, wall, opening)
    else:
        fig.add_trace(go.Scatter3d(
            x=[x0, x1], y=[y0, y1], z=[0, 0],
            mode="lines",
            line=dict(color=color, width=6, dash="dash"),
            name=wall.wall_id,
            hovertext=(
                f"{wall.wall_id}<br>height not authoritative "
                f"(height_authority={wall.height_authority}) — footprint only"
            ),
            hoverinfo="text", showlegend=False,
        ))
        marker_z = 0.05

    # An identification marker, offset out along the wall's normal so it
    # isn't coplanar with (and hidden behind) the mesh panel's own surface.
    # Hover reliably shows the wall_id; Plotly.js does not fire click/
    # selection events for 3D scatter traces (confirmed empirically), so this
    # is a hover aid, not a click target — actual selection happens through
    # the inspector's own dropdown, outside this module. customdata is kept
    # (harmless, and future-proof if 3D click-selection ever lands upstream).
    mid_x, mid_y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    _, (nx, ny) = _wall_unit_and_normal(wall)
    marker_offset = 0.15
    fig.add_trace(go.Scatter3d(
        x=[mid_x + nx * marker_offset], y=[mid_y + ny * marker_offset], z=[marker_z],
        mode="markers",
        marker=dict(size=8, color=color, symbol="circle", line=dict(color="#171717", width=1)),
        customdata=[[wall.wall_id]],
        name=wall.wall_id,
        hovertext=f"{wall.wall_id}",
        hoverinfo="text", showlegend=False,
    ))


def _add_opening(fig: go.Figure, wall: WallModel, opening: OpeningModel) -> None:
    x0, y0 = wall.start_pt
    (ux, uy), (nx, ny) = _wall_unit_and_normal(wall)
    length = wall.length_m if wall.length_m > 0 else 1.0

    known_position = opening.offset_x_m is not None and opening.offset_z_m is not None
    along = opening.offset_x_m if opening.offset_x_m is not None else max(0.0, (length - opening.width_m) / 2.0)
    vertical = opening.offset_z_m if opening.offset_z_m is not None else max(0.0, (wall.height_m - opening.height_m) / 2.0)
    # Never let the overlay visually spill off the wall it belongs to.
    along = min(max(along, 0.0), max(0.0, length - opening.width_m))
    vertical = min(max(vertical, 0.0), max(0.0, wall.height_m - opening.height_m))

    p0 = (x0 + ux * along, y0 + uy * along)
    p1 = (x0 + ux * (along + opening.width_m), y0 + uy * (along + opening.width_m))
    eps = 0.02  # nudges the overlay slightly off the wall face so it renders in front, not z-fighting

    fig.add_trace(go.Mesh3d(
        x=[p0[0] + nx * eps, p1[0] + nx * eps, p1[0] + nx * eps, p0[0] + nx * eps],
        y=[p0[1] + ny * eps, p1[1] + ny * eps, p1[1] + ny * eps, p0[1] + ny * eps],
        z=[vertical, vertical, vertical + opening.height_m, vertical + opening.height_m],
        i=[0, 0], j=[1, 2], k=[2, 3],
        color=_OPENING_COLORS.get(opening.opening_type, _DEFAULT_OPENING_COLOR),
        opacity=0.9 if known_position else 0.45,
        name=opening.opening_id,
        hovertext=(
            f"{opening.opening_type} {opening.opening_id}<br>"
            f"{opening.width_m:.2f} × {opening.height_m:.2f} m"
            + ("" if known_position else "<br>(position not recorded — shown centered)")
        ),
        hoverinfo="text", showscale=False, showlegend=False,
    ))


def _add_zone_footprint(fig: go.Figure, zone: Mapping[str, Any]) -> None:
    """Flat horizontal footprint for a mapped 2D zone, reusing the same
    x/y/width/depth-from-pixels conversion pb_planreader_3d_app.build_3d_figure
    already applies to mapped_zones as its own fallback — not a new
    approximation this module invents."""
    view_type = str(zone.get("view_type") or "").lower()
    if view_type not in _ZONE_VIEW_TYPES:
        return
    pxpm = _safe_float(zone.get("px_per_m"))
    if not pxpm or pxpm <= 0:
        return
    x_px, y_px = _safe_float(zone.get("x_px")), _safe_float(zone.get("y_px"))
    w_px, h_px = _safe_float(zone.get("w_px")), _safe_float(zone.get("h_px"))
    if x_px is None or y_px is None or not w_px or not h_px or w_px <= 0 or h_px <= 0:
        return
    x, y, w, d = x_px / pxpm, y_px / pxpm, w_px / pxpm, h_px / pxpm

    fig.add_trace(go.Mesh3d(
        x=[x, x + w, x + w, x], y=[y, y, y + d, y + d], z=[0, 0, 0, 0],
        i=[0, 0], j=[1, 2], k=[2, 3],
        color="#276FBF", opacity=0.15,
        name=str(zone.get("name") or "Zone"),
        hovertext=f"{zone.get('name')}<br>{w:.2f} × {d:.2f} m footprint",
        hoverinfo="text", showscale=False, showlegend=False,
    ))


def build_workspace_3d_figure(
    walls: Sequence[WallModel],
    zone_rows: Sequence[Mapping[str, Any]] = (),
) -> go.Figure:
    """Build the read-only 3D scene for a hydrated workspace. No editing, no
    photorealism, no VR — just orbit/pan/zoom (native to a Plotly 3D scene)
    and hover-to-identify markers naming each wall's object id."""
    fig = go.Figure()
    for zone in zone_rows:
        _add_zone_footprint(fig, zone)
    for wall in walls:
        _add_wall(fig, wall)
    fig.update_layout(
        height=560,
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(
            xaxis_title="X (m)", yaxis_title="Y (m)", zaxis_title="Height (m)",
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=-1.7, z=1.25)),
        ),
        showlegend=False,
    )
    return fig
