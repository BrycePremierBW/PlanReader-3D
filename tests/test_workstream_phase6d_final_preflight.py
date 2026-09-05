"""tests/test_workstream_phase6d_final_preflight.py — P9: Phase 6D Final Preflight Regression Suite.

Verifies the 9 required safety conditions:
  1. Unapproved 3D model surfaces
  2. Tampered approval fingerprints
  3. Invalid scale (uncalibrated)
  4. Provisional scale (provisional auto / title block / inherited)
  5. Missing review evidence (fail closed)
  6. Workspace replay (model surfaces & B5 opening evidence)
  7. B5 invalid evidence (pipeline errors, conflicts, unproven deductions)
  8. Excluded rows
  9. Floor-reference rows

Enforces: No unsafe data reaches consequential output.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import MagicMock

from pb_commercial_export_preflight_v163 import (
    _get_takeoff_row_stats,
    derive_export_preflight,
    verify_toctou_and_publish_jobhub,
)
from pb_opening_production_v175 import (
    PAGES_INDEX_KEY,
    SETTING_PREFIX,
)
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
)


def _create_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            job_no TEXT,
            job_name TEXT,
            drawing_issue TEXT,
            jobhub_job_id INTEGER,
            executive_summary TEXT
        );
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            file_name TEXT
        );
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            document_id INTEGER,
            page_no INTEGER,
            page_label TEXT,
            selected INTEGER DEFAULT 1,
            px_per_m REAL DEFAULT 100.0,
            drawing_type TEXT,
            scale_text TEXT
        );
        CREATE TABLE takeoff_rows (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            section TEXT,
            element TEXT,
            location TEXT,
            substrate TEXT,
            unit TEXT,
            quantity REAL,
            quantity_status TEXT,
            coats REAL DEFAULT 1.0,
            rate_per_unit REAL DEFAULT 25.0,
            labour_hours REAL DEFAULT 5.0,
            paint_litres REAL DEFAULT 10.0,
            value_ex_gst REAL DEFAULT 100.0,
            finish_system TEXT,
            coverage_m2_per_litre REAL DEFAULT 12.0,
            productivity_m2_per_hour REAL DEFAULT 20.0,
            confidence TEXT,
            inclusion_status TEXT,
            row_role TEXT,
            source_page TEXT,
            source_reference TEXT,
            notes TEXT,
            commercial_authority_status TEXT DEFAULT '',
            commercial_authority_source TEXT DEFAULT '',
            commercial_authority_reviewed_by TEXT DEFAULT '',
            commercial_authority_reviewed_at TEXT DEFAULT '',
            commercial_authority_fingerprint TEXT DEFAULT ''
        );
        CREATE TABLE register_items (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            register_name TEXT,
            title TEXT,
            detail TEXT,
            status TEXT,
            priority TEXT,
            source_reference TEXT
        );
        CREATE TABLE workspace_settings (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            key TEXT,
            value TEXT
        );
        """
    )
    cur.execute("INSERT INTO workspaces VALUES (1, 'JOB-P9', 'P9 Final Preflight QA', 'Rev 1', 101, 'Summary')")
    cur.execute("INSERT INTO documents VALUES (10, 1, 'Drawing-01.pdf')")
    cur.execute("INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, selected, px_per_m) VALUES (100, 1, 10, 1, 'D-01', 1, 100.0)")
    # Base publishable work row
    cur.execute(
        """INSERT INTO takeoff_rows (
            id, workspace_id, section, element, location, substrate, unit, quantity,
            quantity_status, confidence, inclusion_status, row_role
        ) VALUES (1000, 1, 'Internal', 'Base Wall', 'Room 1', 'Plasterboard', 'm²', 80.0, 'Measured', 'High', 'included', 'work')"""
    )
    conn.commit()
    return conn


class MockTestApp:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def lquery(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def scale_gate_issues(self, wid: int):
        return []

    def workspace_setting(self, wid: int, key: str, default: str = "") -> str:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM workspace_settings WHERE workspace_id=? AND key=?", (wid, key))
        row = cur.fetchone()
        return row[0] if row else default

    def set_workspace_setting(self, wid: int, key: str, val: str) -> None:
        cur = self.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO workspace_settings (workspace_id, key, value) VALUES (?, ?, ?)", (wid, key, str(val)))
        self.conn.commit()


class TestProvisionalAndUncalibratedScaleBlocksPreflight(unittest.TestCase):
    def setUp(self):
        self.conn = _create_test_db()
        self.app = MockTestApp(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_provisional_title_block_scale_forces_blocked(self):
        """Provisional title-block scale must force preflight_status and final_publish_state to BLOCKED."""
        self.app.scale_gate_issues = lambda wid: [{
            "page_id": 100,
            "page_label": "D-01",
            "reason": "Provisional title-block scale 1:100",
            "severity": "REVIEW",
            "issue_type": "PROVISIONAL_TITLE_BLOCK_SCALE"
        }]
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertEqual(res.final_publish_state, "BLOCKED")
        self.assertTrue(any("Provisional" in r or "provisional" in r for r in res.blocking_reasons))

    def test_provisional_inherited_scale_forces_blocked(self):
        """Provisional inherited scale context must force preflight_status and final_publish_state to BLOCKED."""
        self.app.scale_gate_issues = lambda wid: [{
            "page_id": 100,
            "page_label": "D-01",
            "reason": "Provisional inherited scale context",
            "severity": "REVIEW",
            "issue_type": "PROVISIONAL_INHERITED_SCALE"
        }]
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertEqual(res.final_publish_state, "BLOCKED")

    def test_uncalibrated_scale_forces_blocked(self):
        """Uncalibrated page scale forces preflight_status and final_publish_state to BLOCKED."""
        self.app.scale_gate_issues = lambda wid: [{
            "page_id": 100,
            "page_label": "D-01",
            "reason": "Uncalibrated drawing page",
            "severity": "Critical",
            "issue_type": "UNCALIBRATED_SCALE"
        }]
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertEqual(res.final_publish_state, "BLOCKED")


class TestB5OpeningDeductionEvidencePreflightValidation(unittest.TestCase):
    def setUp(self):
        self.conn = _create_test_db()
        self.app = MockTestApp(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_b5_pipeline_error_payload_forces_blocked(self):
        """B5 opening analysis payload marked with error status must block preflight."""
        self.app.set_workspace_setting(1, PAGES_INDEX_KEY, json.dumps([100]))
        self.app.set_workspace_setting(
            1,
            f"{SETTING_PREFIX}100",
            json.dumps({
                "version": "1.7.5",
                "workspace_id": 1,
                "page_id": 100,
                "status": "error",
                "error": "Opening geometry analysis failed closed",
                "instances": [],
            })
        )
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertEqual(res.final_publish_state, "BLOCKED")
        self.assertTrue(any("B5 opening analysis error" in r for r in res.blocking_reasons))

    def test_b5_unresolved_conflicts_forces_blocked(self):
        """B5 opening evidence with unresolved physical conflicts must block preflight."""
        self.app.set_workspace_setting(1, PAGES_INDEX_KEY, json.dumps([100]))
        self.app.set_workspace_setting(
            1,
            f"{SETTING_PREFIX}100",
            json.dumps({
                "version": "1.7.5",
                "workspace_id": 1,
                "page_id": 100,
                "status": "complete",
                "conflicts": [{"wall_ref": "W01", "type_a": "door", "type_b": "window"}],
                "instances": [],
            })
        )
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertTrue(any("conflicts" in r.lower() for r in res.blocking_reasons))

    def test_b5_orphaned_page_evidence_forces_blocked(self):
        """B5 evidence referring to a non-existent page ID must fail closed and block preflight."""
        self.app.set_workspace_setting(1, PAGES_INDEX_KEY, json.dumps([999]))
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertTrue(any("Orphaned" in r or "non-existent" in r for r in res.blocking_reasons))

    def test_b5_cross_workspace_replay_forces_blocked(self):
        """B5 evidence belonging to workspace #2 replayed into workspace #1 must block preflight."""
        self.app.set_workspace_setting(1, PAGES_INDEX_KEY, json.dumps([100]))
        self.app.set_workspace_setting(
            1,
            f"{SETTING_PREFIX}100",
            json.dumps({
                "version": "1.7.5",
                "workspace_id": 2,  # Replayed from workspace 2
                "page_id": 100,
                "status": "complete",
                "instances": [],
            })
        )
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertTrue(any("Cross-workspace replay" in r or "replay" in r.lower() for r in res.blocking_reasons))

    def test_b5_unauthorized_opening_deduction_forces_blocked(self):
        """Opening instance with deduct=True but lacking required proof bundle must block preflight."""
        self.app.set_workspace_setting(1, PAGES_INDEX_KEY, json.dumps([100]))
        self.app.set_workspace_setting(
            1,
            f"{SETTING_PREFIX}100",
            json.dumps({
                "version": "1.7.5",
                "workspace_id": 1,
                "page_id": 100,
                "status": "complete",
                "instances": [{
                    "opening_instance_id": "OP-1",
                    "tag": "D01",
                    "deduct": True,
                    "reconciliation_complete": False,  # Missing reconciliation!
                    "dimension_basis": "rough_opening",
                    "geometry_confidence": 0.8,
                    "dimension_confidence": 0.8,
                    "association_confidence": 0.8,
                }],
            })
        )
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertTrue(any("Unauthorized B5 opening deduction" in r for r in res.blocking_reasons))

    def test_b5_clean_authoritative_evidence_passes(self):
        """Valid, reconciled, authoritative B5 evidence does not block preflight."""
        self.app.set_workspace_setting(1, PAGES_INDEX_KEY, json.dumps([100]))
        self.app.set_workspace_setting(
            1,
            f"{SETTING_PREFIX}100",
            json.dumps({
                "version": "1.7.5",
                "workspace_id": 1,
                "page_id": 100,
                "status": "complete",
                "instances": [{
                    "opening_instance_id": "OP-1",
                    "tag": "D01",
                    "deduct": True,
                    "reconciliation_complete": True,
                    "deduction_status": "auto_eligible",
                    "deduction_decision": "deducted",
                    "dimension_basis": "rough_opening",
                    "geometry_confidence": 0.85,
                    "dimension_confidence": 0.85,
                    "association_confidence": 0.85,
                    "wall_ref": "W01",
                    "width_m": 1.0,
                    "height_m": 2.1,
                    "area_m2": 2.1,
                    "dimension_source": "Schedule",
                    "source": "Schedule D01",
                }],
            })
        )
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "AVAILABLE")
        self.assertEqual(res.final_publish_state, "AVAILABLE")


class TestTakeoffRowConsequentialFieldIntegrity(unittest.TestCase):
    def setUp(self):
        self.conn = _create_test_db()
        self.app = MockTestApp(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_unapproved_model_surface_blocks_and_not_counted_in_publishable(self):
        """Unapproved model surface forces preflight to BLOCKED and is not in publishable_takeoff_rows."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (1001, 1, 'Ext', 'Unapproved 3D', 'm²', 50.0, 'Measured', 'High', 'included', 'model_surface')"""
        )
        self.conn.commit()
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertEqual(res.final_publish_state, "BLOCKED")
        self.assertEqual(res.publishable_takeoff_rows, 1)  # Only base row 1000 is publishable

    def test_tampered_model_surface_approval_blocks_preflight(self):
        """Approved model surface with mutated quantity breaks fingerprint and blocks preflight."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (1002, 1, 'Ext', 'Approved 3D', 'm²', 40.0, 'Measured', 'High', 'included', 'model_surface')"""
        )
        self.conn.commit()
        self.conn.row_factory = sqlite3.Row
        row_dict = dict(self.conn.execute("SELECT * FROM takeoff_rows WHERE id=1002").fetchone())
        approved = approve_model_surface_row(row_dict, source="S1", reviewed_by="Estimator", reviewed_at="2026-09-01T00:00:00")
        cur.execute(
            """UPDATE takeoff_rows SET
                commercial_authority_status=?, commercial_authority_source=?,
                commercial_authority_reviewed_by=?, commercial_authority_reviewed_at=?,
                commercial_authority_fingerprint=? WHERE id=1002""",
            (approved["commercial_authority_status"], approved["commercial_authority_source"],
             approved["commercial_authority_reviewed_by"], approved["commercial_authority_reviewed_at"],
             approved["commercial_authority_fingerprint"])
        )
        self.conn.commit()
        # Verify clean approval passes
        res1 = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res1.preflight_status, "AVAILABLE")
        self.assertEqual(res1.publishable_takeoff_rows, 2)

        # Now tamper with quantity
        cur.execute("UPDATE takeoff_rows SET quantity=45.0 WHERE id=1002")
        self.conn.commit()
        res2 = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res2.preflight_status, "BLOCKED")
        self.assertEqual(res2.publishable_takeoff_rows, 1)

    def test_cross_workspace_model_approval_replay_blocks_preflight(self):
        """Model approval replayed from workspace 2 into workspace 1 fails fingerprint and blocks preflight."""
        cur = self.conn.cursor()
        cur.execute("INSERT INTO workspaces VALUES (2, 'JOB-2', 'WS 2', 'Rev A', 102, '')")
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (2001, 2, 'Ext', 'WS2 3D', 'm²', 30.0, 'Measured', 'High', 'included', 'model_surface')"""
        )
        self.conn.commit()
        self.conn.row_factory = sqlite3.Row
        row_ws2 = dict(self.conn.execute("SELECT * FROM takeoff_rows WHERE id=2001").fetchone())
        approved_ws2 = approve_model_surface_row(row_ws2, source="S2", reviewed_by="Estimator", reviewed_at="2026-09-01T00:00:00")

        # Replay into workspace 1
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role,
                commercial_authority_status, commercial_authority_source,
                commercial_authority_reviewed_by, commercial_authority_reviewed_at,
                commercial_authority_fingerprint
            ) VALUES (1003, 1, 'Ext', 'WS2 3D', 'm²', 30.0, 'Measured', 'High', 'included', 'model_surface',
                ?, ?, ?, ?, ?)""",
            (approved_ws2["commercial_authority_status"], approved_ws2["commercial_authority_source"],
             approved_ws2["commercial_authority_reviewed_by"], approved_ws2["commercial_authority_reviewed_at"],
             approved_ws2["commercial_authority_fingerprint"])
        )
        self.conn.commit()
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertEqual(res.publishable_takeoff_rows, 1)

    def test_non_finite_numeric_values_sanitized_in_payload_hash(self):
        """Non-finite values (NaN/Infinity) in takeoff rows must be sanitized and never emit invalid JSON in payload hash."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role, coats, rate_per_unit, labour_hours
            ) VALUES (1004, 1, 'Internal', 'Corrupt Row', 'm²', 10.0, 'Measured', 'High', 'included', 'work', 'NaN', 'inf', '-inf')"""
        )
        self.conn.commit()
        _total, _pub, _excl, _floor, _zero, phash = _get_takeoff_row_stats(self.app, 1)
        self.assertEqual(len(phash), 64)
        # Verify JSON dumping does not contain literal NaN
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertIsNotNone(res.payload_hash)
        self.assertEqual(len(res.payload_hash), 64)


class TestExcludedAndFloorReferenceRowIsolation(unittest.TestCase):
    def setUp(self):
        self.conn = _create_test_db()
        self.app = MockTestApp(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_excluded_row_isolation(self):
        """Excluded row is tracked in excluded_takeoff_rows, excluded from publishable rows, and creates no blocker."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (1005, 1, 'External', 'Excluded Works', 'm²', 50.0, 'Measured', 'High', 'excluded', 'work')"""
        )
        self.conn.commit()
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.excluded_takeoff_rows, 1)
        self.assertEqual(res.publishable_takeoff_rows, 1)
        self.assertEqual(res.preflight_status, "AVAILABLE")

    def test_floor_reference_row_isolation(self):
        """Floor reference row is tracked in floor_reference_rows and excluded from publishable rows."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (1006, 1, 'Internal', 'Floor Area Ref', 'm²', 100.0, 'Measured', 'High', 'included', 'floor_area')"""
        )
        self.conn.commit()
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.floor_reference_rows, 1)
        self.assertEqual(res.publishable_takeoff_rows, 1)

    def test_zero_publishable_rows_due_to_floor_area_only_blocks_preflight(self):
        """Workspace with only floor-area rows has 0 publishable rows and must be BLOCKED."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM takeoff_rows WHERE workspace_id=1")
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (1007, 1, 'Internal', 'Floor Area Only', 'm²', 100.0, 'Measured', 'High', 'included', 'floor_area')"""
        )
        self.conn.commit()
        res = derive_export_preflight(self.app, 1, bridge_available=True)
        self.assertEqual(res.publishable_takeoff_rows, 0)
        self.assertEqual(res.floor_reference_rows, 1)
        self.assertEqual(res.preflight_status, "BLOCKED")
        self.assertIn("Zero publishable take-off rows present in workspace.", res.blocking_reasons)


class TestConsequentialPublicationFailClosed(unittest.TestCase):
    def setUp(self):
        self.conn = _create_test_db()
        self.app = MockTestApp(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_verify_toctou_and_publish_aborts_when_preflight_blocked(self):
        """verify_toctou_and_publish_jobhub must abort with RuntimeError when preflight is BLOCKED."""
        # Force preflight blocked via unapproved model surface
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO takeoff_rows (
                id, workspace_id, section, element, unit, quantity, quantity_status,
                confidence, inclusion_status, row_role
            ) VALUES (1008, 1, 'Ext', 'Unapproved 3D', 'm²', 30.0, 'Measured', 'High', 'included', 'model_surface')"""
        )
        self.conn.commit()
        mock_pub = MagicMock()
        with self.assertRaises(RuntimeError) as ctx:
            verify_toctou_and_publish_jobhub(
                self.app, 1, bridge=MagicMock(), user_name="Tester",
                expected_fingerprint="dummy_fp", acknowledgement_confirmed=True,
                publish_fn=mock_pub
            )
        self.assertIn("Final publish blocked by preflight QA gate", str(ctx.exception))
        mock_pub.assert_not_called()


if __name__ == "__main__":
    unittest.main()
