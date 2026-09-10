"""Plan-stamp opening marks: hyphenated W-# / D-# instance recovery."""
from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

from pb_plan_opening_instance_marks import (
    PlanInstanceOpeningTotals,
    _assemble,
    _nms,
    package_documents_casement_windows,
    should_emit_casement_window_total,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
    )


def _label_image(labels: list[tuple[str, int, int]], width: int = 900, height: int = 220) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(28)
    for text, x, y in labels:
        draw.text((x, y), text, fill=(20, 20, 20), font=font)
    return image


def _pdf_with_raster(
    tmp_path: Path,
    name: str,
    labels: list[tuple[str, int, int]],
    extra_text: str,
) -> Path:
    path = tmp_path / name
    raster = tmp_path / f"{name}.png"
    _label_image(labels).save(raster)
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    page.insert_text((40, 54), extra_text, fontsize=10)
    rect = fitz.Rect(40, 90, 520, 250)
    page.insert_image(rect, filename=str(raster))
    doc.save(path)
    doc.close()
    return path


def test_package_casement_phrase_is_generic() -> None:
    assert package_documents_casement_windows(["Steel casement frames with glass"])
    assert not package_documents_casement_windows(["timber batten door with 3 nos. butt"])


def test_typed_schedule_tags_block_aggregate_emission() -> None:
    totals = PlanInstanceOpeningTotals(
        window_count=12,
        door_count=0,
        window_types=("W1", "W2"),
        door_types=(),
        source_page=1,
        evidence_text="W1",
    )
    assert should_emit_casement_window_total(totals, [])
    assert not should_emit_casement_window_total(totals, ["W1"])


def test_assemble_requires_hyphen_so_grid_d_and_1_do_not_join() -> None:
    parts = [
        {"t": "D", "conf": 80, "x": 10, "y": 10, "w": 12, "h": 16},
        {"t": "1", "conf": 80, "x": 80, "y": 10, "w": 10, "h": 16},
    ]
    marks = _assemble(parts, origin_x=0, origin_y=0, scale_x=1, scale_y=1, page=1)
    assert not any(mark.tag == "D1" for mark in marks)


def test_assemble_joins_w_hyphen_and_digit() -> None:
    parts = [
        {"t": "W-", "conf": 80, "x": 10, "y": 10, "w": 20, "h": 16},
        {"t": "2", "conf": 80, "x": 32, "y": 10, "w": 10, "h": 16},
    ]
    marks = _assemble(parts, origin_x=0, origin_y=0, scale_x=1, scale_y=1, page=1)
    assert any(mark.tag == "W2" and mark.complete for mark in marks)


def test_lone_hyphen_digit_promotes_on_window_band() -> None:
    parts = [
        {"t": "W-1", "conf": 80, "x": 10, "y": 10, "w": 30, "h": 16},
        {"t": "-1", "conf": 70, "x": 200, "y": 10, "w": 16, "h": 16},
        {"t": "W-", "conf": 60, "x": 320, "y": 12, "w": 18, "h": 16},
    ]
    marks = _nms(_assemble(parts, origin_x=0, origin_y=0, scale_x=1, scale_y=1, page=1))
    tags = [mark.tag for mark in marks if mark.trade == "windows"]
    assert tags.count("W1") == 2
    assert "W?" in tags


def test_raster_plan_stamps_emit_casement_total_and_mutate(tmp_path: Path) -> None:
    first_labels = [
        ("W-1", 20, 30),
        ("W-1", 160, 30),
        ("W-2", 300, 30),
        ("W-3", 20, 110),
        ("W-3", 160, 110),
        ("W-4", 300, 110),
    ]
    second_labels = first_labels + [("W-4", 440, 110)]
    extra = "Steel casement frames (25x25x3mm Z & T Sections) with 4mm thick glass."
    first = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _pdf_with_raster(tmp_path, "six.pdf", first_labels, extra)
        )
    }
    second = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _pdf_with_raster(tmp_path, "seven.pdf", second_labels, extra)
        )
    }
    assert first["steel_casement_windows"].quantity == 6.0
    assert second["steel_casement_windows"].quantity == 7.0
    assert "W1" not in first
    assert "W2" not in first
    assert "W3" not in first
    assert "W4" not in first


def test_untagged_casement_callouts_still_do_not_mint_identities(tmp_path: Path) -> None:
    path = tmp_path / "callouts.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    page.insert_text((40, 80), "Steel casement frames with 4mm thick glass", fontsize=9)
    page.insert_text((60, 120), "2,900mm x 900mm steel casement windows with 4mm thick glass", fontsize=9)
    page.insert_text((60, 150), "3,000mm x 900mm steel casement windows with 4mm thick glass", fontsize=9)
    page.insert_text((60, 180), "1,000mm x 2,100mm timber batten door with 3 nos. butt hinges", fontsize=9)
    doc.save(path)
    doc.close()
    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(path)}
    assert "W1" not in preds
    assert "W2" not in preds
    assert "D1" not in preds
    assert "steel_casement_windows" not in preds
