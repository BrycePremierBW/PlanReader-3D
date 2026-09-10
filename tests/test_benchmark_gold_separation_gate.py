from __future__ import annotations

import pytest

from scripts.check_benchmark_gold_separation import (
    check_paths,
    find_separation_violation,
    is_benchmark_defining_file,
)


def test_public_tender_gold_plus_production_fails() -> None:
    with pytest.raises(SystemExit):
        check_paths([
            "benchmarks/public_tenders/example/expected_project.json",
            "pb_extractor.py",
        ])


def test_plan_expected_quantities_plus_production_fails() -> None:
    with pytest.raises(SystemExit):
        check_paths([
            "benchmarks/plans/example/expected_quantities.json",
            "pb_measurement.py",
        ])


def test_plan_tolerances_plus_production_fails() -> None:
    with pytest.raises(SystemExit):
        check_paths([
            "benchmarks/plans/example/tolerances.json",
            "planreader_takeoff_studio/frontend/studio.js",
        ])


def test_plan_expected_schedules_plus_production_fails() -> None:
    with pytest.raises(SystemExit):
        check_paths([
            "benchmarks/plans/example/expected_schedules.json",
            "pb_schedule_extractor.py",
        ])


def test_future_expected_json_is_benchmark_defining() -> None:
    assert is_benchmark_defining_file("benchmarks/plans/example/expected_openings.json")


def test_harmless_notes_and_download_metadata_are_not_gold() -> None:
    assert not is_benchmark_defining_file("benchmarks/plans/example/notes.md")
    assert not is_benchmark_defining_file("benchmarks/public_tenders/example/download_manifest.json")


def test_benchmark_only_changes_are_allowed() -> None:
    benchmark, production = find_separation_violation([
        "benchmarks/plans/example/expected_quantities.json",
        "benchmarks/plans/example/tolerances.json",
        "tests/test_benchmark_runner.py",
    ])
    assert benchmark == []
    assert production == []


def test_production_only_changes_are_allowed() -> None:
    benchmark, production = find_separation_violation(["pb_measurement.py", "frontend/app.js"])
    assert benchmark == []
    assert production == []


def test_windows_path_separators_are_normalized() -> None:
    with pytest.raises(SystemExit):
        check_paths([
            r"benchmarks\plans\example\expected_quantities.json",
            r"src\measurement.py",
        ])


def test_nested_suite_paths_are_recognized() -> None:
    assert is_benchmark_defining_file(
        "benchmarks/plans/group/subsuite/project/expected_render_pages.json"
    )


def test_manifest_and_source_definition_files_are_protected() -> None:
    assert is_benchmark_defining_file("benchmarks/public_tenders/manifest.json")
    assert is_benchmark_defining_file("benchmarks/public_tenders/example/source_manifest.json")
    assert is_benchmark_defining_file("benchmarks/public_tenders/example/benchmark_rules.json")
