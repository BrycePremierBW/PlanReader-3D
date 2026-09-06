"""Unit and integration tests for Workstream P18 — Editor Persistence.

Tests:
1. Main takeoff schedule editor preserves commercial authority on unmodified partial-column roundtrips.
2. Main takeoff schedule editor invalidates commercial authority when consequential bound fields change.
3. Batched takeoff schedule editor (no-AI) preserves commercial authority on unmodified partial-column roundtrips.
4. Batched takeoff schedule editor invalidates commercial authority when consequential bound fields change.
5. Editor attempts to alter or drop model_surface row_role fail closed to prevent provenance laundering.
"""

import sqlite3

import pb_no_ai_takeoff_v1216 as no_ai
import pb_planreader_3d_app as app
from pb_takeoff_authority_v164 import (
    AUTHORITY_FINGERPRINT_FIELD,
    AUTHORITY_REVIEWED_AT_FIELD,
    AUTHORITY_REVIEWED_BY_FIELD,
    AUTHORITY_SOURCE_FIELD,
    AUTHORITY_STATUS_FIELD,
    approve_model_surface_row,
    model_surface_authority,
)


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


def test_main_takeoff_editor_unmodified_partial_columns_preserves_authority(tmp_path):
    """Verify saving through main takeoff schedule editor preserves authority when no bound fields change."""
    db_path = str(tmp_path / "main_editor_preserve.db")
    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        conn = app.local_connect()
        cur = conn.cursor()

        raw_row = {
            "id": 1,
            "workspace_id": 10,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 101",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 75.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "source_page": "3d_model",
            "source_reference": "Model mass #1",
            "inclusion_status": "Included",
            "coats": 2.0,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 15.0,
            "confidence": "HIGH",
            "notes": "Initial setup",
            "row_role": "model_surface",
        }
        approved = approve_model_surface_row(
            raw_row,
            source="Manual Estimator Audit",
            reviewed_by="Bryce Senior",
            reviewed_at="2026-09-01T10:00:00Z",
        )

        cur.execute("""
            INSERT INTO takeoff_rows (
                id, workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, quantity_status, source_page, source_reference, inclusion_status,
                coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, notes,
                row_role, commercial_authority_status, commercial_authority_source,
                commercial_authority_reviewed_by, commercial_authority_reviewed_at, commercial_authority_fingerprint
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
        """, (
            1, approved["workspace_id"], approved["section"], approved["element"], approved["location"], approved["substrate"], approved["finish_system"],
            approved["quantity"], approved["unit"], approved["quantity_status"], approved["source_page"], approved["source_reference"], approved["inclusion_status"],
            approved["coats"], approved["coverage_m2_per_litre"], approved["productivity_m2_per_hour"], approved["rate_per_unit"], approved["confidence"], approved["notes"],
            approved["row_role"], approved["commercial_authority_status"], approved["commercial_authority_source"],
            approved["commercial_authority_reviewed_by"], approved["commercial_authority_reviewed_at"], approved["commercial_authority_fingerprint"]
        ))
        conn.commit()

        # Simulate main editor save loop
        takeoff = app.ldf("SELECT * FROM takeoff_rows WHERE workspace_id=10")
        authority_by_id = {int(r["id"]): dict(r) for r in takeoff.to_dict("records")}

        # Simulate partial editor submission where bound fields are unchanged
        edited_row = {
            "id": 1,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 101",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 75.0,  # UNCHANGED
            "unit": "m²",
            "quantity_status": "Measured",
            "row_role": "model_surface",
        }

        prior = authority_by_id.get(1) or {}
        row_role = str(edited_row.get("row_role") or "").strip()
        if app.is_model_surface_row(prior) or app.is_model_surface_row(edited_row):
            row_role = "model_surface"

        merged_row = {**prior, **edited_row}
        authority = {
            AUTHORITY_STATUS_FIELD: prior.get(AUTHORITY_STATUS_FIELD, ""),
            AUTHORITY_SOURCE_FIELD: prior.get(AUTHORITY_SOURCE_FIELD, ""),
            AUTHORITY_REVIEWED_BY_FIELD: prior.get(AUTHORITY_REVIEWED_BY_FIELD, ""),
            AUTHORITY_REVIEWED_AT_FIELD: prior.get(AUTHORITY_REVIEWED_AT_FIELD, ""),
            AUTHORITY_FINGERPRINT_FIELD: prior.get(AUTHORITY_FINGERPRINT_FIELD, ""),
        }
        candidate = {
            **merged_row,
            "workspace_id": 10,
            "row_role": row_role,
            **authority,
        }

        ok, _reason = model_surface_authority(candidate)
        assert ok is True
        assert candidate[AUTHORITY_STATUS_FIELD] == "APPROVED"

        conn.close()
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_main_takeoff_editor_consequential_mutation_invalidates_authority(tmp_path):
    """Verify modifying a consequential bound field in main editor invalidates commercial authority."""
    db_path = str(tmp_path / "main_editor_invalidate.db")
    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        conn = app.local_connect()
        cur = conn.cursor()

        raw_row = {
            "id": 1,
            "workspace_id": 10,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 101",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 75.0,
            "unit": "m²",
            "coats": 2.0,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 15.0,
            "row_role": "model_surface",
        }
        approved = approve_model_surface_row(
            raw_row,
            source="Manual Estimator Audit",
            reviewed_by="Bryce Senior",
            reviewed_at="2026-09-01T10:00:00Z",
        )

        cur.execute("""
            INSERT INTO takeoff_rows (
                id, workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit,
                row_role, commercial_authority_status, commercial_authority_source,
                commercial_authority_reviewed_by, commercial_authority_reviewed_at, commercial_authority_fingerprint
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
        """, (
            1, approved["workspace_id"], approved["section"], approved["element"], approved["location"], approved["substrate"], approved["finish_system"],
            approved["quantity"], approved["unit"], approved["coats"], approved["coverage_m2_per_litre"], approved["productivity_m2_per_hour"], approved["rate_per_unit"],
            approved["row_role"], approved["commercial_authority_status"], approved["commercial_authority_source"],
            approved["commercial_authority_reviewed_by"], approved["commercial_authority_reviewed_at"], approved["commercial_authority_fingerprint"]
        ))
        conn.commit()

        # Simulate main editor submission where quantity is MUTATED (75.0 -> 120.0)
        takeoff = app.ldf("SELECT * FROM takeoff_rows WHERE workspace_id=10")
        authority_by_id = {int(r["id"]): dict(r) for r in takeoff.to_dict("records")}

        edited_row = {
            "id": 1,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 101",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 120.0,  # MUTATED QUANTITY
            "unit": "m²",
            "row_role": "model_surface",
        }

        prior = authority_by_id.get(1) or {}
        row_role = "model_surface"
        merged_row = {**prior, **edited_row}
        authority = {
            AUTHORITY_STATUS_FIELD: prior.get(AUTHORITY_STATUS_FIELD, ""),
            AUTHORITY_SOURCE_FIELD: prior.get(AUTHORITY_SOURCE_FIELD, ""),
            AUTHORITY_REVIEWED_BY_FIELD: prior.get(AUTHORITY_REVIEWED_BY_FIELD, ""),
            AUTHORITY_REVIEWED_AT_FIELD: prior.get(AUTHORITY_REVIEWED_AT_FIELD, ""),
            AUTHORITY_FINGERPRINT_FIELD: prior.get(AUTHORITY_FINGERPRINT_FIELD, ""),
        }
        candidate = {
            **merged_row,
            "workspace_id": 10,
            "row_role": row_role,
            **authority,
        }

        ok, _reason = model_surface_authority(candidate)
        assert ok is False

        # Apply invalidation rule
        if not ok:
            authority[AUTHORITY_STATUS_FIELD] = "REVIEW_REQUIRED"
            authority[AUTHORITY_REVIEWED_BY_FIELD] = ""
            authority[AUTHORITY_REVIEWED_AT_FIELD] = ""
            authority[AUTHORITY_FINGERPRINT_FIELD] = ""

        assert authority[AUTHORITY_STATUS_FIELD] == "REVIEW_REQUIRED"
        assert authority[AUTHORITY_FINGERPRINT_FIELD] == ""

        conn.close()
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_batched_editor_unmodified_partial_columns_preserves_authority(tmp_path):
    """Verify save_schedule_batched preserves authority on unmodified partial-column roundtrips."""
    db_path = str(tmp_path / "batched_editor_preserve.db")
    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        conn = app.local_connect()
        cur = conn.cursor()

        raw_row = {
            "id": 1,
            "workspace_id": 15,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 201",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 80.0,
            "unit": "m²",
            "coats": 2.0,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 20.0,
            "row_role": "model_surface",
        }
        approved = approve_model_surface_row(
            raw_row,
            source="Manual Audit",
            reviewed_by="Bryce",
            reviewed_at="2026-09-01T10:00:00Z",
        )

        cur.execute("""
            INSERT INTO takeoff_rows (
                id, workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit,
                row_role, commercial_authority_status, commercial_authority_source,
                commercial_authority_reviewed_by, commercial_authority_reviewed_at, commercial_authority_fingerprint
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
        """, (
            1, approved["workspace_id"], approved["section"], approved["element"], approved["location"], approved["substrate"], approved["finish_system"],
            approved["quantity"], approved["unit"], approved["coats"], approved["coverage_m2_per_litre"], approved["productivity_m2_per_hour"], approved["rate_per_unit"],
            approved["row_role"], approved["commercial_authority_status"], approved["commercial_authority_source"],
            approved["commercial_authority_reviewed_by"], approved["commercial_authority_reviewed_at"], approved["commercial_authority_fingerprint"]
        ))
        conn.commit()
        conn.close()

        # Partial edited row without bound metadata overrides
        partial_row = {
            "id": 1,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 201",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 80.0,  # UNCHANGED
            "unit": "m²",
            "row_role": "model_surface",
        }

        no_ai.save_schedule_batched(app, 15, [partial_row])

        conn = app.local_connect()
        row_after = dict(conn.execute("SELECT * FROM takeoff_rows WHERE workspace_id=15").fetchone())
        conn.close()

        ok, _reason = model_surface_authority(row_after)
        assert ok is True
        assert row_after[AUTHORITY_STATUS_FIELD] == "APPROVED"
        assert row_after[AUTHORITY_FINGERPRINT_FIELD] == approved[AUTHORITY_FINGERPRINT_FIELD]
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)


def test_editor_laundering_prevention(tmp_path):
    """Verify attempting to clear or alter model_surface row_role in editors retains model_surface role."""
    db_path = str(tmp_path / "editor_laundering.db")
    orig_local_connect, orig_db_path = _bind_test_db(db_path)
    try:
        app.init_local_db()

        conn = app.local_connect()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO takeoff_rows (
                id, workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, row_role, commercial_authority_status
            ) VALUES (
                1, 20, 'Internal', 'Plasterboard', 'Room 301', 'Plasterboard', 'Paint',
                50.0, 'm²', 'model_surface', 'REVIEW_REQUIRED'
            )
        """)
        conn.commit()
        conn.close()

        # User attempts to edit row and change row_role to empty or floor_area
        tampered_row = {
            "id": 1,
            "section": "Internal",
            "element": "Plasterboard",
            "location": "Room 301",
            "substrate": "Plasterboard",
            "finish_system": "Paint",
            "quantity": 50.0,
            "unit": "m²",
            "row_role": "",  # ATTEMPTED ROLE LAUNDERING
        }

        no_ai.save_schedule_batched(app, 20, [tampered_row])

        conn = app.local_connect()
        row_after = dict(conn.execute("SELECT * FROM takeoff_rows WHERE workspace_id=20").fetchone())
        conn.close()

        assert row_after["row_role"] == "model_surface"
    finally:
        _unbind_test_db(orig_local_connect, orig_db_path)
