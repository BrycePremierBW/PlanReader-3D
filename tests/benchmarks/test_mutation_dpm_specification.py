"""Generic mutation coverage for damp-proof membrane specification wording."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _drawing(tmp_path: Path, wording: str) -> Path:
    path = tmp_path / "synthetic-dpm.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text(
        (50, 50),
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-17\n"
        "13,000 x 7,000\n" + wording,
    )
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize(
    "wording",
    [
        "500 Gauge DPM under floor bed",
        "D.P.M. beneath concrete slab",
        "damp proof membrane under slab",
        "1000 gauge polythene beneath bed",
    ],
)
def test_dpm_wording_variants_bind_to_evidenced_floor_area(
    tmp_path: Path, wording: str
) -> None:
    preds = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _drawing(tmp_path, wording)
        )
    }

    assert preds["floor_screed"].quantity == 91.0
    assert preds["substructure_bed_dpm"].quantity == 91.0


@pytest.mark.parametrize(
    "wording",
    [
        "D.P.C. under masonry walls",
        "damp proof course beneath walling",
    ],
)
def test_dpc_wording_does_not_create_membrane(tmp_path: Path, wording: str) -> None:
    tags = {
        p.tag
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _drawing(tmp_path, wording)
        )
    }

    assert "damp_proof_course" in tags
    assert "substructure_bed_dpm" not in tags
