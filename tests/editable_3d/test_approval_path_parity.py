"""tests/editable_3d/test_approval_path_parity.py — PR D.10 test suite.

Three geometry-approval paths exist across the codebase:
  1. apply_correction_event() with CorrectionAction.APPROVE_QUANTITY (WallModel, #147)
  2. pb_editable_3d_model.approve_corrected_geometry() (WallModel, D.2)
  3. pb_editable_3d_correction_model.approve_corrected_geometry() (EditableGeometryObject, D.1/D.4)

Paths 2 and 3 already required a source trace before granting FIRM authority; path
1 did not. This suite proves path 1 now shares that same floor, and documents (via
a passing test, not just a comment) the one structural difference — revision-hash
staleness gating — that's deliberately NOT retrofitted onto path 1, because
apply_correction_event() always operates on the live object within a single call,
so there's no "held a stale reference" risk for it to guard against.
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import (
    BuildingModel,
    CorrectionAction,
    CorrectionEvent,
    LevelModel,
    WallHeightAuthority,
    WallModel,
    apply_correction_event,
    approve_corrected_geometry as approve_corrected_geometry_wall_model,
)
from pb_editable_3d_correction_model import (
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    approve_corrected_geometry as approve_corrected_geometry_ledger,
)


def _building_with_wall(source_sheet_label: str = "WD-01") -> BuildingModel:
    wall = WallModel(
        wall_id="W_PARITY_1", level_id="L_01",
        start_pt=(0.0, 0.0), end_pt=(4.0, 0.0),
        length_m=4.0, height_m=2.7,
        height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
        authority_status=AuthorityStatus.PROVISIONAL.value,
        source_page_no=1, source_sheet_label=source_sheet_label,
    )
    level = LevelModel(level_id="L_01", name="Ground", elevation_m=0.0, ceiling_height_m=2.7, walls=[wall])
    bldg = BuildingModel(building_id="BLDG_PARITY", name="Parity Test", levels=[level])
    bldg.compute_building_revision_hash()
    return bldg


class TestApproveQuantityActionNowRequiresSourceTrace:
    def test_approve_quantity_blocks_when_source_sheet_missing(self):
        bldg = _building_with_wall(source_sheet_label="")
        event = CorrectionEvent(
            correction_id="CORR-PARITY-1", object_id="W_PARITY_1", object_type="wall",
            action=CorrectionAction.APPROVE_QUANTITY.value, field_name="authority_status",
            old_value="provisional", new_value="firm",
            reason="Verified against elevation", actor="Estimator A",
        )
        with pytest.raises(ValueError):
            apply_correction_event(bldg, event)

    def test_approve_quantity_succeeds_when_source_sheet_present(self):
        bldg = _building_with_wall(source_sheet_label="WD-01")
        event = CorrectionEvent(
            correction_id="CORR-PARITY-2", object_id="W_PARITY_1", object_type="wall",
            action=CorrectionAction.APPROVE_QUANTITY.value, field_name="authority_status",
            old_value="provisional", new_value="firm",
            reason="Verified against elevation", actor="Estimator A",
        )
        bldg, _ = apply_correction_event(bldg, event)
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.FIRM.value
        assert wall.approved_by == "Estimator A"
        assert wall.approved_at is not None

    def test_reject_quantity_is_unaffected_by_the_source_trace_requirement(self):
        # Rejection only ever downgrades authority — it never needs the same gate
        # an approval does, and must keep working even without a source trace.
        bldg = _building_with_wall(source_sheet_label="")
        event = CorrectionEvent(
            correction_id="CORR-PARITY-3", object_id="W_PARITY_1", object_type="wall",
            action=CorrectionAction.REJECT_QUANTITY.value, field_name="authority_status",
            old_value="firm", new_value="review_required",
            reason="Conflicting revision detected", actor="Estimator A",
        )
        bldg, _ = apply_correction_event(bldg, event)
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert wall.approved_by is None


class TestAllThreeApprovalPathsShareTheSameSourceTraceFloor:
    def test_wall_model_gated_path_blocks_without_source_trace(self):
        bldg = _building_with_wall(source_sheet_label="")
        wall = bldg.levels[0].walls[0]
        with pytest.raises(ValueError):
            approve_corrected_geometry_wall_model(
                bldg, object_id="W_PARITY_1", current_revision_hash=wall.revision_hash,
                approved_by="Estimator A",
            )

    def test_ledger_gated_path_blocks_without_source_trace(self):
        ledger = Editable3DCorrectionLedger()
        obj = EditableGeometryObject(
            object_id="W_PARITY_2", object_type=EditableObjectType.WALL.value,
            source_page=1, source_sheet=None,  # missing
            coordinates_or_measurements={"length": 4.0, "height": 2.7},
            authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS",
        )
        ledger.register_object(obj)
        with pytest.raises(ValueError):
            approve_corrected_geometry_ledger(
                ledger, object_id="W_PARITY_2", approved_by="Estimator A",
                current_revision_hash="GENESIS",
            )

    def test_apply_correction_event_approve_quantity_blocks_without_source_trace(self):
        bldg = _building_with_wall(source_sheet_label="")
        event = CorrectionEvent(
            correction_id="CORR-PARITY-4", object_id="W_PARITY_1", object_type="wall",
            action=CorrectionAction.APPROVE_QUANTITY.value, field_name="authority_status",
            old_value="provisional", new_value="firm",
            reason="Verified", actor="Estimator A",
        )
        with pytest.raises(ValueError):
            apply_correction_event(bldg, event)

    def test_all_three_paths_succeed_with_source_trace_present(self):
        # Path 1
        bldg1 = _building_with_wall(source_sheet_label="WD-01")
        event = CorrectionEvent(
            correction_id="CORR-PARITY-5", object_id="W_PARITY_1", object_type="wall",
            action=CorrectionAction.APPROVE_QUANTITY.value, field_name="authority_status",
            old_value="provisional", new_value="firm",
            reason="Verified", actor="Estimator A",
        )
        bldg1, _ = apply_correction_event(bldg1, event)
        assert bldg1.levels[0].walls[0].authority_status == AuthorityStatus.FIRM.value

        # Path 2
        bldg2 = _building_with_wall(source_sheet_label="WD-01")
        wall2 = bldg2.levels[0].walls[0]
        bldg2 = approve_corrected_geometry_wall_model(
            bldg2, object_id="W_PARITY_1", current_revision_hash=wall2.revision_hash,
            approved_by="Estimator A",
        )
        assert bldg2.levels[0].walls[0].authority_status == AuthorityStatus.FIRM.value

        # Path 3
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(EditableGeometryObject(
            object_id="W_PARITY_3", object_type=EditableObjectType.WALL.value,
            source_page=1, source_sheet="WD-01",
            coordinates_or_measurements={"length": 4.0, "height": 2.7},
            authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS",
        ))
        approve_corrected_geometry_ledger(
            ledger, object_id="W_PARITY_3", approved_by="Estimator A",
            current_revision_hash="GENESIS",
        )
        assert ledger.get_object("W_PARITY_3").authority_status == AuthorityStatus.FIRM.value


class TestRevisionHashGatingStructuralDifferenceIsDeliberate:
    def test_gated_paths_reject_a_stale_revision_hash(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(EditableGeometryObject(
            object_id="W_PARITY_STALE", object_type=EditableObjectType.WALL.value,
            source_page=1, source_sheet="WD-01",
            coordinates_or_measurements={"length": 4.0, "height": 2.7},
            authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS",
        ))
        # A caller holding an old hash (e.g. from before a correction landed) is
        # rejected — this is exactly the risk path 2/3 exist to close.
        obj = ledger.get_object("W_PARITY_STALE")
        outcome = ledger.apply_correction(
            correction_id="CORR-PARITY-STALE", object_id="W_PARITY_STALE",
            field="length", new_value=5.0, reason="Site remeasure", actor="Estimator B",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        with pytest.raises(ValueError):
            approve_corrected_geometry_ledger(
                ledger, object_id="W_PARITY_STALE", approved_by="Estimator A",
                current_revision_hash=obj.revision_hash,  # stale — a correction landed since
            )

    def test_apply_correction_event_has_no_equivalent_staleness_risk_within_one_call(self):
        # apply_correction_event() always operates on the live `building` object
        # passed into the same call — there's no cached/stale reference for a
        # revision-hash parameter to protect against here, unlike paths 2/3 which
        # are called independently, potentially much later, against a ledger/
        # building state that may have moved on in between.
        bldg = _building_with_wall(source_sheet_label="WD-01")
        event = CorrectionEvent(
            correction_id="CORR-PARITY-LIVE", object_id="W_PARITY_1", object_type="wall",
            action=CorrectionAction.APPROVE_QUANTITY.value, field_name="authority_status",
            old_value="provisional", new_value="firm",
            reason="Verified against the exact live state just read", actor="Estimator A",
        )
        # No revision hash is passed or needed — `bldg` IS the live state.
        bldg, _ = apply_correction_event(bldg, event)
        assert bldg.levels[0].walls[0].authority_status == AuthorityStatus.FIRM.value
