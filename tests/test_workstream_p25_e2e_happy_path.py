"""tests/test_workstream_p25_e2e_happy_path.py — Workstream P25 End-to-End Happy Path Tests."""

import os
import sqlite3
import tempfile
import pytest

import pb_planreader_3d_app as app
import pb_commercial_review_v161 as review
import pb_commercial_export_preflight_v163 as preflight
import pb_multi_page_scale_v170 as scale_engine
from pb_takeoff_authority_v164 import approve_model_surface_row, is_jobhub_eligible_row
JobHubBridge = app.JobHubBridge


@pytest.fixture
def e2e_db():
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


def test_p25_e2e_happy_path_lifecycle(e2e_db):
    """Execute complete end-to-end commercial takeoff, review, pricing, quotation, and JobHub publication lifecycle."""
    db_path, jh_path = e2e_db

    # 1. Workspace
    with app.local_connect() as conn:
        conn.execute(
            """INSERT INTO workspaces(id, jobhub_job_id, job_no, job_name, builder_client, site_address, drawing_issue, estimator, status, created_at, updated_at)
               VALUES (1, 501, 'JOB-2026-P25', 'Apex Commercial Tower', 'Premier Construction', '100 Commercial Rd', 'Rev A', 'Lead Estimator', 'Draft', '2026-01-01', '2026-01-01')"""
        )
        conn.commit()
    workspace = {"id": 1, "job_name": "Apex Commercial Tower"}

    # 2. Document & Page
    with app.local_connect() as conn:
        conn.execute("INSERT INTO documents(id, workspace_id, file_name, path) VALUES (1, 1, 'architectural_set.pdf', '/docs/arch.pdf')")
        conn.execute(
            """INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, scale_text, px_per_m, image_path, selected, scale_method, scale_verified)
               VALUES (1, 1, 1, 1, 'A101 - Ground Floor Plan', 'Floor Plan', '1:100', 100.0, '/img/a101.png', 1, 'KNOWN_CALIBRATED', 1)"""
        )
        conn.commit()

    # 3. Scale Authority
    with app.local_connect() as conn:
        scale_registry = scale_engine.derive_workspace_scale_authority(conn, 1)
    assert not scale_registry.is_blocked()
    assert len(scale_registry.records) == 1

    # 4. Takeoff & Measurement Lines
    with app.local_connect() as conn:
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, row_role, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, created_at, updated_at)
               VALUES (1, 1, 'Internal', 'Plasterboard Wall', 'Level 1', 'Plasterboard', 'Acrylic Satin', 150.0, 'm²', 'Measured', 'A101', 'ref_wall', 'INCLUSION', '', 2.0, 12.0, 8.0, 22.50, '2026-01-01', '2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, row_role, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, created_at, updated_at)
               VALUES (2, 1, 'Internal', 'Floor Area Reference', 'Level 1', 'Concrete', 'N/A', 200.0, 'm²', 'Measured', 'A101', 'ref_flr', 'INCLUSION', 'floor_area', 0.0, 1.0, 1.0, 0.0, '2026-01-01', '2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, row_role, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, commercial_authority_status, created_at, updated_at)
               VALUES (3, 1, 'Facade', 'Model Exterior Facade', 'North Elevation', 'Concrete Render', 'Weatherproof Render', 350.0, 'm²', 'Measured', '3d_model', '3d_surface_editor', 'INCLUSION', 'model_surface', 2.0, 10.0, 6.0, 65.00, 'REVIEW_REQUIRED', '2026-01-01', '2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO measurement_lines(id, workspace_id, page_id, takeoff_row_id, kind, label, points, length_m, area_m2, colour, created_at)
               VALUES (1, 1, 1, 1, 'polygon', 'Plasterboard Footprint', '[[0,0],[15,0],[15,10],[0,10]]', 50.0, 150.0, '#00FF00', '2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO register_items(id, workspace_id, register_name, item_no, title, detail, priority, status, created_at)
               VALUES (1, 1, 'Clarifications', 'RFI-01', 'Paint Specification Confirmed', 'Architect confirmed satin acrylic finish', 'HIGH', 'Resolved', '2026-01-01')"""
        )
        conn.commit()

    # 5. Approve 3D Model Surface
    with app.local_connect() as conn:
        row3 = dict(conn.execute("SELECT * FROM takeoff_rows WHERE id=3").fetchone())
        approved_row3 = approve_model_surface_row(row3, source="pb 3d surface editor", reviewed_by="Lead Estimator", reviewed_at="2026-01-01T10:00:00Z")
        conn.execute(
            """UPDATE takeoff_rows SET commercial_authority_status=?, commercial_authority_source=?, commercial_authority_reviewed_by=?, commercial_authority_reviewed_at=?, commercial_authority_fingerprint=? WHERE id=3""",
            (
                approved_row3["commercial_authority_status"],
                approved_row3["commercial_authority_source"],
                approved_row3["commercial_authority_reviewed_by"],
                approved_row3["commercial_authority_reviewed_at"],
                approved_row3["commercial_authority_fingerprint"],
            )
        )
        conn.commit()

    # 6. Commercial Review & QA
    signals = review.collect_commercial_review_signals(app, workspace)
    assert signals.required_coverage_complete
    assert signals.blocker_count == 0

    # 7. Pricing & Per-level summary
    df_priced = app.dataframe_for_takeoff(1)
    assert len(df_priced) == 3
    total_val = float(df_priced["value_ex_gst"].sum())
    assert abs(total_val - 26125.00) < 0.01

    per_level = app.per_level_summary(1)
    assert not per_level.empty

    # 8. Quotation & Reconcile
    quote_df = app.quote_summary_frame(1)
    assert not quote_df.empty
    reco = app.reconcile_ai_vs_drawn(1)
    assert not reco.empty

    # 9. Preflight Export & JobHub Publication
    pf_result = preflight.derive_export_preflight(app, 1)
    assert pf_result.preflight_status in ("AVAILABLE", "AVAILABLE_WITH_WARNING")
    assert pf_result.publishable_takeoff_rows == 2

    bridge = app.JobHubBridge(kind="sqlite", source=jh_path)
    with bridge.connect() as jh_conn:
        jh_conn.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, job_no TEXT, job_name TEXT)")
        jh_conn.execute("INSERT INTO jobs(id, job_no, job_name) VALUES (501, 'JOB-2026-P25', 'Apex Commercial Tower')")
        jh_conn.commit()
    app.ensure_jobhub_takeoff_tables(bridge)

    def _publish_wrapper(ws_id, bridge_inst, user):
        pkg_id, count = app.push_takeoff_to_jobhub(ws_id, bridge_inst, user)
        return {"package_id": pkg_id, "pushed_rows": count, "published": True, "job_id": 501}

    pub_res = preflight.verify_toctou_and_publish_jobhub(
        conn_or_app=app,
        workspace_id=1,
        bridge=bridge,
        user_name="Lead Estimator",
        expected_fingerprint=pf_result.preflight_fingerprint,
        acknowledgement_confirmed=True,
        publish_fn=_publish_wrapper,
    )

    assert pub_res.get("published") == True
    assert pub_res.get("pushed_rows") == 2
    assert pub_res.get("package_id") == 1
