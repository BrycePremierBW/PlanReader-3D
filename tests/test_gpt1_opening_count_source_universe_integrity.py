"""Source-owned opening count universes cannot be made complete by ID dedup."""
from __future__ import annotations

import pytest

from pb_live_opening_count_quantity_publication import (
    _authentic_source_id_universe,
)
from pb_live_physical_net_wall_integration import collect_live_physical_net_wall_claim
from tests.test_live_opening_count_quantity_publication import (
    _floor_plan_with_schedule_quantity,
)


@pytest.mark.parametrize("invalid", [
    (), [], None, "", "observation-1", ("source-1", "source-1"),
    ("source-1", ""), ("source-1", " "), ("source-1", True),
    ("source-1", 2), (" source-1",), ("source-1 ",),
])
def test_count_universe_never_silently_sanitizes_original_observation_ids(invalid):
    assert _authentic_source_id_universe(invalid) is False


@pytest.mark.parametrize("authentic", [
    ("source-1",), ["source-1", "source-2"],
    ("source-1", "source-2", "source-3"),
])
def test_distinct_typed_original_observation_members_remain_valid(authentic):
    assert _authentic_source_id_universe(authentic) is True


def test_original_explicit_schedule_count_still_reaches_canonical_quantity(tmp_path):
    path = tmp_path / "explicit-count-original-source.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    assert len(claim.canonical_openings) == 1
    assert len(claim.opening_count_quantity_evidence) == 1
    quantity = claim.opening_count_quantity_evidence[0]
    assert quantity.value == 1.0
    assert quantity.input_entity_ids == (claim.canonical_openings[0].canonical_opening_id,)
    assert quantity.metadata["schedule_corroborated"] is True


def test_missing_explicit_schedule_quantity_still_means_abstain(tmp_path):
    path = tmp_path / "opening-without-quantity.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=None))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    assert claim.opening_count_quantity_evidence == ()
