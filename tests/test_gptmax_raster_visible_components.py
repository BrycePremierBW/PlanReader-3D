"""Original detector losses are negative receipts, never source host authority."""
from copy import deepcopy
from hashlib import sha256

import cv2
import fitz
import numpy as np
import pytest

import pb_raster_visible_segment_detector as detector
from tools.diag_gptmax_raster_visible_components import (
    nonpublishing_component_receipts,
    observe_original_detector_components,
    original_source_component_census,
)


def receipts(stats, orientation="horizontal", minimum=8):
    return nonpublishing_component_receipts(stats, orientation=orientation, min_line_px=minimum)


def test_retains_every_existing_failure_without_centerline_or_host_promotion():
    stats = [[2, 3, 5, 4, 0], [10, 30, 30, 2, 60]]
    before = deepcopy(stats)
    rows = receipts(stats)
    assert stats == before
    assert rows[0]["existing_rejection_reasons"] == ["nonpositive_component_area",
        "component_along_length_below_existing_minimum", "component_aspect_below_existing_minimum"]
    assert not rows[0]["component_passes_existing_pre_snap_filter"]
    assert rows[1]["component_passes_existing_pre_snap_filter"]
    for row in rows:
        assert not row["source_ownership_proven"]
        assert not row["host_publication_allowed"]
        assert "centerline" not in row


def test_existing_aspect_boundary_is_inclusive_and_transposes_with_orientation():
    horizontal = receipts([[4, 7, 12, 4, 48]])[0]
    vertical = receipts([[7, 4, 4, 12, 48]], "vertical")[0]
    assert horizontal["component_passes_existing_pre_snap_filter"]
    assert vertical["component_passes_existing_pre_snap_filter"]
    assert receipts([[4, 7, 11, 4, 44]])[0]["existing_rejection_reasons"] == ["component_aspect_below_existing_minimum"]
    assert receipts([[7, 4, 4, 11, 44]], "vertical")[0]["existing_rejection_reasons"] == ["component_aspect_below_existing_minimum"]


def test_integer_pixel_scale_preserves_existing_dimensionless_decisions():
    stats = [[5, 6, 30, 2, 60], [50, 30, 5, 4, 20]]
    ordinary = receipts(stats)
    scaled = receipts([[2*x, 2*y, 2*w, 2*h, 4*area] for x, y, w, h, area in stats], minimum=16)
    assert [r["existing_rejection_reasons"] for r in ordinary] == [r["existing_rejection_reasons"] for r in scaled]


def test_invalid_orientation_never_defaults_to_a_source_axis():
    with pytest.raises(ValueError, match="orientation"):
        receipts([], orientation="diagonal")


def test_replay_permutation_translation_and_unrelated_component_do_not_change_decisions():
    stats = [[5, 6, 30, 2, 60], [50, 30, 5, 4, 20]]
    ordinary = receipts(stats)
    assert receipts(list(reversed(stats))) == ordinary == receipts(stats)
    translated = receipts([[x+100, y+200, w, h, area] for x, y, w, h, area in stats])
    for old, new in zip(ordinary, translated):
        assert old["existing_rejection_reasons"] == new["existing_rejection_reasons"]
        assert new["pixel_bbox"] == [old["pixel_bbox"][0]+100, old["pixel_bbox"][1]+200,
                                     old["pixel_bbox"][2]+100, old["pixel_bbox"][3]+200]
    assert receipts(stats + [[500, 800, 50, 1, 50]])[:2] == ordinary


@pytest.mark.parametrize("stats", [None, "stats", [[False, 0, 10, 1, 10]],
    [[0., 0, 10, 1, 10]], [[0, 0, 10, 1, float("inf")]], [[0, 0, 10, 1]],
    [[-1, 0, 10, 1, 10]], [[0, 0, 0, 1, 0]], [[0, 0, 10, 1, -1]],
    [[0, 0, 10, 1, 11]], [[0, 0, 10, 1, 10]] * 2])
def test_malformed_or_duplicate_component_inventory_fails_closed(stats):
    with pytest.raises(ValueError):
        receipts(stats)


@pytest.mark.parametrize("minimum", [True, 0, -1, 8., "8"])
def test_malformed_minimum_never_changes_original_predicate(minimum):
    with pytest.raises(ValueError, match="minimum"):
        receipts([], minimum=minimum)


def test_over_limit_component_inventory_abstains_without_changing_producer_limit(monkeypatch):
    import tools.diag_gptmax_raster_visible_components as tool
    monkeypatch.setattr(tool, "MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS", 1)
    with pytest.raises(ValueError, match="over-limit"):
        receipts([[0, 0, 10, 1, 10], [20, 0, 10, 1, 10]])


def png():
    pixels = np.full((160, 200), 255, np.uint8)
    pixels[20:22, 20:100] = 0
    pixels[50:65, 60:100] = 0
    pixels[80:140, 150:152] = 0
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    return encoded.tobytes()


def test_actual_component_observer_preserves_original_detector_output_and_function():
    data = png()
    original = detector._component_segments
    before = detector.detect_axis_aligned_raster_segments(data)
    actual, rows = observe_original_detector_components(data)
    assert actual == before
    assert detector._component_segments is original
    assert rows
    assert any(r["existing_rejection_reasons"] for r in rows)
    assert any(r["component_passes_existing_pre_snap_filter"] for r in rows)
    assert observe_original_detector_components(data) == (actual, rows)


def test_observer_restores_original_function_on_receipt_failure(monkeypatch):
    import tools.diag_gptmax_raster_visible_components as tool
    original = detector._component_segments
    monkeypatch.setattr(tool, "MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS", 0)
    with pytest.raises(ValueError, match="over-limit"):
        observe_original_detector_components(png())
    assert detector._component_segments is original


def test_empty_detection_is_not_complete_source_or_host_evidence():
    assert observe_original_detector_components(b"not-png") == ((), [])


def pdf():
    doc = fitz.open()
    page = doc.new_page(width=150, height=150)
    page.draw_line((20, 20), (100, 20))
    data = doc.tobytes()
    doc.close()
    return data


def test_original_pdf_cli_seam_owns_render_and_retains_nonpublishing_scope():
    data = pdf()
    result = original_source_component_census(data, page_id="1", expected_source_sha=sha256(data).hexdigest())
    assert result["source_sha256"] == sha256(data).hexdigest()
    assert result["page_id"] == "1"
    assert result["native_page_parent_observation_id"]
    assert result["original_source_render_reauthenticated"]
    assert result["original_detector_output_unchanged"]
    assert result["render_dpi"] == 144
    assert result["primitive_safety_cap"] == 20000
    for key in ("source_universe_completeness_proven", "source_ownership_proven",
                "physical_equivalence_proven", "host_publication_allowed",
                "opening_count_publication_allowed", "metric_quantity_publication_allowed"):
        assert result[key] is False
    assert result["benchmark_accuracy"] is None


def test_foreign_pdf_hash_rejected_before_original_source_ingest():
    with pytest.raises(ValueError, match="PDF SHA mismatch"):
        original_source_component_census(b"not-pdf", page_id="1", expected_source_sha="foreign")


@pytest.mark.parametrize("page", [0, "0", "-1", "foreign", None])
def test_invalid_original_page_cannot_change_render_scope(page):
    data = pdf()
    with pytest.raises(ValueError, match="source page"):
        original_source_component_census(data, page_id=page, expected_source_sha=sha256(data).hexdigest())
