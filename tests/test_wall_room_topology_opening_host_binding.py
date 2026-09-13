from __future__ import annotations

import random

import pytest

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_wall_room_topology_contracts import (
    EvidenceResolutionStatus,
    JunctionType,
    WallCandidate,
)
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_opening_host_binding import (
    REASON_COLLINEAR_DANGLING_END_GAP,
    REASON_GAP_AT_OR_BELOW_SNAP_TOLERANCE,
    REASON_GAP_CLUSTER_SIZE_GE_3,
    detect_opening_host_candidates,
)
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT, build_wall_graph_for_viewport
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


def _assemble(segments):
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id="doc_1", page_id="p1", viewport_id="vp_1"
    )
    walls, _edge_map = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_1")
    return walls


def _wall(candidate_id, pts, junction_types, length_m=None, confidence=0.8):
    return WallCandidate(
        candidate_id=candidate_id,
        viewport_id="vp_1",
        representation="single_line",
        centerline_pts=tuple(pts),
        face_a_segment_ids=("seg_x",),
        face_b_segment_ids=None,
        is_curved=False,
        curve_control_pts=None,
        thickness_m=None,
        thickness_authority=MeasurementAuthorityType.PROVISIONAL,
        length_m=length_m,
        end_node_ids=("n0", "n1"),
        junction_types=junction_types,
        interior_exterior="unresolved",
        level_id=None,
        status=EvidenceResolutionStatus.CANDIDATE,
        confidence=confidence,
    )


_DOOR_GAP_RECTANGLE = [
    _seg("top_left", 0, 0, 130, 0),
    _seg("top_right", 170, 0, 300, 0),
    _seg("right", 300, 0, 300, 200),
    _seg("bottom", 300, 200, 0, 200),
    _seg("left", 0, 200, 0, 0),
]

_CLOSED_RECTANGLE = [
    _seg("top", 0, 0, 300, 0),
    _seg("right", 300, 0, 300, 200),
    _seg("bottom", 300, 200, 0, 200),
    _seg("left", 0, 200, 0, 0),
]


class TestGapDetectionFromRealPipeline:
    def test_door_gap_between_two_wall_candidates_is_detected(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts = detect_opening_host_candidates(walls)
        assert len(hosts) == 1
        host = hosts[0]
        assert host.host_status == "ambiguous_host"
        assert len(host.candidate_wall_ids_considered) == 2
        assert REASON_COLLINEAR_DANGLING_END_GAP in host.reason_codes

    def test_closed_rectangle_has_no_opening_candidates(self) -> None:
        walls = _assemble(_CLOSED_RECTANGLE)
        assert detect_opening_host_candidates(walls) == []

    def test_isolated_stub_with_no_partner_is_not_reported(self) -> None:
        walls = _assemble([_seg("stub", 0, 0, 100, 0)])
        assert all(jt == JunctionType.ENDPOINT for jt in walls[0].junction_types)
        assert detect_opening_host_candidates(walls) == []


class TestFailClosedAmbiguity:
    def test_never_produces_hosted_status(self) -> None:
        # This detector only ever has two-or-more plausible wall fragments per
        # gap -- it must never guess a single "hosted" wall.
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts = detect_opening_host_candidates(walls)
        assert all(h.host_status != "hosted" for h in hosts)

    def test_three_way_collinear_cluster_lists_all_three_and_flags_reason(self) -> None:
        walls = [
            _wall("wA", [(0, 0), (100, 0)], (JunctionType.L_CORNER, JunctionType.ENDPOINT)),
            _wall("wB", [(120, 0), (220, 0)], (JunctionType.ENDPOINT, JunctionType.L_CORNER)),
            _wall("wC", [(140, 0), (240, 0)], (JunctionType.ENDPOINT, JunctionType.L_CORNER)),
        ]
        hosts = detect_opening_host_candidates(walls)
        assert len(hosts) == 1
        assert hosts[0].candidate_wall_ids_considered == ("wA", "wB", "wC")
        assert REASON_GAP_CLUSTER_SIZE_GE_3 in hosts[0].reason_codes

    def test_small_gap_at_or_below_snap_tolerance_is_flagged_lower_confidence(self) -> None:
        gap = DEFAULT_GAP_SNAP_TOLERANCE_PT  # exactly at the tolerance boundary
        walls = [
            _wall("wA", [(0, 0), (100, 0)], (JunctionType.L_CORNER, JunctionType.ENDPOINT)),
            _wall("wB", [(100 + gap, 0), (200 + gap, 0)], (JunctionType.ENDPOINT, JunctionType.L_CORNER)),
        ]
        hosts = detect_opening_host_candidates(walls)
        assert len(hosts) == 1
        assert REASON_GAP_AT_OR_BELOW_SNAP_TOLERANCE in hosts[0].reason_codes
        assert hosts[0].confidence <= 0.3


class TestAdversarialNonPairing:
    def test_perpendicular_dangling_ends_never_pair(self) -> None:
        walls = [
            _wall("wF", [(0, 0), (100, 0)], (JunctionType.L_CORNER, JunctionType.ENDPOINT)),
            _wall("wG", [(110, 0), (110, 100)], (JunctionType.ENDPOINT, JunctionType.L_CORNER)),
        ]
        assert detect_opening_host_candidates(walls) == []

    def test_parallel_but_offset_walls_never_pair(self) -> None:
        walls = [
            _wall("wH", [(0, 0), (100, 0)], (JunctionType.L_CORNER, JunctionType.ENDPOINT)),
            _wall("wI", [(140, 50), (240, 50)], (JunctionType.ENDPOINT, JunctionType.L_CORNER)),
        ]
        assert detect_opening_host_candidates(walls) == []

    def test_huge_gap_relative_to_wall_length_is_rejected(self) -> None:
        walls = [
            _wall("wJ", [(0, 0), (50, 0)], (JunctionType.ENDPOINT, JunctionType.ENDPOINT)),
            _wall("wK", [(5000, 0), (5050, 0)], (JunctionType.ENDPOINT, JunctionType.ENDPOINT)),
        ]
        assert detect_opening_host_candidates(walls) == []

    def test_same_wall_both_ends_never_self_pairs(self) -> None:
        walls = [_wall("wL", [(0, 0), (10, 0)], (JunctionType.ENDPOINT, JunctionType.ENDPOINT))]
        assert detect_opening_host_candidates(walls) == []

    def test_non_endpoint_junction_types_never_participate(self) -> None:
        walls = [
            _wall("wM", [(0, 0), (100, 0)], (JunctionType.L_CORNER, JunctionType.T_JUNCTION)),
            _wall("wN", [(120, 0), (220, 0)], (JunctionType.T_JUNCTION, JunctionType.L_CORNER)),
        ]
        assert detect_opening_host_candidates(walls) == []


class TestDuplicateNeverCreated:
    def test_one_gap_produces_exactly_one_record_not_one_per_side(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts = detect_opening_host_candidates(walls)
        assert len(hosts) == 1  # not 2 (one from each wall's perspective)

    def test_host_candidate_id_is_stable_regardless_of_wall_list_order(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        reversed_walls = list(reversed(walls))
        ids_a = {h.host_candidate_id for h in detect_opening_host_candidates(walls)}
        ids_b = {h.host_candidate_id for h in detect_opening_host_candidates(reversed_walls)}
        assert ids_a == ids_b


class TestGapWidthMetreResolution:
    def test_gap_width_m_none_when_no_wall_has_resolved_length(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts = detect_opening_host_candidates(walls)
        assert hosts[0].gap_width_m is None

    def test_gap_width_m_derived_from_a_bounding_walls_own_scale_ratio(self) -> None:
        walls = [
            _wall("wD", [(0, 0), (100, 0)], (JunctionType.L_CORNER, JunctionType.ENDPOINT), length_m=1.0),
            _wall("wE", [(140, 0), (240, 0)], (JunctionType.ENDPOINT, JunctionType.L_CORNER)),
        ]
        hosts = detect_opening_host_candidates(walls)
        assert len(hosts) == 1
        assert hosts[0].gap_width_m == pytest.approx(0.4, abs=1e-6)


class TestInvariance:
    def test_shuffled_wall_order_produces_identical_host_ids(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        shuffled = list(walls)
        random.Random(11).shuffle(shuffled)
        ids_a = {h.host_candidate_id for h in detect_opening_host_candidates(walls)}
        ids_b = {h.host_candidate_id for h in detect_opening_host_candidates(shuffled)}
        assert ids_a == ids_b

    def test_deterministic_replay(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts_a = detect_opening_host_candidates(walls)
        hosts_b = detect_opening_host_candidates(walls)
        assert [h.host_candidate_id for h in hosts_a] == [h.host_candidate_id for h in hosts_b]

    def test_translation_invariance(self) -> None:
        offset_segments = [
            _seg(s["id"], s["x1"] + 500, s["y1"] + 500, s["x2"] + 500, s["y2"] + 500)
            for s in _DOOR_GAP_RECTANGLE
        ]
        walls_a = _assemble(_DOOR_GAP_RECTANGLE)
        walls_b = _assemble(offset_segments)
        hosts_a = detect_opening_host_candidates(walls_a)
        hosts_b = detect_opening_host_candidates(walls_b)
        assert len(hosts_a) == len(hosts_b) == 1

    @staticmethod
    def _rotate(x, y, deg):
        import math

        rad = math.radians(deg)
        return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))

    def _assert_rotation_invariant(self, deg: float) -> None:
        rotated_segments = [
            _seg(s["id"], *self._rotate(s["x1"], s["y1"], deg), *self._rotate(s["x2"], s["y2"], deg))
            for s in _DOOR_GAP_RECTANGLE
        ]
        walls_a = _assemble(_DOOR_GAP_RECTANGLE)
        walls_b = _assemble(rotated_segments)
        hosts_a = detect_opening_host_candidates(walls_a)
        hosts_b = detect_opening_host_candidates(walls_b)
        assert len(hosts_a) == len(hosts_b) == 1

    def test_rotation_invariance_90deg(self) -> None:
        self._assert_rotation_invariant(90.0)

    def test_rotation_invariance_180deg(self) -> None:
        self._assert_rotation_invariant(180.0)

    def test_rotation_invariance_270deg(self) -> None:
        self._assert_rotation_invariant(270.0)

    def test_rotation_invariance_non_round_angle(self) -> None:
        self._assert_rotation_invariant(53.0)

    def _assert_scale_invariant(self, factor: float) -> None:
        scaled_segments = [
            _seg(s["id"], s["x1"] * factor, s["y1"] * factor, s["x2"] * factor, s["y2"] * factor)
            for s in _DOOR_GAP_RECTANGLE
        ]
        walls_a = _assemble(_DOOR_GAP_RECTANGLE)
        walls_b = _assemble(scaled_segments)
        hosts_a = detect_opening_host_candidates(walls_a)
        hosts_b = detect_opening_host_candidates(walls_b)
        assert len(hosts_a) == len(hosts_b) == 1

    def test_scale_invariance_half(self) -> None:
        self._assert_scale_invariant(0.5)

    def test_scale_invariance_1_35x(self) -> None:
        self._assert_scale_invariant(1.35)

    def test_scale_invariance_double(self) -> None:
        self._assert_scale_invariant(2.0)


class TestProvenance:
    def test_reason_codes_always_present_for_ambiguous_host(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts = detect_opening_host_candidates(walls)
        assert all(h.reason_codes for h in hosts)

    def test_candidate_wall_ids_considered_are_unique_and_sorted(self) -> None:
        walls = _assemble(_DOOR_GAP_RECTANGLE)
        hosts = detect_opening_host_candidates(walls)
        for h in hosts:
            ids = h.candidate_wall_ids_considered
            assert len(ids) == len(set(ids))
            assert list(ids) == sorted(ids)


class TestNoQuantityOrLiveWiring:
    def test_no_quantity_evidence_import_or_construction(self) -> None:
        import pb_wall_room_topology_opening_host_binding as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_does_not_import_frozen_schedule_extraction_modules(self) -> None:
        import pb_wall_room_topology_opening_host_binding as mod

        source = open(mod.__file__, encoding="utf-8").read()
        for forbidden in (
            "pb_opening_schedule_v171",
            "pb_opening_deduction_pipeline",
            "pb_opening_evidence_v170",
            "pb_opening_production_v175",
        ):
            assert f"import {forbidden}" not in source
            assert f"from {forbidden}" not in source

    def test_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_opening_host_binding" not in source
