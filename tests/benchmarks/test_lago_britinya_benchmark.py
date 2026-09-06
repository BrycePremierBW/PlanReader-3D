"""tests/benchmarks/test_lago_britinya_benchmark.py — LAGO Birtinya Benchmark Test Suite.

Verifies LAGO Birtinya benchmark seed, drawing set sheet count, external elevation
ground truth fixtures, render sheet detection, and strict mismatch blocking against
School Rd takeoffs.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from pb_benchmark_runner import PlanReaderBenchmarkRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks" / "plans"


def test_lago_manifest_and_quantities_load() -> None:
    """Verify LAGO benchmark configuration."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR)
    manifest = runner.load_manifest("lago_britinya")
    assert manifest.benchmark_id == "lago_britinya"
    assert manifest.project_number == "260617_004"
    assert "Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx" in manifest.rejected_comparison_sources
    assert "Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx" in manifest.rejected_comparison_sources

    expected_proj = runner.load_expected_project("lago_britinya")
    assert expected_proj.sheet_count == 207

    quantities = runner.load_expected_quantities("lago_britinya")
    q_map = {q.quantity_id: q for q in quantities}
    assert q_map["lago_total_sheets_count"].expected_value == 207.0
    assert q_map["lago_cd3001_p86_east_glazed_lights_count"].expected_value == 9.0
    assert q_map["lago_cd3001_p86_opening_height_m"].expected_value == pytest.approx(1.489)
    assert q_map["lago_cd3001_p86_opening_light_width_m"].expected_value == pytest.approx(0.773)


def test_lago_rejects_60_62_takeoff_mismatch(tmp_path: Path) -> None:
    """Prove LAGO blocks comparison against 60-62 School Rd takeoff."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR, results_dir=tmp_path)
    res = runner.run_benchmark(
        "lago_britinya",
        takeoff_path_override=Path("Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx"),
    )
    assert res.comparison_allowed is False
    assert res.rejection_reason == "wrong_project_source_mismatch"
    assert all(q["status"] == "source_mismatch" for q in res.quantities_compared)


def test_lago_rejects_92_94_takeoff_mismatch(tmp_path: Path) -> None:
    """Prove LAGO blocks comparison against 92-94 School Rd takeoff."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR, results_dir=tmp_path)
    res = runner.run_benchmark(
        "lago_britinya",
        takeoff_path_override=Path("Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx"),
    )
    assert res.comparison_allowed is False
    assert res.rejection_reason == "wrong_project_source_mismatch"
    assert all(q["status"] == "source_mismatch" for q in res.quantities_compared)


def test_lago_benchmark_execution_and_fixtures(tmp_path: Path) -> None:
    """Run LAGO benchmark and prove verified ground truth fixture comparison."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR, results_dir=tmp_path)
    res = runner.run_benchmark("lago_britinya")

    assert res.benchmark_id == "lago_britinya"
    assert res.comparison_allowed is True

    q_res = {q["quantity_id"]: q for q in res.quantities_compared}
    assert q_res["lago_total_sheets_count"]["status"] == "exact_match"
    assert q_res["lago_total_sheets_count"]["actual"] == 207.0

    assert q_res["lago_cd3001_p86_east_glazed_lights_count"]["status"] == "exact_match"
    assert q_res["lago_cd3001_p86_east_glazed_lights_count"]["actual"] == 9.0

    assert q_res["lago_cd3001_p86_opening_height_m"]["status"] == "exact_match"
    assert q_res["lago_cd3001_p86_opening_height_m"]["actual"] == pytest.approx(1.489, abs=0.01)

    assert q_res["lago_cd3001_p86_opening_light_width_m"]["status"] == "exact_match"
    assert q_res["lago_cd3001_p86_opening_light_width_m"]["actual"] == pytest.approx(0.773, abs=0.01)
