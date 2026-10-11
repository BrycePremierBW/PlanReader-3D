"""GPT1 Q01: physical canonical floor metric enrichment consumes unmodified source m²."""
from __future__ import annotations

from copy import copy
from types import SimpleNamespace

import pytest

from pb_live_canonical_floor_surface import _valid_metric_area_quantity
from pb_migration_contracts import EvidenceResolutionStatus
from tests.test_live_floor_area_quantity_publication_integrity import _source_area
from tests.test_live_floor_finish_area_source_closed_export import _floor


def _source_entity():
    return SimpleNamespace(
        candidate_entity_id="source-room-1",
        evidence_ids=("face-1", "ev-room", "ev-area"),
        status=EvidenceResolutionStatus.CORROBORATED,
        metadata={"source_sha256": "a" * 64, "revision_id": "rev-1", "page_id": "1"},
    )


def _replay(quantity, **fields):
    altered = copy(quantity)
    for name, value in fields.items():
        object.__setattr__(altered, name, value)
    return altered


def test_real_documented_m2_can_enrich_unscaled_canonical_floor():
    assert _valid_metric_area_quantity(
        _floor(), _source_area(), source_room_entity=_source_entity()
    )


@pytest.mark.parametrize("bad", [True, False, "8.64", float("nan"), float("inf"), 10 ** 400])
def test_tampered_area_cannot_enrich_canonical_floor(bad):
    assert not _valid_metric_area_quantity(
        _floor(), _replay(_source_area(), value=bad),
        source_room_entity=_source_entity(),
    )


@pytest.mark.parametrize("bad", [True, "0.99", float("nan"), -0.1, 1.1, 10 ** 400])
def test_invalid_original_source_confidence_cannot_become_metric_floor(bad):
    assert not _valid_metric_area_quantity(
        _floor(), _replay(_source_area(), confidence=bad),
        source_room_entity=_source_entity(),
    )


@pytest.mark.parametrize("bad", [(), ("ev-room", "ev-room"),
                                  ("ev-room", "  "), ("ev-room", True),
                                  (" ev-room", "ev-area")])
def test_duplicate_or_coerced_source_evidence_cannot_enrich_floor(bad):
    assert not _valid_metric_area_quantity(
        _floor(), _replay(_source_area(), evidence_ids=bad),
        source_room_entity=_source_entity(),
    )
