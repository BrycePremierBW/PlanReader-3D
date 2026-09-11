"""Generic recovery of plan chalkboard labels, undotted DPC notes, and Linux OCR specs."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from pb_drawing_ocr_evidence_layer import DrawingOCREngine
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from tests.benchmarks._ocr_backend import OCR_AVAILABLE


def _text_pdf(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((50, 50), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def _preds(pdf: Path) -> dict:
    return {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)}


def test_two_classroom_chalkboard_labels_count_as_two(tmp_path: Path) -> None:
    pdf = _text_pdf(
        tmp_path,
        "two_chalkboards.pdf",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-01\n"
        "13,000 x 7,000\n"
        "CLASSROOM 01\nChalkboard\n"
        "CLASSROOM 02\nChalkboard\n",
    )
    preds = _preds(pdf)
    assert preds["chalkboard"].quantity == 2.0
    assert preds["chalkboard"].unit == "NO"


def test_elevation_blackboard_sentence_does_not_double_count(tmp_path: Path) -> None:
    pdf = _text_pdf(
        tmp_path,
        "elevation_board.pdf",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-01\n"
        "2,400mm x 1,200mm blaoc painted surface to be used as the black board.\n"
        "2,400mm x 1,200mm blaoc painted surface to be used as the black board.\n",
    )
    preds = _preds(pdf)
    assert preds["chalkboard"].quantity == 1.0


def test_sentence_chalkboard_keyword_without_label_does_not_emit(tmp_path: Path) -> None:
    pdf = _text_pdf(
        tmp_path,
        "keyword_only.pdf",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-01\n"
        "13,000 x 7,000\n"
        "chalkboard on front wall\n",
    )
    preds = _preds(pdf)
    assert "chalkboard" not in preds


def test_undotted_dpc_and_dam_proof_course_emit_perimeter_length(tmp_path: Path) -> None:
    pdf = _text_pdf(
        tmp_path,
        "dpc_undotted.pdf",
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-01\n"
        "13,000 x 7,000\n"
        "06. DPC (Dam Proof Course) to be laid under all walls\n",
    )
    preds = _preds(pdf)
    assert "damp_proof_course" in preds
    assert preds["damp_proof_course"].quantity == 40.0  # 2*(13+7)


@pytest.mark.skipif(not OCR_AVAILABLE, reason="no usable Tesseract backend in this environment")
def test_tesseract_fallback_reads_printed_plan_text() -> None:
    image = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 80), "1000 gauge polythene DPM under slab", fill="black")
    lines = DrawingOCREngine().recognize_pil_image(image)
    blob = " ".join(line["text"] for line in lines).lower()
    assert "polythene" in blob or "dpm" in blob


@pytest.mark.skipif(not OCR_AVAILABLE, reason="no usable Tesseract backend in this environment")
def test_ocr_recovers_polythene_dpm_from_embedded_plan_raster(tmp_path: Path) -> None:
    image = Image.new("RGB", (1000, 280), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.text((30, 110), "1000 gauge polythene DPM under slab", fill="black", font=font)
    raster = tmp_path / "dpm_note.png"
    image.save(raster)

    path = tmp_path / "raster_dpm_plan.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text(
        (50, 40),
        "GROUND FLOOR PLAN\nSCALE 1:100\nDRAWING NO: A-17\n13,000 x 7,000\n",
        fontsize=11,
    )
    page.insert_image(fitz.Rect(40, 160, 800, 360), filename=str(raster))
    doc.save(path)
    doc.close()

    preds = _preds(path)
    assert preds["floor_screed"].quantity == 91.0
    assert preds["substructure_bed_dpm"].quantity == 91.0
