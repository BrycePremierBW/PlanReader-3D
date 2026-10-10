from __future__ import annotations

import fitz

from pb_drawing_evidence_binding import DrawingViewType
from pb_live_canonical_room_composition import (
    LIVE_CANONICAL_ROOM_PARTIAL,
    LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL,
    LIVE_CANONICAL_ROOM_RESOLVED,
    LIVE_CANONICAL_ROOM_UNAVAILABLE,
    LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED,
    compose_live_canonical_rooms,
)
from pb_live_canonical_wall_composition import compose_live_canonical_walls
from pb_live_wall_opening_authority_composition import (
    compose_live_wall_opening_authority,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_room_face_authority import SourceRoomFaceSelector
from pb_source_visibility_authority import SourceVisibilityProducer


def _page(doc: fitz.Document, *, with_partition: bool) -> None:
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
def _source(*, page_partitions: tuple[bool, ...]):
    doc = fitz.open()
    try:
        for with_partition in page_partitions:
            _page(doc, with_partition=with_partition)
        payload = doc.tobytes()
    finally:
        doc.close()

    source = SourceVisibilityProducer(
        producer_method="live-canonical-room-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="live-canonical-room-test-doc",
        source_bytes=payload,
        source_locator="memory://live-canonical-room-test.pdf",
    )
    page_ids = tuple(str(index + 1) for index in range(len(page_partitions)))
    wall_opening = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=page_ids,
    )
    return source, wall_opening


def test_two_room_source_publishes_stable_canonical_room_objects() -> None:
    source, wall_opening = _source(page_partitions=(True,))

    wall_core = compose_live_canonical_walls(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )
    result = compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
        canonical_wall_ids_by_candidate=(
            wall_core.candidate_to_canonical_wall_id
        ),
        unresolved_wall_candidate_ids=(
            wall_core.unresolved_wall_candidate_ids
        ),
    )

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.reason_codes == (LIVE_CANONICAL_ROOM_RESOLVED,)
    assert result.source_pages == (1,)
    assert len(result.rooms) == 2
    ids = {room.canonical_room_id for room in result.rooms}
    assert len(ids) == 2
    for room in result.rooms:
        assert room.canonical_room_id == room.physical_room_id
        assert room.page_id == "1"
        assert room.viewport_id is None
        assert room.coordinate_unit == "pdf_pt"
        assert room.geometry_complete is True
        assert room.metric_geometry_complete is False
        assert len(room.polygon_pdf_pts) >= 4
        assert room.bounding_wall_ids
        assert room.canonical_bounding_wall_ids
        assert room.wall_relationships_complete is False
        assert room.area_page_pts2 > 0.0
        assert room.evidence_ids == (room.source_room_face_record_id,)
        payload = room.to_dict()
        assert payload["canonical_room_id"] == room.canonical_room_id
        assert payload["polygon_pdf_pts"]
        assert payload["bounding_wall_ids"]
        assert payload["canonical_bounding_wall_ids"]
        assert payload["wall_relationships_complete"] is False

        room_binding = result.room_face_authority_binding_for(room)
        assert room_binding is not None
        assert room_binding.viewport_id is None
        assert room_binding.viewport_bbox is None
        room_authority = result.room_face_authority_for(room)
        assert room_authority is room_binding.authority
        resolved = room_authority.resolve_scope(
            SourceRoomFaceSelector(
                document_id=room.document_id,
                revision_id=room.revision_id,
                source_sha256=room.source_sha256,
                snapshot_id=room.snapshot_id,
                page_id=room.page_id,
                decision_scope_id=room.decision_scope_id,
            )
        )
        assert resolved.status is EvidenceResolutionStatus.CORROBORATED
        assert resolved.scope_complete is True
        assert sum(
            record.record_id == room.source_room_face_record_id
            for record in resolved.records
        ) == 1


def test_valid_rooms_publish_but_partial_face_universe_stays_candidate() -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=250)
        for first, second in (
            ((50.0, 50.0), (250.0, 50.0)),
            ((250.0, 50.0), (250.0, 150.0)),
            ((250.0, 150.0), (50.0, 150.0)),
            ((50.0, 150.0), (50.0, 50.0)),
            ((150.0, 50.0), (150.0, 150.0)),
            # A speck larger than the wall graph's 2.5pt gap-snap tolerance (a
            # smaller one is snapped away and never becomes a face) yet far under
            # 1% of the largest face, so it is a genuine degenerate face.
            ((300.0, 50.0), (306.0, 50.0)),
            ((306.0, 50.0), (306.0, 56.0)),
            ((306.0, 56.0), (300.0, 56.0)),
            ((300.0, 56.0), (300.0, 50.0)),
        ):
            page.draw_line(
                fitz.Point(*first),
                fitz.Point(*second),
                color=(0, 0, 0),
                width=1,
            )
        payload = doc.tobytes()
    finally:
        doc.close()

    source = SourceVisibilityProducer(
        producer_method="live-canonical-room-partial-universe-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="live-canonical-room-partial-universe-doc",
        source_bytes=payload,
        source_locator="memory://live-canonical-room-partial-universe.pdf",
    )
    wall_opening = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )

    result = compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.CANDIDATE
    assert LIVE_CANONICAL_ROOM_PARTIAL in result.reason_codes
    assert LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL in result.reason_codes
    assert result.source_pages == (1,)
    assert len(result.rooms) == 2


def test_single_box_fails_closed_without_minting_room_object() -> None:
    source, wall_opening = _source(page_partitions=(False,))

    result = compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert LIVE_CANONICAL_ROOM_UNAVAILABLE in result.reason_codes
    assert result.rooms == ()
    assert result.source_pages == ()


def test_mixed_page_resolution_is_candidate_not_corroborated() -> None:
    source, wall_opening = _source(page_partitions=(True, False))

    result = compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.CANDIDATE
    assert result.reason_codes[0] == LIVE_CANONICAL_ROOM_PARTIAL
    assert result.source_pages == (1,)
    assert len(result.rooms) == 2


def _viewport_fallback_source(
    *,
    drawing_title: str = "GROUND FLOOR PLAN",
):
    doc = fitz.open()
    try:
        page = doc.new_page(width=400.0, height=300.0)

        # Positive physical drawing ownership: one real native vector frame.
        page.draw_rect(
            fitz.Rect(30.0, 30.0, 300.0, 270.0),
            color=(0, 0, 0),
            width=1.0,
        )
        page.insert_text((80.0, 60.0), drawing_title, fontsize=10.0)

        # Reference content exists elsewhere on the same sheet. The title is
        # explicit but intentionally unbounded, and one source line sits in
        # that reference region. Whole-page wall ownership must therefore fail
        # closed rather than absorbing it into the floor-plan topology.
        page.insert_text((325.0, 70.0), "LEGEND", fontsize=10.0)
        page.draw_line(
            fitz.Point(325.0, 150.0),
            fitz.Point(385.0, 150.0),
            color=(0, 0, 0),
            width=1.0,
        )

        # Two closed rooms wholly inside the authenticated floor-plan frame.
        for first, second in (
            ((70.0, 90.0), (270.0, 90.0)),
            ((270.0, 90.0), (270.0, 240.0)),
            ((270.0, 240.0), (70.0, 240.0)),
            ((70.0, 240.0), (70.0, 90.0)),
            ((170.0, 90.0), (170.0, 240.0)),
        ):
            page.draw_line(
                fitz.Point(*first),
                fitz.Point(*second),
                color=(0, 0, 0),
                width=1.0,
            )

        payload = doc.tobytes()
    finally:
        doc.close()

    source = SourceVisibilityProducer(
        producer_method="live-canonical-room-viewport-fallback-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="live-canonical-room-viewport-fallback-doc",
        source_bytes=payload,
        source_locator="memory://live-canonical-room-viewport-fallback.pdf",
    )
    wall_opening = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )
    return source, wall_opening


def test_floor_finish_support_view_cannot_mint_canonical_room_topology() -> None:
    source, wall_opening = _viewport_fallback_source(
        drawing_title="FLOOR FINISHES & PARTITIONS PLAN",
    )

    result = compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert LIVE_CANONICAL_ROOM_UNAVAILABLE in result.reason_codes
    assert result.rooms == ()
    assert result.source_pages == ()


def test_unresolved_page_room_scope_falls_back_to_authenticated_floor_plan_viewport() -> None:
    source, wall_opening = _viewport_fallback_source()

    result = compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.reason_codes == (
        LIVE_CANONICAL_ROOM_RESOLVED,
        LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED,
    )
    assert result.source_pages == (1,)
    assert len(result.rooms) == 2
    assert all(room.viewport_id for room in result.rooms)
    assert all(
        room.decision_scope_id.startswith("wall-source:viewport:1:")
        for room in result.rooms
    )
    assert all(room.geometry_complete is True for room in result.rooms)
    assert all(room.metric_geometry_complete is False for room in result.rooms)
    # The fallback does not guess a relationship to page-wide canonical walls.
    assert all(room.canonical_bounding_wall_ids == () for room in result.rooms)
    assert all(room.wall_relationships_complete is False for room in result.rooms)
    for room in result.rooms:
        room_binding = result.room_face_authority_binding_for(room)
        assert room_binding is not None
        assert room_binding.viewport_id == room.viewport_id
        assert room_binding.viewport_bbox is not None
        assert room_binding.viewport_view_type == DrawingViewType.FLOOR_PLAN.value
        room_authority = result.room_face_authority_for(room)
        assert room_authority is room_binding.authority
        resolved = room_authority.resolve_scope(
            SourceRoomFaceSelector(
                document_id=room.document_id,
                revision_id=room.revision_id,
                source_sha256=room.source_sha256,
                snapshot_id=room.snapshot_id,
                page_id=room.page_id,
                decision_scope_id=room.decision_scope_id,
            )
        )
        assert resolved.status is EvidenceResolutionStatus.CORROBORATED
        assert resolved.scope_complete is True
        assert sum(
            record.record_id == room.source_room_face_record_id
            for record in resolved.records
        ) == 1

    # Runtime authority provenance is not recreated by copying public room data.
    rebuilt = type(result)(
        status=result.status,
        reason_codes=result.reason_codes,
        rooms=result.rooms,
        source_pages=result.source_pages,
    )
    assert all(
        rebuilt.room_face_authority_binding_for(room) is None
        and rebuilt.room_face_authority_for(room) is None
        for room in rebuilt.rooms
    )


def test_incomplete_viewport_wall_scope_is_delegated_to_room_authority(monkeypatch) -> None:
    """Let source-room authority decide whether an incomplete wall scope is locally safe."""
    from types import SimpleNamespace
    import pb_live_canonical_room_composition as module

    source, wall_opening = _source(page_partitions=(False,))
    published = source.published_snapshot_for_revision(wall_opening.revision_id)
    assert published is not None

    selector = SimpleNamespace(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        decision_scope_id="wall-source:viewport:1:local-proof",
    )
    wall_scope = SimpleNamespace(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=False,
        records=(object(),),
        reason_codes=("physical_wall_candidate_scope_bounds_unresolved",),
        viewport_id="floor-plan-vp",
    )
    viewport_wall_authority = SimpleNamespace(
        selectors_for_authenticated_viewports=lambda **_kwargs: (selector,),
        resolve_scope=lambda _selector: wall_scope,
    )
    viewport_wall_producer = SimpleNamespace(authority=lambda: viewport_wall_authority)

    page_room_authority = SimpleNamespace(
        resolve_scope=lambda _selector: SimpleNamespace(
            status=EvidenceResolutionStatus.ABSTAINED,
            scope_complete=False,
            records=(),
            reason_codes=("page_room_unavailable",),
            face_universe_complete=False,
        )
    )
    record = SimpleNamespace(
        face_id="source-room-face-local-proof",
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        decision_scope_id=selector.decision_scope_id,
        polygon_pdf_pts=((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)),
        bounding_wall_ids=("w1", "w2", "w3", "w4"),
        area_page_pts2=100.0,
        record_id="source-room-face-record-local-proof",
    )
    viewport_room_authority = SimpleNamespace(
        resolve_scope=lambda _selector: SimpleNamespace(
            status=EvidenceResolutionStatus.CORROBORATED,
            scope_complete=True,
            records=(record,),
            reason_codes=("source_room_face_boundary_local_recovery",),
            face_universe_complete=False,
        )
    )

    monkeypatch.setattr(
        module.PhysicalWallCandidateProducer,
        "from_authenticated_viewports",
        classmethod(lambda cls, *_args, **_kwargs: viewport_wall_producer),
    )
    monkeypatch.setattr(
        module,
        "build_source_room_face_authority",
        lambda authority: (
            viewport_room_authority
            if authority is viewport_wall_authority
            else page_room_authority
        ),
    )

    result = module.compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.CANDIDATE
    assert LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED in result.reason_codes
    assert LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL in result.reason_codes
    assert result.source_pages == (1,)
    assert len(result.rooms) == 1
    assert result.rooms[0].source_room_face_record_id == record.record_id
    assert result.rooms[0].viewport_id == "floor-plan-vp"


def test_incomplete_viewport_wall_scope_cannot_publish_when_room_authority_abstains(monkeypatch) -> None:
    from types import SimpleNamespace
    import pb_live_canonical_room_composition as module

    source, wall_opening = _source(page_partitions=(False,))
    published = source.published_snapshot_for_revision(wall_opening.revision_id)
    assert published is not None

    selector = SimpleNamespace(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        decision_scope_id="wall-source:viewport:1:no-room-proof",
    )
    wall_scope = SimpleNamespace(
        status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=False,
        records=(object(),),
        reason_codes=("physical_wall_candidate_scope_bounds_unresolved",),
        viewport_id="floor-plan-vp",
    )
    viewport_wall_authority = SimpleNamespace(
        selectors_for_authenticated_viewports=lambda **_kwargs: (selector,),
        resolve_scope=lambda _selector: wall_scope,
    )
    viewport_wall_producer = SimpleNamespace(authority=lambda: viewport_wall_authority)
    abstaining_room_authority = SimpleNamespace(
        resolve_scope=lambda _selector: SimpleNamespace(
            status=EvidenceResolutionStatus.ABSTAINED,
            scope_complete=False,
            records=(),
            reason_codes=("source_room_face_scope_unavailable",),
            face_universe_complete=False,
        )
    )

    monkeypatch.setattr(
        module.PhysicalWallCandidateProducer,
        "from_authenticated_viewports",
        classmethod(lambda cls, *_args, **_kwargs: viewport_wall_producer),
    )
    monkeypatch.setattr(
        module,
        "build_source_room_face_authority",
        lambda _authority: abstaining_room_authority,
    )

    result = module.compose_live_canonical_rooms(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.rooms == ()
    assert result.source_pages == ()



def test_physical_room_identity_ignores_evidence_revision_fingerprints() -> None:
    from types import SimpleNamespace
    import pb_live_canonical_room_composition as module

    polygon = (
        (10.0, 10.0),
        (20.0, 10.0),
        (20.0, 20.0),
        (10.0, 20.0),
    )
    first = SimpleNamespace(
        face_id="source-face-revision-a",
        record_id="source-face-record-revision-a",
        document_id="logical-document-1",
        revision_id="revision-a",
        source_sha256="a" * 64,
        snapshot_id="snapshot-a",
        page_id="7",
        decision_scope_id="wall-source:viewport:7:first",
        polygon_pdf_pts=polygon,
        bounding_wall_ids=("w1", "w2", "w3", "w4"),
        area_page_pts2=100.0,
    )
    second = SimpleNamespace(
        face_id="source-face-revision-b",
        record_id="source-face-record-revision-b",
        document_id="logical-document-1",
        revision_id="revision-b",
        source_sha256="b" * 64,
        snapshot_id="snapshot-b",
        page_id="7",
        decision_scope_id="wall-source:viewport:7:second",
        polygon_pdf_pts=polygon,
        bounding_wall_ids=("new-w1", "new-w2", "new-w3", "new-w4"),
        area_page_pts2=100.0,
    )

    left = module._room_object_from_record(
        first,
        viewport_id="floor-plan-view",
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )
    right = module._room_object_from_record(
        second,
        viewport_id="floor-plan-view",
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )

    assert left.physical_room_id == right.physical_room_id
    assert left.canonical_room_id == right.canonical_room_id
    assert left.source_room_face_record_id != right.source_room_face_record_id
    assert left.evidence_ids != right.evidence_ids


def test_physical_room_identity_is_invariant_to_polygon_start_vertex_and_winding() -> None:
    from types import SimpleNamespace
    import pb_live_canonical_room_composition as module

    def room_record(polygon):
        return SimpleNamespace(
            face_id="evidence-face",
            record_id="evidence-record",
            document_id="doc-a",
            revision_id="revision",
            source_sha256="c" * 64,
            snapshot_id="snapshot",
            page_id="1",
            decision_scope_id="wall-source:page-1",
            polygon_pdf_pts=polygon,
            bounding_wall_ids=("w1", "w2", "w3", "w4"),
            area_page_pts2=100.0,
        )

    base = (
        (10.0, 10.0),
        (20.0, 10.0),
        (20.0, 20.0),
        (10.0, 20.0),
    )
    shifted = (
        (20.0, 20.0),
        (10.0, 20.0),
        (10.0, 10.0),
        (20.0, 10.0),
    )
    reversed_winding = (
        (10.0, 10.0),
        (10.0, 20.0),
        (20.0, 20.0),
        (20.0, 10.0),
    )

    ids = {
        module._room_object_from_record(
            room_record(polygon),
            viewport_id="floor-plan-view",
            canonical_wall_ids_by_candidate=None,
            unresolved_wall_candidate_ids=None,
        ).physical_room_id
        for polygon in (base, shifted, reversed_winding)
    }
    assert len(ids) == 1


def test_physical_room_identity_uses_same_six_decimal_geometry_contract_as_source_faces() -> None:
    from types import SimpleNamespace
    import pb_live_canonical_room_composition as module

    def room_record(polygon):
        return SimpleNamespace(
            face_id="evidence-face",
            record_id="evidence-record",
            document_id="doc-a",
            revision_id="revision",
            source_sha256="c" * 64,
            snapshot_id="snapshot",
            page_id="1",
            decision_scope_id="wall-source:page-1",
            polygon_pdf_pts=polygon,
            bounding_wall_ids=("w1", "w2", "w3", "w4"),
            area_page_pts2=100.0,
        )

    base = (
        (10.0, 10.0),
        (20.0, 10.0),
        (20.0, 20.0),
        (10.0, 20.0),
    )
    sub_quantum_noise = (
        (10.0000004, 9.9999996),
        (20.0000004, 10.0000004),
        (19.9999996, 20.0000004),
        (9.9999996, 19.9999996),
    )

    left = module._room_object_from_record(
        room_record(base),
        viewport_id="floor-plan-view",
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )
    right = module._room_object_from_record(
        room_record(sub_quantum_noise),
        viewport_id="floor-plan-view",
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )
    assert left.physical_room_id == right.physical_room_id


def test_physical_room_identity_keeps_distinct_rooms_and_documents_distinct() -> None:
    from types import SimpleNamespace
    import pb_live_canonical_room_composition as module

    def room_record(*, document_id: str, polygon):
        return SimpleNamespace(
            face_id="evidence-face",
            record_id="evidence-record",
            document_id=document_id,
            revision_id="revision",
            source_sha256="c" * 64,
            snapshot_id="snapshot",
            page_id="1",
            decision_scope_id="wall-source:page-1",
            polygon_pdf_pts=polygon,
            bounding_wall_ids=("w1", "w2", "w3", "w4"),
            area_page_pts2=100.0,
        )

    first_polygon = (
        (10.0, 10.0),
        (20.0, 10.0),
        (20.0, 20.0),
        (10.0, 20.0),
    )
    second_polygon = (
        (30.0, 10.0),
        (40.0, 10.0),
        (40.0, 20.0),
        (30.0, 20.0),
    )

    first = module._room_object_from_record(
        room_record(document_id="doc-a", polygon=first_polygon),
        viewport_id=None,
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )
    other_room = module._room_object_from_record(
        room_record(document_id="doc-a", polygon=second_polygon),
        viewport_id=None,
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )
    other_document = module._room_object_from_record(
        room_record(document_id="doc-b", polygon=first_polygon),
        viewport_id=None,
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )
    other_view = module._room_object_from_record(
        room_record(document_id="doc-a", polygon=first_polygon),
        viewport_id="detail-view",
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
    )

    assert len(
        {
            first.physical_room_id,
            other_room.physical_room_id,
            other_document.physical_room_id,
            other_view.physical_room_id,
        }
    ) == 4


def test_canonical_grid_composite_supersedes_only_its_original_face_cells():
    """Do not publish both component cells and their canonical room union."""
    from types import SimpleNamespace
    from pb_live_canonical_room_composition import _canonical_composite_supersedence

    originals = tuple(
        SimpleNamespace(face_id=face_id, record_id="source_" + face_id)
        for face_id in ("left", "right", "unrelated")
    )
    composite = SimpleNamespace(
        record_id="composite_real",
        constituent_face_ids=("left", "right"),
        constituent_source_room_face_record_ids=("source_left", "source_right"),
    )
    remaining, published = _canonical_composite_supersedence(
        originals, (composite,)
    )
    assert tuple(face.face_id for face in remaining) == ("unrelated",)
    assert published == (composite,)
    # The producer-owned SourceRoomFace receipt universe is not mutated.
    assert len(originals) == 3


def test_canonical_composite_unknown_or_competing_cell_abstains():
    from types import SimpleNamespace
    from pb_live_canonical_room_composition import _canonical_composite_supersedence

    originals = tuple(
        SimpleNamespace(face_id=x, record_id="source_" + x)
        for x in ("a", "b", "c")
    )
    valid = SimpleNamespace(
        record_id="valid", constituent_face_ids=("a", "b"),
        constituent_source_room_face_record_ids=("source_a", "source_b"),
    )
    unknown = SimpleNamespace(
        record_id="unknown", constituent_face_ids=("a", "missing"),
        constituent_source_room_face_record_ids=("source_a", "source_missing"),
    )
    duplicate = SimpleNamespace(
        record_id="duplicate", constituent_face_ids=("b", "b"),
        constituent_source_room_face_record_ids=("source_b", "source_b"),
    )
    overlapping = SimpleNamespace(
        record_id="other", constituent_face_ids=("b", "c"),
        constituent_source_room_face_record_ids=("source_b", "source_c"),
    )

    for composite in (unknown, duplicate):
        remaining, published = _canonical_composite_supersedence(
            originals, (composite,)
        )
        assert remaining == originals
        assert published == ()

    remaining, published = _canonical_composite_supersedence(
        originals, (valid, overlapping)
    )
    # An overlapping candidate cannot quietly retire any component cell.
    assert remaining == originals
    assert published == ()

    remaining, published = _canonical_composite_supersedence(originals, ())
    assert remaining == originals
    assert published == ()


def test_canonical_composite_abstains_when_original_face_identity_is_duplicated():
    from types import SimpleNamespace
    from pb_live_canonical_room_composition import _canonical_composite_supersedence

    # A duplicate physical SourceRoomFace identity cannot be retired twice by
    # one composite witness, even when the composite lists each ID once.
    originals = (
        SimpleNamespace(face_id="a", record_id="a1"),
        SimpleNamespace(face_id="a", record_id="a2"),
        SimpleNamespace(face_id="b", record_id="b1"),
        SimpleNamespace(face_id="c", record_id="c1"),
    )
    composite = SimpleNamespace(
        record_id="candidate",
        constituent_face_ids=("a", "b"),
        constituent_source_room_face_record_ids=("a1", "b1"),
    )
    remaining, accepted = _canonical_composite_supersedence(originals, (composite,))
    assert remaining == originals
    assert accepted == ()

    # A separate genuine two-face composite can still publish independently.
    independent = SimpleNamespace(
        record_id="independent",
        constituent_face_ids=("b", "c"),
        constituent_source_room_face_record_ids=("b1", "c1"),
    )
    remaining, accepted = _canonical_composite_supersedence(
        originals, (independent,)
    )
    assert accepted == (independent,)
    assert tuple(v.record_id for v in remaining) == ("a1", "a2")

    # One-face replacements are not room compositions and cannot retire cells.
    singleton = SimpleNamespace(
        record_id="singleton",
        constituent_face_ids=("b",),
        constituent_source_room_face_record_ids=("b1",),
    )
    remaining, accepted = _canonical_composite_supersedence(
        originals, (singleton,)
    )
    assert remaining == originals
    assert accepted == ()


def test_canonical_composite_requires_exact_original_source_receipt_lineage():
    from types import SimpleNamespace
    from pb_live_canonical_room_composition import _canonical_composite_supersedence

    originals = (
        SimpleNamespace(face_id="a", record_id="original_a"),
        SimpleNamespace(face_id="b", record_id="original_b"),
    )
    missing = SimpleNamespace(
        record_id="composite_missing",
        constituent_face_ids=("a", "b"),
    )
    stale = SimpleNamespace(
        record_id="composite_stale",
        constituent_face_ids=("a", "b"),
        constituent_source_room_face_record_ids=("old_a", "original_b"),
    )
    reversed_receipts = SimpleNamespace(
        record_id="composite_reversed",
        constituent_face_ids=("a", "b"),
        constituent_source_room_face_record_ids=("original_b", "original_a"),
    )
    for composite in (missing, stale, reversed_receipts):
        remaining, accepted = _canonical_composite_supersedence(
            originals, (composite,)
        )
        assert remaining == originals
        assert accepted == ()

    valid = SimpleNamespace(
        record_id="composite_valid",
        constituent_face_ids=("a", "b"),
        constituent_source_room_face_record_ids=("original_a", "original_b"),
    )
    remaining, accepted = _canonical_composite_supersedence(
        originals, (valid,)
    )
    assert remaining == ()
    assert accepted == (valid,)


def test_canonical_composite_rejects_duplicate_producer_receipts_on_distinct_faces():
    from types import SimpleNamespace
    from pb_live_canonical_room_composition import _canonical_composite_supersedence

    originals = (
        SimpleNamespace(face_id="left", record_id="receipt_shared"),
        SimpleNamespace(face_id="right", record_id="receipt_shared"),
        SimpleNamespace(face_id="top", record_id="receipt_top"),
        SimpleNamespace(face_id="bottom", record_id="receipt_bottom"),
    )
    ambiguous = SimpleNamespace(
        record_id="invalid_composite",
        constituent_face_ids=("left", "right"),
        constituent_source_room_face_record_ids=("receipt_shared", "receipt_shared"),
    )
    remaining, accepted = _canonical_composite_supersedence(
        originals, (ambiguous,)
    )
    assert remaining == originals
    assert accepted == ()
    # A separate unique producer-owned pair can still retire *its own* cells.
    genuine = SimpleNamespace(
        record_id="valid_composite",
        constituent_face_ids=("top", "bottom"),
        constituent_source_room_face_record_ids=("receipt_top", "receipt_bottom"),
    )
    remaining, accepted = _canonical_composite_supersedence(
        originals, (genuine,)
    )
    assert accepted == (genuine,)
    assert remaining == originals[:2]


def test_canonical_composite_requires_nonblank_source_receipts():
    from types import SimpleNamespace
    from pb_live_canonical_room_composition import _canonical_composite_supersedence

    for bad_id in ("", "   ", None):
        originals = (
            SimpleNamespace(face_id="left", record_id=bad_id),
            SimpleNamespace(face_id="right", record_id="receipt_right"),
        )
        invalid = SimpleNamespace(
            record_id="invalid_composite",
            constituent_face_ids=("left", "right"),
            constituent_source_room_face_record_ids=(
                "None" if bad_id is None else str(bad_id), "receipt_right"
            ),
        )
        remaining, accepted = _canonical_composite_supersedence(
            originals, (invalid,)
        )
        assert remaining == originals
        assert accepted == ()
    # Missing attributes are not producer-owned source receipts either.
    missing = (
        SimpleNamespace(face_id="left"),
        SimpleNamespace(face_id="right", record_id="receipt_right"),
    )
    invalid = SimpleNamespace(
        constituent_face_ids=("left", "right"),
        constituent_source_room_face_record_ids=("", "receipt_right"),
    )
    remaining, accepted = _canonical_composite_supersedence(
        missing, (invalid,)
    )
    assert remaining == missing
    assert accepted == ()
