from __future__ import annotations

import random

from pb_wall_room_topology_contracts import EvidenceResolutionStatus, RoomCandidate
from pb_wall_room_topology_room_label_binding import (
    REASON_ROOM_LABEL_BOUND,
    REASON_ROOM_LABEL_CONFLICT,
    REASON_ROOM_LABEL_POSITION_AMBIGUOUS,
    bind_room_labels_from_words,
    derive_room_label_bindings,
)


def _room(room_ref, polygon, status=EvidenceResolutionStatus.CANDIDATE, label="", reason_codes=()):
    return RoomCandidate(
        room_ref=room_ref,
        label=label,
        polygon_pdf_pts=tuple(polygon),
        polygon_m=None,
        floor_area_m2=None,
        area_page_pts2=1000.0,
        perimeter_m=None,
        geometry_confidence=0.9,
        evidence=(),
        source_page=0,
        drawing_number="",
        scale_source="",
        calibration_confidence=0.0,
        has_voids=False,
        document_id="doc_1",
        viewport_id="vp_1",
        status=status,
        reason_codes=reason_codes,
    )


_ROOM_A = _room("room_A", [(0, 0), (100, 0), (100, 100), (0, 100)])
_ROOM_B = _room("room_B", [(200, 0), (300, 0), (300, 100), (200, 100)])


class TestCleanBinding:
    def test_single_label_binds_to_containing_room(self) -> None:
        labels = [{"label": "KITCHEN", "x": 50, "y": 50, "confidence": 0.95}]
        updated = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        room_a, room_b = updated
        assert room_a.label == "KITCHEN"
        assert room_b.label == ""
        assert any(rc.startswith(REASON_ROOM_LABEL_BOUND) for rc in room_a.reason_codes)

    def test_each_room_gets_its_own_distinct_label(self) -> None:
        labels = [
            {"label": "KITCHEN", "x": 50, "y": 50, "confidence": 0.95},
            {"label": "BEDROOM", "x": 250, "y": 50, "confidence": 0.95},
        ]
        room_a, room_b = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        assert room_a.label == "KITCHEN"
        assert room_b.label == "BEDROOM"
        assert room_a.status == EvidenceResolutionStatus.CANDIDATE
        assert room_b.status == EvidenceResolutionStatus.CANDIDATE

    def test_case_and_whitespace_variants_of_the_same_label_are_not_a_conflict(self) -> None:
        labels = [
            {"label": "Kitchen", "x": 40, "y": 40, "confidence": 0.9},
            {"label": "KITCHEN", "x": 60, "y": 60, "confidence": 0.95},
        ]
        room_a, _room_b = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        assert room_a.label != ""
        assert room_a.status == EvidenceResolutionStatus.CANDIDATE


class TestUnboundLabelsAreDiscardedNotForced:
    def test_label_outside_every_room_is_dropped_silently(self) -> None:
        labels = [{"label": "KITCHEN", "x": 5000, "y": 5000, "confidence": 0.95}]
        updated = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        assert all(r.label == "" for r in updated)
        assert all(r.reason_codes == () for r in updated)

    def test_room_with_no_candidates_is_returned_unchanged(self) -> None:
        updated = derive_room_label_bindings([_ROOM_A, _ROOM_B], [])
        assert updated[0] is _ROOM_A
        assert updated[1] is _ROOM_B


class TestFailClosedLabelConflict:
    def test_two_distinct_labels_in_one_room_fail_closed(self) -> None:
        labels = [
            {"label": "KITCHEN", "x": 40, "y": 40, "confidence": 0.9},
            {"label": "PANTRY", "x": 60, "y": 60, "confidence": 0.85},
        ]
        room_a, room_b = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        assert room_a.label == ""
        assert room_a.status == EvidenceResolutionStatus.ABSTAINED
        assert any(rc.startswith(REASON_ROOM_LABEL_CONFLICT) for rc in room_a.reason_codes)
        assert room_b.label == ""
        assert room_b.status == EvidenceResolutionStatus.CANDIDATE

    def test_conflict_reason_code_lists_both_texts_sorted(self) -> None:
        labels = [
            {"label": "PANTRY", "x": 40, "y": 40, "confidence": 0.9},
            {"label": "KITCHEN", "x": 60, "y": 60, "confidence": 0.9},
        ]
        room_a, _room_b = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        conflict_codes = [rc for rc in room_a.reason_codes if rc.startswith(REASON_ROOM_LABEL_CONFLICT)]
        assert conflict_codes == [f"{REASON_ROOM_LABEL_CONFLICT}:KITCHEN|PANTRY"]


class TestFailClosedPositionAmbiguity:
    def test_label_inside_two_overlapping_room_polygons_binds_to_neither(self) -> None:
        room_c = _room("room_C", [(30, 30), (130, 30), (130, 130), (30, 130)])
        labels = [{"label": "KITCHEN", "x": 60, "y": 60, "confidence": 0.9}]
        room_a, room_c_out = derive_room_label_bindings([_ROOM_A, room_c], labels)
        assert room_a.label == ""
        assert room_c_out.label == ""
        assert any(rc.startswith(REASON_ROOM_LABEL_POSITION_AMBIGUOUS) for rc in room_a.reason_codes)
        assert any(rc.startswith(REASON_ROOM_LABEL_POSITION_AMBIGUOUS) for rc in room_c_out.reason_codes)

    def test_ambiguous_position_label_does_not_count_toward_a_conflict(self) -> None:
        # Only one OTHER unambiguous label lands in room_A -> single distinct
        # text -> bound, even though an ambiguous-position label also touches it.
        room_c = _room("room_C", [(30, 30), (130, 30), (130, 130), (30, 130)])
        labels = [
            {"label": "KITCHEN", "x": 60, "y": 60, "confidence": 0.9},  # ambiguous: in both A and C
            {"label": "PANTRY", "x": 10, "y": 10, "confidence": 0.9},  # only in A
        ]
        room_a, _room_c_out = derive_room_label_bindings([_ROOM_A, room_c], labels)
        assert room_a.label == "PANTRY"


class TestInvariance:
    def test_deterministic_replay(self) -> None:
        labels = [{"label": "KITCHEN", "x": 50, "y": 50, "confidence": 0.95}]
        u1 = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        u2 = derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)
        assert [(r.room_ref, r.label, r.status) for r in u1] == [
            (r.room_ref, r.label, r.status) for r in u2
        ]

    def test_shuffled_room_order_produces_identical_bindings(self) -> None:
        labels = [
            {"label": "KITCHEN", "x": 50, "y": 50, "confidence": 0.95},
            {"label": "BEDROOM", "x": 250, "y": 50, "confidence": 0.95},
        ]
        rooms = [_ROOM_A, _ROOM_B]
        shuffled = list(rooms)
        random.Random(3).shuffle(shuffled)
        result_a = {r.room_ref: r.label for r in derive_room_label_bindings(rooms, labels)}
        result_b = {r.room_ref: r.label for r in derive_room_label_bindings(shuffled, labels)}
        assert result_a == result_b

    def test_shuffled_label_order_produces_identical_bindings(self) -> None:
        labels = [
            {"label": "KITCHEN", "x": 50, "y": 50, "confidence": 0.95},
            {"label": "BEDROOM", "x": 250, "y": 50, "confidence": 0.95},
        ]
        shuffled_labels = list(reversed(labels))
        result_a = {r.room_ref: r.label for r in derive_room_label_bindings([_ROOM_A, _ROOM_B], labels)}
        result_b = {
            r.room_ref: r.label for r in derive_room_label_bindings([_ROOM_A, _ROOM_B], shuffled_labels)
        }
        assert result_a == result_b


class TestRealFilterReuse:
    def test_multi_word_phrase_is_reconstructed_via_existing_filter_and_bound(self) -> None:
        words = [
            {"text": "MASTER", "bbox": [10, 10, 60, 20]},
            {"text": "BEDROOM", "bbox": [62, 10, 120, 20]},
        ]
        room = _room("room_wide", [(0, 0), (200, 0), (200, 100), (0, 100)])
        updated = bind_room_labels_from_words([room], words)
        assert updated[0].label == "MASTER BEDROOM"

    def test_non_room_words_are_never_bound(self) -> None:
        words = [{"text": "2400", "bbox": [10, 10, 40, 20]}]
        room = _room("room_wide", [(0, 0), (200, 0), (200, 100), (0, 100)])
        updated = bind_room_labels_from_words([room], words)
        assert updated[0].label == ""


class TestNoQuantityOrLiveWiring:
    def test_no_quantity_evidence_import_or_construction(self) -> None:
        import pb_wall_room_topology_room_label_binding as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "import QuantityEvidence" not in source
        assert "QuantityEvidence(" not in source
        assert not hasattr(mod, "QuantityEvidence")

    def test_does_not_import_attach_room_labels(self) -> None:
        import pb_wall_room_topology_room_label_binding as mod

        assert not hasattr(mod, "attach_room_labels")
        source = open(mod.__file__, encoding="utf-8").read()
        assert "import attach_room_labels" not in source
        assert "attach_room_labels(" not in source

    def test_not_imported_by_live_extractor(self) -> None:
        source = open("pb_planreader_pdf_extractor.py", encoding="utf-8").read()
        assert "pb_wall_room_topology_room_label_binding" not in source
