"""tests/benchmarks/test_boq_line_classifier.py — PR F.1 Test Suite.

Verifies classification of public tender BOQ line items into standardized categories:
- measurable_from_drawings
- schedule_extractable
- scope_allowance_only
- provisional_sum
- rate_only
- preliminaries
- not_architectural
- not_applicable_to_planreader
- unknown_requires_review

Verifies that preliminaries and provisional sums do not distort physical measurement
accuracy, and that measurable items demand drawing traces.
"""
from __future__ import annotations

import pytest
from pb_public_tender_benchmark import (
    BOQLineCategory,
    BOQLineItem,
    classify_boq_line,
    evaluate_boq_measurement_traceability,
)


def test_classify_measurable_architectural_items():
    """Physical walls, finishes, and plasterboard map to measurable_from_drawings."""
    cat1 = classify_boq_line("Internal 13mm plasterboard lining to timber framing, painted")
    assert cat1 == BOQLineCategory.MEASURABLE_FROM_DRAWINGS

    cat2 = classify_boq_line("External cement render with elastomeric acrylic paint finish")
    assert cat2 == BOQLineCategory.MEASURABLE_FROM_DRAWINGS

    cat3 = classify_boq_line("Ceramic floor tiles 300x300mm to wet areas on waterproof membrane")
    assert cat3 == BOQLineCategory.MEASURABLE_FROM_DRAWINGS


def test_classify_schedule_extractable_items():
    """Doors, windows, and scheduled fixtures map to schedule_extractable."""
    cat1 = classify_boq_line("Supply and install solid core timber door Type D01 as per Door Schedule")
    assert cat1 == BOQLineCategory.SCHEDULE_EXTRACTABLE

    cat2 = classify_boq_line("Aluminium sliding window W03 including hardware and flyscreens")
    assert cat2 == BOQLineCategory.SCHEDULE_EXTRACTABLE


def test_classify_preliminaries_and_site_overhead():
    """Preliminaries, site supervision, scaffold, insurances map to preliminaries."""
    cat1 = classify_boq_line("Contractor site establishment, temporary facilities, and hoardings")
    assert cat1 == BOQLineCategory.PRELIMINARIES

    cat2 = classify_boq_line("Scaffolding, access equipment, and heavy plant mobilisation")
    assert cat2 == BOQLineCategory.PRELIMINARIES

    cat3 = classify_boq_line("General supervision, insurances, and contractual overheads")
    assert cat3 == BOQLineCategory.PRELIMINARIES


def test_classify_provisional_sums_and_allowances():
    """Provisional sums and generic allowances map correctly."""
    cat1 = classify_boq_line("Provisional Sum (PS) for unforeseen ground excavation and rock removal")
    assert cat1 == BOQLineCategory.PROVISIONAL_SUM

    cat2 = classify_boq_line("Scope allowance for acoustic mastic sealant to partition perimeters")
    assert cat2 == BOQLineCategory.SCOPE_ALLOWANCE_ONLY


def test_classify_rate_only_items():
    """Rate-only items with no fixed quantity map to rate_only."""
    cat1 = classify_boq_line("Rate Only: Extra over for high-gloss enamel finish if directed", rate_only=True)
    assert cat1 == BOQLineCategory.RATE_ONLY


def test_classify_non_architectural_trades():
    """MEP, electrical, civil, and earthworks map to not_architectural."""
    cat1 = classify_boq_line("Supply and lay 100mm PVC sewer drainage pipe in trench")
    assert cat1 == BOQLineCategory.NOT_ARCHITECTURAL

    cat2 = classify_boq_line("Main switchboard installation and 3-phase electrical distribution")
    assert cat2 == BOQLineCategory.NOT_ARCHITECTURAL


def test_preliminaries_ignored_for_physical_measurement_accuracy():
    """Preliminaries must be marked as not measurable from drawings."""
    item = BOQLineItem(
        line_id="BOQ-01",
        description="General Site Preliminaries & Insurance",
        quantity=1.0,
        unit="item",
        category=BOQLineCategory.PRELIMINARIES,
    )
    assert item.is_measurable is False
    assert item.is_preliminary is True


def test_provisional_sums_marked_provisional():
    """Provisional sums are flagged as provisional and excluded from firm physical measurement."""
    item = BOQLineItem(
        line_id="BOQ-02",
        description="Provisional sum for specialized signage",
        quantity=1.0,
        unit="PS",
        category=BOQLineCategory.PROVISIONAL_SUM,
    )
    assert item.is_measurable is False
    assert item.is_provisional is True


def test_measurable_boq_rows_require_drawing_trace_and_missing_is_reported():
    """Measurable BOQ items require drawing sheet/page references; missing traces are reported."""
    items = [
        BOQLineItem(
            line_id="BOQ-101",
            description="External wall render",
            quantity=450.0,
            unit="m²",
            category=BOQLineCategory.MEASURABLE_FROM_DRAWINGS,
            drawing_sheet="A-101",
            drawing_page=3,
        ),
        BOQLineItem(
            line_id="BOQ-102",
            description="Internal plasterboard ceiling",
            quantity=280.0,
            unit="m²",
            category=BOQLineCategory.MEASURABLE_FROM_DRAWINGS,
            drawing_sheet=None,  # missing trace!
            drawing_page=None,
        ),
        BOQLineItem(
            line_id="BOQ-103",
            description="Site Preliminaries",
            quantity=1.0,
            unit="item",
            category=BOQLineCategory.PRELIMINARIES,
        ),
    ]

    report = evaluate_boq_measurement_traceability(items)
    assert report["total_items"] == 3
    assert report["measurable_items"] == 2
    assert report["traced_measurable_items"] == 1
    assert report["missing_trace_items_count"] == 1
    assert len(report["missing_trace_line_ids"]) == 1
    assert report["missing_trace_line_ids"][0] == "BOQ-102"
