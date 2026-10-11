from __future__ import annotations

from dataclasses import replace
import inspect

import fitz
import pytest

from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports
import pb_live_room_area_customer_projection as customer_projection
import pb_live_room_area_source_closed_export as export
import pb_live_floor_area_customer_projection as floor_customer_projection
import pb_live_floor_area_source_closed_export as floor_export
from pb_customer_output_verification import verify_sealed_customer_output
from pb_live_floor_area_quantity_publication import publish_live_floor_area_quantities
from pb_live_physical_net_wall_integration import (
    collect_live_physical_net_wall_claim,
)
from pb_source_closed_run_export import SourceClosedRunConflictError
from pb_quantity_takeoff_adapter import (
    CommercialTakeoffConflictError,
    existing_commercial_gate_results,
)


def _cross_view_room_area_pdf() -> bytes:
    doc = fitz.open()
    try:
        plan = doc.new_page(width=300.0, height=200.0)
        for first, second in (
            ((50.0, 50.0), (250.0, 50.0)),
            ((250.0, 50.0), (250.0, 150.0)),
            ((250.0, 150.0), (50.0, 150.0)),
            ((50.0, 150.0), (50.0, 50.0)),
            ((150.0, 50.0), (150.0, 150.0)),
        ):
            plan.draw_line(
                fitz.Point(*first),
                fitz.Point(*second),
                color=(0, 0, 0),
                width=1.0,
            )
        plan.insert_text((78.0, 100.0), "OFFICE", fontsize=9.0)
        plan.insert_text((178.0, 100.0), "STUDY", fontsize=9.0)

        detail = doc.new_page(width=400.0, height=300.0)
        detail.insert_text((150.0, 150.0), "OFFICE", fontsize=10.0)

        detail.draw_line(
            (100.0, 80.0),
            (250.0, 80.0),
            color=(0, 0, 0),
            width=1.0,
        )
        detail.draw_line(
            (100.0, 68.0),
            (100.0, 92.0),
            color=(0, 0, 0),
            width=1.0,
        )
        detail.draw_line(
            (250.0, 68.0),
            (250.0, 92.0),
            color=(0, 0, 0),
            width=1.0,
        )
        detail.insert_text((164.0, 77.0), "3600", fontsize=9.0)

        # The vertical dimension shares a source witness junction with the
        # horizontal dimension at (250, 80).
        detail.draw_line(
            (280.0, 80.0),
            (280.0, 180.0),
            color=(0, 0, 0),
            width=1.0,
        )
        detail.draw_line(
            (250.0, 80.0),
            (292.0, 80.0),
            color=(0, 0, 0),
            width=1.0,
        )
        detail.draw_line(
            (268.0, 180.0),
            (292.0, 180.0),
            color=(0, 0, 0),
            width=1.0,
        )
        detail.insert_text(
            (277.0, 147.0),
            "2400",
            fontsize=9.0,
            rotate=90,
        )
        return doc.tobytes()
    finally:
        doc.close()


def _framed_cross_view_room_area_pdf() -> bytes:
    doc = fitz.open(stream=_cross_view_room_area_pdf(), filetype="pdf")
    try:
        plan = doc[0]
        # Producer-owned closed drawing frame plus explicit in-view title.
        # All source-room polygons sit wholly inside this one plan viewport.
        plan.draw_rect(
            fitz.Rect(20.0, 20.0, 280.0, 180.0),
            color=(0, 0, 0),
            width=0.8,
        )
        plan.insert_text((92.0, 35.0), "GROUND FLOOR PLAN", fontsize=8.0)
        return doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()


def test_documented_room_area_inherits_unique_authenticated_plan_viewport(
    tmp_path,
) -> None:
    path = tmp_path / "framed-cross-view-room-area.pdf"
    path.write_bytes(_framed_cross_view_room_area_pdf())

    doc = fitz.open(path)
    try:
        viewports = authoritative_floor_plan_viewports(
            doc[0],
            page_number=1,
        )
    finally:
        doc.close()
    resolved = tuple(
        viewport
        for viewport in viewports
        if viewport.bounding_box is not None
    )
    assert len(resolved) == 1
    expected_viewport_id = str(resolved[0].view_id)

    claim = collect_live_physical_net_wall_claim(
        path,
        pages=(0,),
        room_area_support_pages=(1,),
    )
    firm = tuple(
        quantity
        for quantity in claim.room_area_quantity_evidence
        if not quantity.abstained and quantity.value is not None
    )
    assert firm
    documented = tuple(
        quantity
        for quantity in firm
        if quantity.authority == "documented_dimension"
    )
    assert documented
    assert all(
        str(quantity.metadata.get("viewport_id") or "")
        == expected_viewport_id
        for quantity in documented
    )


@pytest.fixture(scope="module")
def live_claim(tmp_path_factory):
    path = (
        tmp_path_factory.mktemp("live-room-area-source-closed")
        / "cross-view-room-area.pdf"
    )
    path.write_bytes(_cross_view_room_area_pdf())
    return collect_live_physical_net_wall_claim(
        path,
        pages=(0,),
        room_area_support_pages=(1,),
    )


def _firm_quantity(claim):
    firm = [
        quantity
        for quantity in claim.room_area_quantity_evidence
        if not quantity.abstained
    ]
    assert len(firm) == 1
    return firm[0]


def _resolved_floor(claim):
    floors = [
        floor
        for floor in claim.canonical_floors
        if floor.metric_area_quantity_id
    ]
    assert len(floors) == 1
    return floors[0]


def test_live_room_area_seals_with_source_and_canonical_floor_trace(
    live_claim,
) -> None:
    quantity = _firm_quantity(live_claim)
    floor = _resolved_floor(live_claim)
    assert quantity.value == pytest.approx(8.64)
    assert floor.metric_area_m2 == pytest.approx(8.64)
    assert floor.metric_area_quantity_id == quantity.quantity_id

    traces = export.build_live_room_area_source_traces(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    assert set(traces) == {quantity.quantity_id}
    trace = traces[quantity.quantity_id]
    assert set(quantity.input_entity_ids).issubset(trace.canonical_entity_ids)
    assert floor.canonical_floor_id in trace.canonical_entity_ids
    assert floor.physical_floor_surface_id in trace.canonical_entity_ids
    assert floor.source_room_face_record_id == trace.metadata[
        "source_room_face_record_id"
    ]
    assert set(quantity.evidence_ids).issubset(trace.evidence_ids)

    run = export.seal_live_room_area_run(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    assert run.project_id == "source-project"
    assert run.source_sha256s == (floor.source_sha256,)
    assert len(run.quantities) == 1

    row = run.quantities[0]
    assert row.quantity_id == quantity.quantity_id
    assert row.family == "room_area"
    assert row.value == pytest.approx(8.64)
    assert row.unit == "m2"
    assert row.lineage_ok is True
    assert row.abstained is False
    # Sealed production identity remains the quantity's real source-room
    # identity; canonical floor identity is additional trace provenance only.
    assert row.object_identity_refs == tuple(sorted(quantity.input_entity_ids))


def test_floor_area_seals_on_physical_floor_identity(
    live_claim,
) -> None:
    floor = _resolved_floor(live_claim)
    floor_quantities = publish_live_floor_area_quantities(live_claim)
    assert len(floor_quantities) == 1
    quantity = floor_quantities[0]

    assert quantity.family == "floor_area"
    assert quantity.value == pytest.approx(8.64)
    assert quantity.input_entity_ids == (floor.physical_floor_surface_id,)

    traces = floor_export.build_live_floor_area_source_traces(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    trace = traces[quantity.quantity_id]
    assert floor.physical_floor_surface_id in trace.canonical_entity_ids
    assert floor.canonical_floor_id in trace.canonical_entity_ids
    assert set(quantity.evidence_ids).issubset(trace.evidence_ids)

    run = floor_export.seal_live_floor_area_run(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    assert len(run.quantities) == 1
    row = run.quantities[0]
    assert row.family == "floor_area"
    assert row.quantity_id == quantity.quantity_id
    assert row.value == pytest.approx(8.64)
    assert row.object_identity_refs == (floor.physical_floor_surface_id,)
    assert floor.physical_floor_surface_id in row.trace_canonical_entity_ids
    assert row.lineage_ok is True


def test_final_floor_area_seal_reaches_one_live_and_persisted_customer_row(
    live_claim,
) -> None:
    run = floor_export.seal_live_floor_area_run(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    rows = floor_customer_projection.project_live_floor_area_customer_rows(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )

    assert len(run.quantities) == len(rows) == 1
    assert rows[0]["quantity_id"] == run.quantities[0].quantity_id
    assert rows[0]["quantity_family"] == "floor_area"
    assert rows[0]["quantity_status"] == "To review"
    assert rows[0]["origin"] == "AI"
    assert rows[0]["row_role"] == "floor_area"

    live_report = verify_sealed_customer_output(run, rows)
    assert live_report.valid_quantity_count == 1
    assert live_report.customer_row_count == 1
    assert live_report.verified_quantity_ids == (run.quantities[0].quantity_id,)

    persisted = {
        "workspace_id": rows[0]["workspace_id"],
        "section": rows[0]["section"],
        "element": rows[0]["element"],
        "location": rows[0]["location"],
        "substrate": rows[0]["substrate"],
        "finish_system": rows[0]["finish_system"],
        "quantity": rows[0]["quantity"],
        "unit": "m²",
        "quantity_status": rows[0]["quantity_status"],
        "source_page": rows[0]["source_page"],
        "source_reference": "PB Auto Geometry v1.2.19 · " + rows[0]["source_reference"],
        "inclusion_status": rows[0]["inclusion_status"],
        "confidence": "Documented",
        "notes": rows[0]["notes"],
        "row_role": "floor_area",
    }
    persisted_report = verify_sealed_customer_output(run, [persisted])
    assert persisted_report.valid_quantity_count == 1
    assert persisted_report.customer_row_count == 1
    assert persisted_report.verified_quantity_ids == (
        run.quantities[0].quantity_id,
    )


def test_floor_area_sealing_is_deterministic(
    live_claim,
) -> None:
    first = floor_export.seal_live_floor_area_run(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    second = floor_export.seal_live_floor_area_run(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    assert first.run_id == second.run_id
    assert first.fingerprint == second.fingerprint
    assert first.to_json() == second.to_json()


def test_unavailable_room_areas_are_omitted_not_exported_as_zero(
    live_claim,
) -> None:
    assert any(
        quantity.abstained
        for quantity in live_claim.room_area_quantity_evidence
    )
    run = export.seal_live_room_area_run(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )
    assert len(run.quantities) == 1
    assert all(not row.abstained for row in run.quantities)
    assert all(row.value is not None and row.value > 0.0 for row in run.quantities)


def test_room_area_export_fails_closed_without_unique_enriched_floor(
    live_claim,
) -> None:
    floor = _resolved_floor(live_claim)
    missing = replace(
        floor,
        metric_area_m2=None,
        metric_area_quantity_id=None,
        metric_area_authority=None,
    )
    claim_without_mapping = replace(
        live_claim,
        canonical_floors=tuple(
            missing if item.canonical_floor_id == floor.canonical_floor_id else item
            for item in live_claim.canonical_floors
        ),
    )
    with pytest.raises(
        SourceClosedRunConflictError,
        match="does not map to exactly one canonical floor",
    ):
        export.build_live_room_area_source_traces(
            claim_without_mapping,
            workspace_id=7,
            project_id="source-project",
        )

    duplicate = replace(
        floor,
        canonical_floor_id=f"{floor.canonical_floor_id}-duplicate",
        physical_floor_surface_id=(
            f"{floor.physical_floor_surface_id}-duplicate"
        ),
    )
    claim_with_duplicate = replace(
        live_claim,
        canonical_floors=(*live_claim.canonical_floors, duplicate),
    )
    with pytest.raises(
        SourceClosedRunConflictError,
        match="does not map to exactly one canonical floor",
    ):
        export.build_live_room_area_source_traces(
            claim_with_duplicate,
            workspace_id=7,
            project_id="source-project",
        )


def test_live_room_area_export_has_no_truth_or_scoring_dependency() -> None:
    source = inspect.getsource(export)
    forbidden = (
        "benchmarks.",
        "full_plan_v2",
        "reference_takeoff",
        "expected_quantity",
        "golden",
    )
    for value in forbidden:
        assert value not in source


def test_live_room_area_figured_quantity_projects_to_unreviewed_customer_row(
    live_claim,
) -> None:
    quantity = _firm_quantity(live_claim)
    figured_ids = tuple(quantity.metadata.get("figured_dimension_ids") or ())
    assert figured_ids

    rows = customer_projection.project_live_room_area_customer_rows(
        live_claim,
        workspace_id=7,
        project_id="source-project",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["quantity_id"] == quantity.quantity_id
    assert row["quantity"] == pytest.approx(8.64)
    assert row["unit"] == "m2"
    assert row["quantity_status"] == "To review"
    assert row["origin"] == "AI"
    assert row["row_role"] == "floor_area"
    assert row["inclusion_status"] == "INCLUSION"
    assert row["measurement_method"] == "figured_dimension"
    assert set(row["figured_dimension_ids"]) == set(figured_ids)
    assert row["source_sha256"] == _resolved_floor(live_claim).source_sha256

    gates = existing_commercial_gate_results(row)
    assert all(result[0] is False for result in gates.values())


def _scaled_room_area_claim(
    live_claim,
    *,
    resolved_scale_id: str | None,
    scale_status: str = "resolved",
    scale_conflicts: tuple[str, ...] = (),
):
    quantity = _firm_quantity(live_claim)
    metadata = dict(quantity.metadata or {})
    metadata["figured_dimension_ids"] = []
    metadata["resolved_scale_id"] = resolved_scale_id
    metadata["scale_status"] = scale_status
    metadata["scale_conflicts"] = list(scale_conflicts)
    scaled = replace(
        quantity,
        authority="pdf_scaled",
        formula="shoelace_polygon_area / trusted_px_per_m^2",
        metadata=metadata,
    )
    floor = _resolved_floor(live_claim)
    scaled_floor = replace(
        floor,
        metric_area_authority="pdf_scaled",
    )
    return replace(
        live_claim,
        room_area_quantity_evidence=tuple(
            scaled if item.quantity_id == quantity.quantity_id else item
            for item in live_claim.room_area_quantity_evidence
        ),
        canonical_floors=tuple(
            scaled_floor if item.canonical_floor_id == floor.canonical_floor_id else item
            for item in live_claim.canonical_floors
        ),
    )


def test_live_room_area_scaled_quantity_projects_only_with_explicit_scale_authority(
    live_claim,
) -> None:
    claim = _scaled_room_area_claim(
        live_claim,
        resolved_scale_id="scale:room-area:1",
        scale_status="resolved",
    )

    rows = customer_projection.project_live_room_area_customer_rows(
        claim,
        workspace_id=7,
        project_id="source-project",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["quantity"] == pytest.approx(8.64)
    assert row["quantity_status"] == "To review"
    assert row["origin"] == "AI"
    assert row["measurement_method"] == "scaled_geometry"
    assert row["resolved_scale_id"] == "scale:room-area:1"
    assert row["scale_status"] == "resolved"
    assert row["scale_conflicts"] == []
    assert row["row_role"] == "floor_area"

    gates = existing_commercial_gate_results(row)
    assert all(result[0] is False for result in gates.values())


def test_scaled_room_area_without_resolved_scale_id_remains_unprojected(
    live_claim,
) -> None:
    claim = _scaled_room_area_claim(
        live_claim,
        resolved_scale_id=None,
        scale_status="resolved",
    )

    rows = customer_projection.project_live_room_area_customer_rows(
        claim,
        workspace_id=7,
        project_id="source-project",
    )

    assert rows == ()


def test_scaled_room_area_with_scale_conflict_fails_closed(
    live_claim,
) -> None:
    claim = _scaled_room_area_claim(
        live_claim,
        resolved_scale_id="scale:room-area:1",
        scale_status="resolved",
        scale_conflicts=("scale_conflict",),
    )

    with pytest.raises(CommercialTakeoffConflictError, match="scale conflicts"):
        customer_projection.project_live_room_area_customer_rows(
            claim,
            workspace_id=7,
            project_id="source-project",
        )


def test_room_area_customer_projection_omits_abstention_instead_of_zero(
    live_claim,
) -> None:
    abstained = tuple(
        quantity
        for quantity in live_claim.room_area_quantity_evidence
        if quantity.abstained
    )
    assert abstained
    claim = replace(live_claim, room_area_quantity_evidence=abstained)

    rows = customer_projection.project_live_room_area_customer_rows(
        claim,
        workspace_id=7,
        project_id="source-project",
    )

    assert rows == ()


def test_live_room_area_customer_projection_has_no_truth_or_scoring_dependency() -> None:
    source = inspect.getsource(customer_projection)
    forbidden = (
        "benchmarks.",
        "full_plan_v2",
        "reference_takeoff",
        "expected_quantity",
        "golden",
    )
    for value in forbidden:
        assert value not in source


def test_source_sealed_floor_customer_diagnostic_is_exact_and_unapproved(
    live_claim,
) -> None:
    from tools.diag_gpt3_maryborough_floor_customer_gate import (
        inspect_floor_customer_handoff,
    )
    proof = inspect_floor_customer_handoff(
        live_claim, workspace_id=7, project_id="source-project"
    )
    published = publish_live_floor_area_quantities(live_claim)
    ids = [row.quantity_id for row in published]
    assert len(ids) == 1
    assert proof["published_floor_area_quantity_ids"] == ids
    assert proof["sealed_floor_area_quantity_ids"] == ids
    assert proof["customer_verified_floor_area_quantity_ids"] == ids
    assert proof["customer_review_row_count"] == 1
    assert proof["customer_projection_failure_type"] is None
    assert proof["diagnostic_workspace_not_customer_approved"] is True
    assert proof["commercial_estimator_approved"] is False
    assert proof["benchmark_accuracy"] is None


def test_unavailable_floor_customer_diagnostic_stays_unpublished(
    live_claim,
) -> None:
    from tools.diag_gpt3_maryborough_floor_customer_gate import (
        inspect_floor_customer_handoff,
    )
    unmeasured = replace(live_claim, room_area_quantity_evidence=())
    proof = inspect_floor_customer_handoff(unmeasured)
    assert proof["published_floor_area_quantity_ids"] == []
    assert proof["sealed_floor_area_quantity_ids"] == []
    assert proof["customer_verified_floor_area_quantity_ids"] == []
    assert proof["customer_review_row_count"] == 0
    assert proof["commercial_estimator_approved"] is False


def test_missing_customer_authority_never_converts_seal_to_verified_row(
    live_claim, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.diag_gpt3_maryborough_floor_customer_gate as module
    from pb_quantity_takeoff_adapter import MissingCommercialAuthorityError

    def reject_customer_rows(*_args, **_kwargs):
        raise MissingCommercialAuthorityError("missing figured dimension witness")

    monkeypatch.setattr(module, "project_live_floor_area_customer_rows", reject_customer_rows)
    proof = module.inspect_floor_customer_handoff(live_claim)
    assert len(proof["published_floor_area_quantity_ids"]) == 1
    assert len(proof["sealed_floor_area_quantity_ids"]) == 1
    assert proof["customer_verified_floor_area_quantity_ids"] == []
    assert proof["customer_review_row_count"] == 0
    assert proof["customer_projection_failure_type"] == "MissingCommercialAuthorityError"
    assert proof["benchmark_accuracy"] is None


def test_floor_customer_figured_authority_requires_two_distinct_typed_source_axes(live_claim):
    original = _firm_quantity(live_claim)
    valid = tuple(original.metadata.get("figured_dimension_ids") or ())
    assert len(valid) == 2
    assert floor_customer_projection._measurement_authority(original) is not None
    for ids in (
        (), (valid[0],), (valid[0], valid[0]),
        (valid[0], valid[1], "unrelated-source-system"),
        valid[0], (valid[0], 42),
    ):
        replay = replace(
            original,
            metadata={**dict(original.metadata), "figured_dimension_ids": ids},
        )
        assert floor_customer_projection._measurement_authority(replay) is None
