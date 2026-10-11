from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from pb_migration_contracts import EvidenceResolutionStatus
from pb_physical_wall_candidate_authority import PhysicalWallCandidateProducer
from pb_portable_raster_ocr_authority import MockOCRBackend, OCRLine
from pb_source_room_face_authority import build_source_room_face_authority
from pb_source_room_label_authority import (
    SOURCE_ROOM_LABEL_CONFLICT,
    SOURCE_ROOM_LABEL_REQUIRED_WORD_UNRESOLVED,
    SourceRoomLabelProducer,
    SourceRoomLabelWordEvidence,
    _Word,
    _line_groups,
    _normalized_room_line,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer


def _word(
    text: str,
    word_no: int,
    *,
    block: int = 1,
    line: int = 2,
) -> _Word:
    return _Word(
        observation_id=f"obs-{word_no}-{text}",
        receipt_id=f"receipt-{word_no}-{text}",
        source_partition_id="page:1",
        raw_text=text,
        geometry=(
            10.0 + word_no * 12.0,
            10.0,
            20.0 + word_no * 12.0,
            20.0,
        ),
        block_no=block,
        line_no=line,
        word_no=word_no,
    )


def test_whole_line_semantics_accept_room_labels_not_embedded_equipment_notes() -> None:
    assert _normalized_room_line("FOOD PREP") == "FOOD PREP"
    assert _normalized_room_line("COLD ROOM") == "COLD ROOM"
    assert _normalized_room_line("FREEZER") == "FREEZER"
    assert _normalized_room_line("PWD") == "PWD"
    assert _normalized_room_line("M-AMB") == "M-AMB"
    assert _normalized_room_line("F-AMB") == "F-AMB"
    assert _normalized_room_line("ENS") == "ENS"
    assert _normalized_room_line("WIR") == "WIR"
    assert _normalized_room_line("GARAGE") == "GARAGE"
    assert _normalized_room_line("ENS NOTE") is None
    assert _normalized_room_line("WIR NOTE") is None
    assert _normalized_room_line("GARAGE NOTE") is None
    assert _normalized_room_line("POS COUNTER") == "POS COUNTER"
    assert _normalized_room_line("WC & SHOWER") == "WC & SHOWER"
    assert (
        _normalized_room_line(
            "ICE CREAM FREEZER SUPPLIED INSTALLED BY LESSEE"
        )
        is None
    )
    assert _normalized_room_line("LAUNDRY TUB") is None
    assert _normalized_room_line("OFFICE 1") is None
    assert _normalized_room_line("M-AMB FIXTURE NOTE") is None
    assert _normalized_room_line("POS COUNTER 1") is None


def test_line_grouping_uses_exact_source_block_line_and_word_order() -> None:
    grouped = _line_groups(
        (
            _word("ROOM", 1),
            _word("COLD", 0),
            _word("OFFICE", 0, block=9, line=4),
        )
    )
    assert [
        [word.raw_text for word in group]
        for group in grouped
    ] == [
        ["COLD", "ROOM"],
        ["OFFICE"],
    ]


def test_duplicate_word_order_abstains_from_line_reconstruction() -> None:
    assert _line_groups((_word("COLD", 0), _word("ROOM", 0))) == ()


def _write_two_room_pdf(
    path: Path,
    *,
    left_lines=("FOOD PREP",),
    right_lines=("COLD ROOM",),
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300.0, height=200.0)
    for first, second in (
        ((50.0, 50.0), (250.0, 50.0)),
        ((250.0, 50.0), (250.0, 150.0)),
        ((250.0, 150.0), (50.0, 150.0)),
        ((50.0, 150.0), (50.0, 50.0)),
        ((150.0, 50.0), (150.0, 150.0)),
    ):
        page.draw_line(
            fitz.Point(*first),
            fitz.Point(*second),
            color=(0, 0, 0),
            width=1.0,
        )
    y = 90.0
    for text in left_lines:
        page.insert_text((75.0, y), text, fontsize=9.0)
        y += 18.0
    y = 90.0
    for text in right_lines:
        page.insert_text((175.0, y), text, fontsize=9.0)
        y += 18.0
    doc.save(path)
    doc.close()


def _setup(path: Path):
    source = SourceVisibilityProducer(
        producer_method="source-room-label-test",
        producer_version="1.0",
    )
    source.ingest_native_pdf_bytes(
        document_id=f"test:{path.name}",
        source_bytes=path.read_bytes(),
        source_locator=str(path),
        page_ids=("1",),
    )
    walls = PhysicalWallCandidateProducer.from_source_visibility_producer(
        source,
        page_ids=("1",),
    ).authority()
    room_faces = build_source_room_face_authority(walls)
    return source, room_faces


def _fake_authorized(
    _self,
    _published,
    word: _Word,
):
    return SourceRoomLabelWordEvidence(
        observation_id=word.observation_id,
        receipt_id=word.receipt_id,
        trusted_text=word.raw_text,
        authority_kind="test_authenticated_text",
        authority_record_id=f"authority:{word.observation_id}",
        geometry=word.geometry,
        word_no=word.word_no,
    )


def _records(producer: SourceRoomLabelProducer):
    return [
        record
        for result in producer.published_results()
        for record in result.records
    ]


def test_end_to_end_binds_complete_source_lines_to_exact_room_faces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "two-room-labels.pdf"
    _write_two_room_pdf(path)
    source, room_faces = _setup(path)
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        _fake_authorized,
    )

    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        MockOCRBackend(),
        page_ids=("1",),
    )
    records = _records(producer)

    assert {record.label for record in records} == {
        "FOOD PREP",
        "COLD ROOM",
    }
    assert len({record.face_id for record in records}) == 2
    assert all(
        record.status is EvidenceResolutionStatus.CORROBORATED
        for record in records
    )
    assert all(record.observation_ids for record in records)


def test_unresolved_required_word_blocks_only_that_room_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "one-word-unresolved.pdf"
    _write_two_room_pdf(path)
    source, room_faces = _setup(path)

    def authorize(self, published, word):
        if word.raw_text == "PREP":
            return None
        return _fake_authorized(self, published, word)

    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        authorize,
    )
    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        MockOCRBackend(),
        page_ids=("1",),
    )
    records = _records(producer)
    assert {record.label for record in records} == {"COLD ROOM"}
    assert any(
        SOURCE_ROOM_LABEL_REQUIRED_WORD_UNRESOLVED
        in result.reason_codes
        for result in producer.published_results()
    )


def test_two_distinct_authenticated_label_lines_in_one_face_conflict_not_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "conflict.pdf"
    _write_two_room_pdf(
        path,
        left_lines=("OFFICE", "STUDY"),
        right_lines=("COLD ROOM",),
    )
    source, room_faces = _setup(path)
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        _fake_authorized,
    )

    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        MockOCRBackend(),
        page_ids=("1",),
    )
    records = _records(producer)
    assert {record.label for record in records} == {"COLD ROOM"}
    assert any(
        SOURCE_ROOM_LABEL_CONFLICT in result.reason_codes
        for result in producer.published_results()
    )


def test_room_looking_token_inside_long_note_is_never_cherry_picked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "note.pdf"
    _write_two_room_pdf(
        path,
        left_lines=(
            "ICE CREAM FREEZER SUPPLIED INSTALLED BY LESSEE",
        ),
        right_lines=("COLD ROOM",),
    )
    source, room_faces = _setup(path)
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        _fake_authorized,
    )

    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        MockOCRBackend(),
        page_ids=("1",),
    )
    assert {
        record.label for record in _records(producer)
    } == {"COLD ROOM"}


def _line_backend(readings):
    values = iter(readings)

    def responder(_image, _dpi):
        try:
            value = next(values)
        except StopIteration:
            return ()
        if value is None:
            return ()
        return (
            OCRLine(
                text=value,
                confidence=1.0,
                bbox_px=(1.0, 1.0, 30.0, 10.0),
                bbox_pt=(1.0, 1.0, 30.0, 10.0),
            ),
        )

    return MockOCRBackend(responder=responder)


def test_whole_line_two_render_fallback_can_authenticate_closed_room(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "line-fallback.pdf"
    _write_two_room_pdf(
        path,
        left_lines=("SALES",),
        right_lines=(),
    )
    source, room_faces = _setup(path)

    # Force the integration down the whole-line path. The fallback independently
    # revalidates native source ownership/text integrity before it may use OCR.
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        lambda *_args, **_kwargs: None,
    )
    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        _line_backend(("SALES", "SALES")),
        page_ids=("1",),
    )

    records = _records(producer)
    assert {record.label for record in records} == {"SALES"}
    assert records[0].word_evidence[0].authority_kind == (
        "raster_text_line_corroboration"
    )


def test_whole_line_fallback_requires_both_renders_to_match_exact_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "line-mismatch.pdf"
    _write_two_room_pdf(
        path,
        left_lines=("SALES",),
        right_lines=(),
    )
    source, room_faces = _setup(path)
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        lambda *_args, **_kwargs: None,
    )
    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        _line_backend(("SALES", "SAILS")),
        page_ids=("1",),
    )

    assert _records(producer) == []
    assert any(
        SOURCE_ROOM_LABEL_REQUIRED_WORD_UNRESOLVED
        in result.reason_codes
        for result in producer.published_results()
    )


def test_whole_line_fallback_does_not_bypass_text_trace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "trace-unavailable.pdf"
    _write_two_room_pdf(
        path,
        left_lines=("SALES",),
        right_lines=(),
    )
    source, room_faces = _setup(path)
    authority = source.text_integrity_authority()
    authority_type = type(authority)
    original_resolve = authority_type.resolve_text

    def forced_trace_failure(self, selector):
        result = original_resolve(self, selector)
        receipt = result.receipt
        if (
            receipt is not None
            and str(receipt.raw_text or "").strip() == "SALES"
        ):
            reasons = ("text_trace_unavailable",)
            return replace(
                result,
                status=EvidenceResolutionStatus.ABSTAINED,
                trusted_text=None,
                receipt=replace(
                    receipt,
                    trusted=False,
                    reason_codes=reasons,
                ),
                reason_codes=reasons,
            )
        return result

    monkeypatch.setattr(authority_type, "resolve_text", forced_trace_failure)
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        lambda *_args, **_kwargs: None,
    )
    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        _line_backend(("SALES", "SALES")),
        page_ids=("1",),
    )

    assert _records(producer) == []


def test_authenticated_whole_line_still_requires_all_words_in_same_room_face(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "split-face-line.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300.0, height=200.0)
    for first, second in (
        ((50.0, 50.0), (250.0, 50.0)),
        ((250.0, 50.0), (250.0, 150.0)),
        ((250.0, 150.0), (50.0, 150.0)),
        ((50.0, 150.0), (50.0, 50.0)),
        ((150.0, 50.0), (150.0, 150.0)),
    ):
        page.draw_line(
            fitz.Point(*first),
            fitz.Point(*second),
            color=(0, 0, 0),
            width=1.0,
        )
    # The whole source line is a valid room semantic, but the physical divider
    # deliberately splits its two word centres across two source-room faces.
    page.insert_text((130.0, 95.0), "FOOD SERVICE", fontsize=9.0)
    doc.save(path)
    doc.close()

    source, room_faces = _setup(path)
    monkeypatch.setattr(
        SourceRoomLabelProducer,
        "_authorize_word",
        lambda *_args, **_kwargs: None,
    )
    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source,
        room_faces,
        _line_backend(("FOOD SERVICE", "FOOD SERVICE")),
        page_ids=("1",),
    )

    assert _records(producer) == []


def test_source_room_bbox_prefilter_never_rejects_polygon_inside_or_boundary():
    """Conservative page-space bounds only reduce polygon checks, not authority."""
    from pb_source_room_label_authority import (
        _point_in_polygon,
        _point_may_belong_to_face_bbox,
        _source_face_polygon_bbox,
    )

    polygons = (
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        ((0.0, 0.0), (8.0, 0.0), (8.0, 2.0), (2.0, 2.0),
         (2.0, 8.0), (0.0, 8.0)),
    )
    points = (
        (0.0, 0.0), (5.0, 5.0), (10.0, 10.0),
        (0.0 - 5e-7, 5.0), (10.0 + 5e-7, 5.0),
        (1.0, 1.0), (3.0, 3.0), (-2.0, -2.0),
        (12.0, 12.0), (2.0, 2.0),
    )
    for polygon in polygons:
        bbox = _source_face_polygon_bbox(polygon)
        assert bbox is not None
        for point in points:
            with_prefilter = (
                _point_may_belong_to_face_bbox(point, bbox)
                and _point_in_polygon(point, polygon)
            )
            assert with_prefilter == _point_in_polygon(point, polygon)


def test_source_room_bbox_prefilter_abstains_from_pruning_invalid_geometry():
    from pb_source_room_label_authority import (
        _source_face_polygon_bbox,
        _point_may_belong_to_face_bbox,
    )

    assert _source_face_polygon_bbox(()) is None
    assert _source_face_polygon_bbox(((0.0, 0.0), (float("nan"), 0.0),
                                      (0.0, 10.0))) is None
    assert _source_face_polygon_bbox(((0.0, 0.0), (float("inf"), 0.0),
                                      (0.0, 10.0))) is None
    assert _point_may_belong_to_face_bbox((100.0, 100.0), None)
    bbox = (0.0, 0.0, 10.0, 10.0)
    assert _point_may_belong_to_face_bbox((10.0 + 5e-7, 5.0), bbox)
    assert not _point_may_belong_to_face_bbox((10.0 + 2e-6, 5.0), bbox)
    assert not _point_may_belong_to_face_bbox((1000.0, 1000.0), bbox)


def test_room_label_producer_builds_one_sealed_text_authority_per_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Page, word and fallback gates share immutable source text receipts."""
    path = tmp_path / "source-label-text-authority-reuse.pdf"
    _write_two_room_pdf(path)
    source, room_faces = _setup(path)
    original = SourceVisibilityProducer.text_integrity_authority
    created = []

    def counted(self):
        authority = original(self)
        created.append(authority)
        return authority

    monkeypatch.setattr(SourceVisibilityProducer, "text_integrity_authority", counted)
    monkeypatch.setattr(SourceRoomLabelProducer, "_authorize_word", _fake_authorized)
    producer = SourceRoomLabelProducer.from_authorities_for_tests(
        source, room_faces, MockOCRBackend(), page_ids=("1",),
    )
    # Raster corroboration owns one separate sealed text resolver. The label
    # producer must mint its own exactly once rather than once per word.
    assert len(created) == 2
    assert producer._raster._text_authority is created[0]
    assert producer._text_integrity_authority is created[1]
    assert {record.label for record in _records(producer)} == {
        "FOOD PREP", "COLD ROOM",
    }
    # Repeated native selector checks cannot rebuild or alter the sealed
    # authority's source universe.
    assert producer._authorize_word is not None
    assert len(created) == 2


def test_gpt2_source_room_label_ownership_rejects_duplicate_face_ids():
    from types import SimpleNamespace as R
    from pb_source_room_label_authority import (
        _unique_source_faces_for_label_ownership,
    )
    a=R(face_id="face-a",record_id="record-a")
    b=R(face_id="face-b",record_id="record-b")
    conflict=R(face_id="face-a",record_id="another-original-record")
    assert _unique_source_faces_for_label_ownership((a,b,conflict))==(b,)
    assert _unique_source_faces_for_label_ownership((a,b,b))==(a,)


def test_gpt2_source_room_label_ownership_rejects_shared_source_receipt():
    from types import SimpleNamespace as R
    from pb_source_room_label_authority import (
        _unique_source_faces_for_label_ownership,
    )
    a=R(face_id="face-a",record_id="shared")
    b=R(face_id="face-b",record_id="shared")
    independent=R(face_id="face-c",record_id="independent")
    assert _unique_source_faces_for_label_ownership(
        (a,b,independent)
    )==(independent,)
    assert _unique_source_faces_for_label_ownership(
        (independent,b,a)
    )==(independent,)


def test_gpt2_source_room_label_ownership_rejects_string_coerced_ids():
    from types import SimpleNamespace as R
    from pb_source_room_label_authority import (
        _unique_source_faces_for_label_ownership,
    )
    valid=R(face_id="a",record_id="ra")
    malformed=(
        R(face_id=None,record_id="bad1"),
        R(face_id=7,record_id="bad2"),
        R(face_id="b ",record_id="bad3"),
        R(face_id="c",record_id=None),
        R(face_id="d",record_id=73),
        R(face_id="e",record_id="  "),
    )
    assert _unique_source_faces_for_label_ownership(
        (*malformed,valid)
    )==(valid,)
