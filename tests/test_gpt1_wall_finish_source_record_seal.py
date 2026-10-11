"""Q03: source signed wall finish material/surface/area cannot be replayed."""
from __future__ import annotations

from copy import copy

import pytest

from pb_live_wall_finish_quantity_publication import publish_bound_wall_finish_quantity
from tests.test_live_wall_finish_quantity_publication import _resolved_record_and_surface


def replay(record, **fields):
    changed = copy(record)
    for name, value in fields.items():
        object.__setattr__(changed, name, value)
    return changed


def test_original_source_owned_wall_finish_scope_still_yields_12_5_m2():
    record, surface = _resolved_record_and_surface()
    published = publish_bound_wall_finish_quantity(record)
    assert published.value == 12.5
    assert published.input_entity_ids == (surface.physical_surface_id,)
    assert published.metadata["commercial_projection_allowed"] is True


@pytest.mark.parametrize(("key", "value"), [
    ("record_id", "stale-or-forged-record"),
    ("finish_material", "paint-from-other-source"),
    ("trade_scope_id", "unrelated-coating-scope"),
    ("snapshot_id", "other-revision-snapshot"),
    ("physical_face_ids", ("foreign-physical-face",)),
    ("finish_binding_ids", ("foreign-source-binding",)),
    ("net_wall_record_ids", ("foreign-net-wall",)),
    ("finish_scope_record_id", "foreign-finish-scope"),
    ("quantity_m2", 11.75),
])
def test_replayed_area_finish_or_source_receipts_cannot_inherit_old_seal(key, value):
    record, _ = _resolved_record_and_surface()
    with pytest.raises(ValueError, match="record seal mismatch"):
        publish_bound_wall_finish_quantity(replay(record, **{key: value}))


@pytest.mark.parametrize(("key", "value"), [
    ("quantity_m2", True), ("quantity_m2", float("nan")),
    ("quantity_m2", float("inf")), ("quantity_m2", "12.5"),
    ("physical_face_ids", ("one-face", "one-face")),
    ("physical_surface_ids", ("one-surface", "one-surface")),
    ("finish_binding_ids", ("duplicate-binding", "duplicate-binding")),
    ("net_wall_record_ids", ("duplicate-net", "duplicate-net")),
    ("source_sha256", "bad-source-sha"),
    ("decision_scope_id", ""),
    ("viewport_id", ""),
])
def test_malformed_source_receipts_fail_before_qty_id_generation(key, value):
    record, _ = _resolved_record_and_surface()
    with pytest.raises(ValueError, match="receipts or area are invalid"):
        publish_bound_wall_finish_quantity(replay(record, **{key: value}))
