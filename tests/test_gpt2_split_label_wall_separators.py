"""Split-face labels stay CANDIDATE even across exact W4 source-owned walls."""
from types import SimpleNamespace as Obj
from tools.diag_gpt2_split_label_wall_separators import (
    split_face_source_wall_separator_gate as gate,
)

def candidate(ids=("face-left","face-right")):
    return Obj(
        label="EXAMPLE SPACE",record_id="source-split-candidate",
        source_room_face_record_ids=ids,
        document_id="doc",revision_id="rev",source_sha256="a"*64,
        snapshot_id="snap",page_id="7",decision_scope_id="view:7",
    )

def face(name,wall_id,edge):
    return Obj(
        record_id=name,document_id="doc",revision_id="rev",
        source_sha256="a"*64,snapshot_id="snap",page_id="7",
        decision_scope_id="view:7",
        boundary_wall_edges=((wall_id,edge),),
    )

def sample():
    return {
      "face-left":face("face-left","W4-wall-1",((5.,0.),(5.,10.))),
      "face-right":face("face-right","W4-wall-1",((5.,10.),(5.,0.))),
    }

def test_exact_reverse_edge_with_same_wall_is_separator_not_merge():
    row=gate(candidate(),sample())
    edge=row["pairwise_source_wall_gates"][0]
    assert edge["first_gate"]=="source_proven_wall_separator_do_not_merge"
    assert edge["matching_authenticated_wall_segments"][0]["source_wall_id_a"]=="W4-wall-1"
    assert row["merge_source_faces_authorized"] is False
    assert row["source_room_label_published"] is False

def test_matching_geometry_with_competing_wall_id_rejects():
    faces=sample()
    faces["face-right"]=face("face-right","W4-other",((5.,10.),(5.,0.)))
    row=gate(candidate(),faces)
    assert row["pairwise_source_wall_gates"][0]["first_gate"]=="competing_wall_owners_on_shared_source_edge"
    assert row["merge_source_faces_authorized"] is False

def test_disjoint_face_walls_do_not_imply_join():
    faces=sample()
    faces["face-right"]=face("face-right","W4-wall-1",((15.,10.),(15.,0.)))
    row=gate(candidate(),faces)
    assert row["pairwise_source_wall_gates"][0]["first_gate"]=="no_exact_shared_source_wall_separator"

def test_same_forward_orientation_is_not_proven_opposite_faces():
    faces=sample()
    faces["face-right"]=face("face-right","W4-wall-1",((5.,0.),(5.,10.)))
    assert gate(candidate(),faces)["pairwise_source_wall_gates"][0]["first_gate"]=="no_exact_shared_source_wall_separator"

def test_stale_or_missing_face_or_lineage_abstains():
    assert gate(candidate(),{})["first_gate"]=="split_source_face_record_missing"
    faces=sample()
    faces["face-right"].source_sha256="b"*64
    assert gate(candidate(),faces)["first_gate"]=="split_source_face_lineage_mismatch"

def test_missing_and_duplicate_candidate_face_id_abstains():
    assert gate(candidate(("face-left",)),sample())["first_gate"]=="split_source_face_identity_invalid"
    assert gate(candidate(("face-left","face-left")),sample())["first_gate"]=="split_source_face_identity_invalid"

def test_malformed_wall_subedge_fails_closed():
    faces=sample()
    faces["face-right"].boundary_wall_edges=(("W4-wall-1",((float("nan"),0),(5.,0))),)
    row=gate(candidate(),faces)
    assert row["pairwise_source_wall_gates"][0]["first_gate"]=="malformed_source_wall_subedges"

def test_multiple_faces_pairwise_no_automatic_transitive_join():
    faces=sample()
    faces["third"]=face("third","W4-wall-2",((40.,10.),(40.,0.)))
    row=gate(candidate(("face-left","face-right","third")),faces)
    assert len(row["pairwise_source_wall_gates"])==3
    assert row["merge_source_faces_authorized"] is False
    assert row["metric_quantity_published"] is False


def test_partial_exact_collinear_source_span_is_not_merged_or_absent():
    faces=sample()
    faces["face-right"]=face(
        "face-right","W4-wall-1",((5.,8.),(5.,2.))
    )
    result=gate(candidate(),faces)
    pair=result["pairwise_source_wall_gates"][0]
    assert pair["first_gate"]=="partial_collinear_source_span_requires_w4_proof"
    assert len(pair["partial_collinear_source_spans_observed_only"])==1
    assert pair["matching_authenticated_wall_segments"]==[]
    assert result["merge_source_faces_authorized"] is False
    assert result["source_room_label_published"] is False
    assert result["metric_quantity_published"] is False


def test_partial_collinear_span_other_w4_identity_is_unresolved():
    faces=sample()
    faces["face-right"]=face(
        "face-right","W4-another-identity",((5.,8.),(5.,2.))
    )
    pair=gate(candidate(),faces)["pairwise_source_wall_gates"][0]
    assert pair["first_gate"]=="partial_source_span_competing_wall_owners_unresolved"
    assert len(pair["partial_span_competing_wall_owners_observed_only"])==1


def test_partial_source_wall_spans_reject_offset_direction_and_point_contacts():
    for edge in (
        ((5.0001,8.),(5.0001,2.)),  # drawn parallel, not exact source
        ((5.,2.),(5.,8.)),          # same direction, not facing separator
        ((5.,15.),(5.,10.)),        # shares endpoint only
        ((6.,8.),(5.,2.)),          # not collinear
    ):
        faces=sample()
        faces["face-right"]=face("face-right","W4-wall-1",edge)
        row=gate(candidate(),faces)["pairwise_source_wall_gates"][0]
        assert row["first_gate"]=="no_exact_shared_source_wall_separator"
        assert row["partial_collinear_source_spans_observed_only"]==[]


def test_split_label_diagnostic_rejects_nontext_or_padded_original_face_id():
    for invalid in (None, 73, "", " ", " face-left"):
        row=gate(candidate((invalid,"face-right")),sample())
        assert row["first_gate"]=="split_source_face_identity_invalid"
        assert row["source_room_label_published"] is False
        assert row["metric_quantity_published"] is False


def test_split_label_diagnostic_rejects_missing_or_forged_lineage():
    for attr,bad in (
        ("source_sha256",None),
        ("document_id",""),
        ("revision_id"," "),
        ("snapshot_id",None),
        ("page_id",6),
        ("decision_scope_id","view:7 "),
    ):
        split=candidate()
        setattr(split,attr,bad)
        faces=sample()
        # Even if both sides agree on a malformed source scope, it is
        # not an authenticated original room source identifier.
        setattr(faces["face-left"],attr,bad)
        setattr(faces["face-right"],attr,bad)
        row=gate(split,faces)
        assert row["first_gate"]=="split_source_face_lineage_mismatch"
        assert row["merge_source_faces_authorized"] is False


def test_gpt2_b01_native_near_reverse_edges_are_not_exact_separator_proof():
    for shifted in (
        ((5.0000001,10.),(5.0000001,0.)),
        ((5.,10.0000001),(5.,0.)),
        ((5.,10.),(5.,0.0000001)),
    ):
        faces=sample()
        faces["face-right"]=face("face-right","W4-wall-1",shifted)
        report=gate(candidate(),faces)
        pair=report["pairwise_source_wall_gates"][0]
        assert pair["first_gate"]=="no_exact_shared_source_wall_separator"
        assert pair["matching_authenticated_wall_segments"]==[]
        assert report["merge_source_faces_authorized"] is False
        assert report["metric_quantity_published"] is False


def test_gpt2_b01_overflowing_source_wall_coordinate_never_aborts_diagnostic():
    faces=sample()
    faces["face-right"]=face("face-right","W4-wall-1",(
        (10**500,10.),(5.,0.)
    ))
    row=gate(candidate(),faces)
    assert row["pairwise_source_wall_gates"][0]["first_gate"]==(
        "malformed_source_wall_subedges"
    )
    assert row["merge_source_faces_authorized"] is False
