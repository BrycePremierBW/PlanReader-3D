"""Producer ownership of real pixels never proves physical host authority."""
from dataclasses import replace
from hashlib import sha256

import cv2
import fitz
import numpy as np
import pytest

from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_observation_authority import SOURCE_OBSERVATION_EXISTS, ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer
import tools.gptmax_raster_positive_pixel_source as pixel


def png(image):
    ok, data = cv2.imencode(".png", image)
    assert ok
    return data.tobytes()


def image():
    result = np.full((160, 180), 255, np.uint8)
    result[40:65, 50:90] = 0
    # A real interior hole. Morphology does not authorize filling it.
    result[49:53, 70:73] = 255
    return result


def pdf(pixels=None, rotation=0):
    pixels = image() if pixels is None else pixels
    with fitz.open() as doc:
        page = doc.new_page(width=pixels.shape[1]/2, height=pixels.shape[0]/2)
        page.insert_image(page.rect, stream=png(pixels))
        page.draw_line((5, 5), (30, 5))
        page.set_rotation(rotation)
        return doc.tobytes()


def owner(data=None):
    data = pdf() if data is None else data
    return pixel.PixelRunSourceProducer(data, expected_source_sha=sha256(data).hexdigest(), page_id="1")


def test_real_source_pixels_receive_owned_records_without_physical_authority():
    producer = owner()
    base = producer.base_snapshot
    published = producer.nominate()
    assert producer.base_snapshot == base
    selectors = producer.selectors()
    assert selectors
    results = producer.authority().resolve_many(selectors)
    assert all(r.status == EvidenceResolutionStatus.CORROBORATED for r in results)
    assert all(r.proposition == SOURCE_OBSERVATION_EXISTS for r in results)
    assert all(r.observation.observation_kind == pixel.PIXEL_RUN_KIND for r in results)
    assert all(not r.semantic_enumeration_complete and not r.decision_scope_complete for r in results)
    assert all(r.physical_opening_existence == "physical_opening_existence_unresolved" for r in results)
    assert set(base.snapshot.observation_ids) <= set(published.snapshot.observation_ids)
    assert all(r.observation.derivation_parent_ids for r in results)


def test_existing_visibility_reader_rejects_pixel_nominations_and_resolves_real_control():
    data = pdf()
    shadow = owner(data)
    selectors = shadow.selectors()
    normal = SourceVisibilityProducer(producer_method="test", producer_version="1")
    original = normal.ingest_native_pdf_bytes(document_id="original", source_bytes=data,
        source_locator="memory://test.pdf", page_ids=("1",))
    original = normal.augment_with_raster_visible_segments(original.revision.revision_id, page_ids=("1",))
    authority = normal.authority()
    assert all(authority.resolve_visible(s).status == EvidenceResolutionStatus.ABSTAINED for s in selectors)
    control = ObservationSelector(original.revision.document_id, original.revision.revision_id,
        original.revision.source_sha256, original.snapshot.snapshot_id, original.visible_observation_ids[0])
    assert authority.resolve_visible(control).status == EvidenceResolutionStatus.CORROBORATED


@pytest.mark.parametrize("field,value", [
    ("document_id", "foreign"), ("revision_id", "stale"), ("source_sha256", "0"*64),
    ("snapshot_id", "foreign"), ("observation_id", "raster_detector_component_fake"),
])
def test_foreign_scope_or_diagnostic_id_cannot_borrow_owned_receipt(field, value):
    producer = owner()
    selector = producer.selectors()[0]
    assert producer.authority().resolve(replace(selector, **{field:value})).status != EvidenceResolutionStatus.CORROBORATED


@pytest.mark.parametrize("value", [None, {}, "fake", 1, True])
def test_selector_types_abstain(value):
    producer = owner()
    producer.nominate()
    assert producer.authority().resolve(value).status == EvidenceResolutionStatus.ABSTAINED


@pytest.mark.parametrize("page", [None, 1, True, "01", "0", "-1", "1.0", " 1", "١"])
def test_page_address_is_canonical_without_numeric_coercion(page):
    data = pdf()
    with pytest.raises(ValueError):
        pixel.PixelRunSourceProducer(data, expected_source_sha=sha256(data).hexdigest(), page_id=page)


@pytest.mark.parametrize("value", [None, bytearray(b"pdf"), memoryview(b"pdf"), "pdf"])
def test_caller_png_or_mutable_bytes_cannot_be_a_source(value):
    with pytest.raises(TypeError):
        pixel.PixelRunSourceProducer(value, expected_source_sha="0"*64, page_id="1")


@pytest.mark.parametrize("value", [None, "bad", "0"*64, "A"*64])
def test_source_sha_is_independently_verified(value):
    with pytest.raises(ValueError):
        pixel.PixelRunSourceProducer(pdf(), expected_source_sha=value, page_id="1")


def test_direct_factory_construction_is_rejected():
    with pytest.raises(TypeError):
        pixel.PixelRunSourceAuthority({})


def test_receipt_substitution_is_rejected_after_warm_read():
    producer = owner()
    selector = producer.selectors()[0]
    authority = producer.authority()
    assert authority.resolve(selector).status == EvidenceResolutionStatus.CORROBORATED
    producer._proofs[selector.observation_id] = replace(producer._proofs[selector.observation_id], geometry=(1., 2., 3., 4.))
    assert authority.resolve(selector).status == EvidenceResolutionStatus.CONFLICT


@pytest.mark.parametrize("field,value", [("geometry", (1.,2.,3.,4.)), ("page_id", "2"),
    ("derivation_parent_ids", ("fake",)), ("source_primitive_ref", "raster_segment:fake:1:0"),
    ("observation_kind", "raster_pdf_visible_segment")])
def test_replaced_source_record_is_not_authority_after_warm_read(field, value):
    producer = owner()
    selector = producer.selectors()[0]
    authority = producer.authority()
    assert authority.resolve(selector).status == EvidenceResolutionStatus.CORROBORATED
    store = producer._source._store
    key = (selector.snapshot_id, selector.observation_id)
    store.observations[key] = replace(store.observations[key], **{field:value})
    assert authority.resolve(selector).status != EvidenceResolutionStatus.CORROBORATED


def test_source_bytes_substitution_fails_after_warm_read():
    producer = owner()
    selector = producer.selectors()[0]
    authority = producer.authority()
    assert authority.resolve(selector).status == EvidenceResolutionStatus.CORROBORATED
    producer._source._store.source_bytes_by_revision[selector.revision_id] = pdf(np.rot90(image()).copy())
    assert authority.resolve(selector).status == EvidenceResolutionStatus.CONFLICT


def test_parent_removed_from_snapshot_fails_after_warm_read():
    producer = owner()
    selector = producer.selectors()[0]
    authority = producer.authority()
    result = authority.resolve(selector)
    parent_id = result.observation.derivation_parent_ids[0]
    producer._source._store.observations.pop((selector.snapshot_id, parent_id))
    assert authority.resolve(selector).status != EvidenceResolutionStatus.CORROBORATED


def test_returned_frozen_record_mutation_does_not_poison_producer():
    producer = owner()
    published = producer.nominate()
    original = published.snapshot.snapshot_id
    object.__setattr__(published.snapshot, "snapshot_id", "fake")
    assert producer.nominate().snapshot.snapshot_id == original
    selector = producer.selectors()[0]
    result = producer.authority().resolve(selector)
    object.__setattr__(result.observation, "geometry", (1.,2.,3.,4.))
    assert producer.authority().resolve(selector).observation.geometry != (1.,2.,3.,4.)


def test_source_nomination_ids_and_replay_are_deterministic():
    data = pdf()
    first, second = owner(data), owner(data)
    assert first.selectors() == second.selectors()
    assert first.nominate() == second.nominate()
    assert first.nominate() == first.nominate()


@pytest.mark.parametrize("rotation", [90,180,270])
def test_unproven_render_to_native_transform_fails_closed(rotation):
    with pytest.raises((ValueError, RuntimeError)):
        owner(pdf(rotation=rotation)).nominate()


def test_cap_failure_is_atomic_and_does_not_publish_partial_inventory(monkeypatch):
    producer = owner()
    base = producer.base_snapshot
    before = dict(producer._source._store.snapshots)
    monkeypatch.setattr(pixel, "MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS", 0)
    with pytest.raises(ValueError, match="safety bound"):
        producer.nominate()
    assert producer._published is None
    assert producer.base_snapshot == base
    assert producer._source._store.snapshots == before


def test_no_foreground_proves_no_source_universe_completeness():
    producer = owner(pdf(np.full((160,180),255,np.uint8)))
    assert producer.selectors() == ()
    assert producer.nominate() == producer.base_snapshot


def test_complete_runs_do_not_bridge_real_holes():
    proofs = pixel._inventory(png(image()))
    assert proofs
    for proof in proofs:
        x0,y0,x1,y1 = proof.pixel_geometry
        xs = np.arange(x0,x1+1) if y0 == y1 else np.full(y1-y0+1,x0)
        ys = np.arange(y0,y1+1) if x0 == x1 else np.full(x1-x0+1,y0)
        assert np.all(image()[ys,xs] == 0)
    assert not any(p.orientation == "vertical" and p.pixel_geometry[0] == 71
                   and p.pixel_geometry[1] < 49 and p.pixel_geometry[3] >= 53 for p in proofs)


def test_translation_preserves_full_run_geometry_and_all_alternatives():
    original = image()
    moved = np.full((200,230),255,np.uint8)
    moved[11:171,17:197] = original
    first = pixel._inventory(png(original))
    second = pixel._inventory(png(moved))
    assert {(p.orientation,p.pixel_geometry) for p in second} == {
        (p.orientation,tuple(v + (17 if i%2==0 else 11) for i,v in enumerate(p.pixel_geometry))) for p in first}


def test_transpose_retains_every_row_and_column():
    first = pixel._inventory(png(image()))
    second = pixel._inventory(png(image().T.copy()))
    assert {(p.orientation,p.pixel_geometry) for p in second} == {
        ("vertical" if p.orientation == "horizontal" else "horizontal",
         (p.pixel_geometry[1],p.pixel_geometry[0],p.pixel_geometry[3],p.pixel_geometry[2])) for p in first}


def test_inverse_polarity_and_unrelated_content_preserve_geometric_runs():
    base = image()
    extra = base.copy()
    extra[100:102,10:150] = 0
    expected = {(p.orientation,p.pixel_geometry) for p in pixel._inventory(png(base))}
    assert {(p.orientation,p.pixel_geometry) for p in pixel._inventory(png(255-base))} == expected
    assert {(p.orientation,p.pixel_geometry) for p in pixel._inventory(png(extra))} == expected


@pytest.mark.parametrize("selectors", [[], {}, "fake", None])
def test_batch_read_rejects_untyped_inventory(selectors):
    producer = owner()
    producer.nominate()
    with pytest.raises(ValueError):
        producer.authority().resolve_many(selectors)


def test_full_source_report_preserves_normal_source_and_every_shadow_parent():
    from tools.diag_gptmax_raster_positive_pixel_source import original_pixel_source_report
    data = pdf()
    report = original_pixel_source_report(data, expected_source_sha=sha256(data).hexdigest(),page_id="1")
    assert report["ordinary_source_snapshot_unchanged"]
    assert report["ordinary_visibility_rejects_shadow_kind"]
    assert len(report["ordinary_visible_source_records"]) == report["ordinary_source_record_count"]
    assert {r["snapshot_id"] for r in report["ordinary_visible_source_records"]} == {report["ordinary_source_snapshot"]["snapshot"]["snapshot_id"]}
    assert report["authenticated_pixel_source_count"] > 0
    assert not report["host_publication_allowed"]
    assert not report["source_universe_completeness_proven"]
    trace = report["experimental_w2_w4"]
    assert trace["input_source_count"] == report["ordinary_source_record_count"] + report["authenticated_pixel_source_count"]
    source_ids = {r["source_observation"]["observation_id"] for r in report["authenticated_pixel_source_records"]}
    census_ids = {r["source_observation_id"] for r in trace["source_parent_census"]}
    assert source_ids <= census_ids
    assert len(census_ids) == trace["input_source_count"]
    assert not trace["host_publication_allowed"]
    assert trace["w4_edge_map_consistent"]
    assert all(not r["physical_host_authority"] for r in trace["all_w2_edges"])
    assert all(not r["physical_host_authority"] for r in trace["all_experimental_w4_candidates"])
    assert all(r["status"] != EvidenceResolutionStatus.CORROBORATED.value for r in trace["all_experimental_w4_candidates"])


def test_source_trace_preserves_input_order_and_source_splitting_ancestry():
    from tools.diag_gptmax_raster_positive_pixel_source import _trace_sources
    producer = owner()
    records = tuple(r.observation for r in producer.authority().resolve_many(producer.selectors()))
    a = _trace_sources(records)
    b = _trace_sources(tuple(reversed(records)))
    assert a == b
    assert len(a["source_parent_census"]) == len(records)
    all_parents = {p for r in a["all_w2_edges"] for p in r["source_observation_ids"]}
    assert all_parents <= {r.observation_id for r in records}
    losses={r["fragment_id"]:r for r in a["all_snap_collapsed_fragments"]}
    for row in a["source_parent_census"]:
        for fragment_id in row["snap_collapsed_fragment_ids"]:
            assert row["source_observation_id"] in losses[fragment_id]["source_observation_ids"]
    for loss in losses.values():
        assert all(any(r["source_observation_id"]==parent and loss["fragment_id"] in r["snap_collapsed_fragment_ids"]
                       for r in a["source_parent_census"]) for parent in loss["source_observation_ids"])


@pytest.mark.parametrize("field,value", [("geometry", (True,1,2,3)),
    ("geometry", (float("inf"),1,2,3)), ("geometry", (1,2,1,2)),
    ("geometry", ("1",2,3,4))])
def test_experimental_topology_refuses_untyped_or_nonfinite_geometry(field,value):
    from tools.diag_gptmax_raster_positive_pixel_source import _trace_sources
    producer = owner()
    record = producer.authority().resolve(producer.selectors()[0]).observation
    with pytest.raises(ValueError,match="geometry"):
        _trace_sources((replace(record,**{field:value}),))


def test_experimental_topology_refuses_duplicate_and_foreign_scope():
    from tools.diag_gptmax_raster_positive_pixel_source import _trace_sources
    producer = owner()
    records = tuple(r.observation for r in producer.authority().resolve_many(producer.selectors()))
    with pytest.raises(ValueError,match="duplicate"):
        _trace_sources((records[0],records[0]))
    with pytest.raises(ValueError,match="foreign"):
        _trace_sources((records[0],replace(records[1],page_id="2")))


def test_source_report_render_hash_is_not_caller_authority():
    from tools.diag_gptmax_raster_positive_pixel_source import original_pixel_source_report
    data = pdf()
    with pytest.raises(ValueError,match="render SHA"):
        original_pixel_source_report(data,expected_source_sha=sha256(data).hexdigest(),page_id="1",expected_render_sha="0"*64)


def test_w3_removed_parent_stays_reported_without_invented_w4_owner():
    from tools.diag_gptmax_raster_positive_pixel_source import _trace_sources
    producer = owner()
    record = producer.authority().resolve(producer.selectors()[0]).observation
    alternate = replace(record,observation_id="independent-pixel-alternative",
        geometry=tuple(v+(0.5 if i%2==0 else 0.) for i,v in enumerate(record.geometry)))
    trace = _trace_sources((record,alternate))
    assert trace["w4_edge_map_consistent"]
    assert len(trace["source_parent_census"]) == 2
    removed = [r for r in trace["all_w2_edges"] if r["w3_removed"]]
    assert removed
    assert all(not r["experimental_w4_candidate_ids"] for r in removed)
    assert all(not r["physical_host_authority"] for r in removed)


def test_morphology_added_pixels_never_enter_a_source_run():
    original = image()
    foreground = pixel._foreground_mask(original)
    kernel = np.ones((8,1),np.uint8)
    mask = cv2.morphologyEx(foreground,cv2.MORPH_OPEN,kernel)
    assert np.any((mask != 0) & (foreground == 0))
    for proof in pixel._inventory(png(original)):
        x0,y0,x1,y1 = proof.pixel_geometry
        xs = np.arange(x0,x1+1) if y0 == y1 else np.full(y1-y0+1,x0)
        ys = np.arange(y0,y1+1) if x0 == x1 else np.full(x1-x0+1,y0)
        assert np.all(foreground[ys,xs] != 0)


def test_combined_source_cap_precedes_any_graph_mutation(monkeypatch):
    import tools.diag_gptmax_raster_positive_pixel_source as diagnostic
    producer = owner()
    record = producer.authority().resolve(producer.selectors()[0]).observation
    monkeypatch.setattr(diagnostic,"MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS",0)
    def forbidden(_segments):
        raise AssertionError("graph called before cap validation")
    monkeypatch.setattr(diagnostic,"build_wall_graph_for_viewport",forbidden)
    with pytest.raises(ValueError,match="safety bound"):
        diagnostic._trace_sources((record,))


def test_length_boundary_uses_unchanged_existing_page_point_minimum():
    original=np.full((70,70),255,np.uint8)
    original[20:30,20:40]=0
    proofs=pixel._inventory(png(original))
    vertical=[p for p in proofs if p.orientation=="vertical"]
    assert vertical and all((p.pixel_geometry[3]-p.pixel_geometry[1])/2>=4. for p in vertical)
    short=original.copy()
    short[29,:]=255
    assert not any(p.orientation=="vertical" for p in pixel._inventory(png(short)))
