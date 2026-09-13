"""Unique door WxH callouts bind onto one dimensionless door identity only."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import fitz

from pb_opening_callout_dimension_binder import (
    bind_unique_door_callout_dimensions,
    parse_opening_size_callouts,
    unique_door_size_mm,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


@dataclass
class _Pred:
    tag: str
    trade_type: str
    dimensions: Optional[List[float]] = None
    metadata: Dict[str, str] = field(default_factory=dict)


def test_parses_split_line_door_callout_and_ignores_hardware_count() -> None:
    text = (
        "2,900mm x 900mm steel casement windows with 4mm thick glass\n"
        "3,000mm x 900mm steel casement windows with 4mm thick glass\n"
        "1,000mm x 2,100mm timber\n"
        "batten door with 3 nos. butt hinges\n"
    )
    callouts = parse_opening_size_callouts(text)
    doors = [item for item in callouts if item.kind == "door"]
    windows = [item for item in callouts if item.kind == "window"]
    assert unique_door_size_mm(callouts) == (1000.0, 2100.0)
    assert len(doors) >= 1
    assert doors[0].width_mm == 1000.0
    assert doors[0].height_mm == 2100.0
    assert len(windows) == 2


def test_two_disagreeing_door_sizes_bind_nothing() -> None:
    text = (
        "1000mm x 2100mm timber door\n"
        "900mm x 2100mm flush door\n"
    )
    assert unique_door_size_mm(parse_opening_size_callouts(text)) is None
    preds = [_Pred("D1", "doors")]
    assert bind_unique_door_callout_dimensions(preds, [text]) == 0
    assert preds[0].dimensions is None


def test_unique_door_size_binds_only_dimensionless_d1() -> None:
    preds = [_Pred("D1", "doors"), _Pred("W1", "windows", dimensions=[1500.0])]
    text = "1,000mm x 2,100mm timber batten door with 3 nos. butt hinges"
    assert bind_unique_door_callout_dimensions(preds, [text]) == 1
    assert preds[0].dimensions == [1000.0, 2100.0]
    assert preds[1].dimensions == [1500.0]


def test_two_dimensionless_door_identities_fail_closed() -> None:
    preds = [_Pred("D1", "doors"), _Pred("D2", "doors")]
    text = "1000mm x 2100mm timber door"
    assert bind_unique_door_callout_dimensions(preds, [text]) == 0
    assert preds[0].dimensions is None
    assert preds[1].dimensions is None


def test_lumped_doors_complete_is_not_a_bind_target() -> None:
    preds = [_Pred("doors_complete", "doors")]
    text = "1000mm x 2100mm timber door"
    assert bind_unique_door_callout_dimensions(preds, [text]) == 0
    assert preds[0].dimensions is None


def test_conflicting_existing_width_fails_closed() -> None:
    preds = [_Pred("D1", "doors", dimensions=[1500.0])]
    text = "1000mm x 2100mm timber door"
    assert bind_unique_door_callout_dimensions(preds, [text]) == 0
    assert preds[0].dimensions == [1500.0]


def test_malformed_near_match_is_not_a_door_size() -> None:
    text = "50mm x 50mm s/w battens on timber trusses"
    assert parse_opening_size_callouts(text) == []


def test_window_callouts_do_not_mint_identities(tmp_path: Path) -> None:
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


def _swing_and_callout_pdf(tmp_path: Path) -> Path:
    """One unlabeled cubic door swing plus a unique door WxH note."""
    path = tmp_path / "swing_callout.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 36), "GROUND FLOOR PLAN  SCALE 1:100", fontsize=11)
    page.insert_text(
        (40, 54),
        "1,000mm x 2,100mm timber batten door with 3 nos. butt hinges",
        fontsize=9,
    )
    for i in range(12):
        _quarter(page, (80 + (i % 8) * 28, 90 + (i // 8) * 28), 16)
    _quarter(page, (120, 320), 40)
    doc.save(path)
    doc.close()
    return path


def test_unique_door_callout_binds_onto_sole_plan_swing(tmp_path: Path) -> None:
    preds = {
        p.tag: p
        for p in GenericPlanReaderExtractor().extract_from_pdf(
            _swing_and_callout_pdf(tmp_path)
        )
    }
    assert "D1" in preds
    assert preds["D1"].dimensions == [1000.0, 2100.0]
    assert "W1" not in preds
    assert "W2" not in preds
