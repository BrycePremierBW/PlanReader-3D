from __future__ import annotations

from dataclasses import replace

import fitz

import pb_cross_view_room_area_authority as cross_view
from pb_cross_view_room_area_authority import (
    CROSS_VIEW_ROOM_AREA_CONFLICT,
    CROSS_VIEW_ROOM_AREA_RESOLVED,
    CrossViewRoomAreaProducer,
    CrossViewRoomAreaRecord,
)
from pb_live_canonical_room_composition import (
    LIVE_CANONICAL_ROOM_RESOLVED,
    LiveCanonicalRoomComposition,
    LiveCanonicalRoomObject,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_portable_raster_ocr_authority import MockOCRBackend, OCRLine
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer


def _payload(
    *,
    duplicate_dimension_box: bool = False,
    duplicate_source_witness: bool = False,
) -> bytes:
    doc = fitz.open()
    try:
        plan = doc.new_page(width=400.0, height=300.0)
        plan.insert_text((80.0, 60.0), "GROUND FLOOR PLAN", fontsize=10.0)

        detail = doc.new_page(width=400.0, height=300.0)

        # 3.6m horizontal span: 150 source points.
        detail.draw_line((100.0, 80.0), (250.0, 80.0), color=(0, 0, 0), width=1.0)
        detail.draw_line((100.0, 68.0), (100.0, 92.0), color=(0, 0, 0), width=1.0)
        detail.draw_line((250.0, 68.0), (250.0, 92.0), color=(0, 0, 0), width=1.0)
        if duplicate_source_witness:
            # Multiple native primitives may paint the exact same physical
            # witness. The authority must preserve both source IDs without
            # inventing an ambiguity in the already-identical geometry.
            detail.draw_line(
                (250.0, 68.0),
                (250.0, 92.0),
                color=(0, 0, 0),
                width=1.0,
            )
        detail.insert_text((164.0, 77.0), "3600", fontsize=9.0)

        # 2.4m vertical span: 100 source points, same figured scale ratio.
        # Its top witness crosses the horizontal dimension's right witness,
        # proving one orthogonal source-dimension junction.
        detail.draw_line((280.0, 80.0), (280.0, 180.0), color=(0, 0, 0), width=1.0)
        detail.draw_line((250.0, 80.0), (292.0, 80.0), color=(0, 0, 0), width=1.0)
        detail.draw_line((268.0, 180.0), (292.0, 180.0), color=(0, 0, 0), width=1.0)
        detail.insert_text((277.0, 147.0), "2400", fontsize=9.0, rotate=90)

        if duplicate_dimension_box:
            # A second complete orthogonal box around the same trusted label
            # must create ambiguity rather than a confidence/ranking choice.
            detail.draw_line((90.0, 230.0), (260.0, 230.0), color=(0, 0, 0), width=1.0)
            detail.draw_line((90.0, 218.0), (90.0, 242.0), color=(0, 0, 0), width=1.0)
            detail.draw_line((260.0, 218.0), (260.0, 242.0), color=(0, 0, 0), width=1.0)
            detail.insert_text((164.0, 227.0), "4080", fontsize=9.0)

            # 2.88m vertical span: 120 source points, same figured ratio
            # as the second 4.08m horizontal span. Its bottom witness crosses
            # the second horizontal dimension's right witness.
            detail.draw_line((280.0, 120.0), (280.0, 240.0), color=(0, 0, 0), width=1.0)
            detail.draw_line((268.0, 120.0), (292.0, 120.0), color=(0, 0, 0), width=1.0)
            detail.draw_line((260.0, 240.0), (292.0, 240.0), color=(0, 0, 0), width=1.0)
            detail.insert_text((277.0, 197.0), "2880", fontsize=9.0, rotate=90)

        # Insert semantic label after figured dimensions so the dimension-token
        # classifier does not see a room-label context immediately before 3600.
        detail.insert_text((150.0, 150.0), "TEST ROOM", fontsize=10.0)

        return doc.tobytes()
    finally:
        doc.close()


def _source_and_room(
    *,
    duplicate_room_label: bool = False,
    duplicate_dimension_box: bool = False,
    duplicate_source_witness: bool = False,
    page_ids: tuple[str, ...] | None = None,
    room_page_id: str = "1",
):
    source = SourceVisibilityProducer(
        producer_method="cross-view-room-area-test",
        producer_version="1.0",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="cross-view-room-area-doc",
        source_bytes=_payload(
            duplicate_dimension_box=duplicate_dimension_box,
            duplicate_source_witness=duplicate_source_witness,
        ),
        source_locator="memory://cross-view-room-area.pdf",
        page_ids=page_ids,
    )

    def room(identity: str, face_record: str) -> LiveCanonicalRoomObject:
        return LiveCanonicalRoomObject(
            canonical_room_id=identity,
            physical_room_id=identity,
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            page_id=room_page_id,
            viewport_id="plan-vp",
            decision_scope_id="wall-source:viewport:1:plan-vp",
            polygon_pdf_pts=((100.0, 100.0), (250.0, 100.0), (250.0, 200.0), (100.0, 200.0)),
            bounding_wall_ids=("w1", "w2", "w3", "w4"),
            canonical_bounding_wall_ids=(),
            wall_relationships_complete=False,
            area_page_pts2=15000.0,
            source_room_face_record_id=face_record,
            evidence_ids=(face_record,),
            geometry_complete=True,
            metric_geometry_complete=False,
            room_label="TEST ROOM",
            room_label_binding_record_id=f"label-binding:{identity}",
            room_label_evidence_ids=(f"label-evidence:{identity}",),
            room_label_reason_codes=("source_room_label_resolved",),
        )

    rooms = [room("physical-room-1", "source-face-record-1")]
    if duplicate_room_label:
        rooms.append(room("physical-room-2", "source-face-record-2"))

    return source, LiveCanonicalRoomComposition(
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=(LIVE_CANONICAL_ROOM_RESOLVED,),
        rooms=tuple(rooms),
        source_pages=(int(room_page_id),),
    )


def _force_dimension_words_to_isolated_authority(
    monkeypatch,
    source: SourceVisibilityProducer,
    revision_id: str,
    *,
    readings_by_word: dict[str, tuple[str | None, str | None]] | None = None,
    integrity_reason_codes: tuple[str, ...] = (
        "text_glyph_mapping_unverified",
    ),
) -> None:
    published = source.published_snapshot_for_revision(revision_id)
    assert published is not None
    authority = source.text_integrity_authority()
    authority_type = type(authority)
    original_resolve = authority_type.resolve_text

    dimension_words: dict[str, str] = {}
    for observation_id in published.text_observation_ids:
        result = original_resolve(
            authority,
            ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=observation_id,
            ),
        )
        receipt = result.receipt
        if (
            receipt is not None
            and str(receipt.page_id) == "2"
            and str(receipt.raw_text).strip() in {"3600", "2400"}
        ):
            dimension_words[str(observation_id)] = str(receipt.raw_text).strip()
    assert set(dimension_words.values()) == {"3600", "2400"}

    def forced_resolve(self, selector):
        result = original_resolve(self, selector)
        if str(selector.observation_id) in dimension_words:
            forced_receipt = replace(
                result.receipt,
                trusted=False,
                reason_codes=integrity_reason_codes,
            )
            return replace(
                result,
                status=EvidenceResolutionStatus.ABSTAINED,
                trusted_text=None,
                receipt=forced_receipt,
                reason_codes=integrity_reason_codes,
            )
        return result

    monkeypatch.setattr(authority_type, "resolve_text", forced_resolve)

    scripted = readings_by_word or {}
    sequence: list[str | None] = []
    for value in dimension_words.values():
        sequence.extend(scripted.get(value, (value, value)))
    iterator = iter(sequence)

    def responder(image, dpi):
        try:
            value = next(iterator)
        except StopIteration:
            return ()
        if value is None:
            return ()
        return (
            OCRLine(
                text=value,
                confidence=1.0,
                bbox_px=(1.0, 1.0, 10.0, 10.0),
                bbox_pt=(1.0, 1.0, 10.0, 10.0),
            ),
        )

    backend = MockOCRBackend(responder=responder)
    monkeypatch.setattr(
        cross_view,
        "select_production_ocr_backend",
        lambda: (backend, "test_isolated_dimension_backend"),
    )


def test_cross_view_dimension_text_accepts_isolated_two_render_corroboration(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()
    _force_dimension_words_to_isolated_authority(
        monkeypatch,
        source,
        rooms.rooms[0].revision_id,
    )

    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    assert result.records[0].area_evidence.normalized_value == 8.64


def test_cross_view_dimension_isolated_corroboration_must_match_native_value(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()
    _force_dimension_words_to_isolated_authority(
        monkeypatch,
        source,
        rooms.rooms[0].revision_id,
        readings_by_word={"3600": ("3601", "3601")},
    )

    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.records == ()
    assert result.status in {
        EvidenceResolutionStatus.ABSTAINED,
        EvidenceResolutionStatus.CONFLICT,
    }


def test_cross_view_dimension_isolated_corroboration_requires_view_agreement(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()
    _force_dimension_words_to_isolated_authority(
        monkeypatch,
        source,
        rooms.rooms[0].revision_id,
        readings_by_word={"3600": ("3600", "3601")},
    )

    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.records == ()


def test_cross_view_dimension_isolated_corroboration_keeps_other_text_vetoes(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()
    _force_dimension_words_to_isolated_authority(
        monkeypatch,
        source,
        rooms.rooms[0].revision_id,
        integrity_reason_codes=(
            "text_glyph_mapping_unverified",
            "text_occluded_by_later_paint",
        ),
    )

    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.records == ()


def test_cross_view_exact_label_and_witnessed_orthogonal_dimensions_mint_room_owned_area():
    source, rooms = _source_and_room()
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.reason_codes == (CROSS_VIEW_ROOM_AREA_RESOLVED,)
    assert result.unresolved_physical_room_ids == ()
    assert result.unresolved_first_failure_by_physical_room_id == {}
    assert len(result.records) == 1

    record = result.records[0]
    assert record.physical_room_id == "physical-room-1"
    assert record.source_room_face_record_id == "source-face-record-1"
    assert record.source_dimension_page_id == "2"
    assert record.source_label_observation_ids
    assert record.source_label_receipt_ids
    assert record.horizontal_dimension_id
    assert record.vertical_dimension_id

    evidence = record.area_evidence
    assert evidence.document_id == rooms.rooms[0].document_id
    # The area proposition is owned by the physical room plan scope, not by
    # the independent dimension sheet that supports the derived value.
    assert evidence.page_id == "1"
    assert evidence.viewport_id == "plan-vp"
    assert evidence.kind == "explicit_room_area"
    assert evidence.method == "authenticated_cross_view_figured_dimensions"
    assert evidence.status is EvidenceResolutionStatus.CORROBORATED
    assert evidence.normalized_value == 8.64
    assert evidence.unit == "m2"
    assert evidence.metadata["source_dimension_page_id"] == "2"
    assert evidence.metadata["horizontal_value_mm"] == 3600
    assert evidence.metadata["vertical_value_mm"] == 2400
    assert set(evidence.metadata["figured_dimension_ids"]) == {
        record.horizontal_dimension_id,
        record.vertical_dimension_id,
    }
    assert evidence.metadata["horizontal_witness_observation_ids"]
    assert evidence.metadata["vertical_witness_observation_ids"]


def test_exact_coincident_source_witnesses_preserve_all_provenance_without_ambiguity():
    source, rooms = _source_and_room(duplicate_source_witness=True)
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    assert result.records[0].area_evidence.normalized_value == 8.64


def test_scoped_ingest_preserves_one_based_measurement_page_identity():
    source, rooms = _source_and_room(page_ids=("2",))
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    assert result.records[0].source_dimension_page_id == "2"
    assert result.records[0].area_evidence.metadata["source_dimension_page_id"] == "2"


def test_same_page_dimensions_cannot_mint_cross_view_room_area():
    source, rooms = _source_and_room(
        page_ids=("2",),
        room_page_id="2",
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.records == ()
    assert result.unresolved_physical_room_ids == ("physical-room-1",)
    assert result.status in {
        EvidenceResolutionStatus.ABSTAINED,
        EvidenceResolutionStatus.CONFLICT,
    }


def test_cross_view_mixed_or_stale_source_snapshot_fails_closed():
    source, rooms = _source_and_room(duplicate_room_label=True)
    mixed = replace(
        rooms, rooms=(
            rooms.rooms[0],
            replace(rooms.rooms[1], snapshot_id="foreign-snapshot"),
        ),
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=mixed,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()
    assert set(result.unresolved_physical_room_ids) == {
        "physical-room-1", "physical-room-2",
    }

    stale = replace(
        rooms, rooms=(replace(rooms.rooms[0], snapshot_id="foreign-snapshot"),),
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=stale,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()


def test_cross_view_duplicate_source_face_between_distinct_labels_fails_closed():
    source, rooms = _source_and_room(duplicate_room_label=True)
    distinct = replace(
        rooms,
        rooms=(
            rooms.rooms[0],
            replace(
                rooms.rooms[1],
                room_label="OTHER",
                source_room_face_record_id=rooms.rooms[0].source_room_face_record_id,
            ),
        ),
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=distinct,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()
    assert set(result.unresolved_physical_room_ids) == {
        "physical-room-1", "physical-room-2",
    }


def test_cross_view_duplicate_physical_room_across_distinct_labels_fails_closed():
    source, rooms = _source_and_room(duplicate_room_label=True)
    distinct = replace(
        rooms,
        rooms=(
            rooms.rooms[0],
            replace(
                rooms.rooms[1],
                room_label="OTHER",
                physical_room_id=rooms.rooms[0].physical_room_id,
            ),
        ),
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=distinct,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()
    assert result.unresolved_physical_room_ids == ("physical-room-1",)


def test_cross_view_eligibility_does_not_compare_room_polygons(monkeypatch):
    source, rooms = _source_and_room()
    monkeypatch.setattr(
        LiveCanonicalRoomObject, "__eq__",
        lambda self, other: (_ for _ in ()).throw(
            AssertionError("room geometry must not be compared for eligibility")
        ),
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=rooms,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    assert result.records[0].area_evidence.normalized_value == 8.64


def test_cross_view_first_gate_distinguishes_missing_support_from_dimensions(monkeypatch):
    source, rooms = _source_and_room(page_ids=("1",))
    no_support = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=rooms,
    ).publish()
    assert no_support.unresolved_first_failure_by_physical_room_id == {
        "physical-room-1": "cross_view_trusted_support_label_unavailable",
    }

    source, rooms = _source_and_room()
    monkeypatch.setattr(
        cross_view, "_trusted_native_dimensions_for_page",
        lambda *args, **kwargs: (),
    )
    no_dimensions = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=rooms,
    ).publish()
    assert no_dimensions.unresolved_first_failure_by_physical_room_id == {
        "physical-room-1": "cross_view_trusted_support_dimensions_unavailable",
    }


def test_cross_view_first_gate_reports_mixed_room_source_lineage():
    source, rooms = _source_and_room()
    invalid = replace(
        rooms,
        rooms=(replace(rooms.rooms[0], source_sha256="b" * 64),),
    )
    result = CrossViewRoomAreaProducer.from_source(
        source=source, rooms=invalid,
    ).publish()
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.records == ()
    assert result.unresolved_first_failure_by_physical_room_id == {
        "physical-room-1": "cross_view_source_lineage_conflict",
    }


def test_duplicate_canonical_room_label_fails_closed_before_cross_view_binding():
    source, rooms = _source_and_room(duplicate_room_label=True)
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.reason_codes == (CROSS_VIEW_ROOM_AREA_CONFLICT,)
    assert result.records == ()
    assert set(result.unresolved_physical_room_ids) == {
        "physical-room-1",
        "physical-room-2",
    }
    assert result.unresolved_first_failure_by_physical_room_id == {
        "physical-room-1": "cross_view_room_label_duplicate",
        "physical-room-2": "cross_view_room_label_duplicate",
    }


def test_multiple_orthogonal_dimension_pairs_around_same_label_fail_closed():
    source, rooms = _source_and_room(duplicate_dimension_box=True)
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status in {
        EvidenceResolutionStatus.CONFLICT,
        EvidenceResolutionStatus.ABSTAINED,
    }
    assert result.records == ()
    assert result.unresolved_physical_room_ids == ("physical-room-1",)


def test_record_constructor_rejects_caller_forgery():
    source, rooms = _source_and_room()
    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()
    assert result.records
    record = result.records[0]

    try:
        CrossViewRoomAreaRecord(
            physical_room_id=record.physical_room_id,
            source_room_face_record_id=record.source_room_face_record_id,
            room_label=record.room_label,
            source_dimension_page_id=record.source_dimension_page_id,
            source_label_observation_ids=record.source_label_observation_ids,
            source_label_receipt_ids=record.source_label_receipt_ids,
            horizontal_dimension_id=record.horizontal_dimension_id,
            vertical_dimension_id=record.vertical_dimension_id,
            area_evidence=record.area_evidence,
        )
    except TypeError:
        pass
    else:
        raise AssertionError("caller-forged cross-view room area record was accepted")

def test_cross_view_narrows_dimension_auth_to_authenticated_candidate_lines(monkeypatch):
    source, rooms = _source_and_room()
    observed = []
    original = cross_view._trusted_native_dimensions_for_page

    def wrapped(source_arg, *, revision_id, page_id, candidate_lines=()):
        if candidate_lines:
            observed.extend(candidate_lines)
        return original(
            source_arg,
            revision_id=revision_id,
            page_id=page_id,
            candidate_lines=candidate_lines,
        )

    monkeypatch.setattr(cross_view, "_trusted_native_dimensions_for_page", wrapped)
    result = CrossViewRoomAreaProducer.from_source(source=source, rooms=rooms).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert observed
    assert {line.text for line in observed} == {"TEST ROOM"}



def test_exact_label_line_can_fallback_to_two_render_line_corroboration(monkeypatch) -> None:
    from types import SimpleNamespace

    source, rooms = _source_and_room()
    revision_id = rooms.rooms[0].revision_id
    published = source.published_snapshot_for_revision(revision_id)
    assert published is not None

    authority = source.text_integrity_authority()
    authority_type = type(authority)
    original_resolve = authority_type.resolve_text
    label_observation_ids: set[str] = set()
    for observation_id in published.text_observation_ids:
        result = original_resolve(
            authority,
            ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=observation_id,
            ),
        )
        receipt = result.receipt
        if (
            receipt is not None
            and str(receipt.page_id) == "2"
            and str(receipt.raw_text).strip() in {"TEST", "ROOM"}
        ):
            label_observation_ids.add(str(observation_id))
    assert len(label_observation_ids) == 2

    def forced_resolve(self, selector):
        result = original_resolve(self, selector)
        if str(selector.observation_id) in label_observation_ids:
            reasons = ("text_glyph_mapping_unverified",)
            return replace(
                result,
                status=EvidenceResolutionStatus.ABSTAINED,
                trusted_text=None,
                receipt=replace(
                    result.receipt,
                    trusted=False,
                    reason_codes=reasons,
                ),
                reason_codes=reasons,
            )
        return result

    monkeypatch.setattr(authority_type, "resolve_text", forced_resolve)
    monkeypatch.setattr(
        cross_view.RasterTextCorroborationProducer,
        "publish",
        lambda self, selector: SimpleNamespace(
            status=EvidenceResolutionStatus.ABSTAINED,
            record=None,
            corroborated_text=None,
            reason_codes=("raster_text_no_reading",),
        ),
    )

    readings = iter(("TEST ROOM", "TEST ROOM"))

    def responder(image, dpi):
        value = next(readings)
        return (
            OCRLine(
                text=value,
                confidence=1.0,
                bbox_px=(1.0, 1.0, 20.0, 10.0),
                bbox_pt=(1.0, 1.0, 20.0, 10.0),
            ),
        )

    backend = MockOCRBackend(responder=responder)
    monkeypatch.setattr(
        cross_view,
        "select_production_ocr_backend",
        lambda: (backend, "test_line_backend"),
    )

    lines = cross_view._trusted_lines_for_page(
        source,
        revision_id=revision_id,
        page_id="2",
        candidate_labels=("TEST ROOM",),
    )

    assert len(lines) == 1
    assert lines[0].text == "TEST ROOM"
    assert len(lines[0].observation_ids) == 2


def test_repeated_exact_label_annotation_blocks_can_supply_orthogonal_dimensions(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()

    horizontal_line = cross_view._TrustedLine(
        page_id="2",
        text="TEST ROOM",
        bbox=(120.0, 70.0, 180.0, 78.0),
        observation_ids=("label-h",),
        receipt_ids=("receipt-h",),
        source_partition_id="partition-2",
        block_no=10,
        line_no=0,
    )
    vertical_line = cross_view._TrustedLine(
        page_id="2",
        text="TEST ROOM",
        bbox=(270.0, 110.0, 278.0, 170.0),
        observation_ids=("label-v",),
        receipt_ids=("receipt-v",),
        source_partition_id="partition-2",
        block_no=20,
        line_no=0,
    )
    horizontal = cross_view._TrustedBoundDimension(
        dimension_id="h-3600",
        text_observation_id="text-h",
        text_receipt_id="text-receipt-h",
        text_source_partition_id="partition-2",
        text_block_no=10,
        text_line_no=1,
        text_word_no=0,
        value_mm=3600.0,
        orientation="horizontal",
        endpoints_pt=((100.0, 80.0), (250.0, 80.0)),
        dimension_line_observation_ids=("h-line",),
        witness_observation_ids=("h-w1", "h-w2"),
        witness_geometries=(
            (100.0, 68.0, 100.0, 92.0),
            (250.0, 68.0, 250.0, 92.0),
        ),
    )
    vertical = cross_view._TrustedBoundDimension(
        dimension_id="v-2400",
        text_observation_id="text-v",
        text_receipt_id="text-receipt-v",
        text_source_partition_id="partition-2",
        text_block_no=20,
        text_line_no=1,
        text_word_no=0,
        value_mm=2400.0,
        orientation="vertical",
        endpoints_pt=((280.0, 100.0), (280.0, 200.0)),
        dimension_line_observation_ids=("v-line",),
        witness_observation_ids=("v-w1", "v-w2"),
        witness_geometries=(
            (268.0, 100.0, 292.0, 100.0),
            (268.0, 200.0, 292.0, 200.0),
        ),
    )

    monkeypatch.setattr(
        cross_view,
        "_trusted_lines_for_page",
        lambda source_arg, *, revision_id, page_id, candidate_labels,
        allow_compound_annotations=False: (
            horizontal_line,
            vertical_line,
        ) if str(page_id) == "2" else (),
    )
    monkeypatch.setattr(
        cross_view,
        "_trusted_native_dimensions_for_page",
        lambda source_arg, *, revision_id, page_id, candidate_lines=(): (
            horizontal,
            vertical,
        ) if str(page_id) == "2" else (),
    )

    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    record = result.records[0]
    assert record.area_evidence.normalized_value == 8.64
    assert record.area_evidence.metadata["source_label_support_mode"] == (
        "repeated_label_annotation_blocks"
    )
    assert len(record.source_label_receipt_ids) == 2


def test_repeated_label_annotation_blocks_remain_fail_closed_when_pair_is_not_unique(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()

    line_h1 = cross_view._TrustedLine(
        page_id="2", text="TEST ROOM", bbox=(100, 70, 160, 78),
        observation_ids=("lh1",), receipt_ids=("rh1",),
        source_partition_id="partition-2", block_no=10, line_no=0,
    )
    line_h2 = cross_view._TrustedLine(
        page_id="2", text="TEST ROOM", bbox=(100, 220, 160, 228),
        observation_ids=("lh2",), receipt_ids=("rh2",),
        source_partition_id="partition-2", block_no=30, line_no=0,
    )
    line_v = cross_view._TrustedLine(
        page_id="2", text="TEST ROOM", bbox=(270, 110, 278, 170),
        observation_ids=("lv",), receipt_ids=("rv",),
        source_partition_id="partition-2", block_no=20, line_no=0,
    )
    h1 = cross_view._TrustedBoundDimension(
        "h1", "th1", "trh1", "partition-2", 10, 1, 0, 3600.0,
        "horizontal", ((100, 80), (250, 80)), ("hl1",),
        ("hw1", "hw2"), ((100, 68, 100, 92), (250, 68, 250, 92)),
    )
    h2 = cross_view._TrustedBoundDimension(
        "h2", "th2", "trh2", "partition-2", 30, 1, 0, 4080.0,
        "horizontal", ((90, 230), (260, 230)), ("hl2",),
        ("hw3", "hw4"), ((90, 218, 90, 242), (260, 218, 260, 242)),
    )
    v = cross_view._TrustedBoundDimension(
        "v", "tv", "trv", "partition-2", 20, 1, 0, 2400.0,
        "vertical", ((280, 100), (280, 200)), ("vl",),
        ("vw1", "vw2"), ((268, 100, 292, 100), (268, 200, 292, 200)),
    )
    monkeypatch.setattr(
        cross_view,
        "_trusted_lines_for_page",
        lambda *args, **kwargs: (line_h1, line_h2, line_v),
    )
    monkeypatch.setattr(
        cross_view,
        "_trusted_native_dimensions_for_page",
        lambda *args, **kwargs: (h1, h2, v),
    )

    result = CrossViewRoomAreaProducer.from_source(source=source, rooms=rooms).publish()

    assert result.records == ()
    assert result.status is EvidenceResolutionStatus.CONFLICT


def test_exact_and_compound_label_annotations_can_supply_unique_orthogonal_pair(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()

    exact_line = cross_view._TrustedLine(
        page_id="2",
        text="TEST ROOM",
        bbox=(120.0, 70.0, 180.0, 78.0),
        observation_ids=("label-exact",),
        receipt_ids=("receipt-exact",),
        source_partition_id="partition-2",
        block_no=10,
        line_no=0,
        label_members=("test room",),
    )
    compound_line = cross_view._TrustedLine(
        page_id="2",
        text="TEST ROOM / STORE",
        bbox=(270.0, 110.0, 278.0, 170.0),
        observation_ids=("label-group",),
        receipt_ids=("receipt-group",),
        source_partition_id="partition-2",
        block_no=20,
        line_no=0,
        label_members=("test room", "store"),
    )
    horizontal = cross_view._TrustedBoundDimension(
        dimension_id="h-3600",
        text_observation_id="text-h",
        text_receipt_id="text-receipt-h",
        text_source_partition_id="partition-2",
        text_block_no=11,
        text_line_no=0,
        text_word_no=0,
        value_mm=3600.0,
        orientation="horizontal",
        endpoints_pt=((100.0, 80.0), (250.0, 80.0)),
        dimension_line_observation_ids=("h-line",),
        witness_observation_ids=("h-w1", "h-w2"),
        witness_geometries=(
            (100.0, 68.0, 100.0, 92.0),
            (250.0, 68.0, 250.0, 92.0),
        ),
        text_bbox=(130.0, 82.0, 160.0, 90.0),
    )
    vertical = cross_view._TrustedBoundDimension(
        dimension_id="v-2400",
        text_observation_id="text-v",
        text_receipt_id="text-receipt-v",
        text_source_partition_id="partition-2",
        text_block_no=20,
        text_line_no=1,
        text_word_no=0,
        value_mm=2400.0,
        orientation="vertical",
        endpoints_pt=((280.0, 100.0), (280.0, 200.0)),
        dimension_line_observation_ids=("v-line",),
        witness_observation_ids=("v-w1", "v-w2"),
        witness_geometries=(
            (268.0, 100.0, 292.0, 100.0),
            (268.0, 200.0, 292.0, 200.0),
        ),
        text_bbox=(280.0, 130.0, 290.0, 160.0),
    )

    def trusted_lines(
        source_arg,
        *,
        revision_id,
        page_id,
        candidate_labels,
        allow_compound_annotations=False,
    ):
        if str(page_id) != "2":
            return ()
        if allow_compound_annotations:
            return (exact_line, compound_line)
        return (exact_line,)

    monkeypatch.setattr(cross_view, "_trusted_lines_for_page", trusted_lines)
    monkeypatch.setattr(
        cross_view,
        "_trusted_native_dimensions_for_page",
        lambda source_arg, *, revision_id, page_id, candidate_lines=(): (
            horizontal,
            vertical,
        ) if str(page_id) == "2" else (),
    )

    result = CrossViewRoomAreaProducer.from_source(
        source=source,
        rooms=rooms,
    ).publish()

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert len(result.records) == 1
    record = result.records[0]
    assert record.area_evidence.normalized_value == 8.64
    assert record.horizontal_dimension_id == "h-3600"
    assert record.vertical_dimension_id == "v-2400"
    assert record.area_evidence.metadata["source_label_support_mode"] == (
        "repeated_label_annotation_blocks"
    )


def test_compound_label_alone_cannot_mint_room_area(
    monkeypatch,
) -> None:
    source, rooms = _source_and_room()
    compound_line = cross_view._TrustedLine(
        page_id="2",
        text="TEST ROOM / STORE",
        bbox=(100.0, 70.0, 180.0, 78.0),
        observation_ids=("label-group",),
        receipt_ids=("receipt-group",),
        source_partition_id="partition-2",
        block_no=10,
        line_no=0,
        label_members=("test room", "store"),
    )
    horizontal = cross_view._TrustedBoundDimension(
        "h", "th", "trh", "partition-2", 10, 1, 0, 3600.0,
        "horizontal", ((100, 80), (250, 80)), ("hl",),
        ("hw1", "hw2"), ((100, 68, 100, 92), (250, 68, 250, 92)),
    )
    vertical = cross_view._TrustedBoundDimension(
        "v", "tv", "trv", "partition-2", 10, 1, 0, 2400.0,
        "vertical", ((280, 100), (280, 200)), ("vl",),
        ("vw1", "vw2"), ((268, 100, 292, 100), (268, 200, 292, 200)),
    )

    monkeypatch.setattr(
        cross_view,
        "_trusted_lines_for_page",
        lambda source_arg, *, revision_id, page_id, candidate_labels,
        allow_compound_annotations=False: (
            (compound_line,) if allow_compound_annotations else ()
        ),
    )
    monkeypatch.setattr(
        cross_view,
        "_trusted_native_dimensions_for_page",
        lambda *args, **kwargs: (horizontal, vertical),
    )

    result = CrossViewRoomAreaProducer.from_source(source=source, rooms=rooms).publish()

    assert result.records == ()


def _source_area_owner_record(room_id: str, page: str, horizontal: str, vertical: str):
    from pb_migration_contracts import EvidenceAtom

    return CrossViewRoomAreaRecord(
        physical_room_id=room_id,
        source_room_face_record_id="face-"+room_id,
        room_label=room_id,
        source_dimension_page_id=page,
        source_label_observation_ids=("source-label-"+room_id,),
        source_label_receipt_ids=("source-receipt-"+room_id,),
        horizontal_dimension_id=horizontal,
        vertical_dimension_id=vertical,
        area_evidence=EvidenceAtom(
            evidence_id="area-"+room_id,
            document_id="source-test-doc",
            page_id="1",
            kind="explicit_room_area",
            method="authenticated_cross_view_figured_dimensions",
            normalized_value=8.64,
            unit="m2",
            status=EvidenceResolutionStatus.CORROBORATED,
        ),
        _seal=cross_view._RECORD_SEAL,
    )


def test_cross_view_horizontal_dimension_source_is_not_two_room_areas() -> None:
    from pb_cross_view_room_area_authority import (
        _quarantine_reused_cross_view_dimensions,
    )

    one=_source_area_owner_record("room-1","9","shared-h","v1")
    two=_source_area_owner_record("room-2","9","shared-h","v2")
    unrelated=_source_area_owner_record("room-3","9","own-h","v3")
    records, conflict=_quarantine_reused_cross_view_dimensions(
        (one,two,unrelated))
    assert records==[unrelated]
    assert conflict=={"room-1","room-2"}
    reversed_records, reversed_conflict=_quarantine_reused_cross_view_dimensions(
        (unrelated,two,one))
    assert reversed_records==[unrelated]
    assert reversed_conflict==conflict


def test_cross_view_vertical_dimension_source_is_not_two_room_areas() -> None:
    from pb_cross_view_room_area_authority import (
        _quarantine_reused_cross_view_dimensions,
    )

    one=_source_area_owner_record("room-1","9","h1","shared-v")
    two=_source_area_owner_record("room-2","9","h2","shared-v")
    records, conflict=_quarantine_reused_cross_view_dimensions((one,two))
    assert records==[]
    assert conflict=={"room-1","room-2"}


def test_cross_view_dimension_identity_scoped_to_actual_support_page() -> None:
    from pb_cross_view_room_area_authority import (
        _quarantine_reused_cross_view_dimensions,
    )

    one=_source_area_owner_record("room-1","9","common-h","common-v")
    two=_source_area_owner_record("room-2","11","common-h","common-v")
    records, conflict=_quarantine_reused_cross_view_dimensions((one,two))
    assert records==[one,two]
    assert conflict==set()


def test_cross_view_separate_source_dimensions_keep_both_metric_rooms() -> None:
    from pb_cross_view_room_area_authority import (
        _quarantine_reused_cross_view_dimensions,
    )

    one=_source_area_owner_record("room-1","9","h1","v1")
    two=_source_area_owner_record("room-2","9","h2","v2")
    records, conflict=_quarantine_reused_cross_view_dimensions((one,two))
    assert records==[one,two]
    assert conflict==set()


def test_genuine_finite_source_witness_junction_survives_guard() -> None:
    intersect = cross_view._source_segments_intersect
    assert intersect((100.0, 70.0, 100.0, 90.0),
                     (90.0, 80.0, 110.0, 80.0))
    assert intersect((100.0, 80.0, 90.0, 80.0),
                     (90.0, 80.0, 90.0, 90.0))
    assert not intersect((100.0, 70.0, 100.0, 90.0),
                         (101.0, 80.0, 110.0, 80.0))


def test_source_witness_point_segment_cannot_fake_physical_junction() -> None:
    intersect = cross_view._source_segments_intersect
    genuine = (90.0, 80.0, 110.0, 80.0)
    for zero_length in (
        (100.0, 80.0, 100.0, 80.0),
        (90.0, 80.0, 90.0, 80.0),
    ):
        assert not intersect(zero_length, genuine)
        assert not intersect(genuine, zero_length)


def test_nonfinite_or_malformed_source_witness_is_not_a_junction() -> None:
    intersect = cross_view._source_segments_intersect
    genuine = (90.0, 80.0, 110.0, 80.0)
    malformed = (
        (100.0, float("nan"), 100.0, 90.0),
        (100.0, float("inf"), 100.0, 90.0),
        (100.0, 70.0, 100.0, float("-inf")),
        (-1e308, 80.0, 1e308, 80.0),
        (100.0, 80.0, True, 90.0),
        (100.0, 80.0, "100", 90.0),
        (100.0, 80.0, 100.0),
    )
    for invalid in malformed:
        assert not intersect(invalid, genuine)
        assert not intersect(genuine, invalid)
