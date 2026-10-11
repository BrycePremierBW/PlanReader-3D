"""Original detector receipts cannot promote mask pixels into physical hosts."""
from hashlib import sha256
import sys

import cv2
import fitz
import numpy as np
import pytest

import pb_raster_visible_segment_detector as detector
from pb_migration_contracts import EvidenceResolutionStatus
from tools.diag_gptmax_raster_detector_dispositions import observe_detector_dispositions


def png(pixels):
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    return encoded.tobytes()


def line_image():
    image = np.full((100, 160), 255, np.uint8)
    image[30:32, 20:130] = 0
    return image


@pytest.mark.parametrize("inverse", [False, True])
def test_actual_foreground_polarity_preserves_original_output(inverse):
    pixels = line_image()
    if inverse:
        pixels = 255-pixels
    data = png(pixels)
    original = detector.detect_axis_aligned_raster_segments(data)
    result = observe_detector_dispositions(data)
    assert result["original_detector_output_unchanged"]
    assert result["foreground"]["selected_polarity"] == ("light" if inverse else "dark")
    assert result["foreground"]["foreground_area_px"] == 220
    assert result["render_sha256"] == sha256(data).hexdigest()
    assert result["observed_original_segment_count"] == len(original)
    assert result["evidence_resolution_status"] == EvidenceResolutionStatus.ABSTAINED.value
    assert not result["host_publication_allowed"]


def test_invalid_png_and_uniform_page_are_separate_unavailable_receipts():
    bad = observe_detector_dispositions(b"not-png")
    white = observe_detector_dispositions(png(np.full((40, 50), 255, np.uint8)))
    assert bad["first_observed_failure"] == "raster_png_decode_unavailable"
    assert white["first_observed_failure"] == "original_foreground_mask_unavailable"
    assert bad["observed_original_segment_count"] == white["observed_original_segment_count"] == 0
    assert not bad["source_universe_completeness_proven"]
    assert not white["source_universe_completeness_proven"]


def test_existing_trace_is_refused_and_preserved():
    def existing(frame, event, arg):
        return existing
    sys.settrace(existing)
    try:
        with pytest.raises(ValueError, match="existing Python trace"):
            observe_detector_dispositions(png(line_image()))
        assert sys.gettrace() is existing
    finally:
        sys.settrace(None)


def test_observer_restores_trace_after_exception(monkeypatch):
    def invalid(_gray):
        raise RuntimeError("unrelated original producer failure")
    monkeypatch.setattr(detector, "_foreground_mask", invalid)
    with pytest.raises(RuntimeError, match="unrelated"):
        observe_detector_dispositions(png(line_image()))
    assert sys.gettrace() is None


@pytest.mark.parametrize("data", [None, "png", [1,2]])
def test_png_bytes_are_never_coerced(data):
    with pytest.raises(TypeError):
        observe_detector_dispositions(data)


def test_component_receipts_retain_actual_pixels_and_original_rejections():
    pixels = line_image()
    pixels[50:65, 60:100] = 0
    before = pixels.copy()
    data = png(pixels)
    result = observe_detector_dispositions(data)
    rows = result["component_receipts"]
    assert np.array_equal(pixels, before)
    rejected = [r for r in rows if r["existing_rejection_reasons"]]
    accepted = [r for r in rows if r["original_component_line_px"] is not None]
    assert rejected and accepted
    assert all(r["component_pixel_sha256"] for r in rows)
    assert all(r["original_mask_sha256"] for r in rows)
    assert all(not r["source_ownership_proven"] for r in rows)
    assert any("component_aspect_below_existing_minimum" in r["existing_rejection_reasons"] for r in rejected)
    assert rows == observe_detector_dispositions(data)["component_receipts"]
    assert len({r["component_id"] for r in rows}) == len(rows)


def test_component_axis_transpose_retains_original_filter_decisions():
    a = observe_detector_dispositions(png(line_image()))["component_receipts"]
    b = observe_detector_dispositions(png(line_image().T.copy()))["component_receipts"]
    assert len(a) == len(b)
    assert sorted(r["foreground_area_px"] for r in a) == sorted(r["foreground_area_px"] for r in b)
    assert sorted(r["existing_rejection_reasons"] for r in a) == sorted(r["existing_rejection_reasons"] for r in b)


def test_component_cap_failure_restores_trace(monkeypatch):
    import tools.diag_gptmax_raster_detector_dispositions as tool
    monkeypatch.setattr(tool, "MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS", 0)
    with pytest.raises(ValueError, match="over-limit"):
        observe_detector_dispositions(png(line_image()))
    assert sys.gettrace() is None


def test_dedupe_retains_every_original_parent_without_equivalence_promotion():
    from tools.diag_gptmax_raster_detector_dispositions import _dedupe_receipt
    inputs = [(1., 3., 8., 3.), (1.0001, 3., 8., 3.), (20., 30., 40., 30.)]
    before = list(inputs)
    row = _dedupe_receipt(inputs, detector._dedupe(inputs))
    assert inputs == before
    assert row["groups"][0]["input_indices"] == [0,1]
    assert row["groups"][0]["coalescence_observed"]
    assert row["groups"][0]["rounding_observed"]
    assert not row["groups"][0]["physical_equivalence_proven"]
    reversed_row = _dedupe_receipt(list(reversed(inputs)), detector._dedupe(reversed(inputs)))
    assert reversed_row["output_lines_px"] == row["output_lines_px"]
    assert sorted(i for g in reversed_row["groups"] for i in g["input_indices"]) == [0,1,2]


@pytest.mark.parametrize("inputs,outputs", [([("1", 2., 8., 2.)], []),
    ([(True, 2., 8., 2.)], []), ([(1., 2., float("inf"), 2.)], []),
    ([(1., 2., 8., 2.)], []), ([(1., 2., 8., 2.)], [(0., 2., 8., 2.)]),
    ([], [(1.,2.,8.,2.)]), (None, []), ([], None)])
def test_dedupe_malformed_or_missing_parent_receipts_fail_closed(inputs, outputs):
    from tools.diag_gptmax_raster_detector_dispositions import _dedupe_receipt
    with pytest.raises(ValueError):
        _dedupe_receipt(inputs, outputs)


def test_actual_detector_records_all_four_original_dedupe_calls():
    result = observe_detector_dispositions(png(line_image()))
    assert len(result["original_dedupe_calls"]) == 4
    for call in result["original_dedupe_calls"]:
        assert sorted(i for g in call["groups"] for i in g["input_indices"]) == list(range(len(call["input_lines_px"])))


def test_actual_snap_receipts_preserve_collapsed_input_instead_of_claiming_a_host():
    from tools.diag_gptmax_raster_detector_dispositions import observe_original_snap_passes
    horizontal = [(10.,20.,20.,20.)]
    vertical = [(float(x),10.,float(x),50.) for x in range(10,21,2)]
    before = list(horizontal), list(vertical)
    result = observe_original_snap_passes(horizontal, vertical, tolerance_px=2.)
    assert (horizontal, vertical) == before
    assert result["original_snap_outputs"]["horizontal"] == []
    lost = [r for r in result["original_snap_pass_receipts"] if not r["kept_in_original_pass"]]
    assert lost and lost[0]["input_line_px"] == list(horizontal[0])
    assert lost[0]["output_line_px"] == [20.,20.,20.,20.]
    assert not result["host_publication_allowed"]
    assert not result["source_scope_authenticated"]
    permuted = observe_original_snap_passes(horizontal, list(reversed(vertical)), tolerance_px=2.)
    assert result["original_snap_outputs"] == permuted["original_snap_outputs"]
    assert result["original_snap_pass_receipts"] == permuted["original_snap_pass_receipts"]
    assert permuted["original_dedupe_calls"][1]["input_lines_px"] == [list(x) for x in reversed(vertical)]


def test_snap_passes_transpose_translate_and_retain_actual_original_endpoint_moves():
    from tools.diag_gptmax_raster_detector_dispositions import observe_original_snap_passes
    h, v = [(10.,20.,30.,20.)], [(11.,10.,11.,40.)]
    result = observe_original_snap_passes(h,v,tolerance_px=2.)
    assert result["original_snap_outputs"]["horizontal"] == [[11.,20.,30.,20.]]
    translated = observe_original_snap_passes([(x+100,y+200,x2+100,y2+200) for x,y,x2,y2 in h],
        [(x+100,y+200,x2+100,y2+200) for x,y,x2,y2 in v], tolerance_px=2.)
    assert translated["original_snap_outputs"]["horizontal"] == [[111.,220.,130.,220.]]
    swapped = observe_original_snap_passes([(10.,11.,40.,11.)],[(20.,10.,20.,30.)],tolerance_px=2.)
    assert swapped["original_snap_outputs"]["vertical"] == [[20.,11.,20.,30.]]


def test_actual_png_loss_has_complete_three_pass_receipts():
    pixels = np.full((80,80),255,np.uint8)
    pixels[20,10:21] = 0
    for x in range(10,21,2):
        pixels[10:51,x] = 0
    result = observe_detector_dispositions(png(pixels))
    assert result["original_detector_output_unchanged"]
    assert any(not r["kept_in_original_pass"] for r in result["original_snap_pass_receipts"])
    assert result["original_snap_inputs"]["tolerance_px"] == 2.


def test_unknown_snap_function_structure_abstains_before_tracing(monkeypatch):
    monkeypatch.setattr(detector, "_snap_intersections", lambda h,v,**kw:(h,v))
    with pytest.raises(ValueError, match="original snap loop structure"):
        observe_detector_dispositions(png(line_image()))
    assert sys.gettrace() is None


@pytest.mark.parametrize("width,retained", [(8,False),(9,True),(10,True)])
def test_original_post_snap_length_boundary_has_exact_component_ancestry(width, retained):
    pixels = np.full((80,80),255,np.uint8)
    pixels[30,20:20+width] = 0
    result = observe_detector_dispositions(png(pixels))
    rows = result["original_post_snap_length_receipts"]
    assert len(rows) == 1
    assert rows[0]["minimum_length_rejected"] is (not retained)
    assert rows[0]["original_minimum_length_pt"] == detector._MIN_LINE_LENGTH_PT == 4.
    assert rows[0]["component_parent_ids"]
    assert rows[0]["source_primitive_ref"] is None
    component = result["component_receipts"][0]
    assert component["component_id"] in rows[0]["component_parent_ids"]
    assert bool(component["final_detector_output_indices"]) is retained
    assert ("original_post_snap_minimum_length" in component["observed_loss_stages"]) is (not retained)
    assert result["observed_original_segment_count"] == int(retained)


def test_every_final_detector_index_has_all_actual_pixel_component_parents():
    result = observe_detector_dispositions(png(line_image()))
    final = [r for r in result["original_post_snap_length_receipts"] if not r["minimum_length_rejected"]]
    assert sorted(r["final_detector_output_index"] for r in final) == list(range(result["observed_original_segment_count"]))
    components = {r["component_id"]:r for r in result["component_receipts"]}
    for row in final:
        for cid in row["component_parent_ids"]:
            assert row["final_detector_output_index"] in components[cid]["final_detector_output_indices"]


def test_dedupe_lineage_keeps_all_exact_indices_and_rejects_missing_parent():
    from tools.diag_gptmax_raster_detector_dispositions import _dedupe_receipt, _dedupe_parent_lists
    inputs = [(1.,2.,8.,2.),(1.0001,2.,8.,2.)]
    call = _dedupe_receipt(inputs,detector._dedupe(inputs))
    assert _dedupe_parent_lists(call,[{"component_a"},{"component_b"}]) == [{"component_a","component_b"}]
    assert call["groups"][0]["component_parent_ids"] == ["component_a","component_b"]
    with pytest.raises(ValueError,match="index inventory"):
        _dedupe_parent_lists(call,[{"component_a"}])
    with pytest.raises(ValueError,match="lacks pixel"):
        _dedupe_parent_lists(call,[{"component_a"},set()])


def test_component_bbox_overlap_does_not_fabricate_pixel_intersection():
    pixels = np.full((100,100),255,np.uint8)
    pixels[20:60,20:25] = 0
    pixels[20:60,45:50] = 0
    pixels[20:30,20:50] = 0
    data = png(pixels)
    result = observe_detector_dispositions(data,queries=[{"query_id":"empty_inside_bbox",
        "render_bbox_pt":[15.,18.,19.,26.]}])
    query = result["pixel_query_receipts"][0]
    hits = query["bbox_intersecting_components"]
    assert hits
    assert any(r["bbox_intersection_observed"] and r["actual_component_pixels_in_query"] == 0 for r in hits)
    assert all(r["actual_pixel_center_bbox"] is None for r in hits if r["actual_component_pixels_in_query"] == 0)
    assert not query["opening_or_wall_ownership_authenticated"]
    assert not query["host_publication_allowed"]


def test_actual_component_pixel_query_retains_precise_count_and_output_links():
    result = observe_detector_dispositions(png(line_image()),queries=[{"query_id":"line_pixels",
        "render_bbox_pt":[20.,15.,22.,15.5]}])
    hits = result["pixel_query_receipts"][0]["bbox_intersecting_components"]
    assert len(hits) == 1
    assert hits[0]["actual_component_pixels_in_query"] == 10
    assert hits[0]["actual_pixel_center_bbox"] == [40,30,44,31]
    assert hits[0]["final_detector_output_indices"] == [0]
    assert not hits[0]["source_ownership_proven"]


@pytest.mark.parametrize("queries", [None, "queries", [{"query_id":" ","render_bbox_pt":[0.,0.,1.,1.]}],
    [{"query_id":"q","render_bbox_pt":[-1.,0.,1.,1.]}],
    [{"query_id":"q","render_bbox_pt":[0.,0.,999.,1.]}],
    [{"query_id":"q","render_bbox_pt":[2.,0.,1.,1.]}],
    [{"query_id":"q","render_bbox_pt":[False,0.,1.,1.]}],
    [{"query_id":"q","render_bbox_pt":["0",0.,1.,1.]}],
    [{"query_id":"q","render_bbox_pt":[0.,0.,float("inf"),1.]}],
    [{"query_id":"q","render_bbox_pt":[0.,0.,1.,1.]}]*2,
    [{"query_id":"q","render_bbox_pt":[0.,0.,1.,1.],"host_wall_id":"invented"}]])
def test_malformed_foreign_or_duplicate_pixel_queries_fail_closed(queries):
    with pytest.raises(ValueError):
        observe_detector_dispositions(png(line_image()),queries=queries)
    assert sys.gettrace() is None


def source_pdf(rotation=0):
    doc = fitz.open()
    page = doc.new_page(width=160,height=100)
    page.draw_line((20,30),(130,30))
    page.set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.parametrize("rotation", [0,90])
def test_source_pdf_seam_owns_replayed_render_and_keeps_native_display_frames_separate(rotation):
    from tools.diag_gptmax_raster_detector_dispositions import original_source_detector_dispositions
    data = source_pdf(rotation)
    result = original_source_detector_dispositions(data,page_id="1",expected_source_sha=sha256(data).hexdigest())
    assert result["source_sha256"] == sha256(data).hexdigest()
    assert result["page_id"] == "1" and result["viewport_id"] is None
    assert result["native_page_frame"]["rotation"] == rotation
    assert result["native_page_frame"]["coordinate_space"] == "native_page_user_space"
    assert result["native_page_parent_observation_id"]
    assert result["original_source_render_reauthenticated"]
    assert result["original_detector_output_unchanged"]
    assert result["render_dpi"] == 144 and result["primitive_safety_cap"] == 20000
    for k in ("visibility_publication_proven","source_universe_completeness_proven",
              "physical_equivalence_proven","host_publication_allowed","opening_count_publication_allowed",
              "metric_quantity_publication_allowed"):
        assert result[k] is False
    assert result["benchmark_accuracy"] is None


@pytest.mark.parametrize("page", [None,0,"0","01"," 1","١","-1","foreign"])
def test_noncanonical_original_source_page_rejected(page):
    from tools.diag_gptmax_raster_detector_dispositions import original_source_detector_dispositions
    data = source_pdf()
    with pytest.raises(ValueError,match="canonical original source page"):
        original_source_detector_dispositions(data,page_id=page,expected_source_sha=sha256(data).hexdigest())


@pytest.mark.parametrize("expected", [None,False,"foreign","a"*64])
def test_foreign_or_malformed_source_sha_rejected_before_ingest(expected):
    from tools.diag_gptmax_raster_detector_dispositions import original_source_detector_dispositions
    with pytest.raises(ValueError,match="source PDF SHA"):
        original_source_detector_dispositions(b"not-pdf",page_id="1",expected_source_sha=expected)


def test_foreign_render_sha_cannot_certify_original_pixels():
    from tools.diag_gptmax_raster_detector_dispositions import original_source_detector_dispositions
    data = source_pdf()
    with pytest.raises(ValueError,match="render SHA mismatch"):
        original_source_detector_dispositions(data,page_id="1",expected_source_sha=sha256(data).hexdigest(),
            expected_render_sha="a"*64)


def test_pixel_runs_require_original_foreground_and_keep_gaps_and_full_endpoints():
    from tools.diag_gptmax_raster_detector_dispositions import _positive_pixel_runs
    fg = np.zeros((20,20),np.uint8)
    fg[2:6,3] = 255
    fg[7:10,3] = 255
    xs = np.full(10,3,np.int64)
    ys = np.arange(1,11)
    before = fg.copy()
    assert _positive_pixel_runs(xs,ys,fg,orientation="vertical") == [(3,2,5),(3,7,9)]
    assert np.array_equal(fg,before)
    assert _positive_pixel_runs(ys,xs,fg.T,orientation="horizontal") == [(3,2,5),(3,7,9)]


def test_query_never_trims_full_original_positive_runs_into_false_contacts():
    result = observe_detector_dispositions(png(line_image()),queries=[{"query_id":"small_query",
        "render_bbox_pt":[20.,15.,22.,15.5]}])
    hit = result["pixel_query_receipts"][0]["bbox_intersecting_components"][0]
    assert hit["query_pixels_also_in_original_foreground"] == 10
    runs = hit["original_positive_pixel_run_receipts"]
    assert len(runs) == 2
    assert all(r["complete_run_pixel_geometry"][0] == 21 and r["complete_run_pixel_geometry"][2] == 129 for r in runs)
    assert all(r["query_did_not_trim_endpoints"] and r["component_pixels_and_original_foreground_all_positive"] for r in runs)
    assert all(r["source_primitive_ref"] is None and not r["physical_wall_line_proven"] for r in runs)
    component = result["component_receipts"][0]
    assert component["pixels_also_in_original_foreground"] < component["foreground_area_px"]


def test_rejected_branched_component_retains_genuine_pixel_runs_without_making_source_primitives():
    from types import SimpleNamespace
    from tools.gptmax_raster_flank_ownership import _flank_metrics
    pixels = np.full((100,120),255,np.uint8)
    pixels[36:45,30:85] = 0
    pixels[31:46,31] = 0
    result = observe_detector_dispositions(png(pixels),queries=[{"query_id":"branched_ink",
        "render_bbox_pt":[15.,18.,16.5,22.]}])
    hits = result["pixel_query_receipts"][0]["bbox_intersecting_components"]
    vertical = [h for h in hits if h["orientation"] == "vertical"]
    assert vertical and all("component_aspect_below_existing_minimum" in h["existing_rejection_reasons"] for h in vertical)
    opening = SimpleNamespace(origin=(15.5,22.5),axis=(0.,1.),normal=(-1.,0.),length=10.,thickness=2.)
    flank = {"role":"left","axis_span_pt":[-4.5,-.5],"normal_band_pt":[-1.,1.],"endpoint_pt":-.5}
    runs = [r for h in vertical for r in h["original_positive_pixel_run_receipts"]]
    assert any(_flank_metrics(r["complete_run_render_geometry_pt"],opening,flank)["flank_predicates_pass"] for r in runs)
    assert all(r["source_primitive_ref"] is None and not r["physical_wall_line_proven"] and not r["host_publication_allowed"] for r in runs)
    assert all(not h["final_detector_output_indices"] for h in vertical)


def test_render_canvas_boundary_query_keeps_all_actual_pixel_centers():
    result = observe_detector_dispositions(png(line_image()),queries=[{"query_id":"whole_render",
        "render_bbox_pt":[0.,0.,80.,50.]}])
    hit = result["pixel_query_receipts"][0]["bbox_intersecting_components"][0]
    assert hit["actual_component_pixels_in_query"] == 220
    assert hit["query_pixels_also_in_original_foreground"] == 218
    assert not result["source_universe_completeness_proven"]
    with pytest.raises(ValueError,match="outside render frame"):
        observe_detector_dispositions(png(line_image()),queries=[{"query_id":"outside",
            "render_bbox_pt":[0.,0.,80.01,50.]}])


@pytest.mark.parametrize("xs,ys,foreground,orientation", [
    (np.array([1]),np.array([2]),np.zeros((10,10),np.uint8),"diagonal"),
    ([1],np.array([2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([1.]),np.array([2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([True]),np.array([2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([1,2]),np.array([2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([-1]),np.array([2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([10]),np.array([2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([1,1]),np.array([2,2]),np.zeros((10,10),np.uint8),"vertical"),
    (np.array([1]),np.array([2]),np.zeros((10,10),float),"vertical"),
])
def test_foreign_duplicate_or_untyped_pixel_runs_fail_closed(xs,ys,foreground,orientation):
    from tools.diag_gptmax_raster_detector_dispositions import _positive_pixel_runs
    with pytest.raises(ValueError):
        _positive_pixel_runs(xs,ys,foreground,orientation=orientation)


def test_pixel_component_addresses_cannot_substitute_for_real_source_authority_receipts():
    from pb_source_observation_authority import ObservationSelector
    from pb_source_visibility_authority import SourceVisibilityProducer
    from tools.diag_gptmax_raster_detector_dispositions import original_source_detector_dispositions
    data = source_pdf()
    digest = sha256(data).hexdigest()
    producer = SourceVisibilityProducer(producer_method="test-pixel-source-boundary",producer_version="1")
    published = producer.ingest_native_pdf_bytes(document_id="source:pixel-boundary",source_bytes=data,
        source_locator="memory://pixel-boundary.pdf",page_ids=("1",))
    visibility = producer.authority()
    def selector(oid):
        return ObservationSelector(document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,source_sha256=digest,
            snapshot_id=published.snapshot.snapshot_id,observation_id=oid)
    assert len(published.visible_observation_ids) == 1
    genuine = visibility.resolve_visible(selector(published.visible_observation_ids[0]))
    assert genuine.status is EvidenceResolutionStatus.CORROBORATED and genuine.observation is not None
    report = original_source_detector_dispositions(data,page_id="1",expected_source_sha=digest)
    assert report["component_receipts"]
    for component in report["component_receipts"]:
        for result in (visibility.resolve_visible(selector(component["component_id"])),
                       visibility.resolve_raster_opening_primitive(selector(component["component_id"]))):
            assert result.status is EvidenceResolutionStatus.ABSTAINED
            assert result.observation is None
