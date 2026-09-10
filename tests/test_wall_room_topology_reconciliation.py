from __future__ import annotations

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_wall_room_topology_contracts import (
    EvidenceResolutionStatus,
    JunctionType,
    RoomCandidate,
    WallCandidate,
)
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_opening_host_binding import detect_opening_host_candidates
from pb_wall_room_topology_reconciliation import (
    RECONCILIATION_SCHEMA_VERSION,
    reconcile_topology,
)
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_room_wall_relationships import (
    REASON_ANOMALOUS_WALL_USAGE,
    derive_room_wall_relationships,
)
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
    return junctions, updated_walls, updated_rooms, room_rels, hosts


def _wall(candidate_id, interior_exterior="unresolved", reason_codes=(), status=EvidenceResolutionStatus.CANDIDATE):
    return WallCandidate(
        candidate_id=candidate_id,
        viewport_id="vp_1",
        representation="single_line",
        centerline_pts=((0, 0), (100, 0)),
        face_a_segment_ids=("seg_x",),
        face_b_segment_ids=None,
        is_curved=False,
        curve_control_pts=None,
        thickness_m=None,
        thickness_authority=MeasurementAuthorityType.PROVISIONAL,
        length_m=None,
        end_node_ids=("n0", "n1"),
        junction_types=(JunctionType.L_CORNER, JunctionType.L_CORNER),
        interior_exterior=interior_exterior,
        level_id=None,
        status=status,
        confidence=0.8,
        reason_codes=reason_codes,
    )


def _room(room_ref, bounding_wall_candidate_ids=(), status=EvidenceResolutionStatus.CANDIDATE):
    return RoomCandidate(
        room_ref=room_ref,
        label="",
        polygon_pdf_pts=((0, 0), (100, 0), (100, 100), (0, 100)),
        polygon_m=None,
        floor_area_m2=None,
        area_page_pts2=1000.0,
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
        bounding_wall_candidate_ids=bounding_wall_candidate_ids,
    )


_TWO_ROOM_PARTITION = [
    _seg("a", 0, 0, 300, 0),
    _seg("b", 300, 0, 300, 200),
    _seg("c", 300, 200, 150, 200),
    _seg("d", 0, 200, 0, 0),
    _seg("e", 150, 200, 0, 200),
    _seg("partition", 150, 0, 150, 200),
]

_THREE_ROOM_ROW = [
    _seg("top", 0, 0, 300, 0),
    _seg("bottom", 0, 200, 300, 200),
    _seg("left", 0, 0, 0, 200),
    _seg("right", 300, 0, 300, 200),
    _seg("p1", 100, 0, 100, 200),
    _seg("p2", 200, 0, 200, 200),
]

_DOOR_GAP_RECTANGLE = [
    _seg("top_left", 0, 0, 130, 0),
    _seg("top_right", 170, 0, 300, 0),
    _seg("right", 300, 0, 300, 200),
    _seg("bottom", 300, 200, 0, 200),
    _seg("left", 0, 200, 0, 0),
]


class TestHealthyTopologyIsNotFlagged:
    def test_two_room_partition_produces_no_flags_or_integrity_issues(self) -> None:
        junctions, walls, rooms, rels, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        summary = reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        assert summary.flagged_entities == ()
        assert summary.integrity_issues == ()

    def test_status_counts_reflect_actual_entity_counts(self) -> None:
        junctions, walls, rooms, rels, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        summary = reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        assert sum(summary.status_counts["junctions"].values()) == len(junctions)
        assert sum(summary.status_counts["walls"].values()) == len(walls)
        assert sum(summary.status_counts["rooms"].values()) == len(rooms)
        assert sum(summary.status_counts["room_relationships"].values()) == len(rels)


class TestRoutineProvenanceIsNeverFlagged:
    def test_wall_assembled_from_n_edges_code_alone_does_not_flag(self) -> None:
        wall = _wall("w1", interior_exterior="interior", reason_codes=("assembled_from_2_stage_a_edges",))
        summary = reconcile_topology("vp_1", walls=[wall])
        assert summary.flagged_entities == ()

    def test_relationship_reason_codes_never_flag_anything(self) -> None:
        # W6's ADJACENT_TO/SEPARATES relationships always carry routine
        # provenance reason codes (shared_wall_id:..., other_side_room_ref:...)
        # -- relationships are never individually flagged.
        junctions, walls, rooms, rels, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        assert any(rel.reason_codes for rel in rels)
        summary = reconcile_topology("vp_1", room_relationships=rels)
        assert summary.flagged_entities == ()


class TestExistingAnomaliesAreSurfacedNotReDecided:
    def test_three_room_row_flags_exactly_the_anomalous_walls(self) -> None:
        junctions, walls, rooms, rels, hosts = _full_pipeline(_THREE_ROOM_ROW)
        summary = reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        anomalous_wall_ids = {w.candidate_id for w in walls if REASON_ANOMALOUS_WALL_USAGE in w.reason_codes}
        assert len(anomalous_wall_ids) >= 1
        flagged_wall_ids = {f.entity_id for f in summary.flagged_entities if f.entity_type == "wall"}
        assert anomalous_wall_ids <= flagged_wall_ids
        # The anomalous walls stay "unresolved" -- W9 does not re-decide them.
        for wall in walls:
            if wall.candidate_id in anomalous_wall_ids:
                assert wall.interior_exterior == "unresolved"

    def test_opening_host_ambiguous_candidates_are_always_flagged(self) -> None:
        graph = build_wall_graph_for_viewport(_DOOR_GAP_RECTANGLE)
        junctions, relationships = classify_junctions(
            graph, document_id="doc_1", page_id="p1", viewport_id="vp_1"
        )
        walls, _edge_map = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_1")
        hosts = detect_opening_host_candidates(walls)
        assert len(hosts) == 1
        summary = reconcile_topology("vp_1", opening_hosts=hosts)
        flagged_host_ids = {f.entity_id for f in summary.flagged_entities if f.entity_type == "opening_host"}
        assert flagged_host_ids == {hosts[0].host_candidate_id}
        assert summary.status_counts["opening_hosts"] == {"ambiguous_host": 1}

    def test_reconcile_never_mutates_or_reissues_input_entities(self) -> None:
        junctions, walls, rooms, rels, hosts = _full_pipeline(_THREE_ROOM_ROW)
        before = ([w.status for w in walls], [r.label for r in rooms], [j.status for j in junctions])
        reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        after = ([w.status for w in walls], [r.label for r in rooms], [j.status for j in junctions])
        assert before == after


class TestReferentialIntegrityChecks:
    def test_dangling_wall_reference_from_room_is_detected(self) -> None:
        room = _room("room_x", bounding_wall_candidate_ids=("wall_missing",))
        summary = reconcile_topology("vp_1", walls=[], rooms=[room])
        assert any("dangling_wall_reference" in issue and "room_x" in issue for issue in summary.integrity_issues)

    def test_dangling_wall_reference_from_opening_host_is_detected(self) -> None:
        from pb_wall_room_topology_contracts import OpeningHostCandidate

        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_missing_a",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="ambiguous_host",
            candidate_wall_ids_considered=("wall_missing_a", "wall_missing_b"),
            confidence=0.5,
            reason_codes=("collinear_dangling_end_gap",),
        )
        summary = reconcile_topology("vp_1", walls=[], opening_hosts=[host])
        dangling = [i for i in summary.integrity_issues if "dangling_wall_reference" in i]
        assert len(dangling) == 2

    def test_dangling_room_reference_from_adjacent_room_refs_is_detected(self) -> None:
        room = _replace_adjacent(_room("room_x"))
        summary = reconcile_topology("vp_1", rooms=[room])
        assert any(
            "dangling_room_reference" in issue and "room_missing" in issue for issue in summary.integrity_issues
        )

    def test_no_false_positive_integrity_issues_on_consistent_input(self) -> None:
        junctions, walls, rooms, rels, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        summary = reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        assert summary.integrity_issues == ()

    def test_unresolved_wall_referenced_by_room_without_anomaly_reason_is_flagged(self) -> None:
        wall = _wall("wall_bad", interior_exterior="unresolved", reason_codes=())
        room = _room("room_x", bounding_wall_candidate_ids=("wall_bad",))
        summary = reconcile_topology("vp_1", walls=[wall], rooms=[room])
        assert any("unresolved_without_anomaly_reason" in issue for issue in summary.integrity_issues)

    def test_unresolved_wall_with_anomaly_reason_is_not_an_integrity_issue(self) -> None:
        wall = _wall("wall_ok", interior_exterior="unresolved", reason_codes=(REASON_ANOMALOUS_WALL_USAGE,))
        room = _room("room_x", bounding_wall_candidate_ids=("wall_ok",))
        summary = reconcile_topology("vp_1", walls=[wall], rooms=[room])
        assert not any("unresolved_without_anomaly_reason" in issue for issue in summary.integrity_issues)

    def test_junction_incident_wall_ids_are_never_checked_against_wall_list(self) -> None:
        # JunctionCandidate.incident_wall_candidate_ids references Stage-A edge
        # ids, a different namespace than WallCandidate.candidate_id -- must
        # never be reported as a dangling reference.
        junctions, walls, rooms, rels, hosts = _full_pipeline(_TWO_ROOM_PARTITION)
        assert any(j.incident_wall_candidate_ids for j in junctions)
        summary = reconcile_topology("vp_1", junctions=junctions, walls=[])
        assert summary.integrity_issues == ()


def _replace_adjacent(room: RoomCandidate) -> RoomCandidate:
    from dataclasses import replace

    return replace(room, adjacent_room_refs=("room_missing",))


class TestRoomAreaConflictIsFlagged:
    def test_room_with_area_conflict_is_flagged_even_without_reason_codes(self) -> None:
        room = _room("room_x")
        from dataclasses import replace

        room = replace(room, area_conflict={"polygon_area_m2": 24.5, "explicit_area_m2": 30.0})
        summary = reconcile_topology("vp_1", rooms=[room])
        flagged_room_ids = {f.entity_id for f in summary.flagged_entities if f.entity_type == "room"}
        assert "room_x" in flagged_room_ids

    def test_room_with_no_label_alone_is_not_flagged(self) -> None:
        room = _room("room_x")
        assert room.label == ""
        summary = reconcile_topology("vp_1", rooms=[room])
        assert summary.flagged_entities == ()


class TestDeterminism:
    def test_deterministic_replay(self) -> None:
        junctions, walls, rooms, rels, hosts = _full_pipeline(_THREE_ROOM_ROW)
        s1 = reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        s2 = reconcile_topology(
            "vp_1", junctions=junctions, walls=walls, rooms=rooms, room_relationships=rels, opening_hosts=hosts
        )
        assert s1.to_dict() == s2.to_dict()


class TestNoQuantityOrLiveWiring:
    def test_no_quantity_evidence_import_or_construction(self) -> None:
        import pb_wall_room_topology_reconciliation as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_schema_version_is_exported(self) -> None:
        assert RECONCILIATION_SCHEMA_VERSION == "1.0"

    def test_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_reconciliation" not in source
