"""Canonical room semantics must preserve exact source-owned face ancestry."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pb_live_canonical_room_composition import (
    _room_object_from_record,
    _unique_source_room_labels_by_face,
    _verified_source_room_label_for_face,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_room_label_authority import (
    SourceRoomLabelRecord,
    SourceRoomLabelWordEvidence,
    _RECORD_SEAL,
)


def _face():
    return SimpleNamespace(
        record_id="source-face-record-7",
        document_id="document-1",
        revision_id="revision-1",
        source_sha256="a" * 64,
        snapshot_id="snapshot-1",
        page_id="7",
        decision_scope_id="wall-source:page-7",
        face_id="face-7",
        polygon_pdf_pts=((10.0, 10.0), (80.0, 10.0), (80.0, 40.0), (10.0, 40.0)),
        bounding_wall_ids=("wall-1", "wall-2", "wall-3", "wall-4"),
        area_page_pts2=2100.0,
    )


def _label(face=None):
    face = face or _face()
    return SourceRoomLabelRecord(
        record_id="source-room-label-7",
        document_id=face.document_id,
        revision_id=face.revision_id,
        source_sha256=face.source_sha256,
        snapshot_id=face.snapshot_id,
        page_id=face.page_id,
        decision_scope_id=face.decision_scope_id,
        face_id=face.face_id,
        source_room_face_record_id=face.record_id,
        label="FREEZER",
        observation_ids=("native-word-7",),
        word_evidence=(SourceRoomLabelWordEvidence(
            observation_id="native-word-7",
            receipt_id="text-receipt-7",
            trusted_text="FREEZER",
            authority_kind="native_text_integrity",
            authority_record_id="text-receipt-7",
            geometry=(20.0, 20.0, 55.0, 28.0),
            word_no=0,
        ),),
        source_bbox=(20.0, 20.0, 55.0, 28.0),
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=("source_room_label_scope_resolved",),
        _seal=_RECORD_SEAL,
    )


def _canonical(face, label):
    return _room_object_from_record(
        face,
        viewport_id=None,
        canonical_wall_ids_by_candidate=None,
        unresolved_wall_candidate_ids=None,
        room_label_record=label,
    )


def test_exact_source_owned_label_can_bind_to_same_face_without_granting_metric():
    face = _face()
    room = _canonical(face, _label(face))
    assert room.room_label == "FREEZER"
    assert room.room_label_binding_record_id == "source-room-label-7"
    assert room.source_room_face_record_id == face.record_id
    assert room.geometry_complete
    assert room.metric_geometry_complete is False
    assert room.area_page_pts2 == 2100.0
    assert room.coordinate_unit == "pdf_pt"


@pytest.mark.parametrize("field,replacement", [
    ("document_id", "other-doc"),
    ("revision_id", "other-revision"),
    ("source_sha256", "b" * 64),
    ("snapshot_id", "other-snapshot"),
    ("page_id", "8"),
    ("decision_scope_id", "wall-source:page-8"),
    ("face_id", "other-face"),
    ("source_room_face_record_id", "other-face-record"),
])
def test_stale_or_cross_face_label_cannot_relabel_valid_geometry(field, replacement):
    face = _face()
    invalid = replace(_label(face), **{field: replacement})
    plain = _canonical(face, None)
    room = _canonical(face, invalid)
    assert _verified_source_room_label_for_face(face, invalid) is None
    assert room.room_label is None
    assert room.room_label_binding_record_id is None
    assert room.room_label_evidence_ids == ()
    assert room.canonical_room_id == plain.canonical_room_id
    assert room.polygon_pdf_pts == plain.polygon_pdf_pts
    assert room.source_room_face_record_id == face.record_id


def test_duplicate_identical_receipt_is_idempotent_but_distinct_competitor_abstains():
    first = _label()
    duplicate = replace(first)
    competitor = replace(first, record_id="other-label-receipt", label="SALES")
    assert _unique_source_room_labels_by_face((first, duplicate)) == {"face-7": first}
    assert _unique_source_room_labels_by_face((first, competitor)) == {}
    assert _unique_source_room_labels_by_face((competitor, first)) == {}
    assert _unique_source_room_labels_by_face((first, competitor, first)) == {}


def test_distinct_faces_keep_independent_receipts_on_competition():
    face = _face()
    first = _label(face)
    # A distinct physical face needs an independent native word observation,
    # not merely a different label record ID. Reusing native-word-7 would
    # correctly quarantine both faces under the cross-face replay guard.
    second_word = replace(
        first.word_evidence[0], observation_id="native-word-8",
        receipt_id="text-receipt-8", authority_record_id="text-receipt-8",
    )
    second = replace(
        first, face_id="face-8", source_room_face_record_id="source-face-record-8",
        record_id="source-label-8", observation_ids=("native-word-8",),
        word_evidence=(second_word,),
    )
    competitor = replace(first, record_id="competing-face-7-receipt")
    assert _unique_source_room_labels_by_face((first, second, competitor)) == {
        "face-8": second
    }
