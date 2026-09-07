"""tests/editable_3d/test_workspace_viewer.py — PR D.11C test suite.

pb_editable_3d_workspace_viewer.build_workspace_3d_figure() is a pure function
over already-hydrated WallModel instances (see D.11B). These tests prove the
"authoritative wall heights only" rule holds structurally in the built figure
(a wall with an untrusted height never gets a Mesh3d extrusion trace), that
click-selection customdata correctly identifies each wall, and that opening
overlays only ever appear on walls that were actually extruded.
"""
from __future__ import annotations

import plotly.graph_objects as go

from pb_editable_3d_model import OpeningModel, WallHeightAuthority, WallModel
from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_workspace_viewer import build_workspace_3d_figure


def _wall(**overrides) -> WallModel:
    kwargs = dict(
        wall_id="MASS-1", level_id="Ground", start_pt=(0.0, 0.0), end_pt=(6.0, 0.0),
        length_m=6.0, height_m=2.7, height_authority=WallHeightAuthority.USER_ENTERED.value,
        wall_type="standard", source_page_no=0, source_sheet_label="WD-04",
        scale_ratio="unknown", authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
    )
    kwargs.update(overrides)
    return WallModel(**kwargs)


def _mesh_names(fig: go.Figure) -> list[str]:
    return [t.name for t in fig.data if isinstance(t, go.Mesh3d)]


def _scatter_lines(fig: go.Figure) -> list[go.Scatter3d]:
    return [t for t in fig.data if isinstance(t, go.Scatter3d) and t.mode == "lines"]


def _markers(fig: go.Figure) -> list[go.Scatter3d]:
    return [t for t in fig.data if isinstance(t, go.Scatter3d) and t.mode == "markers"]


class TestAuthoritativeHeightsOnly:
    def test_wall_with_trusted_height_gets_a_mesh_extrusion(self):
        fig = build_workspace_3d_figure([_wall(height_authority=WallHeightAuthority.USER_ENTERED.value)])
        assert "MASS-1" in _mesh_names(fig)
        # An authoritative wall gets exactly one line trace: its solid (not
        # dashed) edge-outline border — never the dashed footprint-only line
        # a non-authoritative wall gets.
        lines = _scatter_lines(fig)
        assert len(lines) == 1
        assert lines[0].line.dash is None

    def test_wall_with_unknown_height_never_gets_a_mesh_extrusion(self):
        wall = _wall(height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        assert wall.authority_status == AuthorityStatus.BLOCKED.value  # enforced by WallModel itself
        fig = build_workspace_3d_figure([wall])
        assert "MASS-1" not in _mesh_names(fig)
        lines = _scatter_lines(fig)
        assert len(lines) == 1
        assert lines[0].line.dash == "dash"

    def test_wall_with_zero_height_is_never_extruded_even_if_authority_is_trusted(self):
        # A trusted-but-zero height has nothing real to extrude to.
        wall = _wall(height_m=0.0, height_authority=WallHeightAuthority.USER_ENTERED.value)
        fig = build_workspace_3d_figure([wall])
        assert "MASS-1" not in _mesh_names(fig)

    def test_unknown_height_wall_still_gets_a_click_marker(self):
        wall = _wall(height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        fig = build_workspace_3d_figure([wall])
        markers = _markers(fig)
        assert len(markers) == 1
        assert markers[0].customdata[0][0] == "MASS-1"


class TestClickSelectionCustomdata:
    def test_each_wall_marker_carries_its_own_wall_id(self):
        walls = [_wall(wall_id="MASS-1", start_pt=(0, 0), end_pt=(6, 0)),
                 _wall(wall_id="MASS-2", start_pt=(0, 4), end_pt=(5, 4))]
        fig = build_workspace_3d_figure(walls)
        markers = _markers(fig)
        assert len(markers) == 2
        ids = sorted(m.customdata[0][0] for m in markers)
        assert ids == ["MASS-1", "MASS-2"]

    def test_marker_z_is_mid_height_for_an_extruded_wall(self):
        fig = build_workspace_3d_figure([_wall(height_m=3.0)])
        marker = _markers(fig)[0]
        assert marker.z[0] == 1.5


class TestOpeningOverlays:
    def test_opening_on_an_authoritative_wall_is_rendered(self):
        opening = OpeningModel(
            opening_id="OPENING-1", wall_id="MASS-1", opening_type="door",
            width_m=0.9, height_m=2.1, area_m2=1.89, offset_x_m=1.0, offset_z_m=0.0,
        )
        fig = build_workspace_3d_figure([_wall(openings=[opening])])
        assert "OPENING-1" in _mesh_names(fig)

    def test_opening_on_a_non_authoritative_wall_is_not_rendered(self):
        opening = OpeningModel(
            opening_id="OPENING-1", wall_id="MASS-1", opening_type="door",
            width_m=0.9, height_m=2.1, area_m2=1.89, offset_x_m=1.0, offset_z_m=0.0,
        )
        wall = _wall(height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value, openings=[opening])
        fig = build_workspace_3d_figure([wall])
        assert "OPENING-1" not in _mesh_names(fig)

    def test_opening_with_unknown_position_is_dimmer_than_a_known_one(self):
        known = OpeningModel(
            opening_id="OPENING-KNOWN", wall_id="MASS-1", opening_type="door",
            width_m=0.9, height_m=2.1, area_m2=1.89, offset_x_m=1.0, offset_z_m=0.0,
        )
        unknown = OpeningModel(
            opening_id="OPENING-UNKNOWN", wall_id="MASS-1", opening_type="window",
            width_m=1.0, height_m=1.2, area_m2=1.2, offset_x_m=None, offset_z_m=None,
        )
        fig = build_workspace_3d_figure([_wall(openings=[known, unknown])])
        by_name = {t.name: t for t in fig.data if isinstance(t, go.Mesh3d) and t.name.startswith("OPENING")}
        assert by_name["OPENING-KNOWN"].opacity > by_name["OPENING-UNKNOWN"].opacity

    def test_opening_overlay_never_spills_off_the_wall(self):
        # offset_x_m + width_m exceeds the wall's own length — must be clamped,
        # never drawn hanging off the end of the wall.
        opening = OpeningModel(
            opening_id="OPENING-1", wall_id="MASS-1", opening_type="door",
            width_m=1.0, height_m=2.1, area_m2=2.1, offset_x_m=5.9, offset_z_m=0.0,
        )
        wall = _wall(length_m=6.0, end_pt=(6.0, 0.0), openings=[opening])
        fig = build_workspace_3d_figure([wall])
        overlay = next(t for t in fig.data if isinstance(t, go.Mesh3d) and t.name == "OPENING-1")
        assert max(overlay.x) <= 6.0 + 1e-6


class TestAuthorityColorCoding:
    def test_firm_and_blocked_walls_get_different_colors(self):
        firm_wall = _wall(authority_status=AuthorityStatus.FIRM.value)
        blocked_wall = _wall(
            wall_id="MASS-2", height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value,
        )
        fig = build_workspace_3d_figure([firm_wall, blocked_wall])
        firm_mesh = next(t for t in fig.data if isinstance(t, go.Mesh3d) and t.name == "MASS-1")
        blocked_line = next(t for t in _scatter_lines(fig) if t.name == "MASS-2")
        assert firm_mesh.color != blocked_line.line.color


class TestZoneFootprints:
    def _zone(self, **overrides):
        row = {
            "name": "Living Room", "view_type": "floor plan",
            "x_px": 0.0, "y_px": 0.0, "w_px": 300.0, "h_px": 400.0, "px_per_m": 100.0,
        }
        row.update(overrides)
        return row

    def test_valid_floor_plan_zone_is_rendered(self):
        fig = build_workspace_3d_figure([], zone_rows=[self._zone()])
        assert "Living Room" in _mesh_names(fig)

    def test_unrecognized_view_type_is_skipped(self):
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(view_type="elevation")])
        assert fig.data == ()

    def test_missing_px_per_m_is_skipped_not_fabricated(self):
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(px_per_m=None)])
        assert fig.data == ()

    def test_zero_px_per_m_is_skipped(self):
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(px_per_m=0)])
        assert fig.data == ()


class TestEmptyInputs:
    def test_no_walls_and_no_zones_produces_an_empty_figure(self):
        fig = build_workspace_3d_figure([], zone_rows=[])
        assert fig.data == ()


class TestSelectionHighlighting:
    def test_selected_authoritative_wall_gets_a_highlighted_border(self):
        walls = [_wall(wall_id="MASS-1"), _wall(wall_id="MASS-2", start_pt=(0, 4), end_pt=(6, 4))]
        fig = build_workspace_3d_figure(walls, selected_wall_id="MASS-2")
        lines_by_name = {t.name: t for t in _scatter_lines(fig)}
        assert lines_by_name["MASS-1"].line.color != lines_by_name["MASS-2"].line.color
        assert lines_by_name["MASS-2"].line.width > lines_by_name["MASS-1"].line.width

    def test_selected_non_authoritative_wall_gets_a_highlighted_dashed_line(self):
        walls = [
            _wall(wall_id="MASS-1", height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value),
            _wall(wall_id="MASS-2", height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value, start_pt=(0, 4), end_pt=(6, 4)),
        ]
        fig = build_workspace_3d_figure(walls, selected_wall_id="MASS-2")
        lines_by_name = {t.name: t for t in _scatter_lines(fig)}
        assert lines_by_name["MASS-1"].line.color != lines_by_name["MASS-2"].line.color
        assert lines_by_name["MASS-1"].line.dash == "dash"
        assert lines_by_name["MASS-2"].line.dash == "dash"

    def test_selected_wall_marker_is_larger_than_unselected(self):
        walls = [_wall(wall_id="MASS-1"), _wall(wall_id="MASS-2", start_pt=(0, 4), end_pt=(6, 4))]
        fig = build_workspace_3d_figure(walls, selected_wall_id="MASS-2")
        markers_by_id = {m.customdata[0][0]: m for m in _markers(fig)}
        assert markers_by_id["MASS-2"].marker.size > markers_by_id["MASS-1"].marker.size

    def test_no_selection_means_no_wall_is_highlighted(self):
        walls = [_wall(wall_id="MASS-1"), _wall(wall_id="MASS-2", start_pt=(0, 4), end_pt=(6, 4))]
        fig = build_workspace_3d_figure(walls, selected_wall_id=None)
        lines_by_name = {t.name: t for t in _scatter_lines(fig)}
        assert lines_by_name["MASS-1"].line.color == lines_by_name["MASS-2"].line.color

    def test_selecting_an_id_not_present_highlights_nothing(self):
        fig = build_workspace_3d_figure([_wall(wall_id="MASS-1")], selected_wall_id="MASS-DOES-NOT-EXIST")
        lines = _scatter_lines(fig)
        assert len(lines) == 1
        assert lines[0].line.width == 2  # unselected border width, not the highlighted one


class TestZoneRealGeometryClassification:
    def _zone(self, **overrides):
        row = {
            "name": "Living Room", "view_type": "floor plan",
            "x_px": 0.0, "y_px": 0.0, "w_px": 300.0, "h_px": 400.0, "px_per_m": 100.0,
        }
        row.update(overrides)
        return row

    def test_evidence_backed_exact_rectangle_renders_trusted_and_filled(self):
        import json
        polygon = json.dumps([[0, 0], [300, 0], [300, 400], [0, 400]])
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(polygon_json=polygon, quantity_status="Measured")])
        mesh = next(t for t in fig.data if isinstance(t, go.Mesh3d) and t.name == "Living Room")
        assert mesh.color == "#2E8B57"

    def test_approximation_flag_renders_provisional_not_trusted(self):
        import json
        polygon = json.dumps([{"approximation": True}])
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(polygon_json=polygon)])
        mesh = next(t for t in fig.data if isinstance(t, go.Mesh3d) and t.name == "Living Room")
        assert mesh.color == "#D7A21B"

    def test_real_l_shaped_polygon_is_filled_with_its_own_vertices_not_a_rectangle(self):
        import json
        # A real L-shape: 6 vertices, not a rectangle.
        l_shape = [[0, 0], [200, 0], [200, 200], [300, 200], [300, 400], [0, 400]]
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(polygon_json=json.dumps(l_shape))])
        mesh = next(t for t in fig.data if isinstance(t, go.Mesh3d) and t.name == "Living Room")
        assert len(mesh.x) == 6  # the real 6 vertices, not a 4-corner bounding box
        assert mesh.color == "#D7A21B"  # non-rectangular polygon: provisional, not trusted

    def test_zone_with_a_real_void_is_outline_only_never_filled(self):
        import json
        geometry = {
            "outer": [[0, 0], [400, 0], [400, 400], [0, 400]],
            "voids": [[[100, 100], [200, 100], [200, 200], [100, 200]]],
        }
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(polygon_json=json.dumps(geometry))])
        assert "Living Room" not in _mesh_names(fig)
        lines = _scatter_lines(fig)
        assert len(lines) == 1
        assert lines[0].line.dash == "dot"

    def test_zone_with_no_geometry_at_all_and_no_bbox_is_skipped(self):
        fig = build_workspace_3d_figure([], zone_rows=[self._zone(x_px=None, y_px=None, w_px=None, h_px=None)])
        assert fig.data == ()


class TestSceneBoundsFraming:
    def test_axis_ranges_cover_the_real_wall_bounding_box(self):
        wall = _wall(start_pt=(1.0, 2.0), end_pt=(7.0, 2.0), height_m=2.7)
        fig = build_workspace_3d_figure([wall])
        xr = fig.layout.scene.xaxis.range
        yr = fig.layout.scene.yaxis.range
        zr = fig.layout.scene.zaxis.range
        assert xr[0] <= 1.0 and xr[1] >= 7.0
        assert yr[0] <= 2.0 and yr[1] >= 2.0
        assert zr[0] <= 0.0 and zr[1] >= 2.7

    def test_empty_scene_still_produces_a_valid_default_range(self):
        fig = build_workspace_3d_figure([], zone_rows=[])
        xr = fig.layout.scene.xaxis.range
        assert xr[0] < xr[1]
