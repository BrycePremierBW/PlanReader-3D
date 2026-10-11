"""Q02 ceiling shadow consumers require genuine original room-area evidence."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

import pytest

from tests.test_c15_ceiling_lining_quantity import _area_quantity, _build


def replay(**changes):
    original = copy(_area_quantity())
    for name, value in changes.items():
        object.__setattr__(original, name, value)
    return original


def test_real_source_area_and_explicit_finish_still_generate_only_shadow():
    quantity = _build()
    assert quantity.abstained is False
    assert quantity.status == "provisional"
    assert quantity.metadata["commercial_projection_allowed"] is False
    assert quantity.value == 42.375


@pytest.mark.parametrize("wrong_area", [True, False, "42.375", float("nan"), float("inf")])
def test_untyped_source_metric_does_not_reissue_ceiling_area(wrong_area):
    result = _build(area=replay(value=wrong_area))
    assert result.abstained
    assert result.value is None
    assert "upstream_area_invalid" in result.blocking_reasons


@pytest.mark.parametrize("bad_confidence", [True, "0.99", -0.1, 1.1, float("nan")])
def test_invalid_source_confidence_abstains_without_provisional_measurement(bad_confidence):
    result = _build(area=replay(confidence=bad_confidence))
    assert result.abstained
    assert "upstream_area_confidence_invalid" in result.blocking_reasons


@pytest.mark.parametrize("receipts", [(), ("ev-area", "ev-area"), ("ev-area", ""), ("ev-area", "  ")])
def test_copied_area_must_retain_unique_nonempty_original_source_receipts(receipts):
    result = _build(area=replay(evidence_ids=receipts))
    assert result.abstained
    assert "upstream_area_source_receipts_invalid" in result.blocking_reasons


@pytest.mark.parametrize("page", [True, False, 1.0, None, "1.0", " 1", "1 "])
def test_upstream_area_source_page_must_be_authentic_integer_identifier(page):
    area = _area_quantity()
    result = _build(area=replace(
        area, metadata={**dict(area.metadata), "page_no": page}
    ))
    assert result.abstained
    assert "upstream_area_page_unbound" in result.blocking_reasons


def test_original_integer_page_and_explicit_firm_source_stay_supported():
    area = _area_quantity()
    assert _build(area=area).value == area.value
    string_page = replace(area, metadata={**dict(area.metadata), "page_no": "1"})
    assert _build(area=string_page).value == area.value



@pytest.mark.parametrize("untrusted_method", [
    "model_derived", "ai_detected", "schedule_assumption",
    "quantity_replayed", "inferred_from_room_name",
])
def test_claimed_firm_untrusted_measurement_does_not_feed_shadow_ceiling(untrusted_method):
    result = _build(area=replay(authority=untrusted_method))
    assert result.abstained is True
    assert "upstream_area_measurement_authority_untrusted" in result.blocking_reasons


def test_source_quantity_semantic_owner_must_match_physical_room_scope():
    result = _build(area=replay(semantic_key="room_area:unrelated-physical-room"))
    assert result.abstained is True
    assert "upstream_area_semantic_owner_mismatch" in result.blocking_reasons


@pytest.mark.parametrize("supported", ["documented_dimension", "pdf_scaled", "user_approved"])
def test_admissible_metric_room_area_authorities_remain_provisional_not_commercial(supported):
    result = _build(area=replay(authority=supported))
    assert result.abstained is False
    assert result.value == 42.375
    assert result.metadata["shadow_only"] is True
    assert result.metadata["commercial_projection_allowed"] is False
