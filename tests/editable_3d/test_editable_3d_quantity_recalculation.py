"""tests/editable_3d/test_editable_3d_quantity_recalculation.py — PR D.3 test suite.

When geometry changes, PlanReader must not merely mark the old quantity stale — it
must recalculate the affected quantity from the corrected geometry and produce a
new, separate candidate row requiring its own review/approval. The old row is
preserved for audit; the new row is never auto-published.
"""
from __future__ import annotations

import math

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import TakeoffSourceType, create_takeoff_output_row
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
)
from pb_editable_3d_quantity_recalculation import (
    QuantityRecalculationResult,
    RecalculationTarget,
    recalculate_quantities_for_correction,
)


def _wall(object_id="WALL-1", length=5.8, height=2.7, openings=None, **overrides):
    defaults = dict(
        object_id=object_id,
        object_type=EditableObjectType.WALL.value,
        source_page=2,
        source_sheet="WD-02",
        geometry_ref=object_id,
        coordinates_or_measurements={
            "length": length,
            "height": height,
            "openings": openings or [],
        },
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


def _apply_length_correction(ledger, obj, new_length, correction_id="CORR-1"):
    ledger.register_object(obj)
    outcome = ledger.apply_correction(
        correction_id=correction_id,
        object_id=obj.object_id,
        field=CorrectionField.LENGTH.value,
        new_value=new_length,
        reason="Site remeasure",
        actor="Estimator A",
        source=CorrectionSource.EDITOR_3D.value,
    )
    assert outcome.ok is True, outcome.blocking_reasons
    return outcome.event, ledger.get_object(obj.object_id)


class TestWallLengthRecalculation:
    def test_changing_wall_length_recalculates_wall_quantity(self):
        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(ledger, _wall(length=5.8, height=2.7), 6.0)

        results = recalculate_quantities_for_correction(event, obj_after)
        by_target = {r.target: r for r in results}

        assert RecalculationTarget.WALL_GROSS_AREA.value in by_target
        gross = by_target[RecalculationTarget.WALL_GROSS_AREA.value]
        assert gross.status == "recalculated"
        assert gross.old_value == pytest.approx(15.66)  # 5.8 * 2.7
        assert gross.new_value == pytest.approx(16.20)  # 6.0 * 2.7
        assert gross.new_row is not None
        assert gross.new_row.is_publishable is False
        assert gross.new_row.authority_status == AuthorityStatus.REVIEW_REQUIRED.value


class TestWallHeightRecalculation:
    def test_changing_wall_height_recalculates_wall_area(self):
        ledger = Editable3DCorrectionLedger()
        obj = _wall(length=6.0, height=2.7)
        ledger.register_object(obj)
        outcome = ledger.apply_correction(
            correction_id="CORR-HEIGHT",
            object_id="WALL-1",
            field=CorrectionField.HEIGHT.value,
            new_value=3.0,
            reason="Structural section correction",
            actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("WALL-1")

        results = recalculate_quantities_for_correction(outcome.event, obj_after)
        by_target = {r.target: r for r in results}

        gross = by_target[RecalculationTarget.WALL_GROSS_AREA.value]
        assert gross.new_value == pytest.approx(18.0)  # 6.0 * 3.0
        net = by_target[RecalculationTarget.WALL_NET_AREA.value]
        assert net.new_value == pytest.approx(18.0)


class TestOpeningRecalculation:
    def test_changing_opening_size_recalculates_opening_area(self):
        opening = EditableGeometryObject(
            object_id="OPEN-1",
            object_type=EditableObjectType.OPENING.value,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="OPEN-1",
            coordinates_or_measurements={"opening_width": 0.9, "opening_height": 2.1},
            authority_status=AuthorityStatus.PROVISIONAL.value,
            revision_hash="GENESIS",
        )
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(opening)
        outcome = ledger.apply_correction(
            correction_id="CORR-OPEN-W",
            object_id="OPEN-1",
            field=CorrectionField.OPENING_WIDTH.value,
            new_value=1.2,
            reason="Corrected from door schedule",
            actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("OPEN-1")

        results = recalculate_quantities_for_correction(outcome.event, obj_after)
        area = next(r for r in results if r.target == RecalculationTarget.OPENING_AREA.value)
        assert area.new_value == pytest.approx(1.2 * 2.1)


class TestFinishTagRecalculation:
    def test_changing_finish_tag_reallocates_finish_quantity(self):
        surface = EditableGeometryObject(
            object_id="SURF-1",
            object_type=EditableObjectType.SURFACE.value,
            source_page=4,
            source_sheet="WD-04",
            geometry_ref="SURF-1",
            coordinates_or_measurements={"area": 22.0, "finish_tag": "PB01"},
            authority_status=AuthorityStatus.PROVISIONAL.value,
            revision_hash="GENESIS",
        )
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(surface)
        outcome = ledger.apply_correction(
            correction_id="CORR-FINISH",
            object_id="SURF-1",
            field=CorrectionField.FINISH_TAG.value,
            new_value="EC02",
            reason="Corrected from finishes schedule",
            actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("SURF-1")

        results = recalculate_quantities_for_correction(outcome.event, obj_after)
        finish = next(r for r in results if r.target == RecalculationTarget.FINISH_QUANTITY.value)
        assert finish.status == "recalculated"
        assert finish.new_row is not None
        assert finish.new_row.trade  # reclassified trade/scope is present
        assert "EC02" in finish.new_row.description


class TestOldQuantityPreservedAndStale:
    def test_old_quantity_preserved_and_marked_stale(self):
        old_row = create_takeoff_output_row(
            quantity_id="QTY-WALL-1",
            description="Wall 1 Gross Area",
            value=15.66,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="WALL-1",
            dimension_text_id="DIM-1",
        )
        assert old_row.is_publishable is True

        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(ledger, _wall(length=5.8, height=2.7), 6.0)

        results = recalculate_quantities_for_correction(event, obj_after, existing_rows=[old_row])
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)

        assert gross.old_row is not None
        assert gross.old_row.quantity_id == "QTY-WALL-1"
        assert gross.old_row.is_publishable is False
        assert "stale_after_geometry_correction" in gross.old_row.blocking_reasons
        # The truly original row (passed in) is never mutated.
        assert old_row.is_publishable is True

    def test_new_quantity_has_new_revision_hash_and_is_not_auto_approved(self):
        old_row = create_takeoff_output_row(
            quantity_id="QTY-WALL-2",
            description="Wall 2 Gross Area",
            value=15.66,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="WALL-2",
            dimension_text_id="DIM-2",
            revision_hash="GENESIS",
        )
        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(
            ledger, _wall(object_id="WALL-2", length=5.8, height=2.7), 6.0
        )
        results = recalculate_quantities_for_correction(event, obj_after, existing_rows=[old_row])
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)

        assert gross.new_row.revision_hash == event.new_revision_hash
        assert gross.new_row.revision_hash != old_row.revision_hash
        assert gross.new_row.is_publishable is False
        assert gross.new_row.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert gross.new_row.approved_by is None


class TestApprovalAppliesOnlyToNewRevision:
    def test_approving_the_old_row_does_not_approve_the_new_one(self):
        from pb_takeoff_output_authority import approve_takeoff_output_row

        old_row = create_takeoff_output_row(
            quantity_id="QTY-WALL-3",
            description="Wall 3 Gross Area",
            value=15.66,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="WALL-3",
            dimension_text_id="DIM-3",
        )
        approved_old = approve_takeoff_output_row(old_row, approved_by="Lead Estimator Bryce")
        assert approved_old.is_publishable is True

        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(
            ledger, _wall(object_id="WALL-3", length=5.8, height=2.7), 6.0
        )
        results = recalculate_quantities_for_correction(event, obj_after, existing_rows=[approved_old])
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)

        assert gross.new_row.is_publishable is False
        assert gross.new_row.approved_by is None


class TestUnrelatedQuantitiesRemainUnchanged:
    def test_unrelated_rows_are_not_affected(self):
        wall_row = create_takeoff_output_row(
            quantity_id="QTY-WALL-4",
            description="Wall 4 Gross Area",
            value=15.66,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="WALL-4",
            dimension_text_id="DIM-4",
        )
        unrelated_row = create_takeoff_output_row(
            quantity_id="QTY-ROOM-1",
            description="Room 1 Floor Area",
            value=20.0,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=1,
            source_sheet="WD-01",
            geometry_ref="ROOM-1",
            dimension_text_id="DIM-ROOM-1",
        )
        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(
            ledger, _wall(object_id="WALL-4", length=5.8, height=2.7), 6.0
        )
        results = recalculate_quantities_for_correction(
            event, obj_after, existing_rows=[wall_row, unrelated_row]
        )
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.old_row.quantity_id == "QTY-WALL-4"
        # The unrelated room row must never appear anywhere in this result set.
        touched_ids = {r.old_row.quantity_id for r in results if r.old_row is not None}
        assert "QTY-ROOM-1" not in touched_ids
        assert unrelated_row.is_publishable is True


class TestMalformedGeometryFailsClosed:
    @pytest.mark.parametrize("bad_height", [math.nan, math.inf, -math.inf, 0.0, -2.7])
    def test_nan_inf_zero_negative_geometry_blocks_recalculation(self, bad_height):
        obj = _wall(length=6.0, height=2.7)
        obj.coordinates_or_measurements["height"] = bad_height
        event, _ = _apply_length_correction(Editable3DCorrectionLedger(), _wall(length=5.8), 6.0)

        results = recalculate_quantities_for_correction(event, obj)
        by_target = {r.target: r for r in results}
        gross = by_target.get(RecalculationTarget.WALL_GROSS_AREA.value) or next(
            r for r in results if r.status == "manual_review_required"
        )
        assert gross.status == "manual_review_required"
        assert gross.new_row is None
        assert gross.reason

    def test_malformed_room_polygon_blocks_recalculation(self):
        room = EditableGeometryObject(
            object_id="ROOM-BAD",
            object_type=EditableObjectType.ROOM.value,
            source_page=1,
            source_sheet="WD-01",
            geometry_ref="ROOM-BAD",
            coordinates_or_measurements={"coordinates": [[0.0, 0.0], [4.0, 0.0]]},  # only 2 points
            authority_status=AuthorityStatus.PROVISIONAL.value,
            revision_hash="GENESIS",
        )
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(room)
        outcome = ledger.apply_correction(
            correction_id="CORR-ROOM-BAD",
            object_id="ROOM-BAD",
            field=CorrectionField.COORDINATES.value,
            new_value=[[0.0, 0.0], [4.0, 0.0]],
            reason="Room boundary correction",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("ROOM-BAD")

        results = recalculate_quantities_for_correction(outcome.event, obj_after)
        assert all(r.status == "manual_review_required" for r in results)
        assert all(r.new_row is None for r in results)


class TestUnsupportedGeometryReturnsManualReviewRequired:
    def test_unsupported_object_field_combination_returns_manual_review_required(self):
        stair = EditableGeometryObject(
            object_id="STAIR-1",
            object_type=EditableObjectType.STAIR.value,
            source_page=6,
            source_sheet="WD-06",
            geometry_ref="STAIR-1",
            coordinates_or_measurements={"length": 3.0},
            authority_status=AuthorityStatus.PROVISIONAL.value,
            revision_hash="GENESIS",
        )
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(stair)
        outcome = ledger.apply_correction(
            correction_id="CORR-STAIR",
            object_id="STAIR-1",
            field=CorrectionField.LENGTH.value,
            new_value=3.5,
            reason="Corrected stair run",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("STAIR-1")

        results = recalculate_quantities_for_correction(outcome.event, obj_after)
        assert len(results) == 1
        assert results[0].target == RecalculationTarget.MANUAL_REVIEW_REQUIRED.value
        assert results[0].status == "manual_review_required"
        assert results[0].new_row is None
        # No guessed number was fabricated.
        assert results[0].new_value is None


class TestSourceTraceAndAuditReferencePreserved:
    def test_recalculation_retains_source_page_and_sheet_trace(self):
        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(
            ledger, _wall(length=5.8, height=2.7, source_page=9, source_sheet="WD-09"), 6.0
        )
        results = recalculate_quantities_for_correction(event, obj_after)
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.new_row.source_page == 9
        assert gross.new_row.source_sheet == "WD-09"

    def test_recalculation_retains_correction_id_for_audit(self):
        ledger = Editable3DCorrectionLedger()
        event, obj_after = _apply_length_correction(
            ledger, _wall(length=5.8, height=2.7), 6.0, correction_id="CORR-AUDIT-99"
        )
        results = recalculate_quantities_for_correction(event, obj_after)
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.new_row.correction_id == "CORR-AUDIT-99"
        assert gross.correction_id == "CORR-AUDIT-99"
