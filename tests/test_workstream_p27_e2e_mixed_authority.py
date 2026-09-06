"""tests/test_workstream_p27_e2e_mixed_authority.py — Workstream P27 End-to-End Mixed Authority Integration Tests."""

import math
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock
import pytest

import pb_planreader_3d_app as app
import pb_commercial_review_v161 as review
import pb_commercial_export_preflight_v163 as preflight
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    compute_model_surface_authority_fingerprint,
    is_commercial_floor_reference_row,
    is_excluded_takeoff_row,
    is_model_surface_row,
    model_surface_authority,
    takeoff_row_pricing_authority,
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


def test_p27_full_mixed_authority_dataset_evaluation(mixed_authority_db):
    """Verify that a full 10-row mixed authority dataset correctly classifies every row,
    emits exact commercial review signals (6 blockers, 0 blockers for legitimate/excluded rows),
    blocks export preflight, and fails closed against publication.
    """
    db_path = mixed_authority_db
    with app.local_connect() as conn:
        conn.execute("INSERT INTO workspaces (id, jobhub_job_id, job_no, job_name, created_at, updated_at) VALUES (1, 501, 'JOB-P27', 'P27 Commercial Project', '2026-09-06T10:00:00Z', '2026-09-06T10:00:00Z')")
        conn.execute("INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, px_per_m, scale_method, scale_verified) VALUES (10, 1, 1, 1, 'A-01', 100.0, 'KNOWN_CALIBRATED', 1)")

        # 1. Manual Authoritative Wall Height
        row_101 = {
            "id": 101, "workspace_id": 1, "section": "Internal", "element": "Manual Internal Wall Paint",
            "location": "Ground Floor", "quantity": 100.0, "unit": "m²", "rate_per_unit": 50.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "A-01",
            "source_reference": "manual_elevation_h2.7m", "quantity_status": "Measured", "confidence": "Measured",
        }

        # 2. Approved Model-Derived Wall Height
        raw_102 = {
            "id": 102, "workspace_id": 1, "section": "External", "element": "Approved 3D Model Wall",
            "location": "North Facade", "quantity": 200.0, "unit": "m²", "coats": 2,
            "coverage_m2_per_litre": 12.0, "productivity_m2_per_hour": 8.0, "rate_per_unit": 60.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
            "source_reference": "pb 3d surface editor · wall:W01", "quantity_status": "Measured", "confidence": "Measured",
        }
        row_102 = approve_model_surface_row(raw_102, source="pb 3d surface editor", reviewed_by="Lead Estimator Bryce", reviewed_at="2026-09-06T12:00:00Z")

        # 3. Unapproved Model-Derived Wall Height
        row_103 = {
            "id": 103, "workspace_id": 1, "section": "External", "element": "Unapproved 3D Model Wall",
            "location": "South Facade", "quantity": 150.0, "unit": "m²", "rate_per_unit": 55.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
            "source_reference": "pb 3d surface editor · wall:W02", "quantity_status": "Measured", "confidence": "To review",
            "commercial_authority_status": "REVIEW_REQUIRED",
        }

        # 4. Tampered Approval / Fingerprint Mismatch
        row_104 = {
            "id": 104, "workspace_id": 1, "section": "External", "element": "Tampered 3D Model Wall",
            "location": "East Facade", "quantity": 180.0, "unit": "m²", "rate_per_unit": 70.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
            "source_reference": "pb 3d surface editor · wall:W03", "quantity_status": "Measured", "confidence": "Measured",
            "commercial_authority_status": "APPROVED", "commercial_authority_source": "pb 3d surface editor",
            "commercial_authority_reviewed_by": "Lead Estimator Bryce", "commercial_authority_reviewed_at": "2026-09-06T12:00:00Z",
            "commercial_authority_fingerprint": "TAMPERED_FINGERPRINT",
        }

        # 5. Cross-Workspace Approval Replay
        raw_foreign = {
            "id": 105, "workspace_id": 2, "section": "Internal", "element": "Replayed Foreign 3D Wall",
            "location": "Foreign Room", "quantity": 90.0, "unit": "m²", "rate_per_unit": 45.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
            "source_reference": "pb 3d surface editor · foreign_wall", "quantity_status": "Measured", "confidence": "Measured",
        }
        app_foreign = approve_model_surface_row(raw_foreign, source="pb 3d surface editor", reviewed_by="Estimator", reviewed_at="2026-09-06T12:00:00Z")
        row_105 = dict(app_foreign)
        row_105["workspace_id"] = 1  # Replayed into workspace 1 with stale workspace 2 fingerprint

        # 6. Excluded Row
        row_106 = {
            "id": 106, "workspace_id": 1, "section": "Internal", "element": "Excluded Demolition Wall",
            "location": "Basement", "quantity": 120.0, "unit": "m²", "rate_per_unit": 30.0,
            "row_role": "work", "inclusion_status": "EXCLUDED", "source_page": "A-01",
            "source_reference": "specs_demolition", "quantity_status": "Excluded", "confidence": "Confirmed",
        }

        # 7. Floor-Reference Row
        row_107 = {
            "id": 107, "workspace_id": 1, "section": "Internal", "element": "Floor Area Level 1 Reference",
            "location": "Level 1", "quantity": 250.0, "unit": "m²", "rate_per_unit": 0.0,
            "row_role": "floor_area", "inclusion_status": "INCLUSION", "source_page": "A-01",
            "source_reference": "floor_slab_plan", "quantity_status": "Measured", "confidence": "Measured",
        }

        # 8. Missing Authority Evidence Row
        row_108 = {
            "id": 108, "workspace_id": 1, "section": "External", "element": "Missing Evidence 3D Wall",
            "location": "West Facade", "quantity": 140.0, "unit": "m²", "rate_per_unit": 50.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
            "source_reference": "pb 3d surface editor · wall:W04", "quantity_status": "Measured", "confidence": "Measured",
            "commercial_authority_status": "APPROVED", "commercial_authority_source": "",
            "commercial_authority_reviewed_by": "Lead Estimator Bryce", "commercial_authority_reviewed_at": "2026-09-06T12:00:00Z",
            "commercial_authority_fingerprint": "some_hash",
        }

        # 9. Malformed Authority Metadata Row (sentinel string 'null')
        row_109 = {
            "id": 109, "workspace_id": 1, "section": "External", "element": "Malformed Meta 3D Wall",
            "location": "Courtyard Wall", "quantity": 110.0, "unit": "m²", "rate_per_unit": 50.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
            "source_reference": "pb 3d surface editor · wall:W05", "quantity_status": "Measured", "confidence": "Measured",
            "commercial_authority_status": "APPROVED", "commercial_authority_source": "pb 3d surface editor",
            "commercial_authority_reviewed_by": "null", "commercial_authority_reviewed_at": "2026-09-06T12:00:00Z",
            "commercial_authority_fingerprint": "some_hash",
        }

        # 10. Non-Finite Quantity Row
        row_110 = {
            "id": 110, "workspace_id": 1, "section": "Internal", "element": "Non-Finite Quantity Wall",
            "location": "Void Area", "quantity": float("nan"), "unit": "m²", "rate_per_unit": 40.0,
            "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "A-01",
            "source_reference": "drawing_elevation", "quantity_status": "Measured", "confidence": "Measured",
        }

        for r in [row_101, row_102, row_103, row_104, row_105, row_106, row_107, row_108, row_109, row_110]:
            _insert_row(conn, r)
        conn.commit()

        # Check row-level publishability
        cur = conn.execute("SELECT * FROM takeoff_rows WHERE workspace_id=1 ORDER BY id")
        db_rows = {r["id"]: dict(r) for r in cur.fetchall()}

        assert takeoff_row_publishability(db_rows[101])[0] is True   # Manual authoritative
        assert takeoff_row_publishability(db_rows[102])[0] is True   # Approved 3D model
        assert takeoff_row_publishability(db_rows[103])[0] is False  # Unapproved 3D model
        assert takeoff_row_publishability(db_rows[104])[0] is False  # Tampered fingerprint
        assert takeoff_row_publishability(db_rows[105])[0] is False  # Cross-workspace replay
        assert takeoff_row_publishability(db_rows[106])[0] is False  # Excluded
        assert takeoff_row_publishability(db_rows[107])[0] is False  # Floor reference
        assert takeoff_row_publishability(db_rows[108])[0] is False  # Missing evidence
        assert takeoff_row_publishability(db_rows[109])[0] is False  # Malformed metadata

    # Commercial review signals: 6 invalid rows must emit BLOCKER; legitimate rows 101, 102 and excluded 106 must NOT emit blocker
    rev_res = review.collect_commercial_review_signals(app, {"id": 1})
    blocker_ids = {str(s.source_id) for s in rev_res.signals if s.severity == "BLOCKER"}
    for bad_id in ["103", "104", "105", "108", "109", "110"]:
        assert bad_id in blocker_ids, f"Row {bad_id} must emit a BLOCKER review signal"
    for good_id in ["101", "102", "106"]:
        assert good_id not in blocker_ids, f"Row {good_id} must not emit a BLOCKER review signal"

    # Export preflight must be BLOCKED
    pf_res = preflight.derive_export_preflight(app, 1, bridge_available=True)
    assert pf_res.preflight_status == "BLOCKED"
    assert pf_res.final_publish_state == "BLOCKED"
    assert pf_res.publishable_takeoff_rows == 3

    # verify_toctou_and_publish_jobhub must raise RuntimeError on BLOCKED preflight
    jh_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    jh_path = jh_file.name
    jh_file.close()
    try:
        bridge = app.JobHubBridge(kind="sqlite", source=jh_path)
        with pytest.raises(RuntimeError, match=r"Final publish blocked by preflight QA gate"):
            preflight.verify_toctou_and_publish_jobhub(
                app, 1, bridge, "Tester", pf_res.preflight_fingerprint, True, lambda w, b, u: {"published": True}
            )
    finally:
        if os.path.exists(jh_path):
            try:
                os.remove(jh_path)
            except OSError:
                pass


def test_p27_authority_fingerprint_cross_workspace_replay(mixed_authority_db):
    """Verify that an approved model surface cannot be replayed into another workspace."""
    raw_ws1 = {
        "id": 201, "workspace_id": 1, "section": "Internal", "element": "Approved Surface",
        "location": "Room 1", "quantity": 100.0, "unit": "m²", "rate_per_unit": 40.0,
        "row_role": "work", "inclusion_status": "INCLUSION", "source_page": "3d_model",
        "source_reference": "pb 3d surface editor · wall:01", "quantity_status": "Measured",
    }
    app_ws1 = approve_model_surface_row(raw_ws1, source="pb 3d surface editor", reviewed_by="Bryce", reviewed_at="2026-09-06T12:00:00Z")

    # In workspace 1: Valid
    assert model_surface_authority(app_ws1)[0] is True

    # Replayed into workspace 2: row dict mutated to workspace_id 2
    replayed_ws2 = dict(app_ws1)
    replayed_ws2["workspace_id"] = 2
    pub_ok, reason = takeoff_row_publishability(replayed_ws2)
    assert pub_ok is False
    assert "no longer matches" in reason

    # Mutating rate or quantity also invalidates fingerprint
    mutated_rate = dict(app_ws1)
    mutated_rate["rate_per_unit"] = 999.0
    pub_rate, reason_rate = takeoff_row_publishability(mutated_rate)
    assert pub_rate is False
    assert "no longer matches" in reason_rate


def test_p27_jobhub_mixed_authority_publication_toctou_and_duplicate_guard(mixed_authority_db):
    """Verify that on an approved mixed dataset, publication enforces TOCTOU protection
    and strictly prevents duplicate publication attempts.
    """
    jh_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    jh_path = jh_file.name
    jh_file.close()

    try:
        bridge = app.JobHubBridge(kind="sqlite", source=jh_path)
        with app.local_connect() as conn:
            conn.execute("INSERT INTO workspaces (id, jobhub_job_id, job_no, job_name, created_at, updated_at) VALUES (1, 501, 'JOB-P27', 'P27 Project', '2026-09-06T10:00:00Z', '2026-09-06T10:00:00Z')")
            conn.execute("INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, px_per_m, scale_method, scale_verified) VALUES (10, 1, 1, 1, 'A-01', 100.0, 'KNOWN_CALIBRATED', 1)")

            # Insert clean approved rows
            _insert_row(conn, {
                "id": 1, "workspace_id": 1, "element": "Manual Wall", "quantity": 100.0,
                "unit": "m²", "rate_per_unit": 50.0, "row_role": "work", "inclusion_status": "INCLUSION",
                "source_page": "A-01", "source_reference": "elevation", "quantity_status": "Measured",
            })
            approved_model = approve_model_surface_row({
                "id": 2, "workspace_id": 1, "element": "Approved 3D Wall", "quantity": 150.0,
                "unit": "m²", "rate_per_unit": 60.0, "row_role": "work", "inclusion_status": "INCLUSION",
                "source_page": "3d_model", "source_reference": "pb 3d surface editor · wall:W1",
                "quantity_status": "Measured", "coats": 2.0, "coverage_m2_per_litre": 12.0,
                "productivity_m2_per_hour": 8.0,
            }, source="pb 3d surface editor", reviewed_by="Bryce", reviewed_at="2026-09-06T12:00:00Z")
            _insert_row(conn, approved_model)
            conn.commit()

        pf_res = preflight.derive_export_preflight(app, 1, bridge_available=True)
        assert pf_res.preflight_status in ("AVAILABLE", "AVAILABLE_WITH_WARNING")
        assert pf_res.publishable_takeoff_rows == 2

        # 1. Stale fingerprint must fail closed
        stale_fp = "0000000000000000000000000000000000000000000000000000000000000000"
        with pytest.raises(RuntimeError, match=r"Project QA/export state changed"):
            preflight.verify_toctou_and_publish_jobhub(
                app, 1, bridge, "Tester", stale_fp, True, lambda w, b, u: {"published": True}
            )

        # 2. First publication succeeds
        call_count = 0
        def _publish_callback(w, b, u, **kwargs):
            nonlocal call_count
            call_count += 1
            app.ensure_jobhub_takeoff_tables(b)
            b.execute(
                "INSERT INTO painting_takeoff_packages (job_id, takeoff_no, status, notes, created_at, updated_at) "
                "VALUES (?, 'PKG-01', 'Published', ?, 'now', 'now')",
                (pf_res.jobhub_job_id, f"Preflight FP: {pf_res.preflight_fingerprint}"),
            )
            return {"package_id": 1, "published": True}

        res = preflight.verify_toctou_and_publish_jobhub(
            app, 1, bridge, "Tester", pf_res.preflight_fingerprint, True, _publish_callback
        )
        assert res["published"] is True
        assert call_count == 1

        # 3. Duplicate publication attempt fails closed
        with pytest.raises(RuntimeError, match=r"already in progress or published"):
            preflight.verify_toctou_and_publish_jobhub(
                app, 1, bridge, "Tester", pf_res.preflight_fingerprint, True, _publish_callback
            )
        assert call_count == 1  # Callback not called a second time
    finally:
        if os.path.exists(jh_path):
            try:
                os.remove(jh_path)
            except OSError:
                pass


def test_p27_non_finite_and_malformed_authority_fail_closed(mixed_authority_db):
    """Verify that non-finite numbers and malformed authority metadata fail closed."""
    base_row = {
        "id": 301, "workspace_id": 1, "element": "Wall", "row_role": "work",
        "inclusion_status": "INCLUSION", "source_page": "A-01", "source_reference": "drawing",
        "quantity_status": "Measured",
    }

    # Non-finite quantities in measured rows emit BLOCKER review signals
    for bad_qty in [float("nan"), float("inf"), float("-inf"), "NaN", "nan", "inf"]:
        mock_app = MagicMock()
        mock_app.lquery.return_value = [dict(base_row, quantity=bad_qty)]
        signals = review.collect_commercial_review_signals(mock_app, {"id": 1}).signals
        blockers = [s for s in signals if s.severity == "BLOCKER"]
        assert len(blockers) >= 1
        assert any("non-finite" in r or "numeric" in r for s in blockers for r in s.reasons)

    # Sentinel strings in model authority
    model_row = dict(base_row, row_role="model_surface", source_page="3d_model", source_reference="pb 3d surface editor")
    for sentinel in ["none", "null", "nan", ""]:
        r = dict(model_row, commercial_authority_status="APPROVED", commercial_authority_source=sentinel,
                 commercial_authority_reviewed_by="Bryce", commercial_authority_reviewed_at="2026-09-06T12:00:00Z")
        ok, reason = model_surface_authority(r)
        assert ok is False
        assert "no source evidence" in reason

    # Boolean workspace_id fails closed
    r_bool = dict(model_row, workspace_id=True, commercial_authority_status="APPROVED",
                  commercial_authority_source="pb 3d surface editor", commercial_authority_reviewed_by="Bryce",
                  commercial_authority_reviewed_at="2026-09-06T12:00:00Z")
    ok, reason = model_surface_authority(r_bool)
    assert ok is False
    assert "positive workspace identity" in reason

