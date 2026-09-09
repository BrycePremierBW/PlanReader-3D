"""Synthetic mutation coverage for contextual combined-WD card evidence."""
from __future__ import annotations

import fitz
import pytest

from pb_contextual_wd_card_evidence import extract_contextual_wd_card_evidence
from pb_raster_schedule_extractor import GenericScheduleTableExtractor


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _fragmented_wd_card(
    *,
    number: int = 7,
    quantity: int = 23,
    x: float = 100.0,
    y: float = 180.0,
    scale: float = 1.0,
    witness_count: int = 3,
    add_d: bool = True,
    door_conflict: bool = False,
) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=1200 * scale, height=1000 * scale)
    fs = 10 * scale
    page.insert_text((x, y), "W", fontsize=fs)
    if add_d:
        page.insert_text((x + 16 * scale, y), "D", fontsize=fs)
    page.insert_text((x + 35 * scale, y), f"{number:02d}", fontsize=fs)
    labels = [
        "Window panel :",
        "Window frame :",
        "Window leaf type :",
        "Window stay type :",
    ]
    for idx, label in enumerate(labels[:witness_count]):
        page.insert_text(
            (x, y + (24 + idx * 16) * scale),
            label,
            fontsize=8 * scale,
        )
    if door_conflict:
        page.insert_text(
            (x, y + 88 * scale),
            "Door frame :",
            fontsize=8 * scale,
        )
    # Deliberately offset right so the quantity does not overlap the tag bbox.
    page.insert_text(
        (x + 85 * scale, y + 130 * scale),
        f"Overall Quantity: {quantity}",
        fontsize=8 * scale,
    )
    return _reopen(doc)


def _evidence(doc: fitz.Document):
    rows = extract_contextual_wd_card_evidence(doc[0], source_page=1)
    doc.close()
    return {row.tag: row for row in rows}


def test_fragmented_documented_wd_header_resolves_with_multiple_window_fields():
    rows = _evidence(_fragmented_wd_card())
    assert set(rows) == {"WD7"}
    assert rows["WD7"].quantity == 23.0
    assert set(rows["WD7"].witnesses) >= {"panel", "frame"}


def test_tag_and_quantity_mutations_propagate_without_lookup():
    a = _evidence(_fragmented_wd_card(number=4, quantity=19))
    b = _evidence(_fragmented_wd_card(number=9, quantity=31))
    assert set(a) == {"WD4"}
    assert a["WD4"].quantity == 19.0
    assert set(b) == {"WD9"}
    assert b["WD9"].quantity == 31.0


@pytest.mark.parametrize(
    "x,y,scale",
    [
        (70.0, 160.0, 1.0),
        (360.0, 330.0, 1.0),
        (140.0, 260.0, 1.7),
    ],
)
def test_translation_and_scale_invariance(x: float, y: float, scale: float):
    rows = _evidence(
        _fragmented_wd_card(
            x=x,
            y=y,
            scale=scale,
            number=12,
            quantity=6,
        )
    )
    assert set(rows) == {"WD12"}
    assert rows["WD12"].quantity == 6.0


def test_wd_without_window_semantics_remains_ambiguous_and_fails_closed():
    assert _evidence(_fragmented_wd_card(witness_count=0)) == {}


def test_single_window_field_is_insufficient_evidence():
    assert _evidence(_fragmented_wd_card(witness_count=1)) == {}


def test_door_field_conflict_forces_abstention():
    assert _evidence(
        _fragmented_wd_card(witness_count=3, door_conflict=True)
    ) == {}


def test_missing_d_fragment_does_not_invent_combined_identity():
    rows = _evidence(_fragmented_wd_card(add_d=False, witness_count=3))
    assert "WD7" not in rows


def test_combined_wd_text_block_can_resolve_only_with_window_fields():
    doc = fitz.open()
    page = doc.new_page(width=900, height=800)
    page.insert_text((100, 180), "WD - 05", fontsize=10)
    page.insert_text((100, 210), "Window panel :", fontsize=8)
    page.insert_text((100, 226), "Window frame :", fontsize=8)
    page.insert_text((185, 300), "Overall Quantity: 14", fontsize=8)
    rows = _evidence(_reopen(doc))
    assert set(rows) == {"WD5"}
    assert rows["WD5"].quantity == 14.0


def test_neighbouring_card_quantity_is_not_borrowed():
    doc = fitz.open()
    page = doc.new_page(width=1600, height=900)
    page.insert_text((100, 180), "W", fontsize=10)
    page.insert_text((116, 180), "D", fontsize=10)
    page.insert_text((135, 180), "08", fontsize=10)
    page.insert_text((100, 210), "Window panel :", fontsize=8)
    page.insert_text((100, 226), "Window frame :", fontsize=8)
    page.insert_text((900, 310), "Overall Quantity: 27", fontsize=8)
    assert "WD8" not in _evidence(_reopen(doc))


def test_wired_into_full_schedule_extractor():
    doc = _fragmented_wd_card(number=6, quantity=17, witness_count=3)
    rows = {
        row.tag: row
        for row in GenericScheduleTableExtractor().extract_from_page(doc[0], 1)
    }
    doc.close()
    assert "WD6" in rows
    assert rows["WD6"].quantity == 17.0
    assert rows["WD6"].trade_type == "windows"
    assert rows["WD6"].confidence == pytest.approx(0.90)
