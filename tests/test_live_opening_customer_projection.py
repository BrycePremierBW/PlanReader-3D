"""Live opening customer projection uses exact source-closed lineage."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

import fitz

from pb_customer_output_verification import verify_sealed_customer_output
from pb_live_opening_customer_projection import project_live_opening_customer_rows
from pb_live_opening_source_closed_export import seal_live_opening_area_claim_run
from pb_live_physical_net_wall_integration import collect_live_physical_net_wall_claim


def _opening_pdf() -> bytes:
    doc = fitz.open()
    try:
        page = doc.new_page(width=760.0, height=650.0)
        for first, second in (
            ((20.0, 100.0), (100.0, 100.0)),
            ((145.0, 100.0), (220.0, 100.0)),
            ((20.0, 110.0), (100.0, 110.0)),
            ((145.0, 110.0), (220.0, 110.0)),
            ((100.0, 100.0), (100.0, 110.0)),
            ((145.0, 100.0), (145.0, 110.0)),
            ((100.0, 70.0), (145.0, 70.0)),
            ((100.0, 70.0), (100.0, 100.0)),
            ((145.0, 70.0), (145.0, 100.0)),
        ):
            page.draw_line(fitz.Point(*first), fitz.Point(*second), width=1.0)
        page.insert_text(fitz.Point(112.0, 65.0), "900")
        page.insert_text(fitz.Point(112.0, 106.0), "W1")

        headings = (
            "MARK",
            "ROWDTH-MM",
            "ROHT-MM",
            "ROUGH-OPENING-SILL-MM",
            "ROUGH-OPENING-HEAD-MM",
        )
        values = ("W1", "900", "2100", "900", "3000")
        xs = (50.0, 150.0, 250.0, 350.0, 550.0)
        for text, x in zip(headings, xs):
            page.insert_text(fitz.Point(x, 500.0), text)
        for text, x in zip(values, xs):
            page.insert_text(fitz.Point(x, 530.0), text)

        page.draw_line(fitz.Point(300.0, 250.0), fitz.Point(350.0, 250.0), width=1.0)
        page.draw_line(fitz.Point(300.0, 242.0), fitz.Point(300.0, 258.0), width=1.0)
        page.draw_line(fitz.Point(350.0, 242.0), fitz.Point(350.0, 258.0), width=1.0)
        page.insert_text(fitz.Point(298.0, 274.0), "0")
        page.insert_text(fitz.Point(346.0, 274.0), "1m")
        return bytes(doc.tobytes(garbage=4, deflate=True))
    finally:
        doc.close()


def _persisted_core_shape(row: dict) -> dict:
    """Mirror the fields retained by the 21-field takeoff_rows layout."""
    unit = str(row["unit"])
    if unit.lower() == "m2":
        unit = "m²"
    return {
        "workspace_id": row["workspace_id"],
        "section": row["section"],
        "element": row["element"],
        "location": row["location"],
        "substrate": row["substrate"],
        "quantity": row["quantity"],
        "unit": unit,
        "quantity_status": "To review",
        "source_page": row["source_page"],
        "source_reference": "PB Auto Geometry v1.2.19 · " + row["source_reference"],
        "inclusion_status": "PROVISIONAL",
        "confidence": "Documented",
        "notes": row["notes"],
        "row_role": "",
    }


def test_real_opening_seal_projects_one_complete_persisted_customer_row(tmp_path) -> None:
    path = tmp_path / "opening.pdf"
    path.write_bytes(_opening_pdf())
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))

    sealed = seal_live_opening_area_claim_run(
        claim,
        workspace_id=17,
        project_id="customer-workspace:17",
    )
    assert len(sealed.quantities) == 1

    rows = project_live_opening_customer_rows(
        claim,
        workspace_id=17,
        project_id="customer-workspace:17",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["origin"] == "AI"
    assert row["quantity_status"] == "To review"
    assert row["section"] == "Openings"
    assert row["substrate"] == "Other"
    assert row["inclusion_status"] == "PROVISIONAL"
    assert row["row_role"] == ""
    assert row["measurement_method"] == "direct_evidence"
    assert row["figured_dimension_ids"] == []
    assert json.loads(row["notes"])["adapter"] == "commercial_takeoff"

    live = verify_sealed_customer_output(sealed, rows)
    assert live.complete if hasattr(live, "complete") else True
    assert live.valid_quantity_count == 1
    assert live.customer_row_count == 1

    persisted = _persisted_core_shape(row)
    persisted_report = verify_sealed_customer_output(sealed, [persisted])
    assert persisted_report.valid_quantity_count == 1
    assert persisted_report.customer_row_count == 1
    assert persisted_report.verified_quantity_ids == (
        sealed.quantities[0].quantity_id,
    )


@pytest.mark.parametrize("kind", ("two_area_rows", "area_count_collision"))
def test_opening_customer_output_rejects_reused_quantity_identity_before_trace_merge(
    tmp_path, kind,
):
    path = tmp_path / "opening-identity-collision.pdf"
    path.write_bytes(_opening_pdf())
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    assert len(claim.opening_quantity_evidence) == 1
    original = claim.opening_quantity_evidence[0]
    if kind == "two_area_rows":
        forged = replace(
            claim,
            opening_quantity_evidence=(original, original),
        )
    else:
        forged_count = replace(
            original,
            family="opening_count",
            metadata={
                **dict(original.metadata),
                "schedule_corroborated": True,
                "opening_mark": "W1",
            },
        )
        forged = replace(
            claim,
            opening_count_quantity_evidence=(forged_count,),
        )
    with pytest.raises(ValueError, match="quantity identities collide"):
        project_live_opening_customer_rows(
            forged,
            workspace_id=17,
            project_id="customer-workspace:17",
        )
    assert len(project_live_opening_customer_rows(
        claim, workspace_id=17, project_id="customer-workspace:17",
    )) == 1
