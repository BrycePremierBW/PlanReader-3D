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
