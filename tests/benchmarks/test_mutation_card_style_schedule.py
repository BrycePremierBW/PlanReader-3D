"""Mutation/metamorphic/red-team tests for card-style schedule detection.

Some drafting standards lay out one bordered "card" per opening type (a
detail drawing plus a small key/value table) rather than a shared table
or a bare tag counted where it appears on a plan. The card states its own
total directly in a labelled field such as "Overall Quantity: 172" --
found for real on a genuine tender drawing (Umma University student
hostels, TI-UUH/25/11 rev.02) where the prior extractor produced *zero*
predictions from 12 real, correctly-labelled door types.

``_extract_card_style_schedules`` associates a "Overall Quantity" field
with the nearest documented tag block positioned directly above it in the
same horizontal band -- real spatial evidence, not document order or a
benchmark-specific count.

All drawings are synthetic. No development-benchmark quantities, project
names, file names, or expected takeoff outputs are used anywhere here.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_raster_schedule_extractor import GenericScheduleTableExtractor


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _card_pdf(*, cards: list[dict]) -> fitz.Document:
    """Build a page with one or more independent "card" layouts.

    Each card dict may contain: ``tag`` (str, inserted at ``tag_pos``),
    ``quantity_text`` (str, inserted at ``qty_pos``), and both positions
    default to a sensible vertical stack if omitted.
    """
    doc = fitz.open()
    page = doc.new_page(width=842, height=1200)
    for card in cards:
        if "tag" in card:
            page.insert_text(card["tag_pos"], card["tag"], fontsize=9)
        if "quantity_text" in card:
            page.insert_text(card["qty_pos"], card["quantity_text"], fontsize=9)
    return _reopen(doc)


def _rows_by_tag(doc: fitz.Document) -> dict:
    extractor = GenericScheduleTableExtractor()
    rows = extractor._extract_card_style_schedules(doc[0], page_num=1)
    doc.close()
    return {r.tag: r for r in rows}


def test_nominal_tag_above_quantity_same_column_resolves():
    doc = _card_pdf(cards=[{
        "tag": "D - 05",
        "tag_pos": (100, 200),
        "quantity_text": "Overall Quantity: 12",
        "qty_pos": (100, 260),
    }])
    rows = _rows_by_tag(doc)
    assert "D5" in rows
    assert rows["D5"].quantity == 12.0
    assert rows["D5"].trade_type == "doors"
    assert rows["D5"].confidence == pytest.approx(0.90)


def test_quantity_value_on_following_line_without_colon_resolves():
    # Matches a real observed variant: "Overall Quantity" then the number
    # on its own line within the same text block, no colon.
    doc = fitz.open()
    page = doc.new_page(width=842, height=1200)
    page.insert_text((100, 200), "W - 07", fontsize=9)
    page.insert_text((100, 260), "Overall Quantity\n7", fontsize=9)
    doc = _reopen(doc)
    rows = _rows_by_tag(doc)
    assert "W7" in rows
    assert rows["W7"].quantity == 7.0
    assert rows["W7"].trade_type == "windows"


def test_multiple_independent_cards_each_resolve_correctly():
    doc = _card_pdf(cards=[
        {"tag": "D - 01", "tag_pos": (100, 200), "quantity_text": "Overall Quantity: 5", "qty_pos": (100, 260)},
        {"tag": "D - 02", "tag_pos": (400, 200), "quantity_text": "Overall Quantity: 9", "qty_pos": (400, 260)},
        {"tag": "W - 03", "tag_pos": (700, 200), "quantity_text": "Overall Quantity: 3", "qty_pos": (700, 260)},
    ])
    rows = _rows_by_tag(doc)
    assert rows["D1"].quantity == 5.0
    assert rows["D2"].quantity == 9.0
    assert rows["W3"].quantity == 3.0


def test_ambiguous_combined_prefix_fails_closed():
    # "WD" is not a single documented opening type -- normalize_opening_tag
    # rejects it, so this card must not resolve to anything at all rather
    # than guessing window or door.
    doc = _card_pdf(cards=[{
        "tag": "WD 01",
        "tag_pos": (100, 200),
        "quantity_text": "Overall Quantity: 172",
        "qty_pos": (100, 260),
    }])
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_tag_substring_inside_longer_sentence_is_not_treated_as_a_card_tag():
    # A tag-shaped substring inside a real sentence (e.g. a spec note) must
    # not be mistaken for a standalone card tag label.
    doc = fitz.open()
    page = doc.new_page(width=842, height=1200)
    page.insert_text(
        (100, 200),
        "Refer to detail D - 05 for the door frame profile and finish",
        fontsize=9,
    )
    page.insert_text((100, 260), "Overall Quantity: 12", fontsize=9)
    doc = _reopen(doc)
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_quantity_without_any_tag_above_it_is_not_fabricated():
    doc = _card_pdf(cards=[{
        "quantity_text": "Overall Quantity: 12",
        "qty_pos": (100, 260),
    }])
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_tag_present_but_no_quantity_field_produces_nothing():
    doc = _card_pdf(cards=[{
        "tag": "D - 05",
        "tag_pos": (100, 200),
    }])
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_tag_below_the_quantity_field_is_not_associated():
    # Wrong reading order: the tag sits BELOW the quantity field. This must
    # never resolve -- a card's tag always heads its own table.
    doc = _card_pdf(cards=[{
        "tag": "D - 05",
        "tag_pos": (100, 300),
        "quantity_text": "Overall Quantity: 12",
        "qty_pos": (100, 200),
    }])
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_tag_in_a_different_horizontal_column_is_not_associated():
    # The tag exists on the page but in an unrelated column (no horizontal
    # overlap with the quantity field) -- must fail closed, not borrow a
    # neighbouring card's tag.
    doc = _card_pdf(cards=[
        {"tag": "D - 01", "tag_pos": (100, 200)},
        {"quantity_text": "Overall Quantity: 9", "qty_pos": (500, 260)},
    ])
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_nearest_tag_wins_when_two_tags_stack_above_one_quantity():
    # Two tag-shaped blocks share the same column, one closer than the
    # other. The nearer one (a more plausible header for this specific
    # card) must be the one associated, not the farther one.
    doc = _card_pdf(cards=[
        {"tag": "D - 01", "tag_pos": (100, 100)},
        {"tag": "D - 02", "tag_pos": (100, 200)},
        {"quantity_text": "Overall Quantity: 9", "qty_pos": (100, 260)},
    ])
    rows = _rows_by_tag(doc)
    assert "D2" in rows
    assert rows["D2"].quantity == 9.0
    assert "D1" not in rows


def test_zero_quantity_value_is_excluded():
    doc = _card_pdf(cards=[{
        "tag": "D - 05",
        "tag_pos": (100, 200),
        "quantity_text": "Overall Quantity: 0",
        "qty_pos": (100, 260),
    }])
    rows = _rows_by_tag(doc)
    assert rows == {}


def test_wired_into_full_extractor_pipeline(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page(width=842, height=1200)
    page.insert_text((100, 200), "D - 05", fontsize=9)
    page.insert_text((100, 260), "Overall Quantity: 12", fontsize=9)
    pdf_path = tmp_path / "card_schedule.pdf"
    doc.save(str(pdf_path))
    doc.close()

    doc2 = fitz.open(str(pdf_path))
    extractor = GenericScheduleTableExtractor()
    rows = {r.tag: r for r in extractor.extract_from_page(doc2[0], page_num=1)}
    doc2.close()
    assert "D5" in rows
    assert rows["D5"].quantity == 12.0
    assert rows["D5"].source_page == 1
    assert rows["D5"].bbox[2] > rows["D5"].bbox[0]
