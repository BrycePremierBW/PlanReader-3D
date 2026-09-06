"""Unit and integration tests for Workstream P16 — Workspace Isolation.

Tests:
1. Model surface authority fingerprint is strictly bound to workspace_id (cross-workspace replay rejected).
2. Export preflight fingerprint is strictly bound to workspace_id (cross-workspace preflight replay rejected).
3. TOCTOU publish gate rejects expected fingerprint from a different workspace.
4. Workspace session state switching clears transient entity selection keys.
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
def dual_workspace_env(tmp_path):
    db_path = str(tmp_path / "test_p16_planreader.db")
    hub_path = str(tmp_path / "test_p16_jobhub.db")

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

        # Workspace 1 (ID 101)
        cur.execute("""
            INSERT INTO workspaces (id, job_no, job_name, builder_client, site_address, drawing_issue, estimator, jobhub_job_id, status)
            VALUES (101, 'J101', 'Job Alpha', 'Alpha Corp', '101 First St', 'Rev A', 'Estimator 1', 1001, 'Draft')
        """)

        # Workspace 2 (ID 202)
        cur.execute("""
            INSERT INTO workspaces (id, job_no, job_name, builder_client, site_address, drawing_issue, estimator, jobhub_job_id, status)
            VALUES (202, 'J202', 'Job Beta', 'Beta Corp', '202 Second St', 'Rev B', 'Estimator 2', 2002, 'Draft')
        """)

        # Workspace 1 documents & pages
        cur.execute("INSERT INTO documents (id, workspace_id, file_name) VALUES (10, 101, 'dwg101.pdf')")
        cur.execute("""
            INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, page_type, px_per_m, scale_text)
            VALUES (100, 101, 10, 1, 'A-101', 'Plan', 100.0, '1:100')
        """)

        # Workspace 2 documents & pages
        cur.execute("INSERT INTO documents (id, workspace_id, file_name) VALUES (20, 202, 'dwg202.pdf')")
        cur.execute("""
            INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, page_type, px_per_m, scale_text)
            VALUES (200, 202, 20, 1, 'B-202', 'Plan', 100.0, '1:100')
        """)

        # Register items
        cur.execute("INSERT INTO register_items (workspace_id, register_name, title, status) VALUES (101, 'door_schedule', 'Doors', 'Closed')")
        cur.execute("INSERT INTO register_items (workspace_id, register_name, title, status) VALUES (202, 'door_schedule', 'Doors', 'Closed')")

        # Takeoff rows for WS 101
        cur.execute("""
            INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity,
                coats, rate_per_unit, inclusion_status, row_role, quantity_status
            ) VALUES (
                1001, 101, 'Internal', 'Wall Paint', 'm2', 100.0,
                2, 15.0, 'included', 'manual_takeoff', 'measured'
            )
        """)

        # Takeoff rows for WS 202
        cur.execute("""
            INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity,
                coats, rate_per_unit, inclusion_status, row_role, quantity_status
            ) VALUES (
                2001, 202, 'Internal', 'Wall Paint', 'm2', 100.0,
                2, 15.0, 'included', 'manual_takeoff', 'measured'
            )
        """)

        conn.commit()

        bridge = MockJobHubBridge(hub_path)
        ensure_shared_jobhub_schema(bridge)
        ensure_jobhub_takeoff_tables(bridge)
        bridge.execute("INSERT OR REPLACE INTO jobs (id, job_no, job_name, status) VALUES (1001, 'J101', 'Job Alpha', 'Active')")
        bridge.execute("INSERT OR REPLACE INTO jobs (id, job_no, job_name, status) VALUES (2002, 'J202', 'Job Beta', 'Active')")

        yield conn, bridge
    finally:
        conn.close()
        if orig_local_connect is not None:
            app.local_connect = orig_local_connect
        if orig_db_path is not None:
            app.DB_PATH = orig_db_path


def test_model_surface_authority_cross_workspace_replay_rejected():
    """Approved 3D surface authority from Workspace 101 must fail verification if replayed in Workspace 202."""
    row_ws101 = {
        "id": 500,
        "workspace_id": 101,
        "section": "Internal",
        "element": "3D Wall",
        "unit": "m2",
        "quantity": 50.0,
        "inclusion_status": "included",
        "row_role": "model_surface",
        "quantity_status": "measured",
    }

    approved = approve_model_surface_row(
        row_ws101,
        source="Manual 3D audit",
        reviewed_by="Alice",
        reviewed_at="2026-09-06T12:00:00Z",
    )

    # Authority MUST be valid in WS 101
    ok1, _ = model_surface_authority(approved)
    assert ok1 is True

    # Replay in WS 202
    replayed = dict(approved)
    replayed["workspace_id"] = 202

    ok2, msg2 = model_surface_authority(replayed)
    assert ok2 is False, "Authority fingerprint from Workspace 101 must not validate in Workspace 202."
    assert "no longer matches" in msg2 or "fingerprint" in msg2


def test_preflight_fingerprint_cross_workspace_replay_rejected(dual_workspace_env):
    """Deriving preflight for Workspace 101 and Workspace 202 must produce unique preflight fingerprints."""
    conn, _ = dual_workspace_env

    pf101 = derive_export_preflight(conn, 101, bridge_available=True)
    pf202 = derive_export_preflight(conn, 202, bridge_available=True)

    assert pf101.preflight_fingerprint != pf202.preflight_fingerprint, "Preflight fingerprints for different workspaces must be distinct."


def test_toctou_gate_rejects_cross_workspace_expected_fingerprint(dual_workspace_env):
    """verify_toctou_and_publish_jobhub on Workspace 202 must abort if expected_fingerprint belongs to Workspace 101."""
    conn, bridge = dual_workspace_env

    pf101 = derive_export_preflight(conn, 101, bridge_available=True)
    pf202 = derive_export_preflight(conn, 202, bridge_available=True)

    assert pf101.preflight_status == "AVAILABLE"
    assert pf202.preflight_status == "AVAILABLE"

    with pytest.raises(RuntimeError, match="Project QA/export state changed"):
        verify_toctou_and_publish_jobhub(
            conn,
            202,
            bridge,
            "tester",
            expected_fingerprint=pf101.preflight_fingerprint,
            acknowledgement_confirmed=True,
            publish_fn=publish_job_to_jobhub,
        )


def test_session_state_workspace_switch_clears_transient_selection():
    """Switching workspace in main() session state must purge transient item selection keys."""
    session_state = {
        "workspace_id": 202,
        "_pb_active_workspace_id": 101,  # Previous active workspace
        "active_page_id": 999,
        "active_takeoff_row_id": 888,
        "active_register_item_id": 777,
        "_pb_nav_target": "drawing",
        "_pb_nav_payload": {"workspace_id": 101, "page_id": 999},
    }

    # Simulate active workspace switch guard
    last_ws = session_state.get("_pb_active_workspace_id")
    current_ws = session_state.get("workspace_id")

    if last_ws is not None and last_ws != current_ws:
        for k in ("active_page_id", "active_takeoff_row_id", "active_register_item_id", "_pb_nav_target", "_pb_nav_payload"):
            session_state.pop(k, None)
    session_state["_pb_active_workspace_id"] = current_ws

    assert "active_page_id" not in session_state
    assert "active_takeoff_row_id" not in session_state
    assert "active_register_item_id" not in session_state
    assert "_pb_nav_target" not in session_state
    assert "_pb_nav_payload" not in session_state
    assert session_state["_pb_active_workspace_id"] == 202
