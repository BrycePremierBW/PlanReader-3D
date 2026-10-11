"""Q03 gross/net wall diagnostics must abstain, not throw, on corrupted m²."""
from __future__ import annotations

from copy import copy

import pytest

from tests.test_wall_net_area_quantity import _build, _complete, _deduction, _gross


def replay(original, **updates):
    item = copy(original)
    for name, value in updates.items():
        object.__setattr__(item, name, value)
    return item


@pytest.mark.parametrize("bad", [True, False, "1.25", 10 ** 400, float("nan"), float("inf")])
def test_invalid_opening_deduction_never_subtracts_a_replayed_metric(bad):
    deduction = replay(_deduction("OP-1", 1.25), value=bad)
    result = _build(deductions=(deduction,), completion=_complete(("OP-1",)))
    assert result.abstained
    assert result.value is None
    assert "opening_deduction_value_invalid" in result.blocking_reasons
    assert "opening_universe_completeness_not_authenticated" in result.blocking_reasons


@pytest.mark.parametrize("bad", [True, False, "12.0", 10 ** 400, float("nan"), float("inf")])
def test_invalid_gross_wall_area_never_mints_positive_net_metric(bad):
    gross = replay(_gross(), value=bad)
    result = _build(
        gross=gross,
        deductions=(_deduction("OP-1", 1.25),),
        completion=_complete(("OP-1",)),
    )
    assert result.abstained
    assert result.value is None
    assert "gross_wall_area_value_invalid" in result.blocking_reasons
    assert "opening_universe_completeness_not_authenticated" in result.blocking_reasons


def test_valid_source_gross_and_opening_deduction_remain_blocked_until_universe_complete():
    result = _build(
        gross=_gross(12.0),
        deductions=(_deduction("OP-1", 1.25),),
        completion=_complete(("OP-1",)),
    )
    assert result.abstained
    assert "gross_wall_area_value_invalid" not in result.blocking_reasons
    assert "opening_deduction_value_invalid" not in result.blocking_reasons
    assert "opening_universe_completeness_not_authenticated" in result.blocking_reasons
