"""tests/test_workstream_p24_app_startup.py — Workstream P24 Application Startup Tests."""

import os
import sqlite3
import tempfile
import pytest

import pb_planreader_3d_app as app


@pytest.fixture
def startup_db():
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

    yield db_path

    app.DB_PATH = old_db_path
    app.local_connect = old_local_connect
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


def test_p24_database_initialization_and_schema_verification(startup_db):
    """Verify that init_local_db initializes all required tables and indexes on application startup."""
    app.init_local_db()

    conn = app.local_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}

        expected_tables = {
            "workspaces", "workspace_settings", "documents", "pages",
            "takeoff_rows", "register_items", "mapped_zones", "model_masses",
            "measurement_lines", "model_openings", "ai_runs"
        }
        assert expected_tables.issubset(tables)

        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {r[0] for r in cur.fetchall()}
        expected_indexes = {
            "idx_pages_ws", "idx_takeoff_ws", "idx_register_ws",
            "idx_measurement_ws", "idx_measurement_page", "idx_measurement_row"
        }
        assert expected_indexes.issubset(indexes)
    finally:
        conn.close()


def test_p24_app_module_entry_points_callable():
    """Verify main entry point and core workspace render functions are importable and callable."""
    assert callable(getattr(app, "main", None))
    assert callable(getattr(app, "plan_mapper_page", None))
    assert callable(getattr(app, "drawing_register_page", None))
    assert callable(getattr(app, "subscription_takeoff_page", None))
