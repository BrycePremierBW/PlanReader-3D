"""Mutation/metamorphic/red-team tests for F.13 raw figured-dimension evidence.

All geometry and values are synthetic. No benchmark ground truth is used.
"""
from __future__ import annotations

import uuid

import fitz
import pytest

from pb_dimension_graph_constraint_engine import ConstraintStatus, DimensionObservation
from pb_figured_dimension_evidence import (
    BindingStatus,
    CoordinateSpace,
    DimensionEvidenceTier,
    ObservedGeometrySegment,
    RasterCoordinateTransform,
    apply_anchor_binding,
    bind_observation_to_vector_geometry,
    build_chains_from_bound_observations,
    calibrate_dimension_layout,
    classify_dimension_token,
    evidence_tier_for,
    extract_dimension_evidence_bundle,
    extract_native_dimension_observations,
    make_ocr_dimension_observation,
    measure_segment_with_page_scale,
    reconcile_candidate_group,
)
from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType, ScaleCalibration
from pb_page_scale_calibration_authority import ScaleCalibrationStatus, ScaleSourceType


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _dimension_page(*, offset_x: float = 0.0, offset_y: float = 0.0, vertical: bool = False) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    if not vertical:
        y = 120 + offset_y
        page.draw_line((60 + offset_x, y), (240 + offset_x, y))
        page.draw_line((60 + offset_x, y - 25), (60 + offset_x, y + 25))
        page.draw_line((240 + offset_x, y - 25), (240 + offset_x, y + 25))
        page.insert_text((135 + offset_x, y - 4), "3800", fontsize=10)
    else:
        x = 160 + offset_x
        page.draw_line((x, 50 + offset_y), (x, 210 + offset_y))
        page.draw_line((x - 25, 50 + offset_y), (x + 25, 50 + offset_y))
        page.draw_line((x - 25, 210 + offset_y), (x + 25, 210 + offset_y))
        page.insert_text((x + 4, 140 + offset_y), "3800", fontsize=10, rotate=90)
    return _reopen(doc)


def _obs(value: float, *, dimension_id: str, method: str = "native_text", authority: str | None = None) -> DimensionObservation:
    return DimensionObservation(
        dimension_id=dimension_id,
        source_page=1,
        view_id="V",
        bbox=(10, 10, 30, 20),
        raw_text=str(value),
        value=value,
        unit="mm",
        extraction_method=method,
        authority=authority or MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        confidence=1.0 if method == "native_text" else 0.7,
    )


class TestTypedDimensionGrammar:
    @pytest.mark.parametrize(
        ("text", "value", "unit"),
        [
            ("3800", 3800.0, "mm"),
            ("3,800", 3800.0, "mm"),
            ("3800 mm", 3800.0, "mm"),
            ("3.8 m", 3.8, "m"),
            ("12'-6\"", 150.0, "in"),
        ],
    )
    def test_valid_dimensions_are_typed(self, text: str, value: float, unit: str) -> None:
        token = classify_dimension_token(text)
        assert token.is_linear_dimension
        assert token.value == pytest.approx(value)
        assert token.unit == unit

    @pytest.mark.parametrize(
        "text",
        ["A501", "3/A501", "ROOM 300", "D01", "W10", "GRID 5", "REV 3", "1:100", "2026", "SHEET 12"],
    )
    def test_required_negative_tokens_are_never_dimensions(self, text: str) -> None:
        token = classify_dimension_token(text)
        assert not token.is_linear_dimension, text

    @pytest.mark.parametrize(
        ("context", "number"),
        [("ROOM", "300"), ("GRID", "5"), ("REV", "3"), ("SHEET", "12"), ("SCALE", "100")],
    )
    def test_separate_label_and_number_words_are_rejected_by_context(self, context: str, number: str) -> None:
        token = classify_dimension_token(number, preceding_context=context)
        assert not token.is_linear_dimension

    def test_mutating_dimension_changes_only_parsed_value(self) -> None:
        before = classify_dimension_token("3000")
        after = classify_dimension_token("3800")
        assert before.value == 3000
        assert after.value == 3800
        assert before.unit == after.unit == "mm"


class TestVectorWitnessBinding:
    def test_two_witness_lines_produce_full_anchor_binding(self) -> None:
        doc = _dimension_page()
        page = doc[0]
        bundle = extract_dimension_evidence_bundle(page, page_num=1, view_id="PLAN")
        assert len(bundle.observations) == 1
        binding = bundle.bindings[0]
        assert binding.status == BindingStatus.WITNESS_BOUND.value
        assert len(binding.witness_line_ids) == 2
        assert binding.endpoints is not None
        bound = bundle.observations[0]
        assert bound.orientation == "horizontal"
        assert bound.endpoints == binding.endpoints
        assert evidence_tier_for(bound, binding) == DimensionEvidenceTier.WITNESS_BOUND.value
        doc.close()

    def test_one_witness_fails_closed_as_partial(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        page.draw_line((60, 120), (240, 120))
        page.draw_line((60, 95), (60, 145))
        page.insert_text((135, 116), "4100", fontsize=10)
        doc = _reopen(doc)
        page = doc[0]
        observations = extract_native_dimension_observations(page, page_num=1)
        from pb_figured_dimension_evidence import extract_vector_segments
        segments = extract_vector_segments(page, page_num=1)
        binding = bind_observation_to_vector_geometry(observations[0], segments, calibrate_dimension_layout(page))
        assert binding.status == BindingStatus.PARTIAL_WITNESS.value
        assert binding.endpoints is None
        doc.close()

    def test_two_indistinguishable_parallel_dimension_lines_are_ambiguous(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        page.draw_line((60, 118), (240, 118))
        page.draw_line((60, 120), (240, 120))
        page.insert_text((135, 116), "4250", fontsize=10)
        doc = _reopen(doc)
        page = doc[0]
        observations = extract_native_dimension_observations(page, page_num=1)
        from pb_figured_dimension_evidence import extract_vector_segments
        segments = extract_vector_segments(page, page_num=1)
        binding = bind_observation_to_vector_geometry(observations[0], segments, calibrate_dimension_layout(page))
        assert binding.status == BindingStatus.AMBIGUOUS.value
        bound = apply_anchor_binding(observations[0], binding)
        assert bound.conflict_state == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        doc.close()


class TestMetamorphicCoordinateSafety:
    def test_translation_preserves_semantic_binding_and_span(self) -> None:
        doc_a = _dimension_page()
        doc_b = _dimension_page(offset_x=25, offset_y=30)
        a = extract_dimension_evidence_bundle(doc_a[0], page_num=1, view_id="V")
        b = extract_dimension_evidence_bundle(doc_b[0], page_num=1, view_id="V")
        assert a.bindings[0].status == b.bindings[0].status == BindingStatus.WITNESS_BOUND.value
        span_a = abs(a.bindings[0].endpoints[1][0] - a.bindings[0].endpoints[0][0])
        span_b = abs(b.bindings[0].endpoints[1][0] - b.bindings[0].endpoints[0][0])
        assert span_a == pytest.approx(span_b)
        assert a.observations[0].value_m == b.observations[0].value_m
        doc_a.close()
        doc_b.close()

    def test_90_degree_orientation_change_preserves_figured_value(self) -> None:
        horizontal = _dimension_page()
        vertical = _dimension_page(vertical=True)
        h = extract_dimension_evidence_bundle(horizontal[0], page_num=1, view_id="V")
        v = extract_dimension_evidence_bundle(vertical[0], page_num=1, view_id="V")
        assert h.bindings[0].status == BindingStatus.WITNESS_BOUND.value
        assert v.bindings[0].status == BindingStatus.WITNESS_BOUND.value
        assert h.observations[0].orientation == "horizontal"
        assert v.observations[0].orientation == "vertical"
        assert h.observations[0].value_m == pytest.approx(v.observations[0].value_m)
        horizontal.close()
        vertical.close()

    def test_raster_bbox_requires_explicit_transform(self) -> None:
        assert make_ocr_dimension_observation(
            dimension_id="OCR-1",
            raw_text="5100",
            bbox_px=(100, 100, 200, 140),
            transform=None,
            source_page=1,
        ) is None

    def test_raster_bbox_transforms_into_pdf_point_space(self) -> None:
        transform = RasterCoordinateTransform(600, 400, 1200, 800)
        obs = make_ocr_dimension_observation(
            dimension_id="OCR-2",
            raw_text="5100",
            bbox_px=(100, 100, 200, 140),
            transform=transform,
            source_page=1,
        )
        assert obs is not None
        assert obs.bbox == pytest.approx((50, 50, 100, 70))
        assert obs.extraction_method == "ocr"
        assert obs.authority == MeasurementAuthorityType.AI_DETECTED.value


class TestOcrCandidatePreservation:
    def test_agreeing_native_and_ocr_candidates_are_both_preserved(self) -> None:
        native = _obs(5300, dimension_id="N")
        ocr = _obs(5300, dimension_id="O", method="ocr", authority=MeasurementAuthorityType.AI_DETECTED.value)
        group = reconcile_candidate_group("G", [native, ocr])
        assert len(group.candidates) == 2
        assert group.resolved is native
        assert group.status == ConstraintStatus.FULLY_CONSTRAINED.value

    def test_conflicting_ocr_is_not_destructively_corrected_or_selected(self) -> None:
        native = _obs(5300, dimension_id="N")
        ocr = _obs(8300, dimension_id="O", method="ocr", authority=MeasurementAuthorityType.AI_DETECTED.value)
        group = reconcile_candidate_group("G", [native, ocr])
        assert [c.value for c in group.candidates] == [5300, 8300]
        assert group.resolved is None
        assert group.status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        assert group.notes


class TestScaleAwareObservedGeometry:
    def test_valid_same_page_scale_measures_observed_vector_without_changing_figured_authority(self) -> None:
        segment = ObservedGeometrySegment("S", 4, (0, 0), (100, 0), CoordinateSpace.PDF_POINTS.value)
        calibration = ScaleCalibration(
            page_no=4,
            ratio_str="1:100",
            px_per_m=10.0,
            method="SCALE_BAR",
            is_verified=True,
            confidence=1.0,
            source_type=ScaleSourceType.SCALE_BAR.value,
            status=ScaleCalibrationStatus.VALID.value,
        )
        measured = measure_segment_with_page_scale(segment, calibration)
        assert measured.status == AuthorityStatus.FIRM.value
        assert measured.length_m == pytest.approx(10.0)
        assert measured.authority == MeasurementAuthorityType.PDF_SCALED.value

    def test_scale_from_different_page_is_blocked(self) -> None:
        segment = ObservedGeometrySegment("S", 4, (0, 0), (100, 0))
        calibration = ScaleCalibration(
            page_no=5,
            ratio_str="1:50",
            px_per_m=20.0,
            method="SCALE_BAR",
            is_verified=True,
            confidence=1.0,
            source_type=ScaleSourceType.SCALE_BAR.value,
            status=ScaleCalibrationStatus.VALID.value,
        )
        measured = measure_segment_with_page_scale(segment, calibration)
        assert measured.status == AuthorityStatus.BLOCKED.value
        assert measured.length_m is None

    def test_unknown_scale_is_blocked_not_guessed(self) -> None:
        segment = ObservedGeometrySegment("S", 1, (0, 0), (100, 0))
        measured = measure_segment_with_page_scale(segment, None)
        assert measured.status == AuthorityStatus.BLOCKED.value
        assert measured.length_m is None


class TestChainsAndIdentityLeakage:
    def test_bound_vertical_observations_form_vertical_chain(self) -> None:
        doc = _dimension_page(vertical=True)
        bundle = extract_dimension_evidence_bundle(doc[0], page_num=1, view_id="VIEW")
        assert bundle.chains
        assert bundle.chains[0].orientation == "vertical"
        doc.close()

    def test_random_view_identity_does_not_change_semantic_values(self) -> None:
        doc = _dimension_page()
        view_a = str(uuid.uuid4())
        view_b = str(uuid.uuid4())
        a = extract_dimension_evidence_bundle(doc[0], page_num=1, view_id=view_a)
        b = extract_dimension_evidence_bundle(doc[0], page_num=1, view_id=view_b)
        assert [o.value_m for o in a.observations] == [o.value_m for o in b.observations]
        assert [c.segment_sum_m for c in a.chains] == [c.segment_sum_m for c in b.chains]
        assert [x.status for x in a.bindings] == [x.status for x in b.bindings]
        doc.close()

    def test_plain_text_dimension_rows_remain_chainable_without_vector_lines(self) -> None:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "150 6,700 150", fontsize=11)
        doc = _reopen(doc)
        observations = extract_native_dimension_observations(doc[0], page_num=1, view_id="V")
        layout = calibrate_dimension_layout(doc[0])
        chains = build_chains_from_bound_observations(observations, calibration=layout)
        assert len(chains) == 1
        assert [o.value_m for o in chains[0].observations] == [0.15, 6.7, 0.15]
        doc.close()
