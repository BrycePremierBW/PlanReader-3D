"""Diagnostic-only tests: the metric floor counter must not invent m².

These are reporting checks, not a source/metric authority replacement.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tools.diag_lot16_room_face_scope import _has_firm_metric_floor_receipt
from pb_geometry_takeoff_model import MeasurementAuthorityType


def _floor(**overrides):
    fields = {
        "metric_area_m2": 8.64,
        "metric_area_quantity_id": "source-room-area-q1",
        "metric_area_authority": MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        "geometry_complete": True,
        "metric_geometry_complete": False,
        "source_room_face_record_id": "face-1",
        "evidence_ids": ("source-dimension-h", "source-dimension-v"),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_valid_documented_area_is_counted_without_physical_scale() -> None:
    # A figured-dimension metric area may be valid without scaled geometry.
    assert _has_firm_metric_floor_receipt(_floor())


@pytest.mark.parametrize("bad_value", (None, 0.0, -1.0, float("nan"), float("inf"), "not-an-area"))
def test_unmeasured_or_invalid_floor_area_is_not_counted(bad_value) -> None:
    assert not _has_firm_metric_floor_receipt(_floor(metric_area_m2=bad_value))


@pytest.mark.parametrize("missing", ("metric_area_quantity_id", "metric_area_authority"))
def test_missing_metric_source_receipt_is_not_counted(missing: str) -> None:
    assert not _has_firm_metric_floor_receipt(_floor(**{missing: ""}))


def test_unscaled_geometry_without_metric_area_never_counts() -> None:
    assert not _has_firm_metric_floor_receipt(
        _floor(
            metric_area_m2=None,
            metric_area_quantity_id=None,
            metric_area_authority=None,
            geometry_complete=True,
            metric_geometry_complete=False,
        )
    )
