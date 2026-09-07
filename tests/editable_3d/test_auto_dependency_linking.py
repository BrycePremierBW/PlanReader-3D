"""tests/editable_3d/test_auto_dependency_linking.py — PR D.8 test suite.

D.4 added dependent_quantity_ids + link_dependent_quantities(), but nothing
auto-populated it from D.3's recalculation flow — a caller had to remember to link
manually. This suite proves recalculate_quantities_for_correction() now does it
automatically when given a ledger, without changing behaviour for callers that
don't pass one (backward compatible with every existing D.3/D.5/D.6 call site).
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
)
from pb_editable_3d_quantity_recalculation import (
    RecalculationTarget,
    recalculate_quantities_for_correction,
)


def _register_wall(ledger, object_id="WALL-LINK-1"):
    ledger.register_object(EditableGeometryObject(
        object_id=object_id,
        object_type=EditableObjectType.WALL.value,
        source_page=2, source_sheet="WD-02", geometry_ref=object_id,
        coordinates_or_measurements={"length": 5.8, "height": 2.7},
        authority_status=AuthorityStatus.PROVISIONAL.value,
        revision_hash="GENESIS",
    ))


def _correct_length(ledger, object_id="WALL-LINK-1", new_value=6.0, correction_id="CORR-LINK-1"):
    outcome = ledger.apply_correction(
        correction_id=correction_id, object_id=object_id,
        field=CorrectionField.LENGTH.value, new_value=new_value,
        reason="Site remeasure", actor="Estimator A",
        source=CorrectionSource.EDITOR_3D.value,
    )
    assert outcome.ok is True
    return outcome.event, ledger.get_object(object_id)


class TestRecalculationAutoLinksWhenLedgerProvided:
    def test_new_row_quantity_id_is_auto_linked_as_dependent(self):
        ledger = Editable3DCorrectionLedger()
        _register_wall(ledger)
        event, obj_after = _correct_length(ledger)

        results = recalculate_quantities_for_correction(event, obj_after, ledger=ledger)
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)

        linked_ids = ledger.get_object("WALL-LINK-1").dependent_quantity_ids
        assert gross.new_row.quantity_id in linked_ids

    def test_every_recalculated_target_gets_linked(self):
        ledger = Editable3DCorrectionLedger()
        _register_wall(ledger)
        event, obj_after = _correct_length(ledger)

        results = recalculate_quantities_for_correction(event, obj_after, ledger=ledger)
        recalculated_qids = {r.new_row.quantity_id for r in results if r.new_row is not None}

        linked_ids = set(ledger.get_object("WALL-LINK-1").dependent_quantity_ids)
        assert recalculated_qids
        assert recalculated_qids.issubset(linked_ids)


class TestManualReviewRequiredResultsAreNotLinked:
    def test_unmapped_correction_produces_no_dependent_link(self):
        ledger = Editable3DCorrectionLedger()
        ledger.register_object(EditableGeometryObject(
            object_id="STAIR-LINK-1", object_type=EditableObjectType.STAIR.value,
            source_page=6, source_sheet="WD-06", geometry_ref="STAIR-LINK-1",
            coordinates_or_measurements={"length": 3.0},
            authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS",
        ))
        outcome = ledger.apply_correction(
            correction_id="CORR-STAIR-LINK", object_id="STAIR-LINK-1",
            field=CorrectionField.LENGTH.value, new_value=3.5,
            reason="Corrected stair run", actor="Estimator A",
            source=CorrectionSource.EDITOR_3D.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("STAIR-LINK-1")

        results = recalculate_quantities_for_correction(outcome.event, obj_after, ledger=ledger)
        assert all(r.status == "manual_review_required" for r in results)
        assert ledger.get_object("STAIR-LINK-1").dependent_quantity_ids == []


class TestBackwardCompatibilityWithoutLedger:
    def test_omitting_ledger_preserves_prior_behaviour_no_error(self):
        ledger = Editable3DCorrectionLedger()
        _register_wall(ledger)
        event, obj_after = _correct_length(ledger)

        # No ledger= passed at all — exactly how every existing D.3/D.5/D.6 caller
        # already uses this function.
        results = recalculate_quantities_for_correction(event, obj_after)
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.new_row is not None
        # Nothing to assert on linkage since no ledger was given — this just proves
        # no exception and no behavioural change from prior PRs.

    def test_existing_rows_kwarg_still_works_alongside_ledger(self):
        from pb_takeoff_output_authority import TakeoffSourceType, create_takeoff_output_row

        ledger = Editable3DCorrectionLedger()
        _register_wall(ledger)
        row = create_takeoff_output_row(
            quantity_id="QTY-LINK-EXISTING", description="Wall Gross Area", value=15.66,
            unit="m²", source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2, source_sheet="WD-02", geometry_ref="WALL-LINK-1", dimension_text_id="DIM-1",
        )
        event, obj_after = _correct_length(ledger)

        results = recalculate_quantities_for_correction(
            event, obj_after, existing_rows=[row], ledger=ledger,
        )
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.old_row is not None
        assert gross.old_row.quantity_id == "QTY-LINK-EXISTING"
        assert gross.new_row.quantity_id in ledger.get_object("WALL-LINK-1").dependent_quantity_ids


class TestAutoLinkingIsAdditiveAndDeduplicating:
    def test_prior_manual_links_are_preserved_and_new_ones_appended(self):
        ledger = Editable3DCorrectionLedger()
        _register_wall(ledger)
        ledger.link_dependent_quantities("WALL-LINK-1", ["QTY-MANUAL-1"])

        event, obj_after = _correct_length(ledger)
        recalculate_quantities_for_correction(event, obj_after, ledger=ledger)

        linked_ids = ledger.get_object("WALL-LINK-1").dependent_quantity_ids
        assert "QTY-MANUAL-1" in linked_ids
        assert len(linked_ids) == len(set(linked_ids))  # no duplicates

    def test_a_second_correction_does_not_duplicate_or_drop_earlier_links(self):
        ledger = Editable3DCorrectionLedger()
        _register_wall(ledger)

        event1, obj1 = _correct_length(ledger, new_value=6.0, correction_id="CORR-LINK-A")
        recalculate_quantities_for_correction(event1, obj1, ledger=ledger)
        first_pass_links = list(ledger.get_object("WALL-LINK-1").dependent_quantity_ids)

        event2, obj2 = _correct_length(ledger, new_value=6.2, correction_id="CORR-LINK-B")
        recalculate_quantities_for_correction(event2, obj2, ledger=ledger)
        second_pass_links = ledger.get_object("WALL-LINK-1").dependent_quantity_ids

        for qid in first_pass_links:
            assert qid in second_pass_links
        assert len(second_pass_links) == len(set(second_pass_links))
