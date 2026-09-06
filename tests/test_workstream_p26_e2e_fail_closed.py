"""tests/test_workstream_p26_e2e_fail_closed.py — Workstream P26 End-to-End Fail-Closed Tests."""

import os
import sqlite3
import tempfile
import pytest

import pb_planreader_3d_app as app
import pb_commercial_review_v161 as review
import pb_commercial_export_preflight_v163 as preflight
import pb_multi_page_scale_v170 as scale_engine
from pb_takeoff_authority_v164 import approve_model_surface_row
JobHubBridge = app.JobHubBridge


@pytest.fixture
def fail_closed_db():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()

    jh_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    jh_path = jh_file.name
    jh_file.close()

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

    yield db_path, jh_path

    app.DB_PATH = old_db_path
    app.local_connect = old_local_connect
    for p in (db_path, jh_path):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_p26_uncalibrated_scale_blocks_preflight_and_prevents_publish(fail_closed_db):
    """Verify uncalibrated page scale forces BLOCKED preflight and prevents JobHub publication."""
    db_path, jh_path = fail_closed_db

    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces(id, jobhub_job_id, job_no, job_name, created_at, updated_at) VALUES (1, 501, 'JOB-P26', 'Block WS', '2026-01-01', '2026-01-01')")
        conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, scale_method, scale_verified) VALUES (1, 1, 1, 1, 'P1', 'UNCALIBRATED', 0)")
        conn.execute("INSERT INTO takeoff_rows(id, workspace_id, section, element, quantity, unit, quantity_status, inclusion_status) VALUES (1, 1, 'Int', 'Wall', 10.0, 'm²', 'Measured', 'INCLUSION')")
        conn.commit()

    pf_res = preflight.derive_export_preflight(app, 1)
    assert pf_res.preflight_status == "BLOCKED"
    assert pf_res.blocker_count > 0

    bridge = JobHubBridge(kind="sqlite", source=jh_path)
    published = False

    def _pub(w, b, u):
        nonlocal published
        published = True
        return {"package_id": 1, "published": True}

    with pytest.raises(RuntimeError) as exc_info:
        preflight.verify_toctou_and_publish_jobhub(app, 1, bridge, "Tester", pf_res.preflight_fingerprint, True, _pub)

    assert "blocked" in str(exc_info.value).lower()
    assert not published


def test_p26_unapproved_or_tampered_model_surface_blocks_publish(fail_closed_db):
    """Verify unapproved 3D model surface or post-approval tampering blocks preflight and prevents publish."""
    db_path, jh_path = fail_closed_db

    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces(id, jobhub_job_id, job_no, job_name, created_at, updated_at) VALUES (1, 501, 'JOB-P26', 'Model WS', '2026-01-01', '2026-01-01')")
        conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, px_per_m, scale_method, scale_verified) VALUES (1, 1, 1, 1, 'P1', 100.0, 'KNOWN_CALIBRATED', 1)")
        conn.execute("INSERT INTO takeoff_rows(id, workspace_id, section, element, quantity, unit, quantity_status, row_role, source_page, source_reference, inclusion_status, commercial_authority_status) VALUES (1, 1, 'Facade', 'Model Facade', 50.0, 'm²', 'Measured', 'model_surface', '3d_model', '3d_surface_editor', 'INCLUSION', 'REVIEW_REQUIRED')")
        conn.commit()

    # Unapproved model surface blocks preflight
    pf_res = preflight.derive_export_preflight(app, 1)
    assert pf_res.preflight_status == "BLOCKED"
    assert pf_res.publishable_takeoff_rows == 0

    # Approve model surface
    with app.local_connect() as conn:
        r1 = dict(conn.execute("SELECT * FROM takeoff_rows WHERE id=1").fetchone())
        app_r1 = approve_model_surface_row(r1, source="pb 3d surface editor", reviewed_by="Lead Estimator", reviewed_at="2026-01-01T10:00:00Z")
        conn.execute(
            "UPDATE takeoff_rows SET commercial_authority_status=?, commercial_authority_source=?, commercial_authority_reviewed_by=?, commercial_authority_reviewed_at=?, commercial_authority_fingerprint=? WHERE id=1",
            (app_r1["commercial_authority_status"], app_r1["commercial_authority_source"], app_r1["commercial_authority_reviewed_by"], app_r1["commercial_authority_reviewed_at"], app_r1["commercial_authority_fingerprint"])
        )
        conn.commit()

    pf_res2 = preflight.derive_export_preflight(app, 1)
    assert pf_res2.preflight_status in ("AVAILABLE", "AVAILABLE_WITH_WARNING")
    assert pf_res2.publishable_takeoff_rows == 1

    # Tamper with rate_per_unit after approval
    with app.local_connect() as conn:
        conn.execute("UPDATE takeoff_rows SET rate_per_unit=999.0 WHERE id=1")
        conn.commit()

    bridge = JobHubBridge(kind="sqlite", source=jh_path)
    published = False
    def _pub(w, b, u):
        nonlocal published
        published = True
        return {"package_id": 1, "published": True}

    with pytest.raises(RuntimeError):
        preflight.verify_toctou_and_publish_jobhub(app, 1, bridge, "Tester", pf_res2.preflight_fingerprint, True, _pub)

    assert not published
