"""tests/benchmarks/test_mutation_dimension_graph_constraint_engine.py

Mutation and red-team suite for Phase F.13 (pb_dimension_graph_constraint_engine).

Every numeric value here is synthetic and invented for this test file — none
are drawn from, or tuned to reproduce, any real benchmark project's expected
ground truth. KSTVET and Murera are development/diagnostic projects only and
are never read from while writing or asserting these tests. Where a specific
value (12.37, 8.42, 3.21+4.55+4.61, 11.97 vs 12.37, 3050->8050) matches the
mutation-test specification given for this workstream, it is used exactly as
specified — never solved backward from any project's expected quantities.
"""
from __future__ import annotations

import pytest

from pb_dimension_graph_constraint_engine import (
    ConstraintStatus,
    DimensionChain,
    DimensionObservation,
    DimensionOrientation,
    HeightResolution,
    LevelMarker,
    classify_chain_segments,
    group_observations_by_reference,
    parse_dimension_tokens_from_text,
    reconcile_duplicate_observations,
    reconcile_overall_and_chain,
    resolve_rectangle_from_chains,
    resolve_wall_height,
)
from pb_drawing_evidence_binding import DrawingViewType
from pb_geometry_takeoff_model import MeasurementAuthorityType


def _obs(dimension_id, value, unit="mm", view_id="V1", **overrides) -> DimensionObservation:
    kwargs = dict(
        dimension_id=dimension_id, value=value, unit=unit, view_id=view_id,
        view_type=DrawingViewType.FLOOR_PLAN.value,
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
    )
    kwargs.update(overrides)
    return DimensionObservation(**kwargs)


def _chain(chain_id, values, view_id="V1", orientation=DimensionOrientation.HORIZONTAL.value) -> DimensionChain:
    return DimensionChain(
        chain_id=chain_id, view_id=view_id, source_page=1, orientation=orientation,
        observations=[_obs(f"{chain_id}-{i}", v, view_id=view_id) for i, v in enumerate(values)],
    )


class TestMutationARectangleFromExactDimensions:
    def test_rectangle_12_37_by_8_42_resolves_exact_geometry(self):
        length_chain = _chain("LEN", [200, 12370, 200], orientation=DimensionOrientation.HORIZONTAL.value)
        width_chain = _chain("WID", [200, 8420, 200], orientation=DimensionOrientation.VERTICAL.value)
        result = resolve_rectangle_from_chains("ZONE-A", length_chain, width_chain)

        assert result.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert result.internal_length_m == pytest.approx(12.37, abs=1e-6)
        assert result.internal_width_m == pytest.approx(8.42, abs=1e-6)
        assert result.internal_area_m2 == pytest.approx(12.37 * 8.42, abs=1e-4)
        assert result.wall_thickness_m == pytest.approx(0.2, abs=1e-6)
        assert result.external_length_m == pytest.approx(12.77, abs=1e-6)
        assert result.external_width_m == pytest.approx(8.82, abs=1e-6)
        assert result.external_perimeter_m == pytest.approx(2 * (12.77 + 8.82), abs=1e-4)


class TestMutationBChangingADimensionChangesGeometryExactly:
    def test_changing_length_from_12_37_to_14_91_updates_geometry_exactly(self):
        length_chain = _chain("LEN", [200, 14910, 200])
        width_chain = _chain("WID", [200, 8420, 200], orientation=DimensionOrientation.VERTICAL.value)
        result = resolve_rectangle_from_chains("ZONE-A", length_chain, width_chain)

        assert result.internal_length_m == pytest.approx(14.91, abs=1e-6)
        assert result.internal_area_m2 == pytest.approx(14.91 * 8.42, abs=1e-4)
        # Only the changed axis moved — the other axis is untouched.
        assert result.internal_width_m == pytest.approx(8.42, abs=1e-6)


class TestMutationCOverallRemovedChainRetained:
    def test_valid_chain_without_overall_sums_exactly(self):
        # 3.21 + 4.55 + 4.61 = 12.37 — a chain with no separate "overall"
        # dimension observation at all, proving the chain sum alone is
        # sufficient evidence.
        chain = _chain("SPAN", [3210, 4550, 4610])
        resolved_m, status, notes = reconcile_overall_and_chain(overall=None, chain=chain)

        assert status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert resolved_m == pytest.approx(12.37, abs=1e-6)
        assert notes == []


class TestMutationDOverallConflictsWithChain:
    def test_overall_disagreeing_with_chain_sum_is_conflict_manual_review(self):
        chain = _chain("SPAN", [3210, 4550, 4700])  # sums to 12.46m
        overall = _obs("OVERALL", 12370)  # printed as 12.37m
        resolved_m, status, notes = reconcile_overall_and_chain(overall, chain)

        assert status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        assert resolved_m is None
        assert notes  # a real, non-empty explanation, not silently dropped
        assert "12.4600" in notes[0] or "12.46" in notes[0]


class TestMutationESameDimensionInElevationDoesNotAlterPlanFootprint:
    def test_elevation_duplicate_of_a_plan_dimension_never_enters_the_plan_chain(self):
        plan_length_chain = _chain("LEN", [200, 12370, 200], view_id="PLAN-1")
        plan_width_chain = _chain("WID", [200, 8420, 200], view_id="PLAN-1", orientation=DimensionOrientation.VERTICAL.value)
        plan_result = resolve_rectangle_from_chains("ZONE-A", plan_length_chain, plan_width_chain)

        # The exact same 12370 value is also printed on an elevation sheet —
        # a DimensionChain is scoped to one view_id by construction, so
        # building an elevation-view chain can never smuggle this value
        # into the plan chain above.
        elevation_chain = _chain("LEN-ELEV", [12370], view_id="ELEV-1")
        assert elevation_chain.view_id == "ELEV-1"
        assert plan_length_chain.view_id == "PLAN-1"

        # Re-resolving the plan rectangle is byte-for-byte identical —
        # the elevation observation was never a candidate input.
        plan_result_again = resolve_rectangle_from_chains("ZONE-A", plan_length_chain, plan_width_chain)
        assert plan_result_again.internal_length_m == plan_result.internal_length_m
        assert plan_result_again.internal_width_m == plan_result.internal_width_m

    def test_a_chain_cannot_be_constructed_mixing_two_views(self):
        mixed_obs = [_obs("A", 200, view_id="PLAN-1"), _obs("B", 12370, view_id="ELEV-1")]
        with pytest.raises(ValueError):
            DimensionChain(chain_id="BAD", view_id="PLAN-1", source_page=1, orientation="horizontal", observations=mixed_obs)


class TestMutationFInternalVsExternalNeverArbitrarilyChosen:
    def test_internal_and_external_dimensions_of_the_same_wall_are_kept_distinct(self):
        internal = _obs("D-INT", 11970, bound_geometry_id="WALL-A-INTERNAL-FACE")
        external = _obs("D-EXT", 12370, bound_geometry_id="WALL-A-EXTERNAL-FACE")
        groups = group_observations_by_reference([internal, external])

        assert len(groups) == 2
        assert groups["WALL-A-INTERNAL-FACE"] == [internal]
        assert groups["WALL-A-EXTERNAL-FACE"] == [external]
        # Neither value was coerced toward the other.
        assert internal.value_m == pytest.approx(11.97, abs=1e-6)
        assert external.value_m == pytest.approx(12.37, abs=1e-6)


class TestMutationGOcrCorruptionBlockedByNativeVectorConflict:
    def test_ocr_misread_conflicts_with_native_text_and_is_blocked(self):
        native = _obs("D-NATIVE", 3050, extraction_method="native_text")
        ocr = _obs("D-OCR", 8050, extraction_method="ocr")
        resolved, status, notes = reconcile_duplicate_observations([native, ocr])

        assert status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        assert resolved is None
        assert notes

    def test_agreeing_native_and_ocr_readings_resolve_to_the_higher_authority_one(self):
        native = _obs("D-NATIVE", 3050, extraction_method="native_text", authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value)
        ocr = _obs("D-OCR", 3050, extraction_method="ocr", authority=MeasurementAuthorityType.AI_DETECTED.value, confidence=0.6)
        resolved, status, notes = reconcile_duplicate_observations([native, ocr])

        assert status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert resolved is native
        assert notes == []


class TestMutationHTwoScalesOnSameSheetStayIsolated:
    def test_two_views_on_the_same_page_never_merge_their_chains(self):
        chain_v1 = _chain("V1-LEN", [200, 12370, 200], view_id="V1")
        chain_v2 = _chain("V2-LEN", [300, 9000, 300], view_id="V2")
        # Both chains happen to share source_page=1 (same physical sheet,
        # two views at different scales) — nothing about that lets them
        # be combined; each still resolves purely from its own evidence.
        assert chain_v1.source_page == chain_v2.source_page == 1
        result_v1 = resolve_rectangle_from_chains("ZONE-V1", chain_v1, None)
        result_v2 = resolve_rectangle_from_chains("ZONE-V2", chain_v2, None)

        assert result_v1.internal_length_m == pytest.approx(12.37, abs=1e-6)
        assert result_v2.internal_length_m == pytest.approx(9.0, abs=1e-6)


class TestMutationILocalBulkheadHeightIsolatedFromGeneralCeiling:
    def test_local_scope_height_never_leaks_into_or_out_of_the_general_datum(self):
        levels = [
            LevelMarker(marker_id="L1", level_m=2.70, raw_text="+2700 Ceiling", marker_type="ceiling", scope_id=None),
            LevelMarker(marker_id="L2", level_m=0.0, raw_text="0 FFL", marker_type="floor", scope_id=None),
            LevelMarker(marker_id="L3", level_m=2.30, raw_text="+2300 Bulkhead", marker_type="ceiling", scope_id="ROOM-9-BULKHEAD"),
            LevelMarker(marker_id="L4", level_m=0.0, raw_text="0 FFL", marker_type="floor", scope_id="ROOM-9-BULKHEAD"),
        ]
        general = resolve_wall_height(levels, scope_id=None)
        local = resolve_wall_height(levels, scope_id="ROOM-9-BULKHEAD")

        assert general.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert general.clear_height_m == pytest.approx(2.70, abs=1e-6)
        assert local.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert local.clear_height_m == pytest.approx(2.30, abs=1e-6)


class TestMutationJMissingHeightEvidenceIsUnresolvedNeverDefaulted:
    def test_no_level_markers_at_all_leaves_height_unresolved(self):
        result = resolve_wall_height([], scope_id=None)
        assert result.status == ConstraintStatus.UNRESOLVED.value
        assert result.clear_height_m is None
        assert result.notes

    def test_only_a_roof_marker_with_no_floor_marker_is_unresolved(self):
        levels = [LevelMarker(marker_id="L1", level_m=2.70, raw_text="+2700 Roof", marker_type="roof")]
        result = resolve_wall_height(levels, scope_id=None)
        assert result.status == ConstraintStatus.UNRESOLVED.value
        assert result.clear_height_m is None

    def test_engine_never_falls_back_to_a_convenience_default_height(self):
        # There must be no module-level "default height" constant that a
        # caller could accidentally read as a resolved value.
        assert not hasattr(__import__("pb_dimension_graph_constraint_engine"), "DEFAULT_WALL_HEIGHT_M")
        assert not hasattr(__import__("pb_dimension_graph_constraint_engine"), "default_wall_height_m")


class TestMutationKRotationProducesTheSamePhysicalDimension:
    def test_swapping_which_axis_is_horizontal_vs_vertical_yields_the_same_rectangle(self):
        chain_a = _chain("A", [200, 12370, 200], orientation=DimensionOrientation.HORIZONTAL.value)
        chain_b = _chain("B", [200, 8420, 200], orientation=DimensionOrientation.VERTICAL.value)

        as_drawn = resolve_rectangle_from_chains("ZONE-A", chain_a, chain_b)
        # Simulate a 90-degree-rotated view: the same two spans, but now
        # chain_b is "horizontal" and chain_a is "vertical" — pass them in
        # the swapped order.
        rotated = resolve_rectangle_from_chains("ZONE-A", chain_b, chain_a)

        assert as_drawn.internal_area_m2 == pytest.approx(rotated.internal_area_m2, abs=1e-6)
        assert {round(as_drawn.internal_length_m, 4), round(as_drawn.internal_width_m, 4)} == \
               {round(rotated.internal_length_m, 4), round(rotated.internal_width_m, 4)}
        assert as_drawn.external_perimeter_m == pytest.approx(rotated.external_perimeter_m, abs=1e-6)


class TestMutationLSyntheticLShapeResolvesComponentLegs:
    def test_each_leg_of_an_l_shape_resolves_from_its_own_chains_not_a_bounding_box(self):
        leg_a_length = _chain("LA-LEN", [200, 6100, 200], view_id="V1")
        leg_a_width = _chain("LA-WID", [200, 3400, 200], view_id="V1", orientation=DimensionOrientation.VERTICAL.value)
        leg_b_length = _chain("LB-LEN", [200, 9800, 200], view_id="V1")
        leg_b_width = _chain("LB-WID", [200, 5600, 200], view_id="V1", orientation=DimensionOrientation.VERTICAL.value)

        leg_a = resolve_rectangle_from_chains("LEG-A", leg_a_length, leg_a_width)
        leg_b = resolve_rectangle_from_chains("LEG-B", leg_b_length, leg_b_width)

        assert leg_a.internal_length_m == pytest.approx(6.1, abs=1e-6)
        assert leg_a.internal_width_m == pytest.approx(3.4, abs=1e-6)
        assert leg_b.internal_length_m == pytest.approx(9.8, abs=1e-6)
        assert leg_b.internal_width_m == pytest.approx(5.6, abs=1e-6)
        # A much larger leg B does not perturb leg A's own, independently
        # constrained result — this module never computes a bounding box
        # across zones; that composition is left to the caller.
        assert leg_a.internal_area_m2 == pytest.approx(6.1 * 3.4, abs=1e-4)
        assert leg_b.zone_id != leg_a.zone_id


class TestSegmentClassification:
    def test_wall_enclosed_chain_isolates_thickness_and_internal_span(self):
        chain = _chain("C", [150, 6500, 150])
        classification = classify_chain_segments(chain)
        assert classification["role"] == "wall_enclosed"
        assert classification["wall_thickness_m"] == (0.15, 0.15)
        assert classification["internal_span_m"] == pytest.approx(6.5, abs=1e-6)

    def test_two_segment_chain_is_not_classified(self):
        chain = _chain("C", [150, 6500])
        classification = classify_chain_segments(chain)
        assert classification["role"] == "insufficient_segments"
        assert classification["wall_thickness_m"] is None

    def test_endpoints_outside_the_plausible_thickness_range_are_unclassified(self):
        # 900mm endpoints are structurally plausible internal spans, not
        # wall thicknesses — must not be misclassified as walls.
        chain = _chain("C", [900, 6500, 900])
        classification = classify_chain_segments(chain)
        assert classification["role"] == "unclassified"
        assert classification["wall_thickness_m"] is None


class TestNoiseTextFilteringIsContextualNotAValueBlacklist:
    def test_calendar_years_are_rejected_generically(self):
        values = parse_dimension_tokens_from_text("Copyright 2024\nAll rights reserved 2026")
        assert values == []

    def test_scale_and_sheet_labels_are_rejected_by_context(self):
        values = parse_dimension_tokens_from_text("Scale: 1200\nSheet: 4500\nDrawing No: 3300")
        assert values == []

    def test_a_real_dimension_chain_survives_alongside_noise(self):
        text = "Copyright 2026\n150\n6500\n150\nScale: 100"
        values = parse_dimension_tokens_from_text(text)
        assert 150.0 in values
        assert 6500.0 in values
        assert 2026.0 not in values
        assert 100.0 not in values  # rejected by the preceding "Scale:" context

    def test_no_hardcoded_numeric_value_blacklist_exists_in_the_module(self):
        # The failure mode this guards against: excluding specific numbers
        # (e.g. "30010.0, 100727.0, 9656.0") because they happened to be
        # noise in one particular real drawing. Filtering here must only
        # ever be by context/shape (years, label words), never by a
        # hardcoded set of excluded values.
        import pb_dimension_graph_constraint_engine as mod
        import inspect
        source = inspect.getsource(mod)
        assert "9656" not in source
        assert "100727" not in source
        assert "30010" not in source
        assert "KSTVET" not in source
        assert "Murera" not in source  # module must never name a benchmark project


class TestGenericDimensionValueObject:
    def test_value_m_converts_units_correctly(self):
        assert _obs("A", 6500, unit="mm").value_m == pytest.approx(6.5, abs=1e-9)
        assert _obs("A", 6.5, unit="m").value_m == pytest.approx(6.5, abs=1e-9)
        assert _obs("A", 256, unit="in").value_m == pytest.approx(6.5024, abs=1e-4)

    def test_unrecognized_unit_raises_rather_than_guessing(self):
        obs = _obs("A", 6500, unit="cubits")
        with pytest.raises(ValueError):
            _ = obs.value_m
