"""tests/geometry/test_takeoff_publishability_flags.py — PR B.4 Test Suite.

Verifies publishability gating rules across all takeoff output source types:
- Scaled-only geometry is provisional / draft only
- AI-detected is provisional / draft only
- User-corrected is review_required until approved
- User-approved is publishable if current, non-stale, and valid
- Excluded is never publishable
- Reference-only is never publishable
- Stale revision blocks publication
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    create_takeoff_output_row,
    approve_takeoff_output_row,
)


def test_scaled_only_geometry_is_provisional_not_publishable():
    """Scaled-only geometry output is provisional and not commercially publishable."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-SCALE",
        description="Scaled Internal Partition",
        value=42.0,
        unit="m²",
        source_type=TakeoffSourceType.PDF_SCALED,
        source_page=3,
        source_sheet="WD-03",
        scale_id="SCALE-1:100",
    )
    assert row.authority_status == AuthorityStatus.PROVISIONAL.value
    assert row.is_publishable is False
    assert any("provisional" in w.lower() or "scaled" in w.lower() for w in row.warnings)


def test_ai_detected_row_is_provisional_not_publishable():
    """AI-detected row is provisional and not commercially publishable."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-AI",
        description="AI Inferred Skirting",
        value=85.0,
        unit="m",
        source_type=TakeoffSourceType.AI_DETECTED,
        source_page=4,
        source_sheet="WD-04",
        confidence=0.65,
    )
    assert row.authority_status == AuthorityStatus.PROVISIONAL.value
    assert row.is_publishable is False
    assert any("ai" in w.lower() or "provisional" in w.lower() for w in row.warnings)


def test_user_corrected_but_unapproved_row_is_not_publishable():
    """User-corrected but unapproved row is review_required and not publishable."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-CORR",
        description="Manual Estimator Area Correction",
        value=33.0,
        unit="m²",
        source_type=TakeoffSourceType.USER_CORRECTED,
        source_page=2,
        source_sheet="WD-02",
    )
    assert row.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
    assert row.is_publishable is False
    assert any("approval" in r.lower() or "review" in r.lower() for r in row.blocking_reasons)


def test_user_approved_row_can_become_publishable():
    """User-approved row can become publishable when attributed and valid."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-APP",
        description="Approved Plasterboard Scope",
        value=150.0,
        unit="m²",
        source_type=TakeoffSourceType.USER_APPROVED,
        source_page=5,
        source_sheet="WD-05",
        approved_by="Estimator Bryce",
        approved_at="2026-09-07T01:00:00Z",
    )
    assert row.authority_status in ("user_approved", AuthorityStatus.FIRM.value)
    assert row.is_publishable is True
    assert row.approved_by == "Estimator Bryce"
    assert len(row.blocking_reasons) == 0


def test_excluded_row_is_never_publishable():
    """Excluded row is never publishable."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-EXCL",
        description="Internal Doors By Builder",
        value=18.0,
        unit="ea",
        source_type=TakeoffSourceType.EXCLUDED,
        source_page=9,
        source_sheet="WD-09",
    )
    assert row.authority_status == AuthorityStatus.EXCLUDED.value
    assert row.is_publishable is False
    assert any("excluded" in r.lower() for r in row.blocking_reasons)


def test_reference_only_row_is_never_publishable():
    """Reference-only row is never publishable."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-REF",
        description="Total Site Area Footprint",
        value=800.0,
        unit="m²",
        source_type=TakeoffSourceType.REFERENCE_ONLY,
        source_page=1,
        source_sheet="WD-01",
    )
    assert row.authority_status == AuthorityStatus.REFERENCE_ONLY.value
    assert row.is_publishable is False
    assert any("reference" in r.lower() for r in row.blocking_reasons)


def test_stale_revision_blocks_publication():
    """A quantity measured against an older superseded drawing revision blocks publication."""
    row = create_takeoff_output_row(
        quantity_id="QTY-PUB-STALE",
        description="Bedroom 2 Wall Area",
        value=24.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=3,
        source_sheet="WD-03",
        revision_hash="rev_issue_1",
        current_revision_hash="rev_issue_2",
    )
    assert row.is_publishable is False
    assert any("stale" in r.lower() or "superseded" in r.lower() or "revision" in r.lower() for r in row.blocking_reasons)


def test_approval_workflow_transitions_unapproved_to_publishable():
    """Approving a provisional model row transitions it to publishable user_approved."""
    draft = create_takeoff_output_row(
        quantity_id="QTY-PUB-WORKFLOW",
        description="3D Parapet Wall Area",
        value=52.0,
        unit="m²",
        source_type=TakeoffSourceType.MODEL_DERIVED,
        source_page=10,
        source_sheet="WD-10",
    )
    assert draft.is_publishable is False

    approved = approve_takeoff_output_row(
        draft,
        approved_by="Lead Estimator Bryce",
        approved_at="2026-09-07T01:15:00Z",
    )
    assert approved.is_publishable is True
    assert approved.authority_status == "user_approved"
    assert approved.approved_by == "Lead Estimator Bryce"
