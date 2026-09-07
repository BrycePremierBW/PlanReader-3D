"""tests/editable_3d/test_inspector_panel_demo_scenario.py — PR D.11A test suite.

pb_editable_3d_inspector_panel.py is a read-only Streamlit panel; its rendering
functions are exercised via the browser, not unit tests. But _build_demo_scenario()
is pure: it calls only real D.1-D.10 backend functions (Editable3DCorrectionLedger,
recalculate_quantities_for_correction, approve_corrected_geometry,
create_takeoff_output_row, approve_takeoff_output_row) with no Streamlit dependency,
so it is fully testable. These tests prove the demo scenario actually demonstrates
the four required UI distinctions using real backend state, not fabricated data.
"""
from __future__ import annotations

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_inspector_panel import _build_demo_scenario


def test_wall_demo_1_is_corrected_but_not_approved():
    ledger, rows, _block_reason = _build_demo_scenario()
    obj = ledger.get_object("WALL-DEMO-1")
    assert obj is not None
    assert obj.correction_ids, "WALL-DEMO-1 must have at least one real correction"
    assert obj.approved_by is None
    assert obj.approved_at is None
    assert obj.authority_status == AuthorityStatus.REVIEW_REQUIRED.value


def test_wall_demo_1_old_quantity_is_stale_not_current():
    ledger, rows, _block_reason = _build_demo_scenario()
    old_row = rows["QTY-DEMO-1-GROSS"]
    assert old_row.is_publishable is False
    assert "stale_after_geometry_correction" in old_row.blocking_reasons


def test_wall_demo_1_new_quantity_is_current_but_not_yet_publishable():
    ledger, rows, _block_reason = _build_demo_scenario()
    obj = ledger.get_object("WALL-DEMO-1")
    new_row_ids = [qid for qid in obj.dependent_quantity_ids if qid in rows]
    assert new_row_ids, "correction must have linked at least one dependent quantity"
    new_row = rows[new_row_ids[0]]
    assert "stale_after_geometry_correction" not in new_row.blocking_reasons
    assert new_row.is_publishable is False  # corrected, not yet approved


def test_wall_demo_2_is_corrected_and_approved():
    ledger, rows, _block_reason = _build_demo_scenario()
    obj = ledger.get_object("WALL-DEMO-2")
    assert obj is not None
    assert obj.correction_ids
    assert obj.approved_by == "Lead Estimator Bryce"
    assert obj.approved_at is not None
    assert obj.authority_status == AuthorityStatus.FIRM.value


def test_wall_demo_2_new_quantity_is_publishable_after_approval():
    ledger, rows, _block_reason = _build_demo_scenario()
    obj = ledger.get_object("WALL-DEMO-2")
    approved_rows = [
        rows[qid] for qid in obj.dependent_quantity_ids
        if qid in rows and rows[qid].approved_by
    ]
    assert approved_rows, "expected at least one approved dependent quantity"
    assert any(r.is_publishable for r in approved_rows)


def test_wall_demo_3_is_untraceable_and_approval_fails_closed():
    ledger, rows, block_reason = _build_demo_scenario()
    obj = ledger.get_object("WALL-DEMO-3")
    assert obj is not None
    assert obj.source_sheet is None
    assert obj.source_page is None
    assert obj.approved_by is None
    assert "missing source trace" in block_reason


def test_all_three_demo_objects_are_registered():
    ledger, _rows, _block_reason = _build_demo_scenario()
    for object_id in ("WALL-DEMO-1", "WALL-DEMO-2", "WALL-DEMO-3"):
        assert ledger.get_object(object_id) is not None


def test_demo_scenario_is_deterministic_across_calls():
    ledger_a, rows_a, block_a = _build_demo_scenario()
    ledger_b, rows_b, block_b = _build_demo_scenario()
    for object_id in ("WALL-DEMO-1", "WALL-DEMO-2", "WALL-DEMO-3"):
        obj_a = ledger_a.get_object(object_id)
        obj_b = ledger_b.get_object(object_id)
        assert obj_a.authority_status == obj_b.authority_status
        assert obj_a.approved_by == obj_b.approved_by
    assert set(rows_a.keys()) == set(rows_b.keys())
    assert block_a == block_b
