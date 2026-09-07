"""tests/benchmarks/test_mutation_drawing_evidence_binding.py

Mutation and Hostile Red-Team test suite for Phase F.12:
Drawing Evidence Binding & Scope Reconciliation Engine.

Enforces:
A. 3 windows represented in floor plan + elevation + schedule => 3 physical objects, not 7
B. Change plan to 4 physical windows => result 4
C. Duplicate elevation sheet => physical count unchanged
D. Add unrelated adjacent-building windows => current scope count unchanged
E. Change schedule W_TEST dimensions => dimensions change but count does not
F. Schedule quantity says 5, plan/elevation evidence says 3 => conflict_manual_review
G. Remove object identity evidence => provisional/manual review, not guessed
H. Native text and OCR represent same schedule row => duplicate observation suppressed
I. Three reconciled openings integrated into F.9 => deduction equals exactly 3 physical openings once
J. Change one physical opening dimension => only that object's deduction changes
K. Repeated detail containing W_TEST does not increase physical count
L. Legend/symbol sample containing W_TEST does not increase physical count

Hostile Red-Team Tests:
- Deliberately misleading drawings
- Cross-building isolation
- Duplicate elevation views
- Schedule without quantities
- Reference views
- Conflicting dimensions
- Isolated elevation-only openings
- Typo tags (W2 vs WZ)
- Cropped/incomplete schedule rows
"""
import pytest

from pb_drawing_evidence_binding import (
    DrawingEvidenceBindingEngine,
    DrawingViewType,
    EvidenceGraph,
    EvidenceObservation,
    EvidenceOccurrence,
    PhysicalOpening,
    ReconciliationStatus,
    ScheduleSpecification,
    build_opening_instances_from_physical_openings,
)
from pb_opening_deduction_pipeline import (
    GenericOpeningDeductionPipeline,
    WallInstance,
)

# ---------------------------------------------------------------------------
# Mutation Tests A through L
# ---------------------------------------------------------------------------

def test_mutation_a_same_3_windows_in_plan_elevation_schedule_yields_3():
    """Mutation A: 3 windows in plan, 3 in elevations, 1 schedule row (qty=3) -> 3 physical objects, not 7."""
    plan_occs = [
        EvidenceOccurrence(f"p_{i}", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=1)
        for i in range(3)
    ]
    elev_occs = [
        EvidenceOccurrence(f"e_{i}", "W2", "windows", view_type=DrawingViewType.ELEVATION.value, source_page=2)
        for i in range(3)
    ]
    sched = ScheduleSpecification("W2", "windows", "W2 steel casement", dimensions=[2900.0, 1200.0], scheduled_quantity=3.0)

    res = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs + elev_occs, sched)

    assert res.final_quantity == 3.0
    assert res.status == ReconciliationStatus.CONFIRMED.value
    assert len(res.physical_object_ids) == 3
    assert len(res.physical_openings) == 3
    # 3 elevation occurrences are suppressed duplicates, not added to count
    assert res.duplicate_observations_suppressed == 3
    assert len(res.conflicts) == 0


def test_mutation_b_change_plan_to_4_physical_windows_yields_4():
    """Mutation B: Changing floor plan to 4 physical windows -> result 4."""
    plan_occs = [
        EvidenceOccurrence(f"p_{i}", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=1)
        for i in range(4)
    ]
    elev_occs = [
        EvidenceOccurrence(f"e_{i}", "W2", "windows", view_type=DrawingViewType.ELEVATION.value, source_page=2)
        for i in range(4)
    ]
    sched = ScheduleSpecification("W2", "windows", "W2 steel casement", dimensions=[2900.0, 1200.0], scheduled_quantity=4.0)

    res = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs + elev_occs, sched)

    assert res.final_quantity == 4.0
    assert len(res.physical_object_ids) == 4
    assert len(res.physical_openings) == 4
    assert res.duplicate_observations_suppressed == 4


def test_mutation_c_duplicate_elevation_sheet_does_not_change_count():
    """Mutation C: Duplicate elevation sheet with additional elevation callouts does not inflate count."""
    plan_occs = [
        EvidenceOccurrence(f"p_{i}", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=1)
        for i in range(3)
    ]
    elev_occs_sheet2 = [
        EvidenceOccurrence(f"e2_{i}", "W2", "windows", view_type=DrawingViewType.ELEVATION.value, source_page=2, bounding_box=[100.0, float(i * 50), 150.0, float(i * 50 + 20)])
        for i in range(3)
    ]
    elev_occs_sheet3 = [
        EvidenceOccurrence(f"e3_{i}", "W2", "windows", view_type=DrawingViewType.ELEVATION.value, source_page=3, bounding_box=[100.0, float(i * 50), 150.0, float(i * 50 + 20)])
        for i in range(3)
    ]
    sched = ScheduleSpecification("W2", "windows", "W2 steel casement", dimensions=[2900.0, 1200.0], scheduled_quantity=3.0)

    res = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs + elev_occs_sheet2 + elev_occs_sheet3, sched)

    assert res.final_quantity == 3.0
    assert len(res.physical_object_ids) == 3
    # All duplicate elevation observations across both sheets are suppressed
    assert res.duplicate_observations_suppressed >= 6


def test_mutation_d_add_unrelated_adjacent_building_windows_keeps_scope_count_unchanged():
    """Mutation D: Adding adjacent-building windows leaves current building scope count unchanged."""
    primary_plan = [
        EvidenceOccurrence(f"p_{i}", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="primary_building")
        for i in range(2)
    ]
    adjacent_plan = [
        EvidenceOccurrence(f"adj_{i}", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="adjacent_block")
        for i in range(5)
    ]
    sched = ScheduleSpecification("W1", "windows", "W1 3000x1200", dimensions=[3000.0, 1200.0], scheduled_quantity=2.0)

    res = DrawingEvidenceBindingEngine.reconcile(
        "W1", "windows", primary_plan + adjacent_plan, sched, active_building_id="primary_building"
    )

    assert res.final_quantity == 2.0
    assert len(res.physical_object_ids) == 2
    assert res.metadata["out_of_scope_suppressed"] == 5


def test_mutation_e_schedule_dimensions_change_dimensions_change_but_count_does_not():
    """Mutation E: Changing schedule height from 1200 to 1500 updates dimensions while keeping count 3."""
    plan_occs = [
        EvidenceOccurrence(f"p_{i}", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value)
        for i in range(3)
    ]
    sched_1200 = ScheduleSpecification("W2", "windows", "W2", dimensions=[2900.0, 1200.0], scheduled_quantity=3.0)
    res_1200 = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs, sched_1200)

    sched_1500 = ScheduleSpecification("W2", "windows", "W2", dimensions=[2900.0, 1500.0], scheduled_quantity=3.0)
    res_1500 = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs, sched_1500)

    assert res_1200.final_quantity == 3.0
    assert res_1500.final_quantity == 3.0
    assert res_1200.dimensions == [2900.0, 1200.0]
    assert res_1500.dimensions == [2900.0, 1500.0]


def test_mutation_f_schedule_says_5_while_plan_proves_3_triggers_explicit_conflict():
    """Mutation F: Discrepancy between schedule (5) and plan (3) triggers conflict_manual_review."""
    plan_occs = [
        EvidenceOccurrence(f"p_{i}", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value)
        for i in range(3)
    ]
    sched = ScheduleSpecification("W2", "windows", "W2", dimensions=[2900.0, 1200.0], scheduled_quantity=5.0)

    res = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs, sched)

    assert res.status == ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value
    assert len(res.conflicts) == 1
    assert res.conflicts[0]["type"] == "schedule_vs_plan_count_mismatch"
    assert res.conflicts[0]["schedule_count"] == 5.0
    assert res.conflicts[0]["plan_count"] == 3.0
    assert res.final_quantity is None


def test_mutation_g_remove_object_identity_evidence_remains_unresolved_not_guessed():
    """Mutation G: Missing occurrences and missing schedule yields conflict/review, not guessed quantity."""
    res = DrawingEvidenceBindingEngine.reconcile("W_UNKNOWN", "windows", [], None)

    assert res.status == ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value
    assert res.final_quantity is None
    assert len(res.conflicts) == 1
    assert res.conflicts[0]["type"] == "missing_object_identity_evidence"


def test_mutation_h_native_text_and_ocr_represent_same_schedule_row():
    """Mutation H: Native text and OCR of same schedule row are merged / duplicate suppressed."""
    graph = EvidenceGraph(active_scope_id="primary_building")
    # Native observation
    graph.add_observation(
        EvidenceObservation(
            evidence_id="native_obs_1",
            source_page=1,
            view_type=DrawingViewType.SCHEDULE.value,
            extraction_method="native",
            interpreted_tag="W3",
            interpreted_type="windows",
            dimensions=[1500.0, 1200.0],
            count_value=2.0,
        )
    )
    # OCR observation of the same row on the same page
    graph.add_observation(
        EvidenceObservation(
            evidence_id="ocr_obs_1",
            source_page=1,
            view_type=DrawingViewType.SCHEDULE.value,
            extraction_method="ocr",
            interpreted_tag="W3",
            interpreted_type="windows",
            dimensions=[1500.0, 1200.0],
            count_value=2.0,
        )
    )
    # Plan occurrences
    graph.add_observation(
        EvidenceObservation(
            evidence_id="plan_w3_1",
            source_page=2,
            view_type=DrawingViewType.FLOOR_PLAN.value,
            extraction_method="native",
            interpreted_tag="W3",
            interpreted_type="windows",
            dimensions=[1500.0, 1200.0],
        )
    )
    graph.add_observation(
        EvidenceObservation(
            evidence_id="plan_w3_2",
            source_page=2,
            view_type=DrawingViewType.FLOOR_PLAN.value,
            extraction_method="native",
            interpreted_tag="W3",
            interpreted_type="windows",
            dimensions=[1500.0, 1200.0],
        )
    )

    reconciled = graph.reconcile_all()
    assert "W3" in reconciled
    w3_group = reconciled["W3"]
    assert w3_group.final_quantity == 2.0
    # Duplicate OCR observation was detected and suppressed
    assert any(d.get("rule") == "ocr_duplicate_of_native" for d in w3_group.suppressed_details)


def test_mutation_i_three_reconciled_openings_integrated_into_f9():
    """Mutation I: Three reconciled openings integrated into F.9 deduct exactly 3 physical openings once."""
    openings = [
        PhysicalOpening(
            physical_object_id=f"W2_physical_{i+1}",
            tag="W2",
            trade_type="windows",
            width=2900.0,  # 2.9m
            height=1200.0,  # 1.2m -> area = 3.48 m² each
            bound_wall_id="perimeter_walling",
            conflict_status=ReconciliationStatus.CONFIRMED.value,
        )
        for i in range(3)
    ]
    # Total deduction expected: 3 * (2.9 * 1.2) = 10.44 m²

    instances = build_opening_instances_from_physical_openings(openings, default_wall_id="perimeter_walling")
    assert len(instances) == 3

    wall = WallInstance(wall_id="perimeter_walling", gross_area_m2=100.0)
    pipeline = GenericOpeningDeductionPipeline()
    results = pipeline.deduct_openings_for_all_walls([wall], instances)

    res = results["perimeter_walling"]
    assert res.total_deducted_area_m2 == pytest.approx(10.44, rel=1e-3)
    assert res.net_area_m2 == pytest.approx(100.0 - 10.44, rel=1e-3)


def test_mutation_j_change_one_physical_opening_dimension():
    """Mutation J: Changing one physical opening dimension changes only that opening's deduction."""
    openings_base = [
        PhysicalOpening(
            physical_object_id=f"W_phys_{i}",
            tag=f"W{i}",
            trade_type="windows",
            width=2000.0,  # 2.0m
            height=1000.0,  # 1.0m -> area = 2.0 m² each
            bound_wall_id="perimeter_walling",
        )
        for i in range(3)
    ]
    # Total deduction = 3 * 2.0 = 6.0 m²
    inst_base = build_opening_instances_from_physical_openings(openings_base)
    wall = WallInstance(wall_id="perimeter_walling", gross_area_m2=100.0)
    pipeline = GenericOpeningDeductionPipeline()
    res_base = pipeline.deduct_openings_for_all_walls([wall], inst_base)["perimeter_walling"]
    assert res_base.total_deducted_area_m2 == pytest.approx(6.0, rel=1e-3)

    # Change only opening 0 to 3.0m width (area becomes 3.0 m², diff is +1.0 m²)
    openings_mod = [
        PhysicalOpening(
            physical_object_id="W_phys_0",
            tag="W0",
            trade_type="windows",
            width=3000.0,  # 3.0m
            height=1000.0,
            bound_wall_id="perimeter_walling",
        ),
        openings_base[1],
        openings_base[2],
    ]
    inst_mod = build_opening_instances_from_physical_openings(openings_mod)
    res_mod = pipeline.deduct_openings_for_all_walls([wall], inst_mod)["perimeter_walling"]
    assert res_mod.total_deducted_area_m2 == pytest.approx(7.0, rel=1e-3)


def test_mutation_k_repeated_detail_containing_w_test_does_not_increase_physical_count():
    """Mutation K: Repeated detail containing W_TEST does not increase physical count."""
    plan_occs = [
        EvidenceOccurrence("p1", "W_TEST", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=1),
        EvidenceOccurrence("p2", "W_TEST", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=1),
    ]
    detail_occ = EvidenceOccurrence(
        "detail_1", "W_TEST", "windows", view_type=DrawingViewType.DETAIL.value, source_page=3
    )

    res = DrawingEvidenceBindingEngine.reconcile("W_TEST", "windows", plan_occs + [detail_occ])

    assert res.final_quantity == 2.0
    assert len(res.physical_object_ids) == 2
    assert any(d.get("rule") == "legend_or_typical_suppressed" for d in res.suppressed_details)


def test_mutation_l_legend_symbol_sample_containing_w_test_does_not_increase_physical_count():
    """Mutation L: Legend/symbol sample containing W_TEST does not increase physical count."""
    plan_occs = [
        EvidenceOccurrence("p1", "W_TEST", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=1),
    ]
    legend_occ = EvidenceOccurrence(
        "leg_1", "W_TEST", "windows", view_type=DrawingViewType.LEGEND.value, source_page=1, is_legend_or_typical=True
    )

    res = DrawingEvidenceBindingEngine.reconcile("W_TEST", "windows", plan_occs + [legend_occ])

    assert res.final_quantity == 1.0
    assert len(res.physical_object_ids) == 1
    assert any(d.get("rule") == "legend_or_typical_suppressed" for d in res.suppressed_details)


# ---------------------------------------------------------------------------
# Hostile Red-Team Tests (Step 12)
# ---------------------------------------------------------------------------

def test_redteam_cross_building_tag_isolation():
    """Red-team: Same tag across two separate buildings is strictly isolated by scope ID."""
    occs = [
        EvidenceOccurrence("bldgA_w1", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="Block_A"),
        EvidenceOccurrence("bldgA_w2", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="Block_A"),
        EvidenceOccurrence("bldgB_w1", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="Block_B"),
        EvidenceOccurrence("bldgB_w2", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="Block_B"),
        EvidenceOccurrence("bldgB_w3", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, building_scope_id="Block_B"),
    ]
    res_a = DrawingEvidenceBindingEngine.reconcile("W1", "windows", occs, active_building_id="Block_A")
    assert res_a.final_quantity == 2.0
    assert len(res_a.physical_object_ids) == 2

    res_b = DrawingEvidenceBindingEngine.reconcile("W1", "windows", occs, active_building_id="Block_B")
    assert res_b.final_quantity == 3.0
    assert len(res_b.physical_object_ids) == 3


def test_redteam_duplicate_sheet_with_different_sheet_number():
    """Red-team: Elevation sheet duplicated under a new sheet number with identical view geometry is suppressed."""
    occs = [
        EvidenceOccurrence("s1_e1", "W1", "windows", view_type=DrawingViewType.ELEVATION.value, source_page=1, bounding_box=[50.0, 50.0, 100.0, 100.0]),
        EvidenceOccurrence("s2_e1", "W1", "windows", view_type=DrawingViewType.ELEVATION.value, source_page=2, bounding_box=[50.0, 50.0, 100.0, 100.0]),
    ]
    res = DrawingEvidenceBindingEngine.reconcile("W1", "windows", occs)
    assert res.final_quantity == 1.0
    assert any(d.get("rule") == "duplicate_elevation_sheet_suppressed" for d in res.suppressed_details)


def test_redteam_schedule_without_quantities():
    """Red-team: Schedule specifying dimensions but no quantity does not invent a count, relies on plan."""
    plan_occs = [
        EvidenceOccurrence("p1", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value),
        EvidenceOccurrence("p2", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value),
    ]
    sched = ScheduleSpecification("W1", "windows", "W1 description", dimensions=[1500.0, 1200.0], scheduled_quantity=None)
    res = DrawingEvidenceBindingEngine.reconcile("W1", "windows", plan_occs, sched)

    assert res.final_quantity == 2.0
    assert res.dimensions == [1500.0, 1200.0]
    assert res.status == ReconciliationStatus.CONFIRMED.value


def test_redteam_repeated_reference_view():
    """Red-team: Repeated reference view annotations are suppressed from physical count."""
    plan_occs = [
        EvidenceOccurrence("p1", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value),
    ]
    ref_occ = EvidenceOccurrence(
        "ref_1", "W1", "windows", view_type=DrawingViewType.REPEATED_OR_REFERENCE.value
    )
    res = DrawingEvidenceBindingEngine.reconcile("W1", "windows", plan_occs + [ref_occ])
    assert res.final_quantity == 1.0


def test_redteam_conflicting_dimensions_flagged():
    """Red-team: Conflicting dimensions between schedule (2900x1200) and detail (2900x1500) record a conflict."""
    plan_occs = [
        EvidenceOccurrence("p1", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, dimensions=[2900.0, 1500.0]),
    ]
    sched = ScheduleSpecification("W2", "windows", "W2", dimensions=[2900.0, 1200.0], scheduled_quantity=1.0)
    res = DrawingEvidenceBindingEngine.reconcile("W2", "windows", plan_occs, sched)

    assert len(res.conflicts) == 1
    assert res.conflicts[0]["type"] == "dimension_conflict"


def test_redteam_isolated_elevation_only_opening_is_provisional():
    """Red-team: Opening only found in elevation without plan or schedule confirmation is marked provisional."""
    elev_occs = [
        EvidenceOccurrence("e1", "W99", "windows", view_type=DrawingViewType.ELEVATION.value),
    ]
    res = DrawingEvidenceBindingEngine.reconcile("W99", "windows", elev_occs)
    assert res.status == ReconciliationStatus.PROVISIONAL.value
    assert res.final_quantity == 1.0


def test_redteam_tag_typo_isolation():
    """Red-team: Typo in tag (e.g. W2 vs WZ) creates distinct groups and does not conflate."""
    graph = EvidenceGraph()
    graph.add_observation(
        EvidenceObservation(evidence_id="w2_1", interpreted_tag="W2", view_type=DrawingViewType.FLOOR_PLAN.value)
    )
    graph.add_observation(
        EvidenceObservation(evidence_id="wz_1", interpreted_tag="WZ", view_type=DrawingViewType.FLOOR_PLAN.value)
    )
    reconciled = graph.reconcile_all()
    assert "W2" in reconciled
    assert "WZ" in reconciled
    assert reconciled["W2"].final_quantity == 1.0
    assert reconciled["WZ"].final_quantity == 1.0


def test_redteam_incomplete_dimensions_zero_deduction():
    """Red-team: Conflicted or missing-dimension opening yields zero deduction in F.9."""
    openings = [
        PhysicalOpening(
            physical_object_id="W_incomplete",
            tag="W_inc",
            trade_type="windows",
            width=None,  # Missing width
            height=1200.0,
            conflict_status=ReconciliationStatus.CONFIRMED.value,
        ),
        PhysicalOpening(
            physical_object_id="W_conflicted",
            tag="W_conf",
            trade_type="windows",
            width=2000.0,
            height=1200.0,
            conflict_status=ReconciliationStatus.CONFLICT_MANUAL_REVIEW.value,  # Conflicted
        ),
    ]
    instances = build_opening_instances_from_physical_openings(openings)
    # Both should be excluded from firm deduction instances
    assert len(instances) == 0
