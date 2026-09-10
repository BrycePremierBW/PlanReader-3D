"""W8: room semantic label binding.

Binds already-extracted, already-filtered room-name text evidence to the
correct ``RoomCandidate`` by spatial containment (point-in-polygon).

REUSE, NOT REINVENTION
------------------------
This module deliberately does NOT build a new room-label vocabulary, a new
text-filtering pass, or a new point-in-polygon test:

- ``filter_room_label_candidates`` (``pb_room_face_takeoff``) is the
  existing, tested semantic-label filter: it already rejects dimensions,
  door/window tags, and drawing annotations, and already reconstructs
  multi-word phrases ("MASTER BEDROOM", "WALK IN ROBE") from adjacent PDF
  words with a position anchor. Reused unmodified.
- ``_point_in_polygon`` (``pb_wall_room_topology_room_faces``, W5's own
  module in this same workstream) is reused for spatial containment,
  rather than importing the point-in-polygon test that lives in the
  unrelated ``pb_room_face_takeoff``/``pb_accuracy_v13_engines_v145``
  BOQ pipeline, or writing a third copy.

This module deliberately does NOT reuse ``attach_room_labels``
(``pb_accuracy_v13_engines_v145``): that function silently takes
``matches[0]`` when a label position falls inside more than one polygon,
and never detects two different label texts landing in the same polygon.
Both are exactly the ambiguity classes this stage must fail closed on, so
a new (small, additive) binding function is written here instead of
reusing that one -- see FAIL-CLOSED AMBIGUITY below. ``attach_room_labels``
itself is left completely untouched; nothing here calls or rewires it.

FAIL-CLOSED AMBIGUITY
------------------------
- A label candidate whose anchor point falls inside zero room polygons is
  simply not attached anywhere -- it is discarded evidence (a title-block
  note, a drawing annotation that slipped through, text outside any closed
  face), not forced onto the nearest room.
- A label candidate whose anchor point falls inside two or more room
  polygons (should not happen -- W5's planar-face reconstruction produces
  disjoint faces -- but is checked, not assumed) is excluded from binding
  to ANY of them; each affected room instead records a
  ``ROOM_LABEL_POSITION_AMBIGUOUS`` reason code.
- A room whose surviving (unambiguous-position) candidates carry two or
  more DISTINCT label texts (case/whitespace-insensitive) is a genuine
  conflict: ``label`` stays ``""`` and ``status`` is set to
  ``EvidenceResolutionStatus.ABSTAINED`` (the one fusion-status vocabulary
  already used throughout this workstream -- no new status is introduced,
  matching ``RoomCandidate``'s own current restriction against using
  ``CONFLICT`` before a later stage adds a conflict-evidence field). A
  room with exactly one distinct surviving label text gets that text
  bound to ``label`` (status is left as-is -- binding a label is not
  geometric corroboration, so it does not on its own promote status).
- A room with zero surviving candidates is left completely unchanged;
  ``label`` stays at whatever value it already had (``""`` for every
  RoomCandidate produced by W5/W6, per their own tests).

Does NOT:
- extract text or run OCR (consumes already-extracted PDF word evidence,
  the same ``[{"text": str, "bbox": [x0,y0,x1,y1]}, ...]`` shape already
  produced by the existing PDF-word extraction used in
  ``pb_room_face_takeoff.extract_room_faces_from_page``);
- assign a room type/classification beyond the literal label text;
- emit ``QuantityEvidence``;
- wire into any live extraction path.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Sequence, Tuple

from pb_room_face_takeoff import filter_room_label_candidates
from pb_wall_room_topology_contracts import EvidenceResolutionStatus, RoomCandidate
from pb_wall_room_topology_room_faces import _point_in_polygon

REASON_ROOM_LABEL_BOUND = "room_label_spatially_bound_via_point_in_polygon"
REASON_ROOM_LABEL_CONFLICT = "room_label_conflict_distinct_texts"
REASON_ROOM_LABEL_POSITION_AMBIGUOUS = "room_label_position_ambiguous_across_rooms"


def _normalize(label: str) -> str:
    return " ".join(label.strip().lower().split())


def derive_room_label_bindings(
    rooms: Sequence[RoomCandidate], label_candidates: Sequence[Dict[str, Any]]
) -> List[RoomCandidate]:
    """Bind already-filtered label candidates (see module docstring for the
    expected ``{"label", "x", "y", ...}`` shape, exactly as returned by
    ``pb_room_face_takeoff.filter_room_label_candidates``) to *rooms*."""
    candidate_room_refs: List[List[str]] = [[] for _ in label_candidates]
    room_candidate_indices: Dict[str, List[int]] = {room.room_ref: [] for room in rooms}

    for idx, candidate in enumerate(label_candidates):
        point = (float(candidate.get("x", 0.0)), float(candidate.get("y", 0.0)))
        for room in rooms:
            if _point_in_polygon(point, room.polygon_pdf_pts):
                candidate_room_refs[idx].append(room.room_ref)

    ambiguous_indices = {idx for idx, refs in enumerate(candidate_room_refs) if len(refs) >= 2}
    for idx in ambiguous_indices:
        for room_ref in candidate_room_refs[idx]:
            room_candidate_indices[room_ref].append(idx)

    for idx, refs in enumerate(candidate_room_refs):
        if idx in ambiguous_indices or len(refs) != 1:
            continue
        room_candidate_indices[refs[0]].append(idx)

    updated_rooms: List[RoomCandidate] = []
    for room in rooms:
        indices = room_candidate_indices[room.room_ref]
        if not indices:
            updated_rooms.append(room)
            continue

        ambiguous_here = [i for i in indices if i in ambiguous_indices]
        unambiguous_here = [i for i in indices if i not in ambiguous_indices]

        distinct_texts: Dict[str, Tuple[int, str]] = {}
        for i in unambiguous_here:
            text = str(label_candidates[i].get("label", "")).strip()
            if not text:
                continue
            key = _normalize(text)
            confidence = float(label_candidates[i].get("confidence", 0.0))
            if key not in distinct_texts or confidence > distinct_texts[key][0]:
                distinct_texts[key] = (confidence, text)

        reason_codes = list(room.reason_codes)
        for i in ambiguous_here:
            text = str(label_candidates[i].get("label", "")).strip()
            reason_codes.append(f"{REASON_ROOM_LABEL_POSITION_AMBIGUOUS}:{text}")

        if len(distinct_texts) >= 2:
            chosen_texts = sorted(text for _confidence, text in distinct_texts.values())
            reason_codes.append(f"{REASON_ROOM_LABEL_CONFLICT}:{'|'.join(chosen_texts)}")
            updated_rooms.append(
                replace(
                    room,
                    label="",
                    status=EvidenceResolutionStatus.ABSTAINED,
                    reason_codes=tuple(reason_codes),
                )
            )
        elif len(distinct_texts) == 1:
            (_confidence, chosen_label) = next(iter(distinct_texts.values()))
            reason_codes.append(f"{REASON_ROOM_LABEL_BOUND}:{chosen_label}")
            updated_rooms.append(
                replace(room, label=chosen_label, reason_codes=tuple(reason_codes))
            )
        else:
            if reason_codes != list(room.reason_codes):
                updated_rooms.append(replace(room, reason_codes=tuple(reason_codes)))
            else:
                updated_rooms.append(room)

    return updated_rooms


def bind_room_labels_from_words(
    rooms: Sequence[RoomCandidate], words: Sequence[Dict[str, Any]]
) -> List[RoomCandidate]:
    """Convenience entry point: filter raw PDF words to credible room-label
    candidates (reusing ``filter_room_label_candidates`` unmodified), then
    bind them to *rooms*."""
    label_candidates = filter_room_label_candidates(list(words))
    return derive_room_label_bindings(rooms, label_candidates)
