"""tests/editable_3d/test_editable_3d_revision_invalidation.py — PR D.1 Test Suite.

Verifies that a geometry correction produces a new revision, and that specific kinds
of corrections (move, height change, finish tag change) each invalidate the geometry
object's revision hash independently and traceably.
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
)


def _make_object(object_id, object_type, **overrides):
    defaults = dict(
        object_id=object_id,
        object_type=object_type,
        source_page=5,
        source_sheet="WD-05",
        geometry_ref=object_id,
        level_id="LEVEL-1",
        room_id="ROOM-1",
        coordinates_or_measurements={"length": 4.0, "height": 2.7, "area": 10.8},
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


class TestMovingWallInvalidatesRevision:
    def test_moving_wall_invalidates_linked_quantity(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_object("WALL-MOVE-1", EditableObjectType.WALL.value))
        before_hash = ledger.get_object("WALL-MOVE-1").revision_hash

        outcome = ledger.apply_correction(
            correction_id="CORR-MOVE",
            object_id="WALL-MOVE-1",
            field=CorrectionField.COORDINATES.value,
            new_value=[[0.0, 0.0], [4.5, 0.0]],
            reason="Wall repositioned per site survey",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
            affected_quantity_ids=["QTY-WALL-MOVE-1"],
        )
        assert outcome.ok is True
        after = ledger.get_object("WALL-MOVE-1")
        assert after.revision_hash != before_hash
        assert outcome.event.affected_quantity_ids == ["QTY-WALL-MOVE-1"]


class TestHeightChangeInvalidatesArea:
    def test_changing_wall_height_invalidates_wall_area_quantity(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_object("WALL-H-1", EditableObjectType.WALL.value))
        before_hash = ledger.get_object("WALL-H-1").revision_hash

        outcome = ledger.apply_correction(
            correction_id="CORR-HEIGHT",
            object_id="WALL-H-1",
            field=CorrectionField.HEIGHT.value,
            new_value=3.2,
            reason="Ceiling height corrected from section",
            actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
            affected_quantity_ids=["QTY-WALL-H-1-AREA"],
        )
        assert outcome.ok is True
        after = ledger.get_object("WALL-H-1")
        assert after.revision_hash != before_hash
        assert after.coordinates_or_measurements["height"] == 3.2
        assert outcome.event.field == CorrectionField.HEIGHT.value


class TestFinishTagChangeInvalidatesSurface:
    def test_changing_finish_tag_invalidates_surface_takeoff_quantity(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_object(
            "SURF-1", EditableObjectType.SURFACE.value,
            coordinates_or_measurements={"finish_tag": "PB01"},
        ))
        before_hash = ledger.get_object("SURF-1").revision_hash

        outcome = ledger.apply_correction(
            correction_id="CORR-FINISH",
            object_id="SURF-1",
            field=CorrectionField.FINISH_TAG.value,
            new_value="EC02",
            reason="Corrected from finishes schedule",
            actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
            affected_quantity_ids=["QTY-SURF-1"],
        )
        assert outcome.ok is True
        after = ledger.get_object("SURF-1")
        assert after.revision_hash != before_hash
        assert after.coordinates_or_measurements["finish_tag"] == "EC02"


class TestEachCorrectionFieldIndependentlyInvalidates:
    @pytest.mark.parametrize(
        "field,new_value",
        [
            (CorrectionField.LENGTH.value, 6.0),
            (CorrectionField.PERIMETER.value, 18.0),
            (CorrectionField.OPENING_WIDTH.value, 0.9),
            (CorrectionField.OPENING_HEIGHT.value, 2.1),
            (CorrectionField.ROOM_ASSIGNMENT.value, "ROOM-2"),
            (CorrectionField.INCLUDE_EXCLUDE_STATUS.value, "excluded"),
            (CorrectionField.SOURCE_SHEET.value, "WD-09"),
            (CorrectionField.SOURCE_PAGE.value, 9),
            (CorrectionField.GEOMETRY_REF.value, "WALL-RENAMED-1"),
        ],
    )
    def test_each_supported_field_produces_a_new_revision(self, field, new_value):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_object("OBJ-MULTI-1", EditableObjectType.WALL.value))
        before_hash = ledger.get_object("OBJ-MULTI-1").revision_hash

        outcome = ledger.apply_correction(
            correction_id=f"CORR-{field}",
            object_id="OBJ-MULTI-1",
            field=field,
            new_value=new_value,
            reason=f"Correcting {field}",
            actor="Estimator A",
            source=CorrectionSource.MANUAL_ESTIMATOR_ENTRY.value,
        )
        assert outcome.ok is True, outcome.blocking_reasons
        after = ledger.get_object("OBJ-MULTI-1")
        assert after.revision_hash != before_hash
