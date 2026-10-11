"""GPT2 #23/#27 source-owned room identity and label replay regressions.

These are adversarial source integrity tests, not evidence of new Maryborough
room areas, physical room discovery, or benchmark accuracy.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pb_live_canonical_room_composition import (
    _canonical_polygon_identity,
    _physical_room_id,
    _unique_source_room_labels_by_face,
    _verified_source_room_label_for_face,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_room_label_authority import (
    SourceRoomLabelRecord,
    SourceRoomLabelWordEvidence,
    _RECORD_SEAL,
)


def _source_face(face_id="face-a", receipt="source-face-a"):
    return SimpleNamespace(
        document_id="doc-1", revision_id="revision-1", source_sha256="a" * 64,
        snapshot_id="snapshot-1", page_id="7",
        decision_scope_id="wall-source:page-7", face_id=face_id,
        record_id=receipt,
    )


def _label(face=None, *, label_record="label-a", observation="word-a"):
    face = face or _source_face()
    return SourceRoomLabelRecord(
        record_id=label_record,
        document_id=face.document_id,
        revision_id=face.revision_id,
        source_sha256=face.source_sha256,
        snapshot_id=face.snapshot_id,
        page_id=face.page_id,
        decision_scope_id=face.decision_scope_id,
        face_id=face.face_id,
        source_room_face_record_id=face.record_id,
        label="FREEZER",
        observation_ids=(observation,),
        word_evidence=(SourceRoomLabelWordEvidence(
            observation_id=observation,
            receipt_id="native-" + observation,
            trusted_text="FREEZER",
            authority_kind="native_text_integrity",
            authority_record_id="native-" + observation,
            geometry=(1.0, 1.0, 3.0, 2.0),
            word_no=0,
        ),),
        source_bbox=(1.0, 1.0, 3.0, 2.0),
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=("source_room_label_scope_resolved",),
        _seal=_RECORD_SEAL,
    )


RECT = ((0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0))


def test_fix_1_explicit_closed_source_polygon_stable_identity():
    assert _canonical_polygon_identity(RECT) == _canonical_polygon_identity(
        RECT + (RECT[0],)
    )
    face = _source_face()
    face.polygon_pdf_pts = RECT
    expected = _physical_room_id(face, viewport_id=None)
    face.polygon_pdf_pts = RECT + (RECT[0],)
    assert _physical_room_id(face, viewport_id=None) == expected


def test_fix_2_consecutive_duplicate_vertices_stable_identity():
    duplicated = (RECT[0], RECT[1], RECT[1], RECT[2], RECT[3])
    assert _canonical_polygon_identity(RECT) == _canonical_polygon_identity(duplicated)
    assert _canonical_polygon_identity(RECT) == _canonical_polygon_identity(
        duplicated[::-1]
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_fix_3_nonfinite_source_polygon_cannot_mint_room_id(bad):
    face = _source_face()
    face.polygon_pdf_pts = ((bad, 0.0),) + RECT[1:]
    with pytest.raises(ValueError, match="non-finite"):
        _physical_room_id(face, viewport_id=None)


@pytest.mark.parametrize("polygon", [
    (),
    ((0.0, 0.0), (1.0, 0.0)),
    ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)),
    ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
])
def test_fix_4_degenerate_source_polygon_cannot_publish_sentinel_identity(polygon):
    with pytest.raises(ValueError, match="degenerate"):
        _canonical_polygon_identity(polygon)
    assert _canonical_polygon_identity(RECT)


def test_fix_5_cross_room_producer_label_receipt_replay_quarantined():
    a = _source_face()
    b = _source_face("face-b", "source-face-b")
    c = _source_face("face-c", "source-face-c")
    first = _label(a, label_record="same-receipt", observation="a")
    replayed = _label(b, label_record="same-receipt", observation="b")
    unaffected = _label(c, label_record="independent", observation="c")
    assert _unique_source_room_labels_by_face((first, replayed, unaffected)) == {
        "face-c": unaffected
    }
    assert _unique_source_room_labels_by_face((unaffected, replayed, first)) == {
        "face-c": unaffected
    }


def test_fix_6_cross_room_source_word_observation_replay_quarantined():
    a = _source_face()
    b = _source_face("face-b", "source-face-b")
    c = _source_face("face-c", "source-face-c")
    first = _label(a, label_record="label-a", observation="shared-word")
    replayed = _label(b, label_record="label-b", observation="shared-word")
    unaffected = _label(c, label_record="label-c", observation="unique-word")
    assert _unique_source_room_labels_by_face((first, replayed, unaffected)) == {
        "face-c": unaffected
    }
    assert _unique_source_room_labels_by_face((_label(a),)) == {"face-a": _label(a)}


@pytest.mark.parametrize("field", [
    "document_id", "revision_id", "source_sha256", "snapshot_id",
    "page_id", "decision_scope_id", "face_id",
])
@pytest.mark.parametrize("malformed", [None, "", "  "])
def test_fix_7_matching_but_malformed_source_lineage_never_authorizes_label(
    field, malformed,
):
    face = _source_face()
    label = _label(face)
    setattr(face, field, malformed)
    modified = replace(label, **{field: malformed})
    assert _verified_source_room_label_for_face(face, modified) is None


def test_fix_7_blank_original_source_face_receipt_never_authorizes_label():
    face = _source_face(receipt=None)
    label = _label(face)
    assert _verified_source_room_label_for_face(face, label) is None


def test_fix_8_word_observation_and_receipt_consistency_required():
    face = _source_face()
    label = _label(face)
    assert _verified_source_room_label_for_face(face, label) == label
    word = label.word_evidence[0]
    corrupted = (
        replace(label, observation_ids=("other-word",)),
        replace(label, observation_ids=("word-a", "word-a"),
                word_evidence=(word, word)),
        replace(label, word_evidence=(replace(word, observation_id="other"),)),
        replace(label, word_evidence=(replace(word, receipt_id=""),)),
        replace(label, word_evidence=(replace(word, authority_record_id=""),)),
        replace(label, word_evidence=(replace(word, trusted_text=""),)),
        replace(label, word_evidence=(replace(word, authority_kind="unknown"),)),
    )
    for invalid in corrupted:
        assert _verified_source_room_label_for_face(face, invalid) is None
