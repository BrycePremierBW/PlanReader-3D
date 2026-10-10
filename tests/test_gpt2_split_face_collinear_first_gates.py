"""No collinear or partial geometry can authorize a room face union."""
from types import SimpleNamespace as O
from tools.diag_gpt2_split_face_collinear_first_gates import _overlap, audit_collinear_candidates


def test_partial_collinear_overlap_is_diagnostic_only():
    assert _overlap(((0, 0), (10, 0)), ((5, 0), (15, 0))) == 5
    assert _overlap(((0, 0), (10, 0)), ((5, 1), (15, 1))) == 0
    assert _overlap(((0, 0), (10, 0)), ((10, 0), (15, 0))) == 0


def test_split_face_candidates_never_grant_authority():
    fields = dict(document_id="doc", revision_id="rev", source_sha256="a"*64,
                  snapshot_id="snap", page_id="7", decision_scope_id="view")
    candidate = O(label="ROOM", source_room_face_record_ids=("a", "b"), **fields)
    a = O(record_id="a", boundary_wall_edges=(("W1", ((0, 0), (10, 0))),), **fields)
    b = O(record_id="b", boundary_wall_edges=(("W1", ((15, 0), (5, 0))),), **fields)
    result = audit_collinear_candidates(candidate, {"a": a, "b": b})
    assert result["first_gate"] == "collinear_candidates_untrusted"
    assert result["candidate_shared_spans"][0]["overlap_pdf_points"] == 5
    assert result["merge_source_faces_authorized"] is False
    assert result["source_room_label_published"] is False
    assert result["metric_quantity_published"] is False
    b.source_sha256 = "b"*64
    assert audit_collinear_candidates(candidate, {"a": a, "b": b})["first_gate"] == "source_lineage_conflict"


def test_different_wall_identity_stays_candidate_only():
    fields = dict(document_id="doc", revision_id="rev", source_sha256="a"*64,
                  snapshot_id="snap", page_id="7", decision_scope_id="view")
    candidate = O(label="ROOM", source_room_face_record_ids=("a", "b"), **fields)
    a = O(record_id="a", boundary_wall_edges=(("W1", ((0, 0), (10, 0))),), **fields)
    b = O(record_id="b", boundary_wall_edges=(("W2", ((5, 0), (15, 0))),), **fields)
    row = audit_collinear_candidates(candidate, {"a": a, "b": b})
    assert row["candidate_shared_spans"][0]["wall_id_agrees"] is False
    assert row["merge_source_faces_authorized"] is False


def test_malformed_source_edge_fails_closed():
    fields = dict(document_id="doc", revision_id="rev", source_sha256="a"*64,
                  snapshot_id="snap", page_id="7", decision_scope_id="view")
    candidate = O(label="ROOM", source_room_face_record_ids=("a", "b"), **fields)
    a = O(record_id="a", boundary_wall_edges=(("W1", ((0, 0), (10, 0))),), **fields)
    b = O(record_id="b", boundary_wall_edges=(("W1", ((float("nan"), 0), (5, 0))),), **fields)
    result = audit_collinear_candidates(candidate, {"a": a, "b": b})
    assert result["first_gate"] == "malformed_source_wall_edge"
    assert result["candidate_shared_spans"] == []
    assert not result["merge_source_faces_authorized"]


def test_original_source_collinear_audit_separates_opposite_from_forward_strokes():
    lineage=dict(document_id="doc", revision_id="rev", source_sha256="a"*64,
                 snapshot_id="snap", page_id="7", decision_scope_id="view")
    split=O(label="GENERIC ROOM", source_room_face_record_ids=("left","right"), **lineage)
    first=O(record_id="left",boundary_wall_edges=(
        ("wall-source-1",((0.,0.),(10.,0.))),), **lineage)
    for other_edge,expected in (
        (((8.,0.),(2.,0.)),True),
        (((2.,0.),(8.,0.)),False),
    ):
        other=O(record_id="right",boundary_wall_edges=(
            ("wall-source-1",other_edge),), **lineage)
        found=audit_collinear_candidates(split,{"left":first,"right":other})
        assert found["candidate_shared_spans"][0][
            "opposite_exact_source_stroke_observed"
        ] is expected
        assert not found["merge_source_faces_authorized"]
        assert not found["metric_quantity_published"]


def test_collinear_audit_rejects_forged_or_nontext_split_source_lineage():
    lineage=dict(document_id="doc", revision_id="rev", source_sha256="a"*64,
                 snapshot_id="snap", page_id="7", decision_scope_id="view")
    faces={
        "left":O(record_id="left",boundary_wall_edges=(),**lineage),
        "right":O(record_id="right",boundary_wall_edges=(),**lineage),
    }
    for invalid in (None, 10, "", " left", {"a":1}):
        split=O(label="ROOM",source_room_face_record_ids=(invalid,"right"),**lineage)
        assert audit_collinear_candidates(split,faces)["first_gate"]=="invalid_split_candidate"
    split=O(label="ROOM",source_room_face_record_ids=("left","right"),**lineage)
    split.snapshot_id=None
    faces["left"].snapshot_id=None
    faces["right"].snapshot_id=None
    assert audit_collinear_candidates(split,faces)["first_gate"]=="source_lineage_conflict"
