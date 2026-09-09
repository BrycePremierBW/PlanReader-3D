"""Atomic benchmark report-set publication and consumption.

All projects, documents, hashes, and quantities in this file are invented
synthetic fixtures.  They are not benchmark gold and must not be treated
as real tender quantities.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import threading

import pytest

from pb_benchmark_accuracy_engine import BenchmarkAccuracyEngine
from pb_benchmark_report_set import (
    CLASSIFICATION_DEVELOPMENT,
    CLASSIFICATION_DIAGNOSTIC,
    CLASSIFICATION_UNTOUCHED_HOLDOUT,
    ArtifactHashMismatchError,
    ClassificationMixError,
    IncompleteReportSetError,
    MalformedTimestampError,
    MissingLocalGoldError,
    MissingSourceDocumentError,
    MixedCommitError,
    MixedRunIdError,
    PointerIncompleteError,
    ProjectReportSpec,
    ReportRunContext,
    SCORING_POLICY_IDENTIFIER,
    StaleReportError,
    SourceHashInvalidationError,
    UnexpectedArtifactError,
    UnsupportedSchemaError,
    detect_stale_legacy_reports,
    load_and_validate_current_report_set,
    new_run_id,
    opaque_holdout_project_id,
    project_payload_from_accuracy_report,
    public_combined_summary_from_projects,
    publish_current_pointer,
    publish_report_set,
    score_content,
    sha256_bytes,
    sha256_file,
    utc_now_iso,
    write_incomplete_run_for_tests,
)


SYNTHETIC_COMMIT_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SYNTHETIC_COMMIT_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _context(commit: str = SYNTHETIC_COMMIT_A, run_id: str | None = None) -> ReportRunContext:
    return ReportRunContext(
        run_id=run_id or new_run_id(),
        evaluated_commit_sha=commit,
        started_at=utc_now_iso(),
    )


def _summary(**overrides):
    payload = {
        "total_boq_items": 3,
        "total_measurable_expected": 2,
        "total_items_compared": 3,
        "exact_matches": 1,
        "within_5_percent": 0,
        "within_10_percent": 0,
        "within_20_percent": 0,
        "gross_mismatches": 0,
        "missed_items": 1,
        "hallucinated_items": 1,
        "overall_accuracy_percentage": 33.33,
        "strict_exact_accuracy_percentage": 33.33,
    }
    payload.update(overrides)
    return payload


def _item(status: str, tier: str, item_id: str, extracted=None):
    return {
        "item_id": item_id,
        "status": status,
        "tolerance_tier": tier,
        "extracted_quantity": extracted,
    }


def _payload(project_id: str, classification: str, **overrides):
    payload = {
        "project_id": project_id,
        "classification": classification,
        "status": "scored",
        "is_scored": True,
        "is_headline_eligible": classification == CLASSIFICATION_DEVELOPMENT,
        "summary": _summary(),
        "item_results": [
            _item("exact_match", "exact", "SYN-WALL-1", 12.0),
            _item("missed_in_extraction", "missed", "SYN-DOOR-1", None),
            _item("hallucinated_item", "hallucinated", "SYN-EXTRA-1", 4.0),
        ],
        "errors": [],
    }
    payload.update(overrides)
    return payload


def _spec(
    project_id: str,
    classification: str,
    *,
    source_hashes=None,
    required_source_documents=None,
    required_gold_files=None,
    raw_benchmark_id=None,
    **payload_overrides,
) -> ProjectReportSpec:
    return ProjectReportSpec(
        project_id=project_id,
        classification=classification,
        report_payload=_payload(project_id, classification, **payload_overrides),
        source_hashes=source_hashes or {},
        required_source_documents=required_source_documents or {},
        required_gold_files=required_gold_files or {},
        raw_benchmark_id=raw_benchmark_id,
    )


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    target = tmp_path / "reports"
    target.mkdir()
    return target


def test_combined_and_project_reports_share_one_run_id(output_dir: Path):
    ctx = _context()
    specs = [
        _spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT),
        _spec("synth_dev_beta", CLASSIFICATION_DEVELOPMENT),
    ]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload(s.project_id, s.classification) for s in specs]
        ),
    )
    run_ids = {published["manifest"]["run_id"], published["combined"]["run_id"]}
    run_ids.update(p["run_id"] for p in published["projects"])
    assert run_ids == {ctx.run_id}


def test_every_report_records_the_same_evaluated_commit(output_dir: Path):
    ctx = _context(SYNTHETIC_COMMIT_A)
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    shas = {published["manifest"]["evaluated_commit_sha"], published["combined"]["evaluated_commit_sha"]}
    shas.update(p["evaluated_commit_sha"] for p in published["projects"])
    assert shas == {SYNTHETIC_COMMIT_A}


def test_every_report_records_the_same_scoring_policy(output_dir: Path):
    ctx = _context()
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    policies = {
        published["manifest"]["scoring_policy_identifier"],
        published["combined"]["scoring_policy_identifier"],
    }
    policies.update(p["scoring_policy_identifier"] for p in published["projects"])
    assert policies == {SCORING_POLICY_IDENTIFIER}


def test_complete_generation_publishes_current_pointer(output_dir: Path):
    ctx = _context()
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    pointer = json.loads((output_dir / "current.json").read_text(encoding="utf-8"))
    assert pointer["run_id"] == ctx.run_id
    assert pointer["completion_state"] == "complete"
    assert published["pointer"]["run_id"] == ctx.run_id


def test_interrupted_generation_preserves_prior_complete_current_run(output_dir: Path):
    first = _context()
    first_specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    publish_report_set(
        output_dir,
        context=first,
        project_specs=first_specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    interrupted = _context()
    write_incomplete_run_for_tests(
        output_dir,
        context=interrupted,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_beta", CLASSIFICATION_DEVELOPMENT)]
        ),
        project_specs=[_spec("synth_dev_beta", CLASSIFICATION_DEVELOPMENT)],
        omit_project_ids=["synth_dev_beta"],
    )
    current = load_and_validate_current_report_set(output_dir)
    assert current["manifest"]["run_id"] == first.run_id
    assert current["pointer"]["run_id"] == first.run_id


def test_missing_project_reports_prevent_publication(output_dir: Path):
    ctx = _context()
    specs = [
        _spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT),
        _spec("synth_dev_beta", CLASSIFICATION_DEVELOPMENT),
    ]
    run_dir = write_incomplete_run_for_tests(
        output_dir,
        context=ctx,
        combined_summary=public_combined_summary_from_projects(
            [_payload(s.project_id, s.classification) for s in specs]
        ),
        project_specs=specs,
        omit_project_ids=["synth_dev_beta"],
        completion_state="complete",
    )
    with pytest.raises((IncompleteReportSetError, UnexpectedArtifactError)):
        publish_current_pointer(output_dir, run_dir)
    assert not (output_dir / "current.json").exists()


def test_extra_unexpected_reports_invalidate_publication(output_dir: Path):
    published = publish_report_set(
        output_dir,
        context=_context(),
        project_specs=[_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)],
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    extra = {
        "schema_version": "1.0.0",
        "run_id": published["manifest"]["run_id"],
        "evaluated_commit_sha": SYNTHETIC_COMMIT_A,
        "scoring_policy_identifier": SCORING_POLICY_IDENTIFIER,
        "generated_at": utc_now_iso(),
        "project_id": "synth_unexpected",
        "classification": CLASSIFICATION_DEVELOPMENT,
        "summary": _summary(),
        "item_results": [],
        "evaluator_version": published["manifest"]["evaluator_version"],
    }
    (published["run_dir"] / "projects" / "unexpected.json").write_text(
        json.dumps(extra), encoding="utf-8"
    )
    with pytest.raises(UnexpectedArtifactError):
        load_and_validate_current_report_set(output_dir)


def test_mixed_run_ids_are_rejected(output_dir: Path):
    ctx = _context()
    specs = [
        _spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT),
        _spec("synth_dev_beta", CLASSIFICATION_DEVELOPMENT),
    ]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload(s.project_id, s.classification) for s in specs]
        ),
    )
    mixed_path = published["run_dir"] / "projects" / "synth_dev_beta.json"
    payload = json.loads(mixed_path.read_text(encoding="utf-8"))
    payload["run_id"] = "ffffffffffffffffffffffffffffffff"
    mixed_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MixedRunIdError):
        load_and_validate_current_report_set(output_dir)


def test_mixed_commit_shas_are_rejected(output_dir: Path):
    ctx = _context(SYNTHETIC_COMMIT_A)
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    path = published["run_dir"] / "projects" / "synth_dev_alpha.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evaluated_commit_sha"] = SYNTHETIC_COMMIT_B
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MixedCommitError):
        load_and_validate_current_report_set(output_dir)


def test_changed_source_hashes_invalidate_prior_reports(output_dir: Path):
    digest_a = sha256_bytes(b"synthetic-drawing-bytes-v1")
    digest_b = sha256_bytes(b"synthetic-drawing-bytes-v2")
    specs = [
        _spec(
            "synth_dev_alpha",
            CLASSIFICATION_DEVELOPMENT,
            source_hashes={"source_pdf": digest_a},
        )
    ]
    publish_report_set(
        output_dir,
        context=_context(),
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    with pytest.raises(SourceHashInvalidationError):
        load_and_validate_current_report_set(
            output_dir,
            current_source_hashes={"synth_dev_alpha:source_pdf": digest_b},
        )


def test_changed_artifact_content_fails_hash_validation(output_dir: Path):
    ctx = _context()
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    combined_path = published["run_dir"] / "combined_summary.json"
    payload = json.loads(combined_path.read_text(encoding="utf-8"))
    payload["headline_metrics"]["exact_matches"] = 99
    combined_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactHashMismatchError):
        load_and_validate_current_report_set(output_dir)


def test_missing_source_documents_fail_explicitly(output_dir: Path, tmp_path: Path):
    missing_pdf = tmp_path / "does_not_exist.pdf"
    specs = [
        _spec(
            "synth_dev_alpha",
            CLASSIFICATION_DEVELOPMENT,
            required_source_documents={"source_pdf": missing_pdf},
        )
    ]
    with pytest.raises(MissingSourceDocumentError):
        publish_report_set(
            output_dir,
            context=_context(),
            project_specs=specs,
            combined_summary=public_combined_summary_from_projects(
                [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
            ),
            require_source_documents=True,
        )
    assert not (output_dir / "current.json").exists()


def test_missing_local_gold_fails_explicitly(output_dir: Path, tmp_path: Path):
    missing_gold = tmp_path / "missing_expected.json"
    specs = [
        _spec(
            "synth_dev_alpha",
            CLASSIFICATION_DEVELOPMENT,
            required_gold_files={"local_gold": missing_gold},
        )
    ]
    with pytest.raises(MissingLocalGoldError):
        publish_report_set(
            output_dir,
            context=_context(),
            project_specs=specs,
            combined_summary=public_combined_summary_from_projects(
                [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
            ),
            require_local_gold=True,
        )
    assert not (output_dir / "current.json").exists()


def test_development_and_holdout_reports_cannot_be_combined(output_dir: Path):
    holdout_raw = "synthetic_holdout_never_public"
    holdout_id = opaque_holdout_project_id(holdout_raw)
    specs = [
        _spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT),
        _spec(
            holdout_id,
            CLASSIFICATION_UNTOUCHED_HOLDOUT,
            raw_benchmark_id=holdout_raw,
        ),
    ]
    with pytest.raises(ClassificationMixError):
        publish_report_set(
            output_dir,
            context=_context(),
            project_specs=specs,
            combined_summary={"headline_metrics": {}},
        )


def test_identical_repeated_runs_match_apart_from_run_metadata(output_dir: Path):
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    combined = public_combined_summary_from_projects(
        [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    )
    first = publish_report_set(
        output_dir / "run_a",
        context=_context(),
        project_specs=specs,
        combined_summary=combined,
    )
    second = publish_report_set(
        output_dir / "run_b",
        context=_context(),
        project_specs=specs,
        combined_summary=combined,
    )
    assert score_content(first["combined"]) == score_content(second["combined"])
    assert score_content(first["projects"][0]) == score_content(second["projects"][0])
    assert first["manifest"]["run_id"] != second["manifest"]["run_id"]


def test_path_rename_with_identical_content_hash_does_not_change_score(output_dir: Path, tmp_path: Path):
    content = b"%PDF-synthetic-identical-bytes\n"
    original = _write_bytes(tmp_path / "drawings" / "north_wing.pdf", content)
    renamed = _write_bytes(tmp_path / "archive" / "renamed_drawing.pdf", content)
    digest = sha256_file(original)
    assert digest == sha256_file(renamed)
    specs_a = [
        _spec(
            "synth_dev_alpha",
            CLASSIFICATION_DEVELOPMENT,
            source_hashes={"source_pdf": digest},
            required_source_documents={"source_pdf": original},
        )
    ]
    specs_b = [
        _spec(
            "synth_dev_alpha",
            CLASSIFICATION_DEVELOPMENT,
            source_hashes={"source_pdf": digest},
            required_source_documents={"source_pdf": renamed},
        )
    ]
    combined = public_combined_summary_from_projects(
        [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    )
    first = publish_report_set(
        output_dir / "a",
        context=_context(),
        project_specs=specs_a,
        combined_summary=combined,
        require_source_documents=True,
    )
    second = publish_report_set(
        output_dir / "b",
        context=_context(),
        project_specs=specs_b,
        combined_summary=combined,
        require_source_documents=True,
    )
    assert score_content(first["combined"]) == score_content(second["combined"])
    assert first["manifest"]["source_hashes"] == second["manifest"]["source_hashes"]


def test_atomic_pointer_never_targets_incomplete_run(output_dir: Path):
    ctx = _context()
    run_dir = write_incomplete_run_for_tests(
        output_dir,
        context=ctx,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
        project_specs=[_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)],
        omit_project_ids=["synth_dev_alpha"],
        completion_state="incomplete",
    )
    with pytest.raises((PointerIncompleteError, IncompleteReportSetError)):
        publish_current_pointer(output_dir, run_dir)
    assert not (output_dir / "current.json").exists()


def test_concurrent_writers_cannot_publish_a_mixed_report_set(output_dir: Path):
    errors: list[BaseException] = []

    def _publish(suffix: str) -> None:
        try:
            specs = [_spec(f"synth_dev_{suffix}", CLASSIFICATION_DEVELOPMENT)]
            publish_report_set(
                output_dir,
                context=_context(),
                project_specs=specs,
                combined_summary=public_combined_summary_from_projects(
                    [_payload(f"synth_dev_{suffix}", CLASSIFICATION_DEVELOPMENT)]
                ),
            )
        except BaseException as exc:  # noqa: BLE001 — collect any concurrent failure
            errors.append(exc)

    workers = [
        threading.Thread(target=_publish, args=("alpha",)),
        threading.Thread(target=_publish, args=("beta",)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == []
    current = load_and_validate_current_report_set(output_dir)
    assert current["pointer"]["completion_state"] == "complete"
    project_ids = {p["project_id"] for p in current["projects"]}
    assert project_ids in ({"synth_dev_alpha"}, {"synth_dev_beta"})
    run_ids = {p["run_id"] for p in current["projects"]}
    run_ids.add(current["combined"]["run_id"])
    assert len(run_ids) == 1


def test_stale_reports_are_detected(output_dir: Path):
    first = publish_report_set(
        output_dir,
        context=_context(),
        project_specs=[_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)],
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    stale = output_dir / "synth_dev_alpha_accuracy_report.json"
    stale.write_text(
        json.dumps(
            {
                "run_id": "stale-run-id",
                "evaluated_commit_sha": SYNTHETIC_COMMIT_B,
                "summary": {"exact_matches": 0},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(StaleReportError):
        detect_stale_legacy_reports(output_dir, legacy_report_paths=[stale])
    fresh = output_dir / "legacy_from_current.json"
    stale_ok = {
        "run_id": first["manifest"]["run_id"],
        "evaluated_commit_sha": first["manifest"]["evaluated_commit_sha"],
    }
    fresh.write_text(json.dumps(stale_ok), encoding="utf-8")
    detect_stale_legacy_reports(output_dir, legacy_report_paths=[fresh])


def test_unsupported_schema_versions_are_rejected(output_dir: Path):
    ctx = _context()
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    manifest_path = published["run_dir"] / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(UnsupportedSchemaError):
        load_and_validate_current_report_set(output_dir)


def test_malformed_timestamps_are_rejected(output_dir: Path):
    ctx = _context()
    specs = [_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
    published = publish_report_set(
        output_dir,
        context=ctx,
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    combined_path = published["run_dir"] / "combined_summary.json"
    payload = json.loads(combined_path.read_text(encoding="utf-8"))
    payload["generated_at"] = "yesterday-afternoon"
    combined_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((MalformedTimestampError, ArtifactHashMismatchError)):
        load_and_validate_current_report_set(output_dir)


def test_hallucinations_and_missed_items_remain_represented(output_dir: Path):
    payload = _payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)
    published = publish_report_set(
        output_dir,
        context=_context(),
        project_specs=[_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)],
        combined_summary=public_combined_summary_from_projects([payload]),
    )
    statuses = {item["status"] for item in published["projects"][0]["item_results"]}
    assert "hallucinated_item" in statuses
    assert "missed_in_extraction" in statuses
    assert published["combined"]["headline_metrics"]["hallucinated_items"] == 1
    assert published["combined"]["headline_metrics"]["missed_items"] == 1


def test_tolerance_bins_remain_mutually_exclusive(output_dir: Path):
    payload = _payload(
        "synth_dev_alpha",
        CLASSIFICATION_DEVELOPMENT,
        item_results=[
            _item("exact_match", "exact", "SYN-A", 10.0),
            _item("within_5_percent", "5%", "SYN-B", 10.4),
            _item("within_10_percent", "10%", "SYN-C", 10.8),
            _item("within_20_percent", "20%", "SYN-D", 11.5),
            _item("gross_mismatch", "gross", "SYN-E", 20.0),
        ],
        summary=_summary(
            exact_matches=1,
            within_5_percent=1,
            within_10_percent=1,
            within_20_percent=1,
            gross_mismatches=1,
            missed_items=0,
            hallucinated_items=0,
            total_items_compared=5,
            total_measurable_expected=5,
        ),
    )
    published = publish_report_set(
        output_dir,
        context=_context(),
        project_specs=[
            ProjectReportSpec(
                project_id="synth_dev_alpha",
                classification=CLASSIFICATION_DEVELOPMENT,
                report_payload=payload,
            )
        ],
        combined_summary=public_combined_summary_from_projects([payload]),
    )
    tiers = [item["tolerance_tier"] for item in published["projects"][0]["item_results"]]
    assert len(tiers) == len(set(tiers))


def test_reporting_changes_do_not_change_benchmark_score(tmp_path: Path):
    engine = BenchmarkAccuracyEngine(output_dir=tmp_path / "reports")
    predictions = [
        {"item_id": "BOQ-C36-A", "quantity": 58.0},
        {"item_id": "BOQ-C36-B", "quantity": 13.0},
    ]
    before = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
        auto_extract=False,
    )
    dashboard = engine.evaluate_suite(
        auto_extract=False,
        predictions_by_benchmark={"tenders_ke_kstvet_cbc_classroom": predictions},
        output_dir=tmp_path / "reports",
        require_local_gold=True,
        require_source_documents=False,
    )
    after = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=predictions,
        auto_extract=False,
    )
    assert before.exact_matches == after.exact_matches
    assert before.within_5_percent == after.within_5_percent
    assert before.total_items_compared == after.total_items_compared
    assert before.overall_accuracy_percentage == after.overall_accuracy_percentage
    kstvet = next(
        r for r in dashboard.headline_reports if r.benchmark_id == "tenders_ke_kstvet_cbc_classroom"
    )
    assert kstvet.exact_matches == before.exact_matches
    assert kstvet.overall_accuracy_percentage == before.overall_accuracy_percentage


def test_extractor_runtime_modules_remain_separated_from_report_modules():
    import pb_planreader_pdf_extractor

    source = inspect.getsource(pb_planreader_pdf_extractor)
    forbidden = [
        "pb_benchmark_report_set",
        "run_manifest.json",
        "combined_summary.json",
        "current.json",
        "benchmark_results",
        "expected_boq_summary.json",
    ]
    for term in forbidden:
        assert term not in source


def test_public_summaries_do_not_contain_raw_expected_quantities(output_dir: Path):
    published = publish_report_set(
        output_dir,
        context=_context(),
        project_specs=[_spec("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)],
        combined_summary=public_combined_summary_from_projects(
            [_payload("synth_dev_alpha", CLASSIFICATION_DEVELOPMENT)]
        ),
    )
    blob = json.dumps({"combined": published["combined"], "projects": published["projects"]})
    assert "expected_quantity" not in blob
    assert "expected_quantities" not in blob
    assert "sample_measurable_items" not in blob


def test_protected_holdout_identifiers_are_not_exposed(output_dir: Path):
    raw_id = "synthetic_frozen_holdout_omega"
    project_id = opaque_holdout_project_id(raw_id)
    assert raw_id not in project_id
    specs = [
        _spec(
            project_id,
            CLASSIFICATION_UNTOUCHED_HOLDOUT,
            raw_benchmark_id=raw_id,
        )
    ]
    published = publish_report_set(
        output_dir,
        context=_context(),
        project_specs=specs,
        combined_summary=public_combined_summary_from_projects(
            [_payload(project_id, CLASSIFICATION_UNTOUCHED_HOLDOUT)]
        ),
    )
    blob = json.dumps(
        {
            "pointer": published["pointer"],
            "manifest": published["manifest"],
            "combined": published["combined"],
            "projects": published["projects"],
        }
    )
    assert raw_id not in blob
    assert project_id in blob


def test_suite_legacy_aliases_share_the_published_run(tmp_path: Path):
    engine = BenchmarkAccuracyEngine(output_dir=tmp_path / "reports")
    dashboard = engine.evaluate_suite(
        auto_extract=False,
        output_dir=tmp_path / "reports",
        require_local_gold=True,
        require_source_documents=False,
    )
    current = load_and_validate_current_report_set(tmp_path / "reports")
    run_id = current["manifest"]["run_id"]
    dashboard_json = json.loads(
        (tmp_path / "reports" / "headline_accuracy_dashboard.json").read_text(encoding="utf-8")
    )
    assert dashboard_json["run_id"] == run_id
    project_report = json.loads(
        (tmp_path / "reports" / "tenders_ke_kstvet_cbc_classroom_accuracy_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert project_report["run_id"] == run_id
    assert dashboard.total_headline_benchmarks == 3


def test_project_payload_from_accuracy_report_does_not_recompute_scores():
    engine = BenchmarkAccuracyEngine()
    report = engine.evaluate_benchmark(
        benchmark_id="tenders_ke_kstvet_cbc_classroom",
        predictions=[{"item_id": "BOQ-C36-A", "quantity": 58.0}],
    )
    payload = project_payload_from_accuracy_report(
        report,
        classification=CLASSIFICATION_DEVELOPMENT,
        project_id="synth_copy",
    )
    assert payload["summary"]["exact_matches"] == report.exact_matches
    assert payload["summary"]["missed_items"] == report.missed_items
    assert payload["summary"]["overall_accuracy_percentage"] == report.overall_accuracy_percentage
    assert "expected_quantity" not in json.dumps(payload)
