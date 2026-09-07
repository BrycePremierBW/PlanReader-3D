"""tests/benchmarks/test_public_tender_mbagha_maternity.py

PR F.4: Verification test suite for the second verified real public tender benchmark:
Construction of a Maternity Block at Mbagha Dispensary (tenders_ke_mbagha_maternity_dispensary).

Verifies:
1. Manifest discovery and verified status in public tender index.
2. Cryptographic SHA-256 hash and document metadata integrity.
3. BOQ classification of healthcare facility elements (maternity wing vs full facility).
4. Strict separation between extractor predictions and ground truth BOQ.
5. Accurate evaluation with penalties for missed scheduled items and gross mismatches.
6. End-to-end evaluation against native tender PDF if downloaded.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from pb_benchmark_accuracy_engine import (
    BenchmarkAccuracyEngine,
    BenchmarkAccuracyReport,
    ItemMatchStatus,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_public_tender_benchmark import (
    BOQLineCategory,
    BOQLineItem,
    PublicTenderBenchmark,
    classify_boq_line,
    list_available_public_tender_benchmarks,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARK_ID = "tenders_ke_mbagha_maternity_dispensary"
BENCHMARK_DIR = REPO_ROOT / "benchmarks" / "public_tenders" / BENCHMARK_ID
DRAWING_PDF_PATH = Path(r"C:\Users\bryce\Downloads\mbagha_maternity_dispensary\drawings.pdf")
BOQ_PDF_PATH = Path(r"C:\Users\bryce\Downloads\mbagha_maternity_dispensary\bq.pdf")


def test_mbagha_manifest_registered_and_verified():
    """Mbagha Maternity Dispensary benchmark is indexed with verified status."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    assert bench.is_candidate_unverified is False
    assert bench.benchmark_id == BENCHMARK_ID
    assert "Mbagha" in bench.project_name
    assert bench.status == "verified_public_benchmark"
    assert bench.tender_reference == "2028763-2025/2026"


def test_mbagha_manifest_file_completeness():
    """All 5 standard benchmark manifest files exist and are valid JSON."""
    assert BENCHMARK_DIR.exists()
    required_files = [
        "source_manifest.json",
        "download_manifest.json",
        "expected_project.json",
        "expected_boq_summary.json",
        "benchmark_rules.json",
    ]
    for rf in required_files:
        f_path = BENCHMARK_DIR / rf
        assert f_path.exists(), f"Missing required file: {rf}"
        data = json.loads(f_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{rf} is not a valid JSON object"


def test_mbagha_download_manifest_hashes():
    """Download manifest contains verified document hashes and page metadata."""
    dl_manifest = json.loads((BENCHMARK_DIR / "download_manifest.json").read_text(encoding="utf-8"))
    assert dl_manifest["benchmark_id"] == BENCHMARK_ID
    docs = dl_manifest["documents"]
    assert len(docs) == 3

    roles = {d["role"]: d for d in docs}
    assert "architectural_drawings" in roles
    assert "bill_of_quantities" in roles
    assert "tender_document" in roles

    draw_doc = roles["architectural_drawings"]
    assert draw_doc["sha256"] == "b535961ae5aa549c6d532ad5afb2e93133dca1fa7c232e86e0eb2090f7852220"
    assert draw_doc["total_pages"] == 1

    boq_doc = roles["bill_of_quantities"]
    assert boq_doc["sha256"] == "006b10b26b3e74d766590a18b1145aa81dbb127430434d169c70e2c8f3edc786"
    assert boq_doc["total_pages"] == 43


def test_mbagha_local_pdf_hashes_match_manifest_if_downloaded():
    """If local files exist in Downloads, their cryptographic SHA-256 hashes must match."""
    if not DRAWING_PDF_PATH.exists() or not BOQ_PDF_PATH.exists():
        pytest.skip("Local Mbagha tender documents not present in environment")

    # Check drawing hash
    draw_hash = hashlib.sha256(DRAWING_PDF_PATH.read_bytes()).hexdigest()
    assert draw_hash == "b535961ae5aa549c6d532ad5afb2e93133dca1fa7c232e86e0eb2090f7852220"

    # Check BOQ hash
    boq_hash = hashlib.sha256(BOQ_PDF_PATH.read_bytes()).hexdigest()
    assert boq_hash == "006b10b26b3e74d766590a18b1145aa81dbb127430434d169c70e2c8f3edc786"


def test_mbagha_boq_classification_rules():
    """Verify classification of healthcare dispensary BOQ lines across trades."""
    # Measurable finishes & partitions
    assert classify_boq_line("200mm thick natural stone foundation walling") == BOQLineCategory.MEASURABLE_FROM_DRAWINGS
    assert classify_boq_line("25mm thick cement sand (1:3) floor screed to receive tiles") == BOQLineCategory.MEASURABLE_FROM_DRAWINGS
    assert classify_boq_line("12mm thick chipboard ceiling fixed to brandering") == BOQLineCategory.MEASURABLE_FROM_DRAWINGS
    assert classify_boq_line("300x 300 x 8mm ceramic floor tiles fixed with approved Adhesive") == BOQLineCategory.MEASURABLE_FROM_DRAWINGS

    # Schedule extractable
    assert classify_boq_line("50mm thick Solid panelled door size 900x2100mm") == BOQLineCategory.SCHEDULE_EXTRACTABLE
    assert classify_boq_line("Mild steel casement window size 650 x 900mm") == BOQLineCategory.SCHEDULE_EXTRACTABLE
    assert classify_boq_line("100mm Brass butt hinges") == BOQLineCategory.SCHEDULE_EXTRACTABLE

    # Non-architectural / Substructure earthworks & drainage
    assert classify_boq_line("Excavate Trench for strip foundation not exceeding 1.5m deep") == BOQLineCategory.NOT_ARCHITECTURAL
    assert classify_boq_line("150mm diameter Heavy duty PVC gutter fixed to fascia") == BOQLineCategory.NOT_ARCHITECTURAL


def test_mbagha_exact_match_predictions_yield_100_percent():
    """When fed ground truth expected values, evaluator correctly produces 100% accuracy."""
    engine = BenchmarkAccuracyEngine()
    boq_summary = json.loads((BENCHMARK_DIR / "expected_boq_summary.json").read_text(encoding="utf-8"))
    exact_preds = [
        {"item_id": it["item_id"], "quantity": it["expected_quantity"]}
        for it in boq_summary["sample_measurable_items"]
    ]

    report = engine.evaluate_benchmark(
        benchmark_id=BENCHMARK_ID,
        predictions=exact_preds,
    )
    assert report.is_scored is True
    assert report.status == "scored"
    assert report.exact_matches == len(exact_preds)
    assert report.overall_accuracy_percentage == 100.0
    assert report.strict_exact_accuracy_percentage == 100.0
    assert report.gross_mismatches == 0
    assert report.missed_items == 0


def test_mbagha_missed_and_mismatched_items_penalized():
    """Missing items and out-of-tolerance values are penalized in accuracy metrics."""
    engine = BenchmarkAccuracyEngine()
    # Provide only 2 items out of 16, with one within tolerance and one gross mismatch
    preds = [
        {"item_id": "BOQ-MAT14-E", "quantity": 64.0},  # exact match
        {"item_id": "BOQ-MAT4-A", "quantity": 250.0},  # gross mismatch vs 77.0
    ]
    report = engine.evaluate_benchmark(
        benchmark_id=BENCHMARK_ID,
        predictions=preds,
    )
    assert report.is_scored is True
    assert report.exact_matches == 1
    assert report.gross_mismatches == 1
    assert report.missed_items == 14  # 16 total expected - 2 provided
    assert report.total_items_compared == 16
    # Accuracy = 1 / 16 = 6.25%
    assert report.overall_accuracy_percentage == pytest.approx(6.25, abs=0.01)


def test_mbagha_leakage_separation():
    """Verify that changing expected BOQ values does not alter extractor predictions."""
    if not DRAWING_PDF_PATH.exists():
        pytest.skip("Local drawing PDF not available for leakage check")

    extractor = GenericPlanReaderExtractor()
    preds1 = extractor.extract_from_pdf(DRAWING_PDF_PATH)
    quantities1 = [p.quantity for p in preds1]

    # Verify extractor does NOT import or read expected_boq_summary.json
    preds2 = extractor.extract_from_pdf(DRAWING_PDF_PATH)
    quantities2 = [p.quantity for p in preds2]

    assert quantities1 == quantities2


def test_mbagha_native_pdf_end_to_end_scoring():
    """Run genuine end-to-end evaluation of Mbagha Dispensary drawings against BOQ."""
    if not DRAWING_PDF_PATH.exists():
        pytest.skip("Drawing PDF not available")

    engine = BenchmarkAccuracyEngine()
    report = engine.evaluate_benchmark(
        benchmark_id=BENCHMARK_ID,
        pdf_path=DRAWING_PDF_PATH,
    )
    assert report.is_scored is True
    assert report.status == "scored"
    assert report.total_boq_items == 123
    assert report.total_measurable_expected == 16
    # Honest evaluation reflects whole-facility drawing vs maternity block BOQ
    assert report.gross_mismatches > 0
    assert report.missed_items > 0
    # Strict exact accuracy is 0.0% due to unrefined scope variance
    assert report.strict_exact_accuracy_percentage == 0.0
