"""Original raster source parent membership is NOT a physical host proof."""
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pb_live_wall_opening_authority_composition import (
    LiveOpeningHostFrameTrace,
    LiveOpeningHostTrace,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_opening_host_binding_authority import _OpeningGeometry
from tools.diag_gptmax_raster_host_source_membership import (
    DiagnosticRasterLineCache,
    nonpublishing_g17_support_receipts,
    nonpublishing_raster_source_w4_membership,
    nonpublishing_support_projection,
    nonpublishing_w2_deduplication_receipts,
    nonpublishing_w2_input_scope,
    nonpublishing_w2_parent_stage_receipts,
    nonpublishing_w2_w4_edge_membership,
    original_raster_host_ancestry_census,
)


def opening():
    return _OpeningGeometry(
        origin=(0.,0.), axis=(1.,0.), normal=(0.,1.),
        length=10., thickness=4.,
    )


def source_binding_trace(host_wall_id, *, index=0, reason_codes=()):
    return LiveOpeningHostTrace(
        opening_identity_id=f"opening-{index}", representative_observation_id=f"observation-{index}",
        page_id="3", status=EvidenceResolutionStatus.CORROBORATED if host_wall_id else EvidenceResolutionStatus.ABSTAINED,
        reason_codes=reason_codes, record_id=f"binding-{index}" if host_wall_id else None,
        host_wall_id=host_wall_id, member_wall_candidate_ids=(),
    )


def source_frame_trace(record_id, *, index=0):
    return LiveOpeningHostFrameTrace(
        opening_identity_id=f"opening-{index}",
        status=EvidenceResolutionStatus.CORROBORATED if record_id else EvidenceResolutionStatus.ABSTAINED,
        reason_codes=(), record_id=record_id,
        host_wall_id="host-a" if record_id else None, whole_wall_candidate_ids=(),
    )


def snapped_duplicate_graph():
    return {
        "nodes": [{"id": 0, "x": .75, "y": 0., "degree": 2},
                  {"id": 1, "x": .75, "y": 10., "degree": 2}],
        "edges": [
            {"id": "kept", "a": 0, "b": 1, "x1": 0., "y1": 0., "x2": 0., "y2": 10.,
             "primitive_lineage": {"source_primitive_ids": ["source-a"]}},
            {"id": "removed", "a": 0, "b": 1, "x1": 1.5, "y1": 0., "x2": 1.5, "y2": 10.,
             "primitive_lineage": {"source_primitive_ids": ["source-b"]}},
        ],
        "adjacency": {0: [0, 1], 1: [0, 1]},
    }


def test_actual_snapped_duplicate_receipts_keep_offset_source_parents_separate():
    graph = snapped_duplicate_graph()
    original = deepcopy(graph)
    report = nonpublishing_w2_deduplication_receipts(graph)
    assert graph == original
    assert report["original_w2_edge_count"] == 2
    assert report["retained_w3_edge_count"] == 1
    assert report["removed_w2_edge_count"] == 1
    row = report["removed_edge_receipts"][0]
    assert row["removed_w2_edge"]["source_primitive_ids"] == ["source-b"]
    assert row["retained_w2_edge"]["source_primitive_ids"] == ["source-a"]
    assert row["removed_w2_edge"]["producer_w2_edge_geometry_pt"] != row["retained_w2_edge"]["producer_w2_edge_geometry_pt"]
    assert row["removed_w2_edge"]["snapped_endpoint_geometry_pt"] == row["retained_w2_edge"]["snapped_endpoint_geometry_pt"]
    assert row["association_basis"] == "same_actual_snapped_node_pair"
    assert row["source_parents_transferred_to_w4"] is False
    assert row["physical_equivalence_proven"] is False
    assert row["host_publication_allowed"] is False


def test_reversed_w2_duplicate_retains_its_actual_source_direction():
    graph = snapped_duplicate_graph()
    edge = graph["edges"][1]
    edge.update(a=1, b=0, x1=1.5, y1=10., x2=1.5, y2=0.)
    row = nonpublishing_w2_deduplication_receipts(graph)["removed_edge_receipts"][0]
    assert row["removed_w2_edge"]["snapped_node_ids"] == [1, 0]
    assert row["removed_w2_edge"]["producer_w2_edge_geometry_pt"] == [1.5, 10., 1.5, 0.]
    assert row["retained_w2_edge"]["source_edge_id"] == "kept"
    assert row["physical_equivalence_proven"] is False


@pytest.mark.parametrize("corruption, message", [
    ("duplicate_edge", "edge address"), ("missing_node", "edge endpoints"),
    ("duplicate_parent", "parent inventory"), ("blank_parent", "parent inventory"),
    ("nonfinite_geometry", "edge geometry"), ("duplicate_node", "node address"),
])
def test_malformed_w2_duplicate_receipts_fail_closed_without_mutation(corruption, message):
    graph = snapped_duplicate_graph()
    if corruption == "duplicate_edge":
        graph["edges"][1]["id"] = "kept"
    elif corruption == "missing_node":
        graph["edges"][1]["b"] = 9
    elif corruption == "duplicate_parent":
        graph["edges"][1]["primitive_lineage"]["source_primitive_ids"] = ["source-b", "source-b"]
    elif corruption == "blank_parent":
        graph["edges"][1]["primitive_lineage"]["source_primitive_ids"] = [" "]
    elif corruption == "nonfinite_geometry":
        graph["edges"][1]["x1"] = float("inf")
    else:
        graph["nodes"].append(dict(graph["nodes"][0]))
    original = deepcopy(graph)
    with pytest.raises(ValueError, match=message):
        nonpublishing_w2_deduplication_receipts(graph)
    assert graph == original


@pytest.mark.parametrize("lineage", [[], "source", True, 42,
    {"source_primitive_ids": "source-b"}, {"source_primitive_ids": {"source-b": True}},
    {"source_primitive_ids": None}])
def test_w2_receipt_lineage_containers_never_become_fabricated_source_ids(lineage):
    graph = snapped_duplicate_graph()
    graph["edges"][1]["primitive_lineage"] = lineage
    original = deepcopy(graph)
    with pytest.raises((TypeError, ValueError), match="W2 deduplication.*(lineage|parent inventory)"):
        nonpublishing_w2_deduplication_receipts(graph)
    assert graph == original


@pytest.mark.parametrize("where,value", [
    ("node", True), ("node", "0.75"), ("edge", False), ("edge", "1.5"),
])
def test_w2_receipt_coordinates_do_not_coerce_bools_or_strings(where, value):
    graph = snapped_duplicate_graph()
    if where == "node":
        graph["nodes"][0]["x"] = value
    else:
        graph["edges"][1]["x1"] = value
    original = deepcopy(graph)
    with pytest.raises(ValueError, match="W2 deduplication.*geometry"):
        nonpublishing_w2_deduplication_receipts(graph)
    assert graph == original


@pytest.mark.parametrize("parents", [("parent", "parent"), "parent", {"parent": 1}, None])
def test_w4_edge_parent_containers_do_not_gain_ancestry_by_normalization(parents):
    row = record("w4-a", ("parent",), source_edges=(("edge", ("parent",)),))
    row.source_edge_fragments[0].source_primitive_ids = parents
    with pytest.raises(ValueError, match="W2 source edge parent inventory"):
        nonpublishing_raster_source_w4_membership([row], {"parent": (-5., 0., 0., 0.)}, opening(), page_id="3")


@pytest.mark.parametrize("parents", [("parent", "parent"), "parent", (), None])
def test_snap_loss_parent_inventory_cannot_be_empty_duplicated_or_coerced(parents):
    row = record("w4-a", ("parent",))
    row.source_snap_collapsed_fragments = (SimpleNamespace(
        edge_id="collapsed", source_primitive_ids=parents, geometry=(-1., 0., 0., 0.)),)
    with pytest.raises(ValueError, match="snap-loss.*parent inventory"):
        nonpublishing_raster_source_w4_membership([row], {"parent": (-5., 0., 0., 0.)}, opening(), page_id="3")


def record(id, source_ids, *, usable=True, source_edges=()):
    return SimpleNamespace(
        wall_candidate_id=id,
        physical_identity=SimpleNamespace(
            source_primitive_ids=tuple(source_ids), usable=usable,
        ),
        source_edge_fragments=tuple(
            SimpleNamespace(edge_id=edge_id, source_primitive_ids=tuple(parents))
            for edge_id, parents in source_edges
        ),
    )


def test_positive_exact_source_ancestry_is_never_local_wall_host_authority():
    rows = [
        record("w4-src-a", ["source-a", "source-common"]),
        record("w4-src-b", ["source-b", "source-common"]),
        record("w4-unusable", ["source-unusable"], usable=False),
    ]
    raw = {
        "source-a": (-5.,-1.,0.,-1.),
        "source-b": (10.,1.,14.,1.),
        "source-common": (-3.,0.,14.,0.),
        "source-unusable": (0.,0.,1.,0.),
        "orphan-source": (0.,1.,1.,1.),
        "off-axis-source": (0.,0.,0.,4.),
        "far-source": (50.,0.,60.,0.),
    }
    original = deepcopy(raw)
    report = nonpublishing_raster_source_w4_membership(
        rows, raw, opening(), page_id="3"
    )
    assert raw == original
    evidence={r["source_primitive_id"]:r for r in report["diagnostic_local_raster_lines"]}
    assert evidence["source-common"]["exact_positive_ancestry_w4_candidate_ids"] == [
        "w4-src-a", "w4-src-b"
    ]
    assert evidence["source-a"]["exact_positive_ancestry_w4_candidate_ids"] == ["w4-src-a"]
    assert evidence["source-unusable"]["exact_positive_ancestry_w4_candidate_ids"] == []
    assert evidence["orphan-source"]["exact_positive_ancestry_w4_candidate_ids"] == []
    assert "off-axis-source" not in evidence
    assert "far-source" not in evidence
    assert report["original_source_stage_counts"]["line_not_parallel_to_opening"] == 1
    assert report["original_source_stage_counts"]["line_outside_aperture_local_band"] == 1
    assert report["unusable_identity_source_parent_count"] == 1
    assert not report["local_host_contact_proven"]
    assert not report["physical_equivalence_proven"]
    assert not report["host_publication_allowed"]
    assert not report["opening_count_publication_allowed"]
    assert not report["metric_quantity_publication_allowed"]
    assert report["benchmark_accuracy"] is None


@pytest.mark.parametrize("line", [
    (float("nan"), 0., 1., 0.), (0., float("inf"),1.,0.),
    (0.,0.,1.), ("invalid",0.,1.,0.),
])
def test_bad_original_source_geometry_does_not_create_candidate_ancestry(line):
    result=nonpublishing_raster_source_w4_membership(
        [record("source-owned", ["source"])], {"source":line},
        opening(), page_id="3",
    )
    assert result["original_source_stage_counts"] == {"invalid_source_geometry":1}
    assert result["diagnostic_local_raster_lines"] == []
    assert not result["host_publication_allowed"]


def test_original_w2_source_edge_witnesses_preserve_shared_parent_ambiguity():
    records=[
        record("w4-a", ["common", "only-a"],
               source_edges=(("split-2296", ["common", "only-a"]),)),
        record("w4-b", ["common"],
               source_edges=(("split-9744", ["common"]),)),
        record("w4-c", ["common"],
               source_edges=(("split-9744", ["common"]),)),
    ]
    original=deepcopy(records)
    result=nonpublishing_raster_source_w4_membership(
        records, {"common": (-2.,0.,13.,0.)}, opening(), page_id="3"
    )
    row=result["diagnostic_local_raster_lines"][0]
    assert row["exact_positive_ancestry_w4_candidate_ids"]==[
        "w4-a", "w4-b", "w4-c"
    ]
    assert row["actual_w2_source_edges_by_w4_candidate"]==[
        {"wall_candidate_id":"w4-a","source_edge_id":"split-2296"},
        {"wall_candidate_id":"w4-b","source_edge_id":"split-9744"},
        {"wall_candidate_id":"w4-c","source_edge_id":"split-9744"},
    ]
    assert records==original
    assert not row["locally_authenticated_host"]
    assert not result["host_publication_allowed"]
    assert not result["opening_count_publication_allowed"]


def test_source_parent_without_w2_edge_witness_is_not_silently_fabricated():
    result=nonpublishing_raster_source_w4_membership(
        [record("w4-with-ancestry", ["positive-parent"])],
        {"positive-parent":(-1.,0.,11.,0.)}, opening(), page_id="3"
    )
    row=result["diagnostic_local_raster_lines"][0]
    assert row["exact_positive_ancestry_w4_candidate_ids"]==[
        "w4-with-ancestry"
    ]
    assert row["actual_w2_source_edges_by_w4_candidate"]==[]
    assert not row["locally_authenticated_host"]


def test_duplicate_ancestry_parent_not_counted_as_two_openings_or_host():
    rows=[record("same-physical-id", ["parent", "parent"])]
    data={"parent": (-1.,0.,1.,0.)}
    original = deepcopy((rows, data))
    with pytest.raises(ValueError, match="source primitive parent inventory"):
        nonpublishing_raster_source_w4_membership(rows,data,opening(),page_id="3")
    assert (rows, data) == original


def test_diagnostic_cannot_accept_a_wrong_original_pdf_sha():
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        original_raster_host_ancestry_census(
            b"not-the-original-pdf", page_id="3", expected_source_sha="0"*64,
        )


@pytest.mark.parametrize("page", ["", "-1", "3a", "0"])
def test_bad_original_source_page_rejected_before_processing(page):
    import hashlib
    data=b"fake-input-is-not-a-PDF"
    with pytest.raises(ValueError, match="invalid page"):
        original_raster_host_ancestry_census(
            data, page_id=page,
            expected_source_sha=hashlib.sha256(data).hexdigest(),
        )


def test_w2_source_edge_parent_not_in_w4_identity_is_quarantined_as_contradiction():
    w4 = record(
        "w4-physical-id", ["legitimate-parent"],
        source_edges=(("split-positive", ["legitimate-parent"]),
                      ("split-foreign", ["foreign-parent"])),
    )
    report = nonpublishing_raster_source_w4_membership(
        [w4], {
            "legitimate-parent": (-1.,0.,1.,0.),
            "foreign-parent": (-1.,0.,1.,0.),
        }, opening(), page_id="3"
    )
    by_parent = {
        row["source_primitive_id"]: row
        for row in report["diagnostic_local_raster_lines"]
    }
    assert by_parent["legitimate-parent"][
        "actual_w2_source_edges_by_w4_candidate"
    ] == [{"wall_candidate_id":"w4-physical-id",
           "source_edge_id":"split-positive"}]
    assert by_parent["foreign-parent"][
        "exact_positive_ancestry_w4_candidate_ids"
    ] == []
    assert by_parent["foreign-parent"][
        "actual_w2_source_edges_by_w4_candidate"
    ] == []
    assert report["source_edge_parent_identity_contradiction_count"] == 1
    assert report["source_edge_parent_identity_contradictions"] == [{
        "wall_candidate_id": "w4-physical-id",
        "source_edge_id": "split-foreign",
        "unowned_source_parent_id": "foreign-parent",
    }]
    assert not report["local_host_contact_proven"]
    assert not report["host_publication_allowed"]
    assert not report["metric_quantity_publication_allowed"]


@pytest.mark.parametrize("changes", [
    {"axis": (2., 0.)}, {"normal": (1., 0.)}, {"normal": (0., 0.)},
    {"origin": (float("nan"), 0.)}, {"origin": (0.,)},
    {"length": 0.}, {"thickness": -1.}, {"length": float("inf")},
])
def test_invalid_aperture_basis_cannot_make_geometry_look_local(changes):
    with pytest.raises(ValueError, match="aperture coordinate basis"):
        nonpublishing_raster_source_w4_membership(
            [record("w4-a", ["parent"])], {"parent":(-1.,0.,11.,0.)},
            replace(opening(), **changes), page_id="3",
        )


@pytest.mark.parametrize("line,aperture,reason", [
    ((-1.7e308,0.,1.7e308,0.), opening(), "invalid_source_geometry"),
    ((1.7e308,0.,1.7e308,1.), replace(opening(), origin=(-1.7e308,0.),
        axis=(0.,1.), normal=(-1.,0.)), "nonfinite_source_projection"),
    ((0.,1.7e308,1.,1.7e308), opening(), "nonfinite_source_projection"),
    ((0.,0.,0.,0.), opening(), "invalid_source_geometry"),
])
def test_finite_source_points_cannot_emit_overflowed_local_axis(line, aperture, reason):
    report = nonpublishing_raster_source_w4_membership(
        [record("w4-a", ["parent"])], {"parent":line}, aperture, page_id="3",
    )
    assert report["diagnostic_local_raster_lines"] == []
    assert report["original_source_stage_counts"] == {reason:1}
    json.dumps(report, allow_nan=False)
    assert not report["host_publication_allowed"]


def test_colliding_w4_addresses_cannot_union_two_competing_source_records():
    rows = [record("shared-id", ["parent-a"]), record("shared-id", ["parent-b"]),
            record("independent", ["parent-a"])]
    original = deepcopy(rows)
    source = {"parent-a":(-1.,0.,11.,0.), "parent-b":(-1.,1.,11.,1.)}
    forward = nonpublishing_raster_source_w4_membership(rows, source, opening(), page_id="3")
    reversed_report = nonpublishing_raster_source_w4_membership(
        tuple(reversed(rows)), source, opening(), page_id="3")
    assert forward == reversed_report
    by_parent = {r["source_primitive_id"]:r for r in forward["diagnostic_local_raster_lines"]}
    assert by_parent["parent-a"]["exact_positive_ancestry_w4_candidate_ids"] == ["independent"]
    assert by_parent["parent-b"]["exact_positive_ancestry_w4_candidate_ids"] == []
    assert forward["quarantined_w4_candidate_addresses"] == [{
        "wall_candidate_id":"shared-id", "source_record_count":2,
        "source_parent_ids_by_record":[["parent-a"],["parent-b"]],
    }]
    assert rows == original
    assert not forward["physical_equivalence_proven"]


def test_contradictory_shared_w2_edge_address_is_quarantined_for_every_owner():
    rows = [record("w4-a", ["parent-a"], source_edges=(("same-edge",["parent-a"]),)),
            record("w4-b", ["parent-b"], source_edges=(("same-edge",["parent-b"]),))]
    source = {"parent-a":(-1.,0.,11.,0.), "parent-b":(-1.,1.,11.,1.)}
    result = nonpublishing_raster_source_w4_membership(rows,source,opening(),page_id="3")
    assert result["conflicting_w2_source_edge_addresses"] == ["same-edge"]
    assert all(row["actual_w2_source_edges_by_w4_candidate"] == []
               for row in result["diagnostic_local_raster_lines"])
    assert not result["local_host_contact_proven"]


@pytest.mark.parametrize("identifier", [None, "", " ", 123])
def test_missing_candidate_id_cannot_be_stringified_into_positive_ancestry(identifier):
    with pytest.raises(ValueError, match="candidate address"):
        nonpublishing_raster_source_w4_membership(
            [record(identifier,["parent"])], {"parent":(-1.,0.,11.,0.)},
            opening(),page_id="3",
        )


def geometric_record(cid, parent, eid, geometry):
    row = record(cid, [parent], source_edges=((eid,[parent]),))
    row.source_edge_fragments[0].geometry = geometry
    return row


def test_long_parent_keeps_remote_and_local_w2_fragments_separately_observable():
    rows = [geometric_record("local", "parent", "local-edge", (-3.,0.,0.,0.)),
            geometric_record("remote", "parent", "remote-edge", (70.,0.,80.,0.))]
    original = deepcopy(rows)
    report = nonpublishing_raster_source_w4_membership(
        rows,{"parent":(-5.,0.,100.,0.)},opening(),page_id="3")
    evidence = report["diagnostic_local_raster_lines"][0]
    geometry = {r["wall_candidate_id"]:r
                for r in evidence["w2_source_fragment_geometry_by_w4_candidate"]}
    assert evidence["exact_positive_ancestry_w4_candidate_ids"] == ["local","remote"]
    assert geometry["local"]["within_aperture_diagnostic_band"]
    assert not geometry["remote"]["within_aperture_diagnostic_band"]
    assert geometry["local"]["distance_from_fragment_axis_endpoints_to_aperture_ends_pt"] == [0.,10.]
    assert geometry["remote"]["distance_from_fragment_axis_endpoints_to_aperture_ends_pt"] == [70.,60.]
    assert all(r["source_parent_contains_w2_fragment_geometry"] for r in geometry.values())
    assert all(not r["physical_contact_proven"] for r in geometry.values())
    assert rows == original


@pytest.mark.parametrize("geometry,disposition", [
    (None,"invalid_source_geometry"), ((0.,0.,1.),"invalid_source_geometry"),
    ((0.,0.,0.,0.),"invalid_source_geometry"),
    ((0.,0.,0.,3.),"line_not_parallel_to_opening"),
])
def test_invalid_w2_fragment_geometry_remains_unavailable_despite_positive_parent(geometry, disposition):
    report = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", geometry)],
        {"parent":(-1.,0.,11.,0.)},opening(),page_id="3")
    observation = report["diagnostic_local_raster_lines"][0][
        "w2_source_fragment_geometry_by_w4_candidate"][0]
    assert observation["geometry_disposition"] == disposition
    assert "within_aperture_diagnostic_band" not in observation
    assert not observation["physical_contact_proven"]


def test_local_fragment_without_raw_parent_containment_is_not_source_continuity():
    report = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", (-3.,0.,0.,0.))],
        {"parent":(-1.,0.,11.,0.)}, opening(),page_id="3")
    observation = report["diagnostic_local_raster_lines"][0][
        "w2_source_fragment_geometry_by_w4_candidate"][0]
    assert observation["within_aperture_diagnostic_band"]
    assert not observation["source_parent_contains_w2_fragment_geometry"]
    assert not observation["physical_contact_proven"]


def test_fragment_locality_is_preserved_by_quarter_rotation_and_translation():
    line = (-3.,0.,0.,0.)
    parent = (-5.,0.,100.,0.)
    def transform_line(value):
        return (100.-value[1],200.+value[0],100.-value[3],200.+value[2])
    ordinary = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", line)],
        {"parent":parent},opening(),page_id="3")
    shifted = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", transform_line(line))],
        {"parent":transform_line(parent)},
        replace(opening(),origin=(100.,200.),axis=(0.,1.),normal=(-1.,0.)),page_id="3")
    left = ordinary["diagnostic_local_raster_lines"][0]["w2_source_fragment_geometry_by_w4_candidate"][0]
    right = shifted["diagnostic_local_raster_lines"][0]["w2_source_fragment_geometry_by_w4_candidate"][0]
    for key in ("aperture_axis_span_pt", "aperture_normal_offset_pt",
                "within_aperture_diagnostic_band", "source_parent_contains_w2_fragment_geometry",
                "distance_from_fragment_axis_endpoints_to_aperture_ends_pt"):
        assert left[key] == right[key]


def test_original_source_audit_counts_frame_receipts_and_retains_abstained_attempts(monkeypatch):
    import hashlib

    import tools.diag_gptmax_raster_host_source_membership as diagnostic

    data = b"source-bytes-for-composition-boundary-regression"
    digest = hashlib.sha256(data).hexdigest()
    revision = SimpleNamespace(revision_id="source-revision", document_id="source-document",
                               source_sha256=digest)
    published = SimpleNamespace(revision=revision,
                                snapshot=SimpleNamespace(snapshot_id="source-snapshot"))
    class SourceProducer:
        def __init__(self, **kwargs):
            pass
        def ingest_native_pdf_bytes(self, **kwargs):
            assert kwargs["source_bytes"] == data
            assert kwargs["page_ids"] == ("3",)
            return published
        def published_snapshot_for_revision(self, revision_id):
            assert revision_id == revision.revision_id
            return published

    composition = SimpleNamespace(
        physical_wall_candidate_authority=SimpleNamespace(
            resolve_scope=lambda selector: SimpleNamespace(scope_complete=True, equivalence=object(), records=())
        ),
        physical_opening_authority=object(),
        opening_bindings=[
            source_binding_trace("host-a"),
            source_binding_trace("host-b",index=1),
            source_binding_trace(None,index=2,reason_codes=("no_authenticated_host_wall_band",)),
        ],
        host_frames=[source_frame_trace("authenticated-frame"),
                     source_frame_trace(None,index=1), source_frame_trace(None,index=2)],
    )
    original = deepcopy(composition.host_frames)
    graph = snapped_duplicate_graph()
    graph_before = deepcopy(graph)
    monkeypatch.setattr(diagnostic.wall_producer, "build_wall_graph_for_viewport", lambda segments, **kwargs: graph)
    def compose_with_actual_graph_passthrough(**kwargs):
        assert diagnostic.wall_producer.build_wall_graph_for_viewport([]) is graph
        return composition
    monkeypatch.setattr(diagnostic,"SourceVisibilityProducer",SourceProducer)
    monkeypatch.setattr(diagnostic,"compose_live_wall_opening_authority",compose_with_actual_graph_passthrough)
    report = diagnostic.original_raster_host_ancestry_census(
        data,page_id="3",expected_source_sha=digest)
    assert report["source_original_opening_count"] == 3
    assert report["source_original_host_count"] == 2
    assert report["source_original_frame_count"] == 1
    assert report["source_original_frame_trace_count"] == 3
    assert composition.host_frames == original
    assert graph == graph_before
    assert report["source_w2_deduplication_censuses"][0]["removed_w2_edge_count"] == 1
    assert report["opening_bindings"][0]["host_wall_id"] == "host-a"
    assert report["host_frames"][1]["status"] == "abstained"
    assert report["primitive_safety_cap"] == 20_000
    assert not report["host_publication_allowed"]
    assert not report["opening_count_publication_allowed"]
    assert not report["metric_quantity_publication_allowed"]


def test_original_frame_count_excludes_abstained_frame_traces(monkeypatch):
    import hashlib

    import tools.diag_gptmax_raster_host_source_membership as diagnostic

    data=b"source-producer-fixture"
    digest=hashlib.sha256(data).hexdigest()
    revision=SimpleNamespace(document_id="doc",revision_id="rev",source_sha256=digest)
    published=SimpleNamespace(revision=revision,snapshot=SimpleNamespace(snapshot_id="snap"))
    class Producer:
        def __init__(self,**kwargs): pass
        def ingest_native_pdf_bytes(self,**kwargs): return published
        def published_snapshot_for_revision(self,revision_id): return published
    wall=SimpleNamespace(scope_complete=True,equivalence=object(),records=())
    composition=SimpleNamespace(
        physical_wall_candidate_authority=SimpleNamespace(resolve_scope=lambda selector:wall),
        physical_opening_authority=object(),opening_bindings=(),
        host_frames=(source_frame_trace("source-proven-frame"),
                     source_frame_trace(None,index=1),source_frame_trace(None,index=2)),
    )
    monkeypatch.setattr(diagnostic,"SourceVisibilityProducer",Producer)
    monkeypatch.setattr(diagnostic,"compose_live_wall_opening_authority",lambda **kwargs:composition)
    report=original_raster_host_ancestry_census(data,page_id="3",expected_source_sha=digest)
    assert report["source_original_frame_count"]==1
    assert report["source_original_frame_trace_count"]==3
    assert report["host_publication_allowed"] is False

@pytest.mark.parametrize("source_ids", [
    ("valid-source", "valid-source"),
    ("valid-source", ""),
    ("valid-source", "   "),
    ("valid-source", None),
])
def test_invalid_w4_source_parent_inventory_never_grants_ancestry(source_ids):
    with pytest.raises(ValueError, match="invalid W4 source primitive parent inventory"):
        nonpublishing_raster_source_w4_membership(
            [record("w4-a", source_ids)],
            {"valid-source": (-5., -1., 0., -1.)},
            opening(), page_id="3",
        )


@pytest.mark.parametrize("edge_id", ("", "   ", None))
def test_missing_w2_source_edge_identity_never_grants_ancestry(edge_id):
    row = record(
        "w4-a", ("valid-source",),
        source_edges=((edge_id, ("valid-source",)),),
    )
    with pytest.raises(ValueError, match="missing W2 source edge identity"):
        nonpublishing_raster_source_w4_membership(
            [row],
            {"valid-source": (-5., -1., 0., -1.)},
            opening(), page_id="3",
        )


def test_source_snap_loss_is_retained_separately_from_surviving_w2_edge_authority():
    row = geometric_record("w4", "parent", "surviving", (-4.,0.,-1.,0.))
    row.source_snap_collapsed_fragments = (SimpleNamespace(
        edge_id="lost-fragment", source_primitive_ids=("parent",),
        geometry=(-1.,0.,0.,0.), reason_code="both_endpoints_snapped_to_same_node"),)
    original = deepcopy(row)
    result = nonpublishing_raster_source_w4_membership(
        [row], {"parent":(-4.,0.,0.,0.)},opening(),page_id="3")
    evidence = result["diagnostic_local_raster_lines"][0]
    assert evidence["actual_w2_source_edges_by_w4_candidate"] == [
        {"wall_candidate_id":"w4", "source_edge_id":"surviving"}]
    loss = evidence["w2_snap_loss_geometry_by_associated_w4_candidate"][0]
    assert loss["source_edge_id"] == "lost-fragment"
    assert loss["w2_disposition"] == "SNAP_COLLAPSED_NOT_SURVIVING_EDGE"
    assert loss["within_aperture_diagnostic_band"]
    assert loss["distance_from_fragment_axis_endpoints_to_aperture_ends_pt"] == [0.,10.]
    assert not loss["surviving_w2_edge"]
    assert not loss["wall_continuity_proven"]
    assert not loss["physical_contact_proven"]
    assert row == original


@pytest.mark.parametrize("corruption", ["already_surviving", "foreign_parent"])
def test_contradictory_source_snap_loss_never_becomes_an_opening_flank(corruption):
    row = geometric_record("w4", "parent", "surviving", (-4.,0.,-1.,0.))
    row.source_snap_collapsed_fragments = (SimpleNamespace(
        edge_id="surviving" if corruption == "already_surviving" else "lost-fragment",
        source_primitive_ids=("foreign" if corruption == "foreign_parent" else "parent",),
        geometry=(-1.,0.,0.,0.), reason_code="both_endpoints_snapped_to_same_node"),)
    with pytest.raises(ValueError, match="snap-loss"):
        nonpublishing_raster_source_w4_membership(
            [row], {"parent":(-4.,0.,0.,0.)},opening(),page_id="3")


def test_finite_axis_interval_cannot_serialize_overflowed_aperture_end_distance():
    report = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", (-1.5e308,0.,-1.4e308,0.))],
        {"parent":(-1.,0.,1.,0.)}, replace(opening(),length=1.7e308),page_id="3")
    observation = report["diagnostic_local_raster_lines"][0][
        "w2_source_fragment_geometry_by_w4_candidate"][0]
    assert observation["geometry_disposition"] == "nonfinite_aperture_end_distance"
    assert "distance_from_fragment_axis_endpoints_to_aperture_ends_pt" not in observation
    assert not observation["physical_contact_proven"]
    json.dumps(report, allow_nan=False)


def input_scope_fixture():
    published = SimpleNamespace(
        revision=SimpleNamespace(document_id="doc", revision_id="rev", source_sha256="sha"),
        snapshot=SimpleNamespace(snapshot_id="graph-snapshot"))
    segments = [{"id": "source-a", "document_id": "doc", "page_id": "3",
                 "viewport_id": "wall-source:page-3", "source_observation_id": "observed-a",
                 "x1": 0., "y1": 0., "x2": 0., "y2": 10.}]
    return published, segments


def test_graph_time_scope_retains_actual_input_receipts_without_mutation():
    published, segments = input_scope_fixture()
    before = deepcopy(segments)
    report = nonpublishing_w2_input_scope(segments, published, page_id="3")
    assert segments == before
    assert report["snapshot_id"] == "graph-snapshot"
    assert report["input_source_receipts"] == [{
        "source_primitive_id": "source-a", "source_observation_id": "observed-a",
        "viewport_id": "wall-source:page-3", "source_geometry_pt": [0., 0., 0., 10.]}]
    assert not report["source_ownership_proven"]
    assert not report["host_publication_allowed"]
    report["input_source_receipts"][0]["source_geometry_pt"][0] = 99.
    assert segments == before


@pytest.mark.parametrize("field,value", [("document_id", "foreign"), ("page_id", "4"),
    ("viewport_id", None), ("source_observation_id", True), ("id", "")])
def test_foreign_or_missing_graph_input_scope_is_not_reconstructed(field, value):
    published, segments = input_scope_fixture()
    segments[0][field] = value
    with pytest.raises(ValueError, match="W2 input source"):
        nonpublishing_w2_input_scope(segments, published, page_id="3")


def test_empty_graph_inputs_remain_explicitly_unknown_and_duplicate_ids_fail():
    published, segments = input_scope_fixture()
    empty = nonpublishing_w2_input_scope([], published, page_id="3")
    assert not empty["input_source_scope_observed"]
    assert empty["input_viewport_ids"] == []
    with pytest.raises(ValueError, match="duplicate W2 input"):
        nonpublishing_w2_input_scope(segments + segments, published, page_id="3")


def test_all_w2_edges_retain_separate_w4_membership_alternatives():
    graph = snapped_duplicate_graph()
    census = nonpublishing_w2_deduplication_receipts(graph)
    records = [geometric_record("owner-a", "source-a", "kept", (0., 0., 0., 10.)),
               geometric_record("owner-b", "source-a", "kept", (0., 0., 0., 10.)),
               geometric_record("unusable", "source-a", "kept", (0., 0., 0., 10.))]
    records[2].physical_identity.usable = False
    before = deepcopy(census)
    report = nonpublishing_w2_w4_edge_membership(census, records)
    assert census == before
    edges = {r["source_edge_id"]: r for r in report["all_w2_edge_receipts"]}
    owners = edges["kept"]["actual_w4_edge_membership_alternatives"]
    assert [r["wall_candidate_id"] for r in owners] == ["owner-a", "owner-b", "unusable"]
    assert [r["w4_membership_receipt_usable"] for r in owners] == [True, True, False]
    assert edges["removed"]["w3_disposition"] == "REMOVED_SNAPPED_NODE_DUPLICATE"
    assert edges["removed"]["actual_w4_edge_membership_alternatives"] == []
    assert edges["removed"]["source_primitive_ids"] == ["source-b"]
    assert not edges["kept"]["physical_equivalence_proven"]
    assert not edges["kept"]["host_publication_allowed"]
    assert report == nonpublishing_w2_w4_edge_membership(census, list(reversed(records)))


@pytest.mark.parametrize("case", ["duplicate-candidate", "foreign-parent", "foreign-geometry", "removed-edge"])
def test_conflicting_w4_edge_receipts_never_become_usable_membership(case):
    census = nonpublishing_w2_deduplication_receipts(snapped_duplicate_graph())
    owner = geometric_record("owner", "source-a", "kept", (0., 0., 0., 10.))
    records = [owner]
    edge_id = "kept"
    if case == "duplicate-candidate":
        records.append(deepcopy(owner))
    elif case == "foreign-parent":
        owner.source_edge_fragments[0].source_primitive_ids = ("foreign",)
    elif case == "foreign-geometry":
        owner.source_edge_fragments[0].geometry = (1., 0., 1., 10.)
    else:
        edge_id = "removed"
        owner.source_edge_fragments[0].edge_id = edge_id
        owner.source_edge_fragments[0].source_primitive_ids = ("source-b",)
        owner.source_edge_fragments[0].geometry = (1.5, 0., 1.5, 10.)
        owner.physical_identity.source_primitive_ids = ("source-b",)
    edges = nonpublishing_w2_w4_edge_membership(census, records)["all_w2_edge_receipts"]
    alternatives = next(r for r in edges if r["source_edge_id"] == edge_id)["actual_w4_edge_membership_alternatives"]
    assert alternatives
    assert not any(r["w4_membership_receipt_usable"] for r in alternatives)
    assert not any(r["host_publication_allowed"] for r in alternatives)


def support_opening():
    return SimpleNamespace(document_id="doc", revision_id="rev", source_sha256="sha",
                           snapshot_id="snap", page_id="3", viewport_id=None,
                           source_observation_ids=("face", "end"))


def support_observation(oid, **changes):
    fields = {"document_id": "doc", "revision_id": "rev", "source_sha256": "sha",
        "snapshot_id": "snap", "page_id": "3", "viewport_id": None, "observation_id": oid,
        "observation_kind": "raster_wall_band_face" if oid == "face" else "raster_wall_band_end",
        "source_primitive_ref": f"visible:primitive-{oid}", "derivation_parent_ids": (f"parent-{oid}",),
        "observation_payload_sha256": f"sealed-payload-{oid}",
        "geometry": (-4., -1., 0., -1.) if oid == "face" else (0., -1., 0., 1.)}
    fields.update(changes)
    return SimpleNamespace(**fields)


def support_authority(observations, *, unavailable=()):
    selectors = []
    def resolve(selector):
        selectors.append(selector)
        return SimpleNamespace(status=EvidenceResolutionStatus.ABSTAINED if selector.observation_id in unavailable
                               else EvidenceResolutionStatus.CORROBORATED,
                               observation=observations.get(selector.observation_id), reason_codes=("original-reason",))
    authority = SimpleNamespace(source_visibility_authority=lambda: SimpleNamespace(resolve_raster_opening_primitive=resolve))
    return authority, selectors


def test_g17_receipts_use_exact_original_selector_and_retain_sealed_face_end_geometry():
    observations = {oid: support_observation(oid) for oid in ("face", "end")}
    authority, selectors = support_authority(observations)
    before = deepcopy(observations)
    report = nonpublishing_g17_support_receipts(authority, support_opening(), opening())
    assert observations == before
    assert [s.observation_id for s in selectors] == ["end", "face"]
    for selector in selectors:
        assert (selector.document_id, selector.revision_id, selector.source_sha256, selector.snapshot_id) == ("doc", "rev", "sha", "snap")
    assert all(r["source_receipt_authenticated"] for r in report)
    assert report[0]["derivation_parent_ids"] == ["parent-end"]
    assert report[0]["observation_payload_sha256"] == "sealed-payload-end"
    assert report[0]["original_source_support_geometry_pt"] == [0., -1., 0., 1.]
    assert report[0]["original_resolution_reason_codes"] == ["original-reason"]
    assert not any(r["physical_contact_proven"] or r["host_publication_allowed"] for r in report)


@pytest.mark.parametrize("field,value", [("document_id", "foreign"), ("revision_id", "foreign"),
    ("source_sha256", "foreign"), ("snapshot_id", "foreign"), ("observation_id", "foreign"),
    ("page_id", "4"), ("viewport_id", "scope"), ("observation_kind", "raster_pdf_visible_segment")])
def test_g17_foreign_receipt_is_retained_as_negative_without_geometry(field, value):
    authority, _ = support_authority({"face": support_observation("face", **{field: value})})
    report = nonpublishing_g17_support_receipts(authority, support_opening(), opening())
    face = next(r for r in report if r["requested_source_observation_id"] == "face")
    assert not face["source_receipt_authenticated"]
    assert face["diagnostic_rejection_reason"] == "G17_support_source_scope_mismatch"
    assert "original_source_support_geometry_pt" not in face
    assert not face["host_publication_allowed"]


def test_unavailable_g17_support_is_not_dropped_or_reconstructed():
    authority, _ = support_authority({"face": support_observation("face")}, unavailable=("end",))
    report = nonpublishing_g17_support_receipts(authority, support_opening(), opening())
    assert len(report) == 2
    end = next(r for r in report if r["requested_source_observation_id"] == "end")
    assert end["resolution_status"] == "abstained"
    assert end["original_resolution_reason_codes"] == ["original-reason"]
    assert not end["source_receipt_authenticated"]
    assert "original_source_support_geometry_pt" not in end


@pytest.mark.parametrize("line,along,normal", [
    ((-4., -1., 0., -1.), [-4., 0.], [-1., -1.]),
    ((0., -1., 0., 1.), [0., 0.], [-1., 1.]),
    ((10., 1., 10., -1.), [10., 10.], [1., -1.])])
def test_signed_support_projections_retain_end_direction_without_contact(line, along, normal):
    result = nonpublishing_support_projection(line, opening())
    assert result["signed_aperture_axis_coordinates_pt"] == along
    assert result["signed_aperture_normal_coordinates_pt"] == normal
    assert not result["physical_contact_proven"]
    assert not result["host_publication_allowed"]
    rotated = (100.-line[1], 200.+line[0], 100.-line[3], 200.+line[2])
    transformed = nonpublishing_support_projection(rotated,
        replace(opening(), origin=(100., 200.), axis=(0., 1.), normal=(-1., 0.)))
    assert transformed["signed_aperture_axis_coordinates_pt"] == along
    assert transformed["signed_aperture_normal_coordinates_pt"] == normal


@pytest.mark.parametrize("line,geometry,reason", [
    ((True, 0., 1., 0.), opening(), "invalid_source_support_geometry"),
    (("0", 0., 1., 0.), opening(), "invalid_source_support_geometry"),
    ((float("nan"), 0., 1., 0.), opening(), "invalid_source_support_geometry"),
    ((0., 0., 0., 0.), opening(), "invalid_source_support_segment_length"),
    ((-1.7e308, 0., 1.7e308, 0.), opening(), "invalid_source_support_segment_length"),
    ((1.7e308, 0., 1.7e308, 1.), replace(opening(), origin=(-1.7e308, 0.)), "nonfinite_source_support_projection")])
def test_bad_support_projection_retains_negative_reason_and_no_nonfinite_json(line, geometry, reason):
    result = nonpublishing_support_projection(line, geometry)
    assert result["geometry_disposition"] == reason
    assert "signed_aperture_axis_coordinates_pt" not in result
    assert not result["physical_contact_proven"]
    json.dumps(result, allow_nan=False)


def test_removed_edge_does_not_mean_parent_lost_when_another_edge_retains_it():
    graph = snapped_duplicate_graph()
    graph["nodes"].append({"id": 2, "x": 1.5, "y": 20., "degree": 1})
    graph["edges"].append({"id": "independently-retained", "a": 1, "b": 2,
        "x1": 1.5, "y1": 10., "x2": 1.5, "y2": 20.,
        "primitive_lineage": {"source_primitive_ids": ["source-b"]}})
    census = nonpublishing_w2_w4_edge_membership(nonpublishing_w2_deduplication_receipts(graph), [])
    report = nonpublishing_w2_parent_stage_receipts(census)
    parent = next(r for r in report["source_parent_stage_receipts"] if r["source_primitive_id"] == "source-b")
    assert parent["removed_w2_source_edge_ids"] == ["removed"]
    assert parent["retained_w3_source_edge_ids"] == ["independently-retained"]
    assert not parent["source_parent_removed_from_entire_w3_inventory"]
    assert parent["source_ancestry_disposition"] == "W3_PARENT_RETAINED_NO_USABLE_W4_EDGE_MEMBERSHIP"
    assert not parent["source_parents_transferred_to_w4"]
    assert not parent["host_publication_allowed"]


def test_removed_only_parent_and_unknown_lineage_are_explicit_negative_stages():
    graph = snapped_duplicate_graph()
    graph["edges"][0]["primitive_lineage"] = None
    census = nonpublishing_w2_w4_edge_membership(nonpublishing_w2_deduplication_receipts(graph), [])
    report = nonpublishing_w2_parent_stage_receipts(census)
    assert report["w2_edges_with_unknown_parent_inventory"] == ["kept"]
    assert len(report["source_parent_stage_receipts"]) == 1
    parent = report["source_parent_stage_receipts"][0]
    assert parent["source_ancestry_disposition"] == "W2_PARENT_ONLY_REMOVED_EDGES"
    assert parent["source_parent_removed_from_entire_w3_inventory"]
    assert parent["actual_usable_w4_edge_memberships"] == []


def test_multiple_w4_parent_memberships_remain_alternatives_after_source_splitting():
    census = nonpublishing_w2_deduplication_receipts(snapped_duplicate_graph())
    records = [geometric_record(cid, "source-a", "kept", (0., 0., 0., 10.)) for cid in ("a", "b")]
    report = nonpublishing_w2_parent_stage_receipts(nonpublishing_w2_w4_edge_membership(census, records))
    parent = report["source_parent_stage_receipts"][0]
    assert parent["source_ancestry_disposition"] == "USABLE_W4_EDGE_MEMBERSHIP_OBSERVED"
    assert parent["actual_usable_w4_edge_memberships"] == [
        {"source_edge_id": "kept", "wall_candidate_id": "a"},
        {"source_edge_id": "kept", "wall_candidate_id": "b"}]
    assert not parent["host_publication_allowed"]


def test_conflicting_shared_w4_edge_address_quarantines_every_alternative():
    census = nonpublishing_w2_deduplication_receipts(snapped_duplicate_graph())
    records = [geometric_record("a", "source-a", "kept", (0., 0., 0., 10.)),
               geometric_record("b", "source-a", "kept", (1., 0., 1., 10.))]
    row = nonpublishing_w2_w4_edge_membership(census, records)["all_w2_edge_receipts"][0]
    assert all(r["source_edge_address_conflicted"] for r in row["actual_w4_edge_membership_alternatives"])
    assert not any(r["w4_membership_receipt_usable"] for r in row["actual_w4_edge_membership_alternatives"])


def test_raster_cache_authenticates_once_for_identical_scope_and_is_immutable(monkeypatch):
    import tools.diag_gptmax_raster_host_source_membership as diagnostic
    calls = []
    source = {"parent": [0., 0., 10., 0.]}
    def authenticate(authority, existence, ids):
        calls.append((authority, existence, ids))
        return source
    monkeypatch.setattr(diagnostic, "_authenticated_raster_source_lines", authenticate)
    cache = DiagnosticRasterLineCache()
    authority = CacheAuthority()
    first = cache.resolve(authority, support_opening(), ("b", "a"), published=cache_published(support_opening()))
    second = cache.resolve(authority, support_opening(), ("a", "b"), published=cache_published(support_opening()))
    assert first is second
    assert len(calls) == 1
    source["parent"][0] = 99.
    assert first["parent"] == (0., 0., 10., 0.)
    with pytest.raises(TypeError):
        first["parent"] = (9., 0., 10., 0.)
    with pytest.raises(TypeError):
        first["parent"][0] = 9.


@pytest.mark.parametrize("field", ["document_id", "revision_id", "source_sha256", "snapshot_id", "page_id", "viewport_id", "source_observation_ids", "authority"])
def test_raster_cache_never_reuses_foreign_scope_or_changed_line_inventory(monkeypatch, field):
    import tools.diag_gptmax_raster_host_source_membership as diagnostic
    calls = []
    def authenticate(authority, existence, ids):
        calls.append((authority, existence, ids))
        return {f"parent-{len(calls)}": (0., 0., 10., 0.)}
    monkeypatch.setattr(diagnostic, "_authenticated_raster_source_lines", authenticate)
    cache = DiagnosticRasterLineCache()
    authority = CacheAuthority()
    existence = support_opening()
    first = cache.resolve(authority, existence, ("a",), published=cache_published(existence))
    changed = deepcopy(existence)
    ids = ("a",)
    if field == "authority":
        authority = CacheAuthority()
    elif field == "source_observation_ids":
        ids = ("a", "b")
    else:
        setattr(changed, field, "foreign")
    second = cache.resolve(authority, changed, ids, published=cache_published(changed))
    assert len(calls) == 2
    assert first != second


@pytest.mark.parametrize("field", ["document_id", "revision_id", "source_sha256", "snapshot_id", "page_id"])
def test_incomplete_raster_cache_scope_cannot_create_or_reuse_entry(monkeypatch, field):
    import tools.diag_gptmax_raster_host_source_membership as diagnostic
    monkeypatch.setattr(diagnostic, "_authenticated_raster_source_lines", lambda *args: pytest.fail("must not authenticate an incomplete scope"))
    existence = support_opening()
    setattr(existence, field, None)
    with pytest.raises(ValueError, match="incomplete raster line source cache scope"):
        DiagnosticRasterLineCache().resolve(CacheAuthority(), existence, ("a",), published=cache_published(existence))


@pytest.mark.parametrize("corruption", [None, [], {"nodes": True, "edges": []},
    {"nodes": [], "edges": "edge"}, {"nodes": [None], "edges": []},
    {"nodes": [], "edges": [None]}])
def test_non_graph_containers_never_enter_production_deduplication(corruption):
    with pytest.raises(TypeError, match="W2 deduplication.*inventory"):
        nonpublishing_w2_deduplication_receipts(corruption)


class CacheAuthority:
    def __init__(self):
        self.damaged = False
        self.payload = "sealed-source-payload"
        self.validations = 0

    def source_visibility_authority(self):
        return self

    def authenticated_visible_observations(self, published):
        self.validations += 1
        if self.damaged:
            raise RuntimeError("producer_integrity_failure")
        return (("a", SimpleNamespace(observation_payload_sha256=self.payload)),)


def cache_published(existence):
    return SimpleNamespace(revision=SimpleNamespace(document_id=existence.document_id,
        revision_id=existence.revision_id, source_sha256=existence.source_sha256),
        snapshot=SimpleNamespace(snapshot_id=existence.snapshot_id))


def test_warm_raster_cache_reauthenticates_source_and_never_replays_damaged_snapshot(monkeypatch):
    import tools.diag_gptmax_raster_host_source_membership as diagnostic
    monkeypatch.setattr(diagnostic, "_authenticated_raster_source_lines", lambda *args: {"p": (0., 0., 10., 0.)})
    authority = CacheAuthority()
    existence = support_opening()
    cache = DiagnosticRasterLineCache()
    cache.resolve(authority, existence, ("a",), published=cache_published(existence))
    authority.damaged = True
    with pytest.raises(RuntimeError, match="producer_integrity_failure"):
        cache.resolve(authority, existence, ("a",), published=cache_published(existence))
    assert authority.validations == 2


def test_raster_cache_key_includes_reauthenticated_source_manifest(monkeypatch):
    import tools.diag_gptmax_raster_host_source_membership as diagnostic
    calls = []
    def lines(*args):
        calls.append(args)
        return {"p": (float(len(calls)), 0., 10., 0.)}
    monkeypatch.setattr(diagnostic, "_authenticated_raster_source_lines", lines)
    cache = DiagnosticRasterLineCache()
    authority = CacheAuthority()
    existence = support_opening()
    first = cache.resolve(authority, existence, ("a",), published=cache_published(existence))
    authority.payload = "different-reauthenticated-source-payload"
    second = cache.resolve(authority, existence, ("a",), published=cache_published(existence))
    assert len(calls) == 2
    assert first != second


def test_raster_cache_rejects_foreign_published_snapshot_before_lookup(monkeypatch):
    import tools.diag_gptmax_raster_host_source_membership as diagnostic
    monkeypatch.setattr(diagnostic, "_authenticated_raster_source_lines", lambda *args: pytest.fail("must not authenticate foreign source"))
    existence = support_opening()
    published = cache_published(existence)
    published.snapshot.snapshot_id = "foreign"
    with pytest.raises(ValueError, match="published source scope mismatch"):
        DiagnosticRasterLineCache().resolve(CacheAuthority(), existence, ("a",), published=published)
