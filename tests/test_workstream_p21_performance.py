"""tests/test_workstream_p21_performance.py — Workstream P21 Performance & Indexing Tests."""

import os
import sqlite3
import tempfile
import time
import pytest

import pb_planreader_3d_app as app
import pb_commercial_review_v161 as review
import pb_commercial_export_preflight_v163 as preflight
import pb_multi_page_scale_v170 as scale_engine


@pytest.fixture
def perf_db():
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


def test_p21_database_indexes_created(perf_db):
    """Verify that init_local_db creates required performance indexes on foreign keys."""
    conn = app.local_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cur.fetchall()}

        expected_indexes = {
            "idx_pages_ws",
            "idx_takeoff_ws",
            "idx_register_ws",
            "idx_measurement_ws",
            "idx_measurement_page",
            "idx_measurement_row",
        }
        for idx in expected_indexes:
            assert idx in indexes, f"Expected index '{idx}' was not created in init_local_db"
    finally:
        conn.close()


def test_p21_reconcile_ai_vs_drawn_batched_query(perf_db):
    """Verify reconcile_ai_vs_drawn operates correctly and efficiently with batched queries."""
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces(id, job_name, estimator, created_at, updated_at) VALUES (1, 'Perf WS', 'Tester', '2026-01-01', '2026-01-01')")
        
        # Insert 100 takeoff rows (50 AI, 50 Manual)
        for r in range(1, 101):
            source_ref = "AI draft" if r <= 50 else "Manual"
            conn.execute(
                """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, row_role, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, created_at, updated_at)
                   VALUES (?, 1, 'Internal', 'Plasterboard', 'Level 1', 'Sub', 'Finish', 10.0, 'm2', 'Measured', 'P01', ?, 'INCLUSION', '', 2, 12, 8, 15.0, '2026-01-01', '2026-01-01')""",
                (r, source_ref)
            )

        # Insert measurement lines for first 25 rows
        for m in range(1, 26):
            conn.execute(
                """INSERT INTO measurement_lines(id, workspace_id, page_id, takeoff_row_id, kind, label, points, length_m, area_m2, colour, created_at)
                   VALUES (?, 1, 1, ?, 'line', 'Skirting', '[[0,0],[10,0]]', 10.0, 0.0, '#FF0000', '2026-01-01')""",
                (m, m)
            )
        conn.commit()

    t0 = time.perf_counter()
    reco_df = app.reconcile_ai_vs_drawn(1)
    t1 = time.perf_counter()

    # Must complete fast (< 500 ms)
    elapsed_ms = (t1 - t0) * 1000
    assert elapsed_ms < 500.0, f"reconcile_ai_vs_drawn took {elapsed_ms:.2f} ms, expected < 500 ms"
    assert not reco_df.empty
    assert "status" in reco_df.columns
