"""tests/editable_3d/test_model_bridge.py — PR D.9 test suite.

pb_editable_3d_model.WallModel (#147, D.2, D.5, D.7) and
pb_editable_3d_correction_model.EditableGeometryObject (D.1, D.4, D.8) are two
separate object models, documented as a known limitation since D.1. This suite
proves the bridge that connects them: a WallModel (with its accuracy logic already
applied) converts to the unified shape and back, without silently bypassing either
model's own safety logic — height-authority enforcement (D.5) and the raked-wall
trapezoid formula (D.7) both re-apply correctly on the reconstructed WallModel.
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import OpeningModel, WallHeightAuthority, WallModel
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
)
from pb_editable_3d_model_bridge import (
    editable_geometry_object_to_wall_model,
    wall_model_to_editable_geometry_object,
)


def _wall(**overrides):
    defaults = dict(
        wall_id="W_BRIDGE_1",
        level_id="L_01",
        start_pt=(1.0, 2.0),
        end_pt=(7.0, 2.0),
        length_m=6.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        wall_type="standard",
        source_page_no=3,
        source_sheet_label="WD-03",
        authority_status=AuthorityStatus.FIRM.value,
        approved_by="Estimator A",
        approved_at="2026-09-07T00:00:00Z",
    )
    defaults.update(overrides)
    return WallModel(**defaults)


class TestForwardConversion:
    def test_wall_model_converts_to_editable_geometry_object(self):
        wall = _wall()
        obj = wall_model_to_editable_geometry_object(wall)

        assert obj.object_id == "W_BRIDGE_1"
        assert obj.object_type == EditableObjectType.WALL.value
        assert obj.source_page == 3
        assert obj.source_sheet == "WD-03"
        assert obj.level_id == "L_01"
        assert obj.authority_status == AuthorityStatus.FIRM.value
        assert obj.approved_by == "Estimator A"
        assert obj.approved_at == "2026-09-07T00:00:00Z"
        assert obj.revision_hash == wall.revision_hash
        assert obj.coordinates_or_measurements["length"] == 6.0
        assert obj.coordinates_or_measurements["height"] == 2.7
        assert obj.coordinates_or_measurements["gross_area_m2"] == pytest.approx(wall.gross_area_m2)

    def test_forward_conversion_captures_original_geometry_ref(self):
        wall = _wall()
        obj = wall_model_to_editable_geometry_object(wall)
        assert obj.original_geometry_ref == obj.geometry_ref == "W_BRIDGE_1"

    def test_openings_are_carried_through(self):
        wall = _wall(openings=[OpeningModel(
            opening_id="D1", wall_id="W_BRIDGE_1", opening_type="door",
            width_m=0.9, height_m=2.1, area_m2=1.89, deducts=True,
        )])
        obj = wall_model_to_editable_geometry_object(wall)
        openings = obj.coordinates_or_measurements["openings"]
        assert len(openings) == 1
        assert openings[0]["opening_id"] == "D1"
        assert openings[0]["area_m2"] == pytest.approx(1.89)


class TestRoundTripPreservesCoreState:
    def test_round_trip_preserves_wall_identity_and_geometry(self):
        wall = _wall()
        obj = wall_model_to_editable_geometry_object(wall)
        rebuilt = editable_geometry_object_to_wall_model(obj)

        assert rebuilt.wall_id == wall.wall_id
        assert rebuilt.length_m == pytest.approx(wall.length_m)
        assert rebuilt.height_m == pytest.approx(wall.height_m)
        assert rebuilt.gross_area_m2 == pytest.approx(wall.gross_area_m2)
        assert rebuilt.authority_status == wall.authority_status
        assert rebuilt.approved_by == wall.approved_by
        assert list(rebuilt.start_pt) == list(wall.start_pt)
        assert list(rebuilt.end_pt) == list(wall.end_pt)

    def test_round_trip_preserves_openings_and_deductions(self):
        wall = _wall(openings=[OpeningModel(
            opening_id="D1", wall_id="W_BRIDGE_1", opening_type="door",
            width_m=0.9, height_m=2.1, area_m2=1.89, deducts=True,
        )])
        obj = wall_model_to_editable_geometry_object(wall)
        rebuilt = editable_geometry_object_to_wall_model(obj)

        assert len(rebuilt.openings) == 1
        assert rebuilt.openings[0].opening_id == "D1"
        assert rebuilt.net_area_m2 == pytest.approx(wall.net_area_m2)


class TestReverseConversionReappliesRealSafetyLogic:
    def test_unknown_height_still_blocks_after_round_trip(self):
        wall = _wall(height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        obj = wall_model_to_editable_geometry_object(wall)
        # Manually corrupt the measurements to simulate a payload from elsewhere
        # claiming FIRM despite an unknown height source.
        obj.coordinates_or_measurements["height_authority"] = WallHeightAuthority.UNKNOWN_HEIGHT.value
        rebuilt = editable_geometry_object_to_wall_model(
            EditableGeometryObject(**{**obj.to_dict(), "authority_status": AuthorityStatus.FIRM.value})
        )
        assert rebuilt.authority_status == AuthorityStatus.BLOCKED.value
        assert rebuilt.gross_area_m2 == 0.0

    def test_raked_wall_trapezoid_formula_reapplies_after_round_trip(self):
        wall = _wall(
            wall_type="raked", height_start_m=2.4, height_end_m=3.6,
            height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        )
        obj = wall_model_to_editable_geometry_object(wall)
        rebuilt = editable_geometry_object_to_wall_model(obj)

        assert rebuilt.height_start_m == pytest.approx(2.4)
        assert rebuilt.height_end_m == pytest.approx(3.6)
        assert rebuilt.gross_area_m2 == pytest.approx(6.0 * (2.4 + 3.6) / 2.0)
        assert rebuilt.authority_status == AuthorityStatus.FIRM.value  # real formula, guard lifted

    def test_raked_wall_without_endpoints_keeps_the_review_guard_after_round_trip(self):
        wall = _wall(wall_type="raked", authority_status=AuthorityStatus.FIRM.value, approved_by=None, approved_at=None)
        obj = wall_model_to_editable_geometry_object(wall)
        rebuilt = editable_geometry_object_to_wall_model(obj)
        assert rebuilt.authority_status == AuthorityStatus.REVIEW_REQUIRED.value


class TestConversionRejectsWrongObjectType:
    def test_converting_a_non_wall_object_raises(self):
        obj = EditableGeometryObject(
            object_id="ROOM-1", object_type=EditableObjectType.ROOM.value,
            revision_hash="GENESIS",
        )
        with pytest.raises(ValueError):
            editable_geometry_object_to_wall_model(obj)


class TestConversionHandlesMinimalPayloadsSafely:
    def test_minimal_editable_geometry_object_reconstructs_without_error(self):
        obj = EditableGeometryObject(
            object_id="W_MIN", object_type=EditableObjectType.WALL.value,
            revision_hash="GENESIS",
        )
        rebuilt = editable_geometry_object_to_wall_model(obj)
        assert rebuilt.wall_id == "W_MIN"
        assert rebuilt.length_m == 0.0
        assert rebuilt.height_m == 0.0
        # No height authority info at all -> fails closed, not a guessed default.
        assert rebuilt.height_authority == WallHeightAuthority.UNKNOWN_HEIGHT.value


class TestBridgeInteroperatesWithTheLedgerPipeline:
    def test_a_bridged_wall_can_be_corrected_via_the_ledger_and_reconstructed(self):
        wall = _wall()
        obj = wall_model_to_editable_geometry_object(wall)

        ledger = Editable3DCorrectionLedger()
        ledger.register_object(obj)
        outcome = ledger.apply_correction(
            correction_id="CORR-BRIDGE-1", object_id="W_BRIDGE_1",
            field=CorrectionField.LENGTH.value, new_value=8.0,
            reason="Corrected via ledger after bridging from WallModel",
            actor="Estimator B", source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        corrected_obj = ledger.get_object("W_BRIDGE_1")

        rebuilt = editable_geometry_object_to_wall_model(corrected_obj)
        assert rebuilt.length_m == pytest.approx(8.0)
        assert rebuilt.gross_area_m2 == pytest.approx(8.0 * 2.7)
        # Correction is not approval (D.2) even across the bridge.
        assert rebuilt.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert rebuilt.approved_by is None
