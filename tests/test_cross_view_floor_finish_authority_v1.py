from __future__ import annotations

from dataclasses import replace

import fitz

import pb_cross_view_floor_finish_authority as floor_finish_authority
import pb_source_material_semantic_authority as material_semantic
from pb_cross_view_floor_finish_authority import (
    _quarantine_reused_floor_finish_occurrences,
    CROSS_VIEW_FLOOR_FINISH_CONFLICT,
    CROSS_VIEW_FLOOR_FINISH_RESOLVED,
    CrossViewFloorFinishProducer,
    enrich_live_canonical_floor_finishes,
)
from pb_cross_view_room_area_authority import CrossViewRoomAreaProducer
from pb_geometry_takeoff_model import MeasurementAuthorityType
import pb_same_view_room_area_authority as same_view_area_authority
from pb_same_view_room_area_authority import (
    SameViewRoomAreaProducer,
    SameViewRoomAreaRecord,
    SameViewRoomAreaResult,
)
from pb_live_canonical_floor_surface import (
    LiveCanonicalFloorSurfaceComposition,
    compose_live_canonical_floor_surfaces,
)
from pb_live_canonical_room_composition import (
    LIVE_CANONICAL_ROOM_RESOLVED,
    LiveCanonicalRoomComposition,
    LiveCanonicalRoomObject,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_visibility_authority import SourceVisibilityProducer
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportBoundarySource,
    ViewportSegmentationStatus,
    _stamp_segment_page_viewports_product,
)


def _payload(
    *,
    detail_codes: tuple[str, ...] = ("FT1",),
    schedule_lines: tuple[str, ...] = ("FT1 Porcelain floor tile",),
) -> bytes:
    doc = fitz.open()
    try:
        plan = doc.new_page(width=400.0, height=300.0)
        plan.insert_text((80.0, 60.0), "GROUND FLOOR PLAN", fontsize=10.0)

        detail = doc.new_page(width=400.0, height=300.0)

        # 3.6m horizontal figured dimension.
        detail.draw_line(
            (100.0, 80.0), (250.0, 80.0),
            color=(0, 0, 0), width=1.0,
        )
        detail.draw_line(
            (100.0, 68.0), (100.0, 92.0),
            color=(0, 0, 0), width=1.0,
        )
        detail.draw_line(
            (250.0, 68.0), (250.0, 92.0),
            color=(0, 0, 0), width=1.0,
        )
        detail.insert_text((164.0, 77.0), "3600", fontsize=9.0)

        # 2.4m vertical figured dimension sharing one real witness junction at
        # (250, 80) with the horizontal system.
        detail.draw_line(
            (280.0, 80.0), (280.0, 180.0),
            color=(0, 0, 0), width=1.0,
        )
        detail.draw_line(
            (250.0, 80.0), (292.0, 80.0),
            color=(0, 0, 0), width=1.0,
        )
        detail.draw_line(
            (268.0, 180.0), (292.0, 180.0),
            color=(0, 0, 0), width=1.0,
        )
        detail.insert_text(
            (277.0, 147.0), "2400", fontsize=9.0, rotate=90,
        )

        # Insert room/material semantics after figured dimensions so dimension
        # token classification cannot be biased by preceding room-label text.
        detail.insert_text((150.0, 150.0), "TEST ROOM", fontsize=10.0)

        # Material codes are source text inside the proven dimension box.
        for index, code in enumerate(detail_codes):
            detail.insert_text(
                (165.0, 165.0 + index * 12.0),
                code,
                fontsize=9.0,
            )

        schedule = doc.new_page(width=400.0, height=300.0)
        schedule.insert_text((40.0, 40.0), "FINISH SCHEDULE", fontsize=10.0)
        for index, line in enumerate(schedule_lines):
            schedule.insert_text(
                (40.0, 70.0 + index * 20.0),
                line,
                fontsize=10.0,
            )
        return doc.tobytes()
    finally:
        doc.close()


def _viewport(
    page_number: int,
    view_type: str,
    view_id: str,
) -> SegmentedViewport:
    return SegmentedViewport(
        view_id=view_id,
        page_number=page_number,
        view_type=view_type,
        label=view_type.upper(),
        title_bbox=(20.0, 10.0, 160.0, 25.0),
        bounding_box=(10.0, 10.0, 390.0, 290.0),
        status=ViewportSegmentationStatus.RESOLVED.value,
        boundary_source=ViewportBoundarySource.VECTOR_FRAME.value,
        confidence=1.0,
    )


def _patch_material_viewports(monkeypatch) -> None:
    types = {1: "floor_plan", 2: "floor_plan", 3: "schedule"}

    def segment(_page, *, page_number):
        return tuple(
            _stamp_segment_page_viewports_product(
                [
                    _viewport(
                        page_number,
                        types[page_number],
                        f"vp-{page_number}",
                    )
                ]
            )
        )

    monkeypatch.setattr(
        material_semantic,
        "segment_page_viewports",
        segment,
    )


def _source_room_area_and_floor(
    payload: bytes,
    *,
    page_ids: tuple[str, ...] | None = None,
):
    source = SourceVisibilityProducer(
        producer_method="cross-view-floor-finish-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="cross-view-floor-finish-doc",
        source_bytes=payload,
        source_locator="memory://cross-view-floor-finish.pdf",
        page_ids=page_ids,
    )
    room = LiveCanonicalRoomObject(
        canonical_room_id="physical-room-1",
        physical_room_id="physical-room-1",
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        viewport_id="plan-vp",
        decision_scope_id="wall-source:viewport:1:plan-vp",
        polygon_pdf_pts=(
            (100.0, 100.0),
            (250.0, 100.0),
            (250.0, 200.0),
            (100.0, 200.0),
        ),
        bounding_wall_ids=("w1", "w2", "w3", "w4"),
        canonical_bounding_wall_ids=(),
        wall_relationships_complete=False,
        area_page_pts2=15000.0,
        source_room_face_record_id="source-face-record-1",
        evidence_ids=("source-face-record-1",),
        geometry_complete=True,
        metric_geometry_complete=False,
        room_label="TEST ROOM",
        room_label_binding_record_id="label-binding:physical-room-1",
        room_label_evidence_ids=("label-evidence:physical-room-1",),
        room_label_reason_codes=("source_room_label_resolved",),
    )
    rooms = LiveCanonicalRoomComposition(
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=(LIVE_CANONICAL_ROOM_RESOLVED,),
        rooms=(room,),
        source_pages=(1,),
    )
    room_areas = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()
    assert room_areas.status is EvidenceResolutionStatus.CORROBORATED
    assert len(room_areas.records) == 1
    assert room_areas.records[0].area_evidence.normalized_value == 8.64

    base_floors = compose_live_canonical_floor_surfaces(rooms)
    floor = base_floors.floors[0]
    floor = replace(
        floor,
        evidence_ids=tuple(
            dict.fromkeys(
                (
                    *floor.evidence_ids,
                    room_areas.records[0].area_evidence.evidence_id,
                )
            )
        ),
        metric_area_m2=8.64,
        metric_area_quantity_id="room-area-quantity-1",
        metric_area_authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
    )
    floors = LiveCanonicalFloorSurfaceComposition(
        status=base_floors.status,
        reason_codes=base_floors.reason_codes,
        floors=(floor,),
        source_pages=base_floors.source_pages,
    )
    return source, room_areas, floors


def test_confirmed_floor_tile_occurrence_binds_same_canonical_floor(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(_payload())

    area_metadata = room_areas.records[0].area_evidence.metadata
    assert area_metadata["source_dimension_box_pdf_pts"]
    assert area_metadata["source_label_bbox_pdf_pts"]
    assert area_metadata["horizontal_endpoints_pt"]
    assert area_metadata["vertical_endpoints_pt"]

    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.reason_codes == (CROSS_VIEW_FLOOR_FINISH_RESOLVED,)
    assert result.unresolved_canonical_floor_ids == ()
    assert len(result.records) == 1

    record = result.records[0]
    assert record.finish_code == "FT1"
    assert record.semantic_finish == "tile"
    assert record.canonical_floor_id == floors.floors[0].canonical_floor_id
    assert record.occurrence_evidence_id
    assert record.support_snapshot_id

    quantity = record.quantity
    assert quantity.family == "floor_finish_area"
    assert quantity.value == 8.64
    assert quantity.unit == "m2"
    assert quantity.status == "firm"
    assert quantity.input_entity_ids == (floors.floors[0].canonical_floor_id,)
    assert quantity.metadata["finish_code"] == "FT1"
    assert quantity.metadata["semantic_finish"] == "tile"
    assert quantity.metadata["support_snapshot_id"] == record.support_snapshot_id
    assert len(quantity.metadata["figured_dimension_ids"]) == 2

    enriched = enrich_live_canonical_floor_finishes(floors, result)
    assert enriched.floors[0].canonical_floor_id == floors.floors[0].canonical_floor_id
    assert enriched.floors[0].finish_descriptor == "tile"
    assert enriched.floors[0].commercial_quantity_authority is False
    assert set(quantity.evidence_ids).issubset(enriched.floors[0].evidence_ids)


def test_floor_finish_can_use_same_revision_distinct_semantic_snapshot(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    payload = _payload()
    geometry_source, room_areas, floors = _source_room_area_and_floor(
        payload,
        page_ids=("1", "2"),
    )
    geometry_published = geometry_source.published_snapshot_for_revision(
        room_areas.records[0].area_evidence.metadata["room_revision_id"]
    )
    assert geometry_published is not None

    semantic_source = SourceVisibilityProducer(
        producer_method="cross-view-floor-finish-semantic-test",
        producer_version="1.0",
    )
    semantic_published = semantic_source.ingest_native_pdf_bytes(
        document_id=geometry_published.revision.document_id,
        source_bytes=payload,
        source_locator="memory://cross-view-floor-finish-semantic.pdf",
        page_ids=("2", "3"),
    )
    assert (
        semantic_published.revision.revision_id
        == geometry_published.revision.revision_id
    )
    assert (
        semantic_published.snapshot.snapshot_id
        != geometry_published.snapshot.snapshot_id
    )

    result = CrossViewFloorFinishProducer.from_source(
        source=semantic_source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    record = result.records[0]
    assert record.finish_code == "FT1"
    assert record.support_snapshot_id == semantic_published.snapshot.snapshot_id
    assert (
        record.quantity.metadata["support_snapshot_id"]
        == semantic_published.snapshot.snapshot_id
    )


def test_floor_finish_rejects_semantic_source_from_different_revision(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    payload = _payload()
    geometry_source, room_areas, floors = _source_room_area_and_floor(
        payload,
        page_ids=("1", "2"),
    )
    geometry_published = geometry_source.published_snapshot_for_revision(
        room_areas.records[0].area_evidence.metadata["room_revision_id"]
    )
    assert geometry_published is not None

    semantic_source = SourceVisibilityProducer(
        producer_method="cross-view-floor-finish-other-revision-test",
        producer_version="1.0",
    )
    semantic_source.ingest_native_pdf_bytes(
        document_id="different-floor-document",
        source_bytes=payload,
        source_locator="memory://different-floor-document.pdf",
        page_ids=("2", "3"),
    )

    result = CrossViewFloorFinishProducer.from_source(
        source=semantic_source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()


def test_raw_material_code_without_authenticated_schedule_cannot_bind(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(
        _payload(schedule_lines=("PT1 Dulux low sheen paint",))
    )
    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.records == ()
    assert result.unresolved_canonical_floor_ids == (
        floors.floors[0].canonical_floor_id,
    )


def test_confirmed_wall_tile_semantic_cannot_become_floor_finish(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(
        _payload(schedule_lines=("FT1 Porcelain wall tile",))
    )
    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.records == ()
    assert result.unresolved_canonical_floor_ids == (
        floors.floors[0].canonical_floor_id,
    )


def test_two_valid_floor_finish_occurrences_inside_same_floor_fail_closed(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(
        _payload(
            detail_codes=("FT1", "FT2"),
            schedule_lines=(
                "FT1 Porcelain floor tile",
                "FT2 Commercial vinyl flooring",
            ),
        )
    )
    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.reason_codes == (CROSS_VIEW_FLOOR_FINISH_CONFLICT,)
    assert result.records == ()
    assert result.unresolved_canonical_floor_ids == (
        floors.floors[0].canonical_floor_id,
    )


def _same_view_payload() -> bytes:
    doc = fitz.open()
    try:
        plan = doc.new_page(width=400.0, height=300.0)
        plan.insert_text((40.0, 30.0), "GROUND FLOOR PLAN", fontsize=10.0)

        plan.draw_line((100.0, 80.0), (250.0, 80.0), color=(0, 0, 0), width=1.0)
        plan.draw_line((100.0, 68.0), (100.0, 92.0), color=(0, 0, 0), width=1.0)
        plan.draw_line((250.0, 68.0), (250.0, 92.0), color=(0, 0, 0), width=1.0)
        plan.insert_text((164.0, 77.0), "3600", fontsize=9.0)

        plan.draw_line((280.0, 80.0), (280.0, 180.0), color=(0, 0, 0), width=1.0)
        plan.draw_line((250.0, 80.0), (292.0, 80.0), color=(0, 0, 0), width=1.0)
        plan.draw_line((268.0, 180.0), (292.0, 180.0), color=(0, 0, 0), width=1.0)
        plan.insert_text((277.0, 147.0), "2400", fontsize=9.0, rotate=90)

        plan.insert_text((150.0, 150.0), "TEST ROOM", fontsize=10.0)
        plan.insert_text((165.0, 165.0), "FT1", fontsize=9.0)

        schedule = doc.new_page(width=400.0, height=300.0)
        schedule.insert_text((40.0, 40.0), "FINISH SCHEDULE", fontsize=10.0)
        schedule.insert_text((40.0, 70.0), "FT1 Porcelain floor tile", fontsize=10.0)
        return doc.tobytes()
    finally:
        doc.close()


def test_same_view_figured_room_area_can_own_floor_finish_occurrence(
    monkeypatch,
) -> None:
    payload = _same_view_payload()

    def segment(_page, *, page_number):
        view_type = "floor_plan" if page_number == 1 else "schedule"
        return tuple(
            _stamp_segment_page_viewports_product(
                [_viewport(page_number, view_type, f"same-vp-{page_number}")]
            )
        )

    monkeypatch.setattr(material_semantic, "segment_page_viewports", segment)

    source = SourceVisibilityProducer(
        producer_method="same-view-floor-finish-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="same-view-floor-finish-doc",
        source_bytes=payload,
        source_locator="memory://same-view-floor-finish.pdf",
    )
    room = LiveCanonicalRoomObject(
        canonical_room_id="physical-room-same-1",
        physical_room_id="physical-room-same-1",
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        page_id="1",
        viewport_id="same-vp-1",
        decision_scope_id="wall-source:viewport:1:same-vp-1",
        polygon_pdf_pts=(
            (100.0, 100.0),
            (250.0, 100.0),
            (250.0, 200.0),
            (100.0, 200.0),
        ),
        bounding_wall_ids=("w1", "w2", "w3", "w4"),
        canonical_bounding_wall_ids=(),
        wall_relationships_complete=False,
        area_page_pts2=15000.0,
        source_room_face_record_id="source-face-same-1",
        evidence_ids=("source-face-same-1",),
        geometry_complete=True,
        metric_geometry_complete=False,
        room_label="TEST ROOM",
        room_label_binding_record_id="label-binding:same-1",
        room_label_evidence_ids=("label-evidence:same-1",),
        room_label_reason_codes=("source_room_label_resolved",),
    )
    rooms = LiveCanonicalRoomComposition(
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=(LIVE_CANONICAL_ROOM_RESOLVED,),
        rooms=(room,),
        source_pages=(1,),
    )
    room_areas = SameViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()
    assert room_areas.status is EvidenceResolutionStatus.CORROBORATED
    assert len(room_areas.records) == 1
    assert room_areas.records[0].area_evidence.normalized_value == 8.64
    assert (
        room_areas.records[0].area_evidence.method
        == "authenticated_same_view_figured_dimensions"
    )
    assert room_areas.records[0].area_evidence.metadata[
        "source_dimension_box_pdf_pts"
    ]

    base_floors = compose_live_canonical_floor_surfaces(rooms)
    floor = replace(
        base_floors.floors[0],
        evidence_ids=tuple(
            dict.fromkeys(
                (
                    *base_floors.floors[0].evidence_ids,
                    room_areas.records[0].area_evidence.evidence_id,
                )
            )
        ),
        metric_area_m2=8.64,
        metric_area_quantity_id="same-room-area-quantity-1",
        metric_area_authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
    )
    floors = LiveCanonicalFloorSurfaceComposition(
        status=base_floors.status,
        reason_codes=base_floors.reason_codes,
        floors=(floor,),
        source_pages=base_floors.source_pages,
    )

    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=None,
        same_view_room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.unresolved_canonical_floor_ids == ()
    assert len(result.records) == 1
    assert result.records[0].canonical_floor_id == floor.canonical_floor_id
    assert result.records[0].finish_code == "FT1"
    assert result.records[0].semantic_finish == "tile"
    assert result.records[0].quantity.value == 8.64
    assert result.records[0].quantity.authority == "documented_dimension"
    assert len(result.records[0].quantity.metadata["figured_dimension_ids"]) == 2


def test_cross_view_floor_finish_area_precedes_same_view_supplement(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, cross_view_areas, floors = _source_room_area_and_floor(_payload())
    cross_record = cross_view_areas.records[0]
    same_evidence = replace(
        cross_record.area_evidence,
        evidence_id="same-view-supplement-area-evidence",
        method="authenticated_same_view_figured_dimensions",
        normalized_value=9.0,
    )
    same_record = SameViewRoomAreaRecord(
        physical_room_id=cross_record.physical_room_id,
        source_room_face_record_id=cross_record.source_room_face_record_id,
        room_label=cross_record.room_label,
        source_dimension_page_id=cross_record.source_dimension_page_id,
        source_label_observation_ids=cross_record.source_label_observation_ids,
        source_label_receipt_ids=cross_record.source_label_receipt_ids,
        horizontal_dimension_id=cross_record.horizontal_dimension_id,
        vertical_dimension_id=cross_record.vertical_dimension_id,
        area_evidence=same_evidence,
        _seal=same_view_area_authority._RECORD_SEAL,
    )
    same_view_areas = SameViewRoomAreaResult(
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=("resolved",),
        records=(same_record,),
        unresolved_physical_room_ids=(),
    )

    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=cross_view_areas,
        same_view_room_areas=same_view_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.unresolved_canonical_floor_ids == ()
    assert len(result.records) == 1
    assert result.records[0].quantity.value == 8.64
    assert (
        result.records[0].quantity.metadata["source_dimension_page_id"]
        == cross_record.source_dimension_page_id
    )
    assert "same-view-supplement-area-evidence" not in (
        result.records[0].quantity.evidence_ids
    )


def _cross_view_floor_finish_payload(*, same_block: bool = True) -> bytes:
    doc = fitz.open(stream=_payload(detail_codes=()), filetype="pdf")
    try:
        finish = doc.new_page(pno=2, width=400.0, height=300.0)
        finish.insert_text(
            (40.0, 40.0),
            "FLOOR FINISHES PLAN",
            fontsize=10.0,
        )
        if same_block:
            finish.insert_textbox(
                fitz.Rect(140.0, 120.0, 240.0, 180.0),
                "TEST ROOM\nFT1",
                fontsize=10.0,
            )
        else:
            finish.insert_text((150.0, 140.0), "TEST ROOM", fontsize=10.0)
            finish.insert_text((165.0, 160.0), "FT1", fontsize=10.0)
        return doc.tobytes()
    finally:
        doc.close()


def _patch_cross_view_floor_finish_viewports(monkeypatch) -> None:
    types = {
        1: "floor_plan",
        2: "floor_plan",
        3: "floor_finish_plan",
        4: "schedule",
    }

    def segment(_page, *, page_number):
        return tuple(
            _stamp_segment_page_viewports_product(
                [
                    _viewport(
                        page_number,
                        types[page_number],
                        f"vp-{page_number}",
                    )
                ]
            )
        )

    monkeypatch.setattr(
        material_semantic,
        "segment_page_viewports",
        segment,
    )
    monkeypatch.setattr(
        floor_finish_authority,
        "segment_page_viewports",
        segment,
    )


def test_separate_floor_finish_plan_binds_by_exact_native_room_block(
    monkeypatch,
) -> None:
    _patch_cross_view_floor_finish_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(
        _cross_view_floor_finish_payload(same_block=True)
    )

    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    record = result.records[0]
    assert record.finish_code == "FT1"
    assert record.semantic_finish == "tile"
    assert record.quantity.value == 8.64
    assert record.quantity.metadata["source_dimension_page_id"] == "2"
    assert record.quantity.metadata["support_page_id"] == "3"
    assert record.quantity.metadata["support_viewport_id"] == "vp-3"
    assert (
        record.quantity.metadata["finish_binding_mode"]
        == "native_block_room_label"
    )


def test_separate_floor_finish_plan_nearby_code_in_different_block_abstains(
    monkeypatch,
) -> None:
    _patch_cross_view_floor_finish_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(
        _cross_view_floor_finish_payload(same_block=False)
    )

    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()

    assert result.records == ()
    assert result.quantities == ()


def test_floor_finish_requires_exact_area_evidence_on_canonical_floor(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(_payload())
    valid = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=floors,
    ).publish()
    assert len(valid.quantities) == 1

    # Same room, same numeric m² and same authenticated material code are
    # insufficient when this floor does not own that exact area evidence.
    original = floors.floors[0]
    unrelated = replace(
        floors,
        floors=(
            replace(
                original,
                evidence_ids=tuple(
                    value
                    for value in original.evidence_ids
                    if value != room_areas.records[0].area_evidence.evidence_id
                ),
            ),
        ),
    )
    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=room_areas,
        floors=unrelated,
    ).publish()
    assert result.records == ()
    assert result.quantities == ()
    assert result.unresolved_canonical_floor_ids == (
        original.canonical_floor_id,
    )


def test_unresolved_documented_area_evidence_cannot_publish_floor_finish(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(_payload())
    area_record = room_areas.records[0]
    compromised = replace(
        room_areas,
        records=(
            replace(
                area_record,
                area_evidence=replace(
                    area_record.area_evidence,
                    status=EvidenceResolutionStatus.CANDIDATE,
                ),
            ),
        ),
    )
    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=compromised,
        floors=floors,
    ).publish()
    assert result.records == ()
    assert result.quantities == ()
    assert result.unresolved_canonical_floor_ids == (
        floors.floors[0].canonical_floor_id,
    )


def test_shared_floor_finish_occurrence_quarantines_all_competing_floor_owners(
    monkeypatch,
) -> None:
    """One producer-owned source occurrence cannot quantify two room floors."""
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(_payload())
    result = CrossViewFloorFinishProducer.from_source(
        source=source, room_areas=room_areas, floors=floors,
    ).publish()
    assert len(result.records) == 1
    authentic = result.records[0]
    competing = replace(
        authentic,
        physical_room_id="physical-room-competing",
        canonical_floor_id="canonical-floor-competing",
        physical_floor_surface_id="physical-floor-competing",
    )
    # Unrelated independently authenticated occurrence survives quarantine.
    unrelated = replace(
        authentic,
        physical_room_id="physical-room-other",
        canonical_floor_id="canonical-floor-other",
        physical_floor_surface_id="physical-floor-other",
        occurrence_record_id="separate-producer-owned-occurrence",
    )
    retained, unresolved = _quarantine_reused_floor_finish_occurrences(
        (authentic, competing, unrelated)
    )
    assert retained == (unrelated,)
    assert unresolved == tuple(sorted((
        authentic.canonical_floor_id, competing.canonical_floor_id,
    )))
    assert retained[0].occurrence_record_id == "separate-producer-owned-occurrence"


def test_identical_floor_finish_source_ownership_is_not_a_conflict(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(_payload())
    result = CrossViewFloorFinishProducer.from_source(
        source=source, room_areas=room_areas, floors=floors,
    ).publish()
    authentic = result.records[0]
    retained, unresolved = _quarantine_reused_floor_finish_occurrences(
        (authentic,)
    )
    assert retained == (authentic,)
    assert unresolved == ()


def test_shared_floor_finish_conflict_result_is_input_order_independent(
    monkeypatch,
) -> None:
    _patch_material_viewports(monkeypatch)
    source, room_areas, floors = _source_room_area_and_floor(_payload())
    verified = CrossViewFloorFinishProducer.from_source(
        source=source, room_areas=room_areas, floors=floors,
    ).publish().records[0]
    competing = replace(
        verified,
        canonical_floor_id="floor-b",
        physical_floor_surface_id="floor-b",
        physical_room_id="room-b",
    )
    unrelated = replace(
        verified,
        canonical_floor_id="floor-c",
        physical_floor_surface_id="floor-c",
        physical_room_id="room-c",
        occurrence_record_id="different-authenticated-occurrence",
    )
    original, ids = _quarantine_reused_floor_finish_occurrences(
        (verified, competing, unrelated)
    )
    reversed_rows, reversed_ids = _quarantine_reused_floor_finish_occurrences(
        (unrelated, competing, verified)
    )
    assert ids == reversed_ids
    assert tuple(row.occurrence_record_id for row in original) == (
        "different-authenticated-occurrence",
    )
    assert tuple(row.occurrence_record_id for row in reversed_rows) == (
        "different-authenticated-occurrence",
    )


def test_gpt2_duplicate_documented_area_cannot_own_a_floor_finish(monkeypatch):
    from pb_cross_view_floor_finish_authority import (
        _unique_documented_area_owner_receipts,
    )
    _patch_material_viewports(monkeypatch)
    source, documented, floors = _source_room_area_and_floor(_payload())
    original = documented.records[0]
    conflicting = replace(
        original,
        area_evidence=replace(
            original.area_evidence, evidence_id="competing-source-documented-area",
            normalized_value=9.0,
        ),
    )
    selected, disputed = _unique_documented_area_owner_receipts(
        (), (original, conflicting)
    )
    assert selected == {}
    assert disputed == (original.source_room_face_record_id,)

    result = CrossViewFloorFinishProducer.from_source(
        source=source,
        room_areas=replace(documented, records=(original, conflicting)),
        floors=floors,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()
    assert result.quantities == ()
    assert result.unresolved_canonical_floor_ids == (
        floors.floors[0].canonical_floor_id,
    )


def test_gpt2_source_floor_finish_crossview_priority_survives_duplicate_supplements(
    monkeypatch,
):
    from pb_cross_view_floor_finish_authority import (
        _unique_documented_area_owner_receipts,
    )
    _patch_material_viewports(monkeypatch)
    source, documented, floors = _source_room_area_and_floor(_payload())
    strong = documented.records[0]
    other = replace(strong, area_evidence=replace(
        strong.area_evidence, evidence_id="supplement-one",
    ))
    another = replace(strong, area_evidence=replace(
        strong.area_evidence, evidence_id="supplement-two",
    ))
    selected, disputed = _unique_documented_area_owner_receipts(
        (other, another), (strong,),
    )
    assert selected == {strong.source_room_face_record_id: strong}
    assert disputed == ()
    # A duplicate cross-view producer receipt may not be silently replaced
    # by even a single independently positive same-view candidate.
    selected, disputed = _unique_documented_area_owner_receipts(
        (other,), (strong, strong),
    )
    assert selected == {}
    assert disputed == (strong.source_room_face_record_id,)


def test_gpt2_invalid_source_room_area_id_never_becomes_finish_owner():
    from types import SimpleNamespace
    from pb_cross_view_floor_finish_authority import (
        _unique_documented_area_owner_receipts,
    )
    authentic = SimpleNamespace(
        source_room_face_record_id="source-face-1",
        area_evidence=SimpleNamespace(evidence_id="independent-source-area-1"),
    )
    invalid = tuple(
        SimpleNamespace(
            source_room_face_record_id=value,
            area_evidence=SimpleNamespace(evidence_id="foreign-source-area"),
        )
        for value in (None, 17, "", " source-face-1", "source-face-1 ")
    )
    owners, disputed = _unique_documented_area_owner_receipts(
        invalid, (authentic,)
    )
    assert owners == {"source-face-1": authentic}
    assert disputed == ()


def test_gpt2_reused_source_area_evidence_cannot_quantify_two_room_finishes():
    from types import SimpleNamespace as Record
    from pb_cross_view_floor_finish_authority import (
        _unique_documented_area_owner_receipts,
    )
    def source_room(room_id, receipt):
        return Record(
            source_room_face_record_id=room_id,
            area_evidence=Record(evidence_id=receipt),
        )
    first=source_room("physical-source-room-one","same-figured-area-receipt")
    second=source_room("physical-source-room-two","same-figured-area-receipt")
    independent=source_room("physical-source-room-three","unique-source-area")
    kept, disputed=_unique_documented_area_owner_receipts(
        (), (first,second,independent)
    )
    assert kept=={"physical-source-room-three":independent}
    assert disputed==(
        "physical-source-room-one","physical-source-room-two"
    )
    assert "physical-source-room-one" not in kept
    assert "physical-source-room-two" not in kept


def test_gpt2_invalid_figured_area_receipt_quarantines_only_its_source_room():
    from types import SimpleNamespace as Record
    from pb_cross_view_floor_finish_authority import (
        _unique_documented_area_owner_receipts,
    )
    good=Record(
        source_room_face_record_id="room-valid",
        area_evidence=Record(evidence_id="real-source-figured-area"),
    )
    for invalid in (None, 79, "", "  ", " source-area-receipt"):
        untrusted=Record(
            source_room_face_record_id="room-unsupported",
            area_evidence=Record(evidence_id=invalid),
        )
        kept,disputed=_unique_documented_area_owner_receipts(
            (), (good,untrusted)
        )
        assert kept=={"room-valid":good}
        assert disputed==("room-unsupported",)
