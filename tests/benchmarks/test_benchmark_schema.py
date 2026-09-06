"""tests/benchmarks/test_benchmark_schema.py — Validate Benchmark JSON Schema Integrity.

Ensures all golden benchmark plans, source manifests, expected quantities,
schedules, and tolerances adhere strictly to the JSON schemas.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from pb_benchmark_schema import (
    EXPECTED_PROJECT_SCHEMA,
    EXPECTED_QUANTITIES_SCHEMA,
    EXPECTED_RENDER_PAGES_SCHEMA,
    SOURCE_MANIFEST_SCHEMA,
    TOLERANCES_SCHEMA,
    validate_benchmark_folder,
    validate_json_schema,
)

BENCHMARKS_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "plans"


def test_all_benchmark_folders_exist_and_validate() -> None:
    """Verify that all benchmark folders exist and pass full schema validation."""
    assert BENCHMARKS_DIR.exists(), f"Benchmark folder not found at {BENCHMARKS_DIR}"

    expected_benchmarks = ["school_rd_60_62", "lago_britinya", "school_rd_92_94", "king_st_122_126"]
    for b_id in expected_benchmarks:
        b_folder = BENCHMARKS_DIR / b_id
        assert b_folder.exists(), f"Expected benchmark folder {b_id} does not exist"
        ok, report = validate_benchmark_folder(b_folder)
        assert ok is True, f"Benchmark folder {b_id} failed validation: {report}"


def test_invalid_manifest_fails_schema_validation() -> None:
    """Ensure malformed source manifest is caught by validator."""
    invalid_manifest = {
        "benchmark_id": "test_invalid",
        # Missing project_name, project_number, client, drawing_issue, drawing_date
        "status": "seed",
    }
    ok, errors = validate_json_schema(invalid_manifest, SOURCE_MANIFEST_SCHEMA)
    assert ok is False
    assert len(errors) >= 1
    assert any("required" in err.lower() for err in errors)


def test_invalid_quantity_item_fails_schema_validation() -> None:
    """Ensure invalid expected quantity item schema is rejected."""
    invalid_quantities = [
        {
            "quantity_id": "q1",
            "description": "Missing required fields",
            "expected_value": "not_a_number",  # Type error
            "unit": "m2",
            "source": {"document": "test"},     # Missing required 'sheet'
            "authority": "unapproved_random_tag", # Invalid authority enum
        }
    ]
    ok, errors = validate_json_schema(invalid_quantities, EXPECTED_QUANTITIES_SCHEMA)
    assert ok is False
    assert len(errors) >= 1


def test_valid_quantity_authorities() -> None:
    """Ensure expected quantities only use allowed authority states."""
    allowed_authorities = {
        "documented",
        "schedule_extracted",
        "pdf_scaled",
        "ai_detected",
        "user_corrected",
        "user_approved",
        "model_derived",
        "provisional",
        "excluded",
        "reference_only",
    }
    for b_folder in BENCHMARKS_DIR.iterdir():
        if b_folder.is_dir() and (b_folder / "expected_quantities.json").exists():
            with open(b_folder / "expected_quantities.json", "r", encoding="utf-8") as f:
                quantities = json.load(f)
            for q in quantities:
                assert q["authority"] in allowed_authorities, (
                    f"Invalid authority '{q['authority']}' in {b_folder.name} for {q['quantity_id']}"
                )
