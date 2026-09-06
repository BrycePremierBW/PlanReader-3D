"""tests/geometry/test_takeoff_output_authority_metadata.py — PR B.4 Test Suite.

Verifies that no naked/bare numbers leave PlanReader:
Every takeoff row must carry authority metadata, source trace, confidence,
scale/dimension references, revision hash, blocking reasons, and warnings arrays.
"""
from __future__ import annotations

import math
import pytest
from typing import Any, Dict

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    create_takeoff_output_row,
    from_database_row,
    from_wall_takeoff,
)


def test_takeoff_output_row_has_all_required_metadata_fields():
    """Verify that every TakeoffOutputRow contains all 20 specified fields."""
    row = create_takeoff_output_row(
        quantity_id="QTY-METADATA-1",
        description="External Cladding - West Elevation",
        value=124.5,
        unit="m²",
        trade="cladding",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        authority_status=AuthorityStatus.FIRM,
        confidence=1.0,
        source_page=3,
        source_sheet="WD-03",
        geometry_ref="WALL-EXT-01",
        scale_id="SCALE-P3-1_100",
        dimension_text_id="DIM-12450",
        benchmark_status="exact_match",
        approved_by="Bryce Curran",
        approved_at="2026-09-07T00:00:00Z",
        revision_hash="rev_abc123",
    )

    d = row.to_dict()
    required_keys = [
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
    ]
    for key in required_keys:
        assert key in d, f"Missing required field in takeoff row: {key}"

    assert isinstance(row.warnings, list)
    assert isinstance(row.blocking_reasons, list)


def test_bare_quantity_without_authority_metadata_is_blocked():
    """A bare quantity lacking authority source, page, and sheet must be blocked."""
    row = create_takeoff_output_row(
        quantity_id="QTY-BARE-1",
        description="Naked Number Area",
        value=50.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=None,
        source_sheet=None,
    )
    assert row.is_publishable is False
    assert any("traceable" in r.lower() or "source" in r.lower() for r in row.blocking_reasons)


def test_figured_dimension_output_includes_source_type_and_dimension_trace():
    """Figured dimension output must carry source_type, dimension_text_id, and scale reference."""
    row = from_wall_takeoff(
        wall_id="WALL-FIG-101",
        description="Master Bedroom Wall",
        net_area_m2=18.4,
        source_page=2,
        source_sheet="WD-02",
        scale_id="SCALE-1:100",
        figured_dimension_mm=3800.0,
        dimension_text_id="DIM-3800-P2",
        trade="painting",
    )
    assert row.source_type == TakeoffSourceType.DOCUMENTED_DIMENSION.value
    assert row.dimension_text_id == "DIM-3800-P2"
    assert row.scale_id == "SCALE-1:100"
    assert row.geometry_ref == "WALL-FIG-101"
    assert row.is_publishable is True
    assert len(row.blocking_reasons) == 0


def test_schedule_extracted_quantity_includes_sheet_page_trace():
    """Schedule extracted quantity includes sheet and page trace."""
    row = create_takeoff_output_row(
        quantity_id="QTY-SCHED-TRACE",
        description="Glazed Sliding Door D04",
        value=6.0,
        unit="ea",
        trade="glazing",
        source_type=TakeoffSourceType.SCHEDULE_EXTRACTED,
        source_page=15,
        source_sheet="WD-15 Door Schedule",
        project_identity_confirmed=True,
    )
    assert row.source_page == 15
    assert row.source_sheet == "WD-15 Door Schedule"
    assert row.trade == "glazing"
    assert row.is_publishable is True


def test_non_finite_quantity_blocks():
    """NaN and infinite quantities must raise ValueError or fail closed to BLOCKED."""
    with pytest.raises(ValueError):
        create_takeoff_output_row(
            quantity_id="QTY-NAN",
            description="NaN Quantity",
            value=float("nan"),
            unit="m²",
        )

    with pytest.raises(ValueError):
        create_takeoff_output_row(
            quantity_id="QTY-INF",
            description="Infinite Quantity",
            value=float("inf"),
            unit="m²",
        )


def test_negative_quantity_blocks():
    """Negative quantities must raise ValueError or fail closed to BLOCKED."""
    with pytest.raises(ValueError):
        create_takeoff_output_row(
            quantity_id="QTY-NEG",
            description="Negative Quantity",
            value=-12.5,
            unit="m²",
        )


def test_zero_quantity_blocks_where_zero_is_invalid():
    """Zero quantity blocks when zero is commercially invalid for a physical wall or surface."""
    row = create_takeoff_output_row(
        quantity_id="QTY-ZERO",
        description="Living Room Wall (Zero Measured)",
        value=0.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=2,
        source_sheet="WD-02",
        allow_zero=False,
    )
    assert row.is_publishable is False
    assert any("zero" in r.lower() for r in row.blocking_reasons)


def test_every_output_carries_blocking_reasons_and_warnings_arrays():
    """Every takeoff row carries both blocking_reasons and warnings arrays, even if empty."""
    clean_row = create_takeoff_output_row(
        quantity_id="QTY-CLEAN",
        description="Clean Wall",
        value=20.0,
        unit="m²",
        source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
        source_page=1,
        source_sheet="WD-01",
    )
    assert isinstance(clean_row.warnings, list)
    assert isinstance(clean_row.blocking_reasons, list)
    assert clean_row.blocking_reasons == []

    warn_row = create_takeoff_output_row(
        quantity_id="QTY-WARN",
        description="Scaled Wall",
        value=20.0,
        unit="m²",
        source_type=TakeoffSourceType.PDF_SCALED,
        source_page=1,
        source_sheet="WD-01",
    )
    assert len(warn_row.warnings) > 0
    assert isinstance(warn_row.warnings, list)
    assert isinstance(warn_row.blocking_reasons, list)
