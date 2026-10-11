"""Proof-aware W2 short source fragment audit: zero geometry authority."""
from copy import deepcopy
import math
import pytest

from pb_wall_room_topology_short_fragment_audit import audit_short_source_fragments


def fragment(fid="split_1", coords=(10.,10.,11.22,10.), *, parent=None):
    if parent is None:
        parent=(10.,10.,30.,10.)
    primitive_id="raster_segment:real-source-sha:1.0.0:1585"
    return {
        "id":fid,
        "x1":coords[0],"y1":coords[1],
        "x2":coords[2],"y2":coords[3],
        "primitive_lineage":{
            "source_primitive_ids":[primitive_id],
            "source_records":[{
                "id":primitive_id,"page_coords_present":True,
                "x1":parent[0],"y1":parent[1],
                "x2":parent[2],"y2":parent[3],
            }],
        },
    }


def graph(fid="split_1", *, a=(10.,10.), b=(11.22,10.), raw=True, merged=False):
    snapped={
        "nodes":[{"id":0,"x":a[0],"y":a[1]},
                 {"id":1,"x":b[0],"y":b[1]}],
        "edges":[{"id":fid,"a":0,"b":1}] if raw else [],
        "endpoint_snap_assignments": {fid: (0, 1) if raw else (0, 0)},
    }
    if merged:
        snapped["edges"].append({"id":"split_2","a":0,"b":1})
    merged_graph={"edges":[
        {"id":"merged_split_1_split_2",
         "collinear_merge_leaf_edge_ids":[fid,"split_2"]}
    ]} if merged else {"edges":[{"id":fid}]} if raw else {"edges":[]}
    return snapped, merged_graph


def audit(fragments, snapped, merged):
    return audit_short_source_fragments(fragments,snapped,merged,max_length_pt=2.5)


def test_positive_source_one_point_two_two_fragment_retained_without_mutation():
    f=fragment()
    s,m=graph()
    original=deepcopy((f,s,m))
    result=audit([f],s,m)
    assert result["w2_retention_reason_counts"]=={"RETAINED_RAW_EDGE":1}
    assert result["original_positive_source_short_fragments"][0]["original_source_length_pt"]==pytest.approx(1.22)
    assert result["original_positive_source_short_fragments"][0]["max_endpoint_snap_displacement_pt"]==0
    assert (f,s,m)==original
    assert not result["physical_host_publication_allowed"]
    assert not result["opening_count_publication_allowed"]
    assert result["benchmark_accuracy"] is None


def test_true_w2_snap_collapse_retains_source_proof_but_never_restores_edge():
    f=fragment(coords=(10.,10.,11.9,10.))
    s,m=graph(raw=False)
    result=audit([f],s,m)
    assert result["w2_retention_reason_counts"]=={"SNAP_COLLAPSED":1}
    witness=result["original_positive_source_short_fragments"][0]
    assert witness["snapped_endpoint_node_ids"] == [0, 0]
    assert witness["max_endpoint_snap_displacement_pt"] == pytest.approx(1.9)
    assert witness["original_source_geometry_pt"]==[10.,10.,11.9,10.]
    assert witness["wall_host_authority"]=="NOT_PROVEN_BY_THIS_AUDIT"
    assert not s["edges"]


def test_source_fragment_collinear_merge_keeps_exact_leaf_ancestry():
    f=fragment()
    s,m=graph(merged=True)
    r=audit([f],s,m)
    assert r["w2_retention_reason_counts"]=={"COLLINEAR_MERGED":1}


def test_displaced_source_endpoints_are_observed_not_snapped_again():
    f=fragment()
    s,m=graph(a=(10.3,10.),b=(11.22,10.))
    original=deepcopy(s)
    r=audit([f],s,m)
    assert r["original_positive_source_short_fragments"][0][
        "max_endpoint_snap_displacement_pt"]==pytest.approx(.3)
    assert s==original


@pytest.mark.parametrize("raw", [True, False])
def test_finite_nodes_cannot_emit_overflowed_displacement(raw):
    f = fragment()
    s, m = graph(a=(1.7e308, 1.7e308), b=(1.6e308, 1.6e308), raw=raw)
    assert all(math.isfinite(n[k]) for n in s["nodes"] for k in ("x", "y"))
    original = deepcopy((f, s, m))
    with pytest.raises(ValueError, match="nonfinite W2 endpoint displacement"):
        audit([f], s, m)
    assert (f, s, m) == original


@pytest.mark.parametrize("change", [
    "unknown_parent", "multi_parent","different_parent","false_source_page",
    "uncorroborated_short_gap","source_off_axis","wrong_parent_end",
])
def test_missing_or_conflicting_source_parent_cannot_become_host_witness(change):
    f=fragment()
    lin=f["primitive_lineage"]
    if change=="unknown_parent": lin["source_records"]=[]
    elif change=="multi_parent":
        lin["source_primitive_ids"].append("unrelated-positive-parent")
    elif change=="different_parent":
        lin["source_records"][0]["id"]="unrelated"
    elif change=="false_source_page":
        lin["source_records"][0]["page_coords_present"]=False
    elif change=="uncorroborated_short_gap":
        lin["source_primitive_ids"]=[]
    elif change=="source_off_axis":
        lin["source_records"][0]["y1"]=11.
    else:
        lin["source_records"][0]["x2"]=10.5
    s,m=graph()
    result=audit([f],s,m)
    assert result["observed_positive_source_short_fragment_count"]==0
    assert result["w2_retention_reason_counts"]=={"UNPROVEN_SOURCE_PARENT_SKIPPED":1}
    assert not result["physical_host_publication_allowed"]


@pytest.mark.parametrize("bad", [
    float("nan"),float("inf"),0.,-1.,True,None,
])
def test_invalid_observation_length_fails_closed(bad):
    s,m=graph()
    with pytest.raises(ValueError):
        audit_short_source_fragments([fragment()],s,m,max_length_pt=bad)


@pytest.mark.parametrize("change",["duplicate_id","nonfinite","missing_geometry","invalid_final_leaf","snap_missing_node","collapsed_reappears_as_merge"])
def test_corrupted_w2_inventory_fails_closed(change):
    f=fragment()
    s,m=graph()
    inventory=[f]
    if change=="duplicate_id":
        inventory.append(deepcopy(f))
    elif change=="nonfinite":
        f["x1"]=float("nan")
    elif change=="missing_geometry":
        del f["x1"]
    elif change=="invalid_final_leaf":
        m["edges"][0]["collinear_merge_leaf_edge_ids"]=[None]
    elif change=="snap_missing_node":
        s["nodes"].pop()
    else:
        s["edges"]=[]
        m["edges"][0]["collinear_merge_leaf_edge_ids"]=[f["id"]]
    with pytest.raises(ValueError):
        audit(inventory,s,m)


def test_full_length_original_line_does_not_claim_short_fragment_authority():
    f=fragment(coords=(10.,10.,20.,10.))
    s,m=graph()
    result=audit([f],s,m)
    assert result["original_positive_source_short_fragments"]==[]
    assert result["observed_positive_source_short_fragment_count"]==0


def test_real_short_vertical_end_remains_observation_not_missing_gap_closure():
    f=fragment("split_324",(582.6,531.25,584.5,531.25),parent=(500.,531.25,584.5,531.25))
    s,m=graph("split_324",a=(582.6,531.25),b=(582.8,531.25))
    r=audit([f],s,m)
    assert r["observed_positive_source_short_fragment_count"]==1
    w=r["original_positive_source_short_fragments"][0]
    assert w["max_endpoint_snap_displacement_pt"]==pytest.approx(1.7)
    assert w["source_gap_closure"]=="NOT_PROVEN_BY_THIS_AUDIT"
    assert not r["metric_quantity_publication_allowed"]



def test_w2_opt_in_trace_never_changes_existing_graph_authority(monkeypatch):
    from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport

    source=[{
        "id":"native_source_line_real_positive",
        "kind":"line","x1":0.,"y1":0.,"x2":8.,"y2":0.,
        "width":1.,"stroke":(0,0,0),
    }]
    monkeypatch.delenv("GPTMAX_W2_SHORT_SOURCE_AUDIT",raising=False)
    base=build_wall_graph_for_viewport(source)
    assert "short_source_fragment_retention_audit" not in base

    monkeypatch.setenv("GPTMAX_W2_SHORT_SOURCE_AUDIT","1")
    traced=build_wall_graph_for_viewport(source)
    witness=traced.pop("short_source_fragment_retention_audit")
    assert traced==base
    assert witness["physical_host_publication_allowed"] is False
    assert witness["opening_count_publication_allowed"] is False
    assert witness["metric_quantity_publication_allowed"] is False


def test_producer_reported_disappearance_is_not_proven_snap_collapse():
    f=fragment(coords=(10.,10.,11.9,10.))
    s,m=graph(raw=False)
    del s["endpoint_snap_assignments"]
    r=audit_short_source_fragments([f],s,m,max_length_pt=2.5,
        producer_reported_collapsed_fragments=[{"id":"split_1","reason":"snap_collapsed"}])
    assert r["w2_retention_reason_counts"]=={"PRODUCER_REPORTED_EDGE_ABSENT":1}
    assert not r["physical_host_publication_allowed"]
    assert not r["opening_count_publication_allowed"]
    with pytest.raises(ValueError):
        audit_short_source_fragments([f],s,m,max_length_pt=2.5,
            producer_reported_collapsed_fragments=[{"id":"split_1"},{"id":"split_1"}])


def test_disappearance_receipt_must_reference_an_absent_original_split_edge():
    f=fragment()
    surviving,merged=graph()
    with pytest.raises(ValueError, match="conflicts"):
        audit_short_source_fragments([f],surviving,merged,max_length_pt=2.5,
            producer_reported_collapsed_fragments=[{"id":"split_1"}])
    absent,empty=graph(raw=False)
    with pytest.raises(ValueError, match="conflicts"):
        audit_short_source_fragments([f],absent,empty,max_length_pt=2.5,
            producer_reported_collapsed_fragments=[{"id":"unrelated_split"}])


def test_absent_edge_without_actual_endpoint_trace_is_unresolved():
    s, m = graph(raw=False)
    del s["endpoint_snap_assignments"]
    result = audit([fragment()], s, m)
    witness = result["original_positive_source_short_fragments"][0]
    assert witness["w2_observation"] == "EDGE_ABSENT_UNRESOLVED"
    assert witness["snapped_endpoint_node_ids"] is None
    assert witness["max_endpoint_snap_displacement_pt"] is None
    assert not result["physical_host_publication_allowed"]


@pytest.mark.parametrize("change", [
    "duplicate_node", "duplicate_edge", "missing_collapsed_node",
    "distinct_missing_endpoints", "retained_trace_disagrees", "bool_node",
    "nonfinite_node", "duplicate_merge_leaf", "foreign_merge_leaf",
    "shared_merge_leaf", "invalid_assignments", "foreign_assignment",
])
def test_invalid_endpoint_trace_never_claims_positive_collapse(change):
    s, m = graph(raw=False)
    if change == "duplicate_node":
        s["nodes"].append(deepcopy(s["nodes"][0]))
    elif change == "duplicate_edge":
        s, m = graph()
        s["edges"].append(deepcopy(s["edges"][0]))
    elif change == "missing_collapsed_node":
        s["endpoint_snap_assignments"]["split_1"] = (9, 9)
    elif change == "distinct_missing_endpoints":
        s["endpoint_snap_assignments"]["split_1"] = (0, 1)
    elif change == "retained_trace_disagrees":
        s, m = graph()
        s["endpoint_snap_assignments"]["split_1"] = (1, 0)
    elif change == "bool_node":
        s["nodes"][0]["id"] = False
    elif change == "nonfinite_node":
        s["nodes"][0]["x"] = math.inf
    elif change == "duplicate_merge_leaf":
        s, m = graph(merged=True)
        m["edges"][0]["collinear_merge_leaf_edge_ids"].append("split_1")
    elif change == "foreign_merge_leaf":
        s, m = graph(merged=True)
        m["edges"][0]["collinear_merge_leaf_edge_ids"].append("foreign")
    elif change == "shared_merge_leaf":
        s, m = graph(merged=True)
        m["edges"].append({"id":"another", "collinear_merge_leaf_edge_ids":["split_1"]})
    elif change == "invalid_assignments":
        s["endpoint_snap_assignments"] = []
    else:
        s["endpoint_snap_assignments"]["foreign"] = (0, 0)
    with pytest.raises(ValueError):
        audit([fragment()], s, m)


def test_real_snap_operation_records_the_discarded_endpoint_association():
    from pb_wall_room_topology_stage_a import _snap_geometry_indexed

    f = fragment()
    plain = _snap_geometry_indexed([f])
    traced = _snap_geometry_indexed([f], include_endpoint_assignments=True)
    assignments = traced.pop("endpoint_snap_assignments")
    assert traced == plain
    assert assignments == {"split_1": (0, 0)}
    result = audit([f], {**traced, "endpoint_snap_assignments":assignments}, {"edges":[]})
    witness = result["original_positive_source_short_fragments"][0]
    assert witness["snapped_endpoint_node_ids"] == [0, 0]
    assert witness["max_endpoint_snap_displacement_pt"] == pytest.approx(.61)


def test_zero_tolerance_trace_does_not_change_historical_snapper():
    from pb_wall_room_topology_stage_a import _snap_geometry_indexed

    f = fragment()
    traced = _snap_geometry_indexed([f], tolerance_pt=0, include_endpoint_assignments=True)
    assert "endpoint_snap_assignments" not in traced
    assert traced == _snap_geometry_indexed([f], tolerance_pt=0)


@pytest.mark.parametrize("angle, scale, offset", [
    (0., 1., (0., 0.)), (90., 1., (200., -50.)),
    (17., 2., (-100., 250.)), (45., .5, (0., 0.)),
])
def test_endpoint_trace_is_transformed_without_inventing_geometry(angle, scale, offset):
    from pb_wall_room_topology_stage_a import _snap_geometry_indexed

    radians = math.radians(angle)
    def transform(x, y):
        return (offset[0] + scale*(x*math.cos(radians)-y*math.sin(radians)),
                offset[1] + scale*(x*math.sin(radians)+y*math.cos(radians)))
    a, b = transform(10., 10.), transform(11.22, 10.)
    c, d = transform(10., 10.), transform(30., 10.)
    f = fragment(coords=(*a, *b), parent=(*c, *d))
    s = _snap_geometry_indexed([f], tolerance_pt=2.5*scale,
                               include_endpoint_assignments=True)
    r = audit_short_source_fragments([f], s, {"edges":[]}, max_length_pt=2.5*scale)
    w = r["original_positive_source_short_fragments"][0]
    assert w["w2_observation"] == "SNAP_COLLAPSED"
    assert w["max_endpoint_snap_displacement_pt"] == pytest.approx(.61*scale)
    assert w["original_source_geometry_pt"] == [*a, *b]


def test_replay_input_order_and_unrelated_content_preserve_source_observations():
    from pb_wall_room_topology_stage_a import _snap_geometry_indexed

    f = fragment()
    unrelated = fragment("far", (200., 200., 201., 200.), parent=(200., 200., 220., 200.))
    original = deepcopy((f, unrelated))
    observations = []
    for inventory in ([f], [f, unrelated], [unrelated, f], [f, unrelated]):
        s = _snap_geometry_indexed(inventory, include_endpoint_assignments=True)
        result = audit(inventory, s, {"edges":[]})
        w = next(v for v in result["original_positive_source_short_fragments"]
                 if v["source_split_fragment_id"] == f["id"])
        observations.append((w["w2_observation"], w["original_source_geometry_pt"],
                             w["max_endpoint_snap_displacement_pt"]))
    assert all(v == observations[0] for v in observations)
    assert (f, unrelated) == original


@pytest.mark.parametrize("raw", [True, False])
def test_finite_original_source_points_cannot_overflow_raw_fragment_length(raw):
    f = fragment(coords=(1.7e308, 1.7e308, -1.7e308, -1.7e308))
    s, m = graph(raw=raw)
    original = deepcopy((f, s, m))
    assert all(math.isfinite(f[key]) for key in ("x1", "y1", "x2", "y2"))
    with pytest.raises(ValueError, match="nonfinite original split source length"):
        audit([f], s, m)
    assert (f, s, m) == original

@pytest.mark.parametrize("which", [
    "split_fragment", "surviving_edge", "merge_leaf", "disappearance_receipt",
])
def test_whitespace_only_w2_source_receipt_ids_fail_closed(which):
    source = fragment()
    snapped, merged = graph()
    reported = []
    if which == "split_fragment":
        source["id"] = "   "
    elif which == "surviving_edge":
        snapped["edges"][0]["id"] = "   "
    elif which == "merge_leaf":
        merged["edges"][0]["collinear_merge_leaf_edge_ids"] = ["   "]
    elif which == "disappearance_receipt":
        reported = [{"id": "   "}]
    with pytest.raises(ValueError):
        audit_short_source_fragments(
            [source], snapped, merged,
            producer_reported_collapsed_fragments=reported,
            max_length_pt=2.5,
        )
