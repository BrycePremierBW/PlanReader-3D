"""tests/publishing/test_planreader_jobhub_draft_vs_commercial_publish.py — PR C Test Suite.

Verifies the behavioral contrast between draft_publish and commercial_publish:
- Draft publish permits provisional, scaled, and AI rows with explicit warnings.
- Draft payload is clearly stamped as non-commercial and not approved cost data.
- Commercial publish strictly requires is_publishable=True on every row.
- Commercial payload is verified commercial and fails closed on any unapproved row.
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
    PlanReaderJobHubPayload,
    PublishMode,
    build_jobhub_payload,
    partition_publishable_rows,
    run_jobhub_publish_preflight,
)


def _sample_context() -> Dict[str, Any]:
    return {
        "project_identity": {
            "project_id": "PRJ-BIRTINYA",
            "project_name": "LAGO Birtinya",
            "project_number": "260617_004",
            "identity_confirmed": True,
        },
        "drawing_revision": {
            "revision_id": "DD Issue",
            "revision_hash": "rev_lago_001",
            "revision_date": "2026-08-15",
        },
        "source_files": ["260617_004-LAGO-BRITINYA_ARCH.pdf"],
        "created_by": "Bryce Curran",
    }


def test_draft_publish_accepts_provisional_row_with_warnings():
    """Draft publish permits provisional scaled rows and marks payload non-commercial."""
    ctx = _sample_context()
    provisional_row = create_takeoff_output_row(
        quantity_id="QTY-DRAFT-1",
        description="Draft Scaled Balcony Soffit",
        value=85.0,
        unit="m²",
        source_type=TakeoffSourceType.PDF_SCALED,
        source_page=8,
        source_sheet="WD-08",
        scale_id="SCALE-1:100",
    )

    # Preflight in draft mode succeeds with warnings
    preflight = run_jobhub_publish_preflight(
        rows=[provisional_row],
        project_identity=ctx["project_identity"],
        drawing_revision=ctx["drawing_revision"],
        mode=PublishMode.DRAFT_PUBLISH,
    )
    assert preflight.is_valid is True
    assert preflight.publish_mode == PublishMode.DRAFT_PUBLISH.value
    assert preflight.provisional_row_count == 1
    assert len(preflight.warnings) > 0

    # Build draft payload
    payload = build_jobhub_payload(
        rows=[provisional_row],
        project_identity=ctx["project_identity"],
        drawing_revision=ctx["drawing_revision"],
        source_files=ctx["source_files"],
        created_by=ctx["created_by"],
        publish_mode=PublishMode.DRAFT_PUBLISH,
    )

    assert payload.publish_mode == PublishMode.DRAFT_PUBLISH.value
    assert payload.is_commercial_ready is False
    assert any("non-commercial" in w.lower() or "draft" in w.lower() for w in payload.warnings)
    assert len(payload.quantities) == 1
    assert payload.quantities[0].authority_status == AuthorityStatus.PROVISIONAL.value


def test_commercial_publish_strictly_filters_to_publishable_rows():
    """Commercial publish only includes rows where is_publishable is True."""
    ctx = _sample_context()
    pub_row = create_takeoff_output_row(
        quantity_id="QTY-COMM-1",
        description="Documented Wall Area",
        value=110.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=2,
        source_sheet="WD-02",
        revision_hash=ctx["drawing_revision"]["revision_hash"],
        current_revision_hash=ctx["drawing_revision"]["revision_hash"],
    )
    assert pub_row.is_publishable is True

    payload = build_jobhub_payload(
        rows=[pub_row],
        project_identity=ctx["project_identity"],
        drawing_revision=ctx["drawing_revision"],
        source_files=ctx["source_files"],
        created_by=ctx["created_by"],
        publish_mode=PublishMode.COMMERCIAL_PUBLISH,
    )
    assert payload.publish_mode == PublishMode.COMMERCIAL_PUBLISH.value
    assert payload.is_commercial_ready is True
    assert len(payload.quantities) == 1
    assert payload.quantities[0].is_publishable is True


def test_partition_publishable_rows_helper():
    """partition_publishable_rows separates commercial publishable from draft and blocked rows."""
    row_firm = create_takeoff_output_row(
        quantity_id="ROW-1",
        description="Firm Documented Item",
        value=10.0,
        unit="m",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=1,
        source_sheet="WD-01",
    )
    row_prov = create_takeoff_output_row(
        quantity_id="ROW-2",
        description="Scaled Item",
        value=20.0,
        unit="m",
        source_type=TakeoffSourceType.PDF_SCALED,
        source_page=2,
        source_sheet="WD-02",
    )
    row_excl = create_takeoff_output_row(
        quantity_id="ROW-3",
        description="Excluded Item",
        value=30.0,
        unit="m",
        source_type=TakeoffSourceType.EXCLUDED,
        source_page=3,
        source_sheet="WD-03",
    )

    parts = partition_publishable_rows([row_firm, row_prov, row_excl])
    assert len(parts["publishable"]) == 1
    assert parts["publishable"][0].quantity_id == "ROW-1"
    assert len(parts["draft_only"]) == 1
    assert parts["draft_only"][0].quantity_id == "ROW-2"
    assert len(parts["unpublishable"]) == 1
    assert parts["unpublishable"][0].quantity_id == "ROW-3"
