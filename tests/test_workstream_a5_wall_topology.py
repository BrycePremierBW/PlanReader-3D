"""tests/test_workstream_a5_wall_topology.py — Workstream A5 Regression Suite.

Issue #81: Wall network topology & room space reconstruction.
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from pb_wall_topology_v174 import (
    RoomSpaceRecord,
    WallTopologyRegistry,
    compute_polygon_area_and_perimeter,
    derive_wall_topology,
)


def _create_mock_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            job_no TEXT,
            job_name TEXT
        );

        CREATE TABLE pages (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            page_label TEXT,
            px_per_m REAL
        );

        CREATE TABLE measurement_lines (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER,
            page_id INTEGER,
            line_type TEXT,
            length_m REAL,
            area_m2 REAL,
            raw_points TEXT
        );
        """
    )
    conn.commit()
    return conn


class WorkstreamA5TopologyTests(unittest.TestCase):

    def setUp(self):
        self.conn = _create_mock_db()
        cur = self.conn.cursor()
        cur.execute("INSERT INTO workspaces VALUES (1, 'JOB-A5', 'Topology Test')")
        cur.execute("INSERT INTO pages VALUES (10, 1, 'A-101 Floor Plan', 100.0)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_01_polygon_area_and_perimeter_calculation(self):
        """Calculates area (m²) and perimeter (m) for a 10m x 5m rectangle at 100 px/m."""
        # 10m * 100 = 1000px, 5m * 100 = 500px
        pts = [(0, 0), (1000, 0), (1000, 500), (0, 500)]
        area_m2, perim_m = compute_polygon_area_and_perimeter(pts, px_per_m=100.0)

        self.assertAlmostEqual(area_m2, 50.0, places=2)
        self.assertAlmostEqual(perim_m, 30.0, places=2)

    def test_02_room_space_wall_surface_derivation(self):
        """Deduces room wall surface area = Perimeter * Wall Height."""
        pts = [(0, 0), (1000, 0), (1000, 500), (0, 500)]
        raw_json = json.dumps(pts)

        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO measurement_lines VALUES (100, 1, 10, 'polygon', 30.0, 50.0, ?)",
            (raw_json,)
        )
        self.conn.commit()

        registry = derive_wall_topology(self.conn, 1, default_wall_height=2.7)
        self.assertEqual(len(registry.rooms), 1)

        room = registry.rooms[0]
        self.assertEqual(room.area_m2, 50.0)
        self.assertEqual(room.perimeter_m, 30.0)
        self.assertAlmostEqual(room.wall_surface_area_m2, 81.0, places=2)  # 30 * 2.7 = 81m²

    def test_03_workspace_wall_topology_registry(self):
        """derive_wall_topology computes total floor area and total wall surface area."""
        cur = self.conn.cursor()
        pts1 = [(0, 0), (1000, 0), (1000, 500), (0, 500)]  # 50m², 30m perim
        pts2 = [(0, 0), (600, 0), (600, 400), (0, 400)]    # 24m², 20m perim
        cur.execute("INSERT INTO measurement_lines VALUES (101, 1, 10, 'polygon', 30.0, 50.0, ?)", (json.dumps(pts1),))
        cur.execute("INSERT INTO measurement_lines VALUES (102, 1, 10, 'polygon', 20.0, 24.0, ?)", (json.dumps(pts2),))
        self.conn.commit()

        registry = derive_wall_topology(self.conn, 1, default_wall_height=2.7)
        self.assertEqual(len(registry.rooms), 2)
        self.assertAlmostEqual(registry.total_floor_area_m2(), 74.0, places=2)
        self.assertAlmostEqual(registry.total_wall_surface_m2(), 135.0, places=2)  # (30+20)*2.7 = 135m²

    def test_04_missing_scale_fails_closed_not_fabricated(self):
        """A page with no px_per_m and no stored measurement must NOT silently assume 100 px/m."""
        cur = self.conn.cursor()
        cur.execute("INSERT INTO pages VALUES (11, 1, 'A-102 No Scale', NULL)")
        pts = [(0, 0), (1000, 0), (1000, 500), (0, 500)]  # would be 50m2 @ 100px/m if fabricated
        cur.execute(
            "INSERT INTO measurement_lines VALUES (200, 1, 11, 'polygon', NULL, NULL, ?)",
            (json.dumps(pts),)
        )
        self.conn.commit()

        registry = derive_wall_topology(self.conn, 1, default_wall_height=2.7)
        self.assertEqual(len(registry.rooms), 1)
        room = registry.rooms[0]

        # Must fail closed to zero, never silently assume a 100 px/m default scale.
        self.assertEqual(room.area_m2, 0.0)
        self.assertEqual(room.perimeter_m, 0.0)
        self.assertEqual(room.wall_surface_area_m2, 0.0)
        self.assertFalse(room.scale_reliable)

        self.assertTrue(registry.is_blocked())
        issues = registry.get_issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["issue_type"], "UNRELIABLE_SCALE_GEOMETRY")
        self.assertEqual(issues[0]["page_id"], 11)

    def test_05_zero_and_nonfinite_scale_fail_closed(self):
        """px_per_m of 0, NaN, or inf must all fail closed rather than fabricating geometry."""
        cur = self.conn.cursor()
        cur.execute("INSERT INTO pages VALUES (12, 1, 'A-103 Zero Scale', 0.0)")
        cur.execute("INSERT INTO pages VALUES (13, 1, 'A-104 NaN Scale', ?)", (float("nan"),))
        cur.execute("INSERT INTO pages VALUES (14, 1, 'A-105 Inf Scale', ?)", (float("inf"),))
        pts = [(0, 0), (1000, 0), (1000, 500), (0, 500)]
        for mid, pid in ((300, 12), (301, 13), (302, 14)):
            cur.execute(
                "INSERT INTO measurement_lines VALUES (?, 1, ?, 'polygon', NULL, NULL, ?)",
                (mid, pid, json.dumps(pts))
            )
        self.conn.commit()

        registry = derive_wall_topology(self.conn, 1, default_wall_height=2.7)
        self.assertEqual(len(registry.rooms), 3)
        for room in registry.rooms:
            self.assertEqual(room.area_m2, 0.0)
            self.assertEqual(room.perimeter_m, 0.0)
            self.assertFalse(room.scale_reliable)
        self.assertTrue(registry.is_blocked())
        self.assertEqual(len(registry.get_issues()), 3)

    def test_06_stored_measurement_trusted_even_without_page_scale(self):
        """A canonical stored area/length is trusted as-is even if the page's px_per_m is later missing."""
        cur = self.conn.cursor()
        cur.execute("INSERT INTO pages VALUES (15, 1, 'A-106 No Scale But Stored', NULL)")
        cur.execute(
            "INSERT INTO measurement_lines VALUES (400, 1, 15, 'polygon', 30.0, 50.0, NULL)"
        )
        self.conn.commit()

        registry = derive_wall_topology(self.conn, 1, default_wall_height=2.7)
        self.assertEqual(len(registry.rooms), 1)
        room = registry.rooms[0]
        self.assertEqual(room.area_m2, 50.0)
        self.assertEqual(room.perimeter_m, 30.0)
        self.assertTrue(room.scale_reliable)
        self.assertFalse(registry.is_blocked())


if __name__ == "__main__":
    unittest.main()
