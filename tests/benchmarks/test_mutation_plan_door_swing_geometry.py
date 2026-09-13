"""Sole unlabeled floor-plan door swings from quarter-circle cubics."""
from __future__ import annotations

from pathlib import Path

import fitz

from pb_plan_door_swing_geometry import (
    QuarterCircleCubic,
    extract_sole_plan_door_swing,
    page_is_floor_plan,
    should_emit_sole_unlabeled_door,
    unlabeled_door_swing_count,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _quarter(page: fitz.Page, origin: tuple[float, float], radius: float) -> None:
    x, y = origin
    page.draw_bezier(
        (x, y),
        (x, y + 0.55 * radius),
        (x - 0.45 * radius, y + radius),
        (x - radius, y + radius),
        color=(0, 0, 0),
        width=0.7,
    )


def _plan_pdf(
    tmp_path: Path,
    name: str,
    *,
    door_swings: int,
    fillets: int = 0,
    title: str = "GROUND FLOOR PLAN  SCALE 1:100",
    extra_text: str = "",
) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 36), title, fontsize=11)
    if extra_text:
        page.insert_text((40, 54), extra_text, fontsize=9)
    for i in range(fillets):
        _quarter(page, (80 + (i % 8) * 28, 90 + (i // 8) * 28), 16)
    for i in range(door_swings):
        _quarter(page, (120 + i * 90, 320), 40)
    doc.save(path)
    doc.close()
    return path


def test_floor_plan_phrase_is_generic() -> None:
    assert page_is_floor_plan("GROUND FLOOR PLAN")
    assert page_is_floor_plan("PLAN : FLOOR LAYOUT")
    assert not page_is_floor_plan("WINDOW AND DOOR SCHEDULE")
    assert not page_is_floor_plan("ROOF PLAN SCALE 1:100")


def test_fillet_cluster_plus_one_swing_counts_one() -> None:
    fillets = [QuarterCircleCubic(16.0, float(i), 10.0, 1) for i in range(12)]
    door = [QuarterCircleCubic(36.0, 200.0, 80.0, 1)]
    assert unlabeled_door_swing_count(fillets + door) == 1
    assert unlabeled_door_swing_count(fillets + door + door) == 2


def test_typed_door_tag_blocks_sole_emission() -> None:
    assert should_emit_sole_unlabeled_door(1, [])
    assert should_emit_sole_unlabeled_door(1, ["W1", "steel_casement_windows"])
    assert not should_emit_sole_unlabeled_door(1, ["D1"])
    assert not should_emit_sole_unlabeled_door(2, [])


def test_sole_plan_swing_emits_d1_and_second_swing_removes_it(tmp_path: Path) -> None:
    one = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _plan_pdf(tmp_path, "one.pdf", door_swings=1, fillets=12)
        )
    }
    two = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _plan_pdf(tmp_path, "two.pdf", door_swings=2, fillets=12)
        )
    }
    assert one["D1"].quantity == 1.0
    assert one["D1"].trade_type == "doors"
    assert "D1" not in two
    assert "D2" not in two


def test_schedule_page_with_logo_cubics_does_not_mint_d1(tmp_path: Path) -> None:
    preds = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _plan_pdf(
                tmp_path,
                "schedule.pdf",
                door_swings=1,
                fillets=0,
                title="WINDOW AND DOOR SCHEDULE  SCALE 1:50",
            )
        )
    }
    assert "D1" not in preds


def test_existing_card_door_identity_keeps_authority(tmp_path: Path) -> None:
    path = tmp_path / "card.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    page.insert_text((80, 120), "D-01", fontsize=16)
    page.insert_text((70, 220), "Overall Quantity: 10", fontsize=11)
    _quarter(page, (400, 320), 40)
    doc.save(path)
    doc.close()
    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(path)}
    assert preds["D1"].quantity == 10.0


def test_untagged_callout_strings_without_geometry_still_do_not_mint_d1(
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


def test_extract_skips_when_two_floor_plan_pages_disagree(tmp_path: Path) -> None:
    path = tmp_path / "disagree.pdf"
    doc = fitz.open()
    first = doc.new_page(width=842, height=595)
    first.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    _quarter(first, (120, 320), 40)
    second = doc.new_page(width=842, height=595)
    second.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    _quarter(second, (120, 320), 40)
    _quarter(second, (220, 320), 40)
    for i in range(12):
        _quarter(second, (80 + (i % 8) * 28, 90 + (i // 8) * 28), 16)
    doc.save(path)
    doc.close()
    opened = fitz.open(path)
    assert extract_sole_plan_door_swing(opened, [0, 1]) is None
    opened.close()
