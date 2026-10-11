"""Source-authenticated room-face authority tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz

from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_physical_wall_candidate_authority import (
    PhysicalWallCandidateProducer,
    PhysicalWallCandidateSelector,
)
from pb_source_room_face_authority import (
    SOURCE_ROOM_FACE_COMPONENT_AMBIGUOUS,
    SOURCE_ROOM_FACE_SCOPE_RESOLVED,
    SourceRoomFaceSelector,
    _canonical_polygon,
    _publication_polygon,
    _derive_scope,
    _edge,
    _edge_contains_edge,
    _unique_containing_wall_owner,
    build_source_room_face_authority,
)
from pb_source_visibility_authority import SourceVisibilityProducer


def _write_plan(path: Path, *, with_partition: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    lines = [
        ((50.0, 50.0), (250.0, 50.0)),
        ((250.0, 50.0), (250.0, 150.0)),
        ((250.0, 150.0), (50.0, 150.0)),
        ((50.0, 150.0), (50.0, 50.0)),
    ]
    if with_partition:
        lines.append(((150.0, 50.0), (150.0, 150.0)))
    for first, second in lines:
        page.draw_line(
            fitz.Point(*first),
            fitz.Point(*second),
            color=(0, 0, 0),
            width=1,
        )
    doc.save(path)
    doc.close()


def _scope(path: Path):
    source = SourceVisibilityProducer(
        producer_method="source-room-face-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id=f"test:{path.name}",
        source_bytes=path.read_bytes(),
        source_locator=str(path),
    )
    wall_producer = PhysicalWallCandidateProducer.from_source_visibility_producer(
        source,
        page_ids=("1",),
    )
    wall_authority = wall_producer.authority()
    wall_selector = PhysicalWallCandidateSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        decision_scope_id="wall-source:page-1",
    )
    wall_scope = wall_authority.resolve_scope(wall_selector)
    assert wall_scope.status is EvidenceResolutionStatus.CORROBORATED
    assert wall_scope.scope_complete is True
    room_authority = build_source_room_face_authority(wall_authority)
    room_selector = SourceRoomFaceSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        decision_scope_id="wall-source:page-1",
    )
    return room_authority.resolve_scope(room_selector)



def test_raw_canonical_polygon_retains_retraced_spur_for_ownership_audit() -> None:
    clean = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )
    with_exact_spur = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (10.0, 8.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )

    raw = _canonical_polygon(with_exact_spur)

    assert len(raw) == 6
    assert raw != _canonical_polygon(clean)
    assert _publication_polygon(raw) == _canonical_polygon(clean)


def test_publication_polygon_collapses_multiple_exact_retraced_spurs() -> None:
    expected = (
        (0.0, 0.0),
        (20.0, 0.0),
        (20.0, 20.0),
        (0.0, 20.0),
        (0.0, 15.0),
    )
    with_spurs = (
        (0.0, 0.0),
        (20.0, 0.0),
        (20.0, 20.0),
        (18.0, 20.0),
        (20.0, 20.0),
        (0.0, 20.0),
        (0.0, 15.0),
        (-3.0, 15.0),
        (0.0, 15.0),
    )

    raw = _canonical_polygon(with_spurs)

    assert len(raw) == len(with_spurs)
    assert _publication_polygon(raw) == _canonical_polygon(expected)


def test_publication_polygon_collapses_consecutive_duplicate_before_spur() -> None:
    clean = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )
    noisy = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (8.0, 10.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )

    assert _publication_polygon(_canonical_polygon(noisy)) == _canonical_polygon(clean)


def test_publication_polygon_does_not_collapse_near_backtrack() -> None:
    near_backtrack = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (10.0, 8.0),
        (10.000001, 10.0),
        (0.0, 10.0),
    )

    raw = _canonical_polygon(near_backtrack)
    result = _publication_polygon(raw)

    assert len(result) == 6
    assert result == raw
    assert result != _canonical_polygon(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    )


def test_publication_polygon_collapses_exact_spur_across_ring_start() -> None:
    clean = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )
    wrapped_spur = (
        (10.0, 8.0),
        (10.0, 10.0),
        (0.0, 10.0),
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
    )

    raw = _canonical_polygon(wrapped_spur)

    assert raw != _canonical_polygon(clean)
    assert _publication_polygon(raw) == _canonical_polygon(clean)


def test_two_room_source_plan_publishes_exact_room_faces(tmp_path: Path) -> None:
    path = tmp_path / "two-room.pdf"
    _write_plan(path, with_partition=True)

    result = _scope(path)

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.scope_complete is True
    assert result.reason_codes == (SOURCE_ROOM_FACE_SCOPE_RESOLVED,)
    assert len(result.records) == 2
    assert all(record.area_page_pts2 > 0.0 for record in result.records)
    assert all(len(record.polygon_pdf_pts) >= 4 for record in result.records)
    assert all(record.bounding_wall_ids for record in result.records)
    assert all(record.boundary_wall_edges for record in result.records)
    assert all(
        len(record.boundary_wall_edges) == len(record.polygon_pdf_pts)
        for record in result.records
    )
    assert len({record.face_id for record in result.records}) == 2

    # Additive boundary-subedge provenance must not participate in the stable
    # physical/source-room record identity. Recompute the historical payload
    # exactly and require the same record id.
    for record in result.records:
        expected_payload = {
            "face_id": record.face_id,
            "document_id": record.document_id,
            "revision_id": record.revision_id,
            "source_sha256": record.source_sha256,
            "snapshot_id": record.snapshot_id,
            "page_id": record.page_id,
            "decision_scope_id": record.decision_scope_id,
            "polygon": record.polygon_pdf_pts,
            "bounding_wall_ids": record.bounding_wall_ids,
            "area_page_pts2": record.area_page_pts2,
        }
        assert record.record_id == stable_contract_id(
            "source_room_face_record", expected_payload, digest_chars=32
        )


def test_single_box_cannot_mint_room_face_authority(tmp_path: Path) -> None:
    path = tmp_path / "single-box.pdf"
    _write_plan(path, with_partition=False)

    result = _scope(path)

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.scope_complete is False
    assert result.records == ()
    assert SOURCE_ROOM_FACE_COMPONENT_AMBIGUOUS in result.reason_codes


def test_selector_lookup_is_exact_lineage(tmp_path: Path) -> None:
    path = tmp_path / "lineage.pdf"
    _write_plan(path, with_partition=True)

    source = SourceVisibilityProducer(
        producer_method="source-room-face-lineage-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="lineage-doc",
        source_bytes=path.read_bytes(),
        source_locator=str(path),
    )
    walls = PhysicalWallCandidateProducer.from_source_visibility_producer(
        source,
        page_ids=("1",),
    ).authority()
    authority = build_source_room_face_authority(walls)

    missing = authority.resolve_scope(
        SourceRoomFaceSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256="0" * 64,
            snapshot_id=published.snapshot.snapshot_id,
            page_id="1",
            decision_scope_id="wall-source:page-1",
        )
    )
    assert missing.status is EvidenceResolutionStatus.ABSTAINED
    assert missing.records == ()


def test_planarized_subedge_inherits_unique_authenticated_wall_owner() -> None:
    parent = _edge((0.0, 0.0), (10.0, 0.0))
    child = _edge((2.0, 0.0), (8.0, 0.0))

    assert _edge_contains_edge(parent, child)
    assert _unique_containing_wall_owner(
        child,
        edge_owner={},
        wall_edges={"wall-a": (parent,)},
    ) == "wall-a"


def test_planarized_diagonal_subedge_inherits_unique_owner() -> None:
    parent = _edge((0.0, 0.0), (10.0, 10.0))
    child = _edge((2.5, 2.5), (7.5, 7.5))

    assert _edge_contains_edge(parent, child)
    assert _unique_containing_wall_owner(
        child,
        edge_owner={},
        wall_edges={"wall-diagonal": (parent,)},
    ) == "wall-diagonal"


def test_contained_edge_owner_fails_closed_for_extension_or_offset() -> None:
    parent = _edge((0.0, 0.0), (10.0, 0.0))
    extended = _edge((-1.0, 0.0), (8.0, 0.0))
    offset = _edge((2.0, 0.001), (8.0, 0.001))

    assert not _edge_contains_edge(parent, extended)
    assert not _edge_contains_edge(parent, offset)
    for edge in (extended, offset):
        assert _unique_containing_wall_owner(
            edge, edge_owner={}, wall_edges={"wall-a": (parent,)}
        ) is None


def test_contained_edge_owner_fails_closed_for_competing_wall_ids() -> None:
    child = _edge((3.0, 0.0), (7.0, 0.0))
    walls = {
        "wall-a": (_edge((0.0, 0.0), (10.0, 0.0)),),
        "wall-b": (_edge((2.0, 0.0), (8.0, 0.0)),),
    }

    assert _unique_containing_wall_owner(
        child, edge_owner={}, wall_edges=walls
    ) is None
    assert _unique_containing_wall_owner(
        child, edge_owner={}, wall_edges=dict(reversed(tuple(walls.items())))
    ) is None


def test_exact_edge_owner_remains_primary_authority() -> None:
    edge = _edge((3.0, 0.0), (7.0, 0.0))
    assert _unique_containing_wall_owner(
        edge,
        edge_owner={edge: "wall-exact"},
        wall_edges={
            "wall-exact": (edge,),
            "wall-broader": (_edge((0.0, 0.0), (10.0, 0.0)),),
        },
    ) == "wall-exact"


def test_planar_face_split_at_partition_keeps_room_face_authority() -> None:
    def record(wall_id: str, first, second):
        return SimpleNamespace(
            wall_candidate_id=wall_id,
            wall_candidate=SimpleNamespace(centerline_pts=(first, second)),
        )

    scope = SimpleNamespace(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(
            record("top", (0.0, 0.0), (10.0, 0.0)),
            record("right", (10.0, 0.0), (10.0, 10.0)),
            record("bottom", (10.0, 10.0), (0.0, 10.0)),
            record("left", (0.0, 10.0), (0.0, 0.0)),
            record("partition", (5.0, 0.0), (5.0, 10.0)),
        ),
        document_id="doc-planar-split",
        revision_id="rev-planar-split",
        source_sha256="a" * 64,
        snapshot_id="snap-planar-split",
        page_id="1",
        decision_scope_id="wall-source:page-1",
    )

    result = _derive_scope(scope)

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.scope_complete is True
    assert result.reason_codes == (SOURCE_ROOM_FACE_SCOPE_RESOLVED,)
    assert len(result.records) == 2
    assert all("partition" in row.bounding_wall_ids for row in result.records)
    partition_edges = [
        edge
        for row in result.records
        for wall_id, edge in row.boundary_wall_edges
        if wall_id == "partition"
    ]
    assert len(partition_edges) == 2
    assert partition_edges[0] == partition_edges[1]

def test_disjoint_faces_on_same_long_wall_do_not_fake_two_sided_boundary() -> None:
    def record(wall_id: str, first, second):
        return SimpleNamespace(
            wall_candidate_id=wall_id,
            wall_candidate=SimpleNamespace(centerline_pts=(first, second)),
        )

    # Two independent boxes hang from disjoint subsegments of one long top
    # wall. They do not share an interior boundary with each other. Planar
    # splitting therefore gives the long wall two owned face subedges, but
    # neither exact subedge is shared by both faces.
    scope = SimpleNamespace(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
        records=(
            record("long-top", (0.0, 0.0), (20.0, 0.0)),
            record("box1-left", (0.0, 0.0), (0.0, 10.0)),
            record("box1-bottom", (0.0, 10.0), (8.0, 10.0)),
            record("box1-right", (8.0, 10.0), (8.0, 0.0)),
            record("box2-left", (12.0, 0.0), (12.0, 10.0)),
            record("box2-bottom", (12.0, 10.0), (20.0, 10.0)),
            record("box2-right", (20.0, 10.0), (20.0, 0.0)),
        ),
        document_id="doc-disjoint-boxes",
        revision_id="rev-disjoint-boxes",
        source_sha256="b" * 64,
        snapshot_id="snap-disjoint-boxes",
        page_id="1",
        decision_scope_id="wall-source:page-1",
    )

    result = _derive_scope(scope)

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.scope_complete is False
    assert result.records == ()
    assert SOURCE_ROOM_FACE_COMPONENT_AMBIGUOUS in result.reason_codes



def test_nonfinite_source_edges_cannot_supply_wall_ownership_or_collinear_overlap():
    """NaN previously survived collinearity comparisons as a fake positive span."""
    from pb_source_room_face_authority import (
        _collinear_overlap_edge,
        _edges_share_positive_collinear_span,
        _finite_source_edge,
    )

    clean = ((0.0, 0.0), (10.0, 0.0))
    partial = ((5.0, 0.0), (15.0, 0.0))
    assert _finite_source_edge(clean)
    assert _collinear_overlap_edge(clean, partial) == (
        (5.0, 0.0), (10.0, 0.0)
    )
    assert _edges_share_positive_collinear_span(clean, partial)
    assert _edge_contains_edge(clean, ((1.0, 0.0), (9.0, 0.0)))

    for bad in (float("nan"), float("inf"), float("-inf")):
        malformed = ((bad, 0.0), (7.0, 0.0))
        assert not _finite_source_edge(malformed)
        assert _collinear_overlap_edge(clean, malformed) is None
        assert _collinear_overlap_edge(malformed, clean) is None
        assert not _edges_share_positive_collinear_span(clean, malformed)
        assert not _edge_contains_edge(clean, malformed)
        assert not _edge_contains_edge(malformed, clean)
    assert not _finite_source_edge(((0.0, 0.0), ()))
    assert _collinear_overlap_edge(clean, ((0.0, 0.0), ())) is None
    assert not _edge_contains_edge(clean, ((0.0, 0.0), ()))


def test_finite_source_coordinates_with_overflowed_intermediates_abstain():
    """Finite inputs still cannot authenticate infinite arithmetic results."""
    from pb_source_room_face_authority import (
        _collinear_overlap_edge, _finite_source_edge,
    )

    infinite_length = ((-1e308, 0.0), (1e308, 0.0))
    assert not _finite_source_edge(infinite_length)
    assert not _finite_source_edge(tuple(reversed(infinite_length)))
    finite_child = ((0.0, 0.0), (10.0, 0.0))
    assert not _edge_contains_edge(infinite_length, finite_child)
    assert _collinear_overlap_edge(infinite_length, finite_child) is None
    assert _collinear_overlap_edge(finite_child, infinite_length) is None

    huge_diagonal = ((0.0, 0.0), (1e200, 1e200))
    off_diagonal = ((5e199, 6e199), (9e199, 9e199))
    assert not _edge_contains_edge(huge_diagonal, off_diagonal)
    assert _collinear_overlap_edge(huge_diagonal, off_diagonal) is None

def test_gpt2_b02_publication_exact_wall_owner_requires_real_original_subedge():
    from pb_source_room_face_authority import _publication_boundary_ownership

    ring=((0.0,0.0),(10.0,0.0),(10.0,10.0),(0.0,10.0))
    edges=tuple(_edge(ring[i],ring[(i+1)%len(ring)]) for i in range(len(ring)))
    walls={f"w{i}":(edge,) for i,edge in enumerate(edges)}
    owners={edge:f"w{i}" for i,edge in enumerate(edges)}
    positive=_publication_boundary_ownership(
        ring,edge_owner=owners,wall_edges=walls,
        ownership_grid={},ownership_oversized=[]
    )
    assert positive is not None
    assert set(positive[1])==set(walls)
    for forged in (
        {**owners,edges[0]:"W4-absent"},
        {**owners,edges[0]:"w1"},
    ):
        assert _publication_boundary_ownership(
            ring,edge_owner=forged,wall_edges=walls,
            ownership_grid={},ownership_oversized=[]
        ) is None
    # An index retaining its ID but losing the physical edge cannot
    # publish the same boundary through stale source ancestry.
    missing={**walls,"w0":()}
    assert _publication_boundary_ownership(
        ring,edge_owner=owners,wall_edges=missing,
        ownership_grid={},ownership_oversized=[]
    ) is None


def test_gpt2_upstream_exact_indexed_w4_owner_must_have_original_edge():
    from pb_source_room_face_authority import _unique_containing_wall_owner, _edge

    edge = _edge((0.,0.),(10.,0.))
    independent = _edge((0.,10.),(10.,10.))
    good={"W4-original":(edge,),"other-source-wall":(independent,)}
    assert _unique_containing_wall_owner(
        edge,edge_owner={edge:"W4-original"},wall_edges=good
    )=="W4-original"
    for invalid in (None,17,""," W4-original","W4-foreign"):
        assert _unique_containing_wall_owner(
            edge,edge_owner={edge:invalid},wall_edges=good
        ) is None
    assert _unique_containing_wall_owner(
        edge,edge_owner={edge:"W4-original"},
        wall_edges={"W4-original":(independent,)}
    ) is None
    # Real source-contained original W4 fallback still works unchanged.
    subedge=_edge((2.,0.),(8.,0.))
    assert _unique_containing_wall_owner(
        subedge,edge_owner={},wall_edges=good
    )=="W4-original"


def test_gpt2_containing_wall_owner_rejects_malformed_w4_fallback_keys():
    from pb_source_room_face_authority import _unique_containing_wall_owner, _edge
    parent=_edge((0.,0.),(10.,0.))
    child=_edge((2.,0.),(8.,0.))
    malformed={
        None:(parent,),
        73:(parent,),
        " owner":(parent,),
        "":(parent,),
        "W4-proven":(parent,),
    }
    assert _unique_containing_wall_owner(
        child,edge_owner={},wall_edges=malformed
    )=="W4-proven"
    assert _unique_containing_wall_owner(
        child,edge_owner={},wall_edges={
            None:(parent,),73:(parent,),"":(parent,),
        }
    ) is None
    # Two truly distinct authenticated source wall owners remain a
    # conflict rather than an arbitrary lexicographic first winner.
    assert _unique_containing_wall_owner(
        child,edge_owner={},wall_edges={
            "W4-one":(parent,),"W4-two":(parent,),
        }
    ) is None
