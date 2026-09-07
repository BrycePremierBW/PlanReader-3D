"""tests/benchmarks/test_mutation_level_datum_extraction.py

Mutation/red-team suite for pb_level_datum_extraction.find_level_markers().
Every value in this file is synthetic and invented for this test.
"""
from __future__ import annotations

from pb_dimension_graph_constraint_engine import ConstraintStatus, resolve_wall_height
from pb_level_datum_extraction import find_level_markers


class TestGenuineLevelAnnotations:
    def test_roof_level_label_then_value_is_parsed(self) -> None:
        markers = find_level_markers("Roof Level +4,120", source_page=7)
        assert len(markers) == 1
        assert markers[0].marker_type == "roof"
        assert markers[0].level_m == 4.12
        assert markers[0].source_page == 7

    def test_ground_floor_label_then_value_is_parsed(self) -> None:
        markers = find_level_markers("Ground floor +225", source_page=3)
        assert len(markers) == 1
        assert markers[0].marker_type == "ground"
        assert markers[0].level_m == 0.225

    def test_negative_level_value_is_parsed_with_correct_sign(self) -> None:
        markers = find_level_markers("Beam Level -140", source_page=1)
        assert len(markers) == 1
        assert markers[0].marker_type == "beam"
        assert markers[0].level_m == -0.14

    def test_ceiling_and_floor_level_pair_resolves_a_height(self) -> None:
        markers = find_level_markers(
            "Ceiling Level +2,650 elsewhere on sheet Floor Level +0", source_page=5,
        )
        assert {m.marker_type for m in markers} == {"ceiling", "floor"}
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert res.clear_height_m == 2.65


class TestFalsePositiveRejection:
    def test_scale_ratio_and_view_title_yields_no_marker(self) -> None:
        # Real false positive found against a live project PDF: a scale
        # ratio immediately preceding a "GROUND FLOOR PLAN" view title must
        # never be read as a ground level value.
        markers = find_level_markers("1:75 GROUND FLOOR PLAN 1:75 ROOF PLAN", source_page=2)
        assert markers == []

    def test_unrelated_dimension_chain_before_label_is_not_attributed_to_it(self) -> None:
        # Real false positive shape found against a live project PDF: an
        # unrelated repeated bay-dimension chain sits immediately before a
        # genuine "Roof Level" label in flat reading order. Only the
        # genuine label-then-value annotation may be picked up.
        markers = find_level_markers(
            "2,200 2,200 3,450 3,450 Roof Level +3,325 PV PV", source_page=4,
        )
        assert len(markers) == 1
        assert markers[0].level_m == 3.325

    def test_decimal_point_level_value_is_not_misparsed(self) -> None:
        # "+3.325" does not follow this codebase's comma-grouped-millimetre
        # convention; it must be rejected outright, never mis-read as "+3".
        markers = find_level_markers("Roof Level +3.325", source_page=1)
        assert markers == []

    def test_no_level_text_yields_no_markers(self) -> None:
        assert find_level_markers("GENERAL NOTES: All work to comply with KS.", source_page=1) == []

    def test_roof_plan_view_title_alone_does_not_match_roof_level(self) -> None:
        assert find_level_markers("ROOF PLAN 1:100", source_page=1) == []


class TestUnresolvedWhenOneSidedEvidence:
    def test_roof_only_evidence_leaves_height_unresolved(self) -> None:
        markers = find_level_markers("Roof Level +3,325", source_page=1)
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.UNRESOLVED.value
        assert res.clear_height_m is None
