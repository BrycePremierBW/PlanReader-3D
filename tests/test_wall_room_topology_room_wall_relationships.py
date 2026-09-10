from __future__ import annotations

import random

from pb_wall_room_topology_contracts import TopologyRelationshipType
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_room_wall_relationships import (
    REASON_ANOMALOUS_WALL_USAGE,
    compute_wall_usage,
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
    walls, edge_map = assemble_wall_candidates(
        graph, junctions, relationships, viewport_id="vp_1"
    )
    rooms = reconstruct_room_candidates(
        graph, edge_map, document_id="doc_1", viewport_id="vp_1"
    )
    return rooms, walls


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


class TestBasicRelationships:
    def test_two_rooms_sharing_a_wall_are_marked_adjacent_both_ways(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        assert len(updated_rooms) == 2
        room_a, room_b = updated_rooms
        assert room_a.adjacent_room_refs == (room_b.room_ref,)
        assert room_b.adjacent_room_refs == (room_a.room_ref,)

    def test_bounded_by_and_bounds_are_emitted_for_every_room_wall_pair(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        bounded_by = [r for r in relationships if r.relationship_type == TopologyRelationshipType.BOUNDED_BY]
        bounds = [r for r in relationships if r.relationship_type == TopologyRelationshipType.BOUNDS]
        expected_pairs = sum(len(r.bounding_wall_candidate_ids) for r in updated_rooms)
        assert len(bounded_by) == expected_pairs
        assert len(bounds) == expected_pairs
        for rel in bounded_by:
            assert rel.subject_ref.startswith("room_")
            assert rel.object_ref.startswith("wall_")
        for rel in bounds:
            assert rel.subject_ref.startswith("wall_")
            assert rel.object_ref.startswith("room_")

    def test_separates_relationship_references_both_rooms(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        separates = [r for r in relationships if r.relationship_type == TopologyRelationshipType.SEPARATES]
        assert len(separates) >= 1
        room_refs = {r.room_ref for r in updated_rooms}
        for rel in separates:
            assert rel.subject_ref.startswith("wall_")
            assert rel.object_ref in room_refs
            other_side = next(rc for rc in rel.reason_codes if rc.startswith("other_side_room_ref:"))
            assert other_side.split(":", 1)[1] in room_refs

    def test_at_least_one_interior_and_one_exterior_wall(self) -> None:
        # The partition itself is always interior (used by exactly the 2
        # rooms it separates); the left and right outer walls are always
        # exterior (each touches only one room, never split by a T-junction
        # in this exact fixture).
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        interior = [w for w in updated_walls if w.interior_exterior == "interior"]
        exterior = [w for w in updated_walls if w.interior_exterior == "exterior"]
        assert len(interior) >= 1
        assert len(exterior) >= 1

    def test_single_room_has_no_adjacency_and_all_walls_exterior(self) -> None:
        segments = [
            _seg("a", 0, 0, 300, 0),
            _seg("b", 300, 0, 300, 200),
            _seg("c", 300, 200, 0, 200),
            _seg("d", 0, 200, 0, 0),
        ]
        rooms, walls = _full_pipeline(segments)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        assert len(updated_rooms) == 1
        assert updated_rooms[0].adjacent_room_refs == ()
        assert all(w.interior_exterior == "exterior" for w in updated_walls)
        assert not any(r.relationship_type == TopologyRelationshipType.ADJACENT_TO for r in relationships)
        assert not any(r.relationship_type == TopologyRelationshipType.SEPARATES for r in relationships)


class TestAmbiguousWallUsageFailsClosed:
    def test_wall_used_by_three_rooms_skips_adjacency_but_stays_unresolved(self) -> None:
        # A naturally-occurring case: two partitions in a 3-room row each
        # form a T-junction with the shared top/bottom outer wall, which W4
        # correctly merges into ONE continuous WallCandidate per the
        # approved "trunk continues through a T" rule -- that one wall ends
        # up genuinely touched by all three rooms. This must never be
        # arbitrarily resolved to "interior" or "exterior", and must never
        # contribute an ADJACENT_TO/SEPARATES claim.
        rooms, walls = _full_pipeline(_THREE_ROOM_ROW)
        assert len(rooms) == 3
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)

        usage = compute_wall_usage(rooms)
        three_way_wall_ids = {wid for wid, refs in usage.items() if len(set(refs)) >= 3}
        assert len(three_way_wall_ids) >= 1

        for wall in updated_walls:
            if wall.candidate_id in three_way_wall_ids:
                assert wall.interior_exterior == "unresolved"
                assert REASON_ANOMALOUS_WALL_USAGE in wall.reason_codes

        for rel in relationships:
            if rel.relationship_type in (
                TopologyRelationshipType.ADJACENT_TO,
                TopologyRelationshipType.SEPARATES,
            ):
                assert rel.subject_ref not in three_way_wall_ids
                assert not any(
                    rc.startswith("shared_wall_id:") and rc.split(":", 1)[1] in three_way_wall_ids
                    for rc in rel.reason_codes
                )

    def test_neighboring_rooms_in_a_row_are_still_correctly_adjacent_via_partitions(self) -> None:
        # Even though the outer walls fail closed (see above), the two
        # partition walls are each used by exactly 2 rooms and must still
        # correctly establish room1<->room2 and room2<->room3 adjacency.
        rooms, walls = _full_pipeline(_THREE_ROOM_ROW)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        adjacency_pairs = {
            frozenset((r.subject_ref, r.object_ref))
            for r in relationships
            if r.relationship_type == TopologyRelationshipType.ADJACENT_TO
        }
        # 3 rooms in a row -> exactly 2 distinct adjacent pairs (1-2, 2-3).
        assert len(adjacency_pairs) == 2
        sorted_by_x = sorted(updated_rooms, key=lambda r: min(p[0] for p in r.polygon_pdf_pts))
        assert frozenset((sorted_by_x[0].room_ref, sorted_by_x[1].room_ref)) in adjacency_pairs
        assert frozenset((sorted_by_x[1].room_ref, sorted_by_x[2].room_ref)) in adjacency_pairs
        assert frozenset((sorted_by_x[0].room_ref, sorted_by_x[2].room_ref)) not in adjacency_pairs


class TestSharedWallNeverDuplicated:
    def test_shared_wall_remains_one_candidate_referenced_by_both_rooms(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        updated_rooms, updated_walls, relationships = derive_room_wall_relationships(rooms, walls)
        wall_ids_before = {w.candidate_id for w in walls}
        wall_ids_after = {w.candidate_id for w in updated_walls}
        assert wall_ids_before == wall_ids_after  # same set, no new/duplicated wall objects
        room_a, room_b = updated_rooms
        shared = set(room_a.bounding_wall_candidate_ids) & set(room_b.bounding_wall_candidate_ids)
        assert len(shared) >= 1


class TestInvariance:
    def test_shuffled_room_order_produces_identical_relationships(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        shuffled_rooms = list(rooms)
        random.Random(9).shuffle(shuffled_rooms)

        _, _, rel_a = derive_room_wall_relationships(rooms, walls)
        _, _, rel_b = derive_room_wall_relationships(shuffled_rooms, walls)
        assert {r.relationship_id for r in rel_a} == {r.relationship_id for r in rel_b}

    def test_deterministic_replay(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        _, walls_a, rel_a = derive_room_wall_relationships(rooms, walls)
        _, walls_b, rel_b = derive_room_wall_relationships(rooms, walls)
        assert {r.relationship_id for r in rel_a} == {r.relationship_id for r in rel_b}
        assert [w.interior_exterior for w in walls_a] == [w.interior_exterior for w in walls_b]


class TestNoQuantityOrLiveWiring:
    def test_no_quantity_evidence_import_or_construction(self) -> None:
        import pb_wall_room_topology_room_wall_relationships as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_no_semantic_room_labels_touched(self) -> None:
        rooms, walls = _full_pipeline(_TWO_ROOM_PARTITION)
        updated_rooms, _, _ = derive_room_wall_relationships(rooms, walls)
        assert all(r.label == "" for r in updated_rooms)

    def test_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_room_wall_relationships" not in source
