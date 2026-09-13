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


def _two_page_plan(tmp_path: Path, name: str, page_one: str, page_two: str) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    for text in (page_one, page_two):
        page = doc.new_page(width=842, height=595)
        page.insert_text((50, 50), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_later_explicit_floor_area_replaces_early_dpm_envelope(tmp_path: Path) -> None:
    pdf = _two_page_plan(
        tmp_path,
        "early-small-dpm.pdf",
        "DETAIL ENLARGEMENT\nSCALE 1:20\nDRAWING NO: A-02\n"
        "5,000 x 3,000\n"
        "500 gauge polythene DPM under slab\n",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: 1 of 3\n"
        "15,950 x 8,200\n"
        "FLOOR AREA - 162.69M2\n"
        "09. 500mm gauge polythene, DPM (Damp Proof Membrane) "
        "under ground floor concrete slab\n",
    )
    preds = {
        p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)
    }
    assert preds["floor_screed"].quantity == 162.69
    assert preds["substructure_bed_dpm"].quantity == 162.69
    assert preds["substructure_bed_dpm"].metadata["area_authority"] == (
        "explicit_drawing_floor_area"
    )


def test_later_small_envelope_does_not_clobber_explicit_dpm(tmp_path: Path) -> None:
    pdf = _two_page_plan(
        tmp_path,
        "explicit-then-small.pdf",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: 1 of 3\n"
        "15,950 x 8,200\n"
        "FLOOR AREA - 162.69M2\n"
        "500 gauge polythene DPM under slab\n",
        "DETAIL ENLARGEMENT\nSCALE 1:20\nDRAWING NO: A-02\n"
        "5,000 x 3,000\n"
        "500 gauge polythene DPM under slab\n",
    )
    preds = {
        p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)
    }
    assert preds["substructure_bed_dpm"].quantity == 162.69


def test_later_explicit_floor_area_replaces_early_envelope_without_local_dpm_text(
    tmp_path: Path,
) -> None:
    """DPM wording may appear only on the later plan; an earlier envelope still binds."""
    pdf = _two_page_plan(
        tmp_path,
        "early-envelope-late-dpm-note.pdf",
        "SECTION A-A\nSCALE 1:50\nDRAWING NO: A-05\n"
        "5,000 x 7,500\n",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: 1 of 3\n"
        "15,950 x 8,200\n"
        "FLOOR AREA - 162.69M2\n"
        "09. 500mm gauge polythene, DPM (Damp Proof Membrane) "
        "under ground floor concrete slab\n",
    )
    preds = {
        p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)
    }
    assert preds["floor_screed"].quantity == 162.69
    assert preds["substructure_bed_dpm"].quantity == 162.69
    assert preds["substructure_bed_dpm"].metadata["area_authority"] == (
        "explicit_drawing_floor_area"
    )


def test_later_explicit_plan_replaces_early_dpc_perimeter(tmp_path: Path) -> None:
    pdf = _two_page_plan(
        tmp_path,
        "early-small-dpc.pdf",
        "DETAIL ENLARGEMENT\nSCALE 1:20\nDRAWING NO: A-02\n"
        "5,000 x 3,000\n"
        "DPC (Dam Proof Course) to be laid under all walls\n",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: 1 of 3\n"
        "15,950 x 8,200\n"
        "FLOOR AREA - 162.69M2\n"
        "06. DPC (Dam Proof Course) to be laid under all walls\n",
    )
    preds = {
        p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)
    }
    assert preds["damp_proof_course"].quantity == 48.3
