#!/usr/bin/env python3
"""scripts/run_planreader_benchmarks.py — CLI Benchmark Runner for PlanReader.

Executes accuracy benchmarks against golden benchmark plans, enforces source project
matching, evaluates tolerances, and writes machine-readable benchmark reports.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pb_benchmark_runner import PlanReaderBenchmarkRunner


def print_result_summary(result) -> None:
    """Print human-readable summary of benchmark execution."""
    d = result.to_dict()
    summary = d["summary"]

    print("=" * 70)
    print(f"Benchmark:           {d['benchmark_id']}")
    print(f"Source PDF:          {d['source_pdf'] or 'Not supplied (synthetic fallback)'}")
    print(f"Source takeoff:      {d['source_takeoff'] or 'Not supplied (unmatched/none)'}")
    print(f"Project identity:    {d['project_identity'].get('project_name')} [{d['project_identity'].get('project_number')}]")
    print(f"Comparison allowed:  {d['comparison_allowed']}" + (f" (BLOCKED: {d['rejection_reason']})" if not d['comparison_allowed'] else " (CONFIRMED)"))
    
    pages_cls = d.get("pages_classified", {})
    if pages_cls and "total_pages" in pages_cls:
        print(f"Pages classified:    {pages_cls['total_pages']} total sheets | {len(pages_cls.get('render_pages_detected', []))} render sheets")
    else:
        print("Pages classified:    None (PDF not available in current environment)")

    print(f"Quantities compared: {len(d['quantities_compared'])}")
    print(f"Pass:                {summary['pass_count']}")
    print(f"Fail:                {summary['fail_count']}")
    print(f"Warnings:            {summary['warnings_count']}")
    print(f"Provisional:         {summary['provisional_count']}")
    print(f"Exact match:         {summary['exact_match_count']}")
    print(f"Within tolerance:    {summary['within_tolerance_count']}")
    print(f"Outside tolerance:   {summary['outside_tolerance_count']}")
    print(f"Missing:             {summary['missing_count']}")
    print(f"Accuracy score:      {summary['accuracy_score'] * 100:.1f}%")
    print(f"Readiness score:     {summary['readiness_score'] * 100:.1f}%")
    print("=" * 70)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="PlanReader Accuracy Benchmark CLI Runner")
    parser.add_argument("--benchmark", help="Benchmark ID to run (e.g. school_rd_60_62, lago_britinya)")
    parser.add_argument("--all", action="store_true", help="Run all available benchmark seeds")
    parser.add_argument("--pdf", help="Optional override path to source PDF")
    parser.add_argument("--takeoff", help="Optional override path to source takeoff workbook")
    parser.add_argument("--benchmarks-dir", default="benchmarks/plans", help="Directory containing benchmark folders")
    parser.add_argument("--results-dir", default="benchmark_results", help="Directory to save benchmark reports")
    args = parser.parse_args()

    runner = PlanReaderBenchmarkRunner(
        benchmarks_dir=args.benchmarks_dir,
        results_dir=args.results_dir,
    )

    benchmarks_to_run = []
    if args.all:
        bench_dir = Path(args.benchmarks_dir)
        for child in sorted(bench_dir.iterdir()):
            if child.is_dir() and (child / "source_manifest.json").exists():
                benchmarks_to_run.append(child.name)
    elif args.benchmark:
        benchmarks_to_run.append(args.benchmark)
    else:
        parser.print_help()
        return 1

    print(f"Running PlanReader Benchmarks: {', '.join(benchmarks_to_run)}")
    all_passed = True

    for bid in benchmarks_to_run:
        try:
            res = runner.run_benchmark(
                benchmark_id=bid,
                pdf_path_override=args.pdf,
                takeoff_path_override=args.takeoff,
            )
            print_result_summary(res)
            # If comparison blocked on a benchmark that expects allowed comparison, flag failure
            if bid == "school_rd_60_62" and not res.comparison_allowed:
                all_passed = False
        except Exception as exc:
            print(f"Error running benchmark {bid}: {exc}")
            import traceback
            traceback.print_exc()
            all_passed = False

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
