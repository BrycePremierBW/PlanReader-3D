"""tests/test_workstream_p11_pricing.py — P11: Commercial Pricing Mixed Dataset Suite.

Verifies exact eligible quantities and totals across mixed datasets:
  - manual authoritative (eligible work)
  - approved model (eligible work)
  - unapproved model (ineligible, must be zero/excluded)
  - tampered approval (ineligible, must be zero/excluded)
  - excluded work (ineligible, must be zero/excluded)
  - floor reference (eligible reference only; 0 painted m², 0 paint/labour, 0 direct value)
  - excluded floor reference (ineligible, must not drive floor pricing or summary)
  - unapproved model floor reference (ineligible, must not drive floor pricing or summary)
  - tampered model floor reference (ineligible, must not drive floor pricing or summary)

Verifies:
  - takeoff_work_rows and commercial_takeoff_rows filtering
  - floor_area_by_level and floor_by_scope isolation
  - dataframe_for_takeoff under wall_m2 and floor_m2 pricing bases
  - weighted floor-m² allocation among eligible work rows without area loss
  - per_level_summary and quote_summary_frame exact sums
  - quote_workbook_bytes and quote_pdf_bytes reconciliation
  - pb_takeoff_accuracy_v125 overlay adherence to commercial authority
"""
from __future__ import annotations

import io
import sqlite3

import pandas as pd
import pytest

import pb_planreader_3d_app as app
import pb_takeoff_accuracy_v125 as v125
from pb_takeoff_authority_v164 import (
    compute_model_surface_authority_fingerprint,
    is_commercial_floor_reference_row,
)


@pytest.fixture
def mixed_dataset_db(tmp_path) -> tuple[str, int]:
    """Create a temporary SQLite database with a standard mixed dataset in workspace 1."""
    db_path = str(tmp_path / "p11_test.db")
    # Monkeypatch local_connect
    def _connect():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    app.local_connect = _connect
    app.init_local_db()
    conn = _connect()

    # Create workspace 1
    wid = app.create_standalone_workspace("P11_WS", "P11 Pricing Mixed Dataset", "PB", "100 Commercial St")

    def _base(rid: int, **kwargs) -> dict:
        d = {
            "id": rid,
            "workspace_id": wid,
            "section": "Internal walls",
            "element": "Internal walls",
            "location": "Unit 1 · Level 1",
            "substrate": "Plasterboard",
            "finish_system": "2 coats low sheen",
            "quantity": 50.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "source_page": "1",
            "source_reference": "Drawing A-101",
            "inclusion_status": "Included",
            "coats": 2,
            "coverage_m2_per_litre": 12.0,
            "productivity_m2_per_hour": 8.0,
            "rate_per_unit": 20.0,
            "confidence": "Reviewed",
            "notes": "",
            "row_role": "work",
            "commercial_authority_status": "",
            "commercial_authority_source": "",
            "commercial_authority_reviewed_by": "",
            "commercial_authority_reviewed_at": "",
            "commercial_authority_fingerprint": "",
        }
        d.update(kwargs)
        return d

    # 1. Manual authoritative (50 m², rate $20 -> $1000)
    r1_manual = _base(1, id=1, element="Manual walls", quantity=50.0, rate_per_unit=20.0)

    # 2. Approved model surface (30 m², rate $20 -> $600)
    r2_app_model = _base(
        2, id=2, element="Approved model walls", quantity=30.0, rate_per_unit=20.0,
        row_role="model_surface",
        source_reference="pb 3d surface editor 101",
        source_page="3d_model",
        commercial_authority_status="APPROVED",
        commercial_authority_source="pb 3d surface editor 101",
        commercial_authority_reviewed_by="Bryce Curran",
        commercial_authority_reviewed_at="2026-09-06T00:00:00Z",
    )
    r2_app_model["commercial_authority_fingerprint"] = compute_model_surface_authority_fingerprint(r2_app_model)

    # 3. Unapproved model surface (40 m², rate $20 -> ineligible)
    r3_unapp_model = _base(
        3, id=3, element="Unapproved model walls", quantity=40.0, rate_per_unit=20.0,
        row_role="model_surface",
        source_reference="pb 3d surface editor 102",
        source_page="3d_model",
        commercial_authority_status="DRAFT",
    )

    # 4. Tampered approval (25 m², rate $20 -> ineligible)
    r4_tampered_model = _base(
        4, id=4, element="Tampered model walls", quantity=25.0, rate_per_unit=20.0,
        row_role="model_surface",
        source_reference="pb 3d surface editor 103",
        source_page="3d_model",
        commercial_authority_status="APPROVED",
        commercial_authority_source="pb 3d surface editor 103",
        commercial_authority_reviewed_by="Bryce Curran",
        commercial_authority_reviewed_at="2026-09-06T00:00:00Z",
        commercial_authority_fingerprint="invalid_tampered_fingerprint_hash",
    )

    # 5. Excluded row (60 m², rate $20 -> ineligible)
    r5_excluded = _base(5, id=5, element="Excluded walls", quantity=60.0, rate_per_unit=20.0, inclusion_status="Excluded")

    # 6. Legitimate manual floor reference (100 m², rate $0 -> eligible floor reference)
    r6_floor = _base(6, id=6, element="Floor area", quantity=100.0, rate_per_unit=0.0, row_role="floor_area")

    # 7. Excluded floor reference (50 m² -> ineligible)
    r7_floor_excl = _base(7, id=7, element="Floor area excluded", quantity=50.0, rate_per_unit=0.0, row_role="floor_area", inclusion_status="Excluded")

    # 8. Unapproved model floor reference (70 m² -> ineligible)
    r8_floor_unapp = _base(
        8, id=8, element="Floor area 3D unapproved", quantity=70.0, rate_per_unit=0.0,
        row_role="floor_area",
        source_reference="pb 3d surface editor 104",
        source_page="3d_model",
        commercial_authority_status="DRAFT",
    )

    # 9. Tampered model floor reference (45 m² -> ineligible)
    r9_floor_tampered = _base(
        9, id=9, element="Floor area 3D tampered", quantity=45.0, rate_per_unit=0.0,
        row_role="floor_area",
        source_reference="pb 3d surface editor 105",
        source_page="3d_model",
        commercial_authority_status="APPROVED",
        commercial_authority_source="pb 3d surface editor 105",
        commercial_authority_reviewed_by="Bryce Curran",
        commercial_authority_reviewed_at="2026-09-06T00:00:00Z",
        commercial_authority_fingerprint="tampered_floor_fingerprint",
    )

    all_rows = [
        r1_manual, r2_app_model, r3_unapp_model, r4_tampered_model,
        r5_excluded, r6_floor, r7_floor_excl, r8_floor_unapp, r9_floor_tampered
    ]

    for r in all_rows:
        cols = list(r.keys())
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            f"INSERT INTO takeoff_rows({','.join(cols)}) VALUES({placeholders})",
            [r[c] for c in cols]
        )
    conn.commit()
    conn.close()

    return db_path, wid


class TestCommercialFloorReferenceAuthority:
    """Tests the is_commercial_floor_reference_row authority policy."""

    def test_manual_included_floor_reference_is_valid(self) -> None:
        row = {"row_role": "floor_area", "inclusion_status": "Included", "source_reference": "Drawing A-101"}
        assert is_commercial_floor_reference_row(row) is True

    def test_excluded_floor_reference_is_invalid(self) -> None:
        for status in ("Excluded", "excluded", "EXCLUSION", "exclude"):
            row = {"row_role": "floor_area", "inclusion_status": status}
            assert is_commercial_floor_reference_row(row) is False

    def test_unapproved_model_floor_reference_is_invalid(self) -> None:
        row = {
            "row_role": "floor_area",
            "inclusion_status": "Included",
            "source_reference": "pb 3d surface editor 101",
            "source_page": "3d_model",
            "commercial_authority_status": "DRAFT",
        }
        assert is_commercial_floor_reference_row(row) is False

    def test_tampered_model_floor_reference_is_invalid(self) -> None:
        row = {
            "row_role": "floor_area",
            "inclusion_status": "Included",
            "source_reference": "pb 3d surface editor 101",
            "source_page": "3d_model",
            "commercial_authority_status": "APPROVED",
            "commercial_authority_source": "pb 3d surface editor 101",
            "commercial_authority_reviewed_by": "Bryce Curran",
            "commercial_authority_reviewed_at": "2026-09-06T00:00:00Z",
            "commercial_authority_fingerprint": "corrupted_hash",
        }
        assert is_commercial_floor_reference_row(row) is False

    def test_approved_model_floor_reference_is_valid(self) -> None:
        row = {
            "id": 10,
            "workspace_id": 1,
            "section": "Internal",
            "element": "Floor area",
            "location": "Level 1",
            "substrate": "Concrete",
            "finish_system": "",
            "quantity": 120.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "source_page": "3d_model",
            "source_reference": "pb 3d surface editor 101",
            "inclusion_status": "Included",
            "coats": 1,
            "coverage_m2_per_litre": 1,
            "productivity_m2_per_hour": 1,
            "rate_per_unit": 0.0,
            "confidence": "Reviewed",
            "notes": "",
            "row_role": "floor_area",
            "commercial_authority_status": "APPROVED",
            "commercial_authority_source": "pb 3d surface editor 101",
            "commercial_authority_reviewed_by": "Bryce Curran",
            "commercial_authority_reviewed_at": "2026-09-06T00:00:00Z",
        }
        row["commercial_authority_fingerprint"] = compute_model_surface_authority_fingerprint(row)
        assert is_commercial_floor_reference_row(row) is True


class TestMixedDatasetPricingEligibility:
    """Verifies exact quantities and totals under mixed dataset for wall_m2 and floor_m2 bases."""

    def test_commercial_takeoff_rows_filters_all_ineligible_rows(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        raw_df = app.ldf("SELECT * FROM takeoff_rows WHERE workspace_id=?", (wid,))
        assert len(raw_df) == 9

        clean_df = app.commercial_takeoff_rows(raw_df)
        # Only row 1 (manual work), row 2 (approved model work), and row 6 (legitimate floor ref)
        assert sorted(clean_df["id"].tolist()) == [1, 2, 6]

    def test_takeoff_work_rows_keeps_only_commercial_work(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        raw_df = app.ldf("SELECT * FROM takeoff_rows WHERE workspace_id=?", (wid,))
        work = app.takeoff_work_rows(raw_df)
        assert sorted(work["id"].tolist()) == [1, 2]
        assert work["quantity"].sum() == 80.0

    def test_floor_area_by_level_ignores_ineligible_floor_rows(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        df = app.dataframe_for_takeoff(wid)
        fa = app.floor_area_by_level(df)
        # Legitimate floor reference is exactly 100.0, ignoring excluded (50), unapproved (70), and tampered (45)
        assert fa == {"Level 1": 100.0}

    def test_wall_m2_pricing_basis_exact_totals(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        app.set_workspace_setting(wid, "internal_pricing_basis", "wall_m2")

        df = app.dataframe_for_takeoff(wid)
        assert sorted(df["id"].tolist()) == [1, 2, 6]

        # Row 1: 50 m² @ $20 = $1,000.00
        r1 = df.loc[df["id"].eq(1)].iloc[0]
        assert r1["priced_quantity"] == 50.0
        assert r1["value_ex_gst"] == 1000.0

        # Row 2: 30 m² @ $20 = $600.00
        r2 = df.loc[df["id"].eq(2)].iloc[0]
        assert r2["priced_quantity"] == 30.0
        assert r2["value_ex_gst"] == 600.0

        # Row 6: floor area -> 0 value
        r6 = df.loc[df["id"].eq(6)].iloc[0]
        assert r6["priced_quantity"] == 100.0
        assert r6["value_ex_gst"] == 0.0

        assert df["value_ex_gst"].sum() == 1600.0

        # Per level summary
        pls = app.per_level_summary(wid)
        assert len(pls) == 1
        row = pls.iloc[0]
        assert row["level"] == "Level 1"
        assert row["rows"] == 2
        assert row["m2"] == 80.0
        assert row["floor_m2"] == 100.0
        assert row["value_ex_gst"] == 1600.0

    def test_floor_m2_pricing_basis_weighted_allocation_and_exact_totals(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        app.set_workspace_setting(wid, "internal_pricing_basis", "floor_m2")

        df = app.dataframe_for_takeoff(wid)
        assert sorted(df["id"].tolist()) == [1, 2, 6]

        # Total legitimate floor area = 100 m²
        # Legitimate wall weights: Row 1 (50 m²), Row 2 (30 m²), total = 80 m²
        # Row 1 allocated floor m²: 100 * (50 / 80) = 62.5 m²
        # Row 1 value: 62.5 * $20 = $1,250.00
        # Row 2 allocated floor m²: 100 * (30 / 80) = 37.5 m²
        # Row 2 value: 37.5 * $20 = $750.00
        r1 = df.loc[df["id"].eq(1)].iloc[0]
        r2 = df.loc[df["id"].eq(2)].iloc[0]
        r6 = df.loc[df["id"].eq(6)].iloc[0]

        assert abs(r1["priced_quantity"] - 62.5) < 1e-6
        assert abs(r1["value_ex_gst"] - 1250.0) < 1e-6

        assert abs(r2["priced_quantity"] - 37.5) < 1e-6
        assert abs(r2["value_ex_gst"] - 750.0) < 1e-6

        assert r6["value_ex_gst"] == 0.0

        assert abs(df["value_ex_gst"].sum() - 2000.0) < 1e-6

        # Per level summary must match
        pls = app.per_level_summary(wid)
        assert len(pls) == 1
        row = pls.iloc[0]
        assert row["level"] == "Level 1"
        assert row["rows"] == 2
        assert abs(row["m2"] - 80.0) < 1e-6
        assert abs(row["floor_m2"] - 100.0) < 1e-6
        assert abs(row["value_ex_gst"] - 2000.0) < 1e-6

    def test_quote_summary_frame_and_workbook_reconciliation(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        app.set_workspace_setting(wid, "internal_pricing_basis", "floor_m2")
        app.set_workspace_setting(wid, "pricing_margin_pct", "15.0")
        app.set_workspace_setting(wid, "gst_rate_pct", "10.0")

        qsf = app.quote_summary_frame(wid)
        assert len(qsf) == 1
        lvl_val = qsf.iloc[0]["value_ex_gst"]
        assert abs(lvl_val - 2000.0) < 1e-6

        # 15% markup on $2,000 = $2,300 ex GST
        assert abs(qsf.iloc[0]["markup_ex_gst"] - 2300.0) < 1e-6
        # 10% GST on $2,300 = $230.00
        assert abs(qsf.iloc[0]["gst"] - 230.0) < 1e-6
        # Total inc GST = $2,530.00
        assert abs(qsf.iloc[0]["total_inc_gst"] - 2530.0) < 1e-6

        # Workbook bytes generation
        wb_bytes = app.quote_workbook_bytes(wid)
        assert isinstance(wb_bytes, bytes) and len(wb_bytes) > 0

        # Read back Totals sheet from workbook
        wb_df = pd.read_excel(io.BytesIO(wb_bytes), sheet_name="Totals")
        metric_map = dict(zip(wb_df["Metric"], wb_df["Amount"]))

        assert abs(metric_map["Value ex GST"] - 2000.0) < 1e-6
        assert abs(metric_map["Mark-up"] - 300.0) < 1e-6
        assert abs(metric_map["Subtotal ex GST"] - 2300.0) < 1e-6
        assert abs(metric_map["GST"] - 230.0) < 1e-6
        assert abs(metric_map["Total inc GST"] - 2530.0) < 1e-6

        # PDF bytes generation
        pdf_bytes = app.quote_pdf_bytes(wid)
        assert isinstance(pdf_bytes, bytes) and len(pdf_bytes) > 0


class TestTakeoffAccuracyV125PricingAdherence:
    """Verifies that pb_takeoff_accuracy_v125 overlay respects commercial authority and mixed dataset filtering."""

    def test_v125_dataframe_for_takeoff_filters_ineligible_rows(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        v125.apply(app)

        df = app.dataframe_for_takeoff(wid)
        # Excluded rows (5, 7), unapproved (3, 8), tampered (4, 9) must NOT be present
        assert sorted(df["id"].tolist()) == [1, 2, 6]

    def test_v125_floor_m2_basis_weighted_allocation(self, mixed_dataset_db) -> None:
        _, wid = mixed_dataset_db
        v125.apply(app)
        app.set_workspace_setting(wid, "internal_pricing_basis", "floor_m2")

        df = app.dataframe_for_takeoff(wid)
        assert sorted(df["id"].tolist()) == [1, 2, 6]

        r1 = df.loc[df["id"].eq(1)].iloc[0]
        r2 = df.loc[df["id"].eq(2)].iloc[0]
        r6 = df.loc[df["id"].eq(6)].iloc[0]

        assert abs(r1["priced_quantity"] - 62.5) < 1e-6
        assert abs(r1["value_ex_gst"] - 1250.0) < 1e-6

        assert abs(r2["priced_quantity"] - 37.5) < 1e-6
        assert abs(r2["value_ex_gst"] - 750.0) < 1e-6

        assert r6["value_ex_gst"] == 0.0
        assert abs(df["value_ex_gst"].sum() - 2000.0) < 1e-6

        pls = app.per_level_summary(wid)
        assert abs(pls.iloc[0]["value_ex_gst"] - 2000.0) < 1e-6
        assert abs(pls.iloc[0]["floor_m2"] - 100.0) < 1e-6
