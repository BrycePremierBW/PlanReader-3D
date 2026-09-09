"""End-to-end synthetic wiring tests for F.30 orthogonal envelope evidence."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _save_corroborated_compound_plan(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((60, 45), "GROUND FLOOR PLAN", fontsize=12)
    page.insert_text((500, 45), "DRAWING NO SYN-F30", fontsize=9)
    page.insert_text((300, 190), "FLOOR AREA - 162.69M2", fontsize=10)

    # Two same-axis horizontal dimensions. The old size-ranked heuristic would
    # incorrectly pair 15.95 with the internal/sub-chain 11.05.
    page.insert_text((240, 80), "15,950", fontsize=10)
    page.insert_text((240, 105), "11,050", fontsize=10)
    page.insert_text((240, 130), "4,300", fontsize=10)

    # The orthogonal overall direction is native rotated text.
    page.insert_text((90, 360), "8,200", fontsize=10, rotate=90)
    page.insert_text((120, 360), "7,800", fontsize=10, rotate=90)
    page.insert_text((150, 360), "4,600", fontsize=10, rotate=90)

    # A separately figured width is spatially bound to the named secondary
    # strip.  No prose states "2m wide verandah"; the binding is geometric.
    page.insert_text((90, 440), "2,000", fontsize=10, rotate=90)
    page.insert_text((300, 430), "VERANDAH", fontsize=10)

    doc.save(path)
    doc.close()
    return path


def _save_uncorroborated_plain_plan(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((60, 45), "GROUND FLOOR PLAN", fontsize=12)
    page.insert_text((240, 80), "10,000", fontsize=10)
    page.insert_text((240, 105), "8,000", fontsize=10)
    doc.save(path)
    doc.close()
    return path


def test_corroborated_orthogonal_envelope_drives_wall_and_floor_geometry(tmp_path: Path):
    pdf = _save_corroborated_compound_plan(tmp_path / "compound.pdf")
    predictions = GenericPlanReaderExtractor().extract_from_pdf(pdf)
    by_tag = {prediction.tag: prediction for prediction in predictions}

    floor = by_tag["floor_screed"]
    wall = by_tag["perimeter_walling"]

    assert floor.quantity == pytest.approx(162.69)
    assert floor.dimensions == pytest.approx([15.95, 8.2])
    assert floor.metadata["derived_footprint_area_m2"] == pytest.approx(162.69)
    assert floor.metadata["envelope_authority"] == (
        "orthogonal_figured_dimensions_corroborated_by_explicit_floor_area"
    )
    assert floor.metadata["secondary_width_m"] == pytest.approx(2.0)
    assert floor.metadata["secondary_width_source"] == "spatial_label_dimension"

    assert wall.dimensions[0] == pytest.approx(48.3)
    assert wall.quantity == pytest.approx(48.3 * 2.8)
    assert wall.metadata["envelope_authority"] == floor.metadata["envelope_authority"]


def test_no_explicit_floor_area_preserves_legacy_envelope_path(tmp_path: Path):
    pdf = _save_uncorroborated_plain_plan(tmp_path / "plain.pdf")
    predictions = GenericPlanReaderExtractor().extract_from_pdf(pdf)
    by_tag = {prediction.tag: prediction for prediction in predictions}

    floor = by_tag["floor_screed"]
    assert floor.dimensions == pytest.approx([10.0, 8.0])
    assert floor.quantity == pytest.approx(80.0)
    assert "envelope_authority" not in floor.metadata
