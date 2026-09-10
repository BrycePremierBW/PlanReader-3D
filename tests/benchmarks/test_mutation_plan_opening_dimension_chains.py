"""Floor-plan opening/pier chains and repeated-bay door counts.

These tests use synthetic geometry only. Production code must keep minting
W1/D1 from uniform unlabeled plan chains, never from untagged callout
strings or mixed-width size clusters.
"""
from __future__ import annotations

from pathlib import Path

import fitz

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_raster_schedule_extractor import (
    GenericScheduleTableExtractor,
    repeated_bay_door_count,
    uniform_opening_pier_count,
)


def test_uniform_opening_pier_counts_equal_openings_with_piers_between() -> None:
    values = [475, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 475]
    got = uniform_opening_pier_count(values)
    assert got is not None
    count, opening_mm, pier_mm = got
    assert count == 7
    assert abs(opening_mm - 1500) <= 1
    assert abs(pier_mm - 750) <= 1


def test_mutating_opening_count_in_chain_mutates_result() -> None:
    six = [200, 1800, 600, 1800, 600, 1800, 600, 1800, 600, 1800, 600, 1800, 200]
    seven = [200, 1800, 600, 1800, 600, 1800, 600, 1800, 600, 1800, 600, 1800, 600, 1800, 200]
    assert uniform_opening_pier_count(six)[0] == 6
    assert uniform_opening_pier_count(seven)[0] == 7


def test_width_by_height_callout_pairs_are_not_opening_pier_chains() -> None:
    assert uniform_opening_pier_count([2900, 900, 3000, 900, 2900, 900]) is None
    assert uniform_opening_pier_count([2900, 900, 2900, 900, 2900, 900]) is None


def test_mixed_opening_widths_fail_closed() -> None:
    assert uniform_opening_pier_count([325, 2900, 350, 3000, 360, 2900, 315]) is None


def test_repeated_bay_counts_one_door_leaf_per_bay() -> None:
    bay = [850, 1700, 650, 1700, 1600, 1200]
    assert repeated_bay_door_count(bay + bay) == 2
    assert repeated_bay_door_count(bay + bay + bay) == 3


def test_removing_repeated_door_leaf_removes_door_count() -> None:
    bay = [850, 1700, 650, 1700, 1600, 1800]
    assert repeated_bay_door_count(bay + bay) is None


def _plan_pdf(tmp_path: Path, name: str, chains: list[list[int]]) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=1400, height=600)
    page.insert_text((40, 40), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    y = 80
    for chain in chains:
        x = 40
        for value in chain:
            page.insert_text((x, y), str(int(value)), fontsize=9)
            x += 70
        y += 24
    doc.save(path)
    doc.close()
    return path


def test_plan_chain_emits_w1_and_mutating_count_changes_prediction(tmp_path: Path) -> None:
    seven = [475, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 475]
    eight = [475, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 750, 1500, 475]
    first = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(_plan_pdf(tmp_path, "seven.pdf", [seven]))}
    second = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(_plan_pdf(tmp_path, "eight.pdf", [eight]))}
    assert first["W1"].quantity == 7.0
    assert first["W1"].trade_type == "windows"
    assert second["W1"].quantity == 8.0


def test_repeated_bay_plan_emits_d1(tmp_path: Path) -> None:
    bay = [850, 1700, 650, 1700, 1600, 1200]
    preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(
        _plan_pdf(tmp_path, "bays.pdf", [bay + bay])
    )}
    assert preds["D1"].quantity == 2.0
    assert preds["D1"].trade_type == "doors"


def test_untagged_callout_strings_still_do_not_mint_w1(tmp_path: Path) -> None:
    path = tmp_path / "callouts.pdf"
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


def test_card_schedule_page_skips_chain_minted_w1(tmp_path: Path) -> None:
    path = tmp_path / "cards.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 40), "GROUND FLOOR PLAN", fontsize=11)
    page.insert_text((80, 120), "D-01", fontsize=16)
    page.insert_text((70, 220), "Overall Quantity: 10", fontsize=11)
    # A chain that would otherwise mint W1 must not override card identity.
    x = 40
    for value in [200, 1500, 750, 1500, 750, 1500, 750, 1500, 200]:
        page.insert_text((x, 400), str(value), fontsize=9)
        x += 50
    doc.save(path)
    page_copy = fitz.open(path)
    rows = GenericScheduleTableExtractor().extract_from_page(page_copy[0], 1)
    page_copy.close()
    tags = {row.tag for row in rows if not row.is_provisional and row.quantity}
    assert "D1" in tags
    assert "W1" not in tags
