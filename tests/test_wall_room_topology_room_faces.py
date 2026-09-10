from __future__ import annotations

import math
import random

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
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


def _rooms(segments, **kwargs):
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id="doc_1", page_id="p1", viewport_id="vp_1"
    )
    walls, edge_map = assemble_wall_candidates(
        graph, junctions, relationships, viewport_id="vp_1"
    )
    rooms = reconstruct_room_candidates(
        graph, edge_map, document_id="doc_1", viewport_id="vp_1", **kwargs
    )
    return rooms, walls


def _rect(prefix, x0, y0, x1, y1):
    return [
        _seg(f"{prefix}0", x0, y0, x1, y0),
        _seg(f"{prefix}1", x1, y0, x1, y1),
        _seg(f"{prefix}2", x1, y1, x0, y1),
        _seg(f"{prefix}3", x0, y1, x0, y0),
    ]


class TestBasicRoomReconstruction:
    def test_01_single_rectangle(self) -> None:
        rooms, walls = _rooms(_rect("r", 0, 0, 300, 200))
        assert len(rooms) == 1
        room = rooms[0]
        assert math.isclose(room.area_page_pts2, 60000.0)
        assert room.status == EvidenceResolutionStatus.CANDIDATE
        assert len(room.bounding_wall_candidate_ids) == 4
        assert room.exterior_boundary is True
        assert room.has_voids is False
        assert room.floor_area_m2 is None  # no quantity authority
        assert room.label == ""  # no semantic naming yet

    def test_02_two_room_partition(self) -> None:
        segments = [
            _seg("a", 0, 0, 300, 0),
            _seg("b", 300, 0, 300, 200),
            _seg("c", 300, 200, 150, 200),
            _seg("d", 0, 200, 0, 0),
            _seg("e", 150, 200, 0, 200),
            _seg("partition", 150, 0, 150, 200),
        ]
        rooms, walls = _rooms(segments)
        assert len(rooms) == 2
        areas = sorted(round(r.area_page_pts2, 1) for r in rooms)
        assert areas == [30000.0, 30000.0]
        # The shared partition wall is used by both rooms.
        partition_wall = next(w for w in walls if _wall_is_vertical_at(w, 150))
        usage = sum(1 for r in rooms if partition_wall.candidate_id in r.bounding_wall_candidate_ids)
        assert usage == 2
        assert all(r.exterior_boundary for r in rooms)

    def test_03_t_plan(self) -> None:
        # A T-shaped enclosure: a wide top bar with a stem hanging down,
        # forming one single non-convex closed room.
        segments = [
            _seg("a", 0, 0, 300, 0),
            _seg("b", 300, 0, 300, 100),
            _seg("c", 300, 100, 200, 100),
            _seg("d", 200, 100, 200, 300),
            _seg("e", 200, 300, 100, 300),
            _seg("f", 100, 300, 100, 100),
            _seg("g", 100, 100, 0, 100),
            _seg("h", 0, 100, 0, 0),
        ]
        rooms, _ = _rooms(segments)
        assert len(rooms) == 1
        assert rooms[0].area_page_pts2 > 0

    def test_04_l_shaped_enclosure(self) -> None:
        segments = [
            _seg("a", 0, 0, 300, 0),
            _seg("b", 300, 0, 300, 150),
            _seg("c", 300, 150, 150, 150),
            _seg("d", 150, 150, 150, 300),
            _seg("e", 150, 300, 0, 300),
            _seg("f", 0, 300, 0, 0),
        ]
        rooms, _ = _rooms(segments)
        assert len(rooms) == 1
        # Full bounding rect would be 300*300=90000; the L removes one 150x150 corner.
        assert math.isclose(rooms[0].area_page_pts2, 300 * 300 - 150 * 150)

    def test_05_multiple_adjacent_rooms(self) -> None:
        # Three rooms in a row sharing two partition walls.
        segments = [
            _seg("top", 0, 0, 300, 0),
            _seg("bottom", 0, 200, 300, 200),
            _seg("left", 0, 0, 0, 200),
            _seg("right", 300, 0, 300, 200),
            _seg("p1", 100, 0, 100, 200),
            _seg("p2", 200, 0, 200, 200),
        ]
        rooms, _ = _rooms(segments)
        assert len(rooms) == 3
        areas = sorted(round(r.area_page_pts2, 1) for r in rooms)
        assert areas == [20000.0, 20000.0, 20000.0]

    def test_06_nested_inner_enclosure_flags_outer_void(self) -> None:
        outer = _rect("o", 0, 0, 400, 300)
        inner = _rect("i", 150, 100, 250, 200)
        rooms, _ = _rooms(outer + inner)
        assert len(rooms) == 2
        outer_room = max(rooms, key=lambda r: r.area_page_pts2)
        inner_room = min(rooms, key=lambda r: r.area_page_pts2)
        assert outer_room.has_voids is True
        assert inner_room.has_voids is False

    def test_07_open_boundary_is_not_a_room(self) -> None:
        # Three of four walls -- never closes.
        segments = [
            _seg("a", 0, 0, 300, 0),
            _seg("b", 300, 0, 300, 200),
            _seg("c", 300, 200, 0, 200),
        ]
        rooms, _ = _rooms(segments)
        assert rooms == []


class TestTinyLoopAndDuplicates:
    def test_08_tiny_spurious_loop_flagged_for_review_not_deleted_not_accepted(self) -> None:
        real_room = _rect("r", 0, 0, 300, 200)
        # Larger than the Stage-A snap tolerance (2.5pt default) so it
        # survives as its own distinguishable polygon, but tiny relative to
        # the real room.
        tiny_loop = _rect("t", 350, 50, 360, 60)
        rooms, _ = _rooms(real_room + tiny_loop)
        assert len(rooms) == 2
        tiny = min(rooms, key=lambda r: r.area_page_pts2)
        real = max(rooms, key=lambda r: r.area_page_pts2)
        assert tiny.status == EvidenceResolutionStatus.ABSTAINED
        assert "tiny_spurious_loop_flagged_for_review" in tiny.reason_codes
        assert real.status == EvidenceResolutionStatus.CANDIDATE

    def test_09_duplicate_line_does_not_duplicate_the_room(self) -> None:
        segments = _rect("r", 0, 0, 300, 200) + [_seg("dup", 0, 0, 300, 0)]
        rooms, _ = _rooms(segments)
        assert len(rooms) == 1
        assert math.isclose(rooms[0].area_page_pts2, 60000.0)

    def test_10_fragmented_walls_still_close_one_room(self) -> None:
        segments = [
            _seg("a1", 0, 0, 100, 0),
            _seg("a2", 100, 0, 200, 0),
            _seg("a3", 200, 0, 300, 0),
            _seg("b", 300, 0, 300, 200),
            _seg("c", 300, 200, 0, 200),
            _seg("d", 0, 200, 0, 0),
        ]
        rooms, _ = _rooms(segments)
        assert len(rooms) == 1
        assert math.isclose(rooms[0].area_page_pts2, 60000.0)


class TestInvariance:
    def test_11_shuffled_input_order(self) -> None:
        segments = _rect("r", 0, 0, 300, 200)
        shuffled = list(segments)
        random.Random(5).shuffle(shuffled)
        base_rooms, _ = _rooms(segments)
        shuffled_rooms, _ = _rooms(shuffled)
        assert {r.room_ref for r in base_rooms} == {r.room_ref for r in shuffled_rooms}

    def test_12_direction_reversal(self) -> None:
        segments = _rect("r", 0, 0, 300, 200)
        reversed_dir = [
            _seg(s["id"], s["x2"], s["y2"], s["x1"], s["y1"]) for s in segments
        ]
        base_rooms, _ = _rooms(segments)
        reversed_rooms, _ = _rooms(reversed_dir)
        assert {r.room_ref for r in base_rooms} == {r.room_ref for r in reversed_rooms}

    def test_13_translation_invariance_of_structure(self) -> None:
        segments = _rect("r", 0, 0, 300, 200)
        offset = 500.0
        translated = [
            _seg(s["id"], s["x1"] + offset, s["y1"] + offset, s["x2"] + offset, s["y2"] + offset)
            for s in segments
        ]
        base_rooms, _ = _rooms(segments)
        translated_rooms, _ = _rooms(translated)
        assert len(base_rooms) == len(translated_rooms) == 1
        assert math.isclose(base_rooms[0].area_page_pts2, translated_rooms[0].area_page_pts2)

    def test_14_rotation_invariance_of_structure(self) -> None:
        def rotate(x, y, deg):
            rad = math.radians(deg)
            return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))

        segments = _rect("r", 0, 0, 300, 200)
        rotated = []
        for s in segments:
            x1, y1 = rotate(s["x1"], s["y1"], 29.0)
            x2, y2 = rotate(s["x2"], s["y2"], 29.0)
            rotated.append(_seg(s["id"], x1, y1, x2, y2))
        base_rooms, _ = _rooms(segments)
        rotated_rooms, _ = _rooms(rotated)
        assert len(base_rooms) == len(rotated_rooms) == 1
        assert math.isclose(base_rooms[0].area_page_pts2, rotated_rooms[0].area_page_pts2, rel_tol=1e-6)

    def test_15_split_merge_representation_invariance(self) -> None:
        one_piece = _rect("r", 0, 0, 300, 200)
        fragmented = [
            _seg("a1", 0, 0, 100, 0),
            _seg("a2", 100, 0, 300, 0),
            _seg("b", 300, 0, 300, 200),
            _seg("c", 300, 200, 0, 200),
            _seg("d", 0, 200, 0, 0),
        ]
        one_piece_rooms, _ = _rooms(one_piece)
        fragmented_rooms, _ = _rooms(fragmented)
        assert one_piece_rooms[0].room_ref == fragmented_rooms[0].room_ref

    def test_18_deterministic_replay(self) -> None:
        segments = _rect("r", 0, 0, 300, 200)
        first, _ = _rooms(segments)
        second, _ = _rooms(segments)
        assert {r.room_ref for r in first} == {r.room_ref for r in second}


class TestOuterFaceAndWallReferences:
    def test_16_outer_unbounded_face_never_appears(self) -> None:
        # Rectangle with one internal partition: exactly 2 rooms, never a
        # spurious 3rd "whole building" face.
        segments = [
            _seg("top", 0, 0, 300, 0),
            _seg("bottom", 0, 200, 300, 200),
            _seg("left", 0, 0, 0, 200),
            _seg("right", 300, 0, 300, 200),
            _seg("p", 150, 0, 150, 200),
        ]
        rooms, _ = _rooms(segments)
        assert len(rooms) == 2

    def test_17_wall_boundary_ids_reference_real_wall_candidates(self) -> None:
        rooms, walls = _rooms(_rect("r", 0, 0, 300, 200))
        wall_ids = {w.candidate_id for w in walls}
        for room in rooms:
            for wall_id in room.bounding_wall_candidate_ids:
                assert wall_id in wall_ids
                assert wall_id.startswith("wall_")


class TestNoQuantityOrLiveWiring:
    def test_19_no_quantity_evidence_import_or_construction(self) -> None:
        import pb_wall_room_topology_room_faces as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_19b_no_floor_area_authority_produced(self) -> None:
        rooms, _ = _rooms(_rect("r", 0, 0, 300, 200))
        for room in rooms:
            assert room.floor_area_m2 is None
            assert room.polygon_m is None
            assert room.scale_source == ""

    def test_20_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_room_faces" not in source

    def test_20b_does_not_edit_shared_planar_face_module(self) -> None:
        # This module must call extract_planar_faces, never redefine it.
        import pb_wall_room_topology_room_faces as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "def extract_planar_faces" not in source
        assert "from pb_accuracy_v13_engines_v145 import extract_planar_faces" in source


def _wall_is_vertical_at(wall, x_value: float) -> bool:
    xs = {round(p[0], 3) for p in wall.centerline_pts}
    return xs == {round(x_value, 3)}
