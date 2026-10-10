"""Exact source receipts and endpoint facts never select or invent a host."""
from copy import deepcopy
import math
from types import SimpleNamespace as NS

import pytest

from pb_opening_host_binding_authority import _OpeningGeometry
from tools.gptmax_raster_flank_ownership import audit_raster_flank_ownership, source_flanks


def fixture():
    lineage=dict(document_id="doc",revision_id="rev",source_sha256="a"*64,
                 snapshot_id="snapshot",page_id="3")
    lines=[(-8.,-2.,0.,-2.),(-8.,2.,0.,2.),(20.,-2.,28.,-2.),
           (20.,2.,28.,2.),(0.,-2.,0.,2.),(20.,-2.,20.,2.)]
    support=[NS(**lineage,observation_id=f"g17-{i}",geometry=line,
                observation_kind="raster_wall_band_face" if i<4 else "raster_wall_band_end")
             for i,line in enumerate(lines)]
    opening_record=NS(**lineage,source_observation_ids=tuple(r.observation_id for r in support))
    geometry=_OpeningGeometry(origin=(0.,0.),axis=(1.,0.),normal=(0.,1.),length=20.,thickness=4.)
    source={"left-parent":(-8.,-1.,0.,-1.),"right-parent":(20.,1.,28.,1.)}
    records=[]
    for role in ("left","right"):
        parent=role+"-parent"
        raw=source[parent]
        w4=((-8.,-1.),(-2.,-1.)) if role=="left" else ((20.,1.),(28.,1.))
        records.append(NS(wall_candidate_id=role,
            physical_identity=NS(wall_candidate_id=role,viewport_id="vp",usable=True,
                                 source_primitive_ids=(parent,)),
            wall_candidate=NS(candidate_id=role,viewport_id="vp",centerline_pts=w4),
            source_edge_fragments=(NS(edge_id=role+"-edge",geometry=raw,source_primitive_ids=(parent,)),),
            source_snap_collapsed_fragments=()))
    return records,source,support,opening_record,geometry


def audit(data=None):
    return audit_raster_flank_ownership(*(fixture() if data is None else data))


def test_exact_source_w2_and_snapped_w4_endpoint_facts_are_separate_and_nonpublishing():
    data=fixture()
    original=deepcopy(data)
    report=audit(data)
    assert data==original
    left=report["flanks"][0]["matching_original_source_primitives"][0]
    owner=left["w4_ancestry_candidates"][0]
    assert left["source_flank_metrics"]["flank_endpoint_distance_pt"]==0
    assert owner["source_edge_fragments"][0]["w2_flank_metrics"]["flank_endpoint_distance_pt"]==0
    assert owner["w4_chain_segments"][0]["w4_flank_metrics"]["flank_endpoint_distance_pt"]==2
    assert not owner["host_contact_proven"]
    assert report["benchmark_accuracy"] is None
    assert all(report[k] is False for k in ("source_scope_authenticated_by_this_audit",
        "host_publication_allowed","opening_count_publication_allowed",
        "metric_quantity_publication_allowed","physical_equivalence_proven"))


@pytest.mark.parametrize("field",["document_id","revision_id","source_sha256","snapshot_id","page_id"])
def test_foreign_support_never_reaches_flank_analysis(field):
    data=fixture()
    setattr(data[2][0],field,"foreign")
    with pytest.raises(ValueError,match="foreign G17"):
        audit(data)


@pytest.mark.parametrize("mutation",["missing","duplicate","substitution"])
def test_support_membership_requires_exact_unique_receipts(mutation):
    data=fixture()
    if mutation=="missing": data[2].pop()
    elif mutation=="duplicate": data[2].append(data[2][0])
    else: data[2][0].observation_id="different-receipt"
    with pytest.raises(ValueError,match="support receipts"):
        audit(data)


@pytest.mark.parametrize("mutation",["one_face","duplicate_end","missing_end","wrong_end","sloping_face"])
def test_incomplete_or_ambiguous_flank_geometry_abstains(mutation):
    data=fixture()
    if mutation=="one_face": data[2][0].observation_kind="other"
    elif mutation=="duplicate_end": data[2][5].geometry=data[2][4].geometry
    elif mutation=="missing_end": data[2][5].observation_kind="other"
    elif mutation=="wrong_end": data[2][4].geometry=(1.,-2.,1.,2.)
    else: data[2][0].geometry=(-8.,-2.,0.,10.)
    with pytest.raises(ValueError,match="G17"):
        audit(data)


@pytest.mark.parametrize("line",[(0.,0.,0.,0.),(0.,0.,math.inf,0.),
    (math.nan,0.,1.,0.),(-1.7e308,0.,1.7e308,0.),(True,0.,1.,0.),(1.,2.,3.)])
def test_invalid_or_overflowing_original_primitive_never_creates_a_match(line):
    data=fixture()
    data[1]["left-parent"]=line
    with pytest.raises(ValueError,match="geometry"):
        audit(data)


def test_source_parent_is_not_evidence_of_a_remote_w2_fragment():
    data=fixture()
    data[0][0].source_edge_fragments[0].geometry=(-50.,-1.,-40.,-1.)
    data[0][0].wall_candidate.centerline_pts=((-50.,-1.),(-40.,-1.))
    owner=audit(data)["flanks"][0]["matching_original_source_primitives"][0]["w4_ancestry_candidates"][0]
    assert not owner["source_edge_fragments"][0]["source_parent_containment_observed"]
    assert not owner["source_edge_fragments"][0]["w2_flank_metrics"]["flank_predicates_pass"]
    assert not owner["w4_chain_segments"][0]["w4_flank_metrics"]["flank_predicates_pass"]
    assert not owner["host_contact_proven"]
    assert owner["first_observed_candidate_failure"]=="w2_geometry_not_contained_in_source_parent"


def test_all_competing_w4_and_edge_receipts_remain_visible():
    data=fixture()
    competitor=deepcopy(data[0][0])
    competitor.wall_candidate_id=competitor.wall_candidate.candidate_id=competitor.physical_identity.wall_candidate_id="competing"
    data[0].append(competitor)
    result=audit(data)
    assert result["edge_receipt_conflicts"]==[{"source_edge_id":"left-edge",
        "w4_candidate_addresses":["competing","left"],"reason":"multiple_surviving_source_edge_receipts"}]
    owners=result["flanks"][0]["matching_original_source_primitives"][0]["w4_ancestry_candidates"]
    assert [r["wall_candidate_id"] for r in owners]==["competing","left"]
    assert all(r["source_edge_fragments"][0]["edge_receipt_conflicted"] for r in owners)
    assert all(r["first_observed_candidate_failure"]=="w2_source_edge_receipt_ownership_conflict" for r in owners)
    assert not result["host_publication_allowed"]


def test_snap_collapsed_source_is_never_a_surviving_edge_or_continuity_proof():
    data=fixture()
    data[0][0].source_snap_collapsed_fragments=(NS(edge_id="lost-end",geometry=(-1.,-1.,0.,-1.),
        source_primitive_ids=("left-parent",),reason_code="both_endpoints_snapped_to_same_node"),)
    row=audit(data)["flanks"][0]["matching_original_source_primitives"][0]
    assert row["collapsed_source_fragments"][0]["source_edge_id"]=="lost-end"
    assert not row["collapsed_source_fragments"][0]["surviving_edge_or_host_evidence"]
    assert [r["source_edge_id"] for r in row["w4_ancestry_candidates"][0]["source_edge_fragments"]]==["left-edge"]


def test_missing_source_parent_reports_first_failure_without_fabricating_a_wall():
    data=fixture()
    data[0].pop(0)
    result=audit(data)
    assert result["flanks"][0]["first_observed_failure"]=="source_primitive_without_w4_parent"
    assert result["flanks"][0]["matching_original_source_primitives"][0]["w4_ancestry_candidates"]==[]
    del data[1]["left-parent"]
    assert audit(data)["flanks"][0]["first_observed_failure"]=="no_source_primitive_at_sealed_flank"


def test_input_order_and_unrelated_source_invariance_and_deterministic_replay():
    data=fixture()
    result=audit(data)
    data[0].reverse()
    data[2].reverse()
    data[1]["unrelated-source"]=(100.,100.,110.,100.)
    assert audit(data)==result==audit(data)


@pytest.mark.parametrize("angle,scale,dx,dy",[(0,1,200,-300),(90,1,0,0),
    (0,2,0,0),(0,.5,0,0)])
def test_rotation_translation_and_scale_preserve_receipt_ownership(angle,scale,dx,dy):
    data=fixture()
    rad=math.radians(angle)
    def point(p):
        x,y=p
        return (scale*(x*math.cos(rad)-y*math.sin(rad))+dx,
                scale*(x*math.sin(rad)+y*math.cos(rad))+dy)
    def line(v): return (*point(v[:2]),*point(v[2:]))
    for r in data[2]: r.geometry=line(r.geometry)
    for k in data[1]: data[1][k]=line(data[1][k])
    for r in data[0]:
        r.wall_candidate.centerline_pts=tuple(point(p) for p in r.wall_candidate.centerline_pts)
        for f in r.source_edge_fragments: f.geometry=line(f.geometry)
    data=(*data[:4],_OpeningGeometry(origin=point((0,0)),axis=(math.cos(rad),math.sin(rad)),
        normal=(-math.sin(rad),math.cos(rad)),length=20*scale,thickness=4*scale))
    result=audit(data)
    assert [f["role"] for f in result["flanks"]]==["left","right"]
    assert [[p["source_primitive_id"] for p in f["matching_original_source_primitives"]] for f in result["flanks"]]==[["left-parent"],["right-parent"]]
    assert not result["host_publication_allowed"]


@pytest.mark.parametrize("angle",[17,135])
def test_arbitrary_rotation_keeps_existing_exact_interval_abstention(angle):
    # The production host predicate groups exact projection intervals. Floating
    # point rotation can separate equal source spans; this diagnostic preserves
    # that abstention and must not introduce another joining tolerance.
    data=fixture()
    rad=math.radians(angle)
    def p(x,y):
        return (x*math.cos(rad)-y*math.sin(rad)+20,
                x*math.sin(rad)+y*math.cos(rad)-40)
    for row in data[2]: row.geometry=(*p(*row.geometry[:2]),*p(*row.geometry[2:]))
    geometry=_OpeningGeometry(origin=(20.,-40.),axis=(math.cos(rad),math.sin(rad)),
        normal=(-math.sin(rad),math.cos(rad)),length=20.,thickness=4.)
    with pytest.raises(ValueError,match="face intervals ambiguous"):
        source_flanks(data[2],data[3],geometry)


def test_splitting_one_source_edge_preserves_parent_ownership_without_inventing_an_edge():
    data=fixture()
    data[0][0].source_edge_fragments=(
        NS(edge_id="left-a",geometry=(-8.,-1.,-4.,-1.),source_primitive_ids=("left-parent",)),
        NS(edge_id="left-b",geometry=(-4.,-1.,0.,-1.),source_primitive_ids=("left-parent",)))
    owner=audit(data)["flanks"][0]["matching_original_source_primitives"][0]["w4_ancestry_candidates"][0]
    assert [f["source_edge_id"] for f in owner["source_edge_fragments"]]==["left-a","left-b"]
    assert all(f["source_parent_containment_observed"] for f in owner["source_edge_fragments"])
    assert not owner["host_contact_proven"]


@pytest.mark.parametrize("failure",["identity","w2_missing","w2_remote","w4_remote"])
def test_candidate_first_failure_distinguishes_the_missing_source_stage(failure):
    data=fixture()
    record=data[0][0]
    if failure=="identity": record.physical_identity.usable=False
    elif failure=="w2_missing": record.source_edge_fragments=()
    elif failure=="w2_remote": record.source_edge_fragments[0].geometry=(-8.,-1.,-6.,-1.)
    else: record.wall_candidate.centerline_pts=((-8.,-1.),(-6.,-1.))
    owner=audit(data)["flanks"][0]["matching_original_source_primitives"][0]["w4_ancestry_candidates"][0]
    assert owner["first_observed_candidate_failure"]=={
        "identity":"w4_source_identity_unavailable",
        "w2_missing":"actual_w2_source_edge_receipt_missing",
        "w2_remote":"local_w2_fragment_misses_sealed_flank",
        "w4_remote":"local_w4_snapped_chain_misses_sealed_flank",
    }[failure]
    assert not owner["host_contact_proven"]


def test_foreign_w2_source_parents_are_reported_separately_from_authentic_membership():
    data=fixture()
    data[0][0].source_edge_fragments[0].source_primitive_ids=("left-parent","foreign-parent")
    report=audit(data)
    assert report["source_edge_parent_identity_contradictions"]==[{
        "source_edge_id":"left-edge","wall_candidate_id":"left",
        "unowned_source_parent_ids":["foreign-parent"]}]
    assert not report["host_publication_allowed"]


def test_source_flank_endpoint_mismatch_keeps_every_aligned_line_without_selecting_nearest():
    data=fixture()
    data[1]["left-parent"]=(-8.,-1.,-3.,-1.)
    data[1]["other-line"]=(-8.,1.,-4.,1.)
    report=audit(data)
    flank=report["flanks"][0]
    assert flank["matching_original_source_primitives"]==[]
    assert flank["first_observed_failure"]=="source_primitive_endpoint_misses_sealed_flank"
    assert [r["source_primitive_id"] for r in flank["original_source_lines_missing_flank_endpoint"]]==["left-parent","other-line"]
    assert [r["source_flank_metrics"]["flank_endpoint_distance_pt"] for r in flank["original_source_lines_missing_flank_endpoint"]]==[3.,4.]
    assert all(not r["host_contact_proven"] for r in flank["original_source_lines_missing_flank_endpoint"])
    assert not report["host_publication_allowed"]
