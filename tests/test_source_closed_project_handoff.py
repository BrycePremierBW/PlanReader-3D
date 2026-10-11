"""Generic project source-closed handoff orchestration tests."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import fitz
import pytest

from pb_migration_contracts import QuantityEvidence
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace
from pb_source_closed_run_export import seal_source_closed_run
from pb_source_floor_plan_page_scope import (
    SourceFloorPlanPageDecision,
    SourceFloorPlanPageScope,
)
from tools import run_source_closed_project_handoff as handoff


def _quantity(quantity_id: str, family: str) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id=quantity_id,
        family=family,
        semantic_key=f"{family}:entity-1",
        value=1.0,
        unit="m2" if family != "opening_count" else "ea",
        input_entity_ids=(f"{family}-entity-1",),
        formula="test",
        formula_version="1",
        evidence_ids=(f"ev-{quantity_id}",),
        authority="documented_dimension",
        status="firm",
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=(),
        metadata={},
    )


def _run(
    *,
    project_id: str,
    source_sha256: str,
    family: str,
    quantity_id: str,
):
    quantity = _quantity(quantity_id, family)
    trace = CommercialTakeoffSourceTrace(
        workspace_id=1,
        project_id=project_id,
        document_id="doc-1",
        source_sha256=source_sha256,
        source_page="1",
        viewport_id="vp-1",
        revision_id="rev-1",
        current_revision_id="rev-1",
        evidence_ids=quantity.evidence_ids,
        canonical_entity_ids=quantity.input_entity_ids,
    )
    return seal_source_closed_run(
        (quantity,),
        project_id=project_id,
        traces_by_quantity_id={quantity.quantity_id: trace},
    )


def _three_page_pdf(path) -> None:
    doc = fitz.open()
    try:
        for _ in range(3):
            doc.new_page(width=200.0, height=100.0)
        doc.save(path)
    finally:
        doc.close()


def test_source_topology_pages_reuses_production_bound_title_scope(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    _three_page_pdf(pdf)
    scope = SourceFloorPlanPageScope(
        decisions=(
            SourceFloorPlanPageDecision(
                0,
                "not_floor_plan",
                "not_floor_plan_bound_title",
                "COVER SHEET",
                (),
            ),
            SourceFloorPlanPageDecision(
                1,
                "floor_plan",
                "floor_plan_bound_title",
                "FLOOR PLAN",
                ("floor_plan",),
            ),
            SourceFloorPlanPageDecision(
                2,
                "not_floor_plan",
                "not_floor_plan_bound_title",
                "ELEVATIONS",
                ("elevation",),
            ),
        ),
        selected_page_indices=(0, 1, 2),
        floor_plan_page_indices=(1,),
        other_drawing_page_indices=(0, 2),
    )
    monkeypatch.setattr(
        handoff,
        "source_floor_plan_topology_scope",
        lambda path, selected: scope,
    )

    topology, support, page_count = handoff._source_page_scopes(pdf)

    assert page_count == 3
    assert topology == (1,)
    # COVER SHEET and ELEVATIONS remain general evidence but are not
    # horizontal room-area support plans.
    assert support == ()


def test_source_topology_pages_preserves_full_scope_when_unrestricted(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    _three_page_pdf(pdf)
    scope = SourceFloorPlanPageScope(
        decisions=(
            SourceFloorPlanPageDecision(
                0,
                "unproven",
                "floor_plan_page_unproven",
            ),
            SourceFloorPlanPageDecision(
                1,
                "floor_plan",
                "floor_plan_bound_title",
                "FLOOR PLAN",
                ("floor_plan",),
            ),
            SourceFloorPlanPageDecision(
                2,
                "unproven",
                "floor_plan_page_unproven",
            ),
        ),
        selected_page_indices=(0, 1, 2),
        floor_plan_page_indices=(1,),
        other_drawing_page_indices=(),
    )
    assert scope.topology_page_indices() is None
    monkeypatch.setattr(
        handoff,
        "source_floor_plan_topology_scope",
        lambda path, selected: scope,
    )

    topology, support, page_count = handoff._source_page_scopes(pdf)

    assert page_count == 3
    assert topology == (0, 1, 2)
    assert support == ()


def test_project_handoff_combines_only_available_source_closed_families(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    source_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    project_id = "project-a"

    floor_q = _quantity("q-floor", "floor_area")
    floor_finish_q = _quantity("q-floor-finish", "floor_finish_area")
    opening_q = _quantity("q-opening", "opening_area")
    count_q = _quantity("q-count", "opening_count")
    claim = SimpleNamespace(
        status=SimpleNamespace(value="corroborated"),
        reason_codes=("resolved",),
        canonical_walls=(1, 2),
        canonical_openings=(1,),
        canonical_rooms=(1,),
        canonical_floors=(1,),
        canonical_spaces=(1,),
        room_area_quantity_evidence=(),
        floor_finish_quantity_evidence=(floor_finish_q,),
        opening_quantity_evidence=(opening_q,),
        opening_count_quantity_evidence=(count_q,),
    )
    ceiling_result = SimpleNamespace()
    ceiling_q = _quantity("q-ceiling", "ceiling_lining")

    monkeypatch.setattr(handoff, "_source_page_scopes", lambda path: ((0,), (), 1))
    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        lambda *args, **kwargs: ceiling_result,
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (ceiling_q,),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (floor_q,),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_floor_area_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="floor_area",
            quantity_id="q-floor",
        ),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_floor_finish_area_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="floor_finish_area",
            quantity_id="q-floor-finish",
        ),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_opening_area_claim_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="opening_area",
            quantity_id="q-opening",
        ),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_opening_count_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="opening_count",
            quantity_id="q-count",
        ),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_ceiling_area_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="ceiling_lining",
            quantity_id="q-ceiling",
        ),
    )

    output = tmp_path / "out"
    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id=project_id,
        workspace_id=1,
        output_dir=output,
    )

    assert summary["status"] == "sealed"
    assert summary["complete_project_handoff"] is True
    assert summary["source_sha256"] == source_sha
    assert summary["topology_pages"] == [1]
    assert summary["topology_mode"] == "live_authority_all_pages_fallback"
    assert summary["family_counts"] == {
        "floor_area": 1,
        "floor_finish_area": 1,
        "opening_area": 1,
        "opening_count": 1,
        "ceiling_area": 1,
    }
    assert summary["combined_quantity_count"] == 5
    assert (output / f"{project_id}.json").is_file()
    assert (output / "production_summary.json").is_file()
    assert sorted((output / "family_runs").glob("*.sealed.json"))


def test_project_handoff_without_vector_hints_delegates_topology_to_live_authority(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    monkeypatch.setattr(handoff, "_source_page_scopes", lambda path: ((0, 1, 2), (), 3))

    claim = SimpleNamespace(
        status=SimpleNamespace(value="abstained"),
        reason_codes=("live-authority-unavailable",),
        canonical_walls=(),
        canonical_openings=(),
        canonical_rooms=(),
        canonical_floors=(),
        canonical_spaces=(),
        room_area_quantity_evidence=(),
        opening_quantity_evidence=(),
        opening_count_quantity_evidence=(),
    )
    seen = {}

    def _collect(*args, **kwargs):
        seen.update(kwargs)
        return claim

    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        _collect,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (),
    )

    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id="project-a",
        workspace_id=1,
        output_dir=tmp_path / "out",
    )

    assert seen["pages"] == (0, 1, 2)
    assert seen["topology_pages"] is None
    assert seen["room_area_support_pages"] is None
    assert summary["status"] == "no_sealable_quantities"
    assert summary["topology_pages"] == [1, 2, 3]
    assert summary["room_area_support_pages"] == []
    assert summary["topology_mode"] == "live_authority_all_pages_fallback"
    assert summary["claim_reason_codes"] == ["live-authority-unavailable"]
    assert summary["combined_run_file"] is None


def test_project_handoff_keeps_full_surface_evidence_but_scopes_room_support(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    monkeypatch.setattr(
        handoff,
        "_source_page_scopes",
        lambda path: ((0,), (2,), 5),
    )

    claim = SimpleNamespace(
        status=SimpleNamespace(value="abstained"),
        reason_codes=("resolved-scope",),
        canonical_walls=(),
        canonical_openings=(),
        canonical_rooms=(),
        canonical_floors=(),
        canonical_spaces=(),
        room_area_quantity_evidence=(),
        opening_quantity_evidence=(),
        opening_count_quantity_evidence=(),
    )
    seen = {}
    ceiling_seen = {}

    def _collect(*args, **kwargs):
        seen.update(kwargs)
        return claim

    def _collect_ceiling(*args, **kwargs):
        ceiling_seen.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        _collect,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        _collect_ceiling,
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (),
    )

    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id="project-a",
        workspace_id=1,
        output_dir=tmp_path / "out",
    )

    assert seen["pages"] == (0, 1, 2, 3, 4)
    assert seen["topology_pages"] == (0,)
    assert seen["room_area_support_pages"] == (2,)
    assert ceiling_seen["pages"] == (0, 1, 2, 3, 4)
    assert ceiling_seen["topology_pages"] == (0,)
    assert summary["topology_pages"] == [1]
    assert summary["room_area_support_pages"] == [3]
    assert summary["execution_pages"] == [1, 2, 3, 4, 5]
    assert summary["topology_mode"] == "source_classified_scope"


def test_surface_family_group_scopes_geometry_but_keeps_full_semantic_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    monkeypatch.setattr(
        handoff,
        "_source_page_scopes",
        lambda path: ((0,), (2,), 5),
    )

    claim = SimpleNamespace(
        status=SimpleNamespace(value="abstained"),
        reason_codes=("resolved-scope",),
        canonical_walls=(),
        canonical_openings=(),
        canonical_rooms=(),
        canonical_floors=(),
        canonical_spaces=(),
        room_area_quantity_evidence=(),
        floor_finish_quantity_evidence=(),
        opening_quantity_evidence=(),
        opening_count_quantity_evidence=(),
    )
    seen = {}
    ceiling_seen = {}

    def _collect(*args, **kwargs):
        seen.update(kwargs)
        return claim

    def _collect_ceiling(*args, **kwargs):
        ceiling_seen.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        _collect,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        _collect_ceiling,
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (),
    )

    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id="project-a",
        workspace_id=1,
        output_dir=tmp_path / "out",
        family_group="surfaces",
    )

    assert seen["pages"] == (0, 2)
    assert seen["topology_pages"] == (0,)
    assert seen["room_area_support_pages"] == (2,)
    assert seen["surface_semantic_pages"] == (0, 1, 2, 3, 4)
    assert ceiling_seen["pages"] == (0, 1, 2, 3, 4)
    assert summary["execution_pages"] == [1, 3]
    assert summary["semantic_execution_pages"] == [1, 2, 3, 4, 5]
    assert summary["topology_mode"] == "source_classified_scope"


def test_project_handoff_rejects_family_run_from_different_source(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    floor_q = _quantity("q-floor", "floor_area")
    claim = SimpleNamespace(
        status=SimpleNamespace(value="corroborated"),
        reason_codes=(),
        canonical_walls=(),
        canonical_openings=(),
        canonical_rooms=(1,),
        canonical_floors=(1,),
        canonical_spaces=(1,),
        room_area_quantity_evidence=(),
        opening_quantity_evidence=(),
        opening_count_quantity_evidence=(),
    )

    monkeypatch.setattr(handoff, "_source_page_scopes", lambda path: ((0,), (), 1))
    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (floor_q,),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_floor_area_run",
        lambda *args, **kwargs: _run(
            project_id="project-a",
            source_sha256="f" * 64,
            family="floor_area",
            quantity_id="q-floor",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="conflicting source SHA envelope",
    ):
        handoff.generate_project_handoff(
            pdf_path=pdf,
            project_id="project-a",
            workspace_id=1,
            output_dir=tmp_path / "out",
        )



def test_project_handoff_combined_filename_matches_suite_scoreboard_contract(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    source_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    project_id = "project-a"
    floor_q = _quantity("q-floor", "floor_area")
    claim = SimpleNamespace(
        status=SimpleNamespace(value="corroborated"),
        reason_codes=(),
        canonical_walls=(),
        canonical_openings=(),
        canonical_rooms=(1,),
        canonical_floors=(1,),
        canonical_spaces=(1,),
        room_area_quantity_evidence=(),
        opening_quantity_evidence=(),
        opening_count_quantity_evidence=(),
    )

    monkeypatch.setattr(handoff, "_source_page_scopes", lambda path: ((0,), (), 1))
    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (floor_q,),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_floor_area_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="floor_area",
            quantity_id="q-floor",
        ),
    )

    output = tmp_path / "sealed"
    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id=project_id,
        workspace_id=1,
        output_dir=output,
    )

    assert summary["combined_run_file"] == str(output / f"{project_id}.json")
    assert (output / f"{project_id}.json").is_file()
    assert not (output / f"{project_id}.sealed.json").exists()


def test_project_handoff_persists_production_failure_summary_before_reraise(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    output = tmp_path / "out"

    monkeypatch.setattr(handoff, "_source_page_scopes", lambda path: ((0, 1), (), 2))

    def _fail(*args, **kwargs):
        raise ValueError("raster opening primitive count exceeds safety bound")

    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        _fail,
    )

    with pytest.raises(
        ValueError,
        match="raster opening primitive count exceeds safety bound",
    ):
        handoff.generate_project_handoff(
            pdf_path=pdf,
            project_id="project-a",
            workspace_id=1,
            output_dir=output,
        )

    summary = __import__("json").loads(
        (output / "production_summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "production_failed"
    assert summary["topology_mode"] == "live_authority_all_pages_fallback"
    assert summary["production_error_type"] == "ValueError"
    assert summary["production_error_message"] == (
        "raster opening primitive count exceeds safety bound"
    )
    assert summary["claim_reason_codes"] == [
        "production_extraction_error:ValueError"
    ]
    assert summary["combined_run_file"] is None



def test_project_handoff_does_not_seal_upstream_room_area_as_final_family(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    upstream_room = _quantity("q-room", "room_area")
    claim = SimpleNamespace(
        status=SimpleNamespace(value="corroborated"),
        reason_codes=(),
        canonical_walls=(),
        canonical_openings=(),
        canonical_rooms=(1,),
        canonical_floors=(1,),
        canonical_spaces=(1,),
        room_area_quantity_evidence=(upstream_room,),
        opening_quantity_evidence=(),
        opening_count_quantity_evidence=(),
    )
    monkeypatch.setattr(handoff, "_source_page_scopes", lambda path: ((0,), (), 1))
    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        lambda *args, **kwargs: claim,
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        lambda claim: (),
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        lambda result: (),
    )

    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id="project-a",
        workspace_id=1,
        output_dir=tmp_path / "out",
    )

    assert summary["family_counts"]["floor_area"] == 0
    assert "room_area" not in summary["family_counts"]
    assert summary["combined_quantity_count"] == 0
    assert summary["status"] == "no_sealable_quantities"



def test_core_family_group_uses_only_proven_topology_scope_and_skips_surfaces(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")
    source_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    project_id = "project-core"

    opening_q = _quantity("q-opening", "opening_area")
    count_q = _quantity("q-count", "opening_count")
    claim = SimpleNamespace(
        status=SimpleNamespace(value="corroborated"),
        reason_codes=("core-resolved",),
        canonical_walls=(1,),
        canonical_openings=(1,),
        canonical_rooms=(),
        canonical_floors=(),
        canonical_spaces=(),
        room_area_quantity_evidence=(),
        opening_quantity_evidence=(opening_q,),
        opening_count_quantity_evidence=(count_q,),
    )
    seen = {}

    monkeypatch.setattr(
        handoff,
        "_source_page_scopes",
        lambda path: ((1,), (0, 2), 3),
    )

    def _collect(*args, **kwargs):
        seen.update(kwargs)
        return claim

    monkeypatch.setattr(
        handoff,
        "collect_live_physical_net_wall_claim",
        _collect,
    )

    def _surface_forbidden(*args, **kwargs):
        raise AssertionError("core handoff must not invoke surface publication")

    monkeypatch.setattr(
        handoff,
        "publish_live_floor_area_quantities",
        _surface_forbidden,
    )
    monkeypatch.setattr(
        handoff,
        "collect_live_ceiling_lining_claims",
        _surface_forbidden,
    )
    monkeypatch.setattr(
        handoff,
        "publish_live_ceiling_area_quantities",
        _surface_forbidden,
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_opening_area_claim_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="opening_area",
            quantity_id="q-opening",
        ),
    )
    monkeypatch.setattr(
        handoff,
        "seal_live_opening_count_run",
        lambda *args, **kwargs: _run(
            project_id=project_id,
            source_sha256=source_sha,
            family="opening_count",
            quantity_id="q-count",
        ),
    )

    output = tmp_path / "out"
    summary = handoff.generate_project_handoff(
        pdf_path=pdf,
        project_id=project_id,
        workspace_id=1,
        output_dir=output,
        family_group="core",
    )

    assert seen["pages"] == (1,)
    assert seen["topology_pages"] == (1,)
    assert seen["room_area_support_pages"] is None
    assert summary["family_group"] == "core"
    assert summary["complete_project_handoff"] is False
    assert summary["execution_pages"] == [2]
    assert summary["family_counts"] == {
        "floor_area": 0,
        "floor_finish_area": 0,
        "opening_area": 1,
        "opening_count": 1,
        "ceiling_area": 0,
    }
    assert summary["combined_quantity_count"] == 2
    assert summary["status"] == "sealed"
    assert summary["combined_run_file"] == str(
        output / f"{project_id}.core.json"
    )
    assert (output / f"{project_id}.core.json").is_file()
    assert not (output / f"{project_id}.json").exists()


def test_invalid_family_group_fails_before_source_scope_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source-bytes")

    def _unexpected(*args, **kwargs):
        raise AssertionError("source scope must not run for invalid family group")

    monkeypatch.setattr(handoff, "_source_page_scopes", _unexpected)

    with pytest.raises(
        ValueError,
        match="family_group must be one of",
    ):
        handoff.generate_project_handoff(
            pdf_path=pdf,
            project_id="project-a",
            workspace_id=1,
            output_dir=tmp_path / "out",
            family_group="not-a-group",
        )
