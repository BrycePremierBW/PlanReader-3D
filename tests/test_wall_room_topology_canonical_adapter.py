from __future__ import annotations

from pb_canonical_building import ReviewState
from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_wall_room_topology_canonical_adapter import adapt_topology_to_canonical_level
from pb_wall_room_topology_contracts import (
    EvidenceResolutionStatus,
    JunctionType,
    OpeningHostCandidate,
    RoomCandidate,
    WallCandidate,
)
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_opening_host_binding import detect_opening_host_candidates
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_room_wall_relationships import derive_room_wall_relationships
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates


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


def _full_pipeline(segments):
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id="doc_1", page_id="p1", viewport_id="vp_1"
    )
    walls, edge_map = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_1")
    rooms = reconstruct_room_candidates(graph, edge_map, document_id="doc_1", viewport_id="vp_1")
    updated_rooms, updated_walls, room_rels = derive_room_wall_relationships(rooms, walls)
    hosts = detect_opening_host_candidates(updated_walls)
    return updated_walls, updated_rooms, hosts


def _wall(
    candidate_id="wall_1",
    interior_exterior="exterior",
    status=EvidenceResolutionStatus.CANDIDATE,
    length_m=None,
    thickness_m=None,
    confidence=0.9,
):
    return WallCandidate(
        candidate_id=candidate_id,
        viewport_id="vp_1",
        representation="single_line",
        centerline_pts=((0, 0), (100, 0)),
        face_a_segment_ids=("seg_x",),
        face_b_segment_ids=None,
        is_curved=False,
        curve_control_pts=None,
        thickness_m=thickness_m,
        thickness_authority=(
            MeasurementAuthorityType.PDF_SCALED
            if thickness_m is not None
            else MeasurementAuthorityType.EXCLUDED
            if status == EvidenceResolutionStatus.CORROBORATED
            else MeasurementAuthorityType.PROVISIONAL
        ),
        length_m=length_m,
        end_node_ids=("n0", "n1"),
        junction_types=(JunctionType.L_CORNER, JunctionType.L_CORNER),
        interior_exterior=interior_exterior,
        level_id=None,
        status=status,
        confidence=confidence,
    )


def _room(room_ref="room_1", label="", polygon_m=None, floor_area_m2=None, status=EvidenceResolutionStatus.CANDIDATE):
    return RoomCandidate(
        room_ref=room_ref,
        label=label,
        polygon_pdf_pts=((0, 0), (100, 0), (100, 100), (0, 100)),
        polygon_m=polygon_m,
        floor_area_m2=floor_area_m2,
        area_page_pts2=10000.0,
        perimeter_m=None,
        geometry_confidence=0.9,
        evidence=(),
        source_page=0,
        drawing_number="",
        scale_source="",
        calibration_confidence=0.0,
        has_voids=False,
        document_id="doc_1",
        viewport_id="vp_1",
        status=status,
    )


_TWO_ROOM_PARTITION = [
    _seg("a", 0, 0, 300, 0),
    _seg("b", 300, 0, 300, 200),
    _seg("c", 300, 200, 150, 200),
    _seg("d", 0, 200, 0, 0),
    _seg("e", 150, 200, 0, 200),
    _seg("partition", 150, 0, 150, 200),
]


class TestIdsReusedVerbatim:
    def test_wall_and_room_ids_are_reused_not_reissued(self) -> None:
        walls, rooms, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        level = adapt_topology_to_canonical_level(
            document_id="doc_1", viewport_id="vp_1", walls=walls, rooms=rooms, opening_hosts=hosts
        )
        assert {w.id for w in level.walls} == {w.candidate_id for w in walls}
        assert {sp.id for sp in level.spaces} == {r.room_ref for r in rooms}
        assert level.id == "vp_1"


class TestNoAuthorityFlagsEver:
    def test_takeoff_eligible_and_deduction_authority_always_false(self) -> None:
        walls, rooms, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        level = adapt_topology_to_canonical_level(
            document_id="doc_1", viewport_id="vp_1", walls=walls, rooms=rooms, opening_hosts=hosts
        )
        assert level.takeoff_eligible is False
        assert level.deduction_authority is False
        assert all(w.takeoff_eligible is False and w.deduction_authority is False for w in level.walls)
        assert all(sp.takeoff_eligible is False and sp.deduction_authority is False for sp in level.spaces)

    def test_authority_flags_false_even_for_corroborated_high_confidence_wall(self) -> None:
        wall = _wall(status=EvidenceResolutionStatus.CORROBORATED, confidence=1.0)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].takeoff_eligible is False
        assert level.walls[0].deduction_authority is False


class TestReviewStateNeverConfirmed:
    def test_no_wall_or_space_is_ever_confirmed(self) -> None:
        walls, rooms, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        level = adapt_topology_to_canonical_level(
            document_id="doc_1", viewport_id="vp_1", walls=walls, rooms=rooms, opening_hosts=hosts
        )
        assert all(w.review_state != ReviewState.CONFIRMED for w in level.walls)
        assert all(sp.review_state != ReviewState.CONFIRMED for sp in level.spaces)
        assert level.review_state != ReviewState.CONFIRMED

    def test_corroborated_status_maps_to_inferred_not_confirmed(self) -> None:
        wall = _wall(status=EvidenceResolutionStatus.CORROBORATED)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].review_state == ReviewState.INFERRED

    def test_candidate_status_maps_to_review_required(self) -> None:
        wall = _wall(status=EvidenceResolutionStatus.CANDIDATE)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].review_state == ReviewState.REVIEW_REQUIRED

    def test_unresolved_interior_exterior_forces_review_required_even_if_status_healthy(self) -> None:
        wall = _wall(
            interior_exterior="unresolved", status=EvidenceResolutionStatus.CORROBORATED
        )
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].review_state == ReviewState.REVIEW_REQUIRED


class TestNoHeightOrAreaAuthority:
    def test_wall_height_always_none(self) -> None:
        wall = _wall(thickness_m=0.2)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].height_m is None

    def test_space_height_always_none(self) -> None:
        room = _room(floor_area_m2=25.0)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", rooms=[room])
        assert level.spaces[0].height_m is None

    def test_specified_floor_area_never_copied_from_room_candidate(self) -> None:
        room = _room(floor_area_m2=25.0, polygon_m=((0, 0), (5, 0), (5, 5), (0, 5)))
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", rooms=[room])
        assert room.floor_area_m2 == 25.0
        assert level.spaces[0].specified_floor_area_m2 is None

    def test_level_elevation_and_height_always_none(self) -> None:
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1")
        assert level.elevation_m is None
        assert level.height_m is None


class TestMetreConversion:
    def test_wall_endpoints_converted_using_walls_own_resolved_length_ratio(self) -> None:
        wall = _wall(length_m=5.0)  # 100pt centerline -> ratio 0.05 m/pt
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        start, end = level.walls[0].start_point, level.walls[0].end_point
        assert start.x == 0.0 and start.y == 0.0
        assert end.x == 5.0 and end.y == 0.0

    def test_wall_endpoints_stay_none_when_length_unresolved(self) -> None:
        wall = _wall(length_m=None)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].start_point.x is None
        assert level.walls[0].end_point.x is None

    def test_room_boundary_uses_existing_polygon_m_directly(self) -> None:
        room = _room(polygon_m=((0, 0), (5, 0), (5, 5), (0, 5)))
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", rooms=[room])
        boundary = level.spaces[0].boundary_polygon
        assert [(p.x, p.y) for p in boundary] == [(0, 0), (5, 0), (5, 5), (0, 5)]

    def test_room_boundary_empty_when_polygon_m_unresolved(self) -> None:
        room = _room(polygon_m=None)
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", rooms=[room])
        assert level.spaces[0].boundary_polygon == []


class TestNoOpeningIsEverMaterialized:
    def test_no_canonical_opening_created_even_when_opening_hosts_exist(self) -> None:
        walls, rooms, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        wall = _wall(candidate_id="wall_1")
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_1",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="ambiguous_host",
            candidate_wall_ids_considered=("wall_1", "wall_2"),
            confidence=0.6,
            reason_codes=("collinear_dangling_end_gap",),
        )
        level = adapt_topology_to_canonical_level(
            document_id="doc_1", viewport_id="vp_1", walls=[wall], opening_hosts=[host]
        )
        assert all(w.openings == [] for w in level.walls)

    def test_ambiguous_host_cross_referenced_on_every_considered_wall(self) -> None:
        wall_a = _wall(candidate_id="wall_a")
        wall_b = _wall(candidate_id="wall_b")
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_a",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="ambiguous_host",
            candidate_wall_ids_considered=("wall_a", "wall_b"),
            confidence=0.6,
            reason_codes=("collinear_dangling_end_gap",),
        )
        level = adapt_topology_to_canonical_level(
            document_id="doc_1", viewport_id="vp_1", walls=[wall_a, wall_b], opening_hosts=[host]
        )
        walls_by_id = {w.id: w for w in level.walls}
        assert walls_by_id["wall_a"].metadata["candidate_opening_host_ids"] == ["host_1"]
        assert walls_by_id["wall_b"].metadata["candidate_opening_host_ids"] == ["host_1"]

    def test_level_metadata_lists_every_unresolved_opening_host(self) -> None:
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_1",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="ambiguous_host",
            candidate_wall_ids_considered=("wall_1", "wall_2"),
            confidence=0.6,
            reason_codes=("collinear_dangling_end_gap",),
        )
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", opening_hosts=[host])
        assert level.metadata["unresolved_opening_host_ids"] == ["host_1"]


class TestProvenanceAndTraceability:
    def test_wall_provenance_carries_document_and_wall_ref(self) -> None:
        wall = _wall()
        level = adapt_topology_to_canonical_level(document_id="doc_42", viewport_id="vp_1", walls=[wall])
        prov = level.walls[0].provenance
        assert prov.document_id == "doc_42"
        assert prov.wall_ref == "wall_1"

    def test_wall_metadata_preserves_topology_reason_codes(self) -> None:
        wall = _wall()
        from dataclasses import replace

        wall = replace(wall, reason_codes=("assembled_from_1_stage_a_edges", "non_simple_chain_topology_fallback_ordering"))
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", walls=[wall])
        assert level.walls[0].metadata["topology_reason_codes"] == [
            "assembled_from_1_stage_a_edges",
            "non_simple_chain_topology_fallback_ordering",
        ]

    def test_room_label_becomes_space_name_when_present(self) -> None:
        room = _room(label="KITCHEN")
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", rooms=[room])
        assert level.spaces[0].name == "KITCHEN"

    def test_room_without_label_gets_default_name_not_invented_one(self) -> None:
        room = _room(label="")
        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1", rooms=[room])
        assert level.spaces[0].name == "Unnamed Element"


class TestNoLevelBuildingOrProjectAggregation:
    def test_returns_a_single_level_not_a_building_or_project(self) -> None:
        from pb_canonical_building import CanonicalLevel

        level = adapt_topology_to_canonical_level(document_id="doc_1", viewport_id="vp_1")
        assert isinstance(level, CanonicalLevel)
        assert not hasattr(level, "levels")  # not a CanonicalBuilding


class TestNoQuantityOrLiveWiring:
    def test_no_quantity_evidence_import_or_construction(self) -> None:
        import pb_wall_room_topology_canonical_adapter as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_does_not_import_canonical_persistence(self) -> None:
        import pb_wall_room_topology_canonical_adapter as mod

        assert "pb_canonical_persistence" not in dir(mod)
        source = open(mod.__file__, encoding="utf-8").read()
        assert "import pb_canonical_persistence" not in source
        assert "from pb_canonical_persistence" not in source

    def test_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_canonical_adapter" not in source
