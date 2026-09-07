"""tests/editable_3d/test_correction_not_approval.py — PR D.2 regression suite.

Fixes the defect where apply_correction_event() in pb_editable_3d_model.py (#147)
auto-approved every geometry correction: CHANGE_HEIGHT, MOVE_WALL, and ADD_OPENING
all immediately set authority_status=FIRM and approved_by=event.actor. Correction
and approval must be separate, explicit acts — this suite proves the fix.
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
    approve_corrected_geometry,
)


def _sample_building(
    authority_status: str = AuthorityStatus.PROVISIONAL.value,
    approved_by=None,
    approved_at=None,
) -> BuildingModel:
    wall = WallModel(
        wall_id="W_101",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(6.0, 0.0),
        length_m=6.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
        source_page_no=2,
        source_sheet_label="WD-02",
        authority_status=authority_status,
        approved_by=approved_by,
        approved_at=approved_at,
    )
    level = LevelModel(
        level_id="L_01",
        name="Ground Floor",
        elevation_m=0.0,
        ceiling_height_m=2.7,
        walls=[wall],
    )
    bldg = BuildingModel(building_id="BLDG_01", name="Test Building", levels=[level])
    bldg.compute_building_revision_hash()
    return bldg


_CORRECTION_CASES = [
    pytest.param(CorrectionAction.CHANGE_HEIGHT.value, "height_m", 3.0, id="change_height"),
    pytest.param(CorrectionAction.MOVE_WALL.value, "length_m", 7.0, id="move_wall"),
    pytest.param(
        CorrectionAction.ADD_OPENING.value,
        "openings",
        {
            "opening_id": "D_ENTRY",
            "opening_type": "door",
            "width_m": 0.9,
            "height_m": 2.1,
            "area_m2": 1.89,
            "deducts": True,
        },
        id="add_opening",
    ),
]


class TestCorrectionDoesNotAutoApprove:
    @pytest.mark.parametrize("action,field_name,new_value", _CORRECTION_CASES)
    def test_correction_does_not_set_authority_status_firm(self, action, field_name, new_value):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-FIRM-CHECK",
            object_id="W_101",
            object_type="wall",
            action=action,
            field_name=field_name,
            old_value=None,
            new_value=new_value,
            reason="Site remeasure",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        assert wall.authority_status != AuthorityStatus.FIRM.value

    @pytest.mark.parametrize("action,field_name,new_value", _CORRECTION_CASES)
    def test_correction_does_not_set_approved_by(self, action, field_name, new_value):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-APPROVED-BY-CHECK",
            object_id="W_101",
            object_type="wall",
            action=action,
            field_name=field_name,
            old_value=None,
            new_value=new_value,
            reason="Site remeasure",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        assert wall.approved_by is None

    @pytest.mark.parametrize("action,field_name,new_value", _CORRECTION_CASES)
    def test_correction_does_not_set_approved_at(self, action, field_name, new_value):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-APPROVED-AT-CHECK",
            object_id="W_101",
            object_type="wall",
            action=action,
            field_name=field_name,
            old_value=None,
            new_value=new_value,
            reason="Site remeasure",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        assert wall.approved_at is None

    def test_added_opening_is_not_auto_approved_either(self):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-OPENING-APPROVAL",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.ADD_OPENING.value,
            field_name="openings",
            old_value=None,
            new_value={
                "opening_id": "D_ENTRY",
                "opening_type": "door",
                "width_m": 0.9,
                "height_m": 2.1,
                "area_m2": 1.89,
                "deducts": True,
            },
            reason="Added entry door from door schedule",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        opening = updated.levels[0].walls[0].openings[0]
        assert opening.approval_status != AuthorityStatus.FIRM.value


class TestCorrectedGeometryRequiresSeparateApproval:
    def test_corrected_geometry_requires_separate_approval(self):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-REQUIRES-APPROVAL",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.1,
            reason="Aligned with structural section S-01",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert wall.approved_by is None
        assert wall.approved_at is None

    def test_approval_helper_can_approve_corrected_geometry_separately(self):
        bldg = _sample_building()
        correction = CorrectionEvent(
            correction_id="CORR-BEFORE-APPROVAL",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.1,
            reason="Aligned with structural section S-01",
            actor="Estimator A",
        )
        bldg, _ = apply_correction_event(bldg, correction)
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

        approval = CorrectionEvent(
            correction_id="CORR-SEPARATE-APPROVAL",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.APPROVE_QUANTITY.value,
            field_name="authority_status",
            old_value="review_required",
            new_value="firm",
            reason="Verified against structural section S-01",
            actor="Lead Estimator Bryce",
        )
        bldg, _ = apply_correction_event(bldg, approval)
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.FIRM.value
        assert wall.approved_by == "Lead Estimator Bryce"
        assert wall.approved_at is not None


class TestFurtherCorrectionInvalidatesPriorApproval:
    def test_correcting_a_previously_approved_wall_clears_the_approval(self):
        bldg = _sample_building(
            authority_status=AuthorityStatus.FIRM.value,
            approved_by="Estimator A",
            approved_at="2026-09-01T00:00:00Z",
        )
        event = CorrectionEvent(
            correction_id="CORR-INVALIDATE-APPROVAL",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.4,
            reason="Revised after further site visit",
            actor="Estimator B",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert wall.approved_by is None
        assert wall.approved_at is None


class TestStaleLinkedQuantityRemainsBlockedAfterCorrection:
    def test_stale_linked_quantity_remains_blocked_after_correction(self):
        from pb_takeoff_output_authority import TakeoffSourceType, create_takeoff_output_row
        from pb_editable_3d_correction_model import invalidate_stale_quantities_for_corrections

        bldg = _sample_building()
        row = create_takeoff_output_row(
            quantity_id="QTY-W101",
            description="Wall W101 Area",
            value=16.2,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2,
            source_sheet="WD-02",
            geometry_ref="W_101",
            dimension_text_id="DIM-W101",
        )
        assert row.is_publishable is True

        event = CorrectionEvent(
            correction_id="CORR-STALE-LINK",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.0,
            reason="Site remeasure",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        # The correction itself must not have quietly re-firmed the wall.
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

        results = invalidate_stale_quantities_for_corrections([row], corrected_object_ids=["W_101"])
        stale_row = results[0].new_row
        assert stale_row.is_publishable is False
        assert "stale_after_geometry_correction" in stale_row.blocking_reasons
        # The original row remains intact for audit.
        assert row.is_publishable is True


class TestCorrectionHistoryRemainsAuditable:
    def test_correction_event_fields_survive_application_unmutated(self):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-AUDIT-1",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.2,
            reason="Aligned with structural section S-02",
            actor="Estimator A",
            source="editor_3d",
        )
        snapshot = dict(
            correction_id=event.correction_id,
            object_id=event.object_id,
            reason=event.reason,
            actor=event.actor,
            old_value=event.old_value,
            new_value=event.new_value,
            created_at=event.created_at,
            source=event.source,
        )

        apply_correction_event(bldg, event)

        assert event.correction_id == snapshot["correction_id"]
        assert event.object_id == snapshot["object_id"]
        assert event.reason == snapshot["reason"]
        assert event.actor == snapshot["actor"]
        assert event.old_value == snapshot["old_value"]
        assert event.new_value == snapshot["new_value"]
        assert event.created_at == snapshot["created_at"]
        assert event.source == snapshot["source"]

    def test_recalculation_result_carries_audit_trail(self):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-AUDIT-2",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.2,
            reason="Aligned with structural section S-02",
            actor="Estimator A",
        )
        _, recals = apply_correction_event(bldg, event)
        assert len(recals) == 1
        rec = recals[0]
        assert rec.object_id == "W_101"
        assert rec.old_gross_m2 == pytest.approx(16.2)
        assert rec.new_gross_m2 != rec.old_gross_m2
        assert rec.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert rec.is_preflight_invalidated is True


class TestCorrectionNeverSetsUserApproved:
    @pytest.mark.parametrize("action,field_name,new_value", _CORRECTION_CASES)
    def test_correction_does_not_set_user_approved_status(self, action, field_name, new_value):
        bldg = _sample_building()
        event = CorrectionEvent(
            correction_id="CORR-NOT-USER-APPROVED",
            object_id="W_101",
            object_type="wall",
            action=action,
            field_name=field_name,
            old_value=None,
            new_value=new_value,
            reason="Site remeasure",
            actor="Estimator A",
        )
        updated, _ = apply_correction_event(bldg, event)
        wall = updated.levels[0].walls[0]
        assert wall.authority_status != "user_approved"


class TestApprovalIsRevisionHashGated:
    def test_approval_operates_against_the_latest_revision_hash(self):
        bldg = _sample_building()
        correction = CorrectionEvent(
            correction_id="CORR-LATEST-1",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.1,
            reason="Site remeasure",
            actor="Field Estimator",
        )
        bldg, _ = apply_correction_event(bldg, correction)
        wall = bldg.levels[0].walls[0]
        latest_hash = wall.revision_hash

        bldg = approve_corrected_geometry(
            bldg,
            object_id="W_101",
            current_revision_hash=latest_hash,
            approved_by="Lead Estimator Bryce",
        )
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.FIRM.value
        assert wall.approved_by == "Lead Estimator Bryce"
        assert wall.approved_at is not None

    def test_approval_against_a_stale_revision_fails_closed(self):
        bldg = _sample_building()
        wall = bldg.levels[0].walls[0]
        stale_hash = wall.revision_hash

        correction = CorrectionEvent(
            correction_id="CORR-STALE-APPROVAL",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.4,
            reason="Site remeasure",
            actor="Field Estimator",
        )
        bldg, _ = apply_correction_event(bldg, correction)

        with pytest.raises(ValueError):
            approve_corrected_geometry(
                bldg,
                object_id="W_101",
                current_revision_hash=stale_hash,
                approved_by="Lead Estimator Bryce",
            )

        # The stale approval attempt must not have mutated anything.
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert wall.approved_by is None

    def test_approval_requires_source_trace(self):
        bldg = _sample_building()
        bldg.levels[0].walls[0].source_sheet_label = ""
        wall = bldg.levels[0].walls[0]
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                bldg,
                object_id="W_101",
                current_revision_hash=wall.revision_hash,
                approved_by="Lead Estimator Bryce",
            )

    def test_approval_requires_approved_by(self):
        bldg = _sample_building()
        wall = bldg.levels[0].walls[0]
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                bldg, object_id="W_101", current_revision_hash=wall.revision_hash, approved_by="",
            )

    def test_approval_of_unknown_object_id_fails_closed(self):
        bldg = _sample_building()
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                bldg, object_id="NOT-A-REAL-WALL", current_revision_hash="anything", approved_by="Estimator A",
            )


class TestSecondCorrectionAfterApprovalMakesQuantitiesStaleAgain:
    def test_second_correction_after_approval_reverts_to_review_required(self):
        bldg = _sample_building()
        first = CorrectionEvent(
            correction_id="CORR-CHAIN-1",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.0,
            reason="Site remeasure",
            actor="Field Estimator",
        )
        bldg, _ = apply_correction_event(bldg, first)
        wall = bldg.levels[0].walls[0]

        bldg = approve_corrected_geometry(
            bldg, object_id="W_101", current_revision_hash=wall.revision_hash, approved_by="Lead Estimator Bryce",
        )
        wall = bldg.levels[0].walls[0]
        assert wall.authority_status == AuthorityStatus.FIRM.value
        approved_hash = wall.revision_hash

        second = CorrectionEvent(
            correction_id="CORR-CHAIN-2",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=3.0,
            new_value=3.3,
            reason="Further site remeasure",
            actor="Field Estimator",
        )
        bldg, _ = apply_correction_event(bldg, second)
        wall = bldg.levels[0].walls[0]

        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert wall.approved_by is None
        assert wall.approved_at is None
        assert wall.revision_hash != approved_hash

        # Approving against the now-superseded approved_hash must fail closed.
        with pytest.raises(ValueError):
            approve_corrected_geometry(
                bldg, object_id="W_101", current_revision_hash=approved_hash, approved_by="Lead Estimator Bryce",
            )


class TestCorrectionAndApprovalActorsCanDiffer:
    def test_correction_actor_and_approval_actor_can_be_different_people(self):
        bldg = _sample_building()
        correction = CorrectionEvent(
            correction_id="CORR-DIFFERENT-ACTORS",
            object_id="W_101",
            object_type="wall",
            action=CorrectionAction.CHANGE_HEIGHT.value,
            field_name="height_m",
            old_value=2.7,
            new_value=3.1,
            reason="Site remeasure",
            actor="Field Estimator Jones",
        )
        bldg, _ = apply_correction_event(bldg, correction)
        wall = bldg.levels[0].walls[0]
        assert wall.approved_by is None

        bldg = approve_corrected_geometry(
            bldg, object_id="W_101", current_revision_hash=wall.revision_hash, approved_by="Lead Estimator Bryce",
        )
        wall = bldg.levels[0].walls[0]
        assert wall.approved_by == "Lead Estimator Bryce"
        assert wall.approved_by != "Field Estimator Jones"
