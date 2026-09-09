"""tests/benchmarks/test_headline_accuracy_dashboard.py

PR F.6: Test Suite for Multi-Benchmark Headline Accuracy Dashboard & Suite Runner.

Verifies:
1. evaluate_suite discovers all registered public tender benchmarks.
2. Candidate seeds (candidate_unverified) are strictly excluded from headline metrics.
3. Scope-divergence stress tests (verified_scope_mismatch) are strictly excluded from headline metrics.
4. Mathematical aggregation across headline-eligible benchmarks (verified_scored_benchmark).
5. Dashboard serialization (to_dict, to_json) integrity.
6. Executive Markdown report rendering (tables, callouts, and sections).
7. Simulated multi-benchmark prediction evaluation.
8. File output generation for dashboard JSON and Markdown.
9. CLI --all execution produces exit code 0.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import pytest

from pb_benchmark_accuracy_engine import (
    BenchmarkAccuracyEngine,
    BenchmarkAccuracyReport,
    HeadlineAccuracyDashboard,
    run_public_tender_benchmark_suite,
)
from pb_public_tender_benchmark import PublicTenderBenchmark, list_available_public_tender_benchmarks


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks" / "public_tenders"
RESULTS_DIR = REPO_ROOT / "benchmark_results"


def test_evaluate_suite_discovers_all_benchmarks(tmp_path: Path):
    """evaluate_suite discovers all benchmarks and categorizes them correctly."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)
    dashboard = engine.evaluate_suite(auto_extract=False)

    assert dashboard.total_headline_benchmarks == 3
    assert dashboard.total_stress_test_benchmarks == 1
    assert dashboard.total_candidate_seeds >= 6

    # Verify headline benchmark IDs
    headline_ids = [r.benchmark_id for r in dashboard.headline_reports]
    assert "tenders_ke_kstvet_cbc_classroom" in headline_ids
    assert "tenders_ke_murera_science_lab" in headline_ids
    assert "tenders_ke_ghazi_science_lab" in headline_ids

    # Verify stress test benchmark IDs
    stress_ids = [r.benchmark_id for r in dashboard.stress_test_reports]
    assert "tenders_ke_mbagha_maternity_dispensary" in stress_ids

    # Verify candidate seed IDs
    candidate_ids = [r.benchmark_id for r in dashboard.candidate_seed_reports]
    assert "ungm_unops_wecc_torit" in candidate_ids
    assert "king_st_122_126" in candidate_ids


def test_candidate_seeds_strictly_excluded_from_headline_metrics(tmp_path: Path):
    """Candidate seeds have zero contribution to headline accuracy metrics."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)
    dashboard = engine.evaluate_suite(auto_extract=False)

    for cand_report in dashboard.candidate_seed_reports:
        assert cand_report.is_headline_eligible is False
        assert cand_report.is_scored is False
        assert cand_report.overall_accuracy_percentage is None

    # Check that candidate items are not added into headline items compared
    headline_item_count = sum(r.total_items_compared for r in dashboard.headline_reports)
    assert dashboard.total_headline_items_compared == headline_item_count


def test_scope_mismatch_benchmarks_strictly_excluded_from_headline_metrics(tmp_path: Path):
    """Scope mismatch stress tests (e.g. Mbagha Dispensary) do not dilute headline metrics."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)
    dashboard = engine.evaluate_suite(auto_extract=False)

    for stress_report in dashboard.stress_test_reports:
        assert stress_report.is_headline_eligible is False
        assert stress_report.status in ("verified_scope_mismatch", "candidate_unscored")

    # Headline reports contain only verified_scored_benchmark
    for head_report in dashboard.headline_reports:
        assert head_report.is_headline_eligible is True


def test_headline_accuracy_mathematical_aggregation(tmp_path: Path):
    """Verify exact mathematical aggregation of headline accuracy across benchmarks."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)

    # Provide controlled mock predictions for both headline benchmarks
    predictions_by_bench = {
        "tenders_ke_kstvet_cbc_classroom": [
            {"item_id": "BOQ-C36-A", "quantity": 58.0},  # exact match
            {"item_id": "BOQ-C36-B", "quantity": 13.0},  # exact match
        ],
        "tenders_ke_murera_science_lab": [
            {"item_id": "roof_trusses", "quantity": 13.0},            # exact match
            {"item_id": "steel_casement_windows", "quantity": 12.0},  # exact match
        ],
    }

    dashboard = engine.evaluate_suite(
        auto_extract=False,
        predictions_by_benchmark=predictions_by_bench,
    )

    tot_expected = sum(r.total_measurable_expected for r in dashboard.headline_reports)
    tot_compared = sum(r.total_items_compared for r in dashboard.headline_reports)
    tot_exact = sum(r.exact_matches for r in dashboard.headline_reports)
    tot_w5 = sum(r.within_5_percent for r in dashboard.headline_reports)

    assert dashboard.total_headline_measurable_expected == tot_expected
    assert dashboard.total_headline_items_compared == tot_compared
    assert dashboard.total_headline_exact_matches == tot_exact == 4  # 2 + 2
    assert dashboard.total_headline_within_5_percent == tot_w5

    expected_overall = round(((tot_exact + tot_w5) / tot_compared) * 100.0, 2)
    expected_strict = round((tot_exact / tot_compared) * 100.0, 2)

    assert dashboard.headline_overall_accuracy == expected_overall
    assert dashboard.headline_strict_exact_accuracy == expected_strict


def test_dashboard_serialization_round_trip(tmp_path: Path):
    """Dashboard serializes to dictionary and JSON with full fidelity."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)
    dashboard = engine.evaluate_suite(auto_extract=False)

    d_dict = dashboard.to_dict()
    assert "timestamp" in d_dict
    assert "headline_metrics" in d_dict
    assert "summary_counts" in d_dict
    assert "headline_reports" in d_dict
    assert "stress_test_reports" in d_dict
    assert "candidate_seed_reports" in d_dict

    d_json = dashboard.to_json(indent=2)
    parsed = json.loads(d_json)
    assert parsed["summary_counts"]["headline_benchmarks"] == 3
    assert parsed["summary_counts"]["stress_test_benchmarks"] == 1
    assert parsed["summary_counts"]["candidate_seeds"] >= 6


def test_dashboard_markdown_rendering(tmp_path: Path):
    """Markdown rendering includes executive summary, headline tables, and exclusion sections."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)
    dashboard = engine.evaluate_suite(auto_extract=False)

    md = dashboard.to_markdown()
    assert "# PlanReader Public Tender Benchmark — Executive Headline Accuracy Dashboard" in md
    assert "## 1. Executive Headline Metrics" in md
    assert "## 2. Headline Benchmark Breakdown" in md
    assert "## 3. Real-World Scope Divergence Stress Tests" in md
    assert "## 4. Candidate Seed Inventory" in md
    assert "## 5. Non-Penalized Denominator Exclusions" in md
    assert "tenders_ke_kstvet_cbc_classroom" in md
    assert "tenders_ke_murera_science_lab" in md
    assert "tenders_ke_ghazi_science_lab" in md
    assert "tenders_ke_mbagha_maternity_dispensary" in md


def test_save_dashboard_generates_files(tmp_path: Path):
    """save_dashboard writes both JSON and Markdown files to the target directory."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=BENCHMARKS_DIR, output_dir=tmp_path)
    dashboard = engine.evaluate_suite(auto_extract=False)
    j_path, m_path = engine.save_dashboard(dashboard, output_dir=tmp_path)

    assert j_path.exists()
    assert m_path.exists()
    assert j_path.name == "headline_accuracy_dashboard.json"
    assert m_path.name == "headline_accuracy_dashboard.md"
    assert j_path.stat().st_size > 0
    assert m_path.stat().st_size > 0


def test_cli_all_execution():
    """Executing CLI with --all flag exits code 0 and prints headline dashboard."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "pb_benchmark_accuracy_engine.py"),
        "--all",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert res.returncode == 0
    assert "PLANREADER PUBLIC TENDER BENCHMARK" in res.stdout
    assert "Official Headline Accuracy" in res.stdout
    assert "Scored Headline Benchmarks:            3" in res.stdout
