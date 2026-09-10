from __future__ import annotations

import math

from pb_measurement_input_authority import scale_calibration_fingerprint
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    ViewportEvidence,
    ViewportResolutionStatus,
)
from pb_migration_provider_envelope import ProviderContext
from pb_page_scale_calibration_authority import (
    ScaleSourceReading,
    ScaleSourceType,
    resolve_page_scale_calibration,
)
from pb_room_area_quantity import build_room_area_quantities, build_room_area_quantity
from pb_wall_room_topology_contracts import RoomCandidate

SHA = "d" * 64


def _context(
    *,
    revision: str | None = "R1",
    current: str | None = "R1",
    multi_viewport: bool = False,
) -> ProviderContext:
    viewport_ids = ("vp", "vp2") if multi_viewport else ("vp",)
    ownership = (("vp", 1), ("vp2", 1)) if multi_viewport else (("vp", 1),)
    return ProviderContext(
        run_id="run",
        workspace_id="ws",
        project_id="project",
        document_id="doc",
        source_sha256=SHA,
        revision_id=revision,
        current_revision_id=current,
        selected_pages=(0,),
        owned_viewport_ids=viewport_ids,
        evidence_snapshot_id="evsnap",
        canonical_graph_snapshot_id="graphsnap",
        measurement_authority_snapshot_id="measuresnap",
        owned_page_numbers=(1,),
        viewport_page_ownership=ownership,
    )


def _document(ids: tuple[str, ...] = ("room-ev", "area-ev")) -> DocumentEvidence:
    return DocumentEvidence(
        document_id="doc",
        source_sha256=SHA,
        page_count=1,
        page_ids=("page-1",),
        evidence_ids=ids,
    )


def _viewport(*, resolved_scale_id: str | None = None, status=ViewportResolutionStatus.RESOLVED) -> ViewportEvidence:
    return ViewportEvidence(
        viewport_id="vp",
        document_id="doc",
        page_id="page-1",
        bbox=(0.0, 0.0, 2000.0, 2000.0),
        view_type="floor_plan",
        status=status,
        evidence_ids=("room-ev",),
        resolved_scale_id=resolved_scale_id,
        confidence=1.0,
    )


def _entity(
    room_id: str = "r1",
    *,
    ids: tuple[str, ...] = ("room-ev", "area-ev"),
    status=EvidenceResolutionStatus.CORROBORATED,
) -> EntityEvidence:
    return EntityEvidence(
        candidate_entity_id=room_id,
        candidate_type="room",
        evidence_ids=ids,
        status=status,
        confidence=1.0,
    )


def _room(
    room_id: str = "r1",
    *,
    points=((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)),
    has_voids: bool = False,
    status=EvidenceResolutionStatus.CORROBORATED,
    floor_area_m2: float | None = None,
    explicit_area_label_m2: float | None = None,
    area_conflict=None,
) -> RoomCandidate:
    return RoomCandidate(
        room_ref=room_id,
        label="ROOM",
        polygon_pdf_pts=tuple(points),
        polygon_m=None,
        floor_area_m2=floor_area_m2,
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
        explicit_area_label_m2=explicit_area_label_m2,
        area_conflict=area_conflict,
        level_id="L1",
        building_component_id="",
    )


def _scale(*, ratio=100.0, revision: str | None = "R1", source=ScaleSourceType.SCALE_BAR):
    return resolve_page_scale_calibration(
        page_no=1,
        sheet_label="A101",
        readings=[ScaleSourceReading(source.value, f"1:{ratio:g}", ratio, 1.0)],
        revision_id=revision,
    )


def _explicit_area(value=25.0, *, status=EvidenceResolutionStatus.CORROBORATED) -> EvidenceAtom:
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
        status=status,
    )


def _square(scale, side_m=5.0, offset=(0.0, 0.0)):
    side = scale.px_per_m * side_m
    ox, oy = offset
    return ((ox, oy), (ox + side, oy), (ox + side, oy + side), (ox, oy + side))


def _scaled_qty(*, room=None, scale=None, context=None, viewport=None, entity=None):
    scale = scale or _scale()
    room = room or _room(points=_square(scale))
    return build_room_area_quantity(
        room=room,
        context=context or _context(),
        document=_document(ids=("room-ev",)),
        viewport=viewport or _viewport(),
        entity=entity or _entity(ids=("room-ev",)),
        page_no=1,
        scale_calibration=scale,
    )


def test_firm_current_scale_emits_room_area() -> None:
    qty = _scaled_qty()
    assert qty.abstained is False
    assert math.isclose(qty.value or 0.0, 25.0, abs_tol=1e-6)
    assert qty.family == "room_area"
    assert qty.semantic_key == "room_area:r1"
    assert qty.status == "firm"


def test_translation_rotation_and_ring_order_are_area_invariant() -> None:
    scale = _scale()
    pts = _square(scale, side_m=4.0)
    variants = (
        pts,
        tuple((x + 700.0, y - 300.0) for x, y in pts),
        (pts[2], pts[3], pts[0], pts[1]),
        tuple(reversed(pts)),
    )
    values = [
        _scaled_qty(room=_room(points=v), scale=scale).value
        for v in variants
    ]
    assert values == [16.0, 16.0, 16.0, 16.0]


def test_candidate_entity_cannot_emit_numeric_area() -> None:
    qty = _scaled_qty(entity=_entity(ids=("room-ev",), status=EvidenceResolutionStatus.CANDIDATE))
    assert qty.abstained is True
    assert "entity_unresolved" in qty.blocking_reasons


def test_candidate_room_topology_cannot_emit_numeric_area() -> None:
    qty = _scaled_qty(room=_room(status=EvidenceResolutionStatus.CANDIDATE))
    assert qty.abstained is True
    assert "room_topology_not_corroborated" in qty.blocking_reasons


def test_unversioned_scale_abstains() -> None:
    scale = _scale(revision=None)
    qty = _scaled_qty(room=_room(points=_square(scale)), scale=scale)
    assert qty.abstained is True
    assert "scale_revision_unbound" in qty.blocking_reasons


def test_stale_run_revision_abstains_before_area() -> None:
    qty = _scaled_qty(context=_context(revision="R0", current="R1"))
    assert qty.abstained is True
    assert "stale_revision" in qty.blocking_reasons


def test_title_block_scale_is_not_firm() -> None:
    scale = _scale(source=ScaleSourceType.TITLE_BLOCK)
    qty = _scaled_qty(room=_room(points=_square(scale)), scale=scale)
    assert qty.abstained is True
    assert "scale_not_firm" in qty.blocking_reasons


def test_multi_viewport_page_requires_exact_scale_binding() -> None:
    scale = _scale()
    room = _room(points=_square(scale))
    blocked = _scaled_qty(
        room=room,
        scale=scale,
        context=_context(multi_viewport=True),
        viewport=_viewport(resolved_scale_id=None),
    )
    assert blocked.abstained is True
    assert "scale_not_bound_to_multi_viewport" in blocked.blocking_reasons

    scale_id = scale_calibration_fingerprint(scale)
    accepted = _scaled_qty(
        room=room,
        scale=scale,
        context=_context(multi_viewport=True),
        viewport=_viewport(resolved_scale_id=scale_id),
    )
    assert accepted.abstained is False
    assert accepted.value == 25.0
    assert accepted.metadata["scale_fingerprint"] == scale_id


def test_explicit_area_requires_corroborated_owned_evidence() -> None:
    qty = build_room_area_quantity(
        room=_room(),
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        explicit_area_evidence=_explicit_area(status=EvidenceResolutionStatus.CANDIDATE),
    )
    assert qty.abstained is True
    assert "explicit_area_not_corroborated" in qty.blocking_reasons


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
    qty = build_room_area_quantity(
        room=_room(points=_square(scale, side_m=5.0)),
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        scale_calibration=scale,
        explicit_area_evidence=_explicit_area(40.0),
    )
    assert qty.abstained is True
    assert "explicit_vs_scaled_area_conflict" in qty.blocking_reasons


def test_void_geometry_requires_authoritative_explicit_area() -> None:
    scale = _scale()
    blocked = _scaled_qty(room=_room(points=_square(scale), has_voids=True), scale=scale)
    assert blocked.abstained is True
    assert "room_void_geometry_not_explicit" in blocked.blocking_reasons

    explicit = build_room_area_quantity(
        room=_room(points=_square(scale), has_voids=True),
        context=_context(),
        document=_document(),
        viewport=_viewport(),
        entity=_entity(),
        page_no=1,
        explicit_area_evidence=_explicit_area(25.0),
    )
    assert explicit.abstained is False
    assert explicit.value == 25.0


def test_prefilled_room_numeric_fields_are_not_authority() -> None:
    room = _room(floor_area_m2=999.0, explicit_area_label_m2=777.0)
    no_evidence = build_room_area_quantity(
        room=room,
        context=_context(),
        document=_document(ids=("room-ev",)),
        viewport=_viewport(),
        entity=_entity(ids=("room-ev",)),
        page_no=1,
    )
    assert no_evidence.abstained is True
    assert no_evidence.value is None
    assert "no_authoritative_area_input" in no_evidence.blocking_reasons

    scale = _scale()
    scaled_room = _room(
        points=_square(scale),
        floor_area_m2=999.0,
        explicit_area_label_m2=777.0,
    )
    scaled = _scaled_qty(room=scaled_room, scale=scale)
    assert scaled.abstained is False
    assert scaled.value == 25.0
    assert scaled.value != scaled_room.floor_area_m2
    assert scaled.value != scaled_room.explicit_area_label_m2


def test_room_area_conflict_always_blocks() -> None:
    scale = _scale()
    room = _room(
        points=_square(scale),
        area_conflict={"polygon_area_m2": 25.0, "explicit_area_m2": 40.0},
    )
    qty = _scaled_qty(room=room, scale=scale)
    assert qty.abstained is True
    assert "room_area_conflict" in qty.blocking_reasons


def test_duplicate_face_and_duplicate_identity_fail_closed() -> None:
    scale = _scale()
    pts = _square(scale)
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


def test_quantity_identity_is_deterministic_and_scale_sensitive() -> None:
    scale = _scale()
    room = _room(points=_square(scale))
    first = _scaled_qty(room=room, scale=scale)
    second = _scaled_qty(room=room, scale=scale)
    assert first.quantity_id == second.quantity_id
    assert first.to_dict() == second.to_dict()

    other_scale = _scale(ratio=50.0)
    other_room = _room(points=_square(other_scale))
    other = _scaled_qty(room=other_room, scale=other_scale)
    assert other.value == first.value == 25.0
    assert other.quantity_id != first.quantity_id
