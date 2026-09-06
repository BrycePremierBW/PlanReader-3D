"""Focused A9 regressions for unresolved scope in pricing and quote outputs."""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock

import openpyxl
import pandas as pd
import pytest

import pb_planreader_3d_app as app
import pb_commercial_review_v161 as review
import pb_commercial_export_preflight_v163 as preflight
from pb_takeoff_authority_v164 import (
    approve_model_surface_row,
    compute_model_surface_authority_fingerprint,
    is_commercial_floor_reference_row,
    is_jobhub_eligible_row,
    model_surface_authority,
    takeoff_row_pricing_authority,
    takeoff_row_publishability,
    takeoff_row_scope_authority,
)


@pytest.fixture
def scope_pricing_workspace(tmp_path, monkeypatch) -> int:
    db_path = str(tmp_path / "a9_scope_pricing.db")

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(app, "local_connect", _connect)
    app.init_local_db()
    workspace_id = app.create_standalone_workspace(
        "A9-SCOPE", "A9 scope pricing", "PB", "100 Commercial St"
    )

    base = {
        "workspace_id": workspace_id,
        "section": "Internal",
        "element": "Walls",
        "location": "Level 1",
        "substrate": "Plasterboard",
        "finish_system": "Low sheen acrylic",
        "unit": "m²",
        "source_page": "A-101",
        "source_reference": "Drawing A-101",
        "coats": 2,
        "coverage_m2_per_litre": 10.0,
        "productivity_m2_per_hour": 5.0,
        "rate_per_unit": 10.0,
        "confidence": "Reviewed",
        "notes": "",
        "row_role": "work",
    }
    rows = [
        {**base, "id": 1, "quantity": 10.0, "quantity_status": "Measured", "inclusion_status": "INCLUSION"},
        {**base, "id": 2, "quantity": 20.0, "quantity_status": "Measured", "inclusion_status": "EXCLUSION"},
        {**base, "id": 3, "quantity": 30.0, "quantity_status": "Measured", "inclusion_status": "CLARIFICATION"},
        {**base, "id": 4, "quantity": 40.0, "quantity_status": "Measured", "inclusion_status": "PROVISIONAL"},
        {**base, "id": 5, "quantity": 50.0, "quantity_status": "Provisional measured", "inclusion_status": "INCLUSION"},
        {**base, "id": 6, "quantity": 60.0, "quantity_status": "To measure", "inclusion_status": "INCLUSION"},
        {**base, "id": 7, "quantity": 70.0, "quantity_status": "Excluded", "inclusion_status": "INCLUSION"},
        {**base, "id": 8, "element": "Floor area", "quantity": 10.0, "quantity_status": "Measured", "inclusion_status": "INCLUSION", "rate_per_unit": 0.0, "row_role": "floor_area"},
        {**base, "id": 9, "element": "Floor area", "quantity": 900.0, "quantity_status": "Measured", "inclusion_status": "PROVISIONAL", "rate_per_unit": 0.0, "row_role": "floor_area"},
    ]

    with _connect() as conn:
        for row in rows:
            columns = list(row)
            conn.execute(
                f"INSERT INTO takeoff_rows({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                [row[column] for column in columns],
            )

    app.set_workspace_setting(workspace_id, "internal_pricing_basis", "floor_m2")
    return workspace_id


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ({"quantity": 30.0, "quantity_status": "Measured", "inclusion_status": "CLARIFICATION"}, "CLARIFICATION"),
        ({"quantity": 40.0, "quantity_status": "Measured", "inclusion_status": "PROVISIONAL"}, "PROVISIONAL"),
        ({"quantity": 50.0, "quantity_status": "Provisional measured", "inclusion_status": "INCLUSION"}, "PROVISIONAL"),
        ({"quantity": 60.0, "quantity_status": "To measure", "inclusion_status": "INCLUSION"}, "PROVISIONAL"),
        ({"quantity": 70.0, "quantity_status": "Excluded", "inclusion_status": "INCLUSION"}, "EXCLUDED"),
        # P29 hostile scope variants
        ({"quantity": 25.0, "quantity_status": "Measured", "inclusion_status": "SEPARATE ITEM"}, "PROVISIONAL"),
        ({"quantity": 35.0, "quantity_status": "Measured", "inclusion_status": "OPTIONAL"}, "PROVISIONAL"),
        ({"quantity": 45.0, "quantity_status": "Measured", "inclusion_status": "TBD"}, "PROVISIONAL"),
        ({"quantity": 55.0, "quantity_status": "Measured", "inclusion_status": "PENDING"}, "PROVISIONAL"),
        ({"quantity": 65.0, "quantity_status": "Measured", "inclusion_status": "VARIATION"}, "PROVISIONAL"),
        ({"quantity": 75.0, "quantity_status": "Measured", "inclusion_status": "CLIENT_VARIATION"}, "PROVISIONAL"),
        ({"quantity": 85.0, "quantity_status": "Measured", "inclusion_status": "UNCONFIRMED"}, "PROVISIONAL"),
        ({"quantity": 15.0, "quantity_status": "Measured", "inclusion_status": "RFI"}, "CLARIFICATION"),
        ({"quantity": 20.0, "quantity_status": "Measured", "inclusion_status": "QUERY"}, "CLARIFICATION"),
        ({"quantity": 30.0, "quantity_status": "Measured", "inclusion_status": "TO_CLARIFY"}, "CLARIFICATION"),
        ({"quantity": 40.0, "quantity_status": "Measured", "inclusion_status": "DISPUTED"}, "CLARIFICATION"),
        ({"quantity": 50.0, "quantity_status": "Measured", "inclusion_status": "FOOBAR"}, "UNRESOLVED_SCOPE"),
        ({"quantity": 60.0, "quantity_status": "Measured", "inclusion_status": True}, "UNRESOLVED_SCOPE"),
        ({"quantity": 70.0, "quantity_status": "Measured", "inclusion_status": False}, "UNRESOLVED_SCOPE"),
        ({"quantity": 80.0, "quantity_status": "Measured", "inclusion_status": "null"}, "UNRESOLVED_SCOPE"),
        ({"quantity": 90.0, "quantity_status": "Measured", "inclusion_status": "none"}, "UNRESOLVED_SCOPE"),
        ({"quantity": 10.0, "quantity_status": "Measured", "inclusion_status": "nan"}, "UNRESOLVED_SCOPE"),
        # Negative quantities / allowances
        ({"quantity": -50.0, "quantity_status": "Measured", "inclusion_status": "INCLUSION"}, "NEGATIVE_QUANTITY"),
        ({"quantity": -30.0, "quantity_status": "Allowance", "inclusion_status": "INCLUSION"}, "NEGATIVE_QUANTITY"),
    ],
)
def test_unresolved_scope_is_not_firm_pricing_or_active_work(row: dict, reason: str) -> None:
    assert takeoff_row_pricing_authority(row) == (False, reason)
    assert is_jobhub_eligible_row(row) == (False, reason)


@pytest.mark.parametrize(
    "row",
    [
        {"quantity": 30.0, "quantity_status": "Measured", "inclusion_status": "CLARIFICATION"},
        {"quantity": 40.0, "quantity_status": "Measured", "inclusion_status": "PROVISIONAL"},
        {"quantity": 50.0, "quantity_status": "Provisional measured", "inclusion_status": "INCLUSION"},
    ],
)
def test_unresolved_scope_remains_visible_to_preflight_review(row: dict) -> None:
    assert takeoff_row_publishability(row) == (True, "PUBLISHABLE")


def test_unresolved_scope_cannot_inflate_pricing_or_quote_totals(
    scope_pricing_workspace: int,
) -> None:
    workspace_id = scope_pricing_workspace
    raw = app.ldf(
        "SELECT * FROM takeoff_rows WHERE workspace_id=? ORDER BY id",
        (workspace_id,),
    )

    assert raw["quantity"].sum() == pytest.approx(1190.0)
    assert app.takeoff_work_rows(raw)["id"].tolist() == [1]

    priced = app.dataframe_for_takeoff(workspace_id)
    assert priced["id"].tolist() == [1, 8]
    assert priced.loc[priced["id"].eq(1), "priced_quantity"].item() == pytest.approx(10.0)
    assert priced.loc[priced["id"].eq(8), "value_ex_gst"].item() == 0.0
    assert priced["value_ex_gst"].sum() == pytest.approx(100.0)

    quote = app.quote_summary_frame(workspace_id)
    assert quote["value_ex_gst"].sum() == pytest.approx(100.0)

    workbook = openpyxl.load_workbook(
        io.BytesIO(app.quote_workbook_bytes(workspace_id)), data_only=True
    )
    totals = {
        row[0]: float(row[1])
        for row in workbook["Totals"].iter_rows(values_only=True)
        if row[0] not in (None, "Metric")
    }
    assert totals["Value ex GST"] == pytest.approx(100.0)
    detail = list(workbook["Take-off Detail"].iter_rows(values_only=True))
    id_index = detail[0].index("id")
    assert [row[id_index] for row in detail[1:]] == [1, 8]


def test_negative_quantities_and_floor_deductions_fail_closed() -> None:
    """Verify that negative quantities cannot deduct from floor areas or act as valid commercial scope."""
    # 1. Negative floor reference row is rejected
    neg_floor_row = {
        "id": 1,
        "row_role": "floor_area",
        "unit": "m²",
        "quantity": -30.0,
        "location": "Level 1",
        "inclusion_status": "INCLUSION",
        "quantity_status": "Measured",
    }
    assert is_commercial_floor_reference_row(neg_floor_row) is False

    # 2. floor_area_by_level ignores negative floor rows and does not deduct from legitimate floor area
    df = pd.DataFrame([
        {
            "id": 10,
            "row_role": "floor_area",
            "unit": "m²",
            "quantity": 100.0,
            "location": "Level 1",
            "inclusion_status": "INCLUSION",
            "quantity_status": "Measured",
        },
        neg_floor_row,
    ])
    assert app.floor_area_by_level(df) == {"Level 1": 100.0}

    # 3. Negative quantity rows emit BLOCKER review signal
    mock_app = MagicMock()
    mock_app.lquery.return_value = [
        {
            "id": 20,
            "element": "Deduction Wall",
            "row_role": "work",
            "quantity": -50.0,
            "unit": "m²",
            "quantity_status": "Measured",
            "inclusion_status": "INCLUSION",
        }
    ]
    signals = review.collect_commercial_review_signals(mock_app, {"id": 1}).signals
    blockers = [s for s in signals if s.severity == "BLOCKER"]
    assert len(blockers) >= 1
    assert any("negative" in r for s in blockers for r in s.reasons)


def test_mixed_scope_bundle_pricing_isolation(tmp_path, monkeypatch) -> None:
    """Verify that in a mixed-scope room bundle, only explicit firm inclusions enter pricing,
    while exclusions, clarifications, provisionals, separate items, and negative allowances are strictly isolated.
    """
    db_path = str(tmp_path / "mixed_scope_bundle.db")

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(app, "local_connect", _connect)
    app.init_local_db()
    workspace_id = app.create_standalone_workspace(
        "A9-BUNDLE", "Mixed Bundle Project", "PB", "200 Commercial Way"
    )

    base = {
        "workspace_id": workspace_id,
        "section": "Internal",
        "location": "Boardroom",
        "substrate": "Plasterboard",
        "finish_system": "Acrylic",
        "unit": "m²",
        "source_page": "A-101",
        "source_reference": "Drawing A-101",
        "coats": 2,
        "coverage_m2_per_litre": 12.0,
        "productivity_m2_per_hour": 8.0,
        "confidence": "Reviewed",
        "notes": "",
    }

    bundle_rows = [
        # 1. Firm Included Wall ($1,000)
        {**base, "id": 1, "element": "Base Wall Paint", "quantity": 20.0, "rate_per_unit": 50.0, "quantity_status": "Measured", "inclusion_status": "INCLUSION", "row_role": "work"},
        # 2. Excluded Feature Wall
        {**base, "id": 2, "element": "Excluded Feature Wall", "quantity": 10.0, "rate_per_unit": 60.0, "quantity_status": "Measured", "inclusion_status": "EXCLUSION", "row_role": "work"},
        # 3. Clarification Acoustic Ceiling
        {**base, "id": 3, "element": "Clarification Acoustic Ceiling", "quantity": 15.0, "rate_per_unit": 40.0, "quantity_status": "Measured", "inclusion_status": "CLARIFICATION", "row_role": "work"},
        # 4. Provisional Bulkhead Paint
        {**base, "id": 4, "element": "Provisional Bulkhead Paint", "quantity": 8.0, "rate_per_unit": 45.0, "quantity_status": "Measured", "inclusion_status": "PROVISIONAL", "row_role": "work"},
        # 5. Separate Item Door Framing
        {**base, "id": 5, "element": "Separate Item Door Framing", "quantity": 5.0, "rate_per_unit": 70.0, "quantity_status": "Measured", "inclusion_status": "SEPARATE ITEM", "row_role": "work"},
        # 6. RFI Acoustic Baffle
        {**base, "id": 6, "element": "RFI Acoustic Baffle", "quantity": 12.0, "rate_per_unit": 35.0, "quantity_status": "Measured", "inclusion_status": "RFI", "row_role": "work"},
        # 7. Negative Allowance
        {**base, "id": 7, "element": "Negative Deduction Allowance", "quantity": -10.0, "rate_per_unit": 20.0, "quantity_status": "Allowance", "inclusion_status": "INCLUSION", "row_role": "work"},
        # 8. Legitimate Floor Reference (100 m²)
        {**base, "id": 8, "element": "Floor Area Boardroom", "quantity": 100.0, "rate_per_unit": 0.0, "quantity_status": "Measured", "inclusion_status": "INCLUSION", "row_role": "floor_area"},
        # 9. Provisional Floor Reference (500 m²)
        {**base, "id": 9, "element": "Provisional Floor Area", "quantity": 500.0, "rate_per_unit": 0.0, "quantity_status": "Measured", "inclusion_status": "PROVISIONAL", "row_role": "floor_area"},
        # 10. Negative Floor Reference (-40 m²)
        {**base, "id": 10, "element": "Negative Void Floor", "quantity": -40.0, "rate_per_unit": 0.0, "quantity_status": "Measured", "inclusion_status": "INCLUSION", "row_role": "floor_area"},
    ]

    with _connect() as conn:
        for r in bundle_rows:
            cols = list(r)
            conn.execute(
                f"INSERT INTO takeoff_rows({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
                [r[c] for c in cols],
            )
        conn.commit()

    # 1. takeoff_work_rows only contains Row 1
    raw = app.ldf("SELECT * FROM takeoff_rows WHERE workspace_id=? ORDER BY id", (workspace_id,))
    work_rows = app.takeoff_work_rows(raw)
    assert work_rows["id"].tolist() == [1]

    # 2. dataframe_for_takeoff only prices Row 1 ($1,000) and includes legitimate floor reference Row 8 ($0)
    priced = app.dataframe_for_takeoff(workspace_id)
    assert priced["id"].tolist() == [1, 8]
    assert priced.loc[priced["id"].eq(1), "value_ex_gst"].item() == pytest.approx(1000.0)
    assert priced.loc[priced["id"].eq(8), "value_ex_gst"].item() == 0.0
    assert priced["value_ex_gst"].sum() == pytest.approx(1000.0)

    # 3. quote_summary_frame matches exactly $1,000
    quote = app.quote_summary_frame(workspace_id)
    assert quote["value_ex_gst"].sum() == pytest.approx(1000.0)

    # 4. quote_workbook_bytes matches exactly $1,000
    workbook = openpyxl.load_workbook(io.BytesIO(app.quote_workbook_bytes(workspace_id)), data_only=True)
    totals = {
        row[0]: float(row[1])
        for row in workbook["Totals"].iter_rows(values_only=True)
        if row[0] not in (None, "Metric")
    }
    assert totals["Value ex GST"] == pytest.approx(1000.0)

    # 5. JobHub takeoff CSV lines export ONLY row 1
    csv_lines = app._jobhub_takeoff_lines_csv({"id": workspace_id, "job_no": "A9-BUNDLE"}, raw)
    assert "Base Wall Paint" in csv_lines
    for excluded_elem in [
        "Excluded Feature Wall",
        "Clarification Acoustic Ceiling",
        "Provisional Bulkhead Paint",
        "Separate Item Door Framing",
        "RFI Acoustic Baffle",
        "Negative Deduction Allowance",
        "Floor Area Boardroom",
        "Provisional Floor Area",
        "Negative Void Floor",
    ]:
        assert excluded_elem not in csv_lines


def test_scope_boundary_transitions_and_tamper_invalidation() -> None:
    """Verify that transitioning scope across commercial boundaries preserves integrity and rejects tampering."""
    # 1. Unapproved 3D model surface row cannot gain authority by simply setting inclusion_status='INCLUSION'
    unapproved_model = {
        "id": 1, "workspace_id": 1, "element": "3D Wall", "quantity": 100.0, "unit": "m²",
        "rate_per_unit": 50.0, "row_role": "work", "source_page": "3d_model",
        "source_reference": "pb 3d surface editor · wall:1", "quantity_status": "Measured",
        "inclusion_status": "INCLUSION", "commercial_authority_status": "REVIEW_REQUIRED",
    }
    assert takeoff_row_pricing_authority(unapproved_model)[0] is False

    # 2. Approved model row with inclusion_status='INCLUSION'
    raw_approved = {
        "id": 2, "workspace_id": 1, "element": "Approved 3D Wall", "quantity": 150.0, "unit": "m²",
        "rate_per_unit": 60.0, "row_role": "work", "source_page": "3d_model",
        "source_reference": "pb 3d surface editor · wall:2", "quantity_status": "Measured",
        "inclusion_status": "INCLUSION", "coats": 2.0, "coverage_m2_per_litre": 12.0,
        "productivity_m2_per_hour": 8.0,
    }
    approved = approve_model_surface_row(raw_approved, source="pb 3d surface editor", reviewed_by="Bryce", reviewed_at="2026-09-06T12:00:00Z")
    assert takeoff_row_pricing_authority(approved)[0] is True

    # 3. Transitioning approved row to PROVISIONAL or SEPARATE ITEM blocks pricing
    prov_transition = dict(approved, inclusion_status="PROVISIONAL")
    pricing_ok, reason = takeoff_row_pricing_authority(prov_transition)
    assert pricing_ok is False
    assert reason in ("PROVISIONAL", "3D model surface approval no longer matches the current row")

    sep_transition = dict(approved, inclusion_status="SEPARATE ITEM")
    pricing_ok_sep, reason_sep = takeoff_row_pricing_authority(sep_transition)
    assert pricing_ok_sep is False
    assert reason_sep in ("PROVISIONAL", "3D model surface approval no longer matches the current row")

    # 4. Transitioning approved row to CLARIFICATION blocks pricing
    clar_transition = dict(approved, inclusion_status="CLARIFICATION")
    pricing_ok_clar, reason_clar = takeoff_row_pricing_authority(clar_transition)
    assert pricing_ok_clar is False
    assert reason_clar in ("CLARIFICATION", "3D model surface approval no longer matches the current row")


def test_unresolved_scope_blocks_final_publish_and_preflight(tmp_path, monkeypatch) -> None:
    """Verify that unresolved scope rows block export preflight QA gate and prevent publication."""
    db_path = str(tmp_path / "preflight_scope.db")

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(app, "local_connect", _connect)
    app.init_local_db()
    workspace_id = app.create_standalone_workspace(
        "A9-PREFLIGHT", "Preflight Scope Project", "PB", "300 Commercial Ave"
    )

    with _connect() as conn:
        conn.execute("UPDATE workspaces SET jobhub_job_id=901 WHERE id=?", (workspace_id,))
        conn.execute("INSERT INTO pages (id, workspace_id, document_id, page_no, page_label, px_per_m, scale_method, scale_verified) VALUES (10, ?, 1, 1, 'A-01', 100.0, 'KNOWN_CALIBRATED', 1)", (workspace_id,))
        conn.execute("INSERT INTO documents (id, workspace_id, file_name, path, page_count) VALUES (1, ?, 'A-01.pdf', 'path', 1)", (workspace_id,))
        conn.execute("INSERT INTO register_items (id, workspace_id, register_name, item_no, title, status) VALUES (1, ?, 'Drawings', 'A-01', 'Floor Plan', 'Current')", (workspace_id,))

        # Clean row
        conn.execute(
            "INSERT INTO takeoff_rows(workspace_id, element, quantity, unit, rate_per_unit, row_role, inclusion_status, quantity_status, source_page, source_reference) "
            "VALUES(?, 'Clean Wall', 100.0, 'm²', 50.0, 'work', 'INCLUSION', 'Measured', 'A-01', 'drawing')",
            (workspace_id,),
        )
        # Unresolved separate item row
        conn.execute(
            "INSERT INTO takeoff_rows(workspace_id, element, quantity, unit, rate_per_unit, row_role, inclusion_status, quantity_status, source_page, source_reference) "
            "VALUES(?, 'Separate Door', 10.0, 'm²', 60.0, 'work', 'SEPARATE ITEM', 'Measured', 'A-01', 'drawing')",
            (workspace_id,),
        )
        conn.commit()

    pf_res = preflight.derive_export_preflight(app, workspace_id, bridge_available=True)
    assert pf_res.final_publish_state == "BLOCKED"
    assert len(pf_res.warnings) >= 1

    jh_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    jh_path = jh_file.name
    jh_file.close()
    try:
        bridge = app.JobHubBridge(kind="sqlite", source=jh_path)
        with pytest.raises(RuntimeError, match=r"Final publish blocked by preflight QA gate"):
            preflight.verify_toctou_and_publish_jobhub(
                app, workspace_id, bridge, "Tester", pf_res.preflight_fingerprint, True, lambda w, b, u: {"published": True}
            )
    finally:
        if os.path.exists(jh_path):
            try:
                os.remove(jh_path)
            except OSError:
                pass

