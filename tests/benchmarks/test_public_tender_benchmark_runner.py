"""tests/benchmarks/test_public_tender_benchmark_runner.py — PR F.1 Test Suite.

Verifies end-to-end execution of public tender benchmarks:
- Discovery of public tender benchmarks under benchmarks/public_tenders/
- Execution of benchmark comparison
- Accuracy scoring excluding preliminaries and provisional sums
"""
from __future__ import annotations

import pytest
from pathlib import Path

from pb_public_tender_benchmark import (
    PublicTenderBenchmark,
    list_available_public_tender_benchmarks,
)


def test_list_available_public_tender_benchmarks():
    """Verify that all public tender benchmarks are discovered."""
    benchmarks = list_available_public_tender_benchmarks()
    assert len(benchmarks) >= 5

    expected_ids = {
        "ungm_unops_wecc_torit",
        "ungm_category_iv_housing_units",
        "ungm_category_iv_shelters",
        "ungm_fmns_faculty_building",
        "ungm_al_qayarah_hospital_renovation",
    }
    found_ids = {b.benchmark_id for b in benchmarks}
    for eid in expected_ids:
        assert eid in found_ids, f"Expected benchmark {eid} not found in discovery"


def test_public_tender_benchmark_loads_metadata():
    """Verify that PublicTenderBenchmark loads expected project and BOQ summaries."""
    bench = PublicTenderBenchmark.load("ungm_unops_wecc_torit")
    assert bench.benchmark_id == "ungm_unops_wecc_torit"
    assert bench.project_name == "UNOPS WECC Torit Vocational Training Centre"
    assert bench.organization == "UNOPS"
    assert len(bench.expected_boq_summary.get("classified_breakdown", {})) > 0


def test_evaluate_benchmark_accuracy_excludes_preliminaries():
    """Verify that accuracy evaluation excludes preliminaries from physical scoring denominator."""
    bench = PublicTenderBenchmark.load("ungm_unops_wecc_torit")
    result = bench.evaluate_accuracy_summary()
    assert "accuracy_score" in result
    assert "preliminaries_excluded_count" in result
    assert result["preliminaries_excluded_count"] > 0
