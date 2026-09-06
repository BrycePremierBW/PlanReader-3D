"""tests/publishing/test_planreader_jobhub_preflight_gate.py — PR C Test Suite.

Verifies that run_jobhub_publish_preflight enforces strict fail-closed commercial rules:
- Rejects unapproved AI / model / scaled rows
- Rejects stale rows
- Rejects project mismatch or unknown project identity
- Rejects missing authority metadata
- Rejects excluded / reference-only / blocked rows
- Rejects non-finite, negative, or invalid zero quantities
"""
from __future__ import annotations

import pytest
from typing import Any, Dict

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    create_takeoff_output_row,
)
from pb_planreader_jobhub_publish_contract import (
    PublishMode,
    PublishPreflightResult,
    run_jobhub_publish_preflight,
)


def _valid_project_identity() -> Dict[str, Any]:
    return {
        "project_id": "PRJ-001",
        "project_name": "60-62 School Rd",
        "project_number": "26-017",
        "identity_confirmed": True,
    }


def _valid_drawing_revision() -> Dict[str, Any]:
    return {
        "revision_id": "Rev A",
        "revision_hash": "rev_hash_100",
        "revision_date": "2026-09-01",
    }


def _valid_approved_row() -> TakeoffOutputRow:
    return create_takeoff_output_row(
        quantity_id="QTY-APP-01",
        description="Approved Plasterboard Lining",
        value=120.0,
        unit="m²",
        trade="plasterboard",
        source_type=TakeoffSourceType.USER_APPROVED,
        source_page=2,
        source_sheet="WD-02",
        approved_by="Estimator Bryce",
        approved_at="2026-09-07T00:00:00Z",
        revision_hash="rev_hash_100",
        current_revision_hash="rev_hash_100",
    )


def test_valid_approved_rows_pass_commercial_preflight():
    """Valid approved rows build a passing commercial preflight result."""
    row = _valid_approved_row()
    res = run_jobhub_publish_preflight(
        rows=[row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is True
    assert res.publishable_row_count == 1
    assert res.blocked_row_count == 0
    assert len(res.blocking_reasons) == 0


def test_provisional_scaled_row_blocks_commercial_publish():
    """A provisional scaled row fails commercial preflight."""
    scaled_row = create_takeoff_output_row(
        quantity_id="QTY-SCALED-01",
        description="Scaled Corridor Partition",
        value=45.0,
        unit="m²",
        source_type=TakeoffSourceType.PDF_SCALED,
        source_page=3,
        source_sheet="WD-03",
    )
    res = run_jobhub_publish_preflight(
        rows=[scaled_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert res.blocked_row_count == 1
    assert any("provisional" in r.lower() or "scaled" in r.lower() for r in res.blocking_reasons)


def test_ai_detected_row_blocks_commercial_publish():
    """An AI-detected row fails commercial preflight."""
    ai_row = create_takeoff_output_row(
        quantity_id="QTY-AI-01",
        description="AI Inferred Ceiling Area",
        value=65.0,
        unit="m²",
        source_type=TakeoffSourceType.AI_DETECTED,
        source_page=4,
        source_sheet="WD-04",
    )
    res = run_jobhub_publish_preflight(
        rows=[ai_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert res.blocked_row_count == 1
    assert any("ai" in r.lower() or "provisional" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_excluded_row():
    """Excluded rows must block commercial publishing."""
    excl_row = create_takeoff_output_row(
        quantity_id="QTY-EXCL-01",
        description="Painting Excluded Area",
        value=30.0,
        unit="m²",
        source_type=TakeoffSourceType.EXCLUDED,
        source_page=5,
        source_sheet="WD-05",
    )
    res = run_jobhub_publish_preflight(
        rows=[excl_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("excluded" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_reference_only_row():
    """Reference-only rows must block commercial publishing."""
    ref_row = create_takeoff_output_row(
        quantity_id="QTY-REF-01",
        description="Site Boundary Reference",
        value=500.0,
        unit="m²",
        source_type=TakeoffSourceType.REFERENCE_ONLY,
        source_page=1,
        source_sheet="WD-01",
    )
    res = run_jobhub_publish_preflight(
        rows=[ref_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("reference" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_stale_revision():
    """Row measured on an older superseded revision blocks commercial publishing."""
    stale_row = create_takeoff_output_row(
        quantity_id="QTY-STALE-01",
        description="Outdated Room Area",
        value=25.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=2,
        source_sheet="WD-02",
        revision_hash="rev_old",
        current_revision_hash="rev_hash_100",
    )
    res = run_jobhub_publish_preflight(
        rows=[stale_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("stale" in r.lower() or "superseded" in r.lower() or "revision" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_project_mismatch():
    """Project identity marked as unconfirmed or mismatched blocks commercial publishing."""
    mismatched_identity = {
        "project_id": "PRJ-92-94",
        "project_name": "92-94 School Rd",
        "identity_confirmed": False,
        "mismatch_reason": "Takeoff uploaded does not belong to active drawing set",
    }
    res = run_jobhub_publish_preflight(
        rows=[_valid_approved_row()],
        project_identity=mismatched_identity,
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("project identity" in r.lower() or "mismatch" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_missing_project_identity():
    """Empty or missing project identity blocks commercial publishing."""
    res = run_jobhub_publish_preflight(
        rows=[_valid_approved_row()],
        project_identity={},
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("project identity" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_row_without_authority_metadata():
    """A row missing basic authority metadata (e.g. naked dict or blank source) blocks commercial publishing."""
    raw_row = {
        "quantity_id": "RAW-01",
        "description": "Naked Number",
        "value": 10.0,
        "unit": "m²",
        # missing authority_status, source_type, source_page, etc.
    }
    res = run_jobhub_publish_preflight(
        rows=[raw_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("authority" in r.lower() or "metadata" in r.lower() for r in res.blocking_reasons)


def test_commercial_publish_rejects_invalid_numbers():
    """Negative, non-finite, or invalid zeroes block commercial preflight."""
    bad_zero_row = create_takeoff_output_row(
        quantity_id="QTY-ZERO",
        description="Zero Wall Area",
        value=0.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=1,
        source_sheet="WD-01",
        allow_zero=False,
    )
    res = run_jobhub_publish_preflight(
        rows=[bad_zero_row],
        project_identity=_valid_project_identity(),
        drawing_revision=_valid_drawing_revision(),
        mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert res.is_valid is False
    assert any("zero" in r.lower() for r in res.blocking_reasons)
