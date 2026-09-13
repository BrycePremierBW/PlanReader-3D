from __future__ import annotations

import math
import random

import pytest

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import JunctionType
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_topology


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


def _assemble(segments, **classify_kwargs):
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id="doc_1", page_id="p1", viewport_id="vp_1", **classify_kwargs
    )
    return assemble_wall_topology(graph, junctions, relationships, viewport_id="vp_1")


def _wall_endpoints(wall):
    return {
        tuple(round(c, 3) for c in wall.centerline_pts[0]),
        tuple(round(c, 3) for c in wall.centerline_pts[-1]),
    }


class TestBasicChainAssembly:
    def test_01_simple_straight_wall_is_one_candidate(self) -> None:
        walls, junctions = _assemble([_seg("a", 0, 0, 300, 0)])
        assert len(walls) == 1
        assert walls[0].face_a_segment_ids == ("split_0",)
        assert _wall_endpoints(walls[0]) == {(0.0, 0.0), (300.0, 0.0)}

    def test_02_fragmented_straight_wall_becomes_one_chain(self) -> None:
        walls, junctions = _assemble(
            [_seg("a", 0, 0, 100, 0), _seg("b", 100, 0, 200, 0), _seg("c", 200, 0, 300, 0)]
        )
        assert len(walls) == 1
        assert _wall_endpoints(walls[0]) == {(0.0, 0.0), (300.0, 0.0)}
        # The two intermediate points are COLLINEAR_CONTINUATION bookkeeping
        # junctions (already merged by W2), each correctly re-keyed to this
        # one wall candidate, never left dangling.
        collinear = [j for j in junctions if j.junction_type == JunctionType.COLLINEAR_CONTINUATION]
        assert len(collinear) == 2
        for j in collinear:
            assert j.incident_wall_candidate_ids == (walls[0].candidate_id,)

    def test_03_l_corner_becomes_two_walls(self) -> None:
        walls, junctions = _assemble([_seg("a", 0, 0, 300, 0), _seg("b", 300, 0, 300, 300)])
        assert len(walls) == 2
        endpoint_sets = [_wall_endpoints(w) for w in walls]
        assert {(0.0, 0.0), (300.0, 0.0)} in endpoint_sets
        assert {(300.0, 0.0), (300.0, 300.0)} in endpoint_sets
        corner = next(j for j in junctions if j.junction_type == JunctionType.L_CORNER)
        assert len(corner.incident_wall_candidate_ids) == 2
        assert len(set(corner.incident_wall_candidate_ids)) == 2  # two DISTINCT walls

    def test_04_t_junction_trunk_continuation_plus_separate_branch(self) -> None:
        walls, junctions = _assemble(
            [
                _seg("bar1", 0, 0, 150, 0),
                _seg("bar2", 150, 0, 300, 0),
                _seg("stem", 150, 0, 150, -80),
            ]
        )
        assert len(walls) == 2
        trunk = next(w for w in walls if len(w.face_a_segment_ids) == 2)
        branch = next(w for w in walls if len(w.face_a_segment_ids) == 1)
        assert _wall_endpoints(trunk) == {(0.0, 0.0), (300.0, 0.0)}
        assert _wall_endpoints(branch) == {(150.0, 0.0), (150.0, -80.0)}
        t_junction = next(j for j in junctions if j.junction_type == JunctionType.T_JUNCTION)
        assert set(t_junction.incident_wall_candidate_ids) == {trunk.candidate_id, branch.candidate_id}

    def test_05_x_crossing_produces_two_logical_wall_continuations(self) -> None:
        walls, junctions = _assemble([_seg("h", -150, 0, 150, 0), _seg("v", 0, -150, 0, 150)])
        assert len(walls) == 2
        endpoint_sets = [_wall_endpoints(w) for w in walls]
        assert {(-150.0, 0.0), (150.0, 0.0)} in endpoint_sets
        assert {(0.0, -150.0), (0.0, 150.0)} in endpoint_sets
        crossing = next(j for j in junctions if j.junction_type == JunctionType.X_CROSSING)
        assert len(set(crossing.incident_wall_candidate_ids)) == 2

    def test_06_multi_way_deterministic_grouping(self) -> None:
        walls, junctions = _assemble(
            [
                _seg("l1", -150, 0, 150, 0),
                _seg("l2", 0, -150, 0, 150),
                _seg("l3", -100, -100, 100, 100),
            ]
        )
        assert len(walls) == 3
        multi = next(j for j in junctions if j.junction_type == JunctionType.MULTI_WAY)
        assert len(set(multi.incident_wall_candidate_ids)) == 3

    def test_07_endpoint_terminates_chain(self) -> None:
        walls, junctions = _assemble([_seg("a", 0, 0, 300, 0)])
        endpoints = [j for j in junctions if j.junction_type == JunctionType.ENDPOINT]
        assert len(endpoints) == 2
        for j in endpoints:
            assert j.incident_wall_candidate_ids == (walls[0].candidate_id,)


class TestDeterminismAndDuplication:
    def test_08_reversed_segment_direction_same_wall_id(self) -> None:
        forward, _ = _assemble([_seg("a", 0, 0, 300, 0)])
        reversed_walls, _ = _assemble([_seg("a", 300, 0, 0, 0)])
        assert forward[0].candidate_id == reversed_walls[0].candidate_id

    def test_09_shuffled_input_order_same_walls(self) -> None:
        segments = [
            _seg("bar1", 0, 0, 150, 0),
            _seg("bar2", 150, 0, 300, 0),
            _seg("stem", 150, 0, 150, -80),
        ]
        shuffled = list(segments)
        random.Random(11).shuffle(shuffled)
        base_walls, _ = _assemble(segments)
        shuffled_walls, _ = _assemble(shuffled)
        assert {w.candidate_id for w in base_walls} == {w.candidate_id for w in shuffled_walls}

    def test_10_translation_invariance_of_structure(self) -> None:
        # Candidate ids are viewport + absolute-position derived, so a
        # translated copy legitimately gets DIFFERENT ids (different real
        # position) -- what must be invariant is the wall COUNT/STRUCTURE.
        segments = [_seg("a", 0, 0, 300, 0), _seg("b", 300, 0, 300, 300)]
        offset = 250.0
        translated = [
            _seg(s["id"], s["x1"] + offset, s["y1"] + offset, s["x2"] + offset, s["y2"] + offset)
            for s in segments
        ]
        base_walls, _ = _assemble(segments)
        translated_walls, _ = _assemble(translated)
        assert len(base_walls) == len(translated_walls) == 2
        base_lengths = sorted(
            round(math.dist(w.centerline_pts[0], w.centerline_pts[-1]), 3) for w in base_walls
        )
        translated_lengths = sorted(
            round(math.dist(w.centerline_pts[0], w.centerline_pts[-1]), 3) for w in translated_walls
        )
        assert base_lengths == translated_lengths

    @staticmethod
    def _rotate(x, y, deg):
        rad = math.radians(deg)
        return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))

    def _assert_rotation_invariant_structure(self, deg: float) -> None:
        segments = [_seg("h", -150, 0, 150, 0), _seg("v", 0, -150, 0, 150)]
        rotated = []
        for s in segments:
            x1, y1 = self._rotate(s["x1"], s["y1"], deg)
            x2, y2 = self._rotate(s["x2"], s["y2"], deg)
            rotated.append(_seg(s["id"], x1, y1, x2, y2))
        base_walls, _ = _assemble(segments)
        rotated_walls, _ = _assemble(rotated)
        assert len(base_walls) == len(rotated_walls) == 2

    def test_11_rotation_invariance_of_structure(self) -> None:
        self._assert_rotation_invariant_structure(41.0)

    def test_11b_rotation_invariance_90deg(self) -> None:
        self._assert_rotation_invariant_structure(90.0)

    def test_11c_rotation_invariance_180deg(self) -> None:
        self._assert_rotation_invariant_structure(180.0)

    def test_11d_rotation_invariance_270deg(self) -> None:
        self._assert_rotation_invariant_structure(270.0)

    def _assert_scale_invariant_structure(self, factor: float) -> None:
        segments = [_seg("a", 0, 0, 300, 0), _seg("b", 300, 0, 300, 300)]
        scaled = [
            _seg(s["id"], s["x1"] * factor, s["y1"] * factor, s["x2"] * factor, s["y2"] * factor)
            for s in segments
        ]
        base_walls, _ = _assemble(segments)
        scaled_walls, _ = _assemble(scaled)
        assert len(base_walls) == len(scaled_walls) == 2
        base_lengths = sorted(
            round(math.dist(w.centerline_pts[0], w.centerline_pts[-1]), 3) for w in base_walls
        )
        scaled_lengths = sorted(
            round(math.dist(w.centerline_pts[0], w.centerline_pts[-1]), 3) for w in scaled_walls
        )
        for base_len, scaled_len in zip(base_lengths, scaled_lengths):
            assert scaled_len == pytest.approx(base_len * factor, rel=1e-6)

    def test_11e_scale_invariance_half(self) -> None:
        self._assert_scale_invariant_structure(0.5)

    def test_11f_scale_invariance_1_35x(self) -> None:
        self._assert_scale_invariant_structure(1.35)

    def test_11g_scale_invariance_double(self) -> None:
        self._assert_scale_invariant_structure(2.0)

    def test_12_split_merge_invariance_same_wall_id(self) -> None:
        # Semantic topology invariance: the SAME overall wall span, drawn as
        # one segment vs. pre-split into three, yields the IDENTICAL
        # candidate id -- because the id is derived from the chain's final
        # boundary geometry, not from the (necessarily different)
        # contributing Stage-A edge id lists.
        one_piece, _ = _assemble([_seg("a", 0, 0, 300, 0)])
        three_pieces, _ = _assemble(
            [_seg("a", 0, 0, 100, 0), _seg("b", 100, 0, 200, 0), _seg("c", 200, 0, 300, 0)]
        )
        assert one_piece[0].candidate_id == three_pieces[0].candidate_id
        # Source-evidence identity is correctly NOT invariant: the
        # contributing edge lists differ (this is the distinction the W4
        # brief explicitly asks to be made explicit, not blurred).
        assert one_piece[0].face_a_segment_ids != three_pieces[0].face_a_segment_ids

    def test_13_duplicate_edge_id_does_not_create_extra_wall(self) -> None:
        walls, _ = _assemble([_seg("a", 0, 0, 300, 0)])
        walls_with_dup, _ = _assemble(
            [_seg("wall", 0, 0, 300, 0), _seg("wall_copy", 0, 0, 300, 0)]
        )
        assert len(walls_with_dup) == 1
        assert walls[0].candidate_id == walls_with_dup[0].candidate_id

    def test_14_overlapping_duplicate_line_produces_no_second_candidate(self) -> None:
        # Same case as 13, phrased as the brief's own named scenario: an
        # overlapping duplicate trace directly over a real wall.
        walls, junctions = _assemble(
            [_seg("wall", 0, 0, 300, 0), _seg("wall_copy", 0, 0, 300, 0)]
        )
        assert len(walls) == 1
        for j in junctions:
            assert j.incident_wall_candidate_ids == (walls[0].candidate_id,)

    def test_18_wall_candidate_id_deterministic_replay(self) -> None:
        segments = [_seg("a", 0, 0, 300, 0), _seg("b", 300, 0, 300, 300)]
        first, _ = _assemble(segments)
        second, _ = _assemble(segments)
        assert {w.candidate_id for w in first} == {w.candidate_id for w in second}


class TestAmbiguityFailClosed:
    def test_15_ambiguous_short_arm_case_blocks_chain_merge(self) -> None:
        walls, junctions = _assemble([_seg("wall", 0, 0, 300, 0), _seg("stub", 150, 0, 155, 15)])
        # The bar must NOT merge through the ambiguous point into one wall --
        # three separate candidates: left half, right half, stub.
        assert len(walls) == 3
        endpoint_sets = [_wall_endpoints(w) for w in walls]
        assert {(0.0, 0.0), (150.0, 0.0)} in endpoint_sets
        assert {(150.0, 0.0), (300.0, 0.0)} in endpoint_sets
        blocked = [w for w in walls if any(r.startswith("chain_extension_blocked_by:ambiguous") for r in w.reason_codes)]
        assert len(blocked) >= 2
        ambiguous_junction = next(j for j in junctions if j.junction_type == JunctionType.AMBIGUOUS)
        assert ambiguous_junction.status == EvidenceResolutionStatus.ABSTAINED
        # All three walls touching this point remain real, inspectable
        # candidates (fail-closed via non-merge, not via disappearance).
        assert len(set(ambiguous_junction.incident_wall_candidate_ids)) == 3

    def test_16_near_junction_review_case_blocks_merge(self) -> None:
        walls, junctions = _assemble([_seg("a", 0, 0, 100, 0), _seg("b", 104, 0, 200, 0)])
        assert len(walls) == 2
        review_junctions = [j for j in junctions if j.junction_type == JunctionType.NEAR_JUNCTION_REVIEW]
        assert len(review_junctions) == 2
        for j in review_junctions:
            assert j.status == EvidenceResolutionStatus.ABSTAINED

    def test_17_rejected_annotation_crossing_never_becomes_a_wall(self) -> None:
        # A hatch-layer-tagged segment crossing a real wall must never
        # contribute a wall candidate of its own, and must never merge the
        # real wall's two halves into one (there is no real gap here, but a
        # geometric crossing must still never silently become topology).
        wall = _seg("wall", 0, 0, 300, 0)
        hatch = _seg("hatch", 100, -20, 120, 20, layer="hatch_45")
        walls, junctions = _assemble([wall, hatch])
        assert len(walls) == 1  # the hatch segment produced no candidate at all
        assert _wall_endpoints(walls[0]) == {(0.0, 0.0), (300.0, 0.0)}


class TestJunctionRekeying:
    def test_19_junctions_rekeyed_to_real_wall_candidate_ids(self) -> None:
        walls, junctions = _assemble(
            [
                _seg("bar1", 0, 0, 150, 0),
                _seg("bar2", 150, 0, 300, 0),
                _seg("stem", 150, 0, 150, -80),
            ]
        )
        wall_ids = {w.candidate_id for w in walls}
        for j in junctions:
            for wid in j.incident_wall_candidate_ids:
                assert wid in wall_ids

    def test_20_no_stage_a_raw_edge_ids_left_in_incident_fields(self) -> None:
        walls, junctions = _assemble(
            [_seg("a", 0, 0, 100, 0), _seg("b", 100, 0, 200, 0), _seg("c", 200, 0, 300, 0)]
        )
        for j in junctions:
            for wid in j.incident_wall_candidate_ids:
                assert wid.startswith("wall_"), f"leftover non-wall id: {wid!r}"
                assert not wid.startswith("split_")
                assert not wid.startswith("merged_")

    def test_t_junction_rekey_deduplicates_repeated_bar_arm(self) -> None:
        # The bar's two original arms both belong to the same merged trunk
        # wall -- re-keying must deduplicate to ONE entry for that wall, not
        # two identical entries (which would violate incident id uniqueness).
        _, junctions = _assemble(
            [
                _seg("bar1", 0, 0, 150, 0),
                _seg("bar2", 150, 0, 300, 0),
                _seg("stem", 150, 0, 150, -80),
            ]
        )
        t_junction = next(j for j in junctions if j.junction_type == JunctionType.T_JUNCTION)
        assert len(t_junction.incident_wall_candidate_ids) == 2
        assert len(t_junction.incident_angles_deg) == 2


class TestNoQuantityOrLiveWiring:
    def test_21_no_quantity_evidence_type_anywhere_in_module(self) -> None:
        # The module docstring correctly MENTIONS QuantityEvidence while
        # explaining that it is never produced -- this checks for actual
        # usage (import or construction), not that string's mere presence
        # in prose.
        import pb_wall_room_topology_wall_assembly as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_21b_wall_candidates_carry_no_thickness_or_length(self) -> None:
        walls, _ = _assemble([_seg("a", 0, 0, 300, 0)])
        assert walls[0].thickness_m is None
        assert walls[0].length_m is None

    def test_22_module_is_not_imported_by_the_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_wall_assembly" not in source
        assert "pb_wall_room_topology_junction_classifier" not in source
        assert "pb_wall_room_topology_stage_a" not in source

    def test_22b_module_does_not_import_canonical_building(self) -> None:
        # Same distinction as above: the docstring correctly documents that
        # no conflict with pb_canonical_building was found and that
        # extract_planar_faces was only inspected, not invoked -- this
        # checks for an actual import line, not the module's own prose.
        import pb_wall_room_topology_wall_assembly as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import pb_canonical_building" not in source
        assert "from pb_canonical_building" not in source
        assert "from pb_accuracy_v13_engines_v145" not in source
        assert "import pb_accuracy_v13_engines_v145" not in source
