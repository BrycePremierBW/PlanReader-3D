"""Read-only wall-topology diagnostic harness tests.

These tests cover the diagnostic layer only. They do not change W1-W10
classification behavior.
"""
from __future__ import annotations

import copy
import json
import random

import pytest

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import (
    JunctionCandidate,
    JunctionType,
    OpeningHostCandidate,
    TopologyRelationship,
    TopologyRelationshipType,
    WallCandidate,
)
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_topology_diagnostics import (
    TopologySnapshot,
    collect_topology_from_page,
    collect_topology_from_segments,
    diagnose_wall_topology,
    document_id_from_path,
    length_distribution,
    list_page_viewports,
    percentile,
    report_to_canonical_json,
    report_to_markdown,
    report_to_svg,
)


def _seg(seg_id, x1, y1, x2, y2, **overrides):
    base = {
        "id": seg_id,
        "kind": "line",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": 1.0,
        "stroke": (0, 0, 0),
        "fill": None,
        "layer": "",
        "dashes": "",
    }
    base.update(overrides)
    return base


def _rectangle(origin=(0.0, 0.0), width=100.0, height=80.0, prefix="r"):
    x0, y0 = origin
    x1, y1 = x0 + width, y0 + height
    return [
        _seg(f"{prefix}0", x0, y0, x1, y0),
        _seg(f"{prefix}1", x1, y0, x1, y1),
        _seg(f"{prefix}2", x1, y1, x0, y1),
        _seg(f"{prefix}3", x0, y1, x0, y0),
    ]


def _wall(
    candidate_id="wall_1",
    start=(0.0, 0.0),
    end=(40.0, 0.0),
    face_ids=("edge_a",),
    status=EvidenceResolutionStatus.CANDIDATE,
    reason_codes=(),
    representation="single_line",
    face_b=None,
):
    return WallCandidate(
        candidate_id=candidate_id,
        viewport_id="vp_1",
        representation=representation,
        centerline_pts=(start, end),
        face_a_segment_ids=face_ids,
        face_b_segment_ids=face_b,
        is_curved=False,
        curve_control_pts=None,
        thickness_m=None,
        thickness_authority=MeasurementAuthorityType.PROVISIONAL,
        length_m=None,
        end_node_ids=("n0_" + candidate_id, "n1_" + candidate_id),
        junction_types=(JunctionType.ENDPOINT, JunctionType.ENDPOINT),
        interior_exterior="unresolved",
        level_id=None,
        status=status,
        confidence=0.5,
        reason_codes=tuple(reason_codes),
    )


class TestPercentiles:
    def test_empty_is_none(self) -> None:
        assert percentile([], 50.0) is None
        dist = length_distribution([])
        assert dist["count"] == 0
        assert dist["median"] is None

    def test_known_sample(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert percentile(values, 0.0) == 1.0
        assert percentile(values, 50.0) == 3.0
        assert percentile(values, 100.0) == 5.0
        assert percentile(values, 25.0) == 2.0
        dist = length_distribution(values)
        assert dist["min"] == 1.0
        assert dist["max"] == 5.0
        assert dist["mean"] == 3.0
        assert dist["p50"] == 3.0


class TestEmptyAndSingle:
    def test_empty_pipeline(self) -> None:
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="page_0",
            page_number=0,
            viewport_id="",
            viewport_authority="unavailable",
            fail_closed_reason="safe_floor_plan_viewport_unavailable",
        )
        report = diagnose_wall_topology(snapshot)
        assert report["counts"]["wall_candidates"] == 0
        assert report["counts"]["connected_components"] == 0
        assert report["source"]["fail_closed_reason"] == "safe_floor_plan_viewport_unavailable"
        assert report["wall_candidates"] == []
        markdown = report_to_markdown(report)
        assert "Fail-closed" in markdown
        assert report_to_svg(report) is None

    def test_one_candidate(self) -> None:
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
            viewport_authority="caller_supplied",
            walls=(_wall(),),
            opening_host_evaluated=True,
        )
        report = diagnose_wall_topology(snapshot)
        assert report["counts"]["wall_candidates"] == 1
        assert report["counts"]["isolated_candidates"] == 1
        assert report["counts"]["connected_components"] == 1
        row = report["wall_candidates"][0]
        assert row["candidate_id"] == "wall_1"
        assert row["length_pt"] == 40.0
        assert row["length_m"] is None
        assert row["thickness_m"] is None
        assert row["fill_hatch_evidence"] == "unavailable"
        assert row["opening_host_state"] == "UNBOUND"
        assert row["room_face_participation"] == "no"
        assert row["paired_face_evidence"] == "no"
        assert report["pipeline"]["stages_evaluated"] == []


class TestComponentsAndBindings:
    def test_multiple_connected_components(self) -> None:
        snapshot = collect_topology_from_segments(
            _rectangle((0, 0), 40, 30, "a") + _rectangle((200, 200), 40, 30, "b"),
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        report = diagnose_wall_topology(snapshot)
        assert report["counts"]["connected_components"] == 2
        sizes = sorted(item["size"] for item in report["components"])
        assert sizes == [4, 4]
        assert report["counts"]["isolated_candidates"] == 0

    def test_ambiguous_binding_preserved(self) -> None:
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_a",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="ambiguous_host",
            candidate_wall_ids_considered=("wall_a", "wall_b"),
            confidence=0.4,
            reason_codes=("collinear_dangling_end_gap",),
        )
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
            viewport_authority="caller_supplied",
            walls=(_wall("wall_a"), _wall("wall_b", start=(50, 0), end=(90, 0))),
            opening_hosts=(host,),
            opening_host_evaluated=True,
        )
        report = diagnose_wall_topology(snapshot)
        states = {row["candidate_id"]: row["opening_host_state"] for row in report["wall_candidates"]}
        assert states["wall_a"] == "AMBIGUOUS"
        assert states["wall_b"] == "AMBIGUOUS"
        assert report["opening_hosts"][0]["host_status"] == "ambiguous_host"

    def test_not_evaluated_binding(self) -> None:
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
            viewport_authority="caller_supplied",
            walls=(_wall(),),
            opening_host_evaluated=False,
        )
        report = diagnose_wall_topology(snapshot)
        assert report["wall_candidates"][0]["opening_host_state"] == "not_evaluated"

    def test_missing_metre_fields_stay_null(self) -> None:
        snapshot = collect_topology_from_segments(
            _rectangle(),
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        report = diagnose_wall_topology(snapshot)
        for row in report["wall_candidates"]:
            assert row["length_m"] is None
            assert row["thickness_m"] is None
            assert row["spacing_evidence"] == "unavailable"
            assert row["fill_hatch_evidence"] == "unavailable"


class TestDeterminism:
    def test_repeated_execution_identical_json(self) -> None:
        snapshot = collect_topology_from_segments(
            _rectangle(),
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        first = report_to_canonical_json(diagnose_wall_topology(snapshot))
        second = report_to_canonical_json(diagnose_wall_topology(snapshot))
        assert first == second

    def test_shuffled_wall_order_same_canonical_json(self) -> None:
        snapshot = collect_topology_from_segments(
            _rectangle((0, 0), 50, 40, "a") + _rectangle((120, 0), 50, 40, "b"),
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        baseline = report_to_canonical_json(diagnose_wall_topology(snapshot))
        walls = list(snapshot.walls)
        rng = random.Random(7)
        rng.shuffle(walls)
        shuffled = TopologySnapshot(
            document_id=snapshot.document_id,
            page_id=snapshot.page_id,
            page_number=snapshot.page_number,
            viewport_id=snapshot.viewport_id,
            viewport_authority=snapshot.viewport_authority,
            raw_primitive_count=snapshot.raw_primitive_count,
            scoped_primitive_count=snapshot.scoped_primitive_count,
            stage_a_graph=snapshot.stage_a_graph,
            junctions=tuple(reversed(snapshot.junctions)),
            relationships=snapshot.relationships,
            walls=tuple(walls),
            edge_id_to_wall_id=snapshot.edge_id_to_wall_id,
            rooms=tuple(reversed(snapshot.rooms)),
            room_relationships=snapshot.room_relationships,
            opening_hosts=snapshot.opening_hosts,
            opening_host_evaluated=snapshot.opening_host_evaluated,
            reconciliation=snapshot.reconciliation,
        )
        assert report_to_canonical_json(diagnose_wall_topology(shuffled)) == baseline

    def test_candidate_ids_stable_across_segment_shuffle(self) -> None:
        segments = _rectangle()
        first = collect_topology_from_segments(
            segments,
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        shuffled = list(segments)
        random.Random(3).shuffle(shuffled)
        second = collect_topology_from_segments(
            shuffled,
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        assert sorted(wall.candidate_id for wall in first.walls) == sorted(
            wall.candidate_id for wall in second.walls
        )

    def test_does_not_mutate_inputs(self) -> None:
        snapshot = collect_topology_from_segments(
            _rectangle(),
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
        )
        before_walls = copy.deepcopy([wall.to_dict() for wall in snapshot.walls])
        before_rooms = copy.deepcopy([room.to_dict() for room in snapshot.rooms])
        before_hosts = copy.deepcopy([host.to_dict() for host in snapshot.opening_hosts])
        before_graph = copy.deepcopy(dict(snapshot.stage_a_graph))
        diagnose_wall_topology(snapshot)
        assert [wall.to_dict() for wall in snapshot.walls] == before_walls
        assert [room.to_dict() for room in snapshot.rooms] == before_rooms
        assert [host.to_dict() for host in snapshot.opening_hosts] == before_hosts
        assert dict(snapshot.stage_a_graph) == before_graph


class TestProductionParity:
    def test_w4_ids_unchanged_when_diagnostics_imported(self) -> None:
        segments = _rectangle()
        graph = build_wall_graph_for_viewport(segments)
        junctions, relationships = classify_junctions(
            graph, document_id="doc", page_id="p1", viewport_id="vp_1"
        )
        walls, _edge_map = assemble_wall_candidates(
            graph, junctions, relationships, viewport_id="vp_1"
        )
        snapshot = collect_topology_from_segments(
            segments,
            document_id="doc",
            page_id="p1",
            page_number=1,
            viewport_id="vp_1",
        )
        assert sorted(wall.candidate_id for wall in walls) == sorted(
            wall.candidate_id for wall in snapshot.walls
        )

    def test_w3_relationship_objects_not_rewritten(self) -> None:
        relationship = TopologyRelationship(
            relationship_id="rel_1",
            from_edge_id="e1",
            to_edge_id=None,
            relationship_type=TopologyRelationshipType.TERMINATES_AT,
            via_junction_id="j1",
            confidence=0.9,
        )
        junction = JunctionCandidate(
            node_id="j1",
            document_id="doc",
            page_id="p1",
            viewport_id="vp_1",
            position_pt=(0.0, 0.0),
            junction_type=JunctionType.ENDPOINT,
            incident_wall_candidate_ids=("wall_1",),
            incident_angles_deg=(0.0,),
            status=EvidenceResolutionStatus.CANDIDATE,
            confidence=0.9,
        )
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="p1",
            page_number=1,
            viewport_id="vp_1",
            viewport_authority="caller_supplied",
            junctions=(junction,),
            relationships=(relationship,),
            walls=(_wall(),),
        )
        diagnose_wall_topology(snapshot)
        assert snapshot.relationships[0] is relationship
        assert snapshot.junctions[0] is junction


class TestBindingAndPairedFace:
    def test_bound_state_preserved(self) -> None:
        host = OpeningHostCandidate(
            host_candidate_id="host_bound",
            wall_candidate_id="wall_1",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="hosted",
            candidate_wall_ids_considered=("wall_1",),
            confidence=0.8,
            reason_codes=(),
        )
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
            viewport_authority="caller_supplied",
            walls=(_wall(),),
            opening_hosts=(host,),
            opening_host_evaluated=True,
        )
        report = diagnose_wall_topology(snapshot)
        assert report["wall_candidates"][0]["opening_host_state"] == "BOUND"
        assert report["distributions"]["opening_host_binding"]["BOUND"] == 1

    def test_paired_face_yes_when_double_line(self) -> None:
        wall = _wall(representation="double_line", face_b=("edge_b",))
        snapshot = TopologySnapshot(
            document_id="doc",
            page_id="page_1",
            page_number=1,
            viewport_id="vp_1",
            viewport_authority="caller_supplied",
            walls=(wall,),
        )
        report = diagnose_wall_topology(snapshot)
        assert report["wall_candidates"][0]["paired_face_evidence"] == "yes"


class TestSerializers:
    def test_markdown_contains_required_headings(self) -> None:
        report = diagnose_wall_topology(
            collect_topology_from_segments(
                _rectangle(),
                document_id="doc",
                page_id="page_1",
                page_number=1,
                viewport_id="vp_1",
            )
        )
        markdown = report_to_markdown(report)
        for heading in (
            "# Wall Topology Diagnostic",
            "## Pipeline Counts",
            "## Candidate Length Distribution",
            "## Connected Components",
            "## Junction Participation",
            "## Room-Face Participation",
            "## Paired-Face Evidence",
            "## Fill/Hatch Evidence",
            "## Opening Host Binding",
            "## Highest-Connectivity Candidates",
            "## Isolated Candidates",
            "## Ambiguous Candidates",
        ):
            assert heading in markdown
        assert "false wall" not in markdown.lower()
        assert "true wall" not in markdown.lower()

    def test_svg_optional_and_dependency_free(self) -> None:
        report = diagnose_wall_topology(
            collect_topology_from_segments(
                _rectangle(),
                document_id="doc",
                page_id="page_1",
                page_number=1,
                viewport_id="vp_1",
            )
        )
        svg = report_to_svg(report)
        assert svg is not None
        assert svg.startswith("<svg")
        assert "data-candidate=" in svg
        assert "data-junction=" in svg
        assert "data-room=" in svg

    def test_equivalent_dictionary_order_same_json(self) -> None:
        report = diagnose_wall_topology(
            collect_topology_from_segments(
                _rectangle(),
                document_id="doc",
                page_id="page_1",
                page_number=1,
                viewport_id="vp_1",
            )
        )
        reversed_report = {key: report[key] for key in reversed(list(report))}
        assert report_to_canonical_json(reversed_report) == report_to_canonical_json(report)

    def test_document_id_is_basename_only(self) -> None:
        assert document_id_from_path(r"C:\Users\someone\drawings\plan.pdf") == "plan.pdf"
        assert "\\" not in document_id_from_path("/tmp/nested/plan.pdf")
        assert "/" not in document_id_from_path("/tmp/nested/plan.pdf")


class TestProductionIsolation:
    def test_diagnostics_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_topology_diagnostics" not in source

    def test_diagnostics_do_not_import_extractor_or_scorer(self) -> None:
        source = open("pb_wall_topology_diagnostics.py", encoding="utf-8").read()
        assert "pb_planreader_pdf_extractor" not in source
        assert "pb_benchmark" not in source
        assert "expected_boq" not in source


class TestPageFailClosed:
    def test_blank_page_has_no_safe_floor_plan(self) -> None:
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        try:
            page = doc.new_page()
            snapshot = collect_topology_from_page(
                page, page_number=1, document_id="blank.pdf"
            )
            listing = list_page_viewports(page, page_number=1)
        finally:
            doc.close()
        assert snapshot.fail_closed_reason == "safe_floor_plan_viewport_unavailable"
        report = diagnose_wall_topology(snapshot)
        assert report["counts"]["wall_candidates"] == 0
        assert report["source"]["fail_closed_reason"] == "safe_floor_plan_viewport_unavailable"
        assert listing == []

    def test_caller_supplied_bbox_scopes_segments(self) -> None:
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.draw_line((10, 10), (90, 10))
        page.draw_line((90, 10), (90, 90))
        page.draw_line((90, 90), (10, 90))
        page.draw_line((10, 90), (10, 10))
        page.draw_line((150, 150), (190, 150))
        data = doc.tobytes()
        doc.close()
        reopened = fitz.open(stream=data, filetype="pdf")
        try:
            snapshot = collect_topology_from_page(
                reopened[0],
                page_number=1,
                document_id="caller.pdf",
                viewport_bbox=(0.0, 0.0, 120.0, 120.0),
                viewport_id="caller_box",
            )
        finally:
            reopened.close()
        assert snapshot.fail_closed_reason is None
        assert snapshot.viewport_authority == "caller_supplied"
        report = diagnose_wall_topology(snapshot)
        assert report["counts"]["raw_primitives"] > report["counts"]["scoped_primitives"]
        assert report["counts"]["wall_candidates"] >= 1


class TestCli:
    def test_cli_fail_closed_writes_canonical_json(self, tmp_path) -> None:
        fitz = pytest.importorskip("fitz")
        pdf_path = tmp_path / "blank.pdf"
        doc = fitz.open()
        try:
            doc.new_page()
            doc.save(pdf_path)
        finally:
            doc.close()
        json_path = tmp_path / "out.json"
        md_path = tmp_path / "out.md"
        import importlib.util
        from pathlib import Path as _Path

        cli_path = _Path(__file__).resolve().parents[1] / "tools" / "audit_wall_topology.py"
        spec = importlib.util.spec_from_file_location("audit_wall_topology_cli", cli_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        main = module.main

        assert main([str(pdf_path), "--page", "1", "--json", str(json_path), "--markdown", str(md_path)]) == 0
        first = json_path.read_text(encoding="utf-8")
        assert main([str(pdf_path), "--page", "1", "--json", str(json_path)]) == 0
        assert json_path.read_text(encoding="utf-8") == first
        payload = json.loads(first)
        assert payload["source"]["document_id"] == "blank.pdf"
        assert payload["source"]["fail_closed_reason"] == "safe_floor_plan_viewport_unavailable"
        assert "C:" not in first
        assert "Users" not in first
        assert md_path.read_text(encoding="utf-8").startswith("# Wall Topology Diagnostic")
