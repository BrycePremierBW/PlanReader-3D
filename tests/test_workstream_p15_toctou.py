"""Unit and integration tests for Workstream P15 — TOCTOU Invalidation & Gate Integrity.
Tests:
- Invariant 13: No stale/invalidated preflight fingerprint may publish.
- Invariant 14: Every consequential field mutation changes fingerprint.
- Invariant 15: TOCTOU check re-verifies live database against preflight fingerprint within locked transaction.
"""

import sqlite3

import pytest

import pb_planreader_3d_app as app
from pb_commercial_export_preflight_v163 import (
    derive_export_preflight,
    verify_toctou_and_publish_jobhub,
)
from pb_planreader_3d_app import (
    ensure_jobhub_takeoff_tables,
    ensure_shared_jobhub_schema,
    publish_job_to_jobhub,
)
from pb_takeoff_authority_v164 import (
    AUTHORITY_FINGERPRINT_FIELD,
    AUTHORITY_REVIEWED_AT_FIELD,
    AUTHORITY_REVIEWED_BY_FIELD,
    AUTHORITY_SOURCE_FIELD,
    AUTHORITY_STATUS_FIELD,
    approve_model_surface_row,
)


class MockJobHubBridge:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.kind = "sqlite"

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def query(self, sql, params=(), conn=None):
        should_close = False
        if conn is None:
            conn = self.connect()
            should_close = True
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            if should_close:
                conn.close()

    def execute(self, sql, params=(), returning=False, conn=None):
        should_close = False
        if conn is None:
            conn = self.connect()
            should_close = True
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            if returning and "RETURNING" in sql.upper():
                res = cur.fetchone()
                row_id = res[0] if res else None
            else:
                row_id = cur.lastrowid
            if should_close:
                conn.commit()
            return row_id
        finally:
            if should_close:
                conn.close()


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "test_p15_planreader.db")
    hub_path = str(tmp_path / "test_p15_jobhub.db")

    orig_local_connect = getattr(app, "local_connect", None)
    orig_db_path = getattr(app, "DB_PATH", None)

    def _test_local_connect():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    app.local_connect = _test_local_connect
    app.DB_PATH = db_path
    app._pb_local_db_initialized_v1215 = False
    app.init_local_db()

    conn = app.local_connect()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO workspaces (job_no, job_name, builder_client, site_address, drawing_issue, estimator, jobhub_job_id, status)
            VALUES ('J100', 'Test Job Alpha', 'ABC Builders', '123 Main St', 'Rev A', 'John Estimator', 55, 'Draft')
        """)
        ws_id = cur.lastrowid

        cur.execute("INSERT INTO documents (workspace_id, file_name) VALUES (?, 'dwg1.pdf')", (ws_id,))
        doc_id = cur.lastrowid
        cur.execute("""
            INSERT INTO pages (workspace_id, document_id, page_no, page_label, page_type, px_per_m, scale_text)
            VALUES (?, ?, 1, 'A-01', 'Plan', 100.0, '1:100')
        """, (ws_id, doc_id))
        page_id = cur.lastrowid

        cur.execute("""
            INSERT INTO register_items (workspace_id, register_name, title, status)
            VALUES (?, 'Clarifications', 'RFI 1', 'Closed')
        """, (ws_id,))

        cur.execute("""
            INSERT INTO takeoff_rows (
                workspace_id, section, element, unit, quantity,
                coats, rate_per_unit,
                inclusion_status, row_role, quantity_status
            ) VALUES (
                ?, 'Internal', 'Wall Paint', 'm2', 100.0,
                2, 15.0,
                'included', 'manual_takeoff', 'measured'
            )
        """, (ws_id,))

        conn.commit()

        bridge = MockJobHubBridge(hub_path)
        ensure_shared_jobhub_schema(bridge)
        ensure_jobhub_takeoff_tables(bridge)
        bridge.execute("INSERT OR REPLACE INTO jobs (id, job_no, job_name, status) VALUES (55, 'J100', 'Test Job Alpha', 'Active')")

        yield conn, ws_id, page_id, bridge, hub_path
    finally:
        conn.close()
        if orig_local_connect is not None:
            app.local_connect = orig_local_connect
        if orig_db_path is not None:
            app.DB_PATH = orig_db_path


def test_workspace_metadata_mutation_invalidates_preflight_fingerprint(test_env):
    """Mutating workspace fields (job_name, site_address, builder_client, estimator) must alter preflight fingerprint."""
    conn, ws_id, _, _, _ = test_env

    pf1 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp1 = pf1.preflight_fingerprint

    cur = conn.cursor()
    cur.execute("""
        UPDATE workspaces
        SET job_name = 'Test Job Mutated', site_address = '999 New St', builder_client = 'XYZ Builders', estimator = 'Jane Estimator'
        WHERE id = ?
    """, (ws_id,))
    conn.commit()

    pf2 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp2 = pf2.preflight_fingerprint

    assert fp1 != fp2, "Mutating workspace metadata must invalidate the preflight fingerprint."


def test_scale_calibration_mutation_invalidates_preflight_fingerprint(test_env):
    """Mutating page scale (e.g. px_per_m) must alter preflight fingerprint even when remaining CALIBRATED."""
    conn, ws_id, page_id, _, _ = test_env

    pf1 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp1 = pf1.preflight_fingerprint

    cur = conn.cursor()
    cur.execute("UPDATE pages SET px_per_m = 200.0, scale_text = '1:50' WHERE id = ?", (page_id,))
    conn.commit()

    pf2 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp2 = pf2.preflight_fingerprint

    assert fp1 != fp2, "Mutating page scale must invalidate the preflight fingerprint."


def test_takeoff_quantity_and_field_mutation_invalidates_preflight_fingerprint(test_env):
    """Mutating takeoff row quantity, rates, coats, or substrate must alter preflight fingerprint."""
    conn, ws_id, _, _, _ = test_env

    pf1 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp1 = pf1.preflight_fingerprint

    cur = conn.cursor()
    cur.execute("UPDATE takeoff_rows SET quantity = 250.0 WHERE workspace_id = ?", (ws_id,))
    conn.commit()

    pf2 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp2 = pf2.preflight_fingerprint

    assert fp1 != fp2, "Mutating takeoff quantity must invalidate the preflight fingerprint."


def test_3d_approval_and_authority_metadata_mutation_invalidates_preflight_fingerprint(test_env):
    """Approving or modifying 3D model surface authority metadata must alter preflight fingerprint."""
    conn, ws_id, _, _, _ = test_env

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO takeoff_rows (
            workspace_id, section, element, unit, quantity,
            inclusion_status, row_role, quantity_status
        ) VALUES (
            ?, 'Internal', '3D Mass Wall', 'm2', 50.0,
            'included', 'model_surface', 'provisional'
        )
    """, (ws_id,))
    conn.commit()
    row_id = cur.lastrowid

    pf1 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp1 = pf1.preflight_fingerprint
    assert pf1.preflight_status == "BLOCKED"

    # Approve 3D surface
    cur.execute("SELECT * FROM takeoff_rows WHERE id = ?", (row_id,))
    row = dict(cur.fetchone())
    row["quantity_status"] = "measured"
    approved_dict = approve_model_surface_row(
        row,
        source="Manual 3D audit",
        reviewed_by="Bryce",
        reviewed_at="2026-09-06T12:00:00Z"
    )

    cur.execute("""
        UPDATE takeoff_rows
        SET commercial_authority_status = ?, commercial_authority_source = ?,
            commercial_authority_reviewed_by = ?, commercial_authority_reviewed_at = ?,
            commercial_authority_fingerprint = ?, quantity_status = 'measured',
            source_page = ?, source_reference = ?
        WHERE id = ?
    """, (
        approved_dict[AUTHORITY_STATUS_FIELD],
        approved_dict[AUTHORITY_SOURCE_FIELD],
        approved_dict[AUTHORITY_REVIEWED_BY_FIELD],
        approved_dict[AUTHORITY_REVIEWED_AT_FIELD],
        approved_dict[AUTHORITY_FINGERPRINT_FIELD],
        approved_dict.get("source_page", ""),
        approved_dict.get("source_reference", ""),
        row_id,
    ))
    conn.commit()

    pf2 = derive_export_preflight(conn, ws_id, bridge_available=True)
    fp2 = pf2.preflight_fingerprint

    assert fp1 != fp2, "Approving 3D surface authority must invalidate old preflight fingerprint."
    assert pf2.preflight_status == "AVAILABLE", f"Preflight status blocked by: {pf2.blocking_reasons}"


def test_verify_toctou_and_publish_jobhub_aborts_on_stale_fingerprint(test_env):
    """verify_toctou_and_publish_jobhub must raise RuntimeError when expected fingerprint is stale."""
    conn, ws_id, _, bridge, _ = test_env

    pf1 = derive_export_preflight(conn, ws_id, bridge_available=True)
    stale_fp = pf1.preflight_fingerprint

    # Mutate takeoff quantity
    cur = conn.cursor()
    cur.execute("UPDATE takeoff_rows SET quantity = 999.0 WHERE workspace_id = ?", (ws_id,))
    conn.commit()

    with pytest.raises(RuntimeError, match="Project QA/export state changed"):
        verify_toctou_and_publish_jobhub(
            conn,
            ws_id,
            bridge,
            "tester",
            expected_fingerprint=stale_fp,
            acknowledgement_confirmed=True,
            publish_fn=publish_job_to_jobhub,
        )


def test_verify_toctou_and_publish_jobhub_aborts_when_preflight_blocked(test_env):
    """verify_toctou_and_publish_jobhub must abort if workspace preflight is BLOCKED."""
    conn, ws_id, _, bridge, _ = test_env

    # Add unapproved model_surface row
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO takeoff_rows (
            workspace_id, section, element, unit, quantity,
            inclusion_status, row_role, quantity_status
        ) VALUES (
            ?, 'Internal', 'Unapproved Wall', 'm2', 50.0,
            'included', 'model_surface', 'provisional'
        )
    """, (ws_id,))
    conn.commit()

    pf = derive_export_preflight(conn, ws_id, bridge_available=True)
    assert pf.preflight_status == "BLOCKED"

    with pytest.raises(RuntimeError, match="Final publish blocked by preflight QA gate"):
        verify_toctou_and_publish_jobhub(
            conn,
            ws_id,
            bridge,
            "tester",
            expected_fingerprint=pf.preflight_fingerprint,
            acknowledgement_confirmed=True,
            publish_fn=publish_job_to_jobhub,
        )


def test_toctou_re_verification_passes_when_unmodified(test_env):
    """verify_toctou_and_publish_jobhub must succeed when preflight state is unmodified."""
    conn, ws_id, _, bridge, _ = test_env

    pf1 = derive_export_preflight(conn, ws_id, bridge_available=True)
    assert pf1.preflight_status == "AVAILABLE"

    res = verify_toctou_and_publish_jobhub(
        conn,
        ws_id,
        bridge,
        "tester",
        expected_fingerprint=pf1.preflight_fingerprint,
        acknowledgement_confirmed=True,
        publish_fn=publish_job_to_jobhub,
    )

    assert res.get("published") is True
    assert res.get("job_status") == "Published"
    assert res.get("package_id") is not None
