"""tests/test_workstream_p22_malformed_data.py — Workstream P22 Legacy Malformed Data Tests."""

import os
import sqlite3
import tempfile
import pytest

import pb_planreader_3d_app as app
import pb_commercial_review_v161 as review
import pb_commercial_export_preflight_v163 as preflight
import pb_multi_page_scale_v170 as scale_engine
from pb_takeoff_authority_v164 import is_excluded_takeoff_row, is_model_surface_row


@pytest.fixture
def malformed_db():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()

    old_db_path = app.DB_PATH
    old_local_connect = app.local_connect

    app.DB_PATH = db_path
    def _test_connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    app.local_connect = _test_connect
    app._pb_local_db_initialized_v1215 = False
    app.init_local_db()

    yield db_path

    app.DB_PATH = old_db_path
    app.local_connect = old_local_connect
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


def test_p22_orphan_rows_and_missing_ids_handling(malformed_db):
    """Verify orphan rows and missing/non-numeric IDs fail safely without crashing."""
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces(id, job_name, estimator, created_at, updated_at) VALUES (1, 'Orphan WS', 'Tester', '2026-01-01', '2026-01-01')")
        
        # Insert takeoff row with missing/non-numeric ID simulation via raw execute
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, created_at, updated_at)
               VALUES (10, 1, 'Internal', 'Doors', 'Level 1', 'Timber', 'Gloss', 5.0, 'No.', 'Measured', 'P9999_ORPHAN', 'ref_orph', 'INCLUSION', 'INVALID_DATE', 'INVALID_DATE')"""
        )
        
        # Insert measurement line with orphan page_id=9999 and takeoff_row_id=8888
        conn.execute(
            """INSERT INTO measurement_lines(id, workspace_id, page_id, takeoff_row_id, kind, label, points, length_m, area_m2, colour, created_at)
               VALUES (1, 1, 9999, 8888, 'invalid_kind', 'Skirting', 'INVALID_JSON_POINTS', 0.0, 0.0, '#FF0000', 'BAD_DATE')"""
        )
        
        # Insert register item with null title and invalid status
        conn.execute(
            """INSERT INTO register_items(id, workspace_id, register_name, item_no, title, detail, priority, status, created_at)
               VALUES (1, 1, 'Clarifications', 'RFI-01', NULL, 'Detail text', 'HIGH', 'CORRUPTED_STATUS', 'BAD_DATE')"""
        )
        conn.commit()

    workspace = {"id": 1, "job_name": "Orphan WS"}
    
    # 1. Commercial review signal collection must succeed and surface unrecognised status
    signals = review.collect_commercial_review_signals(app, workspace)
    assert signals.signal_count > 0

    # 2. Preflight export must run safely
    pf_res = preflight.derive_export_preflight(app, 1)
    assert pf_res.preflight_status in ("AVAILABLE", "AVAILABLE_WITH_WARNING", "BLOCKED")

    # 3. Dataframe loading and per-level summary must operate safely
    df = app.dataframe_for_takeoff(1)
    assert len(df) == 1

    per_level = app.per_level_summary(1)
    assert isinstance(per_level, app.pd.DataFrame)


def test_p22_bad_numeric_values_and_timestamps(malformed_db):
    """Verify non-finite numbers (NaN/Inf), strings with units, and malformed timestamps fail safely."""
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces(id, job_name, estimator, created_at, updated_at) VALUES (1, 'Bad Numeric WS', 'Tester', '2026-01-01', '2026-01-01')")
        
        # Row 1: NaN quantity and bad rates
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, created_at, updated_at)
               VALUES (1, 1, 'Internal', 'Walls', 'Level 1', 'Plaster', 'Acrylic', 'NaN', 'm2', 'Measured', 'P01', 'ref_1', 'INCLUSION', 'BAD_COATS', 'NaN', 'Inf', '-Inf', '2026-01-01', '2026-01-01')"""
        )
        
        # Row 2: string quantity with unit
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, rate_per_unit, created_at, updated_at)
               VALUES (2, 1, 'Internal', 'Ceilings', 'Level 1', 'Plaster', 'Acrylic', '150.0 m2', 'm2', 'Measured', 'P01', 'ref_2', 'INCLUSION', 25.0, '2026-01-01', '2026-01-01')"""
        )
        conn.commit()

    workspace = {"id": 1, "job_name": "Bad Numeric WS"}
    
    # Review signal collection flags non-finite quantity on Measured row
    signals = review.collect_commercial_review_signals(app, workspace)
    assert any("non-finite" in r for s in signals.signals for r in s.reasons)

    # dataframe_for_takeoff safely defaults bad numeric fields
    df = app.dataframe_for_takeoff(1)
    assert len(df) == 2
    assert df.loc[df["id"] == 1, "quantity"].iloc[0] == 0.0
    assert df.loc[df["id"] == 2, "quantity"].iloc[0] == 0.0


def test_p22_unrecognised_statuses_surfaced(malformed_db):
    """Verify unrecognised quantity_status and inclusion_status generate review signals."""
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces(id, job_name, estimator, created_at, updated_at) VALUES (1, 'Status WS', 'Tester', '2026-01-01', '2026-01-01')")
        
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, created_at, updated_at)
               VALUES (1, 1, 'Internal', 'Walls', 'Level 1', 'Plaster', 'Acrylic', 50.0, 'm2', 'CORRUPTED_QTY_STATUS', 'P01', 'ref_1', 'CORRUPTED_INCL_STATUS', '2026-01-01', '2026-01-01')"""
        )
        conn.commit()

    workspace = {"id": 1, "job_name": "Status WS"}
    signals = review.collect_commercial_review_signals(app, workspace)
    reasons_text = " ".join(r for s in signals.signals for r in s.reasons)
    assert "unrecognised" in reasons_text.lower()
