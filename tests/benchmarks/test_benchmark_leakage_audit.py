"""tests/benchmarks/test_benchmark_leakage_audit.py — Audit for Benchmark Leakage & Overfitting.

Verifies strict decoupling between PlanReader prediction extraction and ground truth BOQ:
1. changing expected_quantity must not change prediction
2. removing BOQ ground truth must not prevent PlanReader extraction
3. benchmark ID rename must not change extracted quantity
4. prediction generation cannot import/load expected_quantities.json or expected_boq_summary.json
5. evaluator may see both expected and predicted data, extractor may not
6. unknown new benchmark can use the same extraction path without bespoke code
"""
import copy
import inspect
import json
from pathlib import Path
import pytest

from pb_benchmark_accuracy_engine import (
    BenchmarkAccuracyEngine,
    BenchmarkAccuracyReport,
    ItemMatchStatus,
)
from pb_planreader_pdf_extractor import (
    ExtractedPrediction,
    GenericPlanReaderExtractor,
)


@pytest.fixture
def mock_pdf(tmp_path):
    """Create a minimal mock PDF with drawing annotations and dimensions."""
    import fitz
    pdf_path = tmp_path / "mock_drawing.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 landscape
    # Insert drawing text
    page.insert_text(
        (50, 50),
        "GROUND FLOOR PLAN\n"
        "SCALE 1:100\n"
        "DRAWING NO: AD-01\n"
        "12,000 x 6,000\n"
        "Mild steel casement window 3000 x 1200\n"
        "Mild steel panelled double door 1000 x 2100\n"
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_1_changing_expected_quantity_does_not_change_prediction(mock_pdf, tmp_path):
    """Rule 1: Changing expected_quantity in BOQ ground truth MUST NOT alter PlanReader predictions."""
    extractor = GenericPlanReaderExtractor()
    preds_baseline = extractor.extract_from_pdf(mock_pdf)

    # Create dummy benchmark directory
    bench_dir = tmp_path / "bench_test"
    bench_dir.mkdir()
    (bench_dir / "source_manifest.json").write_text(json.dumps({
        "benchmark_id": "bench_test",
        "project_name": "Test",
        "status": "verified_public_benchmark",
    }))
    (bench_dir / "download_manifest.json").write_text(json.dumps({"tender_reference": "T1", "documents": []}))
    (bench_dir / "expected_project.json").write_text(json.dumps({"project_name": "Test"}))
    (bench_dir / "benchmark_rules.json").write_text(json.dumps({}))

    # Set expected_quantity to 99999.0 in BOQ summary
    (bench_dir / "expected_boq_summary.json").write_text(json.dumps({
        "total_line_items": 1,
        "sample_measurable_items": [
            {"item_id": "ITEM-1", "expected_quantity": 99999.0, "category": "measurable_from_drawings"}
        ],
    }))

    # Extract again
    preds_after = extractor.extract_from_pdf(mock_pdf)

    assert len(preds_baseline) == len(preds_after)
    for p1, p2 in zip(preds_baseline, preds_after):
        assert p1.quantity == p2.quantity
        assert p1.tag == p2.tag


def test_2_removing_boq_ground_truth_does_not_prevent_extraction(mock_pdf):
    """Rule 2: Removing or having no BOQ ground truth file does not prevent PlanReader extraction."""
    extractor = GenericPlanReaderExtractor()
    # Execute extraction with no BOQ directory or manifests present anywhere
    preds = extractor.extract_from_pdf(mock_pdf)
    assert len(preds) > 0
    assert any(p.trade_type in ("doors", "windows", "walls", "finishes") for p in preds)


def test_3_benchmark_id_rename_does_not_change_extracted_quantity(mock_pdf):
    """Rule 3: Renaming or changing the benchmark ID has zero impact on extracted quantities."""
    extractor = GenericPlanReaderExtractor()
    preds_1 = extractor.extract_from_pdf(mock_pdf)
    # The extractor takes only a PDF path, not a benchmark ID
    sig = inspect.signature(extractor.extract_from_pdf)
    assert "benchmark_id" not in sig.parameters

    preds_2 = extractor.extract_from_pdf(mock_pdf)
    assert [p.quantity for p in preds_1] == [p.quantity for p in preds_2]


def test_4_prediction_generation_cannot_import_or_read_expected_json():
    """Rule 4: Prediction generation code cannot import, read, or reference expected JSON files."""
    import pb_planreader_pdf_extractor
    source = inspect.getsource(pb_planreader_pdf_extractor)

    forbidden_terms = [
        "expected_boq_summary.json",
        "expected_quantities.json",
        "expected_project.json",
        "source_manifest.json",
        "BOQ-C",
        "KSTVET/08/2024",
        "10150",
        "8300",
    ]
    for term in forbidden_terms:
        assert term not in source, f"Forbidden leaked term '{term}' found in pb_planreader_pdf_extractor.py"


def test_5_evaluator_sees_both_extractor_sees_only_pdf(mock_pdf, tmp_path):
    """Rule 5: Evaluator may see both expected and predicted data; extractor may only see source PDF."""
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(mock_pdf)

    # Extractor does not accept ground truth
    ext_params = inspect.signature(extractor.extract_from_pdf).parameters
    assert "expected" not in ext_params
    assert "boq" not in ext_params
    assert "ground_truth" not in ext_params

    # Evaluator accepts predictions and evaluates against benchmark
    engine = BenchmarkAccuracyEngine()
    eval_params = inspect.signature(engine.evaluate_benchmark).parameters
    assert "predictions" in eval_params
    assert "benchmark_id" in eval_params


def test_6_unknown_new_benchmark_uses_same_extraction_path(mock_pdf):
    """Rule 6: An unknown new benchmark uses the identical generic extraction path without bespoke code."""
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(mock_pdf)

    # Predictions contain generic tags and trades
    tags = [p.tag for p in preds]
    assert all(not t.startswith("BOQ-") for t in tags)
    assert all(isinstance(p.quantity, (int, float)) for p in preds)
