"""Unit and integration tests for Workstream P19 — PlanReader Streamlit UI State.

Tests:
1. plan_mapper_page calculates and passes correct selectbox index when active_page_id is set.
2. drawing_register_page calculates and passes correct preview selectbox index when active_register_item_id is set.
3. subscription_takeoff_page 3D surface commercial authority expander selects target row index when active_takeoff_row_id is set.
4. clear_workspace_session_state_if_changed purges all workspace-bound session state on workspace switch.
"""

import sqlite3
from unittest.mock import MagicMock, patch

import streamlit as st

import pb_planreader_3d_app as app


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


def test_plan_mapper_target_page_navigation(tmp_path):
    """Verify plan_mapper_page selects correct page index matching active_page_id."""
    db_path = str(tmp_path / "plan_mapper_nav.db")
    orig_lc, orig_dp = _bind_test_db(db_path)
    try:
        app.init_local_db()
        with app.local_connect() as conn:
            conn.execute("INSERT INTO workspaces(id, job_name, created_at, updated_at) VALUES (1, 'WS 1', '2026-01-01', '2026-01-01')")
            conn.execute("INSERT INTO documents(id, workspace_id, file_name, path) VALUES (1, 1, 'test.pdf', '/tmp/test.pdf')")
            conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, image_path, selected) VALUES (10, 1, 1, 1, 'P1', 'Floor Plan', '/tmp/p1.png', 1)")
            conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, image_path, selected) VALUES (20, 1, 1, 2, 'P2', 'Elevation', '/tmp/p2.png', 1)")
            conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, image_path, selected) VALUES (30, 1, 1, 3, 'P3', 'Detail', '/tmp/p3.png', 1)")
            conn.commit()

        workspace = {"id": 1, "job_name": "WS 1"}

        st.session_state.clear()
        st.session_state["active_page_id"] = 30  # Target page #30 (index 2)

        selectbox_calls = []
        def mock_selectbox(label, options, **kwargs):
            selectbox_calls.append((label, options, kwargs))
            idx = kwargs.get("index", 0)
            return options[idx]

        with patch("streamlit.selectbox", side_effect=mock_selectbox), \
             patch("pb_planreader_3d_app.hero"), patch("streamlit.info"), patch("streamlit.tabs", return_value=[MagicMock()]*4), \
             patch("streamlit.expander", return_value=MagicMock()), patch("streamlit.columns", return_value=[MagicMock()]*5), \
             patch("streamlit.button", return_value=False), patch("streamlit.markdown"), patch("streamlit.caption"), patch("streamlit.warning"):
            try:
                app.plan_mapper_page(workspace)
            except Exception as exc:
                assert exc is not None

        drawing_page_calls = [c for c in selectbox_calls if c[0] == "Drawing page"]
        assert len(drawing_page_calls) == 1
        _, options, kwargs = drawing_page_calls[0]
        assert kwargs.get("index") == 2
        assert options[2].startswith("#30")
    finally:
        _unbind_test_db(orig_lc, orig_dp)


def test_drawing_register_target_item_navigation(tmp_path):
    """Verify drawing_register_page selects correct preview index matching active_register_item_id."""
    db_path = str(tmp_path / "drawing_register_nav.db")
    orig_lc, orig_dp = _bind_test_db(db_path)
    try:
        app.init_local_db()
        with app.local_connect() as conn:
            conn.execute("INSERT INTO workspaces(id, job_name, created_at, updated_at) VALUES (1, 'WS 1', '2026-01-01', '2026-01-01')")
            conn.execute("INSERT INTO documents(id, workspace_id, file_name, path) VALUES (1, 1, 'test.pdf', '/tmp/test.pdf')")
            conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, image_path, selected) VALUES (10, 1, 1, 1, 'P1', 'Floor Plan', '/tmp/p1.png', 1)")
            conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, image_path, selected) VALUES (20, 1, 1, 2, 'P2', 'Elevation', '/tmp/p2.png', 1)")
            conn.execute("INSERT INTO pages(id, workspace_id, document_id, page_no, page_label, page_type, image_path, selected) VALUES (30, 1, 1, 3, 'P3', 'Detail', '/tmp/p3.png', 1)")
            conn.commit()

        workspace = {"id": 1, "job_name": "WS 1"}

        st.session_state.clear()
        st.session_state["active_register_item_id"] = 20  # Target page/register ID #20 (index 1)

        selectbox_calls = []
        def mock_selectbox(label, options, **kwargs):
            selectbox_calls.append((label, options, kwargs))
            idx = kwargs.get("index", 0)
            return options[idx]

        with patch("streamlit.selectbox", side_effect=mock_selectbox), \
             patch("pb_planreader_3d_app.hero"), patch("streamlit.info"), patch("streamlit.data_editor"), patch("streamlit.button", return_value=False), \
             patch("streamlit.subheader"), patch("streamlit.image"), patch("streamlit.success"):
            try:
                app.drawing_register_page(workspace)
            except Exception as exc:
                assert exc is not None

        preview_page_calls = [c for c in selectbox_calls if c[0] == "Preview page"]
        assert len(preview_page_calls) == 1
        _, options, kwargs = preview_page_calls[0]
        assert kwargs.get("index") == 1
        assert options[1].startswith("#20")
    finally:
        _unbind_test_db(orig_lc, orig_dp)


def test_3d_surface_authority_target_row_selection(tmp_path):
    """Verify subscription_takeoff_page 3D surface expander selects target row index when active_takeoff_row_id is set."""
    db_path = str(tmp_path / "surface_authority_nav.db")
    orig_lc, orig_dp = _bind_test_db(db_path)
    try:
        app.init_local_db()
        with app.local_connect() as conn:
            conn.execute("INSERT INTO workspaces(id, job_name, created_at, updated_at) VALUES (1, 'WS 1', '2026-01-01', '2026-01-01')")
            conn.execute("""INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, row_role, commercial_authority_status, created_at, updated_at)
                            VALUES (100, 1, 'Int', 'Wall 1', 'Plasterboard', 'Render', 'Acrylic', 10.0, 'm2', 'Measured', '3d_model', '3d_surface_editor', 'INCLUSION', 'model_surface', 'REVIEW_REQUIRED', '2026-01-01', '2026-01-01')""")
            conn.execute("""INSERT INTO takeoff_rows(id, workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, source_page, source_reference, inclusion_status, row_role, commercial_authority_status, created_at, updated_at)
                            VALUES (200, 1, 'Int', 'Wall 2', 'Plasterboard', 'Render', 'Acrylic', 25.0, 'm2', 'Measured', '3d_model', '3d_surface_editor', 'INCLUSION', 'model_surface', 'REVIEW_REQUIRED', '2026-01-01', '2026-01-01')""")
            conn.commit()

        workspace = {"id": 1, "job_name": "WS 1"}

        st.session_state.clear()
        st.session_state["active_takeoff_row_id"] = 200  # Target row #200 (index 1)

        selectbox_calls = []
        def mock_selectbox(label, options, **kwargs):
            selectbox_calls.append((label, options, kwargs))
            idx = kwargs.get("index", 0)
            return options[idx]

        def mock_columns(spec, **kwargs):
            n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            return [MagicMock() for _ in range(n)]

        with patch("streamlit.selectbox", side_effect=mock_selectbox), \
             patch("pb_planreader_3d_app.hero"), patch("streamlit.info"), patch("streamlit.data_editor"), patch("streamlit.button", return_value=False), \
             patch("streamlit.tabs", return_value=[MagicMock()]*6), patch("streamlit.expander", return_value=MagicMock()), \
             patch("streamlit.columns", side_effect=mock_columns), patch("streamlit.text_input"), patch("streamlit.warning"), patch("streamlit.caption"):
            try:
                app.subscription_takeoff_page(workspace, "api-key", "OpenAI")
            except Exception as exc:
                assert exc is not None

        surface_calls = [c for c in selectbox_calls if c[0] == "3D surface row"]
        assert len(surface_calls) == 1
        _, options, kwargs = surface_calls[0]
        assert kwargs.get("index") == 1
        assert options[1].startswith("#200")
    finally:
        _unbind_test_db(orig_lc, orig_dp)


def test_workspace_session_state_isolation_on_switch():
    """Verify clear_workspace_session_state_if_changed purges all workspace-bound session state on workspace switch."""
    st.session_state.clear()
    st.session_state["_pb_last_active_workspace_id"] = 1
    st.session_state["active_page_id"] = 10
    st.session_state["active_takeoff_row_id"] = 100
    st.session_state["active_register_item_id"] = 5
    st.session_state["_pb_nav_target"] = "drawing"
    st.session_state["_pb_nav_payload"] = {"page_id": 10}
    st.session_state["latest_ai_result"] = {"rows": [1, 2, 3]}
    st.session_state["latest_render_result"] = {"status": "ok"}
    st.session_state["takeoff_editor"] = {"edited_rows": {"0": {"quantity": 50}}}
    st.session_state["offline_results"] = {"data": "old"}
    st.session_state["offline_takeoff"] = {"data": "old"}
    st.session_state["offline_doc_name"] = "old.pdf"
    st.session_state["_pb_ack_workspace_id"] = 1
    st.session_state["_pb_ack_fp"] = "abc"
    st.session_state["_pb_ack_confirmed"] = True

    # Switch workspace to 2
    app.clear_workspace_session_state_if_changed(2)

    assert st.session_state["_pb_last_active_workspace_id"] == 2
    for k in (
        "active_page_id",
        "active_takeoff_row_id",
        "active_register_item_id",
        "_pb_nav_target",
        "_pb_nav_payload",
        "latest_ai_result",
        "latest_render_result",
        "takeoff_editor",
        "offline_results",
        "offline_takeoff",
        "offline_doc_name",
        "_pb_ack_workspace_id",
        "_pb_ack_fp",
        "_pb_ack_confirmed",
    ):
        assert k not in st.session_state
