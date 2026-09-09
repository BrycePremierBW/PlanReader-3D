"""Synthetic mutation tests for F.30 orthogonal envelope evidence."""
from __future__ import annotations

import inspect

import fitz
import pytest

from pb_orthogonal_envelope_evidence import (
    extract_oriented_dimension_observations,
    resolve_orthogonal_envelope_evidence,
)


def _dimension_text(value_m: float) -> str:
    return f"{int(round(value_m * 1000.0)):,}"


def _make_page(
    horizontal: list[float],
    vertical: list[float],
    *,
    prose: list[str] | None = None,
    secondary_width: float | None = None,
    secondary_label: str | None = None,
    secondary_label_y: float = 430.0,
    secondary_dimension_y: float = 440.0,
    duplicate_secondary_label: bool = False,
):
    doc = fitz.open()
    page = doc.new_page(width=800, height=600)
    for idx, value in enumerate(horizontal):
        page.insert_text((240, 80 + idx * 24), _dimension_text(value), fontsize=10)
    for idx, value in enumerate(vertical):
        page.insert_text((90 + idx * 24, 360), _dimension_text(value), fontsize=10, rotate=90)
    if secondary_width is not None:
        page.insert_text(
            (90, secondary_dimension_y),
            _dimension_text(secondary_width),
            fontsize=10,
            rotate=90,
        )
    if secondary_label is not None:
        page.insert_text((300, secondary_label_y), secondary_label, fontsize=10)
        if duplicate_secondary_label:
            page.insert_text((450, secondary_label_y), secondary_label, fontsize=10)
    for idx, text in enumerate(prose or []):
        page.insert_text((500, 80 + idx * 20), text, fontsize=9)
    return doc, page


def test_resolves_unique_orthogonal_pair_with_supplied_secondary_strip():
    doc, page = _make_page([15.95, 11.05, 4.3], [8.2, 7.8, 4.6, 3.0])
    try:
        result = resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=162.69,
            secondary_width_m=2.0,
        )
        assert result is not None
        assert result.length_m == pytest.approx(15.95)
        assert result.width_m == pytest.approx(8.2)
        assert result.corroborated_area_m2 == pytest.approx(162.69)
        assert result.relative_area_error == pytest.approx(0.0)
        assert result.secondary_width_m == pytest.approx(2.0)
        assert result.secondary_width_evidence is None
        assert result.horizontal_evidence.orientation == "horizontal"
        assert result.vertical_evidence.orientation == "vertical"
    finally:
        doc.close()


def test_resolves_labeled_secondary_strip_from_its_spatial_band():
    doc, page = _make_page(
        [15.95, 11.05, 4.3],
        [8.2, 7.8, 4.6, 3.0],
        secondary_width=2.0,
        secondary_label="VERANDAH",
    )
    try:
        result = resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=162.69,
        )
        assert result is not None
        assert (result.length_m, result.width_m) == pytest.approx((15.95, 8.2))
        assert result.secondary_width_m == pytest.approx(2.0)
        assert result.secondary_width_evidence is not None
        assert result.secondary_width_evidence.value_m == pytest.approx(2.0)
        assert result.secondary_label_evidence is not None
        assert result.secondary_label_evidence.text.upper() == "VERANDAH"
    finally:
        doc.close()


def test_resolves_simple_rectangle_without_secondary_area():
    doc, page = _make_page([10.0, 9.6], [8.0, 7.6])
    try:
        result = resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=80.0,
        )
        assert result is not None
        assert (result.length_m, result.width_m) == pytest.approx((10.0, 8.0))
        assert result.secondary_width_m is None
    finally:
        doc.close()


def test_text_direction_is_source_evidence_not_bbox_guessing():
    doc, page = _make_page([12.0], [7.0])
    try:
        observations = extract_oriented_dimension_observations(page)
        by_value = {obs.value_m: obs for obs in observations}
        assert by_value[12.0].orientation == "horizontal"
        assert by_value[7.0].orientation == "vertical"
        assert abs(by_value[12.0].direction[0]) >= 0.99
        assert abs(by_value[7.0].direction[1]) >= 0.99
    finally:
        doc.close()


def test_small_figured_dimension_is_retained_for_secondary_width_evidence():
    doc, page = _make_page([12.0], [7.0], secondary_width=1.5)
    try:
        observations = extract_oriented_dimension_observations(page)
        assert 1.5 in {obs.value_m for obs in observations}
    finally:
        doc.close()


def test_prose_standard_numbers_and_dates_are_not_dimensions():
    doc, page = _make_page(
        [10.0],
        [8.0],
        prose=[
            "Fabric reinforcements shall be to BS 4483.",
            "Y indicates Cold Rolled High Tensile Steel to BS 4461.",
            "JANUARY 2017",
        ],
    )
    try:
        observations = extract_oriented_dimension_observations(page)
        values = {obs.value_m for obs in observations}
        assert values == {10.0, 8.0}
    finally:
        doc.close()


def test_missing_orthogonal_axis_fails_closed():
    doc, page = _make_page([10.0, 8.0], [])
    try:
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=80.0,
        ) is None
    finally:
        doc.close()


def test_floor_area_mismatch_fails_closed():
    doc, page = _make_page([10.0], [8.0])
    try:
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=95.0,
        ) is None
    finally:
        doc.close()


def test_two_distinct_area_matching_envelopes_are_ambiguous():
    doc, page = _make_page([12.0, 10.0], [9.6, 8.0])
    try:
        # 12 x 8 and 10 x 9.6 both independently equal 96 m2.
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=96.0,
        ) is None
    finally:
        doc.close()


def test_dimension_mutation_changes_resolved_envelope_deterministically():
    doc_a, page_a = _make_page([10.0], [8.0])
    doc_b, page_b = _make_page([11.0], [8.0])
    try:
        a = resolve_orthogonal_envelope_evidence(page_a, explicit_floor_area_m2=80.0)
        b = resolve_orthogonal_envelope_evidence(page_b, explicit_floor_area_m2=88.0)
        assert a is not None and b is not None
        assert a.length_m == 10.0
        assert b.length_m == 11.0
        assert a.width_m == b.width_m == 8.0
    finally:
        doc_a.close()
        doc_b.close()


def test_supplied_secondary_width_mutation_requires_area_agreement():
    doc, page = _make_page([12.0], [7.0])
    try:
        good_area = 12.0 * 7.0 + 12.0 * 1.5
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=good_area,
            secondary_width_m=1.5,
        ) is not None
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=good_area,
            secondary_width_m=2.5,
        ) is None
    finally:
        doc.close()


def test_unrelated_small_dimension_outside_label_band_is_rejected():
    doc, page = _make_page(
        [12.0],
        [7.0],
        secondary_width=1.5,
        secondary_label="VERANDAH",
        secondary_label_y=430.0,
        secondary_dimension_y=250.0,
    )
    try:
        good_area = 12.0 * 7.0 + 12.0 * 1.5
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=good_area,
        ) is None
    finally:
        doc.close()


def test_secondary_dimension_without_label_cannot_expand_floor_area():
    doc, page = _make_page([12.0], [7.0], secondary_width=1.5)
    try:
        good_area = 12.0 * 7.0 + 12.0 * 1.5
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=good_area,
        ) is None
    finally:
        doc.close()


def test_duplicate_secondary_labels_fail_closed_for_compound_area():
    doc, page = _make_page(
        [12.0],
        [7.0],
        secondary_width=1.5,
        secondary_label="VERANDAH",
        duplicate_secondary_label=True,
    )
    try:
        good_area = 12.0 * 7.0 + 12.0 * 1.5
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=good_area,
        ) is None
    finally:
        doc.close()


def test_conflicting_band_widths_fail_closed_when_both_fit_tolerance():
    doc = fitz.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((240, 80), "12,000", fontsize=10)
    page.insert_text((90, 360), "7,000", fontsize=10, rotate=90)
    page.insert_text((90, 440), "1,500", fontsize=10, rotate=90)
    page.insert_text((120, 440), "1,600", fontsize=10, rotate=90)
    page.insert_text((300, 430), "VERANDAH", fontsize=10)
    try:
        # Midpoint area keeps both 1.5 and 1.6 within the 1.5% tolerance.
        ambiguous_area = 12.0 * 7.0 + 12.0 * 1.55
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=ambiguous_area,
        ) is None
    finally:
        doc.close()


def test_label_and_dimension_translation_preserves_resolution():
    doc_a, page_a = _make_page(
        [12.0], [7.0], secondary_width=1.5, secondary_label="VERANDAH"
    )
    doc_b, page_b = _make_page(
        [12.0],
        [7.0],
        secondary_width=1.5,
        secondary_label="VERANDAH",
        secondary_label_y=500.0,
        secondary_dimension_y=510.0,
    )
    try:
        area = 12.0 * 7.0 + 12.0 * 1.5
        a = resolve_orthogonal_envelope_evidence(page_a, explicit_floor_area_m2=area)
        b = resolve_orthogonal_envelope_evidence(page_b, explicit_floor_area_m2=area)
        assert a is not None and b is not None
        assert (a.length_m, a.width_m, a.secondary_width_m) == (
            b.length_m,
            b.width_m,
            b.secondary_width_m,
        )
    finally:
        doc_a.close()
        doc_b.close()


def test_invalid_secondary_width_fails_closed():
    doc, page = _make_page([10.0], [8.0])
    try:
        assert resolve_orthogonal_envelope_evidence(
            page,
            explicit_floor_area_m2=80.0,
            secondary_width_m=0.0,
        ) is None
    finally:
        doc.close()


def test_module_contains_no_benchmark_identity_or_expected_answer_access():
    import pb_orthogonal_envelope_evidence as module

    source = inspect.getsource(module).lower()
    forbidden = [
        "tenders_ke_",
        "ghazi",
        "kstvet",
        "murera",
        "umma",
        "expected_boq_summary",
        "benchmark_rules",
    ]
    for term in forbidden:
        assert term not in source
