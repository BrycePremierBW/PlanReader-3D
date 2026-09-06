"""Regression tests for Workstream P14 — PlanReader -> JobHub Publication.

Audits PlanReader's integration contract with JobHub:
- package header
- package lines
- payload hash
- preflight fingerprint
- job status
- duplicates
- retry after Failed
- Pending cleanup
- blobs
- units
- workspace/job identity
- row eligibility (Invariant 21)
"""
from __future__ import annotations

import math
import pathlib
import sqlite3
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

import pb_planreader_3d_app as app
from pb_commercial_export_preflight_v163 import (
    derive_export_preflight,
    verify_toctou_and_publish_jobhub,
)
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
)


@pytest.fixture
def test_env():
    """Create isolated SQLite databases for PlanReader and JobHub."""
    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    local_db_path = tmp_dir / "planreader_local.db"
    hub_db_path = tmp_dir / "jobhub.db"

    # Monkeypatch local_connect to point to our test database
    def _local_connect():
        conn = sqlite3.connect(str(local_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    orig_local_connect = app.local_connect
    app.local_connect = _local_connect

    # Initialize full schema
    app.init_local_db()
    with _local_connect() as l_conn:
        l_conn.execute("""
        INSERT INTO workspaces (id, job_no, job_name, builder_client, site_address, drawing_issue, jobhub_job_id)
        VALUES (1, 'JOB-2026-P14', 'Commercial Tower', 'Builder Co', '100 King St', 'Rev C', 501)
        """)
        l_conn.execute("""
        INSERT INTO documents (workspace_id, file_name)
        VALUES (1, 'Architectural_Plans_RevC.pdf')
        """)
        l_conn.execute("""
        INSERT INTO pages (workspace_id, document_id, page_no, scale_text, px_per_m)
        VALUES (1, 1, 1, '1:100', 100.0)
        """)
        l_conn.execute("""
        INSERT INTO register_items (workspace_id, register_name, title, status)
        VALUES (1, 'door_schedule', 'Doors', 'confirmed')
        """)
        l_conn.execute("""
        INSERT INTO register_items (workspace_id, register_name, title, status)
        VALUES (1, 'inclusions', 'Inclusions', 'confirmed')
        """)
        l_conn.commit()

    # Set up JobHub SQLite database
    with sqlite3.connect(str(hub_db_path)) as h_conn:
        h_conn.execute("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT,
            notes TEXT
        )
        """)
        h_conn.execute("INSERT INTO jobs (id, status, notes) VALUES (501, 'Estimating', 'Initial')")
        h_conn.commit()

    bridge = app.JobHubBridge(kind="sqlite", source=str(hub_db_path), timeout=5.0)

    sample_takeoff = pd.DataFrame([
        {
            "id": 1,
            "section": "Internal walls and ceilings",
            "location": "Level 01",
            "substrate": "Plasterboard",
            "element": "Internal Wall",
            "unit": "m²",
            "quantity": 100.0,
            "labour_hours": 12.0,
            "paint_litres": 25.0,
            "rate_per_unit": 35.0,
            "value_ex_gst": 3500.0,
            "inclusion_status": "INCLUDED",
            "row_role": "work",
            "quantity_status": "measured",
            "notes": "Main walls",
            "source_reference": "Sheet A-101",
            "confidence": "High",
        },
        {
            "id": 2,
            "section": "External facade",
            "location": "Level 01",
            "substrate": "Render",
            "element": "External Wall",
            "unit": "m2",  # ASCII variant
            "quantity": 50.0,
            "labour_hours": 8.0,
            "paint_litres": 15.0,
            "rate_per_unit": 40.0,
            "value_ex_gst": 2000.0,
            "inclusion_status": "INCLUDED",
            "row_role": "work",
            "quantity_status": "measured",
            "notes": "North facade",
            "source_reference": "Sheet A-201",
            "confidence": "High",
        },
        {
            "id": 3,
            "section": "Internal trim",
            "location": "Level 01",
            "substrate": "Timber",
            "element": "Skirting",
            "unit": "LM",  # Length variant
            "quantity": 60.0,
            "labour_hours": 5.0,
            "paint_litres": 5.0,
            "rate_per_unit": 12.0,
            "value_ex_gst": 720.0,
            "inclusion_status": "INCLUDED",
            "row_role": "work",
            "quantity_status": "measured",
            "notes": "Timber skirtings",
            "source_reference": "Sheet A-101",
            "confidence": "High",
        },
        {
            "id": 4,
            "section": "Internal doors",
            "location": "Level 01",
            "substrate": "Timber Doors",
            "element": "Door Leaf",
            "unit": "each",  # Count variant
            "quantity": 10.0,
            "labour_hours": 6.0,
            "paint_litres": 4.0,
            "rate_per_unit": 80.0,
            "value_ex_gst": 800.0,
            "inclusion_status": "INCLUDED",
            "row_role": "work",
            "quantity_status": "measured",
            "notes": "Flush doors",
            "source_reference": "Sheet A-101",
            "confidence": "High",
        },
        {
            "id": 5,
            "section": "Internal floor reference",
            "location": "Level 01",
            "substrate": "Concrete",
            "element": "Floor Slab",
            "unit": "m²",
            "quantity": 120.0,
            "labour_hours": 0.0,
            "paint_litres": 0.0,
            "rate_per_unit": 0.0,
            "value_ex_gst": 0.0,
            "inclusion_status": "INCLUDED",
            "row_role": "floor_area",  # Ineligible floor reference
            "quantity_status": "measured",
            "notes": "Floor reference only",
            "source_reference": "Sheet A-101",
            "confidence": "High",
        },
    ])

    with _local_connect() as l_conn:
        for r in sample_takeoff.to_dict("records"):
            l_conn.execute("""
            INSERT INTO takeoff_rows (
                workspace_id, section, location, substrate, element, unit, quantity,
                rate_per_unit, inclusion_status, row_role, quantity_status, notes, source_reference, confidence
            ) VALUES (
                1, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """, (
                r["section"], r["location"], r["substrate"], r["element"], r["unit"], r["quantity"],
                r["rate_per_unit"], r["inclusion_status"], r["row_role"], r["quantity_status"], r["notes"], r["source_reference"], r["confidence"]
            ))
        l_conn.commit()

    yield {
        "tmp_dir": tmp_dir,
        "local_db_path": local_db_path,
        "hub_db_path": hub_db_path,
        "bridge": bridge,
        "sample_takeoff": sample_takeoff,
    }

    app.local_connect = orig_local_connect


class TestJobHubWorkspaceAndJobIdentity:
    """Audit workspace and job identity validation."""

    def test_nonexistent_workspace_fails_closed(self, test_env):
        """Publishing a non-existent workspace ID must fail closed with informative RuntimeError."""
        bridge = test_env["bridge"]
        with pytest.raises(RuntimeError, match=r"Workspace.*not found"):
            app.publish_job_to_jobhub(99999, bridge, "Tester")

    def test_unlinked_workspace_fails_closed(self, test_env):
        """Publishing a workspace not linked to a JobHub job must fail closed."""
        bridge = test_env["bridge"]
        with sqlite3.connect(str(test_env["local_db_path"])) as l_conn:
            l_conn.execute("UPDATE workspaces SET jobhub_job_id=NULL WHERE id=1")
            l_conn.commit()

        with pytest.raises(RuntimeError, match=r"Link this workspace to a JobHub job"):
            app.publish_job_to_jobhub(1, bridge, "Tester")

    def test_nonexistent_jobhub_job_fails_closed(self, test_env):
        """Workspace linked to a job ID that does NOT exist in JobHub must fail closed."""
        bridge = test_env["bridge"]
        with sqlite3.connect(str(test_env["local_db_path"])) as l_conn:
            l_conn.execute("UPDATE workspaces SET jobhub_job_id=88888 WHERE id=1")
            l_conn.commit()

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=test_env["sample_takeoff"]):
            with pytest.raises(RuntimeError, match=r"Job.*88888.*not found|does not exist"):
                app.publish_job_to_jobhub(
                    1, bridge, "Tester",
                    preflight_fingerprint="fp_nonexistent_job_123",
                    payload_hash="hash_nonexistent_job_123"
                )

        # Verify no phantom package or blobs were created in JobHub
        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            tables = [r[0] for r in h_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "painting_takeoff_packages" in tables:
                rows = h_conn.execute("SELECT COUNT(*) FROM painting_takeoff_packages WHERE job_id=88888").fetchone()[0]
                assert rows == 0


class TestJobHubUnitNormalizationAndPackageHeaderLines:
    """Audit unit normalization across package header, package lines, and synced rows."""

    def test_package_header_and_lines_unit_normalization(self, test_env):
        """Package header interior/exterior m² and lines m2/lm/count must handle unit variants cleanly."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes_test"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_bytes_test"):

            res = app.publish_job_to_jobhub(
                1, bridge, "TesterUnits",
                preflight_fingerprint="fp_unit_norm_12345678",
                payload_hash="hash_unit_norm_12345678"
            )
            assert res["published"] is True
            package_id = res["package_id"]

        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            # 1. Package Header
            pkg = h_conn.execute("SELECT * FROM painting_takeoff_packages WHERE id=?", (package_id,)).fetchone()
            assert pkg is not None
            assert pkg["status"] == "Published"
            # Interior had 100.0 m² (unit "m²")
            assert math.isclose(pkg["interior_total_m2"], 100.0, rel_tol=1e-3)
            # Exterior had 50.0 m² (unit "m2" ASCII variant - MUST NOT BE 0.0!)
            assert math.isclose(pkg["exterior_total_m2"], 50.0, rel_tol=1e-3)

            # 2. Package Lines
            lines = h_conn.execute("SELECT * FROM painting_takeoff_lines WHERE package_id=? ORDER BY id", (package_id,)).fetchall()
            # 4 work rows published (floor_area row #5 excluded)
            assert len(lines) == 4

            # Line 1: m² wall
            l1 = lines[0]
            assert math.isclose(l1["m2"], 100.0, rel_tol=1e-3)
            assert l1["unit"] == "m²"

            # Line 2: m2 ASCII variant external wall (m2 field MUST NOT BE 0.0, unit canonicalized to m²)
            l2 = lines[1]
            assert math.isclose(l2["m2"], 50.0, rel_tol=1e-3)
            assert l2["unit"] == "m²"

            # Line 3: LM variant skirting (lineal_metres MUST NOT BE 0.0, unit canonicalized to lm)
            l3 = lines[2]
            assert math.isclose(l3["lineal_metres"], 60.0, rel_tol=1e-3)
            assert l3["unit"] == "lm"

            # Line 4: each variant door (element_count MUST NOT BE 0.0, unit canonicalized to item or No.)
            l4 = lines[3]
            assert math.isclose(l4["element_count"], 10.0, rel_tol=1e-3)
            assert l4["unit"] in ("item", "No.")

    def test_jobhub_sync_takeoff_rows_unit_normalization(self, test_env):
        """_sync_jobhub_takeoff_rows must populate qty_m2, lineal_m, count across unit variants."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        app.ensure_shared_jobhub_schema(bridge)
        synced = app._sync_jobhub_takeoff_rows(bridge, 501, takeoff)
        assert synced == 4  # 4 work rows

        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            rows = h_conn.execute("SELECT * FROM job_takeoff_rows WHERE job_id=501 ORDER BY id").fetchall()
            assert len(rows) == 4

            row_map = {r["substrate"]: r for r in rows}
            # Plasterboard internal wall
            assert math.isclose(row_map["Plasterboard"]["qty_m2"], 100.0, rel_tol=1e-3)
            # Render external wall (unit was 'm2', qty_m2 MUST NOT BE 0.0!)
            assert math.isclose(row_map["Render"]["qty_m2"], 50.0, rel_tol=1e-3)
            # Skirting (unit was 'LM', lineal_m MUST NOT BE 0.0!)
            assert math.isclose(row_map["Timber"]["lineal_m"], 60.0, rel_tol=1e-3)
            # Door Leaf (unit was 'each', count MUST NOT BE 0.0!)
            assert math.isclose(row_map["Timber Doors"]["count"], 10.0, rel_tol=1e-3)


class TestJobHubFailureRollbackAndStatusIntegrity:
    """Audit rollback and status integrity when publish fails."""

    def test_job_status_rolled_back_on_publish_failure(self, test_env):
        """When publish fails mid-flight, jobs.status must NOT be committed as Published."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        # Intercept bridge.execute to fail during package status finalization
        orig_execute = bridge.execute
        def failing_execute(sql, params=(), returning=False, conn=None):
            if "UPDATE painting_takeoff_packages SET status='Published'" in sql:
                raise RuntimeError("Simulated failure during package publication finalization")
            return orig_execute(sql, params, returning=returning, conn=conn)

        bridge.execute = failing_execute

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_bytes"):

            with pytest.raises(RuntimeError, match=r"Mandatory publish side effect failed"):
                app.publish_job_to_jobhub(
                    1, bridge, "TesterRollback",
                    preflight_fingerprint="fp_rollback_test_123",
                    payload_hash="hash_rollback_test_123"
                )

        # Inspect JobHub database state with a fresh connection
        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            job = h_conn.execute("SELECT status, notes FROM jobs WHERE id=501").fetchone()
            # CRITICAL: Job must remain 'Estimating', NOT 'Published'!
            assert job["status"] == "Estimating", f"Job status corrupted to {job['status']}!"

            # Package must be recorded as Failed with honest error notes
            pkg = h_conn.execute("SELECT status, notes FROM painting_takeoff_packages WHERE job_id=501").fetchone()
            assert pkg is not None
            assert pkg["status"] == "Failed"
            assert "Simulated failure" in pkg["notes"]


class TestJobHubRetryAfterFailedAndPendingCleanup:
    """Audit retry after Failed and cleanup of abandoned Pending packages."""

    def test_retry_after_failed_succeeds_cleanly(self, test_env):
        """Publish retry after a previous Failed attempt must succeed and update job to Published."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        # Step 1: Simulate failed publish
        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", side_effect=OSError("Corrupt 3D model render")):

            with pytest.raises(RuntimeError, match=r"Mandatory publish side effect failed"):
                app.publish_job_to_jobhub(
                    1, bridge, "TesterFail",
                    preflight_fingerprint="fp_retry_lifecycle_123",
                    payload_hash="hash_retry_lifecycle_123"
                )

        # Step 2: Retry with fixed downstream
        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"fixed_progress_bytes"):

            res = app.publish_job_to_jobhub(
                1, bridge, "TesterRetry",
                preflight_fingerprint="fp_retry_lifecycle_123",
                payload_hash="hash_retry_lifecycle_123"
            )
            assert res["published"] is True
            assert res["job_status"] == "Published"

        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            job = h_conn.execute("SELECT status FROM jobs WHERE id=501").fetchone()
            assert job["status"] == "Published"

            pkgs = h_conn.execute("SELECT id, status FROM painting_takeoff_packages WHERE job_id=501 ORDER BY id").fetchall()
            assert len(pkgs) == 2
            assert pkgs[0]["status"] == "Failed"
            assert pkgs[1]["status"] == "Published"

    def test_stale_pending_package_cleaned_up_on_retry(self, test_env):
        """Stale Pending package from abandoned/crashed session must be cleaned up rather than blocking forever."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        app.ensure_jobhub_takeoff_tables(bridge)

        # Insert stale Pending package from dead session
        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.execute("""
            INSERT INTO painting_takeoff_packages (job_id, takeoff_no, status, notes, created_at, updated_at)
            VALUES (501, 'PR-JOB-2026-P14-PUB-fp_stale_pend', 'Pending', 'Published by PB PlanReader. Preflight Fingerprint: fp_stale_pending_123 | Payload Hash: hash_stale_123', '2026-09-01T00:00:00', '2026-09-01T00:00:00')
            """)
            h_conn.commit()

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_bytes"):

            res = app.publish_job_to_jobhub(
                1, bridge, "TesterStalePending",
                preflight_fingerprint="fp_stale_pending_123",
                payload_hash="hash_stale_123"
            )
            assert res["published"] is True
            assert res["job_status"] == "Published"

        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            pkgs = h_conn.execute("SELECT id, status, notes FROM painting_takeoff_packages WHERE job_id=501 ORDER BY id").fetchall()
            # Stale pending package was transitioned to Failed/Cleaned, and new package Published
            statuses = [p["status"] for p in pkgs]
            assert "Published" in statuses
            assert "Pending" not in statuses


class TestJobHubDuplicateAndFreshDb:
    """Audit duplicate prevention and fresh database schema handling."""

    def test_fresh_jobhub_db_without_preexisting_tables(self, test_env):
        """Fresh JobHub database without painting_takeoff_packages must not crash verify_toctou_and_publish_jobhub."""
        # Create fresh JobHub DB with only jobs table
        fresh_hub_path = test_env["tmp_dir"] / "fresh_jobhub.db"
        with sqlite3.connect(str(fresh_hub_path)) as f_conn:
            f_conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT, notes TEXT)")
            f_conn.execute("INSERT INTO jobs (id, status) VALUES (501, 'Estimating')")
            f_conn.commit()

        fresh_bridge = app.JobHubBridge(kind="sqlite", source=str(fresh_hub_path), timeout=5.0)

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=test_env["sample_takeoff"]), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_bytes"):

            # Calling verify_toctou_and_publish_jobhub directly on fresh DB must succeed without OperationalError
            c_meta = sqlite3.connect(str(test_env["local_db_path"]))
            try:
                preflight = derive_export_preflight(c_meta, 1, bridge_available=True)
                res = verify_toctou_and_publish_jobhub(
                    c_meta, 1, fresh_bridge, "TesterFresh",
                    expected_fingerprint=preflight.preflight_fingerprint,
                    acknowledgement_confirmed=True,
                    publish_fn=app.publish_job_to_jobhub,
                )
                assert res["published"] is True
            finally:
                c_meta.close()

    def test_duplicate_publication_fails_closed(self, test_env):
        """Publishing the exact same preflight fingerprint twice must fail closed."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_bytes"):

            res1 = app.publish_job_to_jobhub(
                1, bridge, "TesterDup",
                preflight_fingerprint="fp_dup_guard_12345678",
                payload_hash="hash_dup_guard_12345678"
            )
            assert res1["published"] is True

            with pytest.raises(RuntimeError, match=r"already.*published|Package.*has already been published"):
                app.publish_job_to_jobhub(
                    1, bridge, "TesterDup",
                    preflight_fingerprint="fp_dup_guard_12345678",
                    payload_hash="hash_dup_guard_12345678"
                )


class TestJobHubBlobsAndProgressMarker:
    """Audit blob persistence and honest error reporting."""

    def test_progress_marker_push_blob_failure_reported_honestly(self, test_env):
        """push_progress_marker_to_jobhub must not report blob_recorded: True when blob storage fails."""
        bridge = test_env["bridge"]
        takeoff = test_env["sample_takeoff"]

        orig_execute = bridge.execute
        def failing_blob_execute(sql, params=(), returning=False, conn=None):
            if "INSERT INTO job_document_blobs" in sql:
                raise RuntimeError("Blob storage disk full")
            return orig_execute(sql, params, returning=returning, conn=conn)

        bridge.execute = failing_blob_execute

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=takeoff), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_marker_bytes"), \
             patch("pb_planreader_3d_app.push_takeoff_to_jobhub", return_value=(10, 4)):

            # Must either fail closed or honestly report blob_recorded: False
            try:
                res = app.push_progress_marker_to_jobhub(1, bridge, "TesterBlobFail")
                assert res.get("blob_recorded") is False, "Reported blob_recorded: True despite blob write failure!"
            except RuntimeError as exc:
                assert "Blob storage disk full" in str(exc) or "blob" in str(exc).lower()


class TestJobHubRowEligibility:
    """Audit Invariant 21: JobHub receives only eligible rows."""

    def test_jobhub_receives_only_eligible_rows(self, test_env):
        """JobHub package lines and synced takeoff rows must exclude floor refs, exclusions, unapproved models, and non-positive quantities."""
        bridge = test_env["bridge"]
        mixed_takeoff = pd.DataFrame([
            {
                "id": 1, "section": "Internal", "location": "L1", "substrate": "Plasterboard",
                "element": "Wall", "unit": "m²", "quantity": 100.0, "labour_hours": 10.0, "paint_litres": 20.0,
                "inclusion_status": "INCLUDED", "row_role": "work", "quantity_status": "measured",
            },
            {
                "id": 2, "section": "Internal", "location": "L1", "substrate": "Concrete",
                "element": "Floor", "unit": "m²", "quantity": 80.0, "labour_hours": 0.0, "paint_litres": 0.0,
                "inclusion_status": "INCLUDED", "row_role": "floor_area", "quantity_status": "measured",
            },
            {
                "id": 3, "section": "Internal", "location": "L1", "substrate": "Plasterboard",
                "element": "Feature", "unit": "m²", "quantity": 30.0, "labour_hours": 5.0, "paint_litres": 8.0,
                "inclusion_status": "EXCLUDED", "row_role": "work", "quantity_status": "measured",
            },
            {
                "id": 4, "section": "External", "location": "Facade", "substrate": "Render",
                "element": "Unapproved 3D", "unit": "m²", "quantity": 40.0, "labour_hours": 6.0, "paint_litres": 10.0,
                "inclusion_status": "INCLUDED", "row_role": "model_surface", "commercial_authority_status": "REVIEW_REQUIRED",
            },
            approve_model_surface_row(
                {
                    "id": 5, "workspace_id": 1, "section": "External", "location": "Facade", "substrate": "Render",
                    "element": "Approved 3D", "unit": "m²", "quantity": 25.0, "labour_hours": 4.0, "paint_litres": 6.0,
                    "inclusion_status": "INCLUDED", "row_role": "model_surface",
                },
                source="Drawing Rev C", reviewed_by="Chief Estimator", reviewed_at="2026-09-04T10:00:00+10:00",
            ),
            {
                "id": 6, "section": "Internal", "location": "L1", "substrate": "Plasterboard",
                "element": "Zero Qty", "unit": "m²", "quantity": 0.0, "labour_hours": 0.0, "paint_litres": 0.0,
                "inclusion_status": "INCLUDED", "row_role": "work", "quantity_status": "measured",
            },
        ])

        with patch("pb_planreader_3d_app.dataframe_for_takeoff", return_value=mixed_takeoff), \
             patch("pb_planreader_3d_app.quote_workbook_bytes", return_value=b"quote_bytes"), \
             patch("pb_planreader_3d_app.progress_package_bytes", return_value=b"progress_bytes"):

            res = app.publish_job_to_jobhub(
                1, bridge, "TesterEligibility",
                preflight_fingerprint="fp_eligibility_12345678",
                payload_hash="hash_eligibility_12345678"
            )
            assert res["published"] is True
            package_id = res["package_id"]

        with sqlite3.connect(str(test_env["hub_db_path"])) as h_conn:
            h_conn.row_factory = sqlite3.Row
            lines = h_conn.execute("SELECT * FROM painting_takeoff_lines WHERE package_id=? ORDER BY id", (package_id,)).fetchall()
            # Only row 1 (ordinary wall) and row 5 (approved 3D model) are eligible!
            # Row 2 (floor_area), Row 3 (EXCLUDED), Row 4 (unapproved model), Row 6 (zero qty) must NOT be present!
            assert len(lines) == 2, f"Expected 2 eligible lines, got {len(lines)}: {[l['element_count'] for l in lines]}"
            elements = [l["labour_category"] for l in lines]
            assert "Wall" in elements
            assert "Approved 3D" in elements
            assert "Floor" not in elements
            assert "Feature" not in elements
            assert "Unapproved 3D" not in elements
            assert "Zero Qty" not in elements

