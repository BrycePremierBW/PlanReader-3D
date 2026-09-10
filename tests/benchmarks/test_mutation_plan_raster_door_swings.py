"""Interior inverted-CAD door-swing symbols emit unlabeled D2 totals."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image

from pb_plan_raster_door_swings import (
    interior_door_swings_from_raster,
    should_emit_interior_door_total,
    similar_radius_cluster,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _quarter_ring(image: np.ndarray, cx: int, cy: int, outer: int, inner: int) -> None:
    outer_pts = []
    inner_pts = []
    for angle in range(180, 271):
        rad = math.radians(angle)
        outer_pts.append(
            [int(cx + outer * math.cos(rad)), int(cy + outer * math.sin(rad))]
        )
        inner_pts.append(
            [int(cx + inner * math.cos(rad)), int(cy + inner * math.sin(rad))]
        )
    poly = np.array(outer_pts + inner_pts[::-1], np.int32)
    cv2.fillPoly(image, [poly], (255, 255, 255))


def _dark_swings(count: int) -> np.ndarray:
    image = np.zeros((360, 140 + count * 130, 3), np.uint8)
    for i in range(count):
        _quarter_ring(image, 90 + i * 130, 190, 46, 40)
    return image


def _pdf_with_raster(
    tmp_path: Path,
    name: str,
    rgb: np.ndarray,
    title: str = "PLAN : FLOOR LAYOUT  SCALE 1:100",
) -> Path:
    path = tmp_path / name
    raster = tmp_path / f"{name}.png"
    Image.fromarray(rgb).save(raster)
    doc = fitz.open()
    height = 80 + rgb.shape[0]
    page = doc.new_page(width=float(rgb.shape[1]), height=float(height))
    page.insert_text((40, 36), title, fontsize=11)
    page.insert_image(
        fitz.Rect(0, 70, rgb.shape[1], 70 + rgb.shape[0]),
        filename=str(raster),
    )
    doc.save(path)
    doc.close()
    return path


def test_similar_radius_cluster_is_tight() -> None:
    assert similar_radius_cluster((35.4, 35.7, 36.5))
    assert not similar_radius_cluster((28.0, 47.0))


def test_typed_door_tag_blocks_interior_emission() -> None:
    radii = (35.0, 35.0, 36.0)
    assert should_emit_interior_door_total(3, radii, [])
    assert should_emit_interior_door_total(3, radii, ["W1"])
    assert not should_emit_interior_door_total(3, radii, ["D1"])
    assert not should_emit_interior_door_total(1, radii[:1], [])


def test_light_background_raster_is_ignored() -> None:
    light = np.full((320, 480, 3), 250, np.uint8)
    _quarter_ring(light, 160, 160, 46, 40)
    _quarter_ring(light, 300, 160, 46, 40)
    _quarter_ring(light, 400, 160, 46, 40)
    assert interior_door_swings_from_raster(light) == []


def test_interior_swings_emit_d2_and_mutating_count_changes_prediction(
    tmp_path: Path,
) -> None:
    two = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _pdf_with_raster(tmp_path, "two.pdf", _dark_swings(2))
        )
    }
    three = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _pdf_with_raster(tmp_path, "three.pdf", _dark_swings(3))
        )
    }
    assert two["D2"].quantity == 2.0
    assert three["D2"].quantity == 3.0
    assert two["D2"].trade_type == "doors"
    assert "D1" not in two
    assert "D1" not in three
    assert "W1" not in three


def test_schedule_title_does_not_mint_d2(tmp_path: Path) -> None:
    preds = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _pdf_with_raster(
                tmp_path,
                "sched.pdf",
                _dark_swings(3),
                title="WINDOW AND DOOR SCHEDULE  SCALE 1:50",
            )
        )
    }
    assert "D2" not in preds


def test_existing_card_door_identity_keeps_authority(tmp_path: Path) -> None:
    path = tmp_path / "card.pdf"
    rgb = _dark_swings(3)
    raster = tmp_path / "card.png"
    Image.fromarray(rgb).save(raster)
    doc = fitz.open()
    page = doc.new_page(width=900, height=700)
    page.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    page.insert_text((80, 120), "D-01", fontsize=16)
    page.insert_text((70, 220), "Overall Quantity: 10", fontsize=11)
    page.insert_image(fitz.Rect(40, 280, 40 + rgb.shape[1], 280 + rgb.shape[0]), filename=str(raster))
    doc.save(path)
    doc.close()
    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(path)}
    assert preds["D1"].quantity == 10.0
    assert "D2" not in preds


def test_untagged_callout_strings_without_cad_swings_do_not_mint_d2(
    tmp_path: Path,
) -> None:
    path = tmp_path / "callouts.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    page.insert_text(
        (60, 100),
        "2,900mm x 900mm steel casement windows with 4mm thick glass",
        fontsize=9,
    )
    page.insert_text(
        (60, 130),
        "3,000mm x 900mm steel casement windows with 4mm thick glass",
        fontsize=9,
    )
    page.insert_text(
        (60, 160),
        "1,000mm x 2,100mm timber batten door with 3 nos. butt hinges",
        fontsize=9,
    )
    doc.save(path)
    doc.close()
    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(path)}
    assert "W1" not in preds
    assert "W2" not in preds
    assert "D1" not in preds
    assert "D2" not in preds
