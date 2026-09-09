"""Handoff locks for the frozen opening-count shadow family.

These tests do not change extraction. They keep isolation, gate thresholds,
false-positive regressions, and evaluator ordering from drifting.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from pb_shadow_opening_count_eval import run_project_shadow, score_frozen_quantities
from pb_shadow_opening_count_gate import (
    OPENING_COUNT_AUTHORITY_RECOMMENDATION,
    OPENING_COUNT_AUTHORITY_STATE,
    OPENING_COUNT_MIGRATION_GATE,
    evaluate_opening_count_migration_gate,
)
import pb_shadow_opening_count_eval as eval_mod
import pb_shadow_opening_count_provider as provider_mod
import pb_shadow_opening_evidence as evidence_mod


REQUIRED_REGRESSION_TESTS = {
    "tests/test_shadow_opening_count_provider.py": {
        "test_bill_pages_are_not_drawing_opening_evidence",
        "test_dimension_only_geometry_does_not_create_identities",
        "test_duplicate_detail_and_elevation_do_not_inflate_count",
        "test_provider_and_shadow_runner_are_gold_free",
    },
    "tests/test_shadow_opening_count_evidence.py": {
        "test_builders_work_and_nrm_tables_are_not_opening_schedules",
        "test_work_section_codes_are_not_door_or_window_marks",
        "test_ocr_ambiguity_does_not_normalize_to_nearest_mark",
        "test_raster_opening_schedule_is_read_and_raster_boq_is_rejected",
        "test_notes_detail_title_and_legend_marks_are_not_counted",
        "test_elevation_only_is_supporting_evidence_not_a_type_total",
    },
    "tests/test_shadow_opening_count_gate.py": {
        "test_migration_gate_was_predeclared_and_is_not_relaxed",
    },
}

_FORBIDDEN_IMPORT_TOKENS = (
    "benchmark_accuracy_engine",
    "public_tender_benchmark",
    "benchmark_runner",
    "holdout_suite",
    "expected_boq",
    "expected_project",
    "benchmark_rules",
    "item_mappings",
    "pb_shadow_opening_count_eval",
    "pb_quantity_commercial_adapter",
)

_PRODUCTION_MUST_NOT_IMPORT_SHADOW = (
    "pb_planreader_pdf_extractor.py",
    "pb_legacy_extractor_adapter.py",
    "pb_quantity_prediction_adapter.py",
    "pb_takeoff_output_authority.py",
    "pb_quantity_commercial_adapter.py",
)


def _imported_modules(source: str) -> list[str]:
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_required_false_positive_regressions_remain_registered() -> None:
    for relative, names in REQUIRED_REGRESSION_TESTS.items():
        found = _function_names(Path(relative))
        missing = names - found
        assert not missing, f"{relative} missing {sorted(missing)}"


def test_canonical_gate_stays_frozen_and_does_not_promote_authority() -> None:
    assert OPENING_COUNT_MIGRATION_GATE == {
        "min_precision_on_answered_identities": 0.99,
        "min_exact_correctness_on_answered_counts": 0.99,
        "max_dimension_derived_fake_identities": 0,
        "max_critical_duplicate_counts": 0,
        "require_complete_provenance_on_accepted": True,
        "conflicts_must_fail_closed_or_review": True,
    }
    assert OPENING_COUNT_AUTHORITY_STATE == "new_shadow"
    assert OPENING_COUNT_AUTHORITY_RECOMMENDATION == "remain_new_shadow"
    result = evaluate_opening_count_migration_gate(
        {
            "precision_on_answered_identities": 1.0,
            "exact_correctness_on_answered_counts": 1.0,
            "dimension_derived_fake_identities": 0,
            "critical_duplicate_counts": 0,
            "accepted_answered_count": 15,
            "accepted_missing_provenance": 0,
            "conflict_not_fail_closed": 0,
        }
    )
    assert result["decision"] == "PASS"
    assert result["authority_recommendation"] == "remain_new_shadow"
    assert result["authority_state"] == "new_shadow"
    assert result["coverage_is_not_a_gate_input"] is True


def test_provider_and_evidence_stay_isolated_from_gold_and_scoring() -> None:
    for module in (provider_mod, evidence_mod):
        source = inspect.getsource(module)
        imported = _imported_modules(source)
        leaked = [
            name
            for name in imported
            if any(token in name.lower() for token in _FORBIDDEN_IMPORT_TOKENS)
        ]
        assert leaked == []
        assert "NEW_SELECTIVE" not in source
        assert "NEW_AUTHORITATIVE" not in source
        assert "expected_quantity" not in source
        assert "tenders_ke_olv_laboratory_complex" not in source


def test_production_authority_modules_do_not_import_the_shadow_provider() -> None:
    for relative in _PRODUCTION_MUST_NOT_IMPORT_SHADOW:
        path = Path(relative)
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        imported = _imported_modules(source)
        assert "pb_shadow_opening_count_provider" not in imported
        assert "pb_shadow_opening_evidence" not in imported
        assert "pb_shadow_opening_count_eval" not in imported
        assert "shadow_opening_count" not in source


def test_evaluator_freezes_outputs_before_gold_join() -> None:
    source = inspect.getsource(run_project_shadow)
    extract_at = source.index("extract_bundle")
    freeze_at = source.index("frozen = tuple(bundle.quantities)")
    gold_at = source.index("load_eligible_opening_items")
    score_at = source.index("score_frozen_quantities")
    assert extract_at < freeze_at < gold_at < score_at
    assert inspect.getsource(score_frozen_quantities).count("extract_bundle") == 0
    report_source = inspect.getsource(eval_mod.run_development_shadow_report)
    assert "remain_new_shadow" in report_source or "OPENING_COUNT_AUTHORITY_RECOMMENDATION" in report_source
    assert "gold_joined_after_freeze" in report_source


def test_reproducible_report_command_is_documented() -> None:
    script = Path("scripts/run_shadow_opening_count_report.py").read_text(encoding="utf-8")
    contract = Path("docs/shadow_opening_count_provider_contract.md").read_text(encoding="utf-8")
    command = "python3 scripts/run_shadow_opening_count_report.py"
    assert command in script
    assert command in contract
    assert "shadow_reports/opening_count_shadow_development.json" in script
    assert "NEW_SHADOW" in contract
    assert "remain NEW_SHADOW" in contract
