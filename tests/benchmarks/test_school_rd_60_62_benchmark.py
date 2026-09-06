"""tests/benchmarks/test_school_rd_60_62_benchmark.py — 60-62 School Rd Golden Benchmark Test Suite.

Verifies that 60-62 School Rd extracts documented GFA, unit counts, level counts,
entry door counts, excluded doors, staircases, render sheets, and enforces provisional
gating on unverified geometry.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from pb_benchmark_runner import PlanReaderBenchmarkRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks" / "plans"


def test_60_62_benchmark_manifest_and_quantities_load() -> None:
    """Verify 60-62 School Rd benchmark seed configuration."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR)
    manifest = runner.load_manifest("school_rd_60_62")
    assert manifest.benchmark_id == "school_rd_60_62"
    assert manifest.project_number == "26-017"
    assert "Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx" in manifest.allowed_comparison_sources
    assert "Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx" in manifest.rejected_comparison_sources

    expected_proj = runner.load_expected_project("school_rd_60_62")
    assert expected_proj.number_of_units == 9
    assert expected_proj.number_of_levels == 2
    assert expected_proj.sheet_count == 36

    quantities = runner.load_expected_quantities("school_rd_60_62")
    q_map = {q.quantity_id: q for q in quantities}
    assert q_map["internal_gfa_ground_floor"].expected_value == 650.0
    assert q_map["internal_gfa_level_1"].expected_value == 659.0
    assert q_map["internal_gfa_total"].expected_value == 1309.0
    assert q_map["dwelling_units_count"].expected_value == 9.0
    assert q_map["building_levels_count"].expected_value == 2.0
    assert q_map["entry_doors_count"].expected_value == 9.0
    assert q_map["internal_doors_excluded_count"].expected_value == 78.0
    assert q_map["staircase_allowance_count"].expected_value == 9.0


def test_60_62_render_pages_defined() -> None:
    """Verify 60-62 render / 3D sheets are tracked."""
    rp_file = BENCHMARKS_DIR / "school_rd_60_62" / "expected_render_pages.json"
    assert rp_file.exists()
    with open(rp_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert 1 in data["render_pages"]
    assert 2 in data["render_pages"]
    assert 3 in data["render_pages"]
    assert 4 in data["render_pages"]
    assert 35 in data["render_pages"]
    assert 36 in data["render_pages"]


def test_60_62_benchmark_execution_and_provisional_quantities(tmp_path: Path) -> None:
    """Run 60-62 benchmark and prove exact matches and provisional quantity classification."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR, results_dir=tmp_path)
    res = runner.run_benchmark("school_rd_60_62")

    assert res.benchmark_id == "school_rd_60_62"
    assert res.comparison_allowed is True
    assert res.project_identity["project_number"] == "26-017"

    q_res = {q["quantity_id"]: q for q in res.quantities_compared}
    assert q_res["internal_gfa_total"]["status"] == "exact_match"
    assert q_res["internal_gfa_total"]["actual"] == 1309.0

    assert q_res["internal_gfa_ground_floor"]["status"] == "exact_match"
    assert q_res["internal_gfa_ground_floor"]["actual"] == 650.0

    assert q_res["internal_gfa_level_1"]["status"] == "exact_match"
    assert q_res["internal_gfa_level_1"]["actual"] == 659.0

    assert q_res["dwelling_units_count"]["status"] == "exact_match"
    assert q_res["dwelling_units_count"]["actual"] == 9.0

    assert q_res["building_levels_count"]["status"] == "exact_match"
    assert q_res["building_levels_count"]["actual"] == 2.0

    # Provisional external substrate quantity must be marked provisional_only
    ext_q = q_res["external_substrate_provisional_area"]
    assert ext_q["status"] == "provisional_only"
    assert "provisional" in ext_q["notes"].lower()


def test_60_62_rejects_92_94_takeoff_mismatch(tmp_path: Path) -> None:
    """Prove 60-62 School Rd fails closed and blocks comparison when 92-94 takeoff is supplied."""
    runner = PlanReaderBenchmarkRunner(benchmarks_dir=BENCHMARKS_DIR, results_dir=tmp_path)
    # Pass 92-94 takeoff filename override to test mismatch gating
    res = runner.run_benchmark(
        "school_rd_60_62",
        takeoff_path_override=Path("Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx"),
    )
    assert res.comparison_allowed is False
    assert res.rejection_reason == "wrong_project_source_mismatch"
    assert all(q["status"] == "source_mismatch" for q in res.quantities_compared)
    assert res.summary["accuracy_score"] == 0.0
    assert res.summary["readiness_score"] == 0.0
