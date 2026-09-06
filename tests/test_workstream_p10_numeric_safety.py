"""tests/test_workstream_p10_numeric_safety.py — P10: Commercial Numeric Safety Regression Suite.

Verifies strict commercial numeric hygiene across:
  - quantity, rate, coats, coverage, productivity, labour_hours, paint_litres, value_ex_gst, px_per_m, length, area
  - NaN, +inf, -inf, booleans, and malformed numeric strings
  - No non-finite commercial value may enter pricing, quotation, progress, JobHub, fingerprints, payload hashes, exports
  - Python JSON RFC 8259 handling (allow_nan=False, rejection of NaN/Infinity)
"""
from __future__ import annotations

import io
import json
import math
import sqlite3
import zipfile
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

import pb_planreader_3d_app as app
from pb_commercial_signoff_v181 import (
    compute_commercial_signature,
)
from pb_planreader_3d_app import (
    _quote_settings,
    _sync_jobhub_takeoff_rows,
    dataframe_for_takeoff,
    labour_hours,
    paint_litres,
    per_level_summary,
    progress_package_bytes,
    quote_pdf_bytes,
    quote_summary_frame,
    quote_workbook_bytes,
    row_value,
    to_float,
    to_int,
)
from pb_takeoff_authority_v164 import (
    compute_model_surface_authority_fingerprint,
)


def _strict_rfc8259_loads(s: str) -> Any:
    """Parse JSON enforcing strict RFC 8259 compliance (no NaN, Infinity, -Infinity)."""
    def _reject_constant(c: str) -> None:
        raise ValueError(f"Invalid RFC 8259 constant: {c}")
    return json.loads(s, parse_constant=_reject_constant)


class TestToFloatAndToIntHygiene:
    """Unit tests for to_float and to_int core conversion hygiene."""

    def test_to_float_booleans(self) -> None:
        # In standard Python, float(True) == 1.0 and float(False) == 0.0.
        # For commercial quantities/rates, booleans are not valid numbers and must return default.
        assert to_float(True) == 0.0
        assert to_float(False) == 0.0
        assert to_float(True, default=5.0) == 5.0
        assert to_float(False, default=10.0) == 10.0

    def test_to_float_non_finite_values(self) -> None:
        assert to_float(float("nan")) == 0.0
        assert to_float(float("inf")) == 0.0
        assert to_float(float("-inf")) == 0.0

    def test_to_float_non_finite_strings(self) -> None:
        assert to_float("NaN") == 0.0
        assert to_float("nan") == 0.0
        assert to_float("+inf") == 0.0
        assert to_float("-inf") == 0.0
        assert to_float("Infinity") == 0.0
        assert to_float("-Infinity") == 0.0

    def test_to_float_malformed_strings(self) -> None:
        assert to_float("abc") == 0.0
        assert to_float("12.34.56") == 0.0
        assert to_float("") == 0.0
        assert to_float("   ") == 0.0

    def test_to_float_formatted_numbers(self) -> None:
        assert to_float("$1,250.50") == 1250.50
        assert to_float("  42.5  ") == 42.5
        assert to_float(100) == 100.0

    def test_to_float_safe_default_fallback(self) -> None:
        # If default itself is non-finite or boolean, fallback safely to 0.0
        assert to_float("nan", default=float("inf")) == 0.0
        assert to_float("nan", default=float("nan")) == 0.0
        assert to_float("nan", default=True) == 0.0

    def test_to_int_hygiene(self) -> None:
        assert to_int(True) == 0
        assert to_int(False) == 0
        assert to_int(float("nan")) == 0
        assert to_int(float("inf")) == 0
        assert to_int(float("-inf")) == 0
        assert to_int("NaN") == 0
        assert to_int("+inf") == 0
        assert to_int("$1,250") == 1250
        assert to_int("42") == 42
        assert to_int(42.9) == 42
        assert to_int("bad", default=7) == 7
        assert to_int("bad", default=float("nan")) == 0


class TestCorePricingMathHygiene:
    """Tests that core pricing functions strictly reject non-finite inputs."""

    def test_paint_litres_non_finite_rejection(self) -> None:
        assert paint_litres(float("nan"), "m²", 2.0, 12.0) == 0.0
        assert paint_litres(10.0, "m²", float("inf"), 12.0) == 0.0
        assert paint_litres(10.0, "m²", 2.0, float("nan")) == 0.0
        assert paint_litres(10.0, "m²", 2.0, float("inf")) == 0.0
        assert paint_litres(10.0, "m²", 2.0, 0.0) == 0.0
        assert paint_litres(-10.0, "m²", 2.0, 12.0) == 0.0
        # Valid case produces strictly finite positive float
        res = paint_litres(120.0, "m²", 2.0, 12.0)
        assert math.isclose(res, 20.0)
        assert math.isfinite(res)

    def test_labour_hours_non_finite_rejection(self) -> None:
        assert labour_hours(float("nan"), "m²", 8.0) == 0.0
        assert labour_hours(10.0, "m²", float("nan")) == 0.0
        assert labour_hours(10.0, "m²", float("inf")) == 0.0
        assert labour_hours(10.0, "m²", 0.0) == 0.0
        assert labour_hours(-10.0, "m²", 8.0) == 0.0
        # Valid case
        res = labour_hours(80.0, "m²", 8.0)
        assert math.isclose(res, 10.0)
        assert math.isfinite(res)

    def test_row_value_non_finite_rejection(self) -> None:
        assert row_value(float("nan"), 25.0) == 0.0
        assert row_value(10.0, float("nan")) == 0.0
        assert row_value(10.0, float("inf")) == 0.0
        assert row_value(10.0, float("-inf")) == 0.0
        assert row_value(-10.0, 25.0) == 0.0
        assert row_value(10.0, -25.0) == 0.0
        # Valid case
        res = row_value(10.0, 25.0)
        assert math.isclose(res, 250.0)
        assert math.isfinite(res)


class TestQuoteSettingsNumericHygiene:
    """Tests that workspace settings cannot inject non-finite values into quotes."""

    def test_quote_settings_sanitizes_nan_and_inf(self) -> None:
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("CREATE TABLE workspace_settings (workspace_id INTEGER, key TEXT, value TEXT, updated_at TEXT, PRIMARY KEY (workspace_id, key))")
        cur.execute("INSERT INTO workspace_settings VALUES (1, 'gst_rate_pct', 'NaN', '2026-09-06')")
        cur.execute("INSERT INTO workspace_settings VALUES (1, 'pricing_margin_pct', 'inf', '2026-09-06')")
        cur.execute("INSERT INTO workspace_settings VALUES (1, 'default_coverage_m2_per_litre', '-5.0', '2026-09-06')")
        conn.commit()

        orig_lquery = app.lquery
        app.lquery = lambda sql, params=(): [{"value": r[0]} for r in cur.execute(sql, params).fetchall()]
        try:
            settings = _quote_settings(1)
            assert math.isfinite(settings["gst_rate_pct"])
            assert settings["gst_rate_pct"] == 10.0  # Fallback to default
            assert math.isfinite(settings["pricing_margin_pct"])
            assert settings["pricing_margin_pct"] == 0.0  # Fallback to default
            assert settings["default_coverage_m2_per_litre"] == 12.0  # Fallback to default
        finally:
            app.lquery = orig_lquery


class TestTakeoffDataFrameAndQuotationHygiene:
    """Tests end-to-end quotation and export flows with non-finite values in SQLite."""

    @pytest.fixture
    def setup_takeoff_db(self, tmp_path) -> str:
        db_path = str(tmp_path / "p10_test.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY, job_no TEXT, job_name TEXT, builder_client TEXT, site_address TEXT,
            drawing_issue TEXT, estimator TEXT, status TEXT, executive_summary TEXT, created_at TEXT,
            jobhub_job_id INTEGER
        );
        CREATE TABLE workspace_settings (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, key TEXT, value TEXT, updated_at TEXT,
            UNIQUE(workspace_id, key)
        );
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, source_type TEXT, jobhub_table TEXT,
            jobhub_record_id TEXT, file_name TEXT, mime_type TEXT, path TEXT, sha256 TEXT,
            category TEXT, page_count INTEGER DEFAULT 0, extracted_text TEXT, uploaded_at TEXT
        );
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY, document_id INTEGER, workspace_id INTEGER, page_no INTEGER,
            page_label TEXT, page_type TEXT, scale_text TEXT, px_per_m REAL, image_path TEXT,
            width_px INTEGER, height_px INTEGER, render_zoom REAL, extracted_text TEXT,
            selected INTEGER DEFAULT 1, created_at TEXT
        );
        CREATE TABLE takeoff_rows (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, section TEXT, element TEXT, location TEXT,
            substrate TEXT, finish_system TEXT, quantity REAL DEFAULT 0, unit TEXT, quantity_status TEXT,
            source_page TEXT, source_reference TEXT, inclusion_status TEXT, coats REAL DEFAULT 2,
            coverage_m2_per_litre REAL DEFAULT 12, productivity_m2_per_hour REAL DEFAULT 8,
            rate_per_unit REAL DEFAULT 0, confidence TEXT, notes TEXT, row_role TEXT DEFAULT '',
            commercial_authority_status TEXT DEFAULT '', commercial_authority_source TEXT DEFAULT '',
            commercial_authority_reviewed_by TEXT DEFAULT '', commercial_authority_reviewed_at TEXT DEFAULT '',
            commercial_authority_fingerprint TEXT DEFAULT '', created_at TEXT, updated_at TEXT
        );
        CREATE TABLE register_items (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, register_name TEXT, item_no INTEGER, title TEXT,
            detail TEXT, status TEXT, priority TEXT, source_reference TEXT
        );
        CREATE TABLE mapped_zones (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, page_id INTEGER, name TEXT, view_type TEXT,
            polygon_json TEXT, x_px REAL, y_px REAL, w_px REAL, h_px REAL, px_per_m REAL,
            wall_height_m REAL, area_m2 REAL, substrate TEXT, finish_system TEXT, quantity_status TEXT,
            source_reference TEXT, created_at TEXT
        );
        CREATE TABLE model_masses (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, label TEXT, level_name TEXT, x REAL, y REAL,
            z REAL, width REAL, depth REAL, height REAL, finish TEXT, source_reference TEXT,
            confidence TEXT, notes TEXT, created_at TEXT
        );
        CREATE TABLE model_openings (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, mass_id INTEGER, label TEXT, opening_type TEXT,
            face TEXT, offset_x REAL, offset_z REAL, width REAL, height REAL, count INTEGER, notes TEXT,
            source_reference TEXT, created_at TEXT
        );
        CREATE TABLE measurement_lines (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, page_id INTEGER, takeoff_row_id INTEGER,
            label TEXT, unit TEXT, colour TEXT, kind TEXT, x1 REAL, y1 REAL, x2 REAL, y2 REAL,
            points TEXT, length_m REAL, area_m2 REAL, perimeter_m REAL, quantity_status TEXT,
            moved INTEGER, notes TEXT, created_at TEXT
        );
        """)
        # Insert base job & page
        cur.execute("INSERT INTO workspaces VALUES (1, 'JOB-P10', 'Numeric Safety Job', 'Builder', '100 Main St', 'Rev A', 'Estimator', 'Draft', 'Exec Summary', '2026-09-06', 101)")
        cur.execute("INSERT INTO documents VALUES (1, 1, 'plans', '', '', 'plans.pdf', 'application/pdf', 'plans.pdf', 'hash', 'Drawing', 1, '', '2026-09-06')")
        cur.execute("INSERT INTO pages VALUES (1, 1, 1, 1, 'Ground', 'Floor Plan', '1:100', 100.0, '', 1000, 1000, 2.0, '', 1, '2026-09-06')")

        # Insert rows with corrupt, non-finite, and string quantities/rates
        cur.execute(
            """INSERT INTO takeoff_rows (id, workspace_id, section, element, location, substrate, finish_system,
               quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour,
               rate_per_unit, confidence, row_role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, 1, "Internal walls", "Corrupt String Qty", "Ground", "Plasterboard", "Low sheen",
             "NaN", "m²", "Measured", "Included", 2.0, 12.0, 8.0, 25.0, "High", "work", "2026-09-06", "2026-09-06")
        )
        cur.execute(
            """INSERT INTO takeoff_rows (id, workspace_id, section, element, location, substrate, finish_system,
               quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour,
               rate_per_unit, confidence, row_role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (2, 1, "Internal walls", "Inf Float Qty", "Ground", "Plasterboard", "Low sheen",
             float("inf"), "m²", "Measured", "Included", 2.0, 12.0, 8.0, 25.0, "High", "work", "2026-09-06", "2026-09-06")
        )
        cur.execute(
            """INSERT INTO takeoff_rows (id, workspace_id, section, element, location, substrate, finish_system,
               quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour,
               rate_per_unit, confidence, row_role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (3, 1, "Internal walls", "Valid Row", "Ground", "Plasterboard", "Low sheen",
             50.0, "m²", "Measured", "Included", 2.0, 12.0, 8.0, 30.0, "High", "work", "2026-09-06", "2026-09-06")
        )
        cur.execute(
            """INSERT INTO takeoff_rows (id, workspace_id, section, element, location, substrate, finish_system,
               quantity, unit, quantity_status, inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour,
               rate_per_unit, confidence, row_role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (4, 1, "Internal walls", "Inf Rate Row", "Ground", "Plasterboard", "Low sheen",
             20.0, "m²", "Measured", "Included", 2.0, 12.0, 8.0, float("inf"), "High", "work", "2026-09-06", "2026-09-06")
        )
        conn.commit()
        conn.close()
        return db_path

    def test_dataframe_for_takeoff_sanitization(self, setup_takeoff_db: str) -> None:
        db_path = setup_takeoff_db
        orig_ldf = app.ldf
        orig_lquery = app.lquery
        orig_conn = app.local_connect

        def _conn() -> sqlite3.Connection:
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        app.local_connect = _conn
        app.ldf = lambda sql, params=(): pd.read_sql_query(sql, _conn(), params=params)
        app.lquery = lambda sql, params=(): [dict(r) for r in _conn().execute(sql, params).fetchall()]
        try:
            df = dataframe_for_takeoff(1)
            # All quantities must be finite float64
            assert pd.api.types.is_float_dtype(df["quantity"])
            assert all(math.isfinite(q) for q in df["quantity"])
            assert all(math.isfinite(r) for r in df["rate_per_unit"])
            assert all(math.isfinite(p) for p in df["paint_litres"])
            assert all(math.isfinite(h) for h in df["labour_hours"])
            assert all(math.isfinite(v) for v in df["value_ex_gst"])

            # Verify invalid strings/infs converted to 0.0
            # Row 1 had 'NaN' string -> 0.0
            assert df.loc[df["id"] == 1, "quantity"].values[0] == 0.0
            # Row 2 had float('inf') -> 0.0
            assert df.loc[df["id"] == 2, "quantity"].values[0] == 0.0
            # Row 3 had 50.0 -> 50.0, rate 30.0 -> value 1500.0
            assert df.loc[df["id"] == 3, "quantity"].values[0] == 50.0
            assert df.loc[df["id"] == 3, "value_ex_gst"].values[0] == 1500.0
            # Row 4 had rate inf -> rate 0.0, value 0.0
            assert df.loc[df["id"] == 4, "rate_per_unit"].values[0] == 0.0
            assert df.loc[df["id"] == 4, "value_ex_gst"].values[0] == 0.0
        finally:
            app.ldf = orig_ldf
            app.lquery = orig_lquery
            app.local_connect = orig_conn

    def test_per_level_summary_and_quotes_no_crash(self, setup_takeoff_db: str) -> None:
        db_path = setup_takeoff_db
        orig_ldf = app.ldf
        orig_lquery = app.lquery
        orig_conn = app.local_connect

        def _conn() -> sqlite3.Connection:
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        app.local_connect = _conn
        app.ldf = lambda sql, params=(): pd.read_sql_query(sql, _conn(), params=params)
        app.lquery = lambda sql, params=(): [dict(r) for r in _conn().execute(sql, params).fetchall()]
        try:
            # per_level_summary must calculate without TypeError string concatenation
            pls = per_level_summary(1)
            assert not pls.empty
            assert all(math.isfinite(v) for v in pls["m2"])
            assert all(math.isfinite(v) for v in pls["value_ex_gst"])
            # Ground level total m2 should be 70.0 (rows 1,2 were 0.0; row 3 was 50.0; row 4 was 20.0; total = 70.0)
            assert math.isclose(pls.loc[pls["level"] == "Ground", "m2"].values[0], 70.0)

            # quote_summary_frame
            qsf = quote_summary_frame(1)
            assert not qsf.empty
            assert all(math.isfinite(v) for v in qsf["markup_ex_gst"])
            assert all(math.isfinite(v) for v in qsf["gst"])
            assert all(math.isfinite(v) for v in qsf["total_inc_gst"])

            # quote_workbook_bytes
            wb_b = quote_workbook_bytes(1)
            assert isinstance(wb_b, bytes)
            assert len(wb_b) > 0

            # quote_pdf_bytes
            pdf_b = quote_pdf_bytes(1)
            assert isinstance(pdf_b, bytes)
            assert len(pdf_b) > 0
            # Ensure "$nan" or "$inf" string does not appear in the PDF
            assert b"$nan" not in pdf_b.lower()
            assert b"$inf" not in pdf_b.lower()
        finally:
            app.ldf = orig_ldf
            app.lquery = orig_lquery
            app.local_connect = orig_conn

    def test_progress_package_manifest_rfc8259(self, setup_takeoff_db: str) -> None:
        db_path = setup_takeoff_db
        orig_ldf = app.ldf
        orig_lquery = app.lquery
        orig_conn = app.local_connect

        def _conn() -> sqlite3.Connection:
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        app.local_connect = _conn
        app.ldf = lambda sql, params=(): pd.read_sql_query(sql, _conn(), params=params)
        app.lquery = lambda sql, params=(): [dict(r) for r in _conn().execute(sql, params).fetchall()]
        try:
            pkg_bytes = progress_package_bytes(1)
            zf = zipfile.ZipFile(io.BytesIO(pkg_bytes))

            # Validate package_manifest.json under strict RFC 8259 parser
            manifest_raw = zf.read("package_manifest.json").decode("utf-8")
            manifest = _strict_rfc8259_loads(manifest_raw)

            totals = manifest["totals"]
            for v in totals.values():
                assert isinstance(v, (int, float))
                assert math.isfinite(v)
                assert not math.isnan(v)
                assert not math.isinf(v)

            # Validate 3d/building_geometry.json under strict RFC 8259 parser
            geom_raw = zf.read("3d/building_geometry.json").decode("utf-8")
            geom = _strict_rfc8259_loads(geom_raw)
            assert isinstance(geom, dict)
        finally:
            app.ldf = orig_ldf
            app.lquery = orig_lquery
            app.local_connect = orig_conn


class TestJobHubExportNumericSafety:
    """Tests that JobHub sync and push functions strictly enforce finite float payloads."""

    def test_sync_jobhub_takeoff_rows_sanitizes_values(self) -> None:
        # Create a DataFrame with corrupt/inf quantities
        corrupt_df = pd.DataFrame([{
            "id": 1,
            "section": "Internal walls",
            "element": "Walls",
            "location": "Ground",
            "substrate": "Plasterboard",
            "quantity": float("inf"),
            "unit": "m²",
            "coats": float("nan"),
            "rate_per_unit": "$1,250.00",
            "labour_hours": float("inf"),
            "paint_litres": float("nan"),
            "value_ex_gst": float("inf"),
            "inclusion_status": "Included",
            "row_role": "work",
            "quantity_status": "Measured",
        }])
        mock_bridge = MagicMock()
        mock_bridge.kind = "sqlite"

        synced = _sync_jobhub_takeoff_rows(mock_bridge, 101, corrupt_df)
        assert synced == 1
        assert mock_bridge.execute.called

        # Extract payload passed to bridge.execute
        args, _ = mock_bridge.execute.call_args
        payload = args[1]
        # Payload layout: job_id, internal_external, area_location, substrate, labour_category,
        # qty_m2, lineal_m, count, coats, rate_ex_gst, labour_hours, paint_litres, value_ex_gst, ...
        qty_m2 = payload[5]
        coats = payload[8]
        rate_ex_gst = payload[9]
        labour_hours_val = payload[10]
        paint_litres_val = payload[11]
        value_ex_gst = payload[12]

        assert qty_m2 == 0.0
        assert math.isfinite(qty_m2)
        assert coats == 1.0  # fallback default
        assert rate_ex_gst == 1250.0
        assert labour_hours_val == 0.0
        assert paint_litres_val == 0.0
        assert value_ex_gst == 0.0


class TestFingerprintsAndHashesRfc8259Compliance:
    """Tests that model authority, preflight, and sign-off fingerprints adhere to RFC 8259."""

    def test_model_surface_fingerprint_rfc8259(self) -> None:
        row = {
            "id": 10,
            "workspace_id": 1,
            "section": "External",
            "element": "Cladding",
            "location": "North",
            "substrate": "Concrete",
            "finish_system": "Texture",
            "quantity": 100.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "coats": 2.0,
            "rate_per_unit": 35.0,
            "labour_hours": 10.0,
            "paint_litres": 16.67,
            "value_ex_gst": 3500.0,
            "row_role": "work",
            "inclusion_status": "included",
            "source_reference": "Mass-1:North",
        }
        fp = compute_model_surface_authority_fingerprint(row)
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_commercial_signature_rejects_non_finite_totals(self) -> None:
        with pytest.raises(ValueError, match="[Nn]on-finite"):
            compute_commercial_signature(1, float("nan"), 10.0, 5.0, "fp123")

        with pytest.raises(ValueError, match="[Nn]on-finite"):
            compute_commercial_signature(1, 1000.0, float("inf"), 5.0, "fp123")

        with pytest.raises(ValueError, match="[Nn]on-finite"):
            compute_commercial_signature(1, 1000.0, 10.0, float("-inf"), "fp123")

        sig = compute_commercial_signature(1, 1000.0, 50.0, 20.0, "fp123")
        assert isinstance(sig, str)
        assert len(sig) == 64
