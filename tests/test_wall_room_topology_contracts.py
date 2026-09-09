from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_contracts import (
    REASON_AMBIGUOUS,
    REASON_NO_PLAUSIBLE_HOST,
    JunctionCandidate,
    JunctionType,
    OpeningHostCandidate,
    RoomCandidate,
    WallCandidate,
)


def _single_line_wall(**overrides) -> WallCandidate:
    defaults = dict(
        candidate_id="wall_1",
        viewport_id="vp_1",
        representation="single_line",
        centerline_pts=((0.0, 0.0), (10.0, 0.0)),
        face_a_segment_ids=("seg_1",),
        face_b_segment_ids=None,
        is_curved=False,
        curve_control_pts=None,
        thickness_m=None,
        thickness_authority=MeasurementAuthorityType.PROVISIONAL,
        length_m=None,
        end_node_ids=("n1", "n2"),
        junction_types=(JunctionType.ENDPOINT, JunctionType.ENDPOINT),
        interior_exterior="unresolved",
        level_id=None,
    )
    defaults.update(overrides)
    return WallCandidate(**defaults)


def _junction(**overrides) -> JunctionCandidate:
    defaults = dict(
        node_id="n1",
        document_id="doc_1",
        page_id="p1",
        viewport_id="vp_1",
        position_pt=(5.0, 5.0),
        junction_type=JunctionType.T_JUNCTION,
        incident_wall_candidate_ids=("wall_1", "wall_2", "wall_3"),
        incident_angles_deg=(0.0, 90.0, 180.0),
        status=EvidenceResolutionStatus.CANDIDATE,
        confidence=0.9,
    )
    defaults.update(overrides)
    return JunctionCandidate(**defaults)


class TestJunctionCandidate:
    def test_valid_t_junction_round_trips(self) -> None:
        junction = _junction()
        assert junction.to_dict()["junction_type"] == "t_junction"
        assert junction.to_dict()["status"] == "candidate"

    def test_rejects_mismatched_incident_lists(self) -> None:
        with pytest.raises(ValueError, match="equal length"):
            _junction(
                junction_type=JunctionType.L_CORNER,
                incident_wall_candidate_ids=("wall_1", "wall_2"),
                incident_angles_deg=(0.0,),
                confidence=0.5,
            )

    def test_classified_junction_requires_incident_walls(self) -> None:
        with pytest.raises(ValueError, match="at least one incident"):
            _junction(
                junction_type=JunctionType.L_CORNER,
                incident_wall_candidate_ids=(),
                incident_angles_deg=(),
                confidence=0.5,
            )

    def test_unresolved_junction_may_have_no_incident_walls(self) -> None:
        junction = _junction(
            junction_type=JunctionType.UNRESOLVED,
            incident_wall_candidate_ids=(),
            incident_angles_deg=(),
            status=EvidenceResolutionStatus.ABSTAINED,
            confidence=0.0,
            reason_codes=("irregular_five_way_meeting",),
        )
        assert junction.junction_type is JunctionType.UNRESOLVED

    def test_conflict_status_requires_conflict_evidence_ids(self) -> None:
        with pytest.raises(ValueError, match="CONFLICT status requires"):
            _junction(status=EvidenceResolutionStatus.CONFLICT)

    def test_corroborated_status_rejects_unresolved_conflicts(self) -> None:
        with pytest.raises(ValueError, match="cannot retain unresolved conflicts"):
            _junction(
                status=EvidenceResolutionStatus.CORROBORATED,
                conflict_evidence_ids=("ev_1",),
            )

    def test_new_junction_types_are_constructible(self) -> None:
        for jt in (
            JunctionType.MULTI_WAY,
            JunctionType.AMBIGUOUS,
            JunctionType.NEAR_JUNCTION_REVIEW,
            JunctionType.REJECTED_NON_WALL_CROSSING,
            JunctionType.COLLINEAR_CONTINUATION,
        ):
            junction = _junction(junction_type=jt, incident_wall_candidate_ids=("e1",), incident_angles_deg=(0.0,))
            assert junction.junction_type is jt


class TestWallCandidate:
    def test_minimal_single_line_wall_is_valid(self) -> None:
        wall = _single_line_wall()
        assert wall.thickness_m is None
        assert wall.status is EvidenceResolutionStatus.CANDIDATE
        d = wall.to_dict()
        assert d["representation"] == "single_line"
        assert d["face_b_segment_ids"] is None

    def test_double_line_requires_face_b(self) -> None:
        with pytest.raises(ValueError, match="face_b_segment_ids"):
            _single_line_wall(representation="double_line", face_b_segment_ids=None)

    def test_single_line_rejects_face_b(self) -> None:
        with pytest.raises(ValueError, match="only a double_line"):
            _single_line_wall(face_b_segment_ids=("seg_2",))

    def test_double_line_with_face_b_is_valid(self) -> None:
        wall = _single_line_wall(
            representation="double_line",
            face_b_segment_ids=("seg_2",),
            thickness_m=0.2,
            thickness_authority=MeasurementAuthorityType.PDF_SCALED,
        )
        assert wall.thickness_m == 0.2

    def test_curved_wall_requires_control_points_and_flag_agreement(self) -> None:
        with pytest.raises(ValueError, match="requires representation='curved'"):
            _single_line_wall(is_curved=True, curve_control_pts=((0, 0), (1, 1), (2, 0)))
        with pytest.raises(ValueError, match="requires is_curved=True"):
            _single_line_wall(representation="curved", is_curved=False)
        with pytest.raises(ValueError, match="requires curve_control_pts"):
            _single_line_wall(representation="curved", is_curved=True, curve_control_pts=None)

    def test_valid_curved_wall(self) -> None:
        wall = _single_line_wall(
            representation="curved",
            is_curved=True,
            curve_control_pts=((0.0, 0.0), (5.0, 5.0), (10.0, 0.0)),
        )
        assert wall.is_curved is True
        assert len(wall.curve_control_pts) == 3

    def test_unresolved_thickness_requires_provisional_or_excluded_authority(self) -> None:
        with pytest.raises(ValueError, match="PROVISIONAL or EXCLUDED"):
            _single_line_wall(
                thickness_m=None, thickness_authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION
            )

    def test_provisional_authority_can_never_back_corroborated_status(self) -> None:
        with pytest.raises(ValueError, match="PROVISIONAL measurement authority"):
            _single_line_wall(
                thickness_authority=MeasurementAuthorityType.PROVISIONAL,
                status=EvidenceResolutionStatus.CORROBORATED,
                confidence=0.9,
                supporting_evidence_ids=("ev_1", "ev_2"),
            )

    def test_corroborated_status_requires_positive_confidence(self) -> None:
        with pytest.raises(ValueError, match="positive confidence"):
            _single_line_wall(
                thickness_m=0.2,
                thickness_authority=MeasurementAuthorityType.PDF_SCALED,
                status=EvidenceResolutionStatus.CORROBORATED,
                confidence=0.0,
                supporting_evidence_ids=("ev_1", "ev_2"),
            )

    def test_conflict_status_requires_conflicting_evidence(self) -> None:
        with pytest.raises(ValueError, match="CONFLICT status requires"):
            _single_line_wall(status=EvidenceResolutionStatus.CONFLICT, confidence=0.5)

    def test_corroborated_status_rejects_unresolved_conflicts(self) -> None:
        with pytest.raises(ValueError, match="cannot retain unresolved conflicts"):
            _single_line_wall(
                thickness_m=0.2,
                thickness_authority=MeasurementAuthorityType.PDF_SCALED,
                status=EvidenceResolutionStatus.CORROBORATED,
                confidence=0.9,
                supporting_evidence_ids=("ev_1", "ev_2"),
                conflicting_evidence_ids=("ev_3",),
            )

    def test_same_start_and_end_node_rejected(self) -> None:
        with pytest.raises(ValueError, match="same node"):
            _single_line_wall(end_node_ids=("n1", "n1"))

    def test_duplicate_face_a_segment_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be unique"):
            _single_line_wall(face_a_segment_ids=("seg_1", "seg_1"))

    def test_negative_thickness_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            _single_line_wall(thickness_m=-0.1, thickness_authority=MeasurementAuthorityType.PDF_SCALED)

    def test_angled_wall_is_not_a_special_case(self) -> None:
        # A 37-degree centerline is exactly as valid as an axis-aligned one --
        # no orthogonality assumption exists anywhere in this schema (spec Section 5).
        wall = _single_line_wall(centerline_pts=((0.0, 0.0), (8.0, 6.0)))
        assert wall.centerline_pts[1] == (8.0, 6.0)


class TestRoomCandidate:
    def _room(self, **overrides) -> RoomCandidate:
        defaults = dict(
            room_ref="R01",
            label="Classroom 1",
            polygon_pdf_pts=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
            polygon_m=None,
            floor_area_m2=25.0,
            area_page_pts2=100.0,
            perimeter_m=20.0,
            geometry_confidence=0.95,
            evidence=("ev_1",),
            source_page=1,
            drawing_number="A-101",
            scale_source="figured_dimension",
            calibration_confidence=0.9,
            has_voids=False,
            status="Measured",
        )
        defaults.update(overrides)
        return RoomCandidate(**defaults)

    def test_minimal_room_is_valid(self) -> None:
        room = self._room()
        assert room.to_dict()["room_ref"] == "R01"

    def test_degenerate_polygon_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 3 points"):
            self._room(polygon_pdf_pts=((0.0, 0.0), (1.0, 1.0)))

    def test_room_cannot_be_adjacent_to_itself(self) -> None:
        with pytest.raises(ValueError, match="cannot be adjacent to itself"):
            self._room(adjacent_room_refs=("R01",))

    def test_area_conflict_requires_exact_keys(self) -> None:
        with pytest.raises(ValueError, match="area_conflict must contain exactly"):
            self._room(area_conflict={"polygon_area_m2": 24.5})

    def test_valid_area_conflict(self) -> None:
        room = self._room(
            area_conflict={"polygon_area_m2": 24.5, "explicit_area_m2": 30.0},
        )
        assert room.area_conflict["explicit_area_m2"] == 30.0

    def test_negative_floor_area_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            self._room(floor_area_m2=-1.0)


class TestOpeningHostCandidate:
    def test_hosted_requires_exactly_one_considered_wall(self) -> None:
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_1",
            position_along_wall_m=2.0,
            gap_width_m=0.9,
            host_status="hosted",
            candidate_wall_ids_considered=("wall_1",),
            confidence=0.95,
        )
        assert host.host_status == "hosted"

    def test_hosted_with_two_considered_walls_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly one considered wall"):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=2.0,
                gap_width_m=0.9,
                host_status="hosted",
                candidate_wall_ids_considered=("wall_1", "wall_2"),
                confidence=0.95,
            )

    def test_hosted_wall_id_must_be_in_considered_list(self) -> None:
        with pytest.raises(ValueError, match="must appear in candidate_wall_ids_considered"):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=2.0,
                gap_width_m=0.9,
                host_status="hosted",
                candidate_wall_ids_considered=("wall_2",),
                confidence=0.95,
            )

    def test_ambiguous_host_requires_two_or_more_and_a_reason(self) -> None:
        with pytest.raises(ValueError, match="at least two considered wall candidates"):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=None,
                gap_width_m=None,
                host_status="ambiguous_host",
                candidate_wall_ids_considered=("wall_1",),
                confidence=0.4,
                reason_codes=(REASON_AMBIGUOUS,),
            )
        with pytest.raises(ValueError, match="at least one reason code"):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=None,
                gap_width_m=None,
                host_status="ambiguous_host",
                candidate_wall_ids_considered=("wall_1", "wall_2"),
                confidence=0.4,
            )

    def test_valid_ambiguous_host_retains_both_candidates(self) -> None:
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_1",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="ambiguous_host",
            candidate_wall_ids_considered=("wall_1", "wall_2"),
            confidence=0.4,
            reason_codes=(REASON_AMBIGUOUS,),
        )
        assert set(host.candidate_wall_ids_considered) == {"wall_1", "wall_2"}

    def test_unhosted_requires_no_considered_walls_and_reason_code(self) -> None:
        with pytest.raises(ValueError, match="must not carry considered wall candidates"):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=None,
                gap_width_m=None,
                host_status="unhosted",
                candidate_wall_ids_considered=("wall_1",),
                confidence=0.0,
                reason_codes=(REASON_NO_PLAUSIBLE_HOST,),
            )
        with pytest.raises(ValueError, match=REASON_NO_PLAUSIBLE_HOST):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=None,
                gap_width_m=None,
                host_status="unhosted",
                candidate_wall_ids_considered=(),
                confidence=0.0,
            )

    def test_valid_unhosted(self) -> None:
        host = OpeningHostCandidate(
            host_candidate_id="host_1",
            wall_candidate_id="wall_1",
            position_along_wall_m=None,
            gap_width_m=None,
            host_status="unhosted",
            candidate_wall_ids_considered=(),
            confidence=0.0,
            reason_codes=(REASON_NO_PLAUSIBLE_HOST,),
        )
        assert host.host_status == "unhosted"

    def test_unknown_host_status_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown host_status"):
            OpeningHostCandidate(
                host_candidate_id="host_1",
                wall_candidate_id="wall_1",
                position_along_wall_m=None,
                gap_width_m=None,
                host_status="hosted_maybe",  # type: ignore[arg-type]
                candidate_wall_ids_considered=(),
                confidence=0.0,
            )
