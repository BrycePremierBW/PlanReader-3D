"""tests/test_workstream_p27_e2e_mixed_authority.py — Workstream P27 End-to-End Mixed Authority Integration Tests."""

import os
import sqlite3
import tempfile
import pytest

import pb_planreader_3d_app as app
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    takeoff_row_publishability,
)


@pytest.fixture
def mixed_authority_db():
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


def _insert_row(conn, row_dict):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(takeoff_rows)")
    db_cols = set(r[1] for r in cur.fetchall())
    valid_cols = [c for c in row_dict.keys() if c in db_cols]
    placeholders = ", ".join(["?"] * len(valid_cols))
    col_names = ", ".join(valid_cols)
    vals = [row_dict[c] for c in valid_cols]
    conn.execute(f"INSERT INTO takeoff_rows ({col_names}) VALUES ({placeholders})", vals)


def test_p27_mixed_authority_row_classification(mixed_authority_db):
    """Verify that a mixed dataset of 6 row types accurately classifies publishable vs ineligible rows."""
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces (id, jobhub_job_id, job_no, job_name, created_at, updated_at) VALUES (1, 501, 'JOB-P27', 'P27 Workspace', '2026-01-01', '2026-01-01')")
        conn.execute("INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, scale_method, scale_verified) VALUES (10, 1, 1, 1, 'P1', 'CALIBRATED', 1)")

        # Row 1: Manual Authoritative (Eligible Work)
        _insert_row(conn, {
            "id": 101,
            "workspace_id": 1,
            "element": "Manual Wall Paint",
            "quantity": 100.0,
            "unit": "m²",
            "rate_per_unit": 50.0,
            "row_role": "work",
            "inclusion_status": "INCLUSION",
            "source_reference": "manual_drawing",
            "source_page": "P1",
            "quantity_status": "VERIFIED",
        })

        # Row 2: Approved Model Surface (Eligible Work)
        raw_row2 = {
            "id": 102,
            "workspace_id": 1,
            "element": "Approved 3D Wall",
            "quantity": 200.0,
            "unit": "m²",
            "coats": 2.0,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 60.0,
            "row_role": "work",
            "inclusion_status": "INCLUSION",
            "source_reference": "3d_model_element_123",
            "source_page": "3d_model",
            "quantity_status": "APPROVED",
        }
        app_row2 = approve_model_surface_row(raw_row2, source="pb 3d surface editor", reviewed_by="Estimator Bryce", reviewed_at="2026-09-06T12:00:00Z")
        _insert_row(conn, app_row2)

        # Row 3: Unapproved Model Surface (Ineligible Work)
        _insert_row(conn, {
            "id": 103,
            "workspace_id": 1,
            "element": "Unapproved 3D Wall",
            "quantity": 300.0,
            "unit": "m²",
            "rate_per_unit": 70.0,
            "row_role": "work",
            "inclusion_status": "INCLUSION",
            "source_reference": "3d_model_element_456",
            "source_page": "3d_model",
            "quantity_status": "UNAPPROVED",
            "commercial_authority_status": "UNAPPROVED",
        })

        # Row 4: Tampered Approval Model Surface (Ineligible Work)
        _insert_row(conn, {
            "id": 104,
            "workspace_id": 1,
            "element": "Tampered 3D Wall",
            "quantity": 500.0,
            "unit": "m²",
            "rate_per_unit": 80.0,
            "row_role": "work",
            "inclusion_status": "INCLUSION",
            "source_reference": "3d_model_element_789",
            "source_page": "3d_model",
            "quantity_status": "APPROVED",
            "commercial_authority_status": "APPROVED",
            "commercial_authority_reviewed_by": "Estimator Bryce",
            "commercial_authority_reviewed_at": "2026-09-06T12:00:00Z",
            "commercial_authority_source": "pb 3d surface editor",
            "commercial_authority_fingerprint": "INVALID_TAMPERED_FINGERPRINT",
        })

        # Row 5: Excluded Row (Ineligible Work)
        _insert_row(conn, {
            "id": 105,
            "workspace_id": 1,
            "element": "Excluded Temporary Wall",
            "quantity": 150.0,
            "unit": "m²",
            "rate_per_unit": 40.0,
            "row_role": "work",
            "inclusion_status": "EXCLUDED",
            "source_reference": "manual_drawing",
            "source_page": "P1",
            "quantity_status": "EXCLUDED",
        })

        # Row 6: Floor Reference Row (Reference Only)
        _insert_row(conn, {
            "id": 106,
            "workspace_id": 1,
            "element": "Floor Area Level 1",
            "quantity": 120.0,
            "unit": "m²",
            "rate_per_unit": 0.0,
            "row_role": "floor_area",
            "inclusion_status": "INCLUSION",
            "source_reference": "manual_drawing",
            "source_page": "P1",
            "quantity_status": "VERIFIED",
        })
        conn.commit()

        # Check row publishability
        cur = conn.execute("SELECT * FROM takeoff_rows WHERE workspace_id = 1")
        rows = [dict(r) for r in cur.fetchall()]
        by_id = {r['id']: r for r in rows}

        assert takeoff_row_publishability(by_id[101])[0] is True
        assert takeoff_row_publishability(by_id[102])[0] is True
        assert takeoff_row_publishability(by_id[103])[0] is False
        assert takeoff_row_publishability(by_id[104])[0] is False
        assert takeoff_row_publishability(by_id[105])[0] is False
        assert takeoff_row_publishability(by_id[106])[0] is False


def test_p27_mixed_authority_pricing_and_jobhub_sync(mixed_authority_db):
    """Verify commercial pricing, dataframe, and JobHub sync only include eligible commercial rows."""
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces (id, jobhub_job_id, job_no, job_name, created_at, updated_at) VALUES (1, 501, 'JOB-P27', 'P27 Workspace', '2026-01-01', '2026-01-01')")
        conn.execute("INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, scale_method, scale_verified) VALUES (10, 1, 1, 1, 'P1', 'CALIBRATED', 1)")

        # Row 1: Manual Authoritative ($5,000)
        _insert_row(conn, {
            "id": 101,
            "workspace_id": 1,
            "element": "Manual Wall Paint",
            "quantity": 100.0,
            "unit": "m²",
            "rate_per_unit": 50.0,
            "row_role": "work",
            "inclusion_status": "INCLUSION",
            "source_reference": "manual_drawing",
            "source_page": "P1",
            "quantity_status": "VERIFIED",
        })

        # Row 2: Approved Model Surface ($12,000)
        raw_row2 = {
            "id": 102,
            "workspace_id": 1,
            "element": "Approved 3D Wall",
            "quantity": 200.0,
            "unit": "m²",
            "coats": 2.0,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 60.0,
            "row_role": "work",
            "inclusion_status": "INCLUSION",
            "source_reference": "3d_model_element_123",
            "source_page": "3d_model",
            "quantity_status": "APPROVED",
        }
        app_row2 = approve_model_surface_row(raw_row2, source="pb 3d surface editor", reviewed_by="Estimator Bryce", reviewed_at="2026-09-06T12:00:00Z")
        _insert_row(conn, app_row2)

        # Ineligible Rows
        _insert_row(conn, {"id": 103, "workspace_id": 1, "element": "Unapproved 3D Wall", "quantity": 300.0, "unit": "m²", "rate_per_unit": 70.0, "row_role": "work", "inclusion_status": "INCLUSION", "source_reference": "3d_model_element_456", "source_page": "3d_model", "quantity_status": "UNAPPROVED", "commercial_authority_status": "UNAPPROVED"})
        _insert_row(conn, {"id": 104, "workspace_id": 1, "element": "Tampered 3D Wall", "quantity": 500.0, "unit": "m²", "rate_per_unit": 80.0, "row_role": "work", "inclusion_status": "INCLUSION", "source_reference": "3d_model_element_789", "source_page": "3d_model", "quantity_status": "APPROVED", "commercial_authority_status": "APPROVED", "commercial_authority_fingerprint": "TAMPERED"})
        _insert_row(conn, {"id": 105, "workspace_id": 1, "element": "Excluded Temp Wall", "quantity": 150.0, "unit": "m²", "rate_per_unit": 40.0, "row_role": "work", "inclusion_status": "EXCLUDED", "source_reference": "manual_drawing", "source_page": "P1", "quantity_status": "EXCLUDED"})
        _insert_row(conn, {"id": 106, "workspace_id": 1, "element": "Floor Area Level 1", "quantity": 120.0, "unit": "m²", "rate_per_unit": 0.0, "row_role": "floor_area", "inclusion_status": "INCLUSION", "source_reference": "manual_drawing", "source_page": "P1", "quantity_status": "VERIFIED"})
        conn.commit()

        # Check pricing dataframe
        df = app.dataframe_for_takeoff(1)
        # Filters out unapproved 3D, tampered 3D, and excluded rows
        assert len(df) == 3 # 2 work rows + 1 floor reference row

        # Check commercial_takeoff_rows (eligible commercial takeoff rows)
        comm_df = app.commercial_takeoff_rows(df)
        work_df = comm_df[comm_df['row_role'] == 'work']
        assert len(work_df) == 2
        assert comm_df['value_ex_gst'].sum() == 17000.0  # $5,000 + $12,000

        # Check JobHub takeoff CSV lines (only work lines exported, floor reference excluded)
        csv_data = app._jobhub_takeoff_lines_csv({"id": 1, "job_no": "JOB-P27"}, df)
        assert "Manual Wall Paint" in csv_data
        assert "Approved 3D Wall" in csv_data
        assert "Unapproved 3D Wall" not in csv_data
        assert "Tampered 3D Wall" not in csv_data
        assert "Excluded Temp Wall" not in csv_data
        assert "Floor Area Level 1" not in csv_data
