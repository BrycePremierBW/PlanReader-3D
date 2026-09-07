"""tests/editable_3d/test_commercial_sync_export_integration.py — PR D.11I test suite.

D.11H's sync bridge deliberately writes nothing but an ordinary,
fully-compliant takeoff_rows row — no export/preflight code was touched,
because pb_commercial_export_preflight_v163._get_takeoff_row_stats() and
pb_takeoff_authority_v164's row-authority functions already scan every
takeoff_rows row unconditionally. This suite proves that claim against the
real, unmodified functions on a real (if minimal, isolated, in-memory)
SQLite table — not merely against an in-memory Python dict — so a future
change to either module's row-scanning SQL would be caught here rather
than only discovered by chance in the running app.
"""
from __future__ import annotations

import sqlite3

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import EditableObjectType, EditableGeometryObject
from pb_editable_3d_commercial_sync import build_model_surface_row_candidate
from pb_commercial_export_preflight_v163 import _get_takeoff_row_stats
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    is_jobhub_eligible_row,
    takeoff_row_publishability,
)
from pb_takeoff_output_authority import TakeoffOutputRow, TakeoffSourceType, create_takeoff_output_row

_TAKEOFF_ROWS_SCHEMA = """
CREATE TABLE takeoff_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    section TEXT,
    element TEXT,
    location TEXT,
    substrate TEXT,
    finish_system TEXT,
    quantity REAL DEFAULT 0,
    unit TEXT,
    quantity_status TEXT,
    source_page TEXT,
    source_reference TEXT,
    inclusion_status TEXT,
    coats REAL DEFAULT 2,
    coverage_m2_per_litre REAL DEFAULT 12,
    productivity_m2_per_hour REAL DEFAULT 8,
    rate_per_unit REAL DEFAULT 0,
    confidence TEXT,
    notes TEXT,
    row_role TEXT DEFAULT '',
    commercial_authority_status TEXT DEFAULT '',
    commercial_authority_source TEXT DEFAULT '',
    commercial_authority_reviewed_by TEXT DEFAULT '',
    commercial_authority_reviewed_at TEXT DEFAULT '',
    commercial_authority_fingerprint TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
"""

_INSERT_COLUMNS = (
    "workspace_id", "section", "element", "location", "substrate", "finish_system",
    "quantity", "unit", "quantity_status", "source_page", "source_reference",
    "inclusion_status", "coats", "coverage_m2_per_litre", "productivity_m2_per_hour",
    "rate_per_unit", "confidence", "notes", "row_role",
    "commercial_authority_status", "commercial_authority_source",
    "commercial_authority_reviewed_by", "commercial_authority_reviewed_at",
    "commercial_authority_fingerprint", "created_at", "updated_at",
)


def _isolated_takeoff_rows_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_TAKEOFF_ROWS_SCHEMA)
    return conn


def _insert_row(conn: sqlite3.Connection, row: dict) -> int:
    placeholders = ",".join("?" for _ in _INSERT_COLUMNS)
    cur = conn.execute(
        f"INSERT INTO takeoff_rows({','.join(_INSERT_COLUMNS)}) VALUES({placeholders})",
        tuple(row.get(c) for c in _INSERT_COLUMNS),
    )
    conn.commit()
    return cur.lastrowid


def _approved_object(**overrides) -> EditableGeometryObject:
    defaults = dict(
        object_id="MASS-1", object_type=EditableObjectType.WALL.value,
        source_page=3, source_sheet="WD-03", level_id="Ground",
        coordinates_or_measurements={"length": 8.0, "height": 2.7},
        authority_status=AuthorityStatus.FIRM.value,
        approved_by="Lead Estimator Bryce", approved_at="2026-09-08T00:00:00+00:00",
        revision_hash="REV-CURRENT",
    )
    defaults.update(overrides)
    return EditableGeometryObject(**defaults)


def _current_row(**overrides) -> TakeoffOutputRow:
    kwargs = dict(
        quantity_id="MASS-1-wall_gross_area-BASELINE-REV-CORR-1",
        description="Wall MASS-1 — Gross Area (corrected)",
        value=21.6, unit="m²", trade="general",
        source_type=TakeoffSourceType.USER_APPROVED.value,
        source_page=3, source_sheet="WD-03", geometry_ref="MASS-1",
        approved_by="Lead Estimator Bryce", approved_at="2026-09-08T00:00:00+00:00",
        revision_hash="REV-CURRENT", current_revision_hash="REV-CURRENT",
        allow_zero=False,
    )
    kwargs.update(overrides)
    return create_takeoff_output_row(**kwargs)


class TestSyncedRowIsCountedByTheRealExportPreflightRowScan:
    def test_a_synced_row_is_counted_as_publishable_by_get_takeoff_row_stats(self):
        # Exercises pb_commercial_export_preflight_v163._get_takeoff_row_stats()
        # verbatim — the exact function the Export/JobHub page's preflight
        # card calls — against a real (if isolated) SQLite takeoff_rows
        # table, proving no export-side change was needed for D.11H's
        # synced rows to be recognized.
        conn = _isolated_takeoff_rows_db()
        obj = _approved_object()
        row = _current_row()
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        approved = approve_model_surface_row(
            candidate, source=f"Editable 3D approval — revision {obj.revision_hash}",
            reviewed_by="Senior Estimator Jones", reviewed_at="2026-09-08T00:05:00+00:00",
        )
        approved["created_at"] = approved["updated_at"] = "2026-09-08T00:05:00+00:00"
        _insert_row(conn, approved)

        total, publishable, excluded, floor_ref, measured_zero, _fp = _get_takeoff_row_stats(conn, workspace_id=1)
        assert total == 1
        assert publishable == 1
        assert excluded == 0
        assert floor_ref == 0
        assert measured_zero == 0

    def test_an_unapproved_synced_candidate_is_never_counted_as_publishable(self):
        # A row_role='model_surface' candidate that was never run through
        # approve_model_surface_row() must never be counted — proving the
        # export pipeline itself, not just this bridge, enforces the gate.
        conn = _isolated_takeoff_rows_db()
        obj = _approved_object()
        row = _current_row()
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        candidate["created_at"] = candidate["updated_at"] = "2026-09-08T00:05:00+00:00"
        candidate.setdefault("commercial_authority_status", "")
        candidate.setdefault("commercial_authority_source", "")
        candidate.setdefault("commercial_authority_reviewed_by", "")
        candidate.setdefault("commercial_authority_reviewed_at", "")
        candidate.setdefault("commercial_authority_fingerprint", "")
        _insert_row(conn, candidate)

        total, publishable, *_rest = _get_takeoff_row_stats(conn, workspace_id=1)
        assert total == 1
        assert publishable == 0

    def test_a_tampered_synced_row_is_never_counted_as_publishable(self):
        # A row whose quantity was edited after approval (fingerprint no
        # longer matches) must drop out of the publishable count exactly
        # like tampering with any other model-surface row would.
        conn = _isolated_takeoff_rows_db()
        obj = _approved_object()
        row = _current_row()
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        approved = approve_model_surface_row(
            candidate, source="Editable 3D approval", reviewed_by="Bryce",
            reviewed_at="2026-09-08T00:05:00+00:00",
        )
        approved["created_at"] = approved["updated_at"] = "2026-09-08T00:05:00+00:00"
        approved["quantity"] = approved["quantity"] + 5.0  # tampered post-approval
        _insert_row(conn, approved)

        total, publishable, *_rest = _get_takeoff_row_stats(conn, workspace_id=1)
        assert total == 1
        assert publishable == 0

    def test_synced_row_read_back_from_sqlite_is_jobhub_eligible(self):
        # Reads the row back exactly as the app would (via SQLite, not the
        # in-memory dict this test built it from) and checks it against
        # the real, unmodified pb_takeoff_authority_v164 functions — this
        # is the specific check that caught the source_page TEXT-affinity
        # bug during manual verification; it stays here as a standing
        # regression guard now that the fix (stringifying source_page in
        # build_model_surface_row_candidate) is in place.
        conn = _isolated_takeoff_rows_db()
        obj = _approved_object(source_page=7)
        row = _current_row(source_page=7)
        candidate = build_model_surface_row_candidate(workspace_id=1, obj=obj, row=row)
        approved = approve_model_surface_row(
            candidate, source="Editable 3D approval", reviewed_by="Bryce",
            reviewed_at="2026-09-08T00:05:00+00:00",
        )
        approved["created_at"] = approved["updated_at"] = "2026-09-08T00:05:00+00:00"
        new_id = _insert_row(conn, approved)

        persisted = dict(conn.execute("SELECT * FROM takeoff_rows WHERE id=?", (new_id,)).fetchone())
        publishable, reason = takeoff_row_publishability(persisted)
        assert publishable, reason
        eligible, reason = is_jobhub_eligible_row(persisted)
        assert eligible, reason
