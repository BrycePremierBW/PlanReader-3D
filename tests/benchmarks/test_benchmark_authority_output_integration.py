"""tests/benchmarks/test_benchmark_authority_output_integration.py — PR B.4 Test Suite.

Verifies that benchmark reports and takeoff summaries cleanly separate publishable,
provisional, review-required, and blocked rows with complete authority metadata.
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    create_takeoff_output_row,
    partition_takeoff_rows,
    generate_takeoff_authority_summary,
)


def test_benchmark_report_separates_publishable_provisional_and_blocked_rows():
    """Benchmark output cleanly categorizes rows into publishable, provisional, and blocked groups."""
    rows = [
        # Publishable documented dimension
        create_takeoff_output_row(
            quantity_id="QTY-BENCH-1",
            description="External Cladding Gross Area",
            value=310.0,
            unit="m²",
            source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=1,
            source_sheet="WD-01",
            benchmark_status="exact_match",
        ),
        # Provisional scaled geometry
        create_takeoff_output_row(
            quantity_id="QTY-BENCH-2",
            description="Scaled Internal Partition",
            value=45.0,
            unit="m²",
            source_type=TakeoffSourceType.PDF_SCALED,
            source_page=2,
            source_sheet="WD-02",
            benchmark_status="provisional",
        ),
        # Blocked mismatched project schedule
        create_takeoff_output_row(
            quantity_id="QTY-BENCH-3",
            description="Mismatched Door Schedule Item",
            value=12.0,
            unit="ea",
            source_type=TakeoffSourceType.SCHEDULE_EXTRACTED,
            source_page=10,
            source_sheet="WD-10",
            project_identity_confirmed=False,
            benchmark_status="blocked",
        ),
        # Excluded scope
        create_takeoff_output_row(
            quantity_id="QTY-BENCH-4",
            description="Screed / Tiling (By Others)",
            value=60.0,
            unit="m²",
            source_type=TakeoffSourceType.EXCLUDED,
            source_page=3,
            source_sheet="WD-03",
        ),
    ]

    partitioned = partition_takeoff_rows(rows)
    assert len(partitioned["publishable"]) == 1
    assert partitioned["publishable"][0].quantity_id == "QTY-BENCH-1"

    assert len(partitioned["provisional"]) == 1
    assert partitioned["provisional"][0].quantity_id == "QTY-BENCH-2"

    assert len(partitioned["blocked"]) == 1
    assert partitioned["blocked"][0].quantity_id == "QTY-BENCH-3"

    assert len(partitioned["excluded"]) == 1
    assert partitioned["excluded"][0].quantity_id == "QTY-BENCH-4"

    summary = generate_takeoff_authority_summary(rows)
    assert summary["total_count"] == 4
    assert summary["publishable_count"] == 1
    assert summary["provisional_count"] == 1
    assert summary["blocked_count"] == 1
    assert summary["excluded_count"] == 1
    assert summary["commercial_readiness_pct"] == 25.0
