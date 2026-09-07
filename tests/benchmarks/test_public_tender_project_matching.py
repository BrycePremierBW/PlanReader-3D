"""tests/benchmarks/test_public_tender_project_matching.py — PR F.1 Test Suite.

Verifies project matching and mismatch rejection rules for public tenders:
- Matching drawings and BOQ comparison is permitted.
- Unrelated BOQ comparison is blocked with 'wrong_project_source_mismatch'.
- Cross-project tender takeoffs are rejected outright.
"""
from __future__ import annotations

import pytest
from pb_public_tender_benchmark import (
    compare_tender_drawings_and_boq,
    PublicTenderBenchmark,
)


def test_matching_tender_drawings_and_boq_comparison_is_allowed():
    """Matching drawings and BOQ from the same tender must be allowed for comparison."""
    drawings_meta = {
        "project_name": "UNOPS WECC Torit Vocational Training Centre",
        "tender_reference": "ITB/2023/45890",
        "organization": "UNOPS",
    }
    boq_meta = {
        "project_name": "UNOPS WECC Torit Vocational Training Centre",
        "tender_reference": "ITB/2023/45890",
        "organization": "UNOPS",
    }
    allowed, reason = compare_tender_drawings_and_boq(drawings_meta, boq_meta)
    assert allowed is True
    assert reason == "project_identity_confirmed"


def test_unrelated_boq_comparison_is_blocked_with_source_mismatch():
    """Drawings with an unrelated or foreign BOQ must return wrong_project_source_mismatch."""
    drawings_meta = {
        "project_name": "UNOPS WECC Torit Vocational Training Centre",
        "tender_reference": "ITB/2023/45890",
        "organization": "UNOPS",
    }
    unrelated_boq_meta = {
        "project_name": "Al Qayarah General Hospital Renovation",
        "tender_reference": "RFP/2024/78912",
        "organization": "UNDP / UNGM",
    }
    allowed, reason = compare_tender_drawings_and_boq(drawings_meta, unrelated_boq_meta)
    assert allowed is False
    assert reason == "wrong_project_source_mismatch"


def test_cross_tender_private_to_public_comparison_is_blocked():
    """A private residential takeoff compared against a public UNGM tender drawing set is blocked."""
    drawings_meta = {
        "project_name": "UNGM Category IV Housing Units",
        "tender_reference": "ITB/2023/CAT4-H",
        "organization": "UN-Habitat",
    }
    private_takeoff_meta = {
        "project_name": "60-62 School Rd Maroochydore - Proposed Townhouse Development",
        "project_number": "26-017",
        "client": "Balleo Pty Ltd",
    }
    allowed, reason = compare_tender_drawings_and_boq(drawings_meta, private_takeoff_meta)
    assert allowed is False
    assert reason == "wrong_project_source_mismatch"


def test_public_tender_benchmark_class_matching_guard():
    """PublicTenderBenchmark rejects comparison if candidate file is in rejected_sources."""
    bench = PublicTenderBenchmark.load("ungm_unops_wecc_torit")
    is_allowed, reason = bench.validate_source_files(
        drawings_filename="WECC-Torit-Arch-Drawings.pdf",
        boq_filename="Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx",
    )
    assert is_allowed is False
    assert reason == "wrong_project_source_mismatch"
