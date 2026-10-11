"""GPT1: authoritative slab quantities require intact metric source geometry."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pb_live_canonical_slab_projection import (
    LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH,
    project_resolved_slab_entity,
)
from pb_live_slab_area_quantity_publication import publish_live_slab_area_quantity
from tests.test_live_canonical_slab_projection import _boundary, _lineage, _resolved_slab


def original_slab():
    source = project_resolved_slab_entity(
        slab=_resolved_slab(), boundary=_boundary(), **_lineage(),
    )
    assert source.object is not None
    return source.object


def test_original_source_metric_slab_still_produces_48_square_metres():
    source = original_slab()
    quantity = publish_live_slab_area_quantity(source)
    assert quantity is not None
    assert quantity.value == 48.0
    assert quantity.input_entity_ids == (source.physical_slab_id,)
    assert quantity.metadata["commercial_projection_allowed"] is False


@pytest.mark.parametrize("wrong_area", [47.0, 49.0, True, float("nan"), float("inf")])
def test_canonical_producer_rejects_area_that_disagrees_with_metric_polygon(wrong_area):
    result = project_resolved_slab_entity(
        slab=_resolved_slab(area_m2=wrong_area),
        boundary=_boundary(area_m2=wrong_area),
        **_lineage(),
    )
    assert result.object is None
    assert LIVE_CANONICAL_SLAB_BOUNDARY_MISMATCH in result.reason_codes


@pytest.mark.parametrize("wrong_area", [47.0, 49.0, True, float("nan"), float("inf")])
def test_quantity_boundary_rejects_replayed_metric_value(wrong_area):
    slab = replace(original_slab(), area_m2=wrong_area)
    assert publish_live_slab_area_quantity(slab) is None


@pytest.mark.parametrize("wrong_space", ["source_page_points", "mm", "", None])
def test_quantity_never_treats_nonmetre_coordinates_as_square_metres(wrong_space):
    assert publish_live_slab_area_quantity(
        replace(original_slab(), coordinate_space=wrong_space)
    ) is None


def test_quantity_rejects_changed_polygon_with_same_area_and_old_identity():
    slab = original_slab()
    # 8 x 6 rectangle moved across the source page: area remains 48 but
    # a different physical boundary cannot inherit the original ID.
    moved = tuple((x + 1.0, y) for x, y in slab.polygon_m)
    assert publish_live_slab_area_quantity(
        replace(slab, polygon_m=moved)
    ) is None


@pytest.mark.parametrize("bad_page", [True, -1, "1", None])
def test_quantity_rejects_untyped_or_negative_source_page(bad_page):
    assert publish_live_slab_area_quantity(
        replace(original_slab(), source_page=bad_page)
    ) is None


@pytest.mark.parametrize("bad_sha", ["A" * 64, "bad", " " + ("a" * 64)])
def test_quantity_rejects_uncanonical_original_source_sha(bad_sha):
    assert publish_live_slab_area_quantity(
        replace(original_slab(), source_sha256=bad_sha)
    ) is None


@pytest.mark.parametrize(("key", "value"), [
    ("boundary_id", "replayed-boundary"),
    ("boundary_id", True),
    ("annotation_source_page", 7),
    ("annotation_source_page", True),
    ("annotation_id", False),
    ("dimension_evidence_id", 22),
])
def test_quantity_rejects_tampered_source_provenance_receipt(key, value):
    slab = original_slab()
    forged = replace(slab, provenance={**slab.provenance, key: value})
    assert publish_live_slab_area_quantity(forged) is None


def test_equivalent_polygon_start_vertex_preserves_source_quantity():
    slab = original_slab()
    rotated = slab.polygon_m[1:] + slab.polygon_m[:1]
    changed = replace(slab, polygon_m=rotated)
    # Physical ID is invariant to the cyclic order of genuine source vertices.
    qty = publish_live_slab_area_quantity(changed)
    assert qty is not None
    assert qty.value == 48.0
