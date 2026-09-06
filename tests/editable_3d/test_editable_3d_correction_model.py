"""tests/editable_3d/test_editable_3d_correction_model.py — PR D.1 Test Suite.

Verifies the correction event contract itself: validation, fail-closed rejection of
malformed corrections, append-only ledger behaviour, and source-trace preservation.
"""
from __future__ import annotations

import json
import math

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    create_correction_event,
)


def _make_wall(object_id="WALL-1", **overrides):
    defaults = dict(
        object_id=object_id,
        object_type=EditableObjectType.WALL.value,
        source_page=3,
        source_sheet="WD-03",
        geometry_ref=object_id,
        level_id="LEVEL-1",
        room_id="ROOM-1",
        coordinates_or_measurements={"length": 5.0, "height": 2.7},
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS-HASH",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


class TestCorrectionEventCreatesRevision:
    def test_correction_event_creates_new_revision_hash(self):
        outcome = create_correction_event(
            correction_id="CORR-1",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.4,
            reason="Remeasured against figured dimension",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is True
        assert outcome.event.new_revision_hash != "GENESIS-HASH"
        assert outcome.event.previous_revision_hash == "GENESIS-HASH"
        assert outcome.blocking_reasons == []


class TestCorrectionNotSameAsApproval:
    def test_user_correction_does_not_equal_approval(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        outcome = ledger.apply_correction(
            correction_id="CORR-2",
            object_id="WALL-1",
            field=CorrectionField.HEIGHT.value,
            new_value=3.0,
            reason="Corrected from site measure",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        assert outcome.event.requires_reapproval is True

        obj = ledger.get_object("WALL-1")
        assert obj.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert obj.authority_status != AuthorityStatus.FIRM.value


class TestInvalidCorrectionsFailClosed:
    def test_nan_new_value_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-NAN",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=math.nan,
            reason="bad data",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert outcome.event is None
        assert any("finite" in r.lower() for r in outcome.blocking_reasons)

    def test_infinite_new_value_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-INF",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.HEIGHT.value,
            old_value=2.7,
            new_value=math.inf,
            reason="bad data",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("finite" in r.lower() for r in outcome.blocking_reasons)

    def test_negative_length_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-NEG",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=-2.0,
            reason="bad data",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("negative" in r.lower() for r in outcome.blocking_reasons)

    def test_zero_area_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-ZERO",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.AREA.value,
            old_value=13.5,
            new_value=0.0,
            reason="bad data",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("zero" in r.lower() for r in outcome.blocking_reasons)

    def test_missing_actor_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-NO-ACTOR",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("actor" in r.lower() for r in outcome.blocking_reasons)

    def test_missing_reason_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-NO-REASON",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("reason" in r.lower() for r in outcome.blocking_reasons)

    def test_unsupported_field_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-BAD-FIELD",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field="favourite_colour",
            old_value="blue",
            new_value="red",
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("unsupported" in r.lower() for r in outcome.blocking_reasons)

    def test_missing_object_id_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-NO-OBJ",
            object_id="",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("object_id" in r.lower() for r in outcome.blocking_reasons)

    def test_missing_previous_revision_hash_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-NO-PREV",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash=None,
        )
        assert outcome.ok is False
        assert any("previous_revision_hash" in r.lower() for r in outcome.blocking_reasons)

    def test_unknown_object_type_without_manual_review_blocks(self):
        outcome = create_correction_event(
            correction_id="CORR-UNKNOWN-TYPE",
            object_id="MYSTERY-1",
            object_type="unknown",
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is False
        assert any("manual_review" in r.lower() for r in outcome.blocking_reasons)

    def test_unknown_object_type_with_manual_review_passes(self):
        outcome = create_correction_event(
            correction_id="CORR-UNKNOWN-TYPE-OK",
            object_id="MYSTERY-1",
            object_type="unknown",
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
            manual_review=True,
        )
        assert outcome.ok is True

    def test_rejected_correction_shape(self):
        outcome = create_correction_event(
            correction_id="CORR-SHAPE",
            object_id="",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="",
            actor="",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash=None,
        )
        assert outcome.ok is False
        assert isinstance(outcome.blocking_reasons, list)
        assert len(outcome.blocking_reasons) > 1  # multiple independent violations collected


class TestAffectedQuantityAndSourcePreservation:
    def test_affected_quantity_ids_are_preserved(self):
        outcome = create_correction_event(
            correction_id="CORR-QTY",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
            previous_revision_hash="GENESIS-HASH",
            affected_quantity_ids=["QTY-1", "QTY-2"],
        )
        assert outcome.ok is True
        assert outcome.event.affected_quantity_ids == ["QTY-1", "QTY-2"]

    def test_correction_source_is_preserved(self):
        outcome = create_correction_event(
            correction_id="CORR-SRC",
            object_id="WALL-1",
            object_type=EditableObjectType.WALL.value,
            field=CorrectionField.LENGTH.value,
            old_value=5.0,
            new_value=5.5,
            reason="valid reason",
            actor="Estimator A",
            source=CorrectionSource.BENCHMARK_REVIEW.value,
            previous_revision_hash="GENESIS-HASH",
        )
        assert outcome.ok is True
        assert outcome.event.source == CorrectionSource.BENCHMARK_REVIEW.value

    def test_source_page_sheet_trace_is_preserved_after_correction(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall(source_page=7, source_sheet="WD-07"))
        ledger.apply_correction(
            correction_id="CORR-TRACE",
            object_id="WALL-1",
            field=CorrectionField.LENGTH.value,
            new_value=6.0,
            reason="site remeasure",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_2D.value,
        )
        obj = ledger.get_object("WALL-1")
        assert obj.source_page == 7
        assert obj.source_sheet == "WD-07"
        assert obj.geometry_ref == "WALL-1"


class TestApprovalRecordsAttribution:
    def test_approved_corrected_geometry_records_approved_by_and_approved_at(self):
        from pb_editable_3d_correction_model import approve_corrected_geometry

        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        outcome = ledger.apply_correction(
            correction_id="CORR-APPROVE-1",
            object_id="WALL-1",
            field=CorrectionField.HEIGHT.value,
            new_value=3.1,
            reason="site remeasure",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        new_hash = outcome.event.new_revision_hash

        result = approve_corrected_geometry(
            ledger,
            object_id="WALL-1",
            approved_by="Lead Estimator Bryce",
            current_revision_hash=new_hash,
            approved_at="2026-09-07T02:00:00Z",
        )
        assert result.approved_by == "Lead Estimator Bryce"
        assert result.approved_at == "2026-09-07T02:00:00Z"
        assert result.authority_status == AuthorityStatus.FIRM.value

        obj = ledger.get_object("WALL-1")
        assert obj.authority_status == AuthorityStatus.FIRM.value

    def test_approval_does_not_erase_correction_history(self):
        from pb_editable_3d_correction_model import approve_corrected_geometry

        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        outcome = ledger.apply_correction(
            correction_id="CORR-APPROVE-2",
            object_id="WALL-1",
            field=CorrectionField.HEIGHT.value,
            new_value=3.1,
            reason="site remeasure",
            actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        approve_corrected_geometry(
            ledger, object_id="WALL-1", approved_by="Bryce",
            current_revision_hash=outcome.event.new_revision_hash,
        )
        assert len(ledger.events_for_object("WALL-1")) == 1
        assert ledger.events_for_object("WALL-1")[0].correction_id == "CORR-APPROVE-2"

    def test_approval_rejects_stale_revision(self):
        from pb_editable_3d_correction_model import approve_corrected_geometry

        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                ledger, object_id="WALL-1", approved_by="Bryce",
                current_revision_hash="SOME-OLD-STALE-HASH",
            )


class TestCorrectionLedgerAppendOnlyAndSerializable:
    def test_correction_ledger_is_append_only(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        ledger.apply_correction(
            correction_id="CORR-A1",
            object_id="WALL-1",
            field=CorrectionField.LENGTH.value,
            new_value=5.5,
            reason="r1",
            actor="A",
            source=CorrectionSource.EDITOR_2D.value,
        )
        ledger.apply_correction(
            correction_id="CORR-A2",
            object_id="WALL-1",
            field=CorrectionField.HEIGHT.value,
            new_value=2.8,
            reason="r2",
            actor="A",
            source=CorrectionSource.EDITOR_2D.value,
        )
        assert len(ledger.events) == 2
        assert ledger.events[0].correction_id == "CORR-A1"
        assert ledger.events[1].correction_id == "CORR-A2"

        # events is a read-only view: mutating it must not affect the ledger.
        with pytest.raises((AttributeError, TypeError)):
            ledger.events.append("not allowed")  # tuple has no append

    def test_correction_ledger_serializes_to_json(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        ledger.apply_correction(
            correction_id="CORR-JSON-1",
            object_id="WALL-1",
            field=CorrectionField.LENGTH.value,
            new_value=5.9,
            reason="r1",
            actor="A",
            source=CorrectionSource.EDITOR_2D.value,
        )
        encoded = json.dumps(ledger.to_dict())
        decoded = json.loads(encoded)
        assert len(decoded["events"]) == 1
        assert decoded["events"][0]["correction_id"] == "CORR-JSON-1"
        assert decoded["events"][0]["new_value"] == 5.9


class TestReplayDeterminism:
    def test_replaying_corrections_is_deterministic(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(_make_wall())
        ledger.apply_correction(
            correction_id="CORR-R1", object_id="WALL-1",
            field=CorrectionField.LENGTH.value, new_value=5.5,
            reason="r1", actor="A", source=CorrectionSource.EDITOR_2D.value,
        )
        ledger.apply_correction(
            correction_id="CORR-R2", object_id="WALL-1",
            field=CorrectionField.HEIGHT.value, new_value=2.9,
            reason="r2", actor="A", source=CorrectionSource.EDITOR_3D.value,
        )
        live_hash = ledger.get_object("WALL-1").revision_hash
        replayed_hash = ledger.replay("WALL-1", genesis_hash="GENESIS-HASH")
        assert replayed_hash == live_hash

        # Replaying twice from the same event log must always agree.
        assert ledger.replay("WALL-1", genesis_hash="GENESIS-HASH") == replayed_hash
