from __future__ import annotations

import dataclasses
import math

import pytest

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_hosted_opening_geometry import HostedOpeningSpan
from pb_hosted_opening_wall_binding import (
    HostedOpeningWallBinding,
    REASON_AMBIGUOUS_MULTIPLE_CANDIDATES,
    REASON_AMBIGUOUS_TWO_FLANKING_CHAINS,
    REASON_BOUND_CONTAINED,
    REASON_UNBOUND_NO_HOST,
    bind_hosted_opening_to_walls,
)
from pb_wall_room_topology_contracts import EvidenceResolutionStatus, JunctionType, WallCandidate


def _span(
    *,
    orientation=0.0,
    jamb_start=(100.0, 0.0),
    jamb_end=(140.0, 0.0),
    span_pt=40.0,
    wall_thickness_pt=6.0,
    subtype="window_like",
    width_m=1.5,
):
    return HostedOpeningSpan(
        page=1,
        host_orientation_deg=orientation,
        jamb_start=jamb_start,
        jamb_end=jamb_end,
        span_pt=span_pt,
        width_m=width_m,
        wall_thickness_pt=wall_thickness_pt,
        subtype=subtype,
        evidence_flags=("test_fixture",),
        reason="synthetic test fixture",
    )


def _wall(candidate_id, pts, *, confidence=0.8):
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
        length_m=None,
        end_node_ids=("n0", "n1"),
        junction_types=(JunctionType.ENDPOINT, JunctionType.ENDPOINT),
        interior_exterior="unresolved",
        level_id=None,
        status=EvidenceResolutionStatus.CANDIDATE,
        confidence=confidence,
    )


def _bind(span, walls, **kwargs):
    return bind_hosted_opening_to_walls(span, walls, viewport_id="vp_1", **kwargs)


class TestBoundContainment:
    def test_bound_single_continuous_wall_contains_span(self) -> None:
        span = _span()
        walls = [_wall("wA", [(0.0, 0.0), (300.0, 0.0)])]
        binding = _bind(span, walls)
        assert binding.status == "bound"
        assert binding.reason == REASON_BOUND_CONTAINED

    def test_bound_returns_correct_wall_candidate_id(self) -> None:
        span = _span()
        walls = [_wall("wA", [(0.0, 0.0), (300.0, 0.0)])]
        binding = _bind(span, walls)
        assert binding.wall_candidate_id == "wA"
        assert binding.considered_wall_candidate_ids == ("wA",)

    def test_bound_ignores_unrelated_far_away_collinear_wall(self) -> None:
        span = _span()
        walls = [
            _wall("host", [(0.0, 0.0), (300.0, 0.0)]),
            _wall("far_away", [(1000.0, 0.0), (1300.0, 0.0)]),
        ]
        binding = _bind(span, walls)
        assert binding.status == "bound"
        assert binding.wall_candidate_id == "host"


class TestAmbiguous:
    def test_ambiguous_two_flanking_chains_at_opposite_jambs(self) -> None:
        # jamb_start=(100,0), jamb_end=(140,0) -- one wall ends exactly at
        # x=100 (the "lo" jamb), another begins exactly at x=140 (the "hi"
        # jamb). Neither contains the span; both are equally real hosts of
        # the same interrupted physical wall run.
        span = _span()
        walls = [
            _wall("west_chain", [(0.0, 0.0), (100.0, 0.0)]),
            _wall("east_chain", [(140.0, 0.0), (300.0, 0.0)]),
        ]
        binding = _bind(span, walls)
        assert binding.status == "ambiguous"
        assert binding.wall_candidate_id is None
        assert binding.reason == REASON_AMBIGUOUS_TWO_FLANKING_CHAINS
        assert set(binding.considered_wall_candidate_ids) == {"west_chain", "east_chain"}

    def test_ambiguous_two_walls_both_contain_span_duplicate(self) -> None:
        span = _span()
        walls = [
            _wall("original", [(0.0, 0.0), (300.0, 0.0)]),
            _wall("duplicate_trace", [(0.0, 0.5), (300.0, 0.5)]),
        ]
        binding = _bind(span, walls, perpendicular_tolerance_pt=3.0)
        assert binding.status == "ambiguous"
        assert binding.reason == REASON_AMBIGUOUS_MULTIPLE_CANDIDATES
        assert set(binding.considered_wall_candidate_ids) == {"original", "duplicate_trace"}


class TestUnbound:
    def test_unbound_no_walls_at_all(self) -> None:
        binding = _bind(_span(), [])
        assert binding.status == "unbound"
        assert binding.wall_candidate_id is None
        assert binding.reason == REASON_UNBOUND_NO_HOST

    def test_unbound_wall_wrong_orientation_ignored(self) -> None:
        span = _span()  # horizontal opening
        walls = [_wall("vertical_wall", [(120.0, -200.0), (120.0, 200.0)])]
        binding = _bind(span, walls)
        assert binding.status == "unbound"

    def test_unbound_wall_too_far_perpendicular_offset(self) -> None:
        span = _span()  # cross-axis (y) at 0.0
        walls = [_wall("offset_wall", [(0.0, 500.0), (300.0, 500.0)])]
        binding = _bind(span, walls)
        assert binding.status == "unbound"

    def test_unbound_single_sided_adjacency_insufficient(self) -> None:
        span = _span()
        walls = [_wall("west_chain_only", [(0.0, 0.0), (100.0, 0.0)])]
        binding = _bind(span, walls)
        assert binding.status == "unbound"
        assert binding.reason == "single_sided_adjacency_insufficient"


class TestVerticalOrientation:
    def test_vertical_orientation_bound(self) -> None:
        span = _span(orientation=90.0, jamb_start=(0.0, 100.0), jamb_end=(0.0, 140.0))
        walls = [_wall("vertical_host", [(0.0, 0.0), (0.0, 300.0)])]
        binding = _bind(span, walls)
        assert binding.status == "bound"
        assert binding.wall_candidate_id == "vertical_host"


class TestInvariance:
    def test_deterministic_replay(self) -> None:
        span = _span()
        walls = [_wall("wA", [(0.0, 0.0), (300.0, 0.0)])]
        b1 = _bind(span, walls)
        b2 = _bind(span, walls)
        assert b1 == b2

    def test_wall_order_invariance(self) -> None:
        span = _span()
        walls = [
            _wall("west_chain", [(0.0, 0.0), (100.0, 0.0)]),
            _wall("east_chain", [(140.0, 0.0), (300.0, 0.0)]),
        ]
        b_forward = _bind(span, walls)
        b_reversed = _bind(span, list(reversed(walls)))
        assert b_forward.status == b_reversed.status == "ambiguous"
        assert set(b_forward.considered_wall_candidate_ids) == set(b_reversed.considered_wall_candidate_ids)

    @staticmethod
    def _rotate(x, y, deg):
        rad = math.radians(deg)
        return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))

    def _assert_translation_invariant_bound(self, dx: float, dy: float) -> None:
        span = _span(
            jamb_start=(100.0 + dx, 0.0 + dy),
            jamb_end=(140.0 + dx, 0.0 + dy),
        )
        walls = [_wall("wA", [(0.0 + dx, 0.0 + dy), (300.0 + dx, 0.0 + dy)])]
        binding = _bind(span, walls)
        assert binding.status == "bound"
        assert binding.wall_candidate_id == "wA"

    def test_translation_invariance_positive_x_y(self) -> None:
        self._assert_translation_invariant_bound(137.5, 250.0)

    def test_translation_invariance_negative_x_y(self) -> None:
        self._assert_translation_invariant_bound(-500.0, -80.0)

    def _assert_rotation_invariant_bound(self, deg: float) -> None:
        base_jamb_start, base_jamb_end = (100.0, 0.0), (140.0, 0.0)
        base_wall = [(0.0, 0.0), (300.0, 0.0)]
        r_jamb_start = self._rotate(*base_jamb_start, deg)
        r_jamb_end = self._rotate(*base_jamb_end, deg)
        r_wall = [self._rotate(x, y, deg) for x, y in base_wall]
        orientation = 0.0 if abs(deg % 180.0) < 1e-6 else (90.0 if abs((deg % 180.0) - 90.0) < 1e-6 else None)
        assert orientation is not None, "test only meaningful at axis-aligned rotations"
        span = _span(orientation=orientation, jamb_start=r_jamb_start, jamb_end=r_jamb_end)
        walls = [_wall("wA", r_wall)]
        binding = _bind(span, walls)
        assert binding.status == "bound"
        assert binding.wall_candidate_id == "wA"

    def test_rotation_invariance_90deg(self) -> None:
        self._assert_rotation_invariant_bound(90.0)

    def test_rotation_invariance_180deg(self) -> None:
        self._assert_rotation_invariant_bound(180.0)

    def test_rotation_invariance_270deg(self) -> None:
        self._assert_rotation_invariant_bound(270.0)

    def _assert_scale_invariant_bound(self, factor: float) -> None:
        span = _span(
            jamb_start=(100.0 * factor, 0.0),
            jamb_end=(140.0 * factor, 0.0),
            span_pt=40.0 * factor,
            wall_thickness_pt=6.0 * factor,
        )
        walls = [_wall("wA", [(0.0, 0.0), (300.0 * factor, 0.0)])]
        binding = _bind(span, walls, perpendicular_tolerance_pt=3.0 * factor, adjacency_tolerance_pt=3.0 * factor)
        assert binding.status == "bound"
        assert binding.wall_candidate_id == "wA"

    def test_scale_invariance_half(self) -> None:
        self._assert_scale_invariant_bound(0.5)

    def test_scale_invariance_1_35x(self) -> None:
        self._assert_scale_invariant_bound(1.35)

    def test_scale_invariance_double(self) -> None:
        self._assert_scale_invariant_bound(2.0)


class TestApiShapeNeverCarriesIdentityOrQuantity:
    def test_no_schedule_identity_height_or_quantity_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(HostedOpeningWallBinding)}
        forbidden_substrings = ("tag", "schedule", "height", "quantity", "deduction", "label", "type_mark")
        for name in field_names:
            for bad in forbidden_substrings:
                assert bad not in name.lower(), f"field {name!r} looks like it carries {bad!r}"

    def test_bound_post_init_rejects_missing_wall_id(self) -> None:
        with pytest.raises(ValueError):
            HostedOpeningWallBinding(
                binding_id="x",
                page=1,
                viewport_id="vp_1",
                host_orientation_deg=0.0,
                jamb_start=(0.0, 0.0),
                jamb_end=(1.0, 0.0),
                span_pt=1.0,
                subtype="window_like",
                status="bound",
                wall_candidate_id=None,
                considered_wall_candidate_ids=(),
                reason="x",
                evidence_flags=(),
            )

    def test_ambiguous_post_init_requires_two_considered(self) -> None:
        with pytest.raises(ValueError):
            HostedOpeningWallBinding(
                binding_id="x",
                page=1,
                viewport_id="vp_1",
                host_orientation_deg=0.0,
                jamb_start=(0.0, 0.0),
                jamb_end=(1.0, 0.0),
                span_pt=1.0,
                subtype="window_like",
                status="ambiguous",
                wall_candidate_id=None,
                considered_wall_candidate_ids=("only_one",),
                reason="x",
                evidence_flags=(),
            )
