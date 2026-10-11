"""GPT1 floor sealing: a positive page-space bbox cannot stand in for a source face."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pb_live_floor_area_quantity_publication import publish_live_floor_area_quantities
from pb_live_floor_area_source_closed_export import build_live_floor_area_source_traces
from pb_source_closed_run_export import SourceClosedRunConflictError
from tests.test_live_floor_area_quantity_publication_integrity import (
    _claim_with, _source_area,
)
from tests.test_live_floor_finish_area_source_closed_export import _floor


@pytest.mark.parametrize("degenerate_polygon", (
    ((10.0, 10.0), (20.0, 20.0), (30.0, 30.0)),
    ((10.0, 10.0), (20.0, 20.0), (10.0, 20.0), (20.0, 10.0)),
))
def test_final_floor_seal_rejects_zero_area_source_face_with_positive_bbox(degenerate_polygon):
    base = _claim_with(_source_area())
    malformed_floor = replace(_floor(), polygon_pdf_pts=degenerate_polygon)
    claim = replace(base, canonical_floors=(malformed_floor,))
    # The upstream metric authority alone is not proof the imported physical
    # floor still retains a closed room-face geometry at final sealing.
    assert len(publish_live_floor_area_quantities(claim)) == 1
    with pytest.raises(SourceClosedRunConflictError, match="degenerate"):
        build_live_floor_area_source_traces(
            claim, workspace_id=1, project_id="source-project",
        )


def test_final_floor_seal_keeps_real_rectangular_source_face_and_figured_area():
    base = _claim_with(_source_area())
    traces = build_live_floor_area_source_traces(
        base, workspace_id=1, project_id="source-project",
    )
    assert len(traces) == 1
    assert next(iter(traces.values())).source_bbox == (10.0, 10.0, 20.0, 20.0)
    assert publish_live_floor_area_quantities(base)[0].value == 8.64
