"""tests/editable_3d/test_editable_3d_object_traceability.py — PR D.4 test suite.

Every commercially relevant 3D object must be able to answer: what sheet/page/
region created me, what scale and dimension evidence backs me, which corrections
changed me, which quantities depend on me, and who (if anyone) approved me — all the
way through correction, serialization, and round-trip deserialization.
"""
from __future__ import annotations

import json

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import TakeoffSourceType, create_takeoff_output_row
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    approve_corrected_geometry,
    resolve_dependent_quantities,
)


def _wall(**overrides):
    defaults = dict(
        object_id="WALL-1",
        object_type=EditableObjectType.WALL.value,
        source_file_id="FILE-001",
        source_page=2,
        source_sheet="WD-02",
        source_region="A3:C7",
        geometry_ref="VEC-WALL-1",
        scale_id="SCALE-P2-1_100",
        dimension_text_ids=["DIM-1"],
        confidence=0.95,
        coordinates_or_measurements={"length": 5.8, "height": 2.7},
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


def _opening(**overrides):
    defaults = dict(
        object_id="OPEN-1",
        object_type=EditableObjectType.OPENING.value,
        source_file_id="FILE-001",
        source_page=2,
        source_sheet="WD-02",
        geometry_ref="VEC-OPEN-1",
        dimension_text_ids=["DIM-DOOR-1"],
        coordinates_or_measurements={"opening_width": 0.9, "opening_height": 2.1},
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


class TestSourceTraceRetained:
    def test_wall_retains_source_trace(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        obj = ledger.get_object("WALL-1")
        assert obj.source_file_id == "FILE-001"
        assert obj.source_page == 2
        assert obj.source_sheet == "WD-02"
        assert obj.source_region == "A3:C7"
        assert obj.scale_id == "SCALE-P2-1_100"
        assert obj.dimension_text_ids == ["DIM-1"]

    def test_opening_retains_source_trace(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_opening())
        obj = ledger.get_object("OPEN-1")
        assert obj.source_page == 2
        assert obj.source_sheet == "WD-02"
        assert obj.dimension_text_ids == ["DIM-DOOR-1"]


class TestCorrectedObjectRetainsOriginalSourceAndCorrectionTrace:
    def test_corrected_wall_retains_original_source_and_correction_trace(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())

        outcome1 = ledger.apply_correction(
            correction_id="CORR-1", object_id="WALL-1",
            field=CorrectionField.LENGTH.value, new_value=6.0,
            reason="Site remeasure", actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome1.ok is True
        outcome2 = ledger.apply_correction(
            correction_id="CORR-2", object_id="WALL-1",
            field=CorrectionField.HEIGHT.value, new_value=3.0,
            reason="Structural section correction", actor="Estimator B",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
        )
        assert outcome2.ok is True

        obj = ledger.get_object("WALL-1")
        # Original evidence unchanged.
        assert obj.source_file_id == "FILE-001"
        assert obj.source_page == 2
        assert obj.source_sheet == "WD-02"
        assert obj.source_region == "A3:C7"
        # Correction trace accumulates, in order, never replaced.
        assert obj.correction_ids == ["CORR-1", "CORR-2"]


class TestGeometryRefTracksCurrentVsOriginal:
    def test_new_revision_changes_current_geometry_ref(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        obj = ledger.get_object("WALL-1")
        assert obj.original_geometry_ref == "VEC-WALL-1"
        assert obj.geometry_ref == "VEC-WALL-1"

        outcome = ledger.apply_correction(
            correction_id="CORR-RELINK", object_id="WALL-1",
            field=CorrectionField.GEOMETRY_REF.value, new_value="VEC-WALL-1-REDRAWN",
            reason="Re-linked to redrawn vector geometry", actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        obj = ledger.get_object("WALL-1")
        assert obj.geometry_ref == "VEC-WALL-1-REDRAWN"

    def test_original_evidence_is_not_destroyed_by_a_geometry_ref_correction(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())

        ledger.apply_correction(
            correction_id="CORR-RELINK-2", object_id="WALL-1",
            field=CorrectionField.GEOMETRY_REF.value, new_value="VEC-WALL-1-REDRAWN",
            reason="Re-linked to redrawn vector geometry", actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        obj = ledger.get_object("WALL-1")
        # original_geometry_ref is captured once at registration and never mutated,
        # even though the "current" geometry_ref moved on.
        assert obj.original_geometry_ref == "VEC-WALL-1"
        assert obj.geometry_ref != obj.original_geometry_ref
        assert obj.source_file_id == "FILE-001"
        assert obj.source_page == 2
        assert obj.source_sheet == "WD-02"


class TestDependentQuantityIdsResolve:
    def test_dependent_quantity_ids_resolve_to_real_rows(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())

        row1 = create_takeoff_output_row(
            quantity_id="QTY-WALL-1-GROSS", description="Wall 1 Gross Area", value=15.66,
            unit="m²", source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2, source_sheet="WD-02", geometry_ref="WALL-1", dimension_text_id="DIM-1",
        )
        row2 = create_takeoff_output_row(
            quantity_id="QTY-WALL-1-NET", description="Wall 1 Net Area", value=13.77,
            unit="m²", source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2, source_sheet="WD-02", geometry_ref="WALL-1", dimension_text_id="DIM-1",
        )
        unrelated_row = create_takeoff_output_row(
            quantity_id="QTY-ROOM-1", description="Room 1 Floor Area", value=20.0,
            unit="m²", source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=1, source_sheet="WD-01", geometry_ref="ROOM-1", dimension_text_id="DIM-R1",
        )

        ledger.link_dependent_quantities("WALL-1", ["QTY-WALL-1-GROSS", "QTY-WALL-1-NET"])
        obj = ledger.get_object("WALL-1")
        assert obj.dependent_quantity_ids == ["QTY-WALL-1-GROSS", "QTY-WALL-1-NET"]

        resolved = resolve_dependent_quantities(obj, [row1, row2, unrelated_row])
        resolved_ids = {r.quantity_id for r in resolved}
        assert resolved_ids == {"QTY-WALL-1-GROSS", "QTY-WALL-1-NET"}
        assert "QTY-ROOM-1" not in resolved_ids

    def test_linking_is_idempotent_and_deduplicates(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        ledger.link_dependent_quantities("WALL-1", ["QTY-A", "QTY-B"])
        ledger.link_dependent_quantities("WALL-1", ["QTY-B", "QTY-C"])
        obj = ledger.get_object("WALL-1")
        assert obj.dependent_quantity_ids == ["QTY-A", "QTY-B", "QTY-C"]


class TestUnknownSourceGeometryCannotBecomeCommercial:
    def test_object_with_no_source_trace_at_all_starts_provisional_not_firm(self):
        obj = EditableGeometryObject(
            object_id="MYSTERY-1",
            object_type=EditableObjectType.WALL.value,
            revision_hash="GENESIS",
        )
        assert obj.authority_status != AuthorityStatus.FIRM.value
        assert obj.source_page is None
        assert obj.source_sheet is None


class TestModelObjectWithoutSourceTraceBlocksApproval:
    def test_approval_blocks_when_source_sheet_missing(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall(source_sheet=None))
        obj = ledger.get_object("WALL-1")
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                ledger, object_id="WALL-1", approved_by="Lead Estimator Bryce",
                current_revision_hash=obj.revision_hash,
            )

    def test_approval_blocks_when_source_page_missing(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall(source_page=None))
        obj = ledger.get_object("WALL-1")
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                ledger, object_id="WALL-1", approved_by="Lead Estimator Bryce",
                current_revision_hash=obj.revision_hash,
            )

    def test_approval_succeeds_and_persists_approved_by_and_approved_at_when_trace_present(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        obj = ledger.get_object("WALL-1")

        result = approve_corrected_geometry(
            ledger, object_id="WALL-1", approved_by="Lead Estimator Bryce",
            current_revision_hash=obj.revision_hash, approved_at="2026-09-07T03:00:00Z",
        )
        assert result.approved_by == "Lead Estimator Bryce"

        obj = ledger.get_object("WALL-1")
        assert obj.approved_by == "Lead Estimator Bryce"
        assert obj.approved_at == "2026-09-07T03:00:00Z"
        assert obj.authority_status == AuthorityStatus.FIRM.value

    def test_correcting_approved_geometry_clears_approved_by_and_approved_at(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        obj = ledger.get_object("WALL-1")
        approve_corrected_geometry(
            ledger, object_id="WALL-1", approved_by="Lead Estimator Bryce",
            current_revision_hash=obj.revision_hash,
        )
        obj = ledger.get_object("WALL-1")
        assert obj.approved_by == "Lead Estimator Bryce"

        ledger.apply_correction(
            correction_id="CORR-AFTER-APPROVAL", object_id="WALL-1",
            field=CorrectionField.LENGTH.value, new_value=6.2,
            reason="Further site correction", actor="Estimator C",
            source=CorrectionSource.EDITOR_3D.value,
        )
        obj = ledger.get_object("WALL-1")
        assert obj.approved_by is None
        assert obj.approved_at is None
        assert obj.authority_status == AuthorityStatus.REVIEW_REQUIRED.value


class TestSerializationPreservesTraceability:
    def test_to_dict_includes_every_traceability_field(self):
        obj = _wall()
        d = obj.to_dict()
        for key in (
            "object_id", "object_type", "source_file_id", "source_page", "source_sheet",
            "source_region", "original_geometry_ref", "geometry_ref", "scale_id",
            "dimension_text_ids", "authority_status", "confidence", "revision_hash",
            "correction_ids", "dependent_quantity_ids", "approved_by", "approved_at",
        ):
            assert key in d, f"Missing traceability field in to_dict(): {key}"

    def test_to_dict_round_trips_through_json(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        ledger.apply_correction(
            correction_id="CORR-JSON-1", object_id="WALL-1",
            field=CorrectionField.LENGTH.value, new_value=6.0,
            reason="Site remeasure", actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        obj = ledger.get_object("WALL-1")
        encoded = json.dumps(obj.to_dict())
        decoded = json.loads(encoded)
        assert decoded["correction_ids"] == ["CORR-JSON-1"]
        assert decoded["revision_hash"] == obj.revision_hash


class TestRoundTripDeserializationPreservesRevisionRelationships:
    def test_from_dict_reconstructs_an_equivalent_object(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_wall())
        ledger.apply_correction(
            correction_id="CORR-ROUNDTRIP", object_id="WALL-1",
            field=CorrectionField.LENGTH.value, new_value=6.1,
            reason="Site remeasure", actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        original = ledger.get_object("WALL-1")

        rehydrated = EditableGeometryObject.from_dict(original.to_dict())

        assert rehydrated.object_id == original.object_id
        assert rehydrated.revision_hash == original.revision_hash
        assert rehydrated.original_geometry_ref == original.original_geometry_ref
        assert rehydrated.geometry_ref == original.geometry_ref
        assert rehydrated.correction_ids == original.correction_ids
        assert rehydrated.coordinates_or_measurements == original.coordinates_or_measurements
        assert rehydrated.authority_status == original.authority_status

    def test_from_dict_handles_missing_optional_fields_safely(self):
        rehydrated = EditableGeometryObject.from_dict({
            "object_id": "WALL-MINIMAL",
            "object_type": "wall",
            "revision_hash": "GENESIS",
        })
        assert rehydrated.object_id == "WALL-MINIMAL"
        assert rehydrated.correction_ids == []
        assert rehydrated.dependent_quantity_ids == []
        assert rehydrated.dimension_text_ids == []
        assert rehydrated.approved_by is None
