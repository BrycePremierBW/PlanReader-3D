"""Regression coverage for AI/render-derived commercial authority.

AI plan reading consumes rasterised drawing pages. Its output is a useful draft,
but a model-supplied confidence label must never let that draft enter pricing,
quotation, progress, or JobHub publication before explicit estimator review.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pb_no_ai_takeoff_v1216 as no_ai
import pb_takeoff_accuracy_v125 as accuracy
from pb_takeoff_authority_v164 import (
    is_jobhub_eligible_row,
    is_commercial_floor_reference_row,
    is_progress_eligible_row,
    takeoff_row_publishability,
)


def _ai_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "workspace_id": 7,
        "section": "External",
        "element": "External walls",
        "location": "Ground",
        "substrate": "Render",
        "finish_system": "Exterior acrylic",
        "quantity": 80.0,
        "unit": "m²",
        "quantity_status": "Provisional measured",
        "source_page": "Render R01",
        "source_reference": "Render R01 visual interpretation",
        "inclusion_status": "INCLUSION",
        "coats": 2.0,
        "coverage_m2_per_litre": 12.0,
        "productivity_m2_per_hour": 8.0,
        "rate_per_unit": 25.0,
        "confidence": "Verified",
        "notes": "AI draft — verify against the issued drawing.",
        "row_role": "",
        "origin": "AI",
        "ai_baseline_quantity": 80.0,
    }
    row.update(overrides)
    return row


def test_model_claimed_verified_ai_row_is_not_publishable() -> None:
    allowed, reason = takeoff_row_publishability(_ai_row())

    assert allowed is False
    assert "AI" in reason
    assert is_progress_eligible_row(_ai_row())[0] is False
    assert is_jobhub_eligible_row(_ai_row())[0] is False


def test_ai_floor_reference_cannot_drive_pricing_before_estimator_review() -> None:
    row = _ai_row(
        section="Internal",
        element="Floor area",
        row_role="floor_area",
        rate_per_unit=0.0,
    )

    assert is_commercial_floor_reference_row(row) is False


def test_legacy_ai_draft_marker_remains_fail_closed_if_origin_is_missing() -> None:
    row = _ai_row(origin="", ai_baseline_quantity=None)

    allowed, reason = takeoff_row_publishability(row)

    assert allowed is False
    assert "AI" in reason


def test_ai_origin_cannot_self_authorize_trusted_looking_fields() -> None:
    row = _ai_row(quantity_status="Measured", confidence="Verified")

    allowed, reason = takeoff_row_publishability(row)

    assert allowed is False
    assert "reviewed" in reason


def test_explicit_estimator_confirmation_releases_ai_row() -> None:
    row = _ai_row(
        origin="AI_REVIEWED",
        quantity_status="Measured",
        confidence="Estimator verified",
    )

    assert takeoff_row_publishability(row) == (True, "PUBLISHABLE")


class _SqliteApp:
    UNIT_OPTIONS = ["m²", "lm", "No.", "L", "allowance"]

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def local_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def lquery(self, sql: str, params=()) -> list[dict[str, Any]]:
        conn = self.local_connect()
        try:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
        finally:
            conn.close()

    def ldf(self, sql: str, params=()):
        return accuracy.pd.DataFrame(self.lquery(sql, params))

    def lexecute(self, sql: str, params=()) -> int:
        conn = self.local_connect()
        try:
            cursor = conn.execute(sql, tuple(params))
            conn.commit()
            return int(cursor.lastrowid or 0)
        finally:
            conn.close()

    @staticmethod
    def to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def now_stamp() -> str:
        return "2026-09-06T00:00:00"

    @staticmethod
    def _normalise_unit(value: Any) -> str:
        return {"m2": "m²", "sqm": "m²", "m": "lm"}.get(
            str(value or "").strip().lower(), str(value or "").strip()
        )

    @staticmethod
    def scale_gate_issues(_workspace_id: int) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def workspace_setting(_workspace_id: int, _key: str, default: Any) -> Any:
        return default

    @staticmethod
    def is_internal_wall_row(section: Any, element: Any) -> bool:
        return "internal" in str(section or "").lower() and "wall" in str(element or "").lower()

    @staticmethod
    def is_commercial_floor_reference_row(row: dict[str, Any]) -> bool:
        return is_commercial_floor_reference_row(row)


def _create_takeoff_table(app: _SqliteApp) -> None:
    conn = app.local_connect()
    try:
        conn.execute(
            """CREATE TABLE takeoff_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                section TEXT, element TEXT, location TEXT, substrate TEXT,
                finish_system TEXT, quantity REAL, unit TEXT,
                quantity_status TEXT, source_page TEXT, source_reference TEXT,
                inclusion_status TEXT, coats REAL, coverage_m2_per_litre REAL,
                productivity_m2_per_hour REAL, rate_per_unit REAL,
                confidence TEXT, notes TEXT, row_role TEXT DEFAULT '',
                commercial_authority_status TEXT DEFAULT '',
                commercial_authority_source TEXT DEFAULT '',
                commercial_authority_reviewed_by TEXT DEFAULT '',
                commercial_authority_reviewed_at TEXT DEFAULT '',
                commercial_authority_fingerprint TEXT DEFAULT '',
                ai_baseline_quantity REAL, pre_map_quantity REAL,
                pre_map_quantity_status TEXT, origin TEXT DEFAULT '',
                created_at TEXT, updated_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER, page_label TEXT, px_per_m REAL,
                selected INTEGER DEFAULT 1
            )"""
        )
        conn.execute(
            """CREATE TABLE measurement_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER, page_id INTEGER, takeoff_row_id INTEGER
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def test_ai_import_cannot_self_assert_verified_confidence(tmp_path: Path) -> None:
    app = _SqliteApp(tmp_path / "ai_import.db")
    _create_takeoff_table(app)

    def base_import(workspace_id: int, data: dict[str, Any]) -> dict[str, int]:
        for source in data["takeoff_rows"]:
            app.lexecute(
                """INSERT INTO takeoff_rows(
                    workspace_id,section,element,quantity,unit,quantity_status,
                    inclusion_status,rate_per_unit,confidence,notes,row_role
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    workspace_id,
                    source["section"],
                    source["element"],
                    source["quantity"],
                    source["unit"],
                    source["quantity_status"],
                    source["inclusion_status"],
                    source["rate_per_unit"],
                    source["confidence"],
                    source["notes"],
                    "",  # Production v1.1 importer historically dropped row_role.
                ),
            )
        return {"takeoff": len(data["takeoff_rows"]), "registers": 0, "masses": 0, "openings": 0}

    wrapped_import = accuracy.import_ai(app, base_import)
    wrapped_import(7, {"takeoff_rows": [
        _ai_row(quantity_status="Measured"),
        _ai_row(
            section="Internal",
            element="Floor area",
            row_role="floor_area",
            quantity_status="Measured",
        ),
    ]})
    stored, floor = app.lquery("SELECT * FROM takeoff_rows WHERE workspace_id=7 ORDER BY id")

    assert stored["origin"] == "AI"
    assert stored["quantity_status"] == "Provisional measured"
    assert stored["confidence"] == "To review"
    assert takeoff_row_publishability(stored)[0] is False
    assert floor["row_role"] == "floor_area"
    assert is_commercial_floor_reference_row(floor) is False


def test_accuracy_audit_flags_legacy_model_claimed_confidence(tmp_path: Path) -> None:
    app = _SqliteApp(tmp_path / "legacy_ai_audit.db")
    _create_takeoff_table(app)
    source = _ai_row(quantity_status="Measured", confidence="Verified")
    app.lexecute(
        """INSERT INTO takeoff_rows(
            workspace_id,section,element,location,substrate,finish_system,
            quantity,unit,quantity_status,source_page,source_reference,
            inclusion_status,coats,coverage_m2_per_litre,
            productivity_m2_per_hour,rate_per_unit,confidence,notes,row_role,
            ai_baseline_quantity,origin,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            source["workspace_id"], source["section"], source["element"],
            source["location"], source["substrate"], source["finish_system"],
            source["quantity"], source["unit"], source["quantity_status"],
            source["source_page"], source["source_reference"],
            source["inclusion_status"], source["coats"],
            source["coverage_m2_per_litre"], source["productivity_m2_per_hour"],
            source["rate_per_unit"], source["confidence"], source["notes"],
            source["row_role"], source["ai_baseline_quantity"], source["origin"],
            app.now_stamp(), app.now_stamp(),
        ),
    )

    found = accuracy.issues(app, 7)

    assert any(item["code"] == "AI_UNVERIFIED" for item in found)


def test_batched_editor_preserves_ai_provenance(tmp_path: Path) -> None:
    app = _SqliteApp(tmp_path / "ai_editor.db")
    _create_takeoff_table(app)
    source = _ai_row(confidence="To review")
    row_id = app.lexecute(
        """INSERT INTO takeoff_rows(
            workspace_id,section,element,location,substrate,finish_system,
            quantity,unit,quantity_status,source_page,source_reference,
            inclusion_status,coats,coverage_m2_per_litre,
            productivity_m2_per_hour,rate_per_unit,confidence,notes,row_role,
            ai_baseline_quantity,origin,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            source["workspace_id"], source["section"], source["element"],
            source["location"], source["substrate"], source["finish_system"],
            source["quantity"], source["unit"], source["quantity_status"],
            source["source_page"], source["source_reference"],
            source["inclusion_status"], source["coats"],
            source["coverage_m2_per_litre"], source["productivity_m2_per_hour"],
            source["rate_per_unit"], source["confidence"], source["notes"],
            source["row_role"], source["ai_baseline_quantity"], source["origin"],
            app.now_stamp(), app.now_stamp(),
        ),
    )
    edited = app.lquery("SELECT * FROM takeoff_rows WHERE id=?", (row_id,))[0]

    no_ai.save_schedule_batched(app, 7, [edited])
    stored = app.lquery("SELECT * FROM takeoff_rows WHERE workspace_id=7")[0]

    assert stored["origin"] == "AI"
    assert stored["ai_baseline_quantity"] == 80.0

    stored["quantity_status"] = "Measured"
    stored["confidence"] = "Estimator verified"
    no_ai.save_schedule_batched(app, 7, [stored])
    reviewed = app.lquery("SELECT * FROM takeoff_rows WHERE workspace_id=7")[0]

    assert reviewed["origin"] == "AI_REVIEWED"
    assert takeoff_row_publishability(reviewed) == (True, "PUBLISHABLE")
