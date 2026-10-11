"""Explicit printed room-area evidence must retain its original figured IDs."""
from __future__ import annotations

from copy import copy

import pytest

from pb_room_area_quantity import build_room_area_quantity
from tests.test_room_area_quantity_v2 import (
    _context, _document, _entity, _explicit_area, _room, _viewport,
)


def source_area(atom):
    return build_room_area_quantity(
        room=_room(), context=_context(), document=_document(),
        viewport=_viewport(), entity=_entity(), page_no=1,
        explicit_area_evidence=atom,
    )


def test_authentic_direct_printed_area_does_not_require_figured_dimension_pair():
    value = source_area(_explicit_area(25.0))
    assert not value.abstained
    assert value.value == 25.0
    assert value.metadata["figured_dimension_ids"] == []


def test_two_genuine_figured_source_witnesses_remain_authoritative():
    source = _explicit_area(25.0, metadata={
        "figured_dimension_ids": ("dim-width", "dim-height"),
    })
    quantity = source_area(source)
    assert not quantity.abstained
    assert quantity.value == 25.0
    assert quantity.metadata["figured_dimension_ids"] == ["dim-height", "dim-width"]


@pytest.mark.parametrize("bad_dim_ids", [
    "ab", "horizontal", "dim-width", ("dim-width",), (),
    ("dim-width", "dim-width"), ("dim-width", ""), ("dim-width", True),
    ("dim-width", "dim-height", "unrelated"),
])
def test_untyped_or_ambiguous_figured_dimension_metadata_cannot_mint_firm_area(bad_dim_ids):
    quantity = source_area(_explicit_area(
        25.0, metadata={"figured_dimension_ids": bad_dim_ids},
    ))
    assert quantity.abstained
    assert "explicit_area_figured_receipts_invalid" in quantity.blocking_reasons


@pytest.mark.parametrize("bad_area", [True, False, "25.0", float("nan"), float("inf")])
def test_replayed_untyped_printed_area_does_not_mint_firm_room_metric(bad_area):
    atom = copy(_explicit_area(25.0))
    object.__setattr__(atom, "normalized_value", bad_area)
    quantity = source_area(atom)
    assert quantity.abstained
    assert "explicit_area_invalid" in quantity.blocking_reasons



@pytest.mark.parametrize("bad_confidence", [True, False, "0.95", float("nan"), 1.2, -0.5])
def test_source_explicit_area_with_invalid_confidence_cannot_be_firm(bad_confidence):
    atom = copy(_explicit_area(25.0))
    object.__setattr__(atom, "confidence", bad_confidence)
    quantity = source_area(atom)
    assert quantity.abstained is True
    assert "explicit_area_confidence_invalid" in quantity.blocking_reasons


@pytest.mark.parametrize("bad_confidence", [True, "0.95", float("nan"), -0.1, 1.1])
def test_original_room_geometry_confidence_is_not_a_boolean_or_unbounded_number(bad_confidence):
    room = copy(_room())
    object.__setattr__(room, "geometry_confidence", bad_confidence)
    result = build_room_area_quantity(
        room=room, context=_context(), document=_document(),
        viewport=_viewport(), entity=_entity(), page_no=1,
        explicit_area_evidence=_explicit_area(25.0),
    )
    assert result.abstained is True
    assert "room_area_source_confidence_invalid" in result.blocking_reasons
