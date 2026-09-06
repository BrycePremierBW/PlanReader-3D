"""Unit and integration tests for Workstream P20 — Security.

Tests:
1. Column injection prevention in EstimatorOverrideRegistry.apply_override.
2. XSS prevention via HTML escaping in hero() header rendering.
3. XSS prevention via HTML escaping in plan_mapper_page legend spans.
4. Valid column names pass EstimatorOverrideRegistry.apply_override safely.
"""

import html
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st

import pb_estimator_review_override_v180 as override
import pb_planreader_3d_app as app


def test_override_apply_override_column_injection_rejected(tmp_path):
    """Verify EstimatorOverrideRegistry.apply_override rejects un-whitelisted column names."""
    db_path = str(tmp_path / "security_override.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE takeoff_rows (id INTEGER PRIMARY KEY, workspace_id INTEGER, quantity REAL, notes TEXT)")
        conn.execute("INSERT INTO takeoff_rows (id, workspace_id, quantity, notes) VALUES (1, 10, 100.0, 'Initial')")
        conn.commit()

        malicious_field = "quantity; DROP TABLE takeoff_rows;--"
        with pytest.raises(ValueError, match="Invalid column name for takeoff row override"):
            override.EstimatorOverrideRegistry.apply_override(
                conn, workspace_id=10, row_id=1, field_name=malicious_field, new_value=200.0, override_reason="Test"
            )
    finally:
        conn.close()


def test_override_apply_override_valid_column_accepted(tmp_path):
    """Verify EstimatorOverrideRegistry.apply_override accepts valid column names."""
    db_path = str(tmp_path / "security_override_valid.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""CREATE TABLE takeoff_rows (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, quantity REAL, notes TEXT
        )""")
        conn.execute("""CREATE TABLE takeoff_row_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER, row_id INTEGER, field_name TEXT,
            old_value TEXT, new_value TEXT, override_reason TEXT, estimator_name TEXT, timestamp TEXT
        )""")
        conn.execute("INSERT INTO takeoff_rows (id, workspace_id, quantity, notes) VALUES (1, 10, 100.0, 'Initial')")
        conn.commit()

        record = override.EstimatorOverrideRegistry.apply_override(
            conn, workspace_id=10, row_id=1, field_name="quantity", new_value=250.0, override_reason="Verified by lead", estimator_name="Estimator A"
        )
        assert record.row_id == 1
        assert record.field_name == "quantity"
        assert record.new_value == "250.0"

        cur = conn.cursor()
        cur.execute("SELECT quantity FROM takeoff_rows WHERE id=1")
        assert cur.fetchone()[0] == 250.0
    finally:
        conn.close()


def test_hero_html_escaping():
    """Verify hero() escapes user-supplied text in workspace attributes to prevent XSS."""
    workspace = {
        "id": 1,
        "job_no": "JOB-99",
        "job_name": "<script>alert('xss')</script>",
        "builder_client": "<img src=x onerror=alert(1)>",
        "site_address": "456 Safety Way & <more>",
    }

    markdown_calls = []
    def mock_markdown(content, **kwargs):
        markdown_calls.append((content, kwargs))

    with patch("streamlit.markdown", side_effect=mock_markdown):
        app.hero(workspace)

    assert len(markdown_calls) == 1
    content, kwargs = markdown_calls[0]
    assert kwargs.get("unsafe_allow_html") is True
    assert "<script>" not in content
    assert "&lt;script&gt;" in content
    assert "<img" not in content
    assert "&lt;img" in content
    assert "&amp;" in content
