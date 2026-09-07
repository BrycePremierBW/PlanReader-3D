"""tests/benchmarks/test_mutation_raster_cad_schedules.py

Phase F.8 Mutation Tests: Generic Raster, CAD, and Vector Schedule Extraction.

Verifies:
1. Synthetic schedule with different counts/dimensions produces those exact new values.
2. Removing a schedule row removes that prediction (emits missed item).
3. Changing one row changes only that prediction, leaving others isolated.
4. OCR noise and keyword soup do not silently create exact benchmark-shaped outputs.
5. All outputs include source page and valid bounding box evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import List
import fitz
import pytest

from pb_raster_schedule_extractor import GenericScheduleTableExtractor, ScheduleRow
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _create_mock_schedule_pdf(
    tmp_path: Path,
    filename: str,
    table_rows: List[List[str]],
    callout_text: str = "",
) -> Path:
    """Create a mock drawing PDF with a structured schedule table and optional callouts."""
    pdf_path = tmp_path / filename
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 Landscape

    # Drawing header
    page.insert_text((50, 40), "PROPOSED COMMERCIAL DEVELOPMENT", fontsize=12)
    page.insert_text((50, 60), "DRAWING TITLE: WINDOW & DOOR SCHEDULE", fontsize=10)
    page.insert_text((50, 75), "SCALE 1:50", fontsize=9)
    page.insert_text((50, 90), "DRAWING NO: ARC-SCH-01", fontsize=9)

    # Draw table grid and text
    y_start = 120
    row_height = 25
    col_widths = [80, 140, 90, 200]
    col_xs = [50]
    for w in col_widths:
        col_xs.append(col_xs[-1] + w)

    for r_idx, row in enumerate(table_rows):
        y = y_start + r_idx * row_height
        # Horizontal line
        page.draw_line(fitz.Point(col_xs[0], y), fitz.Point(col_xs[-1], y))
        for c_idx, cell in enumerate(row):
            x = col_xs[c_idx]
            # Vertical line
            page.draw_line(fitz.Point(x, y), fitz.Point(x, y + row_height))
            page.insert_text((x + 6, y + 17), cell, fontsize=9)
        # End vertical line
        page.draw_line(fitz.Point(col_xs[-1], y), fitz.Point(col_xs[-1], y + row_height))
    # Bottom line
    y_bottom = y_start + len(table_rows) * row_height
    page.draw_line(fitz.Point(col_xs[0], y_bottom), fitz.Point(col_xs[-1], y_bottom))

    # Optional extra callout text
    if callout_text:
        page.insert_text((50, y_bottom + 30), callout_text, fontsize=9)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_mutation_1_synthetic_schedule_produces_exact_new_values(tmp_path: Path) -> None:
    """Proves that a synthetic schedule with novel dimensions and counts produces those exact new values."""
    extractor = GenericScheduleTableExtractor()

    # Synthetic schedule with completely novel dimensions and counts
    table = [
        ["Mark", "Dimensions", "Quantity", "Description"],
        ["W1", "1750 x 1350 mm", "7 No.", "Aluminum top-hung window"],
        ["W2", "1150 x 850 mm", "4 No.", "Steel casement window"],
        ["D1", "850 x 2050 mm", "3 No.", "Semi-solid flush door"],
    ]
    callouts = (
        "TRUSS T2 (11 No.)\n"
        "PV  PV  PV  PV  PV\n"
        "6 No. 75mm dia CHS pillars\n"
        "8 No. 400x400 masonry piers\n"
    )

    pdf = _create_mock_schedule_pdf(tmp_path, "synth_sched_1.pdf", table, callouts)
    doc = fitz.open(str(pdf))
    rows = {r.tag: r for r in extractor.extract_from_document(doc)}

    # Window W1: exactly 7 No., dims [1750, 1350]
    assert "W1" in rows
    assert rows["W1"].quantity == 7.0
    assert rows["W1"].dimensions == [1750.0, 1350.0]
    assert rows["W1"].trade_type == "windows"
    assert rows["W1"].source_page == 1
    assert rows["W1"].bbox[2] > rows["W1"].bbox[0]  # Valid bounding box

    # Window W2: exactly 4 No., dims [1150, 850]
    assert "W2" in rows
    assert rows["W2"].quantity == 4.0
    assert rows["W2"].dimensions == [1150.0, 850.0]
    assert rows["W2"].trade_type == "windows"

    # Door D1: exactly 3 No., dims [850, 2050]
    assert "D1" in rows
    assert rows["D1"].quantity == 3.0
    assert rows["D1"].dimensions == [850.0, 2050.0]
    assert rows["D1"].trade_type == "doors"

    # Callouts: Trusses = 11.0, Pillars = 6.0, Piers = 8.0, Vents = 5.0
    assert rows["roof_trusses"].quantity == 11.0
    assert rows["verandah_pillars"].quantity == 6.0
    assert rows["masonry_piers"].quantity == 8.0
    assert rows["brick_vents"].quantity == 5.0


def test_mutation_2_removing_schedule_row_removes_prediction(tmp_path: Path) -> None:
    """Proves that removing a row from the schedule removes that prediction (no hallucination/guess)."""
    extractor = GenericScheduleTableExtractor()

    # Table with W2 removed
    table_without_w2 = [
        ["Mark", "Dimensions", "Quantity", "Description"],
        ["W1", "1750 x 1350 mm", "7 No.", "Aluminum top-hung window"],
        ["D1", "850 x 2050 mm", "3 No.", "Semi-solid flush door"],
    ]

    pdf = _create_mock_schedule_pdf(tmp_path, "synth_sched_no_w2.pdf", table_without_w2)
    doc = fitz.open(str(pdf))
    rows = {r.tag: r for r in extractor.extract_from_document(doc)}

    # W1 and D1 must remain
    assert "W1" in rows
    assert rows["W1"].quantity == 7.0
    assert "D1" in rows
    assert rows["D1"].quantity == 3.0

    # W2 must be completely absent
    assert "W2" not in rows


def test_mutation_3_changing_one_row_changes_only_that_prediction(tmp_path: Path) -> None:
    """Proves that mutating one row's quantity and dimension affects only that prediction."""
    extractor = GenericScheduleTableExtractor()

    # Mutated table: change W1 to 2400 x 1800 with 15 No.
    mutated_table = [
        ["Mark", "Dimensions", "Quantity", "Description"],
        ["W1", "2400 x 1800 mm", "15 No.", "Large curtain wall window"],
        ["W2", "1150 x 850 mm", "4 No.", "Steel casement window"],
        ["D1", "850 x 2050 mm", "3 No.", "Semi-solid flush door"],
    ]

    pdf = _create_mock_schedule_pdf(tmp_path, "synth_sched_mutated.pdf", mutated_table)
    doc = fitz.open(str(pdf))
    rows = {r.tag: r for r in extractor.extract_from_document(doc)}

    # W1 is mutated
    assert rows["W1"].quantity == 15.0
    assert rows["W1"].dimensions == [2400.0, 1800.0]

    # W2 and D1 are strictly unchanged
    assert rows["W2"].quantity == 4.0
    assert rows["W2"].dimensions == [1150.0, 850.0]
    assert rows["D1"].quantity == 3.0
    assert rows["D1"].dimensions == [850.0, 2050.0]


def test_mutation_4_ocr_noise_does_not_create_benchmark_shaped_outputs(tmp_path: Path) -> None:
    """Proves that unstructured text noise and benchmark keywords without tables never emit benchmark quantities."""
    extractor = GenericScheduleTableExtractor()

    noise_pdf_path = tmp_path / "noise.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)

    # Garbage noise mixing benchmark numbers and schedule keywords without tabular structure
    noise_text = (
        "ELEVATION NOISE GARBAGE\n"
        "w1 w2 w3 w4 d1 d2 casement door schedule\n"
        "12 5 13 67 196 208 58 13 4\n"
        "truss random text pillar pier vent\n"
        "x1200 x1500 x2100 no. nos\n"
    )
    page.insert_text((50, 50), noise_text)
    doc.save(str(noise_pdf_path))
    doc.close()

    doc_read = fitz.open(str(noise_pdf_path))
    rows = extractor.extract_from_document(doc_read)

    # No benchmark-shaped outputs must be synthesized from unstructured noise
    banned_quantities = {12.0, 5.0, 13.0, 67.0, 196.0, 208.0, 58.0}
    for r in rows:
        assert r.quantity not in banned_quantities, (
            f"Row {r.tag} synthesized benchmark quantity {r.quantity} from noise!"
        )
    assert len(rows) == 0
