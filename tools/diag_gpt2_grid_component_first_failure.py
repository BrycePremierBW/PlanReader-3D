"""Read-only first-failure audit for original source split-label grid rooms.

Calls existing production source wall, room face, and split-label authorities;
never creates room geometry, changes candidate truth, or issues quantities.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_composite_room_face_authority import (
    _fully_grid_opposed_wall_evidence,
    _grid_local_adjacency,
    _grid_connected_component,
    _component_has_conflicting_label,
    _candidate_record,
)
from pb_physical_wall_candidate_authority import PhysicalWallCandidateScopeResult
from pb_source_room_face_authority import SourceRoomFaceScopeResult
from pb_source_room_label_authority import SourceRoomLabelScopeResult


def inspect_split_grid_component_first_failure(
    candidate: Any,
    *,
    wall_scope: PhysicalWallCandidateScopeResult,
    room_scope: SourceRoomFaceScopeResult,
    label_scope: SourceRoomLabelScopeResult,
) -> dict[str, Any]:
    """Diagnose first missing production authority; do not promote candidates."""
    raw_seeds = getattr(candidate, "word_face_ids", ()) or ()
    seeds = tuple(raw_seeds) if isinstance(raw_seeds, (tuple, list)) else ()
    output = {
        "source_split_candidate_record_id": getattr(candidate, "record_id", None),
        "native_room_label": getattr(candidate, "label", None),
        "native_word_face_ids": list(seeds),
        "first_unclosed_gate": "source_producer_inputs_unverified",
        "connected_component_source_face_ids_diagnostic_only": [],
        "source_room_composite_published_by_diagnostic": False,
        "source_room_metric_area_published": False,
        "new_room_label_owned": False,
    }
    if (
        type(wall_scope) is not PhysicalWallCandidateScopeResult
        or type(room_scope) is not SourceRoomFaceScopeResult
        or type(label_scope) is not SourceRoomLabelScopeResult
        or wall_scope.status is not EvidenceResolutionStatus.CORROBORATED
        or room_scope.status is not EvidenceResolutionStatus.CORROBORATED
        or room_scope.scope_complete is not True
    ):
        return output
    lineage_fields = (
        "document_id", "revision_id", "source_sha256",
        "snapshot_id", "page_id", "decision_scope_id",
    )
    if any(
        getattr(wall_scope, field, None) != getattr(room_scope, field, None)
        or getattr(label_scope, field, None) != getattr(room_scope, field, None)
        or getattr(candidate, field, None) != getattr(room_scope, field, None)
        for field in lineage_fields
    ):
        output["first_unclosed_gate"] = "source_scope_lineage_conflict"
        return output
    if (
        len(seeds) < 2
        or any(
            not isinstance(face, str) or not face or face != face.strip()
            for face in seeds
        )
        or len(set(seeds)) < 2
    ):
        output["first_unclosed_gate"] = "split_source_word_face_identity_unresolved"
        return output

    face_counts = Counter(getattr(face, "face_id", None) for face in room_scope.records)
    record_counts = Counter(getattr(face, "record_id", None) for face in room_scope.records)
    faces = {
        face.face_id: face for face in room_scope.records
        if isinstance(face.face_id, str) and face.face_id
    }
    distinct = tuple(dict.fromkeys(seeds))
    expected = []
    for face_id in distinct:
        row = faces.get(face_id)
        if (
            face_counts[face_id] != 1 or row is None
            or not isinstance(row.record_id, str) or not row.record_id
            or record_counts[row.record_id] != 1
        ):
            output["first_unclosed_gate"] = "split_source_face_or_receipt_ambiguous"
            return output
        expected.append(row.record_id)
    if tuple(getattr(candidate, "source_room_face_record_ids", ()) or ()) != tuple(expected):
        output["first_unclosed_gate"] = "split_label_source_face_receipt_mismatch"
        return output

    fully_grid, grid_evidence = _fully_grid_opposed_wall_evidence(wall_scope)
    output["fully_grid_opposed_w4_wall_count"] = len(fully_grid)
    if not fully_grid:
        output["first_unclosed_gate"] = "no_producer_authenticated_grid_opposed_w4"
        return output

    adjacency = _grid_local_adjacency(room_scope, fully_grid)
    connected = _grid_connected_component(
        seeds, room_scope=room_scope, fully_grid_wall_ids=fully_grid,
        adjacency=adjacency,
    )
    if connected is None:
        output["first_unclosed_gate"] = "split_words_not_connected_by_exact_grid_owned_edges"
        return output
    output["connected_component_source_face_ids_diagnostic_only"] = list(connected)
    if _component_has_conflicting_label(
        connected, candidate, label_scope=label_scope,
    ):
        output["first_unclosed_gate"] = "grid_connected_component_has_competing_room_label"
        return output
    selected = _candidate_record(
        candidate, wall_scope=wall_scope, room_scope=room_scope,
        label_scope=label_scope, fully_grid_wall_ids=fully_grid,
        grid_evidence_by_wall=grid_evidence, grid_adjacency=adjacency,
    )
    if selected is None:
        output["first_unclosed_gate"] = (
            "grid_connected_component_physical_boundary_or_union_unproven"
        )
    else:
        # This states only that the EXISTING production function could
        # return a record; the diagnostic never publishes it.
        output["first_unclosed_gate"] = "production_grid_composite_available"
        output["production_composite_record_id_observed_only"] = selected.record_id
    return output
