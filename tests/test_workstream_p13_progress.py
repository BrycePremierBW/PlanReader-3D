"""Workstream P13 Regression Test Suite: Progress Claims and Reconciliation.

Tests:
1. Progress row eligibility policy (excluding provisional, unapproved model, excluded, and floor reference rows).
2. takeoff_progress_rows filtering on mixed datasets.
3. Progress package manifest totals exact reconciliation (no provisional or ineligible data).
4. Progress package README totals exact reconciliation matching manifest and normalized units.
5. Progress package CSV exports (quantity_summary.csv and takeoff_lines_jobhub.csv) reconciliation.
6. TakeoffStudio completion_summary isolation of provisional areas from claimable completion.
7. End-to-end progress package generation with exact reconciliation across all representations.
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from typing import Any, Dict, List
import pandas as pd
import pytest

import pb_planreader_3d_app as app
import pb_takeoff_authority_v164 as auth
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    is_commercial_floor_reference_row,
    is_excluded_takeoff_row,
    is_floor_reference_row,
    is_model_surface_row,
    is_progress_eligible_row,
    is_provisional_takeoff_row,
    model_surface_authority,
    takeoff_row_publishability,
)
import pb_takeoff_studio_v1211 as studio
from pb_takeoff_studio_v1211 import completion_summary as studio_completion_summary
from pb_planreader_3d_app import takeoff_progress_rows



@pytest.fixture
def setup_db() -> None:
    app.init_local_db()


@pytest.fixture
def mixed_progress_workspace(setup_db: None) -> int:
    wid = app.create_standalone_workspace("PROG_WS", "Progress Tower", "BuildCorp", "50 Market St")
    app.set_workspace_setting(wid, "pricing_margin_pct", 15.0)
    app.set_workspace_setting(wid, "gst_rate_pct", 10.0)

    # Document & Page
    doc_id = app.lexecute(
        "INSERT INTO documents(workspace_id, file_name, source_type, category, page_count, uploaded_at) VALUES(?, 'A101.pdf', 'pdf', 'plans', 1, ?)",
        (wid, app.now_stamp()),
    )
    app.lexecute(
        "INSERT INTO pages(workspace_id, document_id, page_no, page_label, px_per_m) VALUES(?, ?, 1, 'Page 1', 100.0)",
        (wid, doc_id),
    )

    # 1. Authoritative manual measured row: Internal walls (ELIGIBLE)
    # 100 m², rate 20, coats 2, cov 10, prod 10 -> litres: 20, hours: 10, value: 2000
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, created_at, updated_at)
           VALUES(?, 'Internal walls', 'Walls', 'Level 1', 'Plasterboard', 'Low sheen', 100.0, 'm²', 'Measured', 'INCLUSION', 2.0, 10.0, 10.0, 20.0, 'Measured', 'work', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 2. Approved 3D model surface row: External walls (ELIGIBLE)
    # 50 m², rate 20, coats 2, cov 10, prod 10 -> litres: 10, hours: 5, value: 1000
    r2_id = app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, source_reference, source_page, created_at, updated_at)
           VALUES(?, 'External walls', '3D Facade Face 1', 'Facade', 'Render', 'Membrane', 50.0, 'm²', 'Measured', 'INCLUSION', 2.0, 10.0, 10.0, 20.0, 'Measured', 'model_surface', 'pb_3d_surface_editor_face1', '3d_model', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )
    row2 = dict(app.lquery("SELECT * FROM takeoff_rows WHERE id=?", (r2_id,))[0])
    approved_row2 = approve_model_surface_row(row2, source="Elevation A-101", reviewed_by="Estimator 1", reviewed_at="2026-09-06T10:00:00Z")
    app.lexecute(
        "UPDATE takeoff_rows SET commercial_authority_status=?, commercial_authority_source=?, commercial_authority_reviewed_by=?, commercial_authority_reviewed_at=?, commercial_authority_fingerprint=? WHERE id=?",
        (approved_row2["commercial_authority_status"], approved_row2["commercial_authority_source"], approved_row2["commercial_authority_reviewed_by"], approved_row2["commercial_authority_reviewed_at"], approved_row2["commercial_authority_fingerprint"], r2_id),
    )

    # 3. Unapproved 3D model surface row (INELIGIBLE - UNAPPROVED MODEL)
    # 30 m², rate 20 -> value 600
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, source_reference, source_page, created_at, updated_at)
           VALUES(?, 'External walls', '3D Facade Face 2', 'Facade', 'Render', 'Membrane', 30.0, 'm²', 'Provisional measured', 'INCLUSION', 2.0, 10.0, 10.0, 20.0, 'Derived', 'model_surface', 'pb_3d_surface_editor_face2', '3d_model', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 4. Provisional inclusion row: Feature canopy (INELIGIBLE FOR PROGRESS CLAIM - PROVISIONAL)
    # 40 m², rate 20 -> value 800
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, created_at, updated_at)
           VALUES(?, 'External walls', 'Feature canopy', 'Entrance', 'Steel', 'Epoxy', 40.0, 'm²', 'Provisional measured', 'PROVISIONAL', 2.0, 10.0, 10.0, 20.0, 'To review', 'work', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 5. Excluded row: Tenant fitout (INELIGIBLE - EXCLUDED)
    # 25 m², rate 20 -> value 500
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, created_at, updated_at)
           VALUES(?, 'Internal walls', 'Tenant fitout', 'Level 1', 'Plasterboard', 'Low sheen', 25.0, 'm²', 'Measured', 'EXCLUSION', 2.0, 10.0, 10.0, 20.0, 'Measured', 'work', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 6. Commercial floor reference row (INELIGIBLE AS WORK ROW)
    # 80 m²
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, created_at, updated_at)
           VALUES(?, 'Internal', 'Floor area', 'Level 1', 'Concrete', 'Clear sealer', 80.0, 'm²', 'Measured', 'INCLUSION', 0.0, 0.0, 0.0, 0.0, 'Measured', 'floor_area', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 7. Unapproved model floor reference row (INELIGIBLE - UNAPPROVED MODEL FLOOR)
    # 70 m²
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, source_reference, source_page, created_at, updated_at)
           VALUES(?, 'Internal', 'Floor area unapproved', 'Level 2', 'Concrete', 'Clear sealer', 70.0, 'm²', 'Provisional measured', 'INCLUSION', 0.0, 0.0, 0.0, 0.0, 'Derived', 'floor_area', 'pb_3d_surface_editor_floor', '3d_model', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 8. Authoritative manual row with ASCII 'm2': Internal ceilings (ELIGIBLE)
    # 60 m2, rate 10, coats 2, cov 10, prod 10 -> litres: 12, hours: 6, value: 600
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, created_at, updated_at)
           VALUES(?, 'Internal ceilings', 'Ceilings', 'Level 1', 'Plasterboard', 'Flat ceiling', 60.0, 'm2', 'Measured', 'INCLUSION', 2.0, 10.0, 10.0, 10.0, 'Measured', 'work', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    # 9. Authoritative manual row with lineal metres 'LM': Skirting (ELIGIBLE)
    # 30 LM, rate 15, coats 2, cov 10, prod 10 -> litres: 0, hours: 3, value: 450
    app.lexecute(
        """INSERT INTO takeoff_rows(workspace_id, section, element, location, substrate, finish_system, quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour, rate_per_unit, confidence, row_role, created_at, updated_at)
           VALUES(?, 'Internal trim', 'Skirting', 'Level 1', 'Timber', 'Gloss', 30.0, 'LM', 'Measured', 'INCLUSION', 2.0, 10.0, 10.0, 15.0, 'Measured', 'work', ?, ?)""",
        (wid, app.now_stamp(), app.now_stamp()),
    )

    return wid


class TestProgressRowEligibility:
    """Test unit-level progress row eligibility and provisional status detection."""

    def test_authoritative_measured_row_is_eligible(self) -> None:
        assert is_progress_eligible_row is not None, "is_progress_eligible_row must be implemented in pb_takeoff_authority_v164"
        assert is_provisional_takeoff_row is not None, "is_provisional_takeoff_row must be implemented in pb_takeoff_authority_v164"
        row = {
            "quantity": 100.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "inclusion_status": "INCLUSION",
            "row_role": "work",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is True
        assert reason == "ELIGIBLE"
        assert is_provisional_takeoff_row(row) is False

    def test_approved_model_surface_row_is_eligible(self) -> None:
        row = {
            "workspace_id": 1,
            "section": "External",
            "element": "3D Facade",
            "location": "L1",
            "substrate": "Render",
            "quantity": 50.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "inclusion_status": "INCLUSION",
            "row_role": "model_surface",
            "source_reference": "pb_3d_surface_editor_face1",
            "source_page": "3d_model",
        }
        approved = approve_model_surface_row(row, source="Drawing A101", reviewed_by="Reviewer", reviewed_at="2026-09-06T10:00:00Z")
        eligible, reason = is_progress_eligible_row(approved)
        assert eligible is True
        assert reason == "ELIGIBLE"

    def test_unapproved_model_surface_row_is_ineligible(self) -> None:
        row = {
            "quantity": 50.0,
            "unit": "m²",
            "quantity_status": "Provisional measured",
            "inclusion_status": "INCLUSION",
            "row_role": "model_surface",
            "source_reference": "pb_3d_surface_editor_face1",
            "source_page": "3d_model",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is False
        assert "not received commercial approval" in reason.lower()
        assert is_provisional_takeoff_row(row) is True

    def test_provisional_inclusion_row_is_ineligible(self) -> None:
        row = {
            "quantity": 40.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "inclusion_status": "PROVISIONAL",
            "row_role": "work",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is False
        assert reason == "PROVISIONAL"
        assert is_provisional_takeoff_row(row) is True

    def test_provisional_quantity_status_row_is_ineligible(self) -> None:
        row = {
            "quantity": 40.0,
            "unit": "m²",
            "quantity_status": "Provisional measured",
            "inclusion_status": "INCLUSION",
            "row_role": "work",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is False
        assert reason == "PROVISIONAL"
        assert is_provisional_takeoff_row(row) is True

    def test_to_measure_status_row_is_ineligible(self) -> None:
        row = {
            "quantity": 40.0,
            "unit": "m²",
            "quantity_status": "To measure",
            "inclusion_status": "INCLUSION",
            "row_role": "work",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is False
        assert reason == "PROVISIONAL"
        assert is_provisional_takeoff_row(row) is True

    def test_excluded_row_is_ineligible(self) -> None:
        row = {
            "quantity": 25.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "inclusion_status": "EXCLUSION",
            "row_role": "work",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is False
        assert reason == "EXCLUDED"

    def test_floor_reference_row_is_ineligible_for_progress(self) -> None:
        row = {
            "quantity": 80.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "inclusion_status": "INCLUSION",
            "row_role": "floor_area",
        }
        eligible, reason = is_progress_eligible_row(row)
        assert eligible is False
        assert reason == "FLOOR_REFERENCE"

    def test_zero_or_negative_or_nan_quantity_row_is_ineligible(self) -> None:
        for bad_qty in [0.0, -10.0, float("nan"), float("inf"), None]:
            row = {
                "quantity": bad_qty,
                "unit": "m²",
                "quantity_status": "Measured",
                "inclusion_status": "INCLUSION",
                "row_role": "work",
            }
            eligible, reason = is_progress_eligible_row(row)
            assert eligible is False
            assert reason == "ZERO_OR_INVALID_QUANTITY"


class TestTakeoffProgressRowsFiltering:
    """Test DataFrame-level filtering for progress claims."""

    def test_takeoff_progress_rows_keeps_only_eligible_work(self, mixed_progress_workspace: int) -> None:
        wid = mixed_progress_workspace
        raw = app.dataframe_for_takeoff(wid)
        progress_rows = app.takeoff_progress_rows(raw)

        # In mixed_progress_workspace, eligible rows are:
        # 1. Row 1: Internal walls (100 m²)
        # 2. Row 2: Approved 3D Facade Face 1 (50 m²)
        # 3. Row 8: Internal ceilings (60 m²)
        # 4. Row 9: Skirting (30 LM)
        # Total = 4 rows!
        assert len(progress_rows) == 4

        # Verify excluded, unapproved model, provisional, and floor rows are absent
        roles = progress_rows["row_role"].tolist()
        assert "floor_area" not in roles
        inclusions = progress_rows["inclusion_status"].str.upper().tolist()
        assert "EXCLUSION" not in inclusions
        assert "PROVISIONAL" not in inclusions
        statuses = progress_rows["quantity_status"].str.lower().tolist()
        assert "provisional measured" not in statuses


class TestProgressPackageManifestReconciliation:
    """Test progress marker package manifest totals and exact figures."""

    def test_package_manifest_totals_reconciliation(self, mixed_progress_workspace: int) -> None:
        wid = mixed_progress_workspace
        pkg_bytes = app.progress_package_bytes(wid)
        zf = zipfile.ZipFile(io.BytesIO(pkg_bytes))

        manifest = json.loads(zf.read("package_manifest.json").decode("utf-8"))
        totals = manifest["totals"]

        # Expected eligible rows:
        # Row 1: 100 m² @ $20 = $2000, 20 L, 10 hrs
        # Row 2: 50 m² @ $20 = $1000, 10 L, 5 hrs
        # Row 8: 60 m² @ $10 = $600, 12 L, 6 hrs
        # Row 9: 30 LM @ $15 = $450, 0 L, 3 hrs
        # Sums:
        # m2: 100 + 50 + 60 = 210.0 m²
        # lm: 30.0 lm
        # paint_litres: 20 + 10 + 12 = 42.0 L
        # labour_hours: 10 + 5 + 6 + 3 = 24.0 hrs
        # value_ex_gst: 2000 + 1000 + 600 + 450 = $4050.0

        assert totals["m2"] == pytest.approx(210.0)
        assert totals["lm"] == pytest.approx(30.0)
        assert totals["count"] == pytest.approx(0.0)
        assert totals["paint_litres"] == pytest.approx(42.0)
        assert totals["labour_hours"] == pytest.approx(24.0)
        assert totals["value_ex_gst"] == pytest.approx(4050.0)

        # Strictly measured rows count should be 4 (all 4 eligible rows are Measured)
        # It must NOT count the provisional row (Feature canopy)
        assert manifest["measured_rows"] == 4


class TestProgressPackageReadmeReconciliation:
    """Test progress marker README figures match manifest and filter properly."""

    def test_readme_reconciles_with_manifest_and_filters_unapproved_floors(self, mixed_progress_workspace: int) -> None:
        wid = mixed_progress_workspace
        pkg_bytes = app.progress_package_bytes(wid)
        zf = zipfile.ZipFile(io.BytesIO(pkg_bytes))

        readme = zf.read("README.txt").decode("utf-8")
        manifest = json.loads(zf.read("package_manifest.json").decode("utf-8"))
        totals = manifest["totals"]

        # Extract parsed key-value lines from README
        readme_dict = {}
        for line in readme.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                readme_dict[k.strip()] = v.strip()

        # Take-off lines in claim: 4
        assert readme_dict.get("Take-off lines") == "4"

        # Measured m2: 210.00
        assert readme_dict.get("Measured m2") == f"{totals['m2']:,.2f}"

        # Paint litres: 42.00
        assert readme_dict.get("Paint litres") == f"{totals['paint_litres']:,.2f}"

        # Labour hours: 24.00
        assert readme_dict.get("Labour hours") == f"{totals['labour_hours']:,.2f}"

        # Value ex GST: $4,050.00
        assert readme_dict.get("Value ex GST") == f"${totals['value_ex_gst']:,.2f}"

        # Floor m2 (ref): only the approved commercial floor row (80.00 m²), NOT unapproved (70.00)
        assert readme_dict.get("Floor m2 (ref)") == "80.00"

    def test_readme_with_mixed_ascii_and_unicode_units_normalizes_cleanly(self) -> None:
        raw_takeoff = pd.DataFrame([
            {"section": "Internal", "element": "Walls", "location": "L1", "quantity": 100.0, "unit": "m²", "quantity_status": "Measured", "inclusion_status": "INCLUSION", "paint_litres": 20.0, "labour_hours": 10.0, "value_ex_gst": 2000.0, "row_role": "work"},
            {"section": "Internal", "element": "Walls", "location": "L1", "quantity": 50.0, "unit": "m2", "quantity_status": "Measured", "inclusion_status": "INCLUSION", "paint_litres": 10.0, "labour_hours": 5.0, "value_ex_gst": 1000.0, "row_role": "work"},
            {"section": "Internal", "element": "Floor", "location": "L1", "quantity": 80.0, "unit": "m²", "quantity_status": "Measured", "inclusion_status": "INCLUSION", "paint_litres": 0.0, "labour_hours": 0.0, "value_ex_gst": 0.0, "row_role": "floor_area"},
            {"section": "Internal", "element": "Floor", "location": "L2", "quantity": 60.0, "unit": "m2", "quantity_status": "Measured", "inclusion_status": "INCLUSION", "paint_litres": 0.0, "labour_hours": 0.0, "value_ex_gst": 0.0, "row_role": "floor_area"},
            {"section": "Internal", "element": "Floor unapproved", "location": "L3", "quantity": 40.0, "unit": "m²", "quantity_status": "Provisional measured", "inclusion_status": "INCLUSION", "paint_litres": 0.0, "labour_hours": 0.0, "value_ex_gst": 0.0, "row_role": "floor_area", "source_reference": "pb_3d_surface_editor_floor"},
        ])
        pages = pd.DataFrame()
        workspace = {"job_no": "P13-JOB", "job_name": "Test", "builder_client": "Builder"}
        readme = app._progress_package_readme(workspace, raw_takeoff, pages)

        readme_dict = {}
        for line in readme.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                readme_dict[k.strip()] = v.strip()

        # Both m² (100) and m2 (50) must be summed together into Measured m2 -> 150.00
        assert readme_dict.get("Measured m2") == "150.00"

        # Commercial floors: 80 (m²) + 60 (m2) = 140.00. Unapproved (40) excluded!
        assert readme_dict.get("Floor m2 (ref)") == "140.00"


class TestProgressPackageCsvExportsReconciliation:
    """Test CSVs in progress package match manifest totals."""

    def test_quantity_summary_csv_matches_manifest(self, mixed_progress_workspace: int) -> None:
        wid = mixed_progress_workspace
        pkg_bytes = app.progress_package_bytes(wid)
        zf = zipfile.ZipFile(io.BytesIO(pkg_bytes))

        manifest = json.loads(zf.read("package_manifest.json").decode("utf-8"))
        totals = manifest["totals"]

        csv_text = zf.read("takeoff/quantity_summary.csv").decode("utf-8")
        df = pd.read_csv(io.StringIO(csv_text))

        assert df["m2"].sum() == pytest.approx(totals["m2"])
        assert df["lineal_m"].sum() == pytest.approx(totals["lm"])
        assert df["paint_litres"].sum() == pytest.approx(totals["paint_litres"])
        assert df["labour_hours"].sum() == pytest.approx(totals["labour_hours"])
        assert df["value_ex_gst"].sum() == pytest.approx(totals["value_ex_gst"])

    def test_takeoff_lines_jobhub_csv_matches_manifest(self, mixed_progress_workspace: int) -> None:
        wid = mixed_progress_workspace
        pkg_bytes = app.progress_package_bytes(wid)
        zf = zipfile.ZipFile(io.BytesIO(pkg_bytes))

        manifest = json.loads(zf.read("package_manifest.json").decode("utf-8"))
        totals = manifest["totals"]

        csv_text = zf.read("takeoff/takeoff_lines_jobhub.csv").decode("utf-8")
        df = pd.read_csv(io.StringIO(csv_text))

        assert df["qty_m2"].sum() == pytest.approx(totals["m2"])
        assert df["lineal_m"].sum() == pytest.approx(totals["lm"])
        assert df["paint_litres"].sum() == pytest.approx(totals["paint_litres"])
        assert df["labour_hours"].sum() == pytest.approx(totals["labour_hours"])
        assert df["value_ex_gst"].sum() == pytest.approx(totals["value_ex_gst"])


class TestTakeoffStudioCompletionSummary:
    """Test TakeoffStudio completion_summary separates provisional areas from claimable completion."""

    def test_completion_summary_isolates_provisional_areas(self) -> None:
        areas = [
            {"id": "A-1", "area_m2": 100.0, "progress_pct": 80.0, "status": "Paint Included"},
            {"id": "A-2", "area_m2": 50.0, "progress_pct": 100.0, "status": "Separate Item"},
            {"id": "A-3", "area_m2": 40.0, "progress_pct": 50.0, "status": "Provisional"},
            {"id": "A-4", "area_m2": 30.0, "progress_pct": 100.0, "status": "Excluded"},
        ]
        res = studio_completion_summary(areas)

        # Claimable total m2: 100 + 50 = 150.0 m² (Provisional and Excluded are not claimable)
        assert res["total_m2"] == pytest.approx(150.0)
        # Completed claimable m2: (100 * 0.8) + (50 * 1.0) = 80 + 50 = 130.0 m²
        assert res["completed_m2"] == pytest.approx(130.0)
        # Remaining claimable m2: 150.0 - 130.0 = 20.0 m²
        assert res["remaining_m2"] == pytest.approx(20.0)
        # Completed %: 130.0 / 150.0 * 100 = 86.7%
        assert res["completed_pct"] == pytest.approx(86.7)
        # Provisional m2 tracked separately
        assert res.get("provisional_m2") == pytest.approx(40.0)
