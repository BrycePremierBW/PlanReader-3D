"""Q03: never derive FIRM wall area from foreign or untyped dimension claims."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

import pytest

from tests.test_wall_gross_area_quantity import _gross, _height, _length


def altered_quantity(original, **fields):
    # Replaying imported serialized evidence can bypass dataclass validation.
    # Test the final multiplication boundary, not just constructor guards.
    changed = copy(original)
    for key, value in fields.items():
        object.__setattr__(changed, key, value)
    return changed


def test_producer_owned_length_and_height_remain_12_square_metres():
    result = _gross()
    assert result.abstained is False
    assert result.value == 12.0


@pytest.mark.parametrize("which", ["length", "height"])
def test_foreign_semantic_wall_identity_cannot_mint_area(which):
    value = (altered_quantity(_length(), semantic_key="wall_length:FOREIGN")
             if which == "length" else
             altered_quantity(_height(), semantic_key="wall_height:FOREIGN"))
    result = (_gross(length=value) if which == "length" else _gross(height=value))
    assert result.abstained
    assert f"wall_{which}_semantic_identity_mismatch" in result.blocking_reasons


def test_two_different_dimensions_cannot_replay_same_quantity_identity():
    stolen_id = altered_quantity(_height(), quantity_id=_length().quantity_id)
    result = _gross(height=stolen_id)
    assert result.abstained
    assert "wall_dimension_quantity_identity_collision" in result.blocking_reasons


@pytest.mark.parametrize("which", ["length", "height"])
@pytest.mark.parametrize("invalid", [True, False, "3.0", float("nan"), float("inf")])
def test_replayed_untyped_or_nonfinite_dimension_values_are_not_source_metres(which, invalid):
    q = altered_quantity(_length() if which == "length" else _height(), value=invalid)
    result = _gross(**{which: q})
    assert result.abstained
    assert f"wall_{which}_value_invalid" in result.blocking_reasons


@pytest.mark.parametrize("which", ["length", "height"])
@pytest.mark.parametrize("evidence", [(), ("ev", "ev"), ("ev", ""), ("ev", True)])
def test_source_dimension_receipts_are_neither_missing_nor_coerced(which, evidence):
    q = altered_quantity(_length() if which == "length" else _height(), evidence_ids=evidence)
    result = _gross(**{which: q})
    assert result.abstained
    assert f"wall_{which}_source_receipts_invalid" in result.blocking_reasons


@pytest.mark.parametrize("which", ["length", "height"])
@pytest.mark.parametrize("confidence", [True, "0.95", float("nan"), 1.1])
def test_replayed_untyped_confidence_never_authorizes_area(which, confidence):
    q = altered_quantity(_length() if which == "length" else _height(), confidence=confidence)
    result = _gross(**{which: q})
    assert result.abstained
    assert f"wall_{which}_confidence_invalid" in result.blocking_reasons
