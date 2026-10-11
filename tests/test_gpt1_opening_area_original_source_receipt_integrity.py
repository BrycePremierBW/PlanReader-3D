"""Q04 source-measured opening area must not normalize forged original receipts."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pb_live_opening_area_quantity_publication import _opening_quantity
from tests.test_live_opening_area_quantity_publication import _opening


@pytest.mark.parametrize("bad", [True, False, "2.172", 10 ** 400,
                                  float("nan"), float("inf")])
def test_opening_metric_cannot_publish_boolean_string_or_overflow(bad):
    assert _opening_quantity(replace(_opening(), area_m2=bad)) is None


@pytest.mark.parametrize("receipts", [
    ("figured-1", "figured-1", "host-binding-1", "host-frame-1"),
    ("figured-1", True, "host-binding-1", "host-frame-1"),
    ("figured-1", "  ", "host-binding-1", "host-frame-1"),
    ("figured-1", "host-binding-1", "host-frame-1", "host-frame-1"),
    ("figured-1", "host-binding-1", " host-frame-1"),
])
def test_opening_source_receipts_must_remain_original_typed_and_unique(receipts):
    assert _opening_quantity(replace(_opening(), evidence_ids=receipts)) is None


@pytest.mark.parametrize("field", [
    "canonical_opening_id", "physical_opening_id",
    "document_id", "revision_id", "snapshot_id", "page_id",
    "viewport_id", "host_wall_id", "representative_observation_id",
])
def test_opening_required_physical_source_identity_cannot_be_boolean(field):
    assert _opening_quantity(replace(_opening(), **{field: True})) is None


def test_source_owned_figured_opening_keeps_exact_original_2_172_m2():
    opening = _opening()
    quantity = _opening_quantity(opening)
    assert quantity is not None
    assert quantity.value == 2.172
    assert quantity.metadata["measurement_record_id"] == "figured-1"


def test_real_frame_host_remains_supported_without_optional_binding():
    opening = replace(
        _opening(),
        host_binding_record_id="",
    )
    quantity = _opening_quantity(opening)
    assert quantity is not None
    assert quantity.metadata["host_frame_record_id"] == "host-frame-1"
