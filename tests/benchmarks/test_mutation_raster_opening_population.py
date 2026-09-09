from __future__ import annotations

from pb_portable_raster_ocr import RasterOpeningInstanceEvidence
from pb_raster_opening_population import (
    ocr_lines_indicate_floor_plan,
    resolve_single_floor_plan_opening_populations,
)


def _ev(tag: str, trade: str, qty: int, page: int, confidence: float = 0.91):
    return RasterOpeningInstanceEvidence(
        tag=tag,
        trade_type=trade,
        quantity=qty,
        source_page=page,
        confidence=confidence,
        bounding_boxes=tuple((10.0 * i, 20.0, 10.0 * i + 4.0, 24.0) for i in range(qty)),
    )


def test_floor_plan_semantic_is_explicit_not_project_shaped() -> None:
    lines = [
        {"text": "GENERAL WORKSHOP FLOOR PLAN", "confidence": 0.93},
        {"text": "W-1", "confidence": 0.99},
    ]
    assert ocr_lines_indicate_floor_plan(lines)
    assert not ocr_lines_indicate_floor_plan(
        [{"text": "GENERAL WORKSHOP ELEVATION", "confidence": 0.99}]
    )


def test_low_confidence_floor_plan_title_fails_closed() -> None:
    assert not ocr_lines_indicate_floor_plan(
        [{"text": "FLOOR PLAN", "confidence": 0.42}]
    )


def test_single_floor_plan_sums_distinct_window_tags_and_doors_separately() -> None:
    evidence = [
        _ev("W1", "windows", 3, 7),
        _ev("W2", "windows", 2, 7, 0.88),
        _ev("D1", "doors", 4, 7, 0.90),
        _ev("W1", "windows", 1, 9),  # another view: never added
    ]
    result = resolve_single_floor_plan_opening_populations(evidence, {7})
    by_trade = {item.trade_type: item for item in result}
    assert by_trade["windows"].quantity == 5
    assert by_trade["windows"].component_counts == (("W1", 3), ("W2", 2))
    assert by_trade["windows"].confidence == 0.88
    assert by_trade["doors"].quantity == 4


def test_multiple_floor_plan_pages_fail_closed_instead_of_summing_views() -> None:
    evidence = [_ev("W1", "windows", 3, 7), _ev("W1", "windows", 3, 9)]
    assert resolve_single_floor_plan_opening_populations(evidence, {7, 9}) == []


def test_no_semantically_identified_floor_plan_means_no_population() -> None:
    assert resolve_single_floor_plan_opening_populations(
        [_ev("W1", "windows", 3, 7)],
        set(),
    ) == []


def test_duplicate_canonical_tag_records_on_same_plan_fail_closed_for_trade() -> None:
    evidence = [
        _ev("W1", "windows", 2, 7),
        _ev("W1", "windows", 3, 7),
        _ev("D1", "doors", 1, 7),
    ]
    result = resolve_single_floor_plan_opening_populations(evidence, {7})
    assert [item.trade_type for item in result] == ["doors"]
