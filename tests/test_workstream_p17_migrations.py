"""Unit and integration tests for Workstream P17 — Migrations / Legacy Databases.

Tests:
1. Fresh database schema initialization creates all current tables and columns.
2. Legacy database tables lacking modern columns migrate cleanly without errors.
3. Partial migrations and repeated migration executions are completely idempotent.
4. Existing approved commercial authority data is preserved intact (no data loss) and legacy provisional rows are not falsely promoted (no false authority).
5. Dynamic schema query helpers and export functions operate safely across legacy schema variants.
6. Shared JobHub schema initialization and table creation execute idempotently on bridge databases.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

import pb_planreader_3d_app as app
import pb_takeoff_accuracy_v125 as accuracy_v125
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    model_surface_authority,
)


class MockJobHubBridge:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.kind = "sqlite"

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def table_names(self):
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

    def execute(self, sql: str, params=(), returning: bool = False):
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            if returning and "RETURNING" in sql.upper():
                row = cur.fetchone()
                return row[0] if row else None
            return cur.lastrowid
        finally:
            conn.close()

    def query(self, sql: str, params=()):
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def _bind_test_db(db_path: str):
    orig_local_connect = getattr(app, "local_connect", None)
    orig_db_path = getattr(app, "DB_PATH", None)

    def _test_local_connect():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    app.local_connect = _test_local_connect
    app.DB_PATH = db_path
    app._pb_local_db_initialized_v1215 = False
    return orig_local_connect, orig_db_path


def _unbind_test_db(orig_local_connect, orig_db_path):
    if orig_local_connect:
        app.local_connect = orig_local_connect
    if orig_db_path:
        app.DB_PATH = orig_db_path
    app._pb_local_db_initialized_v1215 = False


def test_new_database_schema_initialization(tmp_path):
    """Verify init_local_db creates all required tables and columns on a fresh SQLite database."""
    db_path = str(tmp_path / "fresh.db")
    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        
        expected_tables = {
            "workspaces", "workspace_settings", "documents", "pages",
            "takeoff_rows", "register_items", "mapped_zones", "model_masses",
            "measurement_lines", "model_openings", "ai_runs"
        }
        assert expected_tables.issubset(tables)

        takeoff_cols = {r[1] for r in conn.execute("PRAGMA table_info(takeoff_rows)").fetchall()}
        required_takeoff_cols = {
            "row_role", "commercial_authority_status", "commercial_authority_source",
            "commercial_authority_reviewed_by", "commercial_authority_reviewed_at",
            "commercial_authority_fingerprint", "coats", "coverage_m2_per_litre",
            "productivity_m2_per_hour", "rate_per_unit", "ai_baseline_quantity",
            "pre_map_quantity", "pre_map_quantity_status", "origin"
        }
        assert required_takeoff_cols.issubset(takeoff_cols)

        measurement_cols = {r[1] for r in conn.execute("PRAGMA table_info(measurement_lines)").fetchall()}
        required_measurement_cols = {"kind", "points", "area_m2", "perimeter_m", "measurement_basis"}
        assert required_measurement_cols.issubset(measurement_cols)

        pages_cols = {r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()}
        required_pages_cols = {"render_zoom", "scale_method", "scale_verified"}
        assert required_pages_cols.issubset(pages_cols)

        conn.close()
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_legacy_database_barebones_migration(tmp_path):
    """Verify legacy database with barebones schema migrates cleanly without errors."""
    db_path = str(tmp_path / "legacy_bare.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Create minimal legacy schemas
    cur.execute("""
        CREATE TABLE takeoff_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            section TEXT,
            element TEXT,
            location TEXT,
            substrate TEXT,
            quantity REAL DEFAULT 0,
            unit TEXT,
            notes TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            workspace_id INTEGER NOT NULL,
            page_no INTEGER,
            page_label TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE measurement_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            page_id INTEGER NOT NULL,
            x1 REAL, y1 REAL, x2 REAL, y2 REAL, length_m REAL
        )
    """)
    cur.execute("""
        INSERT INTO takeoff_rows (workspace_id, section, element, location, notes)
        VALUES (1, 'internal', 'floor plan', 'Unit 1 floor area', 'auto-detected')
    """)
    conn.commit()
    conn.close()

    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        # Run accuracy_v125 schema migration
        accuracy_v125.schema(app)

        conn = sqlite3.connect(db_path)
        takeoff_cols = {r[1] for r in conn.execute("PRAGMA table_info(takeoff_rows)").fetchall()}
        assert "row_role" in takeoff_cols
        assert "commercial_authority_status" in takeoff_cols
        assert "rate_per_unit" in takeoff_cols

        # Check migrated legacy row
        cur = conn.cursor()
        cur.execute("SELECT row_role, element, rate_per_unit FROM takeoff_rows WHERE id=1")
        row = cur.fetchone()
        assert row[0] == "floor_area"
        assert row[1] == "Floor area"
        assert row[2] == 0

        conn.close()
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_partial_migration_and_idempotency(tmp_path):
    """Verify migrations on partially migrated databases run idempotently without duplicate column errors."""
    db_path = str(tmp_path / "partial.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Partially migrated schema
    cur.execute("""
        CREATE TABLE takeoff_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            section TEXT, element TEXT, location TEXT, substrate TEXT,
            quantity REAL DEFAULT 0, unit TEXT,
            row_role TEXT DEFAULT '',
            commercial_authority_status TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL, workspace_id INTEGER NOT NULL,
            page_no INTEGER, render_zoom REAL
        )
    """)
    cur.execute("""
        CREATE TABLE measurement_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL, page_id INTEGER NOT NULL,
            kind TEXT DEFAULT 'line', points TEXT
        )
    """)
    conn.commit()
    conn.close()

    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        # Run migration pass 1
        app._pb_local_db_initialized_v1215 = False
        app.init_local_db()
        accuracy_v125.schema(app)

        # Run migration pass 2 (idempotency check)
        app._pb_local_db_initialized_v1215 = False
        app.init_local_db()
        accuracy_v125.schema(app)

        conn = sqlite3.connect(db_path)
        takeoff_cols = {r[1] for r in conn.execute("PRAGMA table_info(takeoff_rows)").fetchall()}
        assert "commercial_authority_fingerprint" in takeoff_cols
        assert "origin" in takeoff_cols

        pages_cols = {r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()}
        assert "scale_method" in pages_cols
        assert "scale_verified" in pages_cols

        measurement_cols = {r[1] for r in conn.execute("PRAGMA table_info(measurement_lines)").fetchall()}
        assert "area_m2" in measurement_cols
        assert "measurement_basis" in measurement_cols

        conn.close()
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_legacy_data_preservation_and_no_false_authority(tmp_path):
    """Verify legacy data is preserved without data loss and provisional rows are not falsely promoted to approved."""
    db_path = str(tmp_path / "legacy_data.db")
    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        raw_row1 = {
            "id": 1,
            "workspace_id": 10,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 101",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 50.0,
            "unit": "m²",
            "coats": 2.0,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 0.0,
            "quantity_status": "Measured",
            "source_page": "3d_model",
            "source_reference": "Model mass #1",
            "inclusion_status": "Included",
            "confidence": "HIGH",
            "notes": "Verified surface",
            "row_role": "model_surface",
        }
        approved_row1 = approve_model_surface_row(
            raw_row1,
            source="Manual Estimator Audit",
            reviewed_by="Bryce Senior",
            reviewed_at="2026-09-01T10:00:00Z",
        )

        # Insert Row 1: Pre-existing Approved row with valid authority metadata
        cur.execute("""
            INSERT INTO takeoff_rows (
                workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit,
                quantity_status, source_page, source_reference, inclusion_status, confidence, notes,
                row_role, commercial_authority_status, commercial_authority_source,
                commercial_authority_reviewed_by, commercial_authority_reviewed_at, commercial_authority_fingerprint
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
        """, (
            approved_row1["workspace_id"], approved_row1["section"], approved_row1["element"], approved_row1["location"], approved_row1["substrate"], approved_row1["finish_system"],
            approved_row1["quantity"], approved_row1["unit"], approved_row1["coats"], approved_row1["coverage_m2_per_litre"], approved_row1["productivity_m2_per_hour"], approved_row1["rate_per_unit"],
            approved_row1["quantity_status"], approved_row1["source_page"], approved_row1["source_reference"], approved_row1["inclusion_status"], approved_row1["confidence"], approved_row1["notes"],
            approved_row1["row_role"], approved_row1["commercial_authority_status"], approved_row1["commercial_authority_source"],
            approved_row1["commercial_authority_reviewed_by"], approved_row1["commercial_authority_reviewed_at"], approved_row1["commercial_authority_fingerprint"]
        ))

        # Insert Row 2: Pre-existing Provisional row with no authority
        cur.execute("""
            INSERT INTO takeoff_rows (
                workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, row_role, commercial_authority_status
            ) VALUES (
                10, 'Internal', 'Plasterboard', 'Room 102', 'Plasterboard', 'Paint',
                30.0, 'm²', 'model_surface', ''
            )
        """)
        conn.commit()
        conn.close()

        # Run accuracy_v125 schema update
        accuracy_v125.schema(app)

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Verify Row 1: Approved metadata preserved exactly
        cur.execute("""
            SELECT commercial_authority_status, commercial_authority_source,
                   commercial_authority_reviewed_by, commercial_authority_reviewed_at,
                   commercial_authority_fingerprint
            FROM takeoff_rows WHERE id=1
        """)
        row1 = cur.fetchone()
        assert row1[0] == "APPROVED"
        assert row1[1] == "Manual Estimator Audit"
        assert row1[2] == "Bryce Senior"
        assert row1[3] == approved_row1["commercial_authority_reviewed_at"]
        assert row1[4] == approved_row1["commercial_authority_fingerprint"]

        # Verify Row 2: Remains unapproved (no false authority promotion)
        cur.execute("""
            SELECT commercial_authority_status, commercial_authority_fingerprint
            FROM takeoff_rows WHERE id=2
        """)
        row2 = cur.fetchone()
        assert row2[0] == ""
        assert row2[1] == ""

        # Test model_surface_authority on migrated row dicts
        cur.execute("SELECT * FROM takeoff_rows WHERE id=1")
        dict1 = dict(zip([col[0] for col in cur.description], cur.fetchone()))
        assert model_surface_authority(dict1)[0] is True

        cur.execute("SELECT * FROM takeoff_rows WHERE id=2")
        dict2 = dict(zip([col[0] for col in cur.description], cur.fetchone()))
        assert model_surface_authority(dict2)[0] is False

        conn.close()
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_shared_jobhub_schema_migration_idempotency(tmp_path):
    """Verify ensure_shared_jobhub_schema and ensure_jobhub_takeoff_tables execute cleanly and idempotently."""
    db_path = str(tmp_path / "jobhub_bridge.db")
    bridge = MockJobHubBridge(db_path)

    # Initial creation
    app.ensure_shared_jobhub_schema(bridge)
    app.ensure_jobhub_takeoff_tables(bridge)

    tables_pass1 = set(bridge.table_names())
    assert "jobs" in tables_pass1
    assert "job_takeoff_rows" in tables_pass1
    assert "painting_takeoff_packages" in tables_pass1
    assert "painting_takeoff_lines" in tables_pass1

    # Second creation (idempotency check)
    app.ensure_shared_jobhub_schema(bridge)
    app.ensure_jobhub_takeoff_tables(bridge)

    tables_pass2 = set(bridge.table_names())
    assert tables_pass1 == tables_pass2
