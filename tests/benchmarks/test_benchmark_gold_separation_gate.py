"""Mutation coverage for benchmark-gold / production-code PR separation."""
from __future__ import annotations

import pytest

from scripts.check_benchmark_gold_separation import (
    check_paths,
    find_separation_violation,
    is_benchmark_defining_file,
    is_production_code_file,
)


def test_expected_boq_summary_is_benchmark_defining() -> None:
    assert is_benchmark_defining_file(
        "benchmarks/public_tenders/synthetic_project/expected_boq_summary.json"
    )


def test_all_four_benchmark_defining_files_are_protected() -> None:
    for filename in (
        "source_manifest.json",
        "benchmark_rules.json",
        "expected_project.json",
        "expected_boq_summary.json",
    ):
        assert is_benchmark_defining_file(
            f"benchmarks/public_tenders/synthetic_project/{filename}"
        )


def test_production_python_is_classified_but_tests_are_not() -> None:
    assert is_production_code_file("pb_planreader_pdf_extractor.py")
    assert is_production_code_file("planreader_takeoff_studio/frontend/studio.js")
    assert not is_production_code_file("tests/benchmarks/test_example.py")
    assert not is_production_code_file(
        "benchmarks/public_tenders/synthetic_project/benchmark_rules.json"
    )


def test_mixed_extractor_and_gold_change_is_rejected() -> None:
    with pytest.raises(SystemExit, match="Benchmark-integrity separation gate failed"):
        check_paths(
            [
                "pb_planreader_pdf_extractor.py",
                "benchmarks/public_tenders/synthetic_project/expected_boq_summary.json",
                "tests/benchmarks/test_synthetic.py",
            ]
        )


def test_benchmark_maintenance_with_tests_is_allowed() -> None:
    check_paths(
        [
            "benchmarks/public_tenders/synthetic_project/expected_boq_summary.json",
            "tests/benchmarks/test_synthetic.py",
            "docs/benchmark_verification.md",
        ]
    )


def test_production_only_change_is_allowed() -> None:
    check_paths(
        [
            "pb_planreader_pdf_extractor.py",
            "tests/benchmarks/test_mutation_synthetic.py",
        ]
    )


def test_source_manifest_plus_benchmark_runner_is_rejected() -> None:
    benchmark_files, production_files = find_separation_violation(
        [
            "benchmarks/public_tenders/synthetic_project/source_manifest.json",
            "scripts/run_planreader_benchmarks.py",
        ]
    )
    assert benchmark_files == [
        "benchmarks/public_tenders/synthetic_project/source_manifest.json"
    ]
    assert production_files == ["scripts/run_planreader_benchmarks.py"]


def test_windows_style_paths_are_normalized() -> None:
    assert is_benchmark_defining_file(
        r"benchmarks\public_tenders\synthetic_project\benchmark_rules.json"
    )
    assert is_production_code_file(r"planreader_takeoff_studio\frontend\studio.js")
