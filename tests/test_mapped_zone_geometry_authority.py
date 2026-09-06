"""Regression tests for mapped-zone geometry authority.

Covers Queue Item 1:
- Preserving real polygon and compound geometry (L-shapes, stepped shapes, internal voids).
- Reproducing cases where L-shaped, stepped, or internally voided areas become rectangular bounding-box quantities marked Measured.
- Classifying approximations as Provisional/REVIEW so they cannot enter firm pricing.
- Permitting Measured only when an evidence-backed exact rectangle is proven.
- Testing L-shape, stepped shape, internal void, geometry mutation, and exact rectangle.
- Proving results through persistence, Review, pricing, JobHub, and final publication.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

import pb_planreader_3d_app as app
import pb_no_ai_takeoff_v1216 as no_ai
from pb_takeoff_authority_v164 import (
    compute_takeoff_row_fingerprint,
    is_commercial_floor_reference_row,
    is_jobhub_eligible_row,
    takeoff_row_pricing_authority,
    takeoff_row_publishability,
    takeoff_row_scope_authority,
    AUTHORITY_APPROVED,
    AUTHORITY_FINGERPRINT_FIELD,
    AUTHORITY_REVIEWED_AT_FIELD,
    AUTHORITY_REVIEWED_BY_FIELD,
    AUTHORITY_SOURCE_FIELD,
    AUTHORITY_STATUS_FIELD,
)
from pb_commercial_review_v161 import (
    CommercialReviewResult,
    collect_commercial_review_signals,
)
from pb_commercial_export_preflight_v163 import derive_export_preflight


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mapped_zone_workspace(tmp_path, monkeypatch):
    db_path = str(tmp_path / "mapped_zone_authority.db")

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(app, "local_connect", _connect)
    app.init_local_db()
    ws_id = app.create_standalone_workspace(
        "MZ-TEST", "Mapped Zone Authority Test", "PB", "100 Geometry Way"
    )
    # Create a calibrated page (px_per_m = 50.0, i.e. 50 px = 1 m)
    app.lexecute(
        """INSERT INTO documents(workspace_id, source_type, file_name, path, sha256)
           VALUES(?, 'upload', 'test.pdf', 'test.pdf', 'dummy_hash')""",
        (ws_id,),
    )
    doc_id = app.lquery("SELECT id FROM documents WHERE workspace_id=?", (ws_id,))[0]["id"]
    app.lexecute(
        """INSERT INTO pages(document_id, workspace_id, page_no, page_label, page_type, px_per_m, width_px, height_px, selected)
           VALUES(?, ?, 1, 'A-01', 'Floor plan', 50.0, 2000, 2000, 1)""",
        (doc_id, ws_id),
    )
    page_id = app.lquery("SELECT id FROM pages WHERE workspace_id=?", (ws_id,))[0]["id"]
    return {"workspace_id": ws_id, "page_id": page_id, "px_per_m": 50.0}


# L-shape: 10m x 10m with 6m x 6m cutout -> True area = 100 - 36 = 64 m2.
# Bounding box is 10m x 10m = 100 m2 (at 50 px/m -> 500px x 500px).
L_SHAPE_POINTS_M = [
    [0.0, 0.0],
    [10.0, 0.0],
    [10.0, 4.0],
    [4.0, 4.0],
    [4.0, 10.0],
    [0.0, 10.0],
]
L_SHAPE_POINTS_PX = [[p[0] * 50.0, p[1] * 50.0] for p in L_SHAPE_POINTS_M]

# Stepped shape: 8 points -> True area = 81 m2.
# Bounding box is 12m x 9m = 108 m2.
STEPPED_POINTS_M = [
    [0.0, 0.0],
    [12.0, 0.0],
    [12.0, 3.0],
    [9.0, 3.0],
    [9.0, 6.0],
    [6.0, 6.0],
    [6.0, 9.0],
    [0.0, 9.0],
]
STEPPED_POINTS_PX = [[p[0] * 50.0, p[1] * 50.0] for p in STEPPED_POINTS_M]

# Internally voided area: 10m x 10m outer (100 m2) with 4m x 4m internal courtyard void (16 m2).
# True area = 100 - 16 = 84 m2. Bounding box = 100 m2.
VOID_COMPOUND_M = {
    "outer": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
    "voids": [[[3.0, 3.0], [7.0, 3.0], [7.0, 7.0], [3.0, 7.0]]],
}
VOID_COMPOUND_PX = {
    "outer": [[p[0] * 50.0, p[1] * 50.0] for p in VOID_COMPOUND_M["outer"]],
    "voids": [[[p[0] * 50.0, p[1] * 50.0] for p in v] for v in VOID_COMPOUND_M["voids"]],
}

# Exact rectangle: 10m x 5m = 50 m2.
EXACT_RECT_POINTS_M = [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]
EXACT_RECT_POINTS_PX = [[p[0] * 50.0, p[1] * 50.0] for p in EXACT_RECT_POINTS_M]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_l_shaped_zone_preserves_real_polygon_and_quantity(mapped_zone_workspace):
    """An L-shaped mapped zone must preserve the 6-point polygon and true 64 m2 area,
    NOT collapse into a 100 m2 bounding box.
    """
    ws_id = mapped_zone_workspace["workspace_id"]
    page_id = mapped_zone_workspace["page_id"]

    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'L-Room', 'Floor plan', ?, 0, 0, 500, 500, 50.0, 2.7, 0,
                 'Concrete', 'Epoxy', 'Measured', 'test-l-shape', 'now')""",
        (ws_id, page_id, json.dumps(L_SHAPE_POINTS_PX)),
    )

    rows = no_ai.build_no_ai_rows(app, ws_id)
    assert len(rows) == 1
    row = rows[0]

    assert row["quantity"] == pytest.approx(64.0, abs=0.1), (
        f"L-shaped area must be 64 m2, but got {row['quantity']} m2 (bounding box was 100 m2)"
    )


def test_l_shaped_bounding_box_approximation_classified_as_provisional(mapped_zone_workspace):
    """If an L-shaped area only has a rectangular bounding-box approximation,
    it must be classified as Provisional/REVIEW so it cannot enter firm pricing.
    """
    ws_id = mapped_zone_workspace["workspace_id"]
    page_id = mapped_zone_workspace["page_id"]

    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'L-Room Approx', 'Ceiling area', ?, 0, 0, 500, 500, 50.0, 2.7, 100.0,
                 'Plasterboard', 'Ceiling paint', 'Measured', 'test-l-approx; shape=approximation', 'now')""",
        (ws_id, page_id, json.dumps([{"approximation": True, "bounding_box": [0, 0, 500, 500]}])),
    )

    rows = no_ai.build_no_ai_rows(app, ws_id)
    assert len(rows) == 1
    row = rows[0]

    # Must be classified as Provisional / To review
    assert "provisional" in row["quantity_status"].lower() or row["quantity_status"] in {"To review", "Provisional measured"}
    assert row["confidence"] in {"To review", "Provisional", "Derived"}
    # Must NOT be authorised for firm pricing
    pricing_auth, reason = takeoff_row_pricing_authority(row)
    assert not pricing_auth, f"Approximation must not enter firm pricing: reason={reason}"


def test_stepped_shape_zone_preserves_real_geometry_and_area(mapped_zone_workspace):
    """Stepped shape area (8 points, 81 m2) must preserve polygon and not become 108 m2 bounding box."""
    ws_id = mapped_zone_workspace["workspace_id"]
    page_id = mapped_zone_workspace["page_id"]

    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'Stepped-Footprint', 'Building footprint', ?, 0, 0, 600, 450, 50.0, 2.7, 0,
                 'Render', 'Exterior acrylic', 'Measured', 'test-stepped', 'now')""",
        (ws_id, page_id, json.dumps(STEPPED_POINTS_PX)),
    )

    rows = no_ai.build_no_ai_rows(app, ws_id)
    assert len(rows) == 1
    row = rows[0]

    assert row["quantity"] == pytest.approx(81.0, abs=0.1), (
        f"Stepped shape area must be 81 m2, but got {row['quantity']} m2 (bounding box was 108 m2)"
    )


def test_internally_voided_area_deducts_void_and_preserves_compound_geometry(mapped_zone_workspace):
    """Compound area with internal void (100 m2 outer - 16 m2 void = 84 m2 net) must deduct the void
    and preserve the compound geometry, NOT take 100 m2 bounding box.
    """
    ws_id = mapped_zone_workspace["workspace_id"]
    page_id = mapped_zone_workspace["page_id"]

    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'Courtyard Floor', 'Floor plan', ?, 0, 0, 500, 500, 50.0, 2.7, 0,
                 'Concrete', 'Sealer', 'Measured', 'test-void', 'now')""",
        (ws_id, page_id, json.dumps(VOID_COMPOUND_PX)),
    )

    rows = no_ai.build_no_ai_rows(app, ws_id)
    assert len(rows) == 1
    row = rows[0]

    assert row["quantity"] == pytest.approx(84.0, abs=0.1), (
        f"Internally voided area must be 84 m2, but got {row['quantity']} m2 (gross box was 100 m2)"
    )


def test_exact_rectangle_permitted_as_measured_and_firm_pricing(mapped_zone_workspace):
    """An evidence-backed exact rectangle (4 points, 90 deg corners, calibrated) is permitted
    as Measured and enters firm pricing.
    """
    ws_id = mapped_zone_workspace["workspace_id"]
    page_id = mapped_zone_workspace["page_id"]

    # 1. Test as a priced work element: Ceilings
    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'Office Ceilings', 'Ceiling area', ?, 0, 0, 500, 250, 50.0, 2.7, 50.0,
                 'Plasterboard', 'Flat ceiling acrylic', 'Measured', 'test-exact-rect-ceiling', 'now')""",
        (ws_id, page_id, json.dumps(EXACT_RECT_POINTS_PX)),
    )

    rows = no_ai.build_no_ai_rows(app, ws_id)
    assert len(rows) == 1
    row = rows[0]

    assert row["quantity"] == pytest.approx(50.0, abs=0.1)
    assert row["quantity_status"] == "Measured"
    assert row["confidence"] == "Measured"

    # Exact rectangle work row permitted in firm pricing
    pricing_auth, reason = takeoff_row_pricing_authority(row)
    assert pricing_auth, f"Proven exact rectangle work row must be authorised for pricing: {reason}"


def test_geometry_mutation_invalidates_stale_quantity_and_approval(mapped_zone_workspace):
    """Mutating the geometry of a mapped zone must update its quantity and invalidate any
    stale approval fingerprint.
    """
    ws_id = mapped_zone_workspace["workspace_id"]

    # Create approved exact rectangular row (work row role)
    row = {
        "workspace_id": ws_id,
        "section": "Internal",
        "element": "Ceilings",
        "location": "Room 1",
        "substrate": "Plasterboard",
        "finish_system": "Flat ceiling",
        "quantity": 50.0,
        "unit": "m²",
        "quantity_status": "Measured",
        "source_page": "A-01",
        "source_reference": "PB No-AI v1.2.16 · zone:1",
        "inclusion_status": "INCLUSION",
        "coats": 2,
        "coverage_m2_per_litre": 10.0,
        "productivity_m2_per_hour": 5.0,
        "rate_per_unit": 25.0,
        "confidence": "Measured",
        "notes": "Exact rectangle",
        "row_role": "work",
        AUTHORITY_SOURCE_FIELD: "model_surface",
        AUTHORITY_STATUS_FIELD: AUTHORITY_APPROVED,
        AUTHORITY_REVIEWED_BY_FIELD: "Estimator",
        AUTHORITY_REVIEWED_AT_FIELD: "2026-09-06T10:00:00Z",
    }
    row[AUTHORITY_FINGERPRINT_FIELD] = compute_takeoff_row_fingerprint(row)

    pub_ok, _ = takeoff_row_publishability(row)
    assert pub_ok

    # Mutate geometry: quantity changes from 50.0 to 64.0 (e.g. reshaped to L-shape)
    mutated_row = dict(row)
    mutated_row["quantity"] = 64.0
    mutated_row["notes"] = "Reshaped to L-shape"

    # Fingerprint mismatch must fail closed
    pub_mut, reason = takeoff_row_publishability(mutated_row)
    assert not pub_mut, "Mutated geometry must invalidate stale approval fingerprint"
    assert any(tok in reason.lower() for tok in ("fingerprint", "tampered", "no longer matches", "invalid", "approval"))


def test_full_pipeline_proof_persistence_review_pricing_jobhub_publish(mapped_zone_workspace):
    """End-to-end proof:
    - Proven exact rectangle reaches persistence, review (no blocker), firm pricing, JobHub, and final publish.
    - An unproven approximation or irregular bounding box is classified as Provisional/REVIEW:
      it persists as Provisional, creates a Review blocker, is excluded from firm pricing and JobHub,
      and blocks final publication.
    """
    ws_id = mapped_zone_workspace["workspace_id"]
    page_id = mapped_zone_workspace["page_id"]

    # 1. Insert proven exact rectangle zone (Ceiling area -> work row)
    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'Exact Office Ceilings', 'Ceiling area', ?, 0, 0, 500, 250, 50.0, 2.7, 50.0,
                 'Plasterboard', 'Flat acrylic', 'Measured', 'zone:exact-1', 'now')""",
        (ws_id, page_id, json.dumps(EXACT_RECT_POINTS_PX)),
    )

    # 2. Insert L-shaped zone approximated as bounding box
    app.lexecute(
        """INSERT INTO mapped_zones(
            workspace_id, page_id, name, view_type, polygon_json,
            x_px, y_px, w_px, h_px, px_per_m, wall_height_m, area_m2,
            substrate, finish_system, quantity_status, source_reference, created_at
        ) VALUES(?, ?, 'L-Corridor Approx', 'Ceiling area', ?, 0, 0, 500, 500, 50.0, 2.7, 100.0,
                 'Plasterboard', 'Acrylic', 'Measured', 'zone:l-approx-2; approx=1', 'now')""",
        (ws_id, page_id, json.dumps([{"approximation": True}])),
    )

    # Build takeoff rows
    rows = no_ai.build_no_ai_rows(app, ws_id)
    assert len(rows) == 2

    exact_row = next(r for r in rows if "Exact Office" in r["location"])
    approx_row = next(r for r in rows if "L-Corridor" in r["location"])

    # Verify exact row
    assert exact_row["quantity_status"] == "Measured"
    assert takeoff_row_pricing_authority(exact_row)[0] is True
    assert is_jobhub_eligible_row(exact_row)[0] is True

    # Verify approx row
    assert "provisional" in approx_row["quantity_status"].lower() or approx_row["quantity_status"] in {"To review", "Provisional measured"}
    assert takeoff_row_pricing_authority(approx_row)[0] is False
    assert is_jobhub_eligible_row(approx_row)[0] is False

    # Persist into DB takeoff_rows
    for r in rows:
        app.lexecute(
            """INSERT INTO takeoff_rows(
                workspace_id, section, element, location, substrate, finish_system,
                quantity, unit, quantity_status, source_page, source_reference,
                inclusion_status, coats, coverage_m2_per_litre, productivity_m2_per_hour,
                rate_per_unit, confidence, notes, row_role, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'now', 'now')""",
            (
                ws_id, r["section"], r["element"], r["location"], r["substrate"], r["finish_system"],
                r["quantity"], r["unit"], r["quantity_status"], r["source_page"], r["source_reference"],
                r["inclusion_status"], r["coats"], r["coverage_m2_per_litre"], r["productivity_m2_per_hour"],
                r["rate_per_unit"], r["confidence"], r["notes"], r["row_role"],
            ),
        )

    # Firm pricing DataFrame must ONLY include the exact row, NOT the approx row
    df = app.dataframe_for_takeoff(ws_id)
    assert not df.empty
    locations = list(df["location"])
    assert any("Exact Office" in loc for loc in locations)
    assert not any("L-Corridor" in loc for loc in locations), (
        f"Unresolved approximation must be excluded from firm pricing: {locations}"
    )

    # Review signals must flag the approximation row with a REVIEW signal
    review_res = collect_commercial_review_signals(app, {"id": ws_id})
    review_signals = [s for s in review_res.signals if s.severity == "REVIEW"]
    assert any(
        "L-Corridor" in (str(s.location or "") + s.title + s.summary)
        or any("provisional" in r.lower() or "approximation" in r.lower() for r in s.reasons)
        for s in review_signals
    ), "Commercial review must flag the provisional approximation with an unresolved REVIEW signal"

    # Set JobHub job ID to enable publication evaluation
    app.lexecute("UPDATE workspaces SET jobhub_job_id='JH-MZ-TEST' WHERE id=?", (ws_id,))

    # Final publication must be BLOCKED because of the unresolved REVIEW signal on takeoff
    preflight = derive_export_preflight(app, ws_id, bridge_available=True)
    assert preflight.final_publish_state == "BLOCKED", (
        f"Final publication must be BLOCKED when an unresolved approximation exists: {preflight.final_publish_state}"
    )
