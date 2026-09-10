from __future__ import annotations

import math

from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    ViewportEvidence,
    ViewportResolutionStatus,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import ScaleSourceReading, ScaleSourceType, resolve_page_scale_calibration
from pb_room_area_quantity import build_room_area_quantities, build_room_area_quantity
from pb_wall_room_topology_contracts import RoomCandidate

SHA = "d" * 64


def _context() -> ProviderContext:
    return ProviderContext(
        run_id="run",
        workspace_id="ws",
        project_id="project",
        document_id="doc",
        source_sha256=SHA,
        revision_id="R1",
        current_revision_id="R1",
        selected_pages=(0,),
        owned_viewport_ids=("vp",),
        evidence_snapshot_id="evsnap",
        canonical_graph_snapshot_id="graphsnap",
        measurement_authority_snapshot_id="measuresnap",
        owned_page_numbers=(1,),
        viewport_page_ownership=(("vp", 1),),
    )


def _document(ids=("room-ev", "area-ev")) -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc",
        source_sha256=SHA,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=tuple(ids),
    )


def _viewport() -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id="vp",
        document_id="doc",
        page_id="page-1",
        bbox=(0.0, 0.0, 2000.0, 2000.0),
        view_type="floor_plan",
        status=ViewportResolutionStatus.RESOLVED,
        evidence_ids=("room-ev",),
        confidence=1.0,
    )


def _entity(room_id="r1", ids=("room-ev", "area-ev")) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id=room_id,
        candidate_type="room",
        evidence_ids=tuple(ids),
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=1.0,
    )


def _room(room_id="r1", points=((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)), *, has_voids=False, status=EvidenceResolutionStatus.CORROBORATED) -> RoomCandidate:
    return RoomCandidate(
        room_ref=room_id,
        label="ROOM",
        polygon_pdf_pts=tuple(points),
        polygon_m=None,
        floor_area_m2=None,
        area_page_pts2=10000.0,
        perimeter_m=None,
        geometry_confidence=1.0,
        evidence=("room-ev",),
        source_page=1,
        drawing_number="A101",
        scale_source="scale_bar",
        calibration_confidence=1.0,
        has_voids=has_voids,
        document_id="doc",
        viewport_id="vp",
        status=status,
        bounding_wall_candidate_ids=(),
        adjacent_room_refs=(),
        opening_refs=(),
        exterior_boundary=False,
        explicit_area_label_m2=None,
        area_conflict=None,
        level_id="L1",
        building_component_id="",
    )


def _scale(ratio=100.0, source=ScaleSourceType.SCALE_BAR):
    return resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A101",
        readings=[ScaleSourceReading(source.value, f"1:{ratio:g}", ratio, 1.0)],
        revision_id="R1",
    )


def _explicit_area(value=25.0) -> EvidenceAtom:
    return EvidenceAtom(
        evidence_id="area-ev",
        document_id="doc",
        page_id="page-1",
        viewport_id="vp",
        kind="explicit_room_area",
        method="vector_text",
        raw_text=f"{value:g} m2",
        normalized_value=value,
        unit="m2",
        confidence=1.0,
        status=EvidenceResolutionStatus.CORROBORATED,
    )


def _square_for_area(scale, side_m=5.0, offset=(0.0, 0.0)):
    side = scale.px_per_m * side_m
    ox, oy = offset
    return ((ox, oy), (ox + side, oy), (ox + side, oy + side), (ox, oy + side))


def test_firm_scaled_square_emits_area() -> None:
    scale = _scale()
    room = _room(points=_square_for_area(scale, 5.0))
    qty = build_room_area_quantity(
        room=room,
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
        scale_calibration=scale,
    )
    assert qty.abstained is False
    assert math.isclose(qty.value or 0.0, 25.0, abs_tol=1e-6)
    assert qty.family == "room_area"


def test_translation_is_area_invariant() -> None:
    scale = _scale()
    a = _room(points=_square_for_area(scale, 4.0, (0.0, 0.0)))
    b = _room(points=_square_for_area(scale, 4.0, (500.0, -300.0)))
    kwargs = dict(
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
        scale_calibration=scale,
    )
    assert build_room_area_quantity(room=a, **kwargs).value == 16.0
    assert build_room_area_quantity(room=b, **kwargs).value == 16.0


def test_rotation_and_vertex_reordering_are_area_invariant() -> None:
    scale = _scale()
    pts = _square_for_area(scale, 3.0)
    rotated_order = (pts[2], pts[3], pts[0], pts[1])
    reversed_order = tuple(reversed(pts))
    kwargs = dict(
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
        scale_calibration=scale,
    )
    assert build_room_area_quantity(room=_room(points=pts), **kwargs).value == 9.0
    assert build_room_area_quantity(room=_room(points=rotated_order), **kwargs).value == 9.0
    assert build_room_area_quantity(room=_room(points=reversed_order), **kwargs).value == 9.0


def test_title_block_only_scale_abstains() -> None:
    qty = build_room_area_quantity(
        room=_room(),
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
        scale_calibration=_scale(source=ScaleSourceType.TITLE_BLOCK),
    )
    assert qty.abstained
    assert "scale_not_firm" in qty.blocking_reasons


def test_missing_scale_degradation_abstains_instead_of_inventing_area() -> None:
    qty = build_room_area_quantity(
        room=_room(),
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
    )
    assert qty.abstained
    assert qty.value is None
    assert "no_authoritative_area_input" in qty.blocking_reasons


def test_void_room_abstains_without_explicit_hole_geometry() -> None:
    qty = build_room_area_quantity(
        room=_room(has_voids=True),
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
        scale_calibration=_scale(),
    )
    assert qty.abstained
    assert "room_void_geometry_not_explicit" in qty.blocking_reasons


def test_authoritative_explicit_area_can_resolve_without_scale() -> None:
    qty = build_room_area_quantity(
        room=_room(),
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        explicit_area_evidence=_explicit_area(25.0),
    )
    assert qty.abstained is False
    assert qty.value == 25.0
    assert qty.formula == "authoritative_explicit_area"


def test_explicit_vs_scaled_area_conflict_abstains() -> None:
    scale = _scale()
    room = _room(points=_square_for_area(scale, 5.0))
    qty = build_room_area_quantity(
        room=room,
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scale_calibration=scale,
        explicit_area_evidence=_explicit_area(40.0),
    )
    assert qty.abstained
    assert "explicit_vs_scaled_area_conflict" in qty.blocking_reasons


def test_duplicate_face_with_cyclic_reorder_fails_closed() -> None:
    scale = _scale()
    pts = _square_for_area(scale, 5.0)
    reordered = (pts[2], pts[3], pts[0], pts[1])
    r1 = _room("r1", points=pts)
    r2 = _room("r2", points=reordered)
    out = build_room_area_quantities(
        rooms=(r1, r2),
        entities_by_room_id={
            "r1": _entity("r1", ids=("room-ev",)),
            "r2": _entity("r2", ids=("room-ev",)),
        },
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        page_no=1,
        scale_calibration=scale,
    )
    assert len(out) == 2
    assert all(q.abstained for q in out)
    assert all("duplicate_room_face" in q.blocking_reasons for q in out)
