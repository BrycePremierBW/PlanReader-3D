from __future__ import annotations

import random

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import JunctionType, TopologyRelationshipType
from pb_wall_room_topology_junction_classifier import (
    classify_junctions,
    deduplicate_coincident_edges,
    detect_near_miss_node_pairs,
    find_rejected_non_wall_crossings,
)
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport, filter_structural_segments


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


def _classify(segments, **kwargs):
    graph = build_wall_graph_for_viewport(segments)
    return classify_junctions(graph, document_id="doc_1", page_id="p1", viewport_id="vp_1", **kwargs)


def _types_at(junctions):
    return {tuple(round(c, 3) for c in j.position_pt): j.junction_type for j in junctions}


class TestBasicJunctionTypes:
    def test_t1_rectangle_is_four_l_corners(self) -> None:
        segments = [
            _seg("s0", 0, 0, 300, 0),
            _seg("s1", 300, 0, 300, 300),
            _seg("s2", 300, 300, 0, 300),
            _seg("s3", 0, 300, 0, 0),
        ]
        junctions, relationships = _classify(segments)
        assert len(junctions) == 4
        assert all(j.junction_type == JunctionType.L_CORNER for j in junctions)
        assert all(j.status == EvidenceResolutionStatus.CANDIDATE for j in junctions)
        assert len(relationships) == 4
        assert all(r.relationship_type == TopologyRelationshipType.CONNECTED_TO for r in relationships)

    def test_l_shape_has_five_l_corners_and_no_misclassification(self) -> None:
        # An L-shaped polygon: 6 vertices, 6 corners, all convex/reflex L corners.
        segments = [
            _seg("a", 0, 0, 300, 0),
            _seg("b", 300, 0, 300, 150),
            _seg("c", 300, 150, 150, 150),
            _seg("d", 150, 150, 150, 300),
            _seg("e", 150, 300, 0, 300),
            _seg("f", 0, 300, 0, 0),
        ]
        junctions, _ = _classify(segments)
        assert len(junctions) == 6
        assert all(j.junction_type == JunctionType.L_CORNER for j in junctions)

    def test_t_junction_classifies_bar_and_stem_correctly(self) -> None:
        segments = [
            _seg("bar1", 0, 0, 150, 0),
            _seg("bar2", 150, 0, 300, 0),
            _seg("stem", 150, 0, 150, -80),
        ]
        junctions, relationships = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(150.0, 0.0)] == JunctionType.T_JUNCTION
        assert by_type[(0.0, 0.0)] == JunctionType.ENDPOINT
        assert by_type[(300.0, 0.0)] == JunctionType.ENDPOINT
        assert by_type[(150.0, -80.0)] == JunctionType.ENDPOINT

        branches = [r for r in relationships if r.relationship_type == TopologyRelationshipType.BRANCHES_FROM]
        continues = [r for r in relationships if r.relationship_type == TopologyRelationshipType.CONTINUES_AS]
        assert len(branches) == 2  # stem -> each bar edge
        assert len(continues) == 1  # the bar pair itself

    def test_x_crossing_classifies_all_four_arms(self) -> None:
        segments = [_seg("h", -150, 0, 150, 0), _seg("v", 0, -150, 0, 150)]
        junctions, relationships = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(0.0, 0.0)] == JunctionType.X_CROSSING
        assert sum(1 for t in by_type.values() if t == JunctionType.ENDPOINT) == 4
        intersects = [r for r in relationships if r.relationship_type == TopologyRelationshipType.INTERSECTS]
        assert len(intersects) == 4

    def test_multi_way_six_arms_cleanly_paired(self) -> None:
        # Three straight lines crossing at one point: 6 arms, 3 clean through-pairs.
        segments = [
            _seg("l1", -150, 0, 150, 0),
            _seg("l2", 0, -150, 0, 150),
            _seg("l3", -100, -100, 100, 100),
        ]
        junctions, _ = _classify(segments)
        center = next(j for j in junctions if j.position_pt == (0.0, 0.0))
        assert center.junction_type == JunctionType.MULTI_WAY

    def test_three_way_non_collinear_star_is_unresolved(self) -> None:
        segments = [
            _seg("a", 0, 0, 150, 0),
            _seg("b", 0, 0, -100, 130),
            _seg("c", 0, 0, -100, -130),
        ]
        junctions, _ = _classify(segments)
        center = next(j for j in junctions if j.position_pt == (0.0, 0.0))
        assert center.junction_type == JunctionType.UNRESOLVED
        assert center.status == EvidenceResolutionStatus.ABSTAINED
        assert "three_way_non_collinear_star" in center.reason_codes

    def test_collinear_continuation_classified_when_merge_did_not_run(self) -> None:
        # Directly exercise the classifier's own degree-2-collinear path,
        # bypassing Stage A's merge, by handing it an already-snapped graph.
        graph = {
            "nodes": [
                {"id": 0, "x": 0.0, "y": 0.0, "samples": 1, "degree": 1},
                {"id": 1, "x": 150.0, "y": 0.0, "samples": 1, "degree": 2},
                {"id": 2, "x": 300.0, "y": 0.0, "samples": 1, "degree": 1},
            ],
            "edges": [
                {"id": "e0", "a": 0, "b": 1, "x1": 0.0, "y1": 0.0, "x2": 150.0, "y2": 0.0,
                 "angle_deg": 0.0, "length_pt": 150.0},
                {"id": "e1", "a": 1, "b": 2, "x1": 150.0, "y1": 0.0, "x2": 300.0, "y2": 0.0,
                 "angle_deg": 0.0, "length_pt": 150.0},
            ],
            "adjacency": {0: [0], 1: [0, 1], 2: [1]},
        }
        junctions, relationships = classify_junctions(
            graph, document_id="d", page_id="p", viewport_id="v"
        )
        mid = next(j for j in junctions if j.position_pt == (150.0, 0.0))
        assert mid.junction_type == JunctionType.L_CORNER or mid.junction_type == JunctionType.COLLINEAR_CONTINUATION
        # angle_delta(0,0) == 0 so this must resolve to the collinear path.
        assert mid.junction_type == JunctionType.COLLINEAR_CONTINUATION
        continues = [r for r in relationships if r.relationship_type == TopologyRelationshipType.CONTINUES_AS]
        assert len(continues) == 1


class TestAmbiguousShortArmDemotion:
    def test_short_stub_touching_long_wall_is_ambiguous_not_t_junction(self) -> None:
        segments = [_seg("wall", 0, 0, 300, 0), _seg("stub", 150, 0, 155, 15)]
        junctions, _ = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(150.0, 0.0)] == JunctionType.AMBIGUOUS
        junction = next(j for j in junctions if j.position_pt == (150.0, 0.0))
        assert junction.status == EvidenceResolutionStatus.ABSTAINED
        assert "short_isolated_arm_present" in junction.reason_codes

    def test_comparable_length_t_junction_is_not_demoted(self) -> None:
        # A stem comparable in length to the bar arms must classify cleanly.
        segments = [
            _seg("bar1", 0, 0, 150, 0),
            _seg("bar2", 150, 0, 300, 0),
            _seg("stem", 150, 0, 150, -140),
        ]
        junctions, _ = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(150.0, 0.0)] == JunctionType.T_JUNCTION

    def test_short_but_non_dead_end_arm_is_not_demoted(self) -> None:
        # The short arm continues on to further structure (its far node is not
        # a bare degree-1 dead end) -- a real, evidenced short return, not a
        # suspicious isolated stub.
        segments = [
            _seg("bar1", 0, 0, 150, 0),
            _seg("bar2", 150, 0, 300, 0),
            _seg("stem", 150, 0, 150, -15),
            _seg("stem_continues", 150, -15, 250, -15),
        ]
        junctions, _ = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(150.0, 0.0)] == JunctionType.T_JUNCTION


class TestNearMissReview:
    def test_two_disconnected_wall_ends_within_review_band_are_flagged(self) -> None:
        segments = [_seg("a", 0, 0, 100, 0), _seg("b", 104, 0, 200, 0)]
        junctions, _ = _classify(segments, snap_tolerance_pt=2.5)
        near_miss = [j for j in junctions if j.junction_type == JunctionType.NEAR_JUNCTION_REVIEW]
        assert len(near_miss) == 2
        positions = {j.position_pt for j in near_miss}
        assert positions == {(100.0, 0.0), (104.0, 0.0)}
        for j in near_miss:
            assert j.status == EvidenceResolutionStatus.ABSTAINED
            assert any(r.startswith("near_miss_partner_node_id:") for r in j.reason_codes)

    def test_wall_ends_far_apart_are_not_flagged(self) -> None:
        segments = [_seg("a", 0, 0, 100, 0), _seg("b", 500, 0, 600, 0)]
        junctions, _ = _classify(segments)
        assert all(j.junction_type != JunctionType.NEAR_JUNCTION_REVIEW for j in junctions)

    def test_junction_internal_nodes_are_never_flagged_as_near_miss(self) -> None:
        # Regression test for a real bug found during development: comparing
        # ALL node pairs (not just degree-1 dangling ends) caused the shared
        # center node of a T/X junction to be misclassified as a near-miss
        # against its own directly-connected neighbors. detect_near_miss_node_pairs
        # must only ever consider degree-1 nodes, and a junction's own
        # multi-way center (degree >= 3) must never be flagged.
        segments = [_seg("h", -150, 0, 150, 0), _seg("v", 0, -150, 0, 150)]
        graph = build_wall_graph_for_viewport(segments)
        pairs = detect_near_miss_node_pairs(graph, snap_tolerance_pt=2.5)
        flagged_node_ids = {n for pair in pairs for n in pair[:2]}
        center_node = next(n for n in graph["nodes"] if (n["x"], n["y"]) == (0.0, 0.0))
        assert center_node["id"] not in flagged_node_ids
        junctions, _ = classify_junctions(
            graph, document_id="d", page_id="p", viewport_id="v", snap_tolerance_pt=2.5
        )
        by_type = _types_at(junctions)
        assert by_type[(0.0, 0.0)] == JunctionType.X_CROSSING


class TestDuplicateEdgeHandling:
    def test_duplicate_line_over_wall_is_deduplicated(self) -> None:
        segments = [_seg("wall", 0, 0, 300, 0), _seg("wall_copy", 0, 0, 300, 0)]
        graph = build_wall_graph_for_viewport(segments)
        assert len(graph["edges"]) == 2  # Stage A does not itself dedupe
        deduped, removed = deduplicate_coincident_edges(graph)
        assert len(deduped["edges"]) == 1
        assert removed == ["split_1"]

    def test_classify_junctions_applies_dedup_internally(self) -> None:
        segments = [_seg("wall", 0, 0, 300, 0), _seg("wall_copy", 0, 0, 300, 0)]
        junctions, relationships = _classify(segments)
        # Only two real endpoints -- the duplicate edge must not create a
        # phantom second wall or any extra junction. Each endpoint correctly
        # still produces its own TERMINATES_AT relationship for the single
        # (deduplicated) edge; what must NOT appear is a second, redundant
        # pair of relationships for the discarded duplicate edge.
        assert len(junctions) == 2
        assert all(j.junction_type == JunctionType.ENDPOINT for j in junctions)
        assert len(relationships) == 2
        assert all(r.relationship_type == TopologyRelationshipType.TERMINATES_AT for r in relationships)
        assert {r.from_edge_id for r in relationships} == {"split_0"}


class TestRejectedNonWallCrossings:
    def test_hatch_crossing_wall_produces_no_real_junction_but_a_recorded_rejection(self) -> None:
        wall = _seg("wall", 0, 0, 300, 0)
        hatch = _seg("hatch", 100, -20, 120, 20, layer="hatch_45")
        kept, excluded = filter_structural_segments([wall, hatch])
        graph = build_wall_graph_for_viewport([wall, hatch])
        junctions, _ = classify_junctions(graph, document_id="d", page_id="p", viewport_id="v")
        assert all(j.junction_type != JunctionType.X_CROSSING for j in junctions)
        assert all(j.junction_type != JunctionType.T_JUNCTION for j in junctions)
        assert len(junctions) == 2  # just the wall's own two endpoints

        rejected = find_rejected_non_wall_crossings(
            graph, excluded, document_id="d", page_id="p", viewport_id="v"
        )
        assert len(rejected) == 1
        assert rejected[0].junction_type == JunctionType.REJECTED_NON_WALL_CROSSING
        assert rejected[0].status == EvidenceResolutionStatus.ABSTAINED
        assert "hatch_layer_excluded" in rejected[0].reason_codes
        assert round(rejected[0].position_pt[0], 1) == 110.0

    def test_dimension_line_crossing_wall_is_rejected(self) -> None:
        wall = _seg("wall", 0, 0, 300, 0)
        dim_line = _seg("dim", 100, -20, 120, 20, layer="dimensions")
        kept, excluded = filter_structural_segments([wall, dim_line])
        graph = build_wall_graph_for_viewport([wall, dim_line])
        rejected = find_rejected_non_wall_crossings(
            graph, excluded, document_id="d", page_id="p", viewport_id="v"
        )
        assert len(rejected) == 1
        assert "dimension_layer_excluded" in rejected[0].reason_codes

    def test_text_box_border_crossing_wall_is_rejected_when_layer_tagged(self) -> None:
        wall = _seg("wall", 0, 0, 300, 0)
        border = _seg("box_border", 100, -20, 120, 20, layer="TEXT-FRAME-1")
        kept, excluded = filter_structural_segments([wall, border])
        graph = build_wall_graph_for_viewport([wall, border])
        rejected = find_rejected_non_wall_crossings(
            graph, excluded, document_id="d", page_id="p", viewport_id="v"
        )
        assert len(rejected) == 1
        assert "text_frame_layer_excluded" in rejected[0].reason_codes

    def test_dashed_annotation_leader_crossing_wall_is_rejected(self) -> None:
        wall = _seg("wall", 0, 0, 300, 0)
        leader = _seg("leader", 100, -20, 120, 20, dashes="[2 2] 0")
        kept, excluded = filter_structural_segments([wall, leader])
        graph = build_wall_graph_for_viewport([wall, leader])
        rejected = find_rejected_non_wall_crossings(
            graph, excluded, document_id="d", page_id="p", viewport_id="v"
        )
        assert len(rejected) == 1
        assert "dashed_line_excluded" in rejected[0].reason_codes


class TestFalsePositiveCoverageSummary:
    """One test per false-positive case named explicitly in the W3 brief,
    each asserting the *specific* protection mechanism responsible."""

    def test_furniture_edge_crossing_wall_is_ambiguous_not_confident(self) -> None:
        # A short, solid, unlabeled segment (no dash/layer signal at all --
        # furniture legs are typically drawn as plain lines) touching a long
        # wall. Protected by the short-isolated-arm demotion (TestAmbiguousShortArmDemotion),
        # not by the Stage-A layer/dash filter, since real furniture linework
        # usually carries neither.
        segments = [_seg("wall", 0, 0, 300, 0), _seg("chair_leg", 150, 0, 152, 12)]
        junctions, _ = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(150.0, 0.0)] == JunctionType.AMBIGUOUS

    def test_short_decorative_line_touching_wall_is_ambiguous_not_confident(self) -> None:
        segments = [_seg("wall", 0, 0, 300, 0), _seg("tick_mark", 200, 0, 203, 5)]
        junctions, _ = _classify(segments)
        by_type = _types_at(junctions)
        assert by_type[(200.0, 0.0)] == JunctionType.AMBIGUOUS

    def test_two_near_but_not_connected_wall_segments_flagged_for_review(self) -> None:
        segments = [_seg("a", 0, 0, 100, 0), _seg("b", 104, 0, 200, 0)]
        junctions, _ = _classify(segments)
        assert any(j.junction_type == JunctionType.NEAR_JUNCTION_REVIEW for j in junctions)

    def test_duplicate_line_directly_over_wall_produces_no_extra_topology(self) -> None:
        segments = [_seg("wall", 0, 0, 300, 0), _seg("wall_copy", 0, 0, 300, 0)]
        junctions, relationships = _classify(segments)
        assert len(junctions) == 2
        # No relationship should ever reference the discarded duplicate edge.
        assert all(r.from_edge_id == "split_0" for r in relationships)

    def test_duplicate_line_spanning_a_collinear_merge_does_not_crash(self) -> None:
        # Real-drawing regression (found running the pipeline against Baghau
        # p36): a wall drawn as two collinear fragments sharing one endpoint
        # (Stage A's own merge_collinear_degree_two_nodes replaces them with
        # one "merged_..." edge spanning the shared node's own two FAR
        # endpoints, and records that new edge's id on the shared node's
        # "merged_into_edge" field) PLUS a separate line spanning exactly
        # those same two far endpoints directly (here: split_segments_at_
        # intersections does not split a line at a point where only another
        # line's own endpoint -- not a true crossing -- touches its
        # interior, so a full-span duplicate stays whole and becomes exactly
        # coincident, by node pair, with the merged edge). This classifier's
        # own deduplicate_coincident_edges pass then discards the merged
        # edge as a "duplicate" of that unrelated edge. Before the fix,
        # classify_junctions still hardcoded COLLINEAR_CONTINUATION for the
        # shared node even though its merged_into_edge target no longer
        # existed, building a JunctionCandidate with zero incident ids and
        # crashing __post_init__. The shared node must fail closed to
        # UNRESOLVED with an explicit reason code instead of crashing --
        # and, just as importantly, must NOT silently reference the
        # surviving duplicate edge, since that edge (by construction here)
        # does not actually touch this node's own location and claiming it
        # would misrepresent which physical span is really resolved.
        segments = [
            _seg("a", 0, 0, 50, 0),
            _seg("b", 50, 0, 100, 0),
            _seg("duplicate_full_span", 0, 0, 100, 0),
        ]
        junctions, _ = _classify(segments)
        by_type = _types_at(junctions)
        # (0, 0) is the node Stage A's own collinear merge absorbed (its two
        # original incident edges -- "a" and the whole "duplicate_full_span"
        # -- get fused into one new far-to-far edge); that new edge is the
        # one this classifier's own dedup then discards as coincident with
        # "b", which is what must fail closed rather than crash or mislead.
        assert by_type[(0.0, 0.0)] == JunctionType.UNRESOLVED
        merge_point = next(j for j in junctions if j.position_pt == (0.0, 0.0))
        assert "collinear_merge_target_edge_missing" in merge_point.reason_codes
        assert merge_point.incident_wall_candidate_ids == ()


class TestMetamorphicInvariance:
    def _fixture(self):
        return [
            _seg("bar1", 0, 0, 150, 0),
            _seg("bar2", 150, 0, 300, 0),
            _seg("stem", 150, 0, 150, -80),
        ]

    def _type_multiset(self, junctions):
        return sorted(j.junction_type.value for j in junctions)

    def test_translation_invariance(self) -> None:
        offset = 137.5
        translated = [
            _seg(s["id"], s["x1"] + offset, s["y1"] + offset, s["x2"] + offset, s["y2"] + offset)
            for s in self._fixture()
        ]
        base_junctions, _ = _classify(self._fixture())
        translated_junctions, _ = _classify(translated)
        assert self._type_multiset(base_junctions) == self._type_multiset(translated_junctions)

    def test_input_segment_order_invariance(self) -> None:
        segments = self._fixture()
        shuffled = list(segments)
        random.Random(7).shuffle(shuffled)
        base_junctions, _ = _classify(segments)
        shuffled_junctions, _ = _classify(shuffled)
        assert self._type_multiset(base_junctions) == self._type_multiset(shuffled_junctions)

    def test_vector_object_order_invariance_via_multiple_permutations(self) -> None:
        segments = self._fixture()
        permutations = [
            segments,
            list(reversed(segments)),
            [segments[2], segments[0], segments[1]],
        ]
        results = [self._type_multiset(_classify(p)[0]) for p in permutations]
        assert all(r == results[0] for r in results)

    def test_collinear_segment_splitting_invariance(self) -> None:
        # Pre-splitting one arm of the bar into extra collinear pieces adds
        # its own (correctly classified) COLLINEAR_CONTINUATION bookkeeping
        # entry at the new split point -- that is expected, not a metamorphic
        # violation. The property under test is narrower and more meaningful:
        # the actual T-junction's own classification at (150, 0) must be
        # identical regardless of how its collinear arm was pre-split.
        pre_split = [
            _seg("bar1a", 0, 0, 80, 0),
            _seg("bar1b", 80, 0, 150, 0),
            _seg("bar2", 150, 0, 300, 0),
            _seg("stem", 150, 0, 150, -80),
        ]
        base_junctions, _ = _classify(self._fixture())
        split_junctions, _ = _classify(pre_split)
        base_t = _types_at(base_junctions)[(150.0, 0.0)]
        split_t = _types_at(split_junctions)[(150.0, 0.0)]
        assert base_t == split_t == JunctionType.T_JUNCTION
        # And the extra split point must itself resolve to a harmless
        # bookkeeping entry, not a spurious structural junction.
        assert _types_at(split_junctions)[(80.0, 0.0)] == JunctionType.COLLINEAR_CONTINUATION

    def test_collinear_segment_merging_invariance(self) -> None:
        # The bar drawn as one single unsplit segment (150 -> not present as a
        # vertex at all) still meeting the stem at (150, 0) via intersection
        # splitting must classify identically to the pre-split two-piece bar.
        merged = [_seg("bar", 0, 0, 300, 0), _seg("stem", 150, 0, 150, -80)]
        base_junctions, _ = _classify(self._fixture())
        merged_junctions, _ = _classify(merged)
        assert self._type_multiset(base_junctions) == self._type_multiset(merged_junctions)

    def test_reversed_segment_direction_invariance(self) -> None:
        # Each segment's own start/end swapped -- angle_deg is computed mod
        # 180 degrees, so direction must not matter.
        reversed_dir = [
            _seg("bar1", 150, 0, 0, 0),
            _seg("bar2", 300, 0, 150, 0),
            _seg("stem", 150, -80, 150, 0),
        ]
        base_junctions, _ = _classify(self._fixture())
        reversed_junctions, _ = _classify(reversed_dir)
        assert self._type_multiset(base_junctions) == self._type_multiset(reversed_junctions)

    @staticmethod
    def _rotate(x, y, deg):
        import math

        rad = math.radians(deg)
        return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))

    def _assert_x_crossing_rotation_invariant(self, deg: float) -> None:
        base = [_seg("h", -150, 0, 150, 0), _seg("v", 0, -150, 0, 150)]
        rotated = []
        for s in base:
            x1, y1 = self._rotate(s["x1"], s["y1"], deg)
            x2, y2 = self._rotate(s["x2"], s["y2"], deg)
            rotated.append(_seg(s["id"], x1, y1, x2, y2))

        base_junctions, _ = _classify(base)
        rotated_junctions, _ = _classify(rotated)
        assert self._type_multiset(base_junctions) == self._type_multiset(rotated_junctions)

    def test_rotation_invariance_for_x_crossing(self) -> None:
        self._assert_x_crossing_rotation_invariant(37.0)

    def test_rotation_invariance_90deg(self) -> None:
        self._assert_x_crossing_rotation_invariant(90.0)

    def test_rotation_invariance_180deg(self) -> None:
        self._assert_x_crossing_rotation_invariant(180.0)

    def test_rotation_invariance_270deg(self) -> None:
        self._assert_x_crossing_rotation_invariant(270.0)

    def _assert_scale_invariant(self, factor: float) -> None:
        scaled = [
            _seg(s["id"], s["x1"] * factor, s["y1"] * factor, s["x2"] * factor, s["y2"] * factor)
            for s in self._fixture()
        ]
        base_junctions, _ = _classify(self._fixture())
        scaled_junctions, _ = _classify(scaled)
        assert self._type_multiset(base_junctions) == self._type_multiset(scaled_junctions)

    def test_scale_invariance_half(self) -> None:
        self._assert_scale_invariant(0.5)

    def test_scale_invariance_1_35x(self) -> None:
        self._assert_scale_invariant(1.35)

    def test_scale_invariance_double(self) -> None:
        self._assert_scale_invariant(2.0)
