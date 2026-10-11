"""Exact-source native figured witness contacts are candidates, not room areas."""
from types import SimpleNamespace as NS
import pytest
from tools.diag_gpt2_room_wall_dimension_endpoints import (
    inspect_source_face_dimension_endpoints as inspect,
)

def face(edges=None):
    return NS(record_id="source-face-record-a",boundary_wall_edges=edges if edges is not None else (
        ("source-wall-left",((0.,0.),(0.,10.))),
        ("source-wall-right",((20.,0.),(20.,10.))),
    ))

def dimension(endpoints):
    return NS(observation_id="native-figured-1",status="witness_bound",
              dimension_line_id="source-dimension-line-1",
              witness_line_ids=("native-witness-1","native-witness-2"),
              endpoints=endpoints)

def test_exact_source_wall_contacts_are_candidate_only_never_metric():
    v=inspect(face(),dimension(((0.,5.),(20.,5.))))
    assert v["first_authority_gate"]=="two_source_wall_endpoint_contacts_candidate_only"
    assert v["endpoint_wall_owner_ids"]==[["source-wall-left"],["source-wall-right"]]
    assert v["room_dimension_owned"] is False
    assert v["metric_area_published"] is False

def test_native_dimension_text_or_line_outside_face_stays_unbound():
    for endpoints in (((0.2,5.),(20.,5.)),((50.,5.),(60.,5.))):
        v=inspect(face(),dimension(endpoints))
        assert v["first_authority_gate"]=="figured_endpoint_not_on_source_room_wall"
        assert v["metric_area_published"] is False

def test_missing_source_subedges_or_witness_span_abstains():
    assert inspect(face(()),dimension(((0.,5.),(20.,5.))))["first_authority_gate"]=="source_owned_wall_subedges_missing"
    assert inspect(face(),dimension(None))["first_authority_gate"]=="source_dimension_endpoints_unbound"

def test_competing_source_wall_id_on_same_edge_abstains():
    f=face((
        ("wall-a",((0.,0.),(0.,10.))),
        ("wall-b",((0.,0.),(0.,10.))),
        ("wall-c",((20.,0.),(20.,10.))),
    ))
    assert inspect(f,dimension(((0.,5.),(20.,5.))))["first_authority_gate"]=="figured_endpoint_competing_source_wall_owners"

def test_two_endpoints_on_one_wall_do_not_measure_span():
    assert inspect(face(),dimension(((0.,2.),(0.,8.))))["first_authority_gate"]=="figured_endpoints_same_wall_no_span"

def test_corner_touch_with_two_owners_stays_ambiguous():
    f=face((
        ("bottom",((0.,0.),(20.,0.))),
        ("left",((0.,0.),(0.,10.))),
        ("right",((20.,0.),(20.,10.))),
    ))
    assert inspect(f,dimension(((0.,0.),(20.,5.))))["first_authority_gate"]=="figured_endpoint_competing_source_wall_owners"

@pytest.mark.parametrize("tol",[0,0.01,float("nan"),-0.01])
def test_tolerance_cannot_relax_actual_native_wall_evidence(tol):
    with pytest.raises(ValueError):
        inspect(face(),dimension(((0.,5.),(20.,5.))),tolerance_pdf_pt=tol)


def test_malformed_source_endpoint_and_wall_edge_rows_abstain():
    for endpoints in (123, "not-an-endpoint", (), ((0.,5.),)):
        row=inspect(face(),dimension(endpoints))
        assert row["first_authority_gate"]=="source_dimension_endpoints_unbound"
        assert row["room_dimension_owned"] is False
    malformed=face((("wall-a",),))
    row=inspect(malformed,dimension(((0.,5.),(20.,5.))))
    assert row["first_authority_gate"]=="source_owned_wall_subedges_malformed"
    assert row["metric_area_published"] is False


def test_figured_endpoint_contact_does_not_underflow_or_divide_by_tiny_wall():
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        _point_on_native_source_subedge,
    )
    epsilon_wall = ((0.0, 0.0), (1e-310, 0.0))
    assert not _point_on_native_source_subedge(
        (0.0, 0.0), epsilon_wall, tolerance=0.0001
    )
    result = inspect(
        face((("microscopic-wall", epsilon_wall),)),
        dimension(((0.0, 0.0), (0.0, 0.0))),
    )
    assert result["first_authority_gate"] == "figured_endpoint_not_on_source_room_wall"
    assert result["room_dimension_owned"] is False
    assert result["metric_area_published"] is False


def test_figured_endpoint_contact_handles_large_finite_native_spans():
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        _point_on_native_source_subedge,
    )
    source_edge = ((0.0, 0.0), (1e180, 0.0))
    assert _point_on_native_source_subedge(
        (5e179, 0.0), source_edge, tolerance=0.0001
    )
    assert not _point_on_native_source_subedge(
        (-1.0, 0.0), source_edge, tolerance=0.0001
    )
    assert not _point_on_native_source_subedge(
        (5e179, 1.0), source_edge, tolerance=0.0001
    )
    # The first-gate ledger still cannot turn two on-wall contacts into a
    # metric room area or authenticated dimension witness.
    second_edge = ((-1e180, 0.0), (-1e179, 0.0))
    result = inspect(
        face((("long-a", source_edge), ("long-b", second_edge))),
        dimension(((5e179, 0.0), (-5e179, 0.0))),
    )
    assert result["first_authority_gate"] == "two_source_wall_endpoint_contacts_candidate_only"
    assert result["room_dimension_owned"] is False
    assert result["metric_area_published"] is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_native_figured_endpoint_geometry_stays_unbound(bad):
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        _point_on_native_source_subedge,
    )
    assert not _point_on_native_source_subedge(
        (bad, 5.0), ((0.0, 0.0), (0.0, 10.0)), tolerance=0.0001
    )
    assert not _point_on_native_source_subedge(
        (0.0, 5.0), ((0.0, 0.0), (bad, 10.0)), tolerance=0.0001
    )
    assert inspect(face(), dimension(((bad, 5.0), (20.0, 5.0))))[
        "first_authority_gate"
    ] == "figured_endpoint_not_on_source_room_wall"


def test_gpt2_source_endpoint_distance_is_nonpublishing_first_failure_only():
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        _native_point_to_source_subedge_distance,
    )
    edge=((0.,0.),(0.,10.))
    assert _native_point_to_source_subedge_distance((0.,5.),edge)==0.0
    assert _native_point_to_source_subedge_distance((2.,5.),edge)==2.0
    assert _native_point_to_source_subedge_distance((0.,13.),edge)==3.0
    report=inspect(face(),dimension(((2.,5.),(18.,5.))))
    assert report["first_authority_gate"]=="figured_endpoint_not_on_source_room_wall"
    assert report["endpoint_nearest_source_wall_distance_pdf_pts_diagnostic_only"]==[2.0,2.0]
    assert report["room_dimension_owned"] is False
    assert report["metric_area_published"] is False


@pytest.mark.parametrize("point,edge", [
    ((float("nan"),1.),((0.,0.),(0.,10.))),
    ((float("inf"),1.),((0.,0.),(0.,10.))),
    ((1.,1.),((0.,0.),(float("inf"),10.))),
    ((1.,1.),((0.,0.),(0.,0.))),
    ("bad",((0.,0.),(0.,10.))),
    ((1.,1.),"missing"),
])
def test_gpt2_no_nonfinite_or_unsupported_nearest_source_wall_distance(point,edge):
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        _native_point_to_source_subedge_distance,
    )
    assert _native_point_to_source_subedge_distance(point,edge) is None


def test_gpt2_unbound_figured_endpoints_have_no_pseudo_wall_distances():
    report=inspect(face(),dimension(None))
    assert report["first_authority_gate"]=="source_dimension_endpoints_unbound"
    assert report["endpoint_nearest_source_wall_distance_pdf_pts_diagnostic_only"]==[]
    assert not report["room_dimension_owned"]
    assert not report["metric_area_published"]


def test_gpt2_mixed_invalid_endpoint_distance_remains_safe_nonpublishing():
    row=inspect(face(),dimension(((float("nan"),5.),(20.,5.))))
    assert row["first_authority_gate"]=="figured_endpoint_not_on_source_room_wall"
    assert row["endpoint_nearest_source_wall_distance_pdf_pts_diagnostic_only"]==[
        None,0.0
    ]
    # A broken witness does not inherit the other endpoint's valid wall.
    assert row["endpoint_wall_owner_ids"]==[[],["source-wall-right"]]
    assert row["room_dimension_owned"] is False
    assert row["metric_area_published"] is False


def test_gpt2_source_figure_text_room_locality_is_candidate_only():
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        source_native_dimension_text_room_locality,
    )
    f=face()
    f.polygon_pdf_pts=((0.,0.),(20.,0.),(20.,10.),(0.,10.))
    inside=NS(dimension_id="figure-1",bbox=(2.,2.,4.,4.))
    outside=NS(dimension_id="figure-2",bbox=(30.,2.,32.,4.))
    yes=source_native_dimension_text_room_locality(f,inside)
    no=source_native_dimension_text_room_locality(f,outside)
    assert yes["first_spatial_gate"]==(
        "native_dimension_text_centre_inside_source_room_candidate_only"
    )
    assert yes["native_room_text_spatial_candidate_only"] is True
    assert no["first_spatial_gate"]=="native_dimension_text_outside_source_room"
    assert no["native_room_text_spatial_candidate_only"] is False
    for item in (yes,no):
        assert item["room_dimension_owned"] is False
        assert item["metric_area_published"] is False


@pytest.mark.parametrize("bbox", [
    None, (), (0.,0.,0.,2.), (0.,0.,float("nan"),2.),
    (0.,0.,float("inf"),2.), (0.,0.,1.), ("invalid",0,1,1)
])
def test_gpt2_missing_native_dimension_text_bbox_does_not_prove_room_locality(bbox):
    from tools.diag_gpt2_room_wall_dimension_endpoints import (
        source_native_dimension_text_room_locality,
    )
    f=face()
    f.polygon_pdf_pts=((0.,0.),(20.,0.),(20.,10.),(0.,10.))
    result=source_native_dimension_text_room_locality(
        f,NS(dimension_id="fig",bbox=bbox),
    )
    assert result["first_spatial_gate"]=="native_dimension_text_geometry_unavailable"
    assert not result["native_room_text_spatial_candidate_only"]
    assert not result["room_dimension_owned"]
