from __future__ import annotations

from pathlib import Path

import fitz

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_raster_schedule_extractor import GenericScheduleTableExtractor


def _schedule_pdf(tmp_path: Path, name: str, rows: list[list[str]], extra_text: str = "") -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "DRAWING TITLE: WINDOW & DOOR SCHEDULE", fontsize=10)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    x = [40, 130, 300, 390, 650]
    y0 = 85
    rh = 28
    for ridx, row in enumerate(rows):
        y = y0 + ridx * rh
        page.draw_line(fitz.Point(x[0], y), fitz.Point(x[-1], y))
        for cidx, cell in enumerate(row):
            page.draw_line(fitz.Point(x[cidx], y), fitz.Point(x[cidx], y + rh))
            page.insert_text((x[cidx] + 5, y + 18), cell, fontsize=9)
        page.draw_line(fitz.Point(x[-1], y), fitz.Point(x[-1], y + rh))
    page.draw_line(fitz.Point(x[0], y0 + len(rows) * rh), fitz.Point(x[-1], y0 + len(rows) * rh))
    if extra_text:
        page.insert_text((40, y0 + len(rows) * rh + 35), extra_text, fontsize=9)
    doc.save(path)
    doc.close()
    return path


def test_arbitrary_documented_tags_wire_end_to_end(tmp_path: Path) -> None:
    pdf = _schedule_pdf(
        tmp_path,
        "arbitrary_tags.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W-17", "1840 x 1260 mm", "6 No.", "Powder coated casement window"],
            ["DOOR 12", "940 x 2140 mm", "3 No.", "Timber flush door"],
        ],
    )
    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)}
    assert preds["W17"].quantity == 6.0
    assert preds["W17"].dimensions == [1840.0, 1260.0]
    assert preds["W17"].trade_type == "windows"
    assert preds["D12"].quantity == 3.0
    assert preds["D12"].dimensions == [940.0, 2140.0]
    assert preds["D12"].trade_type == "doors"


def test_mutating_source_count_changes_only_that_opening(tmp_path: Path) -> None:
    first = _schedule_pdf(
        tmp_path,
        "before.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["WIN 8", "1730 x 1190 mm", "4 No.", "Casement window"],
            ["DR-3", "910 x 2080 mm", "2 No.", "Panel door"],
        ],
    )
    second = _schedule_pdf(
        tmp_path,
        "after.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["WIN 8", "1730 x 1190 mm", "9 No.", "Casement window"],
            ["DR-3", "910 x 2080 mm", "2 No.", "Panel door"],
        ],
    )
    p1 = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(first)}
    p2 = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(second)}
    assert p1["W8"].quantity == 4.0
    assert p2["W8"].quantity == 9.0
    assert p1["D3"].quantity == p2["D3"].quantity == 2.0


def test_removing_explicit_identity_removes_firm_opening(tmp_path: Path) -> None:
    tagged = _schedule_pdf(
        tmp_path,
        "tagged.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W-21", "1680 x 1110 mm", "5 No.", "Casement window"],
        ],
    )
    untagged = _schedule_pdf(
        tmp_path,
        "untagged.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["", "1680 x 1110 mm", "5 No.", "Casement window"],
        ],
    )
    tagged_preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(tagged)}
    untagged_preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(untagged)}
    assert tagged_preds["W21"].quantity == 5.0
    assert "W21" not in untagged_preds


def test_untagged_dimensions_never_synthesize_benchmark_shaped_identities(tmp_path: Path) -> None:
    path = tmp_path / "untagged_callouts.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    page.insert_text((60, 100), "2,900mm x 900mm steel casement windows with 4mm thick glass", fontsize=9)
    page.insert_text((60, 130), "3,000mm x 900mm steel casement windows with 4mm thick glass", fontsize=9)
    page.insert_text((60, 160), "1,000mm x 2,100mm timber batten door with 3 nos. butt hinges", fontsize=9)
    doc.save(path)
    doc.close()

    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(path)}
    assert "W1" not in preds
    assert "W2" not in preds
    assert "D1" not in preds


def test_conflicting_alias_rows_fail_closed(tmp_path: Path) -> None:
    pdf = _schedule_pdf(
        tmp_path,
        "conflict.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W-33", "1870 x 1240 mm", "4 No.", "Casement window"],
            ["WINDOW 33", "1870 x 1240 mm", "7 No.", "Casement window"],
        ],
    )
    doc = fitz.open(pdf)
    rows = GenericScheduleTableExtractor().extract_from_document(doc)
    assert not [r for r in rows if r.tag == "W33" and not r.is_provisional]


def test_production_no_longer_contains_three_special_case_opening_pipeline() -> None:
    import inspect
    import pb_planreader_pdf_extractor as mod

    src = inspect.getsource(mod.GenericPlanReaderExtractor.extract_from_pdf)
    assert "sched_spec_w1" not in src
    assert "sched_spec_w2" not in src
    assert "sched_spec_d1" not in src
    assert "w1_occs" not in src
    assert "w2_occs" not in src
    assert "d1_occs" not in src
