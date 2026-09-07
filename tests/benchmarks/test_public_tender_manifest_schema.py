"""tests/benchmarks/test_public_tender_manifest_schema.py — PR F.1 Test Suite.

Verifies that public tender benchmark manifests conform to standardized schema:
- Top-level manifest.json index is valid
- Every candidate benchmark has source_manifest, download_manifest, expected_project,
  expected_boq_summary, and benchmark_rules.
- Every download_manifest has source_url, tender_reference, publisher, and document roles.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

BENCHMARKS_DIR = Path("benchmarks/public_tenders")


def test_top_level_public_tender_manifest_validates():
    """Verify top-level benchmarks/public_tenders/manifest.json exists and is valid."""
    manifest_path = BENCHMARKS_DIR / "manifest.json"
    assert manifest_path.exists(), f"Missing top-level manifest: {manifest_path}"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "benchmarks" in data
    assert isinstance(data["benchmarks"], list)
    assert len(data["benchmarks"]) >= 5, "Must contain at least 5 public tender benchmarks"

    for b in data["benchmarks"]:
        assert "benchmark_id" in b
        assert "project_name" in b
        assert "organization" in b
        assert "source_url" in b
        assert "status" in b


def test_every_public_benchmark_directory_has_complete_manifest_suite():
    """Each benchmark directory must contain the 5 required JSON manifests."""
    manifest_path = BENCHMARKS_DIR / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    required_files = [
        "source_manifest.json",
        "download_manifest.json",
        "expected_project.json",
        "expected_boq_summary.json",
        "benchmark_rules.json",
    ]

    for b in data["benchmarks"]:
        b_id = b["benchmark_id"]
        b_dir = BENCHMARKS_DIR / b_id
        assert b_dir.exists() and b_dir.is_dir(), f"Benchmark directory missing: {b_dir}"

        for req_file in required_files:
            file_path = b_dir / req_file
            assert file_path.exists(), f"Missing {req_file} in {b_dir}"
            content = json.loads(file_path.read_text(encoding="utf-8"))
            assert isinstance(content, dict), f"{file_path} must be a JSON object"


def test_download_manifest_contains_source_url_and_document_roles():
    """Every download_manifest.json must have source URL, publisher, and document roles."""
    manifest_path = BENCHMARKS_DIR / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    for b in data["benchmarks"]:
        b_id = b["benchmark_id"]
        dl_path = BENCHMARKS_DIR / b_id / "download_manifest.json"
        dl = json.loads(dl_path.read_text(encoding="utf-8"))

        assert "source_url" in dl and dl["source_url"].startswith("http"), f"Invalid source_url in {dl_path}"
        assert "tender_reference" in dl, f"Missing tender_reference in {dl_path}"
        assert "publisher" in dl, f"Missing publisher in {dl_path}"
        assert "documents" in dl and isinstance(dl["documents"], list), f"Missing documents in {dl_path}"

        # Check document roles
        roles = [doc.get("role") for doc in dl["documents"]]
        assert any(r in ("architectural_drawings", "drawings", "tender_drawings") for r in roles), (
            f"{dl_path} must define architectural drawings role"
        )
        assert any(r in ("boq", "bill_of_quantities", "takeoff_schedule") for r in roles), (
            f"{dl_path} must define BOQ role"
        )


def test_expected_boq_summary_has_classification_totals():
    """Every expected_boq_summary.json must contain total lines and classified categories."""
    manifest_path = BENCHMARKS_DIR / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    for b in data["benchmarks"]:
        b_id = b["benchmark_id"]
        boq_path = BENCHMARKS_DIR / b_id / "expected_boq_summary.json"
        boq = json.loads(boq_path.read_text(encoding="utf-8"))

        assert "total_line_items" in boq
        assert "measurable_items_count" in boq
        assert "classified_breakdown" in boq
        assert isinstance(boq["classified_breakdown"], dict)
