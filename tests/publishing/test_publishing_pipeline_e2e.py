"""tests/publishing/test_publishing_pipeline_e2e.py — End-to-end integration tests for publishing pipeline."""
import sqlite3
import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_jobhub_publishing_contract import PublishingMode
from pb_jobhub_publishing_pipeline import (
    build_publishing_package_from_workspace,
    execute_jobhub_publishing,
)


class MockJobHubBridge:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.kind = "sqlite"

    def connect(self):
        return self._conn

    def query(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]


@pytest.fixture
def test_dbs():
    # 1. Local PlanReader Database
    pr_conn = sqlite3.connect(":memory:")
    pr_conn.row_factory = sqlite3.Row
    pr_cur = pr_conn.cursor()

    pr_cur.execute("""
    CREATE TABLE workspaces (
        id INTEGER PRIMARY KEY,
        job_no TEXT,
        job_name TEXT,
        builder_client TEXT,
        site_address TEXT,
        drawing_issue TEXT,
        jobhub_job_id INTEGER,
        estimator TEXT
    )
    """)
    pr_cur.execute("""
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY,
        workspace_id INTEGER,
        file_name TEXT
    )
    """)
    pr_cur.execute("""
    CREATE TABLE pages (
        id INTEGER PRIMARY KEY,
        workspace_id INTEGER,
        page_no INTEGER
    )
    """)
    pr_cur.execute("""
    CREATE TABLE takeoff_rows (
        id INTEGER PRIMARY KEY,
        workspace_id INTEGER,
        section TEXT,
        location TEXT,
        substrate TEXT,
        finish_tag TEXT,
        element TEXT,
        unit TEXT,
        quantity REAL,
        rate REAL,
        total_price REAL,
        commercial_authority_status TEXT,
        commercial_authority_source TEXT,
        commercial_authority_reviewed_by TEXT,
        commercial_authority_reviewed_at TEXT,
        source_page TEXT,
        notes TEXT
    )
    """)

    pr_cur.execute("""
    INSERT INTO workspaces (id, job_no, job_name, builder_client, site_address, drawing_issue, jobhub_job_id, estimator)
    VALUES (1, '26-017', '60-62 School Rd Maroochydore', 'Balleo Pty Ltd', '60-62 School Rd, Maroochydore', 'BA Issue', 501, 'Bryce Curran')
    """)
    pr_cur.execute("INSERT INTO documents (workspace_id, file_name) VALUES (1, '26-017_BA_Drawings.pdf')")
    pr_cur.execute("INSERT INTO pages (workspace_id, page_no) VALUES (1, 1), (1, 2), (1, 3)")

    # 2. Remote JobHub Database
    hub_conn = sqlite3.connect(":memory:")
    hub_cur = hub_conn.cursor()

    hub_cur.execute("""
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY,
        status TEXT,
        notes TEXT
    )
    """)
    hub_cur.execute("INSERT INTO jobs (id, status, notes) VALUES (501, 'Active', 'Commercial Townhouses')")

    hub_cur.execute("""
    CREATE TABLE painting_takeoff_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        takeoff_no TEXT,
        status TEXT,
        interior_m2 REAL,
        exterior_m2 REAL,
        total_hours REAL,
        total_litres REAL,
        created_by TEXT,
        notes TEXT
    )
    """)
    hub_cur.execute("""
    CREATE TABLE painting_takeoff_package_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_id INTEGER,
        section TEXT,
        location TEXT,
        substrate TEXT,
        element TEXT,
        unit TEXT,
        quantity REAL,
        rate REAL,
        total_price REAL
    )
    """)
    hub_conn.commit()

    bridge = MockJobHubBridge(hub_conn)
    return pr_conn, hub_conn, bridge


def test_e2e_commercial_publishing(test_dbs):
    pr_conn, hub_conn, bridge = test_dbs

    # Insert firm takeoff rows
    pr_conn.execute("""
    INSERT INTO takeoff_rows (
        id, workspace_id, section, location, substrate, finish_tag, element, unit, quantity, rate, total_price,
        commercial_authority_status, commercial_authority_source, commercial_authority_reviewed_by
    ) VALUES
    (1, 1, 'Internal walls and ceilings', 'Unit 1', 'Plasterboard', 'PB01', 'Internal Wall', 'm2', 150.0, 22.0, 3300.0, 'firm', 'documented_dimension', 'Bryce Curran'),
    (2, 1, 'External facade', 'Building A', 'Fibre Cement', 'EC01', 'External Cladding', 'm2', 200.0, 35.0, 7000.0, 'firm', 'documented_dimension', 'Bryce Curran')
    """)
    pr_conn.commit()

    pkg = build_publishing_package_from_workspace(
        conn=pr_conn,
        workspace_id=1,
        mode=PublishingMode.COMMERCIAL,
        preflight_fingerprint="fp_abc123456789",
    )
    assert len(pkg.quantities) == 2

    receipt = execute_jobhub_publishing(
        package=pkg,
        bridge=bridge,
        user_name="Bryce Curran",
    )

    assert receipt["success"] is True
    assert receipt["status"] == "Published"
    assert receipt["package_id"] == 1
    assert receipt["interior_m2"] == 150.0
    assert receipt["exterior_m2"] == 200.0
    assert receipt["total_cost"] == 10300.0

    # Verify persisted in JobHub
    cur = hub_conn.cursor()
    cur.execute("SELECT id, status, interior_m2, exterior_m2 FROM painting_takeoff_packages WHERE id=1")
    pkg_row = cur.fetchone()
    assert pkg_row[1] == "Published"
    assert pkg_row[2] == 150.0
    assert pkg_row[3] == 200.0

    cur.execute("SELECT COUNT(*) FROM painting_takeoff_package_lines WHERE package_id=1")
    assert cur.fetchone()[0] == 2


def test_e2e_draft_publishing(test_dbs):
    pr_conn, hub_conn, bridge = test_dbs

    # Insert provisional takeoff row
    pr_conn.execute("""
    INSERT INTO takeoff_rows (
        id, workspace_id, section, location, substrate, finish_tag, element, unit, quantity, rate, total_price,
        commercial_authority_status, commercial_authority_source
    ) VALUES
    (1, 1, 'Internal walls', 'Unit 1', 'Plasterboard', 'PB01', 'Internal Wall', 'm2', 95.0, 22.0, 2090.0, 'provisional', 'pdf_scaled')
    """)
    pr_conn.commit()

    pkg = build_publishing_package_from_workspace(
        conn=pr_conn,
        workspace_id=1,
        mode=PublishingMode.DRAFT,
        preflight_fingerprint="fp_draft123456",
    )
    assert len(pkg.quantities) == 1

    receipt = execute_jobhub_publishing(
        package=pkg,
        bridge=bridge,
        user_name="Bryce Curran",
    )

    assert receipt["success"] is True
    assert receipt["status"] == "Draft"

    cur = hub_conn.cursor()
    cur.execute("SELECT status FROM painting_takeoff_packages WHERE id=?", (receipt["package_id"],))
    assert cur.fetchone()[0] == "Draft"


def test_duplicate_publishing_rejected(test_dbs):
    pr_conn, hub_conn, bridge = test_dbs

    pr_conn.execute("""
    INSERT INTO takeoff_rows (
        id, workspace_id, section, location, substrate, finish_tag, element, unit, quantity, rate, total_price,
        commercial_authority_status, commercial_authority_source
    ) VALUES
    (1, 1, 'Internal walls', 'Unit 1', 'Plasterboard', 'PB01', 'Internal Wall', 'm2', 50.0, 20.0, 1000.0, 'firm', 'documented_dimension')
    """)
    pr_conn.commit()

    pkg = build_publishing_package_from_workspace(
        conn=pr_conn,
        workspace_id=1,
        mode=PublishingMode.COMMERCIAL,
    )

    # First publish succeeds
    execute_jobhub_publishing(package=pkg, bridge=bridge, user_name="Bryce Curran")

    # Second publish with identical payload hash is rejected
    with pytest.raises(RuntimeError, match="Duplicate package"):
        execute_jobhub_publishing(package=pkg, bridge=bridge, user_name="Bryce Curran")


def test_unapproved_ai_rows_blocked_in_commercial_pipeline(test_dbs):
    pr_conn, hub_conn, bridge = test_dbs

    pr_conn.execute("""
    INSERT INTO takeoff_rows (
        id, workspace_id, section, location, substrate, finish_tag, element, unit, quantity, rate, total_price,
        commercial_authority_status, commercial_authority_source
    ) VALUES
    (1, 1, 'Internal walls', 'Unit 1', 'Plasterboard', 'PB01', 'AI Wall Detection', 'm2', 120.0, 20.0, 2400.0, 'firm', 'ai_detected')
    """)
    pr_conn.commit()

    pkg = build_publishing_package_from_workspace(
        conn=pr_conn,
        workspace_id=1,
        mode=PublishingMode.COMMERCIAL,
    )

    with pytest.raises(RuntimeError, match="Publishing blocked by gate QA checks"):
        execute_jobhub_publishing(package=pkg, bridge=bridge, user_name="Bryce Curran")
