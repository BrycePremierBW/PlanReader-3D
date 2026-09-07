"""tests/benchmarks/test_mutation_drawing_ocr_evidence.py — Mutation Tests for F.10 Drawing Vision / OCR Evidence Layer.

Verifies PR F.10:
1. Synthetic raster schedule with W_TEST count 7 => extract 7
2. Change to 11 => prediction changes to 11
3. Remove quantity => unresolved
4. Blur/noise text => lower confidence / provisional
5. Conflicting native vs OCR values => blocked/manual review
6. Clipped "No." with missing digit => never invent quantity
7. Integrate recovered schedule evidence into F.9 opening deductions
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import pytest

from pb_drawing_ocr_evidence_layer import (
    DrawingEvidenceParser,
    DrawingEvidenceRecord,
    DrawingOCREngine,
    EvidenceMethod,
    EvidenceStatus,
    EvidenceReconciler,
)
from pb_opening_deduction_pipeline import (
    GenericOpeningDeductionPipeline,
    OpeningInstance,
    WallInstance,
)
from pb_planreader_pdf_extractor import ExtractedPrediction


def _create_synthetic_schedule_image(text: str, width: int = 500, height: int = 80) -> Image.Image:
    """Create a clean synthetic raster image of schedule text."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 25), text, fill="black")
    return img


def test_mutation_1_synthetic_raster_schedule_extracts_exact_count() -> None:
    """1. Synthetic raster schedule with W_TEST count 7 => extract 7."""
    line_text = "W_TEST - 1500 x 1200 - 7 No."

    # Engine recognizing the synthetic schedule line
    engine = DrawingOCREngine(custom_ocr_func=lambda img: [{"text": line_text, "confidence": 0.95}])
    img = _create_synthetic_schedule_image(line_text)
    ocr_lines = engine.recognize_pil_image(img)

    assert len(ocr_lines) == 1
    rec = DrawingEvidenceParser.parse_schedule_line(
        ocr_lines[0]["text"],
        confidence=ocr_lines[0]["confidence"],
        method=EvidenceMethod.RASTER_OCR.value,
    )

    assert rec is not None
    assert rec.tag == "W_TEST"
    assert rec.quantity == 7.0
    assert rec.unit == "NO"
    assert rec.dimensions == [1500.0, 1200.0]
    assert rec.status == EvidenceStatus.CONFIRMED.value
    assert rec.extraction_method == EvidenceMethod.RASTER_OCR.value


def test_mutation_2_changing_count_to_11_updates_prediction() -> None:
    """2. Change count to 11 => prediction changes strictly to 11."""
    line_text = "W_TEST - 1500 x 1200 - 11 No."

    engine = DrawingOCREngine(custom_ocr_func=lambda img: [{"text": line_text, "confidence": 0.95}])
    img = _create_synthetic_schedule_image(line_text)
    ocr_lines = engine.recognize_pil_image(img)

    rec = DrawingEvidenceParser.parse_schedule_line(
        ocr_lines[0]["text"],
        confidence=ocr_lines[0]["confidence"],
        method=EvidenceMethod.RASTER_OCR.value,
    )

    assert rec is not None
    assert rec.tag == "W_TEST"
    assert rec.quantity == 11.0  # Proves dynamic count sensitivity
    assert rec.status == EvidenceStatus.CONFIRMED.value


def test_mutation_3_remove_quantity_leaves_unresolved() -> None:
    """3. Remove quantity => quantity is None and status is unresolved."""
    # Text contains tag and dimensions, but zero quantity
    line_text = "W_TEST - 1500 x 1200 - steel casement"

    engine = DrawingOCREngine(custom_ocr_func=lambda img: [{"text": line_text, "confidence": 0.90}])
    img = _create_synthetic_schedule_image(line_text)
    ocr_lines = engine.recognize_pil_image(img)

    rec = DrawingEvidenceParser.parse_schedule_line(
        ocr_lines[0]["text"],
        confidence=ocr_lines[0]["confidence"],
        method=EvidenceMethod.RASTER_OCR.value,
    )

    assert rec is not None
    assert rec.tag == "W_TEST"
    assert rec.quantity is None  # Strict fail-closed: no guessing
    assert rec.status == EvidenceStatus.UNRESOLVED.value
    assert "quantity count absent" in rec.notes


def test_mutation_4_blur_noise_text_lowers_confidence_provisional() -> None:
    """4. Blur/noise text => lower confidence and provisional status."""
    clean_img = _create_synthetic_schedule_image("W_TEST - 1500 x 1200 - 7 No.")
    # Heavily blur the image to degrade visual sharpness
    blurred_img = clean_img.filter(ImageFilter.GaussianBlur(radius=5))

    engine = DrawingOCREngine(custom_ocr_func=lambda img: [{"text": "W_TEST - 1500 x 1200 - 7 No.", "confidence": 0.85}])
    clean_quality = engine.evaluate_image_quality(clean_img)
    blurred_quality = engine.evaluate_image_quality(blurred_img)

    # Blurred image has significantly lower edge energy / quality
    assert blurred_quality < clean_quality
    assert blurred_quality <= 0.65

    ocr_lines = engine.recognize_pil_image(blurred_img)
    assert len(ocr_lines) == 1
    assert ocr_lines[0]["confidence"] < 0.70  # Scaled by blurred quality

    rec = DrawingEvidenceParser.parse_schedule_line(
        ocr_lines[0]["text"],
        confidence=ocr_lines[0]["confidence"],
        method=EvidenceMethod.RASTER_OCR.value,
    )
    assert rec is not None
    assert rec.status == EvidenceStatus.PROVISIONAL.value
    assert "Low visual/OCR confidence" in rec.notes


def test_mutation_5_conflicting_native_vs_ocr_triggers_manual_review() -> None:
    """5. Conflicting native vs OCR values => blocked/manual review."""
    # Native text layer extracted 5 No.
    native_rec = DrawingEvidenceRecord(
        tag="W1",
        trade_type="windows",
        description="Window W1",
        quantity=5.0,
        unit="NO",
        dimensions=[2900.0, 900.0],
        source_page=1,
        extraction_method=EvidenceMethod.NATIVE_TEXT.value,
        status=EvidenceStatus.CONFIRMED.value,
    )

    # Raster OCR extracted 3 No. (conflict!)
    ocr_rec = DrawingEvidenceRecord(
        tag="W1",
        trade_type="windows",
        description="Window W1",
        quantity=3.0,
        unit="NO",
        dimensions=[2900.0, 900.0],
        source_page=1,
        extraction_method=EvidenceMethod.RASTER_OCR.value,
        status=EvidenceStatus.CONFIRMED.value,
    )

    reconciled = EvidenceReconciler.reconcile([native_rec], [ocr_rec])

    assert len(reconciled) == 1
    rec = reconciled[0]
    assert rec.tag == "W1"
    # Strict fail closed: quantity is suppressed to None when conflict arises!
    assert rec.quantity is None
    assert rec.status == EvidenceStatus.CONFLICT_MANUAL_REVIEW.value
    assert rec.confidence == 0.0
    assert "Conflict detected" in rec.notes


def test_mutation_6_clipped_no_with_missing_digit_never_invents_quantity() -> None:
    """6. Clipped 'No.' with missing digit => never invent quantity."""
    # Common CAD sheet border clipping: "1500 x 1200 steel casement no." (digit clipped off)
    clipped_text = "W_CLIPPED - 1500 x 1200 steel casement no."

    rec = DrawingEvidenceParser.parse_schedule_line(
        clipped_text,
        confidence=0.90,
        method=EvidenceMethod.RASTER_OCR.value,
    )

    assert rec is not None
    assert rec.tag == "W_CLIPPED"
    assert rec.quantity is None  # Never guesses 1, 10, or 12
    assert rec.status == EvidenceStatus.UNRESOLVED.value
    assert "Clipped 'No.' text missing preceding digit" in rec.notes


def test_mutation_7_integrate_recovered_schedule_into_opening_deductions() -> None:
    """7. Integrate recovered schedule evidence into F.9 opening deductions."""
    # Recovered OCR schedule gives W_RECOVERED: 2.0m x 1.5m, 4 No. (Total = 12.0 m²)
    recovered_rec = DrawingEvidenceRecord(
        tag="W_RECOVERED",
        trade_type="windows",
        description="Recovered window schedule item",
        quantity=4.0,
        unit="NO",
        dimensions=[2000.0, 1500.0],
        source_page=2,
        status=EvidenceStatus.CONFIRMED.value,
        extraction_method=EvidenceMethod.RASTER_OCR.value,
    )

    # Convert confirmed recovered schedule record to OpeningInstance
    op_inst = OpeningInstance(
        opening_id=recovered_rec.tag,
        trade_type=recovered_rec.trade_type,
        width_m=recovered_rec.dimensions[0] / 1000.0,  # 2.0m
        height_m=recovered_rec.dimensions[1] / 1000.0,  # 1.5m
        quantity=recovered_rec.quantity,
        bound_wall_id="perimeter_walling",
    )

    wall = WallInstance(
        wall_id="perimeter_walling",
        gross_area_m2=100.0,
    )

    pipeline = GenericOpeningDeductionPipeline()
    res = pipeline.calculate_wall_deductions(wall, [op_inst])

    # 4 * (2.0 * 1.5) = 12.0 m² deducted
    assert res.gross_area_m2 == 100.0
    assert res.total_deducted_area_m2 == 12.0
    assert res.net_area_m2 == 88.0

    # Propagate to predictions
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
    ]

    updated = pipeline.propagate_to_predictions(preds, {"perimeter_walling": res})
    pred_map = {p.tag: p for p in updated}

    assert pred_map["perimeter_walling"].quantity == 88.0
    assert pred_map["internal_plaster"].quantity == 88.0
    assert pred_map["perimeter_walling"].metadata["total_deducted_opening_area_m2"] == 12.0
