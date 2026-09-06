"""tests/publishing/test_planreader_jobhub_payload_contract.py — PR C Test Suite.

Verifies the PlanReader -> JobHub payload contract:
Every payload must carry complete project identity, drawing revision, benchmark status,
authority summary, quantities with per-row fingerprints, excluded items, warnings,
blocking reasons, source files, creator attribution, publish mode, and payload fingerprint.
"""
from __future__ import annotations

import json
import pytest
from typing import Any, Dict

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    create_takeoff_output_row,
)
from pb_planreader_jobhub_publish_contract import (
    PlanReaderJobHubPayload,
    PlanReaderJobHubQuantityRow,
    PublishMode,
    build_jobhub_payload,
    compute_payload_fingerprint,
)


def _sample_valid_takeoff_row() -> TakeoffOutputRow:
    return create_takeoff_output_row(
        quantity_id="QTY-W01",
        description="External Cladding - West Elevation",
        value=150.0,
        unit="m²",
        trade="cladding",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        authority_status=AuthorityStatus.FIRM,
        confidence=1.0,
        source_page=3,
        source_sheet="WD-03",
        geometry_ref="WALL-01",
        scale_id="SCALE-1:100",
        dimension_text_id="DIM-15000",
        benchmark_status="exact_match",
        approved_by="Bryce Curran",
        approved_at="2026-09-07T00:00:00Z",
        revision_hash="rev_clean_123",
        current_revision_hash="rev_clean_123",
    )


def test_payload_has_all_required_contract_fields():
    """Verify that PlanReaderJobHubPayload contains all 13 specified top-level fields."""
    row = _sample_valid_takeoff_row()
    project_identity = {
        "project_id": "PRJ-60-62",
        "project_name": "60-62 School Rd",
        "project_number": "26-017",
        "identity_confirmed": True,
    }
    drawing_revision = {
        "revision_id": "BA Issue 1",
        "revision_hash": "rev_clean_123",
        "revision_date": "2026-06-09",
    }
    source_files = [
        "26-017 - 60-62 School Rd Maroochydore - BA Issue (1) - 09.06.26.pdf"
    ]

    payload = build_jobhub_payload(
        rows=[row],
        project_identity=project_identity,
        drawing_revision=drawing_revision,
        source_files=source_files,
        created_by="Bryce Curran",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
        benchmark_status={"benchmark_id": "school_rd_60_62", "accuracy_score": 0.9},
    )

    d = payload.to_dict()
    required_top_level = [
        "project_identity",
        "drawing_revision",
        "benchmark_status",
        "authority_summary",
        "quantities",
        "excluded_items",
        "warnings",
        "blocking_reasons",
        "source_files",
        "created_at",
        "created_by",
        "publish_mode",
        "payload_fingerprint",
    ]
    for field in required_top_level:
        assert field in d, f"Missing required payload field: {field}"

    assert payload.publish_mode == PublishMode.COMMERCIAL_PUBLISH.value
    assert payload.created_by == "Bryce Curran"
    assert len(payload.source_files) == 1
    assert payload.source_files[0] == "26-017 - 60-62 School Rd Maroochydore - BA Issue (1) - 09.06.26.pdf"
    assert payload.benchmark_status["benchmark_id"] == "school_rd_60_62"


def test_each_quantity_row_has_all_21_fields_including_fingerprint():
    """Verify that PlanReaderJobHubQuantityRow carries all 20 authority fields plus fingerprint."""
    row = _sample_valid_takeoff_row()
    jobhub_row = PlanReaderJobHubQuantityRow.from_takeoff_output_row(row)
    d = jobhub_row.to_dict()

    expected_fields = [
        "quantity_id",
        "description",
        "value",
        "unit",
        "trade",
        "source_type",
        "authority_status",
        "confidence",
        "source_page",
        "source_sheet",
        "geometry_ref",
        "scale_id",
        "dimension_text_id",
        "benchmark_status",
        "is_publishable",
        "warnings",
        "blocking_reasons",
        "approved_by",
        "approved_at",
        "revision_hash",
        "fingerprint",
    ]
    for field in expected_fields:
        assert field in d, f"Missing required quantity row field: {field}"

    assert jobhub_row.quantity_id == "QTY-W01"
    assert jobhub_row.value == 150.0
    assert jobhub_row.unit == "m²"
    assert jobhub_row.is_publishable is True
    assert len(jobhub_row.fingerprint) == 64  # SHA-256 hex


def test_payload_authority_summary_structure():
    """Verify that authority_summary cleanly reports readiness and counts."""
    row = _sample_valid_takeoff_row()
    payload = build_jobhub_payload(
        rows=[row],
        project_identity={"project_id": "P1", "identity_confirmed": True},
        drawing_revision={"revision_hash": "rev_clean_123"},
        source_files=["plan.pdf"],
        created_by="Estimator",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    summary = payload.authority_summary
    assert "total_count" in summary
    assert "publishable_count" in summary
    assert "provisional_count" in summary
    assert "blocked_count" in summary
    assert "commercial_readiness_pct" in summary
    assert summary["publishable_count"] == 1
    assert summary["commercial_readiness_pct"] == 100.0


def test_payload_fingerprint_deterministic_and_tamper_evident():
    """Verify payload fingerprint is deterministic and detects any quantity or metadata tampering."""
    row1 = _sample_valid_takeoff_row()
    payload1 = build_jobhub_payload(
        rows=[row1],
        project_identity={"project_id": "P1", "identity_confirmed": True},
        drawing_revision={"revision_hash": "rev_clean_123"},
        source_files=["plan.pdf"],
        created_by="Estimator",
        created_at="2026-09-07T01:00:00Z",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )

    # Identical payload produces same fingerprint
    payload2 = build_jobhub_payload(
        rows=[row1],
        project_identity={"project_id": "P1", "identity_confirmed": True},
        drawing_revision={"revision_hash": "rev_clean_123"},
        source_files=["plan.pdf"],
        created_by="Estimator",
        created_at="2026-09-07T01:00:00Z",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert payload1.payload_fingerprint == payload2.payload_fingerprint

    # Tampered quantity value mutates fingerprint
    tampered_row = create_takeoff_output_row(
        quantity_id="QTY-W01",
        description="External Cladding - West Elevation",
        value=155.0,  # mutated
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=3,
        source_sheet="WD-03",
        dimension_text_id="DIM-15000",
        approved_by="Bryce Curran",
        approved_at="2026-09-07T00:00:00Z",
        revision_hash="rev_clean_123",
        current_revision_hash="rev_clean_123",
    )
    payload_tampered = build_jobhub_payload(
        rows=[tampered_row],
        project_identity={"project_id": "P1", "identity_confirmed": True},
        drawing_revision={"revision_hash": "rev_clean_123"},
        source_files=["plan.pdf"],
        created_by="Estimator",
        created_at="2026-09-07T01:00:00Z",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert payload1.payload_fingerprint != payload_tampered.payload_fingerprint


def test_payload_serialization_roundtrip():
    """Verify payload serialization to dict and JSON round-trip."""
    row = _sample_valid_takeoff_row()
    payload = build_jobhub_payload(
        rows=[row],
        project_identity={"project_id": "P1", "identity_confirmed": True},
        drawing_revision={"revision_hash": "rev_clean_123"},
        source_files=["plan.pdf"],
        created_by="Estimator",
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    d = payload.to_dict()
    json_str = json.dumps(d)
    restored_dict = json.loads(json_str)
    restored = PlanReaderJobHubPayload.from_dict(restored_dict)

    assert restored.payload_fingerprint == payload.payload_fingerprint
    assert len(restored.quantities) == 1
    assert restored.quantities[0].quantity_id == "QTY-W01"
    assert restored.quantities[0].fingerprint == payload.quantities[0].fingerprint
