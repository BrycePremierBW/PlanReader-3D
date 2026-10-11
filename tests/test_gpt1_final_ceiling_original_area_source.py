"""Q02 final ceiling authority rejects source replay before commercial sealing."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

import pytest

from pb_live_ceiling_area_quantity_publication import publish_live_ceiling_area_quantities
from tests.test_live_ceiling_area_quantity_publication import _result, _ceiling, _shadow_quantity


def source_replay(**fields):
    source = copy(_shadow_quantity())
    for key, val in fields.items():
        object.__setattr__(source, key, val)
    return source


@pytest.mark.parametrize("value", [True, False, "13.270425", 10 ** 400,
                                   float("nan"), float("inf")])
def test_imported_untyped_upstream_shadow_area_cannot_make_firm_ceiling(value):
    assert publish_live_ceiling_area_quantities(
        _result(shadow=source_replay(value=value))
    ) == ()


@pytest.mark.parametrize("value", [True, False, "13.270425", 10 ** 400,
                                   float("nan"), float("inf")])
def test_imported_canonical_ceiling_area_cannot_mint_firm_meter_measurement(value):
    candidate = copy(_ceiling())
    object.__setattr__(candidate, "area_m2", value)
    assert publish_live_ceiling_area_quantities(_result(ceiling=candidate)) == ()


@pytest.mark.parametrize("value", [True, "0.98", float("nan"), -0.1, 1.1, 10 ** 400])
def test_invalid_original_ceiling_source_confidence_abstains(value):
    assert publish_live_ceiling_area_quantities(
        _result(shadow=source_replay(confidence=value))
    ) == ()


@pytest.mark.parametrize("receipts", [
    ("ev-finish", "ev-finish"),
    ("ev-dim-h", True, "ev-finish"),
    ("ev-dim-h", "", "ev-finish"),
    ("ev-dim-h", " ev-dim-v", "ev-finish"),
])
def test_final_ceiling_area_does_not_sanitize_original_source_receipts(receipts):
    assert publish_live_ceiling_area_quantities(
        _result(shadow=source_replay(evidence_ids=receipts))
    ) == ()


@pytest.mark.parametrize("ids", [
    ("dim-h", "dim-v", "unrelated-third-dimension"),
    ("dim-h", " dim-v"),
    ("dim-h", "dim-v "),
])
def test_documented_ceiling_area_needs_exact_two_original_dimensional_owners(ids):
    assert publish_live_ceiling_area_quantities(
        _result(ceiling=replace(_ceiling(), figured_dimension_ids=ids))
    ) == ()


def test_legitimate_two_dimensional_receipts_preserve_firm_ceiling_and_identity():
    result = publish_live_ceiling_area_quantities(_result())
    assert len(result) == 1
    assert result[0].value == 13.270425
    assert result[0].metadata["figured_dimension_ids"] == ("dim-h", "dim-v")
