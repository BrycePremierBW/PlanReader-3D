"""Focused recovery tests for atomic benchmark report-set publication.

These tests exercise the rebased Cursor reporting-integrity work without
reintroducing its stale three-benchmark assumptions.  All quantities and
identifiers below are synthetic.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import threading

import pytest

from pb_benchmark_accuracy_engine import BenchmarkAccuracyEngine
import pb_benchmark_report_set as report_set
from pb_benchmark_report_set import (
    CLASSIFICATION_DEVELOPMENT,
    MixedRunIdError,
    ProjectReportSpec,
    ReportRunContext,
    load_and_validate_current_report_set,
    new_run_id,
    public_combined_summary_from_projects,
    publish_report_set,
    utc_now_iso,
)


SYNTHETIC_COMMIT = "a" * 40


def _context() -> ReportRunContext:
    return ReportRunContext(
        run_id=new_run_id(),
        evaluated_commit_sha=SYNTHETIC_COMMIT,
        started_at=utc_now_iso(),
    )


def _payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "classification": CLASSIFICATION_DEVELOPMENT,
        "status": "scored",
        "is_scored": True,
        "is_headline_eligible": True,
        "summary": {
            "total_boq_items": 2,
            "total_measurable_expected": 2,
            "total_items_compared": 2,
            "exact_matches": 1,
            "within_5_percent": 0,
            "within_10_percent": 0,
            "within_20_percent": 0,
            "gross_mismatches": 0,
            "missed_items": 1,
            "hallucinated_items": 0,
            "overall_accuracy_percentage": 50.0,
            "strict_exact_accuracy_percentage": 50.0,
        },
        "item_results": [
            {
                "item_id": "SYN-A",
                "status": "exact_match",
                "tolerance_tier": "exact",
                "extracted_quantity": 10.0,
            },
            {
                "item_id": "SYN-B",
                "status": "missed_in_extraction",
                "tolerance_tier": "missed",
                "extracted_quantity": None,
            },
        ],
        "errors": [],
    }


def _spec(project_id: str) -> ProjectReportSpec:
    return ProjectReportSpec(
        project_id=project_id,
        classification=CLASSIFICATION_DEVELOPMENT,
        report_payload=_payload(project_id),
    )


def test_report_set_publishes_one_shared_run_identity(tmp_path: Path):
    context = _context()
    specs = [_spec("synth_alpha"), _spec("synth_beta")]
    published = publish_report_set(
        tmp_path,
        context=context,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_alpha"), _payload("synth_beta")]
        ),
    )

    assert published["pointer"]["run_id"] == context.run_id
    assert published["manifest"]["run_id"] == context.run_id
    assert published["combined"]["run_id"] == context.run_id
    assert {p["run_id"] for p in published["projects"]} == {context.run_id}
    assert {p["evaluated_commit_sha"] for p in published["projects"]} == {SYNTHETIC_COMMIT}


def test_mixed_run_id_is_rejected(tmp_path: Path):
    context = _context()
    published = publish_report_set(
        tmp_path,
        context=context,
        project_specs=[_spec("synth_alpha")],
        combined_summary=public_combined_summary_from_projects([_payload("synth_alpha")]),
    )
    project_path = published["run_dir"] / "projects" / "synth_alpha.json"
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload["run_id"] = "f" * 32
    project_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MixedRunIdError):
        load_and_validate_current_report_set(tmp_path)


def test_concurrent_publishers_never_mix_runs(tmp_path: Path):
    errors: list[BaseException] = []

    def _worker(name: str) -> None:
        try:
            publish_report_set(
                tmp_path,
                context=_context(),
                project_specs=[_spec(name)],
                combined_summary=public_combined_summary_from_projects([_payload(name)]),
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    workers = [
        threading.Thread(target=_worker, args=("synth_alpha",)),
        threading.Thread(target=_worker, args=("synth_beta",)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert errors == []
    current = load_and_validate_current_report_set(tmp_path)
    run_ids = {current["combined"]["run_id"]}
    run_ids.update(p["run_id"] for p in current["projects"])
    assert len(run_ids) == 1


def test_windows_compatibility_facade_precedes_recovered_fcntl_import():
    source = inspect.getsource(report_set)
    assert "os.name != \"nt\"" in source
    assert "msvcrt.locking" in source
    assert "from _pb_benchmark_report_set_impl import *" in source


def test_current_four_benchmark_suite_materializes_one_report_run(tmp_path: Path):
    output = tmp_path / "reports"
    engine = BenchmarkAccuracyEngine(output_dir=output)
    dashboard = engine.evaluate_suite(
        auto_extract=False,
        output_dir=output,
        require_source_documents=False,
        require_local_gold=False,
    )

    assert dashboard.total_headline_benchmarks == 4
    current = load_and_validate_current_report_set(output)
    run_id = current["manifest"]["run_id"]
    dashboard_json = json.loads(
        (output / "headline_accuracy_dashboard.json").read_text(encoding="utf-8")
    )
    kstvet_json = json.loads(
        (output / "tenders_ke_kstvet_cbc_classroom_accuracy_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard_json["run_id"] == run_id
    assert kstvet_json["run_id"] == run_id
