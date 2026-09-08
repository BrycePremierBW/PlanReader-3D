"""tests/benchmarks/test_mutation_holdout_suite_registry.py

Mutation/red-team suite for pb_holdout_suite_registry: registration
validation, project-level separation, and checksum-based tamper
detection. Every project identity, filename, and content value in this
file is synthetic and invented for this test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pb_holdout_suite_registry import (
    HoldoutRegistrationError,
    check_project_level_separation,
    list_registered_holdout_projects,
    register_holdout_project,
    verify_holdout_untouched,
)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_valid_project(
    tmp_path: Path,
    name: str,
    *,
    project_name: str = "Synthetic Test Project",
    project_number: str = "SYN/001/26",
    client: str = "Synthetic Ministry of Testing",
    expected_quantity: float = 42.0,
) -> Path:
    project_dir = tmp_path / name
    project_dir.mkdir()
    _write_json(project_dir / "source_manifest.json", {
        "benchmark_id": name,
        "project_name": project_name,
        "project_number": project_number,
        "client": client,
        "status": "verified_scored_benchmark",
    })
    _write_json(project_dir / "benchmark_rules.json", {"benchmark_id": name, "tolerances": {}})
    _write_json(project_dir / "expected_project.json", {"project_name": project_name})
    _write_json(project_dir / "expected_boq_summary.json", {
        "benchmark_id": name,
        "sample_measurable_items": [{"item_id": "X-1", "expected_quantity": expected_quantity}],
    })
    return project_dir


class TestRegistrationValidation:
    def test_valid_project_registers_successfully(self, tmp_path: Path) -> None:
        project_dir = _make_valid_project(tmp_path, "synth_project_a")
        record = register_holdout_project(project_dir)
        assert record.project_id == "synth_project_a"
        assert len(record.expected_boq_summary_sha256) == 64
        assert (project_dir / ".holdout_lock.json").exists()

    def test_missing_required_file_is_rejected(self, tmp_path: Path) -> None:
        project_dir = _make_valid_project(tmp_path, "synth_project_b")
        (project_dir / "expected_boq_summary.json").unlink()
        with pytest.raises(HoldoutRegistrationError, match="missing required file"):
            register_holdout_project(project_dir)

    def test_malformed_json_is_rejected(self, tmp_path: Path) -> None:
        project_dir = _make_valid_project(tmp_path, "synth_project_c")
        (project_dir / "benchmark_rules.json").write_text("{not valid json", encoding="utf-8")
        with pytest.raises(HoldoutRegistrationError, match="not valid JSON"):
            register_holdout_project(project_dir)

    def test_nonexistent_directory_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(HoldoutRegistrationError):
            register_holdout_project(tmp_path / "does_not_exist")


class TestProjectLevelSeparation:
    def test_matching_project_number_blocks_registration(self, tmp_path: Path) -> None:
        dev_dir = _make_valid_project(tmp_path, "dev_project", project_number="DEV/999/26")
        candidate_dir = _make_valid_project(
            tmp_path, "holdout_candidate", project_number="DEV/999/26",  # same number
        )
        with pytest.raises(HoldoutRegistrationError, match="project-level separation violated"):
            register_holdout_project(candidate_dir, development_project_dirs=[dev_dir])

    def test_distinct_projects_register_cleanly(self, tmp_path: Path) -> None:
        dev_dir = _make_valid_project(
            tmp_path, "dev_project",
            project_name="Development Diagnostic School Block",
            project_number="DEV/999/26",
            client="Development Ministry",
        )
        candidate_dir = _make_valid_project(
            tmp_path, "holdout_candidate",
            project_name="Unrelated Holdout Hospital Wing",
            project_number="HOLD/001/26",
            client="Holdout Ministry",
        )
        record = register_holdout_project(candidate_dir, development_project_dirs=[dev_dir])
        assert record.project_id == "holdout_candidate"

    def test_check_project_level_separation_reports_the_matching_field(self, tmp_path: Path) -> None:
        dev_dir = _make_valid_project(tmp_path, "dev_project", client="Shared Ministry")
        candidate_manifest = {
            "project_name": "Different Name",
            "project_number": "DIFFERENT/1",
            "client": "Shared Ministry",
        }
        collisions = check_project_level_separation(candidate_manifest, [dev_dir])
        assert len(collisions) == 1
        assert "client" in collisions[0]


class TestTamperDetection:
    def test_untouched_project_verifies_clean(self, tmp_path: Path) -> None:
        project_dir = _make_valid_project(tmp_path, "synth_project_d")
        register_holdout_project(project_dir)
        result = verify_holdout_untouched(project_dir)
        assert result.is_untouched is True
        assert result.mismatches == []

    def test_editing_expected_quantities_after_registration_is_detected(self, tmp_path: Path) -> None:
        project_dir = _make_valid_project(tmp_path, "synth_project_e", expected_quantity=42.0)
        register_holdout_project(project_dir)

        # Someone edits the answer key after registration (e.g. to "fix" a score).
        _write_json(project_dir / "expected_boq_summary.json", {
            "benchmark_id": "synth_project_e",
            "sample_measurable_items": [{"item_id": "X-1", "expected_quantity": 999.0}],
        })

        result = verify_holdout_untouched(project_dir)
        assert result.is_untouched is False
        assert any("expected_boq_summary.json" in m for m in result.mismatches)

    def test_never_registered_project_fails_verification(self, tmp_path: Path) -> None:
        project_dir = _make_valid_project(tmp_path, "synth_project_f")
        result = verify_holdout_untouched(project_dir)
        assert result.is_untouched is False
        assert "never registered" in result.mismatches[0]


class TestListing:
    def test_list_only_returns_registered_projects(self, tmp_path: Path) -> None:
        registered_dir = _make_valid_project(tmp_path, "registered_one")
        register_holdout_project(registered_dir)
        _make_valid_project(tmp_path, "unregistered_one")  # never registered

        registered = list_registered_holdout_projects(tmp_path)
        assert registered == ["registered_one"]

    def test_empty_root_returns_empty_list(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "nothing_here"
        assert list_registered_holdout_projects(empty_root) == []
