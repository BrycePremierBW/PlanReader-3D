from types import SimpleNamespace

from pb_migration_contracts import EvidenceAtom, EvidenceResolutionStatus
from pb_physical_wall_candidate_authority import PhysicalWallCandidateScopeResult
from pb_source_composite_room_face_authority import (
    SOURCE_COMPOSITE_ROOM_FACE_RESOLVED,
    compose_grid_separated_room_faces,
)
from pb_source_room_face_authority import (
    SourceRoomFaceRecord,
    SourceRoomFaceScopeResult,
)
from pb_source_room_label_authority import SourceRoomLabelScopeResult


LINEAGE = dict(
    document_id="doc",
    revision_id="rev",
    source_sha256="a" * 64,
    snapshot_id="snap",
    page_id="1",
    decision_scope_id="wall-source:page-1",
)


def _face(face_id, record_id, polygon, walls, boundary_wall_edges=()):
    area = 0.0
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        area += first[0] * second[1] - second[0] * first[1]
    return SourceRoomFaceRecord(
        record_id=record_id,
        face_id=face_id,
        polygon_pdf_pts=tuple(polygon),
        bounding_wall_ids=tuple(walls),
        area_page_pts2=abs(area) * 0.5,
        boundary_wall_edges=tuple(boundary_wall_edges),
        **LINEAGE,
    )


def _wall_record(wall_id, *edge_ids):
    centerlines = {
        "w_sep": ((10.0, 0.0), (10.0, 10.0)),
        "w_lm": ((10.0, 0.0), (10.0, 10.0)),
        "w_mr": ((20.0, 0.0), (20.0, 10.0)),
        "w_left": ((0.0, 0.0), (0.0, 10.0)),
        "w_right": ((30.0, 0.0), (30.0, 10.0)),
    }
    return SimpleNamespace(
        wall_candidate_id=wall_id,
        wall_candidate=SimpleNamespace(
            face_a_segment_ids=tuple(edge_ids),
            face_b_segment_ids=None,
            centerline_pts=centerlines.get(
                wall_id, ((1000.0, 1000.0), (1001.0, 1001.0))
            ),
        ),
    )


def _grid_atom(edge_id, evidence_id="ev_grid"):
    return EvidenceAtom(
        evidence_id=evidence_id,
        document_id="doc",
        page_id="1",
        kind="grid",
        method="typed_negative_geometry_shadow",
        status=EvidenceResolutionStatus.CANDIDATE,
        reason_codes=("source_lineage_dense_orthogonal_lattice",),
        metadata={
            "polarity": "opposing",
            "target_edge_id": edge_id,
        },
    )


def _wall_scope(atoms):
    return PhysicalWallCandidateScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(
            _wall_record("w_sep", "e_sep"),
            _wall_record("w_left", "e_left"),
            _wall_record("w_right", "e_right"),
        ),
        source_observation_ids=(),
        reason_codes=("physical_wall_candidate_scope_resolved",),
        typed_semantic_evidence_atoms=tuple(atoms),
        **LINEAGE,
    )


def _room_scope(*, disconnected=False):
    left = _face(
        "face_left",
        "record_left",
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        ("w_left", "w_sep", "w_top_left", "w_bottom_left"),
        (
            ("w_bottom_left", ((0.0, 0.0), (10.0, 0.0))),
            ("w_sep", ((10.0, 0.0), (10.0, 10.0))),
            ("w_top_left", ((0.0, 10.0), (10.0, 10.0))),
            ("w_left", ((0.0, 0.0), (0.0, 10.0))),
        ),
    )
    x0 = 11.0 if disconnected else 10.0
    right = _face(
        "face_right",
        "record_right",
        ((x0, 0.0), (20.0, 0.0), (20.0, 10.0), (x0, 10.0)),
        ("w_sep", "w_right", "w_top_right", "w_bottom_right"),
        (
            ("w_bottom_right", ((x0, 0.0), (20.0, 0.0))),
            ("w_right", ((20.0, 0.0), (20.0, 10.0))),
            ("w_top_right", ((x0, 10.0), (20.0, 10.0))),
            ("w_sep", ((x0, 0.0), (x0, 10.0))),
        ),
    )
    return SourceRoomFaceScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(left, right),
        reason_codes=("source_room_face_scope_resolved",),
        **LINEAGE,
    )


def _label_scope():
    candidate = SimpleNamespace(
        record_id="split_label_1",
        document_id=LINEAGE["document_id"],
        revision_id=LINEAGE["revision_id"],
        source_sha256=LINEAGE["source_sha256"],
        snapshot_id=LINEAGE["snapshot_id"],
        page_id=LINEAGE["page_id"],
        decision_scope_id=LINEAGE["decision_scope_id"],
        label="GENERIC TWO WORD",
        observation_ids=("obs_a", "obs_b"),
        word_evidence=(
            SimpleNamespace(authority_record_id="text_a"),
            SimpleNamespace(authority_record_id="text_b"),
        ),
        word_face_ids=("face_left", "face_right"),
        source_room_face_record_ids=("record_left", "record_right"),
    )
    return SourceRoomLabelScopeResult(
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("source_room_label_position_unresolved",),
        records=(),
        split_face_candidates=(candidate,),
        **LINEAGE,
    )


def test_grid_only_internal_separator_composes_one_room_face():
    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=_room_scope(),
        label_scope=_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.reason_codes == (SOURCE_COMPOSITE_ROOM_FACE_RESOLVED,)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.label == "GENERIC TWO WORD"
    assert record.constituent_face_ids == ("face_left", "face_right")
    assert record.separator_wall_ids == ("w_sep",)
    assert "w_sep" not in record.bounding_wall_ids
    assert record.area_page_pts2 == 200.0
    assert record.grid_evidence_ids == ("ev_grid",)


def test_grid_opposed_external_boundary_stays_fail_closed():
    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope(
            (
                _grid_atom("e_sep", "ev_sep"),
                _grid_atom("e_left", "ev_outer"),
            )
        ),
        room_scope=_room_scope(),
        label_scope=_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()
    assert result.unresolved_label_candidate_ids == ("split_label_1",)


def test_non_grid_separator_stays_fail_closed():
    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope(()),
        room_scope=_room_scope(),
        label_scope=_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()
    assert result.unresolved_label_candidate_ids == ("split_label_1",)


def test_disconnected_faces_do_not_merge_even_with_grid_evidence():
    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=_room_scope(disconnected=True),
        label_scope=_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()


def _three_cell_wall_scope(atoms):
    return PhysicalWallCandidateScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(
            _wall_record("w_lm", "e_lm"),
            _wall_record("w_mr", "e_mr"),
            _wall_record("w_left", "e_left"),
            _wall_record("w_right", "e_right"),
        ),
        source_observation_ids=(),
        reason_codes=("physical_wall_candidate_scope_resolved",),
        typed_semantic_evidence_atoms=tuple(atoms),
        **LINEAGE,
    )


def _three_cell_room_scope():
    left = _face(
        "face_left",
        "record_left",
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        ("w_left", "w_lm", "w_top_left", "w_bottom_left"),
        (
            ("w_bottom_left", ((0.0, 0.0), (10.0, 0.0))),
            ("w_lm", ((10.0, 0.0), (10.0, 10.0))),
            ("w_top_left", ((0.0, 10.0), (10.0, 10.0))),
            ("w_left", ((0.0, 0.0), (0.0, 10.0))),
        ),
    )
    middle = _face(
        "face_middle",
        "record_middle",
        ((10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0)),
        ("w_lm", "w_mr", "w_top_middle", "w_bottom_middle"),
        (
            ("w_bottom_middle", ((10.0, 0.0), (20.0, 0.0))),
            ("w_mr", ((20.0, 0.0), (20.0, 10.0))),
            ("w_top_middle", ((10.0, 10.0), (20.0, 10.0))),
            ("w_lm", ((10.0, 0.0), (10.0, 10.0))),
        ),
    )
    right = _face(
        "face_right",
        "record_right",
        ((20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)),
        ("w_mr", "w_right", "w_top_right", "w_bottom_right"),
        (
            ("w_bottom_right", ((20.0, 0.0), (30.0, 0.0))),
            ("w_right", ((30.0, 0.0), (30.0, 10.0))),
            ("w_top_right", ((20.0, 10.0), (30.0, 10.0))),
            ("w_mr", ((20.0, 0.0), (20.0, 10.0))),
        ),
    )
    return SourceRoomFaceScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(left, middle, right),
        reason_codes=("source_room_face_scope_resolved",),
        **LINEAGE,
    )


def _three_cell_label_scope(*, middle_label=False, competing_split=False):
    candidate = SimpleNamespace(
        record_id="split_label_primary",
        document_id=LINEAGE["document_id"],
        revision_id=LINEAGE["revision_id"],
        source_sha256=LINEAGE["source_sha256"],
        snapshot_id=LINEAGE["snapshot_id"],
        page_id=LINEAGE["page_id"],
        decision_scope_id=LINEAGE["decision_scope_id"],
        label="GENERIC ROOM",
        observation_ids=("obs_left", "obs_right"),
        word_evidence=(
            SimpleNamespace(authority_record_id="text_left"),
            SimpleNamespace(authority_record_id="text_right"),
        ),
        word_face_ids=("face_left", "face_right"),
        source_room_face_record_ids=("record_left", "record_right"),
    )
    split_candidates = [candidate]
    if competing_split:
        split_candidates.append(
            SimpleNamespace(
                record_id="split_label_competing",
                document_id=LINEAGE["document_id"],
                revision_id=LINEAGE["revision_id"],
                source_sha256=LINEAGE["source_sha256"],
                snapshot_id=LINEAGE["snapshot_id"],
                page_id=LINEAGE["page_id"],
                decision_scope_id=LINEAGE["decision_scope_id"],
                label="OTHER ROOM",
                observation_ids=("obs_middle", "obs_other"),
                word_evidence=(
                    SimpleNamespace(authority_record_id="text_middle"),
                    SimpleNamespace(authority_record_id="text_other"),
                ),
                word_face_ids=("face_middle", "face_right"),
                source_room_face_record_ids=("record_middle", "record_right"),
            )
        )
    records = (
        (SimpleNamespace(face_id="face_middle", label="OTHER ROOM"),)
        if middle_label
        else ()
    )
    return SourceRoomLabelScopeResult(
        status=EvidenceResolutionStatus.CANDIDATE,
        reason_codes=("source_room_label_position_unresolved",),
        records=records,
        split_face_candidates=tuple(split_candidates),
        **LINEAGE,
    )


def test_grid_component_completion_recovers_unlabelled_intervening_face():
    result = compose_grid_separated_room_faces(
        wall_scope=_three_cell_wall_scope(
            (
                _grid_atom("e_lm", "ev_lm"),
                _grid_atom("e_mr", "ev_mr"),
            )
        ),
        room_scope=_three_cell_room_scope(),
        label_scope=_three_cell_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    record = result.records[0]
    assert record.constituent_face_ids == (
        "face_left",
        "face_middle",
        "face_right",
    )
    assert record.separator_wall_ids == ("w_lm", "w_mr")
    assert record.area_page_pts2 == 300.0
    assert record.grid_evidence_ids == ("ev_lm", "ev_mr")
    assert "w_lm" not in record.bounding_wall_ids
    assert "w_mr" not in record.bounding_wall_ids


def test_grid_component_completion_requires_all_label_seed_faces_connected():
    result = compose_grid_separated_room_faces(
        wall_scope=_three_cell_wall_scope((_grid_atom("e_lm", "ev_lm"),)),
        room_scope=_three_cell_room_scope(),
        label_scope=_three_cell_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()
    assert result.unresolved_label_candidate_ids == ("split_label_primary",)


def test_grid_component_completion_blocks_authenticated_label_conflict():
    result = compose_grid_separated_room_faces(
        wall_scope=_three_cell_wall_scope(
            (
                _grid_atom("e_lm", "ev_lm"),
                _grid_atom("e_mr", "ev_mr"),
            )
        ),
        room_scope=_three_cell_room_scope(),
        label_scope=_three_cell_label_scope(middle_label=True),
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()
    assert result.unresolved_label_candidate_ids == ("split_label_primary",)


def test_grid_component_completion_blocks_competing_split_label():
    result = compose_grid_separated_room_faces(
        wall_scope=_three_cell_wall_scope(
            (
                _grid_atom("e_lm", "ev_lm"),
                _grid_atom("e_mr", "ev_mr"),
            )
        ),
        room_scope=_three_cell_room_scope(),
        label_scope=_three_cell_label_scope(competing_split=True),
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()
    assert set(result.unresolved_label_candidate_ids) == {
        "split_label_primary",
        "split_label_competing",
    }


def test_grid_component_completion_preserves_repeated_physical_outer_wall():
    left = _face(
        "face_left",
        "record_left",
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        ("w_left", "w_lm", "w_top", "w_bottom"),
        (
            ("w_bottom", ((0.0, 0.0), (10.0, 0.0))),
            ("w_lm", ((10.0, 0.0), (10.0, 10.0))),
            ("w_top", ((0.0, 10.0), (10.0, 10.0))),
            ("w_left", ((0.0, 0.0), (0.0, 10.0))),
        ),
    )
    middle = _face(
        "face_middle",
        "record_middle",
        ((10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0)),
        ("w_lm", "w_mr", "w_top", "w_bottom"),
        (
            ("w_bottom", ((10.0, 0.0), (20.0, 0.0))),
            ("w_mr", ((20.0, 0.0), (20.0, 10.0))),
            ("w_top", ((10.0, 10.0), (20.0, 10.0))),
            ("w_lm", ((10.0, 0.0), (10.0, 10.0))),
        ),
    )
    right = _face(
        "face_right",
        "record_right",
        ((20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)),
        ("w_mr", "w_right", "w_top", "w_bottom"),
        (
            ("w_bottom", ((20.0, 0.0), (30.0, 0.0))),
            ("w_right", ((30.0, 0.0), (30.0, 10.0))),
            ("w_top", ((20.0, 10.0), (30.0, 10.0))),
            ("w_mr", ((20.0, 0.0), (20.0, 10.0))),
        ),
    )
    room_scope = SourceRoomFaceScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(left, middle, right),
        reason_codes=("source_room_face_scope_resolved",),
        **LINEAGE,
    )

    result = compose_grid_separated_room_faces(
        wall_scope=_three_cell_wall_scope(
            (
                _grid_atom("e_lm", "ev_lm"),
                _grid_atom("e_mr", "ev_mr"),
            )
        ),
        room_scope=room_scope,
        label_scope=_three_cell_label_scope(),
    )

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    record = result.records[0]
    assert record.separator_wall_ids == ("w_lm", "w_mr")
    assert "w_top" in record.bounding_wall_ids
    assert "w_bottom" in record.bounding_wall_ids

def test_long_grid_wall_with_more_than_two_global_owners_uses_local_adjacency():
    top_left = _face(
        "top_left",
        "record_top_left",
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        ("w_outer_left_top", "w_long_grid", "w_top_left", "w_mid_left"),
        (
            ("w_top_left", ((0.0, 0.0), (10.0, 0.0))),
            ("w_long_grid", ((10.0, 0.0), (10.0, 10.0))),
            ("w_mid_left", ((0.0, 10.0), (10.0, 10.0))),
            ("w_outer_left_top", ((0.0, 0.0), (0.0, 10.0))),
        ),
    )
    top_right = _face(
        "top_right",
        "record_top_right",
        ((10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0)),
        ("w_long_grid", "w_outer_right_top", "w_top_right", "w_mid_right"),
        (
            ("w_top_right", ((10.0, 0.0), (20.0, 0.0))),
            ("w_outer_right_top", ((20.0, 0.0), (20.0, 10.0))),
            ("w_mid_right", ((10.0, 10.0), (20.0, 10.0))),
            ("w_long_grid", ((10.0, 0.0), (10.0, 10.0))),
        ),
    )
    bottom_left = _face(
        "bottom_left",
        "record_bottom_left",
        ((0.0, 10.0), (10.0, 10.0), (10.0, 20.0), (0.0, 20.0)),
        ("w_outer_left_bottom", "w_long_grid", "w_mid_left", "w_bottom_left"),
        (
            ("w_mid_left", ((0.0, 10.0), (10.0, 10.0))),
            ("w_long_grid", ((10.0, 10.0), (10.0, 20.0))),
            ("w_bottom_left", ((0.0, 20.0), (10.0, 20.0))),
            ("w_outer_left_bottom", ((0.0, 10.0), (0.0, 20.0))),
        ),
    )
    bottom_right = _face(
        "bottom_right",
        "record_bottom_right",
        ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)),
        ("w_long_grid", "w_outer_right_bottom", "w_mid_right", "w_bottom_right"),
        (
            ("w_mid_right", ((10.0, 10.0), (20.0, 10.0))),
            ("w_outer_right_bottom", ((20.0, 10.0), (20.0, 20.0))),
            ("w_bottom_right", ((10.0, 20.0), (20.0, 20.0))),
            ("w_long_grid", ((10.0, 10.0), (10.0, 20.0))),
        ),
    )
    room_scope = SourceRoomFaceScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(top_left, top_right, bottom_left, bottom_right),
        reason_codes=("source_room_face_scope_resolved",),
        **LINEAGE,
    )
    wall_scope = PhysicalWallCandidateScopeResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(
            SimpleNamespace(
                wall_candidate_id="w_long_grid",
                wall_candidate=SimpleNamespace(
                    face_a_segment_ids=("e_long_grid",),
                    face_b_segment_ids=None,
                    centerline_pts=((10.0, 0.0), (10.0, 20.0)),
                ),
            ),
        ),
        source_observation_ids=(),
        reason_codes=("physical_wall_candidate_scope_resolved",),
        typed_semantic_evidence_atoms=(
            _grid_atom("e_long_grid", "ev_long_grid"),
        ),
        **LINEAGE,
    )
    candidate = SimpleNamespace(
        record_id="split_label_top",
        document_id=LINEAGE["document_id"],
        revision_id=LINEAGE["revision_id"],
        source_sha256=LINEAGE["source_sha256"],
        snapshot_id=LINEAGE["snapshot_id"],
        page_id=LINEAGE["page_id"],
        decision_scope_id=LINEAGE["decision_scope_id"],
        label="GENERIC TWO WORD",
        observation_ids=("obs_top_left", "obs_top_right"),
        word_evidence=(
            SimpleNamespace(authority_record_id="text_top_left"),
            SimpleNamespace(authority_record_id="text_top_right"),
        ),
        word_face_ids=("top_left", "top_right"),
        source_room_face_record_ids=("record_top_left", "record_top_right"),
    )
    label_scope = SourceRoomLabelScopeResult(
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("source_room_label_position_unresolved",),
        records=(),
        split_face_candidates=(candidate,),
        **LINEAGE,
    )

    result = compose_grid_separated_room_faces(
        wall_scope=wall_scope,
        room_scope=room_scope,
        label_scope=label_scope,
    )

    # One long W4 grid chain owns two disjoint local separator subedges.
    # Starting in the top pair must traverse only the exact shared top subedge;
    # point contact with the lower pair is not room adjacency.
    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    assert result.records[0].constituent_face_ids == ("top_left", "top_right")


def test_planarized_source_wall_edges_reject_nonfinite_coordinates():
    # A malformed source edge cannot be a globally shared grid separator.
    from pb_source_composite_room_face_authority import _edge_key

    assert _edge_key(((0.0, 0.0), (10.0, 0.0))) == (
        (0.0, 0.0), (10.0, 0.0)
    )
    assert _edge_key(((10.0, 0.0), (0.0, 0.0))) == (
        (0.0, 0.0), (10.0, 0.0)
    )
    for value in (float("nan"), float("inf"), float("-inf")):
        assert _edge_key(((0.0, 0.0), (value, 0.0))) is None
        assert _edge_key(((value, 1.0), (2.0, 1.0))) is None
    assert _edge_key(((0.0, 0.0), (0.0, 0.0))) is None
    assert _edge_key(((0.0, 0.0), ())) is None
    assert _edge_key(((0.0, 0.0), (10**500, 0.0))) is None


def test_nonfinite_source_wall_cannot_generate_local_grid_adjacency():
    from pb_source_composite_room_face_authority import (
        _grid_local_adjacency,
        _local_edge_owners,
    )
    from types import SimpleNamespace

    source_face_a = SimpleNamespace(
        face_id="a",
        boundary_wall_edges=(("W-grid", ((float("nan"), 0.0), (5.0, 0.0))),),
    )
    source_face_b = SimpleNamespace(
        face_id="b",
        boundary_wall_edges=(("W-grid", ((float("nan"), 0.0), (5.0, 0.0))),),
    )
    source_scope = SimpleNamespace(records=(source_face_a, source_face_b))
    assert _local_edge_owners(source_scope) == {}
    assert _grid_local_adjacency(source_scope, {"W-grid"}) == {}



def test_null_wall_identity_cannot_own_any_composite_room_subedge():
    from pb_source_composite_room_face_authority import (
        _grid_local_adjacency,
        _local_edge_owners,
    )
    from types import SimpleNamespace

    source_scope = SimpleNamespace(records=(
        SimpleNamespace(face_id="a", boundary_wall_edges=((None, ((0, 0), (10, 0))),)),
        SimpleNamespace(face_id="b", boundary_wall_edges=(("", ((10, 0), (0, 0))),)),
    ))
    assert _local_edge_owners(source_scope) == {}
    assert _grid_local_adjacency(source_scope, {"None", ""}) == {}


def test_source_grid_subedges_node_at_exact_split_endpoints():
    """Two authentic W4 wall receipts may use different exact subedge cuts."""
    from dataclasses import replace

    scope = _room_scope()
    left, right = scope.records
    new_right_edges = []
    for wall, edge in right.boundary_wall_edges:
        if wall == "w_sep":
            new_right_edges.extend((
                (wall, ((10.0, 0.0), (10.0, 4.0))),
                (wall, ((10.0, 4.0), (10.0, 10.0))),
            ))
        else:
            new_right_edges.append((wall, edge))
    split_scope = replace(scope, records=(
        left, replace(right, boundary_wall_edges=tuple(new_right_edges)),
    ))

    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=split_scope,
        label_scope=_label_scope(),
    )
    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    assert result.records[0].area_page_pts2 == 200.0
    assert result.records[0].separator_wall_ids == ("w_sep",)


def test_source_grid_edge_noding_requires_exact_axis_and_same_w4_wall():
    from dataclasses import replace
    from pb_source_composite_room_face_authority import _grid_local_adjacency
    scope = _room_scope()
    left, right = scope.records
    incompatible = []
    for wall, edge in right.boundary_wall_edges:
        if wall == "w_sep":
            incompatible.extend((
                (wall, ((10.00001, 0.0), (10.00001, 4.0))),
                (wall, ((10.00001, 4.0), (10.00001, 10.0))),
            ))
        else:
            incompatible.append((wall, edge))
    offset_scope = replace(scope, records=(
        left, replace(right, boundary_wall_edges=tuple(incompatible)),
    ))
    assert _grid_local_adjacency(offset_scope, {"w_sep"}) == {}
    assert compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=offset_scope,
        label_scope=_label_scope(),
    ).records == ()

    # Matching geometry associated with a different W4 wall is never an owner.
    foreign = tuple(
        ("w_wrong", edge) if wall == "w_sep" else (wall, edge)
        for wall, edge in right.boundary_wall_edges
    )
    foreign_scope = replace(scope, records=(
        left, replace(right, boundary_wall_edges=foreign),
    ))
    assert _grid_local_adjacency(foreign_scope, {"w_sep"}) == {}


def test_grid_noding_rejects_duplicate_and_three_sided_source_owners():
    from dataclasses import replace
    from pb_source_composite_room_face_authority import _grid_local_adjacency
    scope = _room_scope()
    left, right = scope.records
    dup_scope = replace(scope, records=(
        replace(left, boundary_wall_edges=left.boundary_wall_edges +
                (("w_sep", ((10.0, 0.0), (10.0, 10.0))),)),
        right,
    ))
    assert _grid_local_adjacency(dup_scope, {"w_sep"}) == {}
    assert compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=dup_scope,
        label_scope=_label_scope(),
    ).records == ()

    third = replace(left, face_id="unrelated_third_face",
                    record_id="unrelated_third_record")
    triple_scope = replace(scope, records=(left, right, third))
    assert _grid_local_adjacency(triple_scope, {"w_sep"}) == {}


def test_touching_grid_source_edges_without_positive_span_do_not_connect():
    from dataclasses import replace
    from pb_source_composite_room_face_authority import _grid_local_adjacency
    scope = _room_scope()
    left, right = scope.records
    left_edges = tuple(
        (wall, ((10.0, 0.0), (10.0, 5.0))) if wall == "w_sep"
        else (wall, edge) for wall, edge in left.boundary_wall_edges
    )
    right_edges = tuple(
        (wall, ((10.0, 5.0), (10.0, 10.0))) if wall == "w_sep"
        else (wall, edge) for wall, edge in right.boundary_wall_edges
    )
    disconnected = replace(scope, records=(
        replace(left, boundary_wall_edges=left_edges),
        replace(right, boundary_wall_edges=right_edges),
    ))
    assert _grid_local_adjacency(disconnected, {"w_sep"}) == {}
    assert compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=disconnected,
        label_scope=_label_scope(),
    ).records == ()


def test_source_grid_union_rejects_overlapping_face_interiors():
    from dataclasses import replace
    original = _room_scope()
    left, right = original.records
    # Even with the same W4 receipt, an internally overlapping source-face
    # footprint is not a true room-cell partition and must not be composed.
    inflated = replace(right,
        polygon_pdf_pts=((8.0, 0.0), (20.0, 0.0),
                         (20.0, 10.0), (8.0, 10.0)),
        area_page_pts2=120.0,
    )
    overlapped = replace(original, records=(left, inflated))
    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=overlapped,
        label_scope=_label_scope(),
    )
    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()


def test_source_endpoint_sweep_preserves_overlapping_same_face_multiplicity():
    """A sweep must not collapse duplicate overlaps into a fake two-sided owner."""
    from dataclasses import replace
    from pb_source_composite_room_face_authority import (
        _atomic_source_wall_edge_counts,
    )

    scope = _room_scope()
    left, right = scope.records
    right_edges = []
    for wall, edge in right.boundary_wall_edges:
        if wall == "w_sep":
            right_edges.extend((
                (wall, ((10.0, 0.0), (10.0, 6.0))),
                (wall, ((10.0, 4.0), (10.0, 10.0))),
            ))
        else:
            right_edges.append((wall, edge))
    modified = replace(scope, records=(
        left, replace(right, boundary_wall_edges=tuple(right_edges)),
    ))
    noded = _atomic_source_wall_edge_counts(modified, {"w_sep"})
    shared = noded[("w_sep", ((10.0, 4.0), (10.0, 6.0)))]
    assert shared["face_left"] == 1
    assert shared["face_right"] == 2
    result = compose_grid_separated_room_faces(
        wall_scope=_wall_scope((_grid_atom("e_sep"),)),
        room_scope=modified,
        label_scope=_label_scope(),
    )
    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()


def test_source_endpoint_sweep_preserves_adjacent_same_face_segments():
    """An end and start at the same authentic cut keep one face owner."""
    from dataclasses import replace
    from pb_source_composite_room_face_authority import (
        _atomic_source_wall_edge_counts,
    )

    scope = _room_scope()
    left, right = scope.records
    right_edges = []
    for wall, edge in right.boundary_wall_edges:
        if wall == "w_sep":
            right_edges.extend((
                (wall, ((10.0, 0.0), (10.0, 4.0))),
                (wall, ((10.0, 4.0), (10.0, 10.0))),
            ))
        else:
            right_edges.append((wall, edge))
    modified = replace(scope, records=(
        left, replace(right, boundary_wall_edges=tuple(right_edges)),
    ))
    noded = _atomic_source_wall_edge_counts(modified, {"w_sep"})
    for start, end in ((0.0, 4.0), (4.0, 10.0)):
        assert noded[("w_sep", ((10.0, start), (10.0, end)))] == {
            "face_left": 1, "face_right": 1,
        }


def test_source_w4_node_counts_are_scoped_once_across_competing_labels(monkeypatch):
    """Candidate abstention semantics stay unchanged without per-label noding."""
    import pb_source_composite_room_face_authority as module

    original = module._atomic_source_wall_edge_counts
    calls = []

    def measured(room_scope, grid_walls):
        calls.append((room_scope, frozenset(grid_walls)))
        return original(room_scope, grid_walls)

    monkeypatch.setattr(module, "_atomic_source_wall_edge_counts", measured)
    room_scope = _three_cell_room_scope()
    result = compose_grid_separated_room_faces(
        wall_scope=_three_cell_wall_scope(
            (_grid_atom("e_lm", "ev_lm"), _grid_atom("e_mr", "ev_mr"))
        ),
        room_scope=room_scope,
        label_scope=_three_cell_label_scope(competing_split=True),
    )
    assert len(calls) == 1
    assert calls[0][0] is room_scope
    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.records == ()
    assert set(result.unresolved_label_candidate_ids) == {
        "split_label_primary",
        "split_label_competing",
    }


def test_gpt2_b02_duplicate_w4_candidate_id_does_not_authenticate_separator():
    """Original Maryborough exposed different W4 candidates with one address.

    A shared W4 address does not prove wall physical equivalence or an exact
    separator. Preserve independent source-owned walls and all face records.
    """
    from dataclasses import replace
    from pb_source_composite_room_face_authority import (
        _fully_grid_opposed_wall_evidence,
    )

    original = _wall_scope((_grid_atom("e_sep"), _grid_atom("e_left")))
    clean_ids, clean_receipts = _fully_grid_opposed_wall_evidence(original)
    assert "w_sep" in clean_ids and "w_left" in clean_ids
    assert clean_receipts["w_sep"]
    duplicate = _wall_record("w_sep", "another_original_source_edge")
    contaminated = replace(
        original, records=(*original.records, duplicate)
    )
    quarantined, receipts = _fully_grid_opposed_wall_evidence(contaminated)
    assert "w_sep" not in quarantined
    assert "w_sep" not in receipts
    assert "w_left" in quarantined
    assert receipts["w_left"] == clean_receipts["w_left"]
    # Exactly the same producer ID repeated twice is also nonunique and
    # cannot silently grant two physical face-cell ownership claims.
    repeated = replace(
        original, records=(*original.records, original.records[0])
    )
    repeated_ids, _ = _fully_grid_opposed_wall_evidence(repeated)
    assert "w_sep" not in repeated_ids

    # A candidate union relying on a colliding W4 separator must abstain.
    attempted = compose_grid_separated_room_faces(
        wall_scope=contaminated,
        room_scope=_room_scope(),
        label_scope=_label_scope(),
    )
    assert attempted.records == ()
    assert attempted.status is EvidenceResolutionStatus.ABSTAINED


def test_gpt2_b02_duplicate_source_face_or_receipt_blocks_room_composite():
    from dataclasses import replace

    original=_room_scope()
    wall=_wall_scope((_grid_atom("e_sep"),))
    label=_label_scope()
    positive=compose_grid_separated_room_faces(
        wall_scope=wall,room_scope=original,label_scope=label
    )
    assert positive.status is EvidenceResolutionStatus.CORROBORATED
    assert len(positive.records)==1

    a,b=original.records
    for corrupted in (
        replace(original,records=(a,b,replace(a,record_id="another-source"))),
        replace(original,records=(a,replace(b,record_id=a.record_id))),
    ):
        result=compose_grid_separated_room_faces(
            wall_scope=wall,room_scope=corrupted,label_scope=label
        )
        assert result.status is EvidenceResolutionStatus.ABSTAINED
        assert result.records == ()
        assert result.unresolved_label_candidate_ids == ("split_label_1",)
        # Original source record universe must remain auditable, never deleted.
        assert len(corrupted.records) in (2,3)


def test_gpt2_b02_invalid_w4_source_key_cannot_impersonate_grid_wall():
    """Fail closed even when a typed GRID atom points to an apparent string ID."""
    from dataclasses import replace
    from pb_source_composite_room_face_authority import (
        _fully_grid_opposed_wall_evidence,
    )
    for invalid in (None, 42, "", "  ", " w_sep"):
        source = _wall_scope((_grid_atom("e_sep"),))
        original = source.records[0]
        forged = SimpleNamespace(
            wall_candidate_id=invalid,
            wall_candidate=original.wall_candidate,
        )
        amended = replace(source, records=(forged, *source.records[1:]))
        grid, receipts = _fully_grid_opposed_wall_evidence(amended)
        assert "w_sep" not in grid
        assert "w_sep" not in receipts
        assert not grid
    # Unaffected producer-owned walls still publish their exact independent
    # grid opposition when another wall has an invalid address.
    source=_wall_scope((_grid_atom("e_sep"),_grid_atom("e_left")))
    forged=SimpleNamespace(
        wall_candidate_id=None,
        wall_candidate=source.records[0].wall_candidate,
    )
    amended=replace(source, records=(forged,*source.records[1:]))
    grid,receipts=_fully_grid_opposed_wall_evidence(amended)
    assert grid=={"w_left"}
    assert receipts["w_left"]
