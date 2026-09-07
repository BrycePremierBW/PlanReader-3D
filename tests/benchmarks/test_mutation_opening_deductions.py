"""tests/benchmarks/test_mutation_opening_deductions.py — Mutation Tests for F.9 Opening Deductions.

Verifies PR F.9 Generic Opening Deduction Pipeline:
1. Add one 1.2x1.5 window -> wall net area decreases exactly 1.8 m²
2. Remove that window -> deduction disappears (returns to gross area)
3. Double quantity -> deduction doubles (from 1.8 m² to 3.6 m²)
4. Move opening to another wall -> only that wall changes
5. Missing height -> no deduction, explicit unresolved state
"""
from __future__ import annotations

from pathlib import Path
import fitz
import pytest

from pb_opening_deduction_pipeline import (
    GenericOpeningDeductionPipeline,
    OpeningDeductionStatus,
    OpeningInstance,
    WallDeductionResult,
    WallInstance,
)
from pb_planreader_pdf_extractor import (
    ExtractedPrediction,
    GenericPlanReaderExtractor,
)


def test_mutation_1_add_window_decreases_net_wall_area_exactly() -> None:
    """1. Add one 1.2x1.5 window -> wall net area decreases exactly 1.8 m²."""
    pipeline = GenericOpeningDeductionPipeline()

    wall = WallInstance(
        wall_id="wall_01",
        length_m=10.0,
        height_m=3.0,
        gross_area_m2=30.0,
    )
    window = OpeningInstance(
        opening_id="W1",
        trade_type="windows",
        width_m=1.2,
        height_m=1.5,
        quantity=1.0,
        bound_wall_id="wall_01",
    )

    res = pipeline.calculate_wall_deductions(wall, [window])

    assert res.gross_area_m2 == 30.0
    # 1.2m * 1.5m * 1.0 = 1.8 m²
    assert res.total_deducted_area_m2 == 1.8
    assert res.net_area_m2 == 28.2  # 30.0 - 1.8 = 28.2
    assert len(res.applied_openings) == 1
    assert res.applied_openings[0]["opening_id"] == "W1"
    assert res.applied_openings[0]["status"] == OpeningDeductionStatus.APPLIED.value


def test_mutation_2_remove_window_deduction_disappears() -> None:
    """2. Remove that window -> deduction disappears, wall net area equals gross area."""
    pipeline = GenericOpeningDeductionPipeline()

    wall = WallInstance(
        wall_id="wall_01",
        length_m=10.0,
        height_m=3.0,
        gross_area_m2=30.0,
    )

    # Empty list of openings (window removed)
    res = pipeline.calculate_wall_deductions(wall, [])

    assert res.gross_area_m2 == 30.0
    assert res.total_deducted_area_m2 == 0.0
    assert res.net_area_m2 == 30.0
    assert len(res.applied_openings) == 0


def test_mutation_3_double_quantity_doubles_deduction() -> None:
    """3. Double quantity -> deduction doubles exactly (1.8 m² -> 3.6 m²)."""
    pipeline = GenericOpeningDeductionPipeline()

    wall = WallInstance(
        wall_id="wall_01",
        length_m=10.0,
        height_m=3.0,
        gross_area_m2=30.0,
    )
    # Quantity doubled to 2.0
    window_2x = OpeningInstance(
        opening_id="W1",
        trade_type="windows",
        width_m=1.2,
        height_m=1.5,
        quantity=2.0,
        bound_wall_id="wall_01",
    )

    res = pipeline.calculate_wall_deductions(wall, [window_2x])

    assert res.gross_area_m2 == 30.0
    # 1.2m * 1.5m * 2.0 = 3.6 m² (exactly double 1.8 m²)
    assert res.total_deducted_area_m2 == 3.6
    assert res.net_area_m2 == 26.4  # 30.0 - 3.6 = 26.4
    assert len(res.applied_openings) == 1
    assert res.applied_openings[0]["quantity"] == 2.0


def test_mutation_4_move_opening_to_another_wall_isolates_change() -> None:
    """4. Move opening to another wall -> only that wall changes, the other remains gross."""
    pipeline = GenericOpeningDeductionPipeline()

    wall_a = WallInstance(
        wall_id="wall_north",
        gross_area_m2=30.0,
    )
    wall_b = WallInstance(
        wall_id="wall_south",
        gross_area_m2=50.0,
    )

    # Opening explicitly bound to wall_south (moved from wall_north)
    window_south = OpeningInstance(
        opening_id="W1",
        trade_type="windows",
        width_m=1.2,
        height_m=1.5,
        quantity=1.0,
        bound_wall_id="wall_south",
    )

    res_a = pipeline.calculate_wall_deductions(wall_a, [window_south])
    res_b = pipeline.calculate_wall_deductions(wall_b, [window_south])

    # Wall North is unchanged (0 deduction, full gross area)
    assert res_a.gross_area_m2 == 30.0
    assert res_a.total_deducted_area_m2 == 0.0
    assert res_a.net_area_m2 == 30.0
    assert len(res_a.applied_openings) == 0

    # Wall South receives the deduction
    assert res_b.gross_area_m2 == 50.0
    assert res_b.total_deducted_area_m2 == 1.8
    assert res_b.net_area_m2 == 48.2
    assert len(res_b.applied_openings) == 1
    assert res_b.applied_openings[0]["bound_wall_id"] == "wall_south"


def test_mutation_5_missing_height_no_deduction_explicit_unresolved_state() -> None:
    """5. Missing height -> no deduction, explicit unresolved state."""
    pipeline = GenericOpeningDeductionPipeline()

    wall = WallInstance(
        wall_id="wall_01",
        gross_area_m2=30.0,
    )
    # Window with missing height (None)
    window_unresolved = OpeningInstance(
        opening_id="W_UNKNOWN",
        trade_type="windows",
        width_m=1.2,
        height_m=None,
        quantity=1.0,
        bound_wall_id="wall_01",
    )

    res = pipeline.calculate_wall_deductions(wall, [window_unresolved])

    # Strict fail-closed: NO guessing, zero deduction
    assert res.gross_area_m2 == 30.0
    assert res.total_deducted_area_m2 == 0.0
    assert res.net_area_m2 == 30.0
    assert len(res.applied_openings) == 0

    # Explicit unresolved state recorded
    assert len(res.unresolved_openings) == 1
    unres = res.unresolved_openings[0]
    assert unres["opening_id"] == "W_UNKNOWN"
    assert unres["status"] == OpeningDeductionStatus.UNRESOLVED_MISSING_DIMENSIONS.value
    assert "Missing figured width or height" in unres["notes"]


def test_propagation_to_predictions_metadata() -> None:
    """Verifies that net wall area propagates to walling and finishes with full audit metadata."""
    pipeline = GenericOpeningDeductionPipeline()

    wall = WallInstance(wall_id="perimeter_walling", gross_area_m2=100.0)
    window = OpeningInstance(
        opening_id="W1",
        width_m=2.0,
        height_m=1.5,
        quantity=2.0,  # 2 * 2.0 * 1.5 = 6.0 m²
        bound_wall_id="perimeter_walling",
    )
    results = pipeline.deduct_openings_for_all_walls([wall], [window])

    preds = [
        ExtractedPrediction(
            tag="perimeter_walling",
            trade_type="walls",
            description="Perimeter walling",
            quantity=100.0,
            unit="SM",
            confidence=0.88,
            source_page=1,
        ),
        ExtractedPrediction(
            tag="internal_plaster",
            trade_type="finishes",
            description="Internal plaster",
            quantity=100.0,
            unit="SM",
            confidence=0.85,
            source_page=1,
        ),
        ExtractedPrediction(
            tag="internal_paint",
            trade_type="finishes",
            description="Internal paint",
            quantity=100.0,
            unit="SM",
            confidence=0.85,
            source_page=1,
        ),
        ExtractedPrediction(
            tag="floor_screed",
            trade_type="finishes",
            description="Floor screed",
            quantity=80.0,
            unit="SM",
            confidence=0.92,
            source_page=1,
        ),
    ]

    updated = pipeline.propagate_to_predictions(preds, results)
    pred_map = {p.tag: p for p in updated}

    # Net walling and wall finishes updated to 94.0 m² (100.0 - 6.0)
    assert pred_map["perimeter_walling"].quantity == 94.0
    assert pred_map["perimeter_walling"].metadata["gross_area_m2"] == 100.0
    assert pred_map["perimeter_walling"].metadata["total_deducted_opening_area_m2"] == 6.0
    assert pred_map["perimeter_walling"].metadata["net_area_m2"] == 94.0

    assert pred_map["internal_plaster"].quantity == 94.0
    assert pred_map["internal_paint"].quantity == 94.0

    # Non-wall finishes untouched
    assert pred_map["floor_screed"].quantity == 80.0
