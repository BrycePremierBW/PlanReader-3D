"""tests/benchmarks/test_benchmark_accuracy_engine.py

Comprehensive tests for PR F.3: Public Tender Benchmark Accuracy Evaluation Engine.
Verifies:
1. Unverified candidate seeds fail closed and cannot be scored in headline metrics.
2. Unscored benchmarks (no predictions / no PDF) return accuracy=None, is_scored=False.
3. Exact matching calculation.
4. Tolerance tiers (within 5%, within 10%, within 20%).
5. Gross mismatches (>20% error, or count discrepancies).
6. Missed items detection and penalty.
7. Hallucinated items detection and penalty.
8. Preliminaries and provisional sums non-penalization.
9. Structured JSON report generation and validity.
10. Formatted Markdown report rendering.
11. End-to-end evaluation against real verified benchmark PDF.
12. CLI / runner integration.
"""
import json
from pathlib import Path
import pytest

from pb_benchmark_accuracy_engine import (
    BenchmarkAccuracyEngine,
    BenchmarkAccuracyReport,
    ItemComparisonResult,
    ItemMatchStatus,
    run_public_tender_benchmark,
)
from pb_public_tender_benchmark import BOQLineCategory


@pytest.fixture
def engine():
    return BenchmarkAccuracyEngine()


def test_unverified_candidate_seed_fails_closed(engine):
    """Candidate unverified seeds must fail closed and never produce headline accuracy."""
    report = engine.evaluate_benchmark(
        benchmark_id="ungm_unops_wecc_torit",
        predictions=[{"item_id": "dummy", "quantity": 10.0}],
    )
    assert report.is_scored is False
    assert report.status == "candidate_unverified"
    assert report.overall_accuracy_percentage is None
    assert "unverified_candidate_seed_cannot_contribute_to_accuracy_metrics" in report.errors


def test_unscored_benchmark_returns_none(engine):
    """When no predictions and no PDF provided, benchmark is unscored with accuracy=None."""
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=None,
        pdf_path=None,
    )
    assert report.is_scored is False
    assert report.status == "candidate_unscored"
    assert report.overall_accuracy_percentage is None


def test_exact_matches_evaluation(engine):
    """Exact match predictions yield 100% accuracy and exact match counts."""
    predictions = [
        {"item_id": "BOQ-C36-A", "quantity": 58.0},
        {"item_id": "BOQ-C36-B", "quantity": 13.0},
        {"item_id": "BOQ-C41-B", "quantity": 2.0},
        {"item_id": "BOQ-C41-C", "quantity": 3.0},
        {"item_id": "BOQ-C44-A", "quantity": 1.0},
        {"item_id": "BOQ-C45-A", "quantity": 97.0},
        {"item_id": "BOQ-C45-B", "quantity": 1.0},
        {"item_id": "BOQ-C46-A", "quantity": 69.0},
        {"item_id": "BOQ-C46-C", "quantity": 69.0},
        {"item_id": "BOQ-C47-A", "quantity": 60.0},
        {"item_id": "BOQ-C47-B", "quantity": 20.0},
        {"item_id": "BOQ-C47-D", "quantity": 4.0},
        {"item_id": "BOQ-C31-C", "quantity": 102.0},
    ]
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
    )
    assert report.is_scored is True
    assert report.status == "scored"
    assert report.exact_matches == 13
    assert report.within_5_percent == 0
    assert report.gross_mismatches == 0
    assert report.missed_items == 0
    assert report.hallucinated_items == 0
    assert report.overall_accuracy_percentage == 100.0
    assert report.strict_exact_accuracy_percentage == 100.0


def test_tolerance_tiers_5_10_20_percent(engine):
    """Predictions within 5%, 10%, and 20% are correctly classified into tiers."""
    predictions = [
        # Expected 58.0 -> actual 59.5 (+2.59% -> within 5%)
        {"item_id": "BOQ-C36-A", "quantity": 59.5},
        # Expected 13.0 -> actual 14.0 (+7.69% -> within 10%)
        {"item_id": "BOQ-C36-B", "quantity": 14.0},
        # Expected 97.0 -> actual 110.0 (+13.40% -> within 20%)
        {"item_id": "BOQ-C45-A", "quantity": 110.0},
        # Exact items
        {"item_id": "BOQ-C41-B", "quantity": 2.0},
        {"item_id": "BOQ-C41-C", "quantity": 3.0},
        {"item_id": "BOQ-C44-A", "quantity": 1.0},
        {"item_id": "BOQ-C45-B", "quantity": 1.0},
        {"item_id": "BOQ-C46-A", "quantity": 69.0},
        {"item_id": "BOQ-C46-C", "quantity": 69.0},
        {"item_id": "BOQ-C47-A", "quantity": 60.0},
        {"item_id": "BOQ-C47-B", "quantity": 20.0},
        {"item_id": "BOQ-C47-D", "quantity": 4.0},
        {"item_id": "BOQ-C31-C", "quantity": 102.0},
    ]
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
    )
    assert report.exact_matches == 10
    assert report.within_5_percent == 1
    assert report.within_10_percent == 1
    assert report.within_20_percent == 1
    assert report.gross_mismatches == 0
    # Overall accuracy accepts exact + within 5% = 11 / 13 = 84.62%
    assert report.overall_accuracy_percentage == pytest.approx(84.62, abs=0.01)
    # Strict exact is 10 / 13 = 76.92%
    assert report.strict_exact_accuracy_percentage == pytest.approx(76.92, abs=0.01)


def test_gross_mismatches_detection(engine):
    """Divergences >20% or count mismatches are categorized as gross mismatches."""
    predictions = [
        # Expected 58.0 -> actual 85.0 (+46.55% -> gross mismatch)
        {"item_id": "BOQ-C36-A", "quantity": 85.0},
        # Count mismatch: expected 2.0 -> actual 3.0 (count mismatch -> gross mismatch)
        {"item_id": "BOQ-C41-B", "quantity": 3.0},
        # Keep rest exact
        {"item_id": "BOQ-C36-B", "quantity": 13.0},
        {"item_id": "BOQ-C41-C", "quantity": 3.0},
        {"item_id": "BOQ-C44-A", "quantity": 1.0},
        {"item_id": "BOQ-C45-A", "quantity": 97.0},
        {"item_id": "BOQ-C45-B", "quantity": 1.0},
        {"item_id": "BOQ-C46-A", "quantity": 69.0},
        {"item_id": "BOQ-C46-C", "quantity": 69.0},
        {"item_id": "BOQ-C47-A", "quantity": 60.0},
        {"item_id": "BOQ-C47-B", "quantity": 20.0},
        {"item_id": "BOQ-C47-D", "quantity": 4.0},
        {"item_id": "BOQ-C31-C", "quantity": 102.0},
    ]
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
    )
    assert report.gross_mismatches == 2
    assert report.exact_matches == 11
    # 11 / 13 = 84.62%
    assert report.overall_accuracy_percentage == pytest.approx(84.62, abs=0.01)


def test_missed_items_penalize_accuracy(engine):
    """Items present in BOQ but missing from predictions are counted as missed."""
    # Only provide 8 of the 13 items
    predictions = [
        {"item_id": "BOQ-C36-A", "quantity": 58.0},
        {"item_id": "BOQ-C36-B", "quantity": 13.0},
        {"item_id": "BOQ-C41-B", "quantity": 2.0},
        {"item_id": "BOQ-C41-C", "quantity": 3.0},
        {"item_id": "BOQ-C44-A", "quantity": 1.0},
        {"item_id": "BOQ-C45-A", "quantity": 97.0},
        {"item_id": "BOQ-C45-B", "quantity": 1.0},
        {"item_id": "BOQ-C46-A", "quantity": 69.0},
    ]
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
    )
    assert report.missed_items == 5
    assert report.exact_matches == 8
    # 8 / 13 = 61.54%
    assert report.overall_accuracy_percentage == pytest.approx(61.54, abs=0.01)


def test_hallucinated_items_penalize_accuracy(engine):
    """Extracted items with no counterpart in BOQ are counted as hallucinated items."""
    predictions = [
        {"item_id": "BOQ-C36-A", "quantity": 58.0},
        {"item_id": "BOQ-C36-B", "quantity": 13.0},
        {"item_id": "BOQ-C41-B", "quantity": 2.0},
        {"item_id": "BOQ-C41-C", "quantity": 3.0},
        {"item_id": "BOQ-C44-A", "quantity": 1.0},
        {"item_id": "BOQ-C45-A", "quantity": 97.0},
        {"item_id": "BOQ-C45-B", "quantity": 1.0},
        {"item_id": "BOQ-C46-A", "quantity": 69.0},
        {"item_id": "BOQ-C46-C", "quantity": 69.0},
        {"item_id": "BOQ-C47-A", "quantity": 60.0},
        {"item_id": "BOQ-C47-B", "quantity": 20.0},
        {"item_id": "BOQ-C47-D", "quantity": 4.0},
        {"item_id": "BOQ-C31-C", "quantity": 102.0},
    ]
    hallucinated = [
        {"item_id": "HALLUCINATED-SWIMMING-POOL", "quantity": 1.0, "unit": "NO"},
        {"item_id": "HALLUCINATED-ELEVATOR-SHAFT", "quantity": 1.0, "unit": "NO"},
    ]
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
        hallucinated_predictions=hallucinated,
    )
    assert report.hallucinated_items == 2
    assert report.exact_matches == 13
    # Total compared = 13 + 2 = 15. Accuracy = 13 / 15 = 86.67%
    assert report.total_items_compared == 15
    assert report.overall_accuracy_percentage == pytest.approx(86.67, abs=0.01)


def test_exclusions_preliminaries_and_provisional(engine, tmp_path):
    """Preliminaries and provisional sums are cleanly excluded without penalty."""
    # Create custom benchmark fixture with preliminary and provisional items
    custom_dir = tmp_path / "custom_bench"
    custom_dir.mkdir()

    (custom_dir / "source_manifest.json").write_text(json.dumps({
        "benchmark_id": "custom_bench",
        "project_name": "Test Project",
        "client": "Test Client",
        "status": "verified_public_benchmark",
    }))
    (custom_dir / "download_manifest.json").write_text(json.dumps({
        "tender_reference": "REF-001",
        "documents": [],
    }))
    (custom_dir / "expected_project.json").write_text(json.dumps({
        "project_name": "Test Project",
        "organization": "Test Org",
    }))
    (custom_dir / "benchmark_rules.json").write_text(json.dumps({}))
    (custom_dir / "expected_boq_summary.json").write_text(json.dumps({
        "total_line_items": 4,
        "sample_measurable_items": [
            {
                "item_id": "PRELIM-01",
                "description": "Contractor site establishment and hoarding",
                "expected_quantity": 1.0,
                "category": BOQLineCategory.PRELIMINARIES.value,
            },
            {
                "item_id": "PS-01",
                "description": "Provisional sum for rock excavation",
                "expected_quantity": 5000.0,
                "category": BOQLineCategory.PROVISIONAL_SUM.value,
            },
            {
                "item_id": "WALL-01",
                "description": "Block walling",
                "expected_quantity": 50.0,
                "category": BOQLineCategory.MEASURABLE_FROM_DRAWINGS.value,
            },
        ],
    }))

    eng = BenchmarkAccuracyEngine(benchmarks_dir=tmp_path)
    # Only supply prediction for physical walling
    report = eng.evaluate_benchmark(
        benchmark_id="custom_bench",
        predictions=[{"item_id": "WALL-01", "quantity": 50.0}],
    )
    assert report.is_scored is True
    assert report.preliminaries_excluded == 1
    assert report.provisional_sums_excluded == 1
    assert report.exact_matches == 1
    assert report.total_measurable_expected == 1
    assert report.overall_accuracy_percentage == 100.0


def test_json_and_markdown_report_generation(engine, tmp_path):
    """Engine generates valid JSON and Markdown reports with full breakdown."""
    predictions = [
        {"item_id": "BOQ-C36-A", "quantity": 58.0},
        {"item_id": "BOQ-C36-B", "quantity": 13.0},
    ]
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
    )
    json_path, md_path = engine.save_report(report, output_dir=tmp_path)

    assert json_path.exists()
    assert md_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["benchmark_id"] == "tenders_ke_kstvet_cbc_classroom"
    assert "summary" in data
    assert len(data["item_results"]) > 0

    md_content = md_path.read_text(encoding="utf-8")
    assert "# PlanReader Accuracy Evaluation Report" in md_content
    assert "Overall Accuracy" in md_content
    assert "BOQ-C36-A" in md_content
    assert "KSTVET/08/2024-AD01" in md_content


def test_convenience_runner(tmp_path):
    """run_public_tender_benchmark executes and writes reports to target dir."""
    predictions = [{"item_id": "BOQ-C36-A", "quantity": 58.0}]
    report = run_public_tender_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
        output_dir=tmp_path,
    )
    assert report.is_scored is True
    assert (tmp_path / "tenders_ke_kstvet_cbc_classroom_accuracy_report.json").exists()
    assert (tmp_path / "tenders_ke_kstvet_cbc_classroom_accuracy_report.md").exists()


def test_native_pdf_extraction_and_evaluation(engine):
    """If real tender PDF is present on disk, verify genuine independent extraction."""
    pdf_path = Path(r"C:\Users\bryce\Downloads\1727358888238-bq-nd-drawing.pdf")
    if not pdf_path.exists():
        pytest.skip("Verified tender PDF not present in local test environment")

    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        pdf_path=pdf_path,
    )
    assert report.is_scored is True
    # Post-cleanup: genuine schedule extraction without hardcoded fallbacks finds scheduled W1 and chalkboard exactly
    assert report.exact_matches >= 2
    assert report.total_items_compared == 12
    assert report.overall_accuracy_percentage > 0.0


def test_cli_main_entrypoint(monkeypatch, tmp_path):
    """Test main CLI entrypoint."""
    from pb_benchmark_accuracy_engine import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "pb_benchmark_accuracy_engine.py",
            "--benchmark",
            "tenders_ke_kstvet_cbc_classroom",
            "--output-dir",
            str(tmp_path),
        ],
    )
    pdf_path = Path(r"C:\Users\bryce\Downloads\1727358888238-bq-nd-drawing.pdf")
    code = main()
    if pdf_path.exists():
        assert code == 0
    else:
        assert code == 1


def test_malformed_benchmark_fails_closed(engine):
    """Non-existent benchmark fails closed gracefully with error."""
    report = engine.evaluate_benchmark(benchmark_id="non_existent_id")
    assert report.is_scored is False
    assert report.status == "failed_closed"
    assert len(report.errors) > 0

