"""GPT1 Q05 original room-area source traces cannot seal a zero-area floor face."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pb_live_room_area_source_closed_export import build_live_room_area_source_traces
from pb_source_closed_run_export import SourceClosedRunConflictError
from tests.test_live_floor_area_quantity_publication_integrity import (
    _claim_with_canonical_room, _source_area,
)


def _claim_with_polygon(polygon):
    claim = _claim_with_canonical_room(_source_area())
    return replace(
        claim,
        canonical_floors=(
            replace(claim.canonical_floors[0], polygon_pdf_pts=polygon),
        ),
    )


@pytest.mark.parametrize("unclosed", (
    ((0.0, 0.0), (3.0, 3.0), (6.0, 6.0)),
    ((0.0, 0.0), (5.0, 5.0), (0.0, 5.0), (5.0, 0.0)),
))
def test_original_room_area_cannot_seal_polygon_with_no_enclosed_face(unclosed):
    with pytest.raises(SourceClosedRunConflictError, match="degenerate"):
        build_live_room_area_source_traces(
            _claim_with_polygon(unclosed),
            workspace_id=1, project_id="source-project",
        )


def test_original_source_room_area_keeps_complete_floor_bbox():
    claim = _claim_with_canonical_room(_source_area())
    trace = build_live_room_area_source_traces(
        claim, workspace_id=1, project_id="source-project",
    )
    assert len(trace) == 1
    assert next(iter(trace.values())).source_bbox == (10.0, 10.0, 20.0, 20.0)
