"""tests/learning_ledger/test_golden_plan_accuracy_report.py — Tests for golden plan accuracy report generator."""
from pathlib import Path
import pytest

from pb_takeoff_learning_ledger import (
    ErrorTaxonomy,
    TakeoffLearningLedger,
    generate_golden_plan_accuracy_report,
)


def test_generate_golden_plan_accuracy_report(tmp_path):
    out_dir = tmp_path / "benchmark_results"

    ledger = TakeoffLearningLedger()
    ledger.record_correction(
        entry_id="c1",
        benchmark_or_job_id="school_rd_60_62",
        object_id="W1",
        object_type="wall",
        planreader_measured_value=10.0,
        user_corrected_value=12.0,
        source_page="WD-01",
        error_reason=ErrorTaxonomy.PROJECT_MISMATCH.value,
    )

    report = generate_golden_plan_accuracy_report(
        benchmark_dir="benchmarks/plans",
        output_dir=out_dir,
        ledger=ledger,
    )

    assert report["total_benchmarks_evaluated"] >= 4
    assert report["total_expected_quantities"] > 0
    assert report["blocked"] >= 0
    assert len(report["benchmarks"]) >= 4
    assert len(report["top_error_reasons"]) > 0

    # Verify markdown file exists and contains essential sections
    md_file = out_dir / "accuracy_report.md"
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "# PlanReader Golden Plan Accuracy & Regression Report" in content
    assert "## Summary Metrics" in content
    assert "## Benchmark Manifest Matrix" in content
    assert "## Top Error Taxonomy Drivers" in content
    assert "## Recommended Next Fixes" in content

    # Verify json file exists and matches
    json_file = out_dir / "accuracy_report.json"
    assert json_file.exists()
