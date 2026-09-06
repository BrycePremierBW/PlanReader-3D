"""tests/benchmarks/test_project_identity_matching.py — Test Project Identity Extraction & Mismatch Protection.

Tests the project identity matching gate to ensure mismatched projects are fail-closed
and never cross-compared.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from pb_benchmark_schema import ProjectIdentity, SourceManifest
from pb_project_identity import (
    evaluate_project_identity_match,
    extract_project_identity_from_pdf,
    extract_project_identity_from_workbook,
)

BENCHMARKS_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "plans"


def test_60_62_pdf_and_60_62_takeoff_allowed() -> None:
    """Prove that matching 60-62 School Rd PDF and 60-62 takeoff is confirmed and allowed."""
    p60_pdf = ProjectIdentity(
        project_name="60-62 School Rd Maroochydore - Proposed Townhouse Development",
        address="60-62 School Rd, Maroochydore QLD 4558",
        client="Balleo Pty Ltd",
        project_number="26-017",
        number_of_units=9,
        number_of_levels=2,
    )
    p60_takeoff = ProjectIdentity(
        project_name="60-62 School Rd Maroochydore - Proposed Townhouse Development",
        address="60-62 School Rd, Maroochydore QLD 4558",
        client="Balleo Pty Ltd",
        project_number="26-017",
        number_of_units=9,
        number_of_levels=2,
    )
    manifest = SourceManifest(
        benchmark_id="school_rd_60_62",
        project_name="60-62 School Rd Maroochydore",
        project_number="26-017",
        client="Balleo Pty Ltd",
        drawing_issue="BA Issue",
        drawing_date="09.06.2026",
        allowed_comparison_sources=["Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx"],
        rejected_comparison_sources=["Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx"],
    )

    allowed, reason, confidence = evaluate_project_identity_match(
        pdf_identity=p60_pdf,
        takeoff_identity=p60_takeoff,
        manifest=manifest,
        takeoff_filename="Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx",
    )
    assert allowed is True
    assert reason == "project_identity_confirmed"
    assert confidence >= 0.95


def test_60_62_pdf_and_92_94_takeoff_blocked() -> None:
    """Prove that 60-62 School Rd PDF and 92-94 takeoff is blocked with wrong_project_source_mismatch."""
    p60_pdf = ProjectIdentity(
        project_name="60-62 School Rd Maroochydore - Proposed Townhouse Development",
        address="60-62 School Rd, Maroochydore QLD 4558",
        client="Balleo Pty Ltd",
        project_number="26-017",
        number_of_units=9,
        number_of_levels=2,
    )
    p92_takeoff = ProjectIdentity(
        project_name="COX PROPERTY GROUP - ELISE",
        address="92-94 SCHOOL RD, MAROOCHYDORE, QLD, 4558",
        client="Cox Property Group",
        project_number="COX05",
        number_of_units=8,
        number_of_levels=2,
    )
    manifest = SourceManifest(
        benchmark_id="school_rd_60_62",
        project_name="60-62 School Rd Maroochydore",
        project_number="26-017",
        client="Balleo Pty Ltd",
        drawing_issue="BA Issue",
        drawing_date="09.06.2026",
        allowed_comparison_sources=["Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx"],
        rejected_comparison_sources=["Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx"],
    )

    allowed, reason, confidence = evaluate_project_identity_match(
        pdf_identity=p60_pdf,
        takeoff_identity=p92_takeoff,
        manifest=manifest,
        takeoff_filename="Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx",
    )
    assert allowed is False
    assert reason == "wrong_project_source_mismatch"


def test_lago_pdf_and_school_rd_takeoffs_blocked() -> None:
    """Prove that LAGO PDF blocks comparisons against both 60-62 and 92-94 School Rd takeoffs."""
    lago_pdf = ProjectIdentity(
        project_name="CUBE DEVELOPMENTS - LAGO DD",
        address="2 MANTRA ESP, BIRTINYA, QLD, 4575",
        client="Cube Developments",
        project_number="260617_004",
    )
    p60_takeoff = ProjectIdentity(
        project_name="60-62 School Rd Maroochydore - Proposed Townhouse Development",
        address="60-62 School Rd, Maroochydore QLD 4558",
        client="Balleo Pty Ltd",
        project_number="26-017",
    )
    p92_takeoff = ProjectIdentity(
        project_name="COX PROPERTY GROUP - ELISE",
        address="92-94 SCHOOL RD, MAROOCHYDORE, QLD, 4558",
        client="Cox Property Group",
        project_number="COX05",
    )
    lago_manifest = SourceManifest(
        benchmark_id="lago_britinya",
        project_name="CUBE DEVELOPMENTS - LAGO DD",
        project_number="260617_004",
        client="Cube Developments",
        drawing_issue="DD",
        drawing_date="17.08.2026",
        allowed_comparison_sources=[],
        rejected_comparison_sources=[
            "Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx",
            "Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx",
        ],
    )

    # 1. Blocked against 60-62
    allowed_60, reason_60, _ = evaluate_project_identity_match(
        pdf_identity=lago_pdf,
        takeoff_identity=p60_takeoff,
        manifest=lago_manifest,
        takeoff_filename="Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx",
    )
    assert allowed_60 is False
    assert reason_60 == "wrong_project_source_mismatch"

    # 2. Blocked against 92-94
    allowed_92, reason_92, _ = evaluate_project_identity_match(
        pdf_identity=lago_pdf,
        takeoff_identity=p92_takeoff,
        manifest=lago_manifest,
        takeoff_filename="Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx",
    )
    assert allowed_92 is False
    assert reason_92 == "wrong_project_source_mismatch"


def test_public_tender_king_st_blocks_mismatched_takeoffs() -> None:
    """Prove that 122-126 King St Buderim blocks private townhouse takeoff comparisons."""
    king_st_pdf = ProjectIdentity(
        project_name="122-126 King St, Buderim - Construction Issue 4 (G)",
        address="122-126 King St, Buderim QLD",
        client="Public Tender Client",
        project_number="23-060",
    )
    p60_takeoff = ProjectIdentity(
        project_name="60-62 School Rd Maroochydore",
        address="60-62 School Rd",
        client="Balleo",
        project_number="26-017",
    )
    allowed, reason, _ = evaluate_project_identity_match(
        pdf_identity=king_st_pdf,
        takeoff_identity=p60_takeoff,
        takeoff_filename="Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx",
    )
    assert allowed is False
    assert reason == "wrong_project_source_mismatch"


def test_unknown_project_identity_requires_manual_review() -> None:
    """Prove that unconfirmed/ambiguous project identity fails closed to manual_review_required."""
    unknown_pdf = ProjectIdentity(
        project_name="",
        address="",
        client="",
        project_number="",
    )
    takeoff = ProjectIdentity(
        project_name="Generic Job",
        address="100 Commercial Rd",
        client="Client",
        project_number="GEN-01",
    )
    allowed, reason, _ = evaluate_project_identity_match(
        pdf_identity=unknown_pdf,
        takeoff_identity=takeoff,
    )
    assert allowed is False
    assert reason == "manual_review_required"
