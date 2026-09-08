"""Mutation tests for generic internal plaster annotation grammar."""
from __future__ import annotations

from pathlib import Path

import fitz

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _extract(tmp_path: Path, annotation: str):
    path = tmp_path / "synthetic-finishes.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text(
        (50, 50),
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-42\n"
        "14,000 x 8,000\n" + annotation,
    )
    doc.save(path)
    doc.close()
    return {
        pred.tag: pred
        for pred in GenericPlanReaderExtractor().extract_from_pdf(path)
    }


def test_inflected_internal_finish_annotation_emits_both_coatings(
    tmp_path: Path,
) -> None:
    preds = _extract(
        tmp_path,
        "150mm masonry walls (Plastered & painted internally)",
    )

    assert preds["internal_plaster"].quantity == preds["perimeter_walling"].quantity
    assert preds["internal_paint"].quantity == preds["perimeter_walling"].quantity


def test_object_finish_without_internal_scope_does_not_finish_all_walls(
    tmp_path: Path,
) -> None:
    preds = _extract(tmp_path, "BLACKBOARD (Plastered & Painted to approval)")

    assert "internal_plaster" not in preds
    assert "internal_paint" not in preds
