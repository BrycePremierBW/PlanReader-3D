from __future__ import annotations

import random

from pb_wall_room_topology_stage_a import (
    build_wall_graph_for_viewport,
    filter_structural_segments,
    is_structural_candidate_segment,
    merge_collinear_degree_two_nodes,
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


def _rectangle_segments():
    return [
        _seg("s0", 0, 0, 10, 0),
        _seg("s1", 10, 0, 10, 10),
        _seg("s2", 10, 10, 0, 10),
        _seg("s3", 0, 10, 0, 0),
    ]


class TestStructuralSegmentFilter:
    def test_solid_untagged_segment_is_kept(self) -> None:
        keep, reasons = is_structural_candidate_segment(_seg("s0", 0, 0, 10, 0))
        assert keep is True
        assert reasons == []

    def test_dashed_segment_is_excluded(self) -> None:
        keep, reasons = is_structural_candidate_segment(_seg("s0", 0, 0, 10, 0, dashes="[3 2] 0"))
        assert keep is False
        assert "dashed_line_excluded" in reasons

    def test_hatch_layer_is_excluded(self) -> None:
        keep, reasons = is_structural_candidate_segment(_seg("s0", 0, 0, 1, 1, layer="A-HATCH-01"))
        assert keep is False
        assert "hatch_layer_excluded" in reasons

    def test_dimension_layer_is_excluded(self) -> None:
        keep, reasons = is_structural_candidate_segment(_seg("s0", 0, 0, 1, 1, layer="Dimensions"))
        assert keep is False
        assert "dimension_layer_excluded" in reasons

    def test_trivial_dash_marker_is_not_excluded(self) -> None:
        # PyMuPDF reports "[] 0" (or empty) for an ordinary solid line.
        keep, reasons = is_structural_candidate_segment(_seg("s0", 0, 0, 10, 0, dashes="[] 0"))
        assert keep is True
        assert reasons == []

    def test_short_segment_alone_is_never_excluded(self) -> None:
        # A short wall return (spec 6.8) must never be rejected by this
        # filter merely for being short -- only dash/layer metadata excludes.
        keep, reasons = is_structural_candidate_segment(_seg("s0", 0, 0, 0.3, 0))
        assert keep is True

    def test_filter_partitions_kept_and_excluded_with_reasons(self) -> None:
        segments = [
            _seg("wall", 0, 0, 10, 0),
            _seg("hatch", 1, 1, 1.2, 1.2, layer="hatch_45"),
            _seg("dim", 2, 2, 5, 2, dashes="[2 1] 0"),
        ]
        kept, excluded = filter_structural_segments(segments)
        assert [s["id"] for s in kept] == ["wall"]
        assert {s["id"] for s in excluded} == {"hatch", "dim"}
        assert all("reason_codes" in s for s in excluded)


class TestCollinearMerge:
    def test_real_corner_is_not_merged(self) -> None:
        graph = build_wall_graph_for_viewport(_rectangle_segments())
        assert len(graph["nodes"]) == 4
        assert len(graph["edges"]) == 4
        for node in graph["nodes"]:
            assert node["degree"] == 2
            assert "merged_into_edge" not in node

    def test_t9_shared_vertex_split_merges_to_one_edge(self) -> None:
        # A single straight wall drawn as two segments sharing one exact
        # endpoint, with nothing else connecting there.
        segments = [_seg("a", 0, 0, 5, 0), _seg("b", 5, 0, 10, 0)]
        graph = build_wall_graph_for_viewport(segments)
        real_edges = graph["edges"]
        assert len(real_edges) == 1
        edge = real_edges[0]
        assert {round(edge["x1"], 3), round(edge["x2"], 3)} == {0.0, 10.0}
        merged_node = next(n for n in graph["nodes"] if n.get("merged_into_edge"))
        assert merged_node["degree"] == 0

    def test_t8_small_gap_fragments_merge_to_one_edge(self) -> None:
        # Three collinear fragments with small (<2pt) gaps and no shared
        # endpoints at all -- closed by snap_geometry's own endpoint
        # tolerance, not by the collinear-merge pass itself.
        segments = [
            _seg("a", 0, 0, 3, 0),
            _seg("b", 3.4, 0, 6, 0),
            _seg("c", 6.3, 0, 10, 0),
        ]
        graph = build_wall_graph_for_viewport(segments)
        assert len(graph["edges"]) == 1
        edge = graph["edges"][0]
        assert {round(edge["x1"], 1), round(edge["x2"], 1)} == {0.0, 10.0}

    def test_three_way_collinear_chain_merges_fully(self) -> None:
        # Two consecutive shared-vertex splits in a row must both collapse,
        # not just the first pair found.
        segments = [
            _seg("a", 0, 0, 3, 0),
            _seg("b", 3, 0, 7, 0),
            _seg("c", 7, 0, 10, 0),
        ]
        graph = build_wall_graph_for_viewport(segments)
        assert len(graph["edges"]) == 1
        edge = graph["edges"][0]
        assert {round(edge["x1"], 1), round(edge["x2"], 1)} == {0.0, 10.0}

        # Regression test: BOTH intermediate (merged-away) nodes must resolve
        # their "merged_into_edge" reference to this one FINAL surviving edge
        # id, not to an intermediate merge product that was itself later
        # superseded by the second merge round. A prior version of this
        # function correctly produced the right final edge (the assertion
        # above already passed) while silently leaving the FIRST
        # merged-away node's own reference pointing at an edge id that no
        # longer existed in the returned graph at all -- undetected because
        # nothing previously checked this field for a 3+-segment chain.
        merged_nodes = [n for n in graph["nodes"] if n.get("merged_into_edge")]
        assert len(merged_nodes) == 2
        surviving_edge_ids = {e["id"] for e in graph["edges"]}
        for node in merged_nodes:
            assert node["merged_into_edge"] in surviving_edge_ids

    def test_slightly_bent_degree_two_node_is_not_merged(self) -> None:
        # A node whose two incident edges differ by more than the collinear
        # tolerance is a real (slight) bend, not a drafting split artifact --
        # it must be left for Section 7's junction classifier, not merged
        # away here.
        segments = [_seg("a", 0, 0, 5, 0), _seg("b", 5, 0, 10, 1)]
        graph = build_wall_graph_for_viewport(segments)
        assert len(graph["edges"]) == 2

    def test_hatch_segments_never_reach_the_graph(self) -> None:
        segments = _rectangle_segments() + [
            _seg("h1", 2, 2, 2.3, 2.3, layer="hatch"),
            _seg("h2", 2.3, 2.3, 2.6, 2.0, layer="hatch"),
        ]
        graph = build_wall_graph_for_viewport(segments)
        assert len(graph["edges"]) == 4
        assert {s["id"] for s in graph["excluded_segments"]} == {"h1", "h2"}


class TestMergeCollinearDegreeTwoNodesUnit:
    def test_operates_directly_on_a_snap_geometry_shaped_graph(self) -> None:
        # Unit-level test against merge_collinear_degree_two_nodes directly,
        # independent of the intersection-split/snap wiring above.
        graph = {
            "nodes": [
                {"id": 0, "x": 0.0, "y": 0.0, "samples": 1, "degree": 1},
                {"id": 1, "x": 5.0, "y": 0.0, "samples": 1, "degree": 2},
                {"id": 2, "x": 10.0, "y": 0.0, "samples": 1, "degree": 1},
            ],
            "edges": [
                {"id": "e0", "a": 0, "b": 1, "x1": 0.0, "y1": 0.0, "x2": 5.0, "y2": 0.0,
                 "angle_deg": 0.0, "length_pt": 5.0},
                {"id": "e1", "a": 1, "b": 2, "x1": 5.0, "y1": 0.0, "x2": 10.0, "y2": 0.0,
                 "angle_deg": 0.0, "length_pt": 5.0},
            ],
            "adjacency": {0: [0], 1: [0, 1], 2: [1]},
        }
        merged = merge_collinear_degree_two_nodes(graph)
        assert len(merged["edges"]) == 1
        assert merged["edges"][0]["collinear_merge_source_edge_ids"] == ["e0", "e1"]
        assert merged["nodes"][1]["merged_into_edge"] == "merged_e0_e1"


class TestOrderAndTranslationInvariance:
    def test_segment_order_does_not_affect_topology(self) -> None:
        segments = _rectangle_segments()
        shuffled = list(segments)
        random.Random(42).shuffle(shuffled)

        graph_a = build_wall_graph_for_viewport(segments)
        graph_b = build_wall_graph_for_viewport(shuffled)

        def node_set(graph):
            return sorted((round(n["x"], 3), round(n["y"], 3)) for n in graph["nodes"])

        def edge_length_multiset(graph):
            return sorted(round(e["length_pt"], 3) for e in graph["edges"])

        assert node_set(graph_a) == node_set(graph_b)
        assert edge_length_multiset(graph_a) == edge_length_multiset(graph_b)

    def test_translation_invariance(self) -> None:
        segments = _rectangle_segments()
        offset = 137.5
        translated = [
            _seg(s["id"], s["x1"] + offset, s["y1"] + offset, s["x2"] + offset, s["y2"] + offset)
            for s in segments
        ]

        graph_a = build_wall_graph_for_viewport(segments)
        graph_b = build_wall_graph_for_viewport(translated)

        assert len(graph_a["nodes"]) == len(graph_b["nodes"])
        assert len(graph_a["edges"]) == len(graph_b["edges"])
        lengths_a = sorted(round(e["length_pt"], 3) for e in graph_a["edges"])
        lengths_b = sorted(round(e["length_pt"], 3) for e in graph_b["edges"])
        assert lengths_a == lengths_b

    def test_pdf_object_order_invariance_via_pre_split_permutation(self) -> None:
        # Simulate a shuffled page.get_drawings() item order by permuting the
        # segment list fed into Stage A before intersection-splitting runs.
        segments = [
            _seg("a", 0, 0, 10, 0),
            _seg("b", 10, 0, 10, 10),
            _seg("c", 0, 0, 0, 10),
            _seg("d", 0, 10, 10, 10),
        ]
        permutations = [segments, list(reversed(segments)), [segments[2], segments[0], segments[3], segments[1]]]
        results = [build_wall_graph_for_viewport(p) for p in permutations]
        node_sets = [
            sorted((round(n["x"], 3), round(n["y"], 3)) for n in g["nodes"]) for g in results
        ]
        edge_sets = [sorted(round(e["length_pt"], 3) for e in g["edges"]) for g in results]
        assert all(ns == node_sets[0] for ns in node_sets)
        assert all(es == edge_sets[0] for es in edge_sets)


class TestFourWayCrossing:
    def test_x_crossing_produces_one_degree_four_node(self) -> None:
        # Two walls crossing at a shared midpoint (a plus-sign layout).
        segments = [
            _seg("h", -5, 0, 5, 0),
            _seg("v", 0, -5, 0, 5),
        ]
        graph = build_wall_graph_for_viewport(segments)
        degrees = sorted(n["degree"] for n in graph["nodes"])
        assert 4 in degrees
        center = next(n for n in graph["nodes"] if n["degree"] == 4)
        assert round(center["x"], 3) == 0.0 and round(center["y"], 3) == 0.0
