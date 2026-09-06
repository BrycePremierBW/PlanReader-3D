"""tests/editable_3d/test_editable_3d_quantity_staleness.py — PR D.1 Test Suite.

Verifies the bridge between geometry corrections and PR B.4's TakeoffOutputRow:
a correction to an object must stale out every TakeoffOutputRow whose geometry_ref
points at it, without deleting the old row, and while preserving its old fingerprint
for audit.
"""
from __future__ import annotations

import json

from pb_takeoff_output_authority import TakeoffSourceType, create_takeoff_output_row
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    QuantityInvalidationResult,
    invalidate_stale_quantities_for_corrections,
)


def _make_wall(object_id="WALL-STALE-1"):
    return EditableGeometryObject(
        object_id=object_id,
        object_type=EditableObjectType.WALL.value,
        source_page=2,
        source_sheet="WD-02",
        geometry_ref=object_id,
        level_id="LEVEL-1",
        room_id="ROOM-1",
        coordinates_or_measurements={"length": 5.0, "height": 2.7},
        authority_status="provisional",
        revision_hash="GENESIS",
    )


class TestStaleQuantityLosesPublishability:
    def test_stale_quantity_becomes_not_publishable(self):
        row = create_takeoff_output_row(
            quantity_id="QTY-STALE-1",
            description="Master Bedroom Wall",
            value=13.5,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="WALL-STALE-1",
            dimension_text_id="DIM-1",
        )
        assert row.is_publishable is True

        results = invalidate_stale_quantities_for_corrections([row], corrected_object_ids=["WALL-STALE-1"])
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, QuantityInvalidationResult)
        assert result.was_invalidated is True
        assert result.new_row.is_publishable is False
        assert "stale_after_geometry_correction" in result.new_row.blocking_reasons

    def test_unaffected_row_is_not_marked_stale(self):
        row = create_takeoff_output_row(
            quantity_id="QTY-UNAFFECTED-1",
            description="Unrelated Wall",
            value=8.0,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=1,
            source_sheet="WD-01",
            geometry_ref="WALL-OTHER-1",
            dimension_text_id="DIM-2",
        )
        results = invalidate_stale_quantities_for_corrections([row], corrected_object_ids=["WALL-STALE-1"])
        assert results[0].was_invalidated is False
        assert results[0].new_row.is_publishable is True


class TestOldRowsPreservedForAudit:
    def test_stale_quantity_keeps_old_fingerprint(self):
        row = create_takeoff_output_row(
            quantity_id="QTY-STALE-2",
            description="Bedroom 2 Wall",
            value=10.0,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=3,
            source_sheet="WD-03",
            geometry_ref="WALL-STALE-2",
            dimension_text_id="DIM-3",
        )
        original_fingerprint = row.compute_fingerprint()

        results = invalidate_stale_quantities_for_corrections([row], corrected_object_ids=["WALL-STALE-2"])
        result = results[0]

        assert result.old_fingerprint == original_fingerprint
        # The old row object itself is untouched and still recoverable for audit.
        assert result.old_row is row
        assert result.old_row.is_publishable is True
        assert result.old_row.compute_fingerprint() == original_fingerprint
        # The fingerprint is computed over core commercial fields (value, source_type,
        # authority_status, ...), not is_publishable/blocking_reasons, so staling a row
        # does not change its fingerprint — that's what makes it useful for audit: it
        # proves the underlying measurement is unchanged even though publishability is.
        assert result.new_row.compute_fingerprint() == original_fingerprint
        assert result.new_row.is_publishable is False

    def test_invalidation_does_not_delete_or_mutate_input_rows(self):
        row = create_takeoff_output_row(
            quantity_id="QTY-STALE-3",
            description="Ensuite Wall",
            value=6.0,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=4,
            source_sheet="WD-04",
            geometry_ref="WALL-STALE-3",
            dimension_text_id="DIM-4",
        )
        rows = [row]
        invalidate_stale_quantities_for_corrections(rows, corrected_object_ids=["WALL-STALE-3"])
        # The original list and row are never mutated in place.
        assert rows[0] is row
        assert rows[0].is_publishable is True


class TestLedgerIntegrationEndToEnd:
    def test_ledger_correction_drives_takeoff_row_staleness(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())

        row = create_takeoff_output_row(
            quantity_id="QTY-E2E-1",
            description="Living Room Wall",
            value=13.5,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="WALL-STALE-1",
            dimension_text_id="DIM-E2E-1",
        )
        assert row.is_publishable is True

        outcome = ledger.apply_correction(
            correction_id="CORR-E2E-1",
            object_id="WALL-STALE-1",
            field=CorrectionField.LENGTH.value,
            new_value=5.6,
            reason="Remeasured on site",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
            affected_quantity_ids=["QTY-E2E-1"],
        )
        assert outcome.ok is True

        results = ledger.invalidate_takeoff_rows([row])
        assert results[0].was_invalidated is True
        assert results[0].new_row.is_publishable is False


class TestQuantityInvalidationResultSerializable:
    def test_results_are_json_serializable_via_row_to_dict(self):
        row = create_takeoff_output_row(
            quantity_id="QTY-JSON-STALE",
            description="Garage Wall",
            value=20.0,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=5,
            source_sheet="WD-05",
            geometry_ref="WALL-JSON-STALE",
            dimension_text_id="DIM-5",
        )
        results = invalidate_stale_quantities_for_corrections([row], corrected_object_ids=["WALL-JSON-STALE"])
        encoded = json.dumps(results[0].new_row.to_dict())
        decoded = json.loads(encoded)
        assert decoded["is_publishable"] is False
        assert "stale_after_geometry_correction" in decoded["blocking_reasons"]
