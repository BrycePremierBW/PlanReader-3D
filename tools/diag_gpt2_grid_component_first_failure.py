"""Read-only first-failure audit for original source split-label grid rooms.

Calls existing production source wall, room face, and split-label authorities;
never creates room geometry, changes candidate truth, or issues quantities.
"""
from __future__ import annotations

from collections import Counter
from typing import Any
from shapely.geometry import Polygon
from shapely.ops import unary_union

from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_composite_room_face_authority import (
    _fully_grid_opposed_wall_evidence,
    _grid_local_adjacency,
    _grid_connected_component,
    _component_has_conflicting_label,
    _candidate_record,
    _atomic_source_wall_edge_counts,
    _edge_key,
)
from pb_physical_wall_candidate_authority import PhysicalWallCandidateScopeResult
from pb_source_room_face_authority import SourceRoomFaceScopeResult
from pb_source_room_label_authority import SourceRoomLabelScopeResult


def _physical_union_first_unclosed_gate(
    component: tuple[str, ...],
    *,
    room_scope: SourceRoomFaceScopeResult,
    fully_grid_wall_ids: set[str],
    grid_evidence: Any,
    local_counts: Any,
) -> dict[str, Any]:
    """Read-only mirror of existing production source-boundary checks.

    No geometry is returned or published; no labels, missing source walls,
    dimension values, physical equivalences or material semantics inferred.
    """
    result = {
        "physical_union_first_unclosed_gate": "source_boundary_unverified",
        "physical_union_candidate_source_face_count": len(component),
        "physical_union_merged_geometry_type_observed_only": None,
        "physical_union_external_grid_edge_count": 0,
        "physical_union_external_grid_w4_ids_diagnostic_only": [],
        "physical_union_internal_separator_edge_count": 0,
        "new_room_geometry_published": False,
        "new_metric_area_published": False,
    }
    # Never let a dict overwrite competing physical face or producer receipt
    # identities. This read-only gate must mirror the production fail-closed
    # source identity contract before examining any geometry.
    face_counts = Counter(getattr(rec, "face_id", None) for rec in room_scope.records)
    receipt_counts = Counter(getattr(rec, "record_id", None) for rec in room_scope.records)
    records = {rec.face_id: rec for rec in room_scope.records}
    if any(face_id not in records for face_id in component):
        result["physical_union_first_unclosed_gate"] = "source_component_face_missing"
        return result
    if any(
        face_counts[face_id] != 1
        or not isinstance(records[face_id].record_id, str)
        or not records[face_id].record_id
        or receipt_counts[records[face_id].record_id] != 1
        for face_id in component
    ):
        result["physical_union_first_unclosed_gate"] = "source_component_face_receipt_conflict"
        return result
    try:
        polygons = [Polygon(records[face_id].polygon_pdf_pts) for face_id in component]
        if any(p.is_empty or not p.is_valid or p.area <= 0 for p in polygons):
            result["physical_union_first_unclosed_gate"] = "source_component_polygon_invalid"
            return result
        merged = unary_union(polygons)
        result["physical_union_merged_geometry_type_observed_only"] = merged.geom_type
        if (
            merged.geom_type != "Polygon" or merged.is_empty or not merged.is_valid
            or merged.area <= 0 or len(tuple(merged.interiors)) != 0
            or abs(sum(p.area for p in polygons) - merged.area)
            > max(1e-6, merged.length * 1e-6)
        ):
            result["physical_union_first_unclosed_gate"] = (
                "source_union_disconnected_overlapping_or_has_holes"
            )
            return result
    except Exception:
        result["physical_union_first_unclosed_gate"] = "source_polygon_union_unavailable"
        return result

    # Producer requires every constituent boundary receipt to be an
    # admissible exact wall subedge. Do not skip bad rows during noding.
    for face_id in component:
        for item in tuple(getattr(records[face_id], "boundary_wall_edges", ()) or ()):
            try:
                wall_id = item[0]
                edge = _edge_key(item[1])
            except (IndexError, TypeError, ValueError, OverflowError):
                edge = None
                wall_id = None
            if (
                not isinstance(wall_id, str) or not wall_id
                or wall_id != wall_id.strip() or edge is None
            ):
                result["physical_union_first_unclosed_gate"] = "source_boundary_receipt_invalid"
                return result

    local = local_counts
    if local is None:
        local = _atomic_source_wall_edge_counts(room_scope, fully_grid_wall_ids)
    owners = {
        key: tuple(sorted(counts))
        for key, counts in local.items()
        if all(value == 1 for value in counts.values())
    }
    component_set = set(component)
    totals = {
        key: sum(n for face, n in face_counts.items() if face in component_set)
        for key, face_counts in local.items()
    }
    totals = {key: n for key, n in totals.items() if n > 0}
    if not totals or any(n > 2 for n in totals.values()):
        result["physical_union_first_unclosed_gate"] = "source_atomic_wall_edge_multiplicity_invalid"
        return result

    internal, external = set(), set()
    for key, count in totals.items():
        wall_id, _edge = key
        global_owners = owners.get(key, ())
        if count == 2:
            if (
                wall_id not in fully_grid_wall_ids or len(global_owners) != 2
                or not set(global_owners).issubset(component_set)
            ):
                result["physical_union_first_unclosed_gate"] = (
                    "source_internal_wall_edge_not_two_sided_grid_owned"
                )
                return result
            internal.add(key)
        elif count == 1:
            external.add(key)
        else:
            result["physical_union_first_unclosed_gate"] = (
                "source_atomic_wall_edge_multiplicity_invalid"
            )
            return result
    result["physical_union_internal_separator_edge_count"] = len(internal)
    external_grid_ids=sorted({
        wall_id for wall_id, edge in external if wall_id in fully_grid_wall_ids
    })
    result["physical_union_external_grid_edge_count"] = sum(
        wall_id in fully_grid_wall_ids for wall_id, edge in external
    )
    # Record actual W4 source identities needed by the upstream wall agent;
    # they remain unowned/diagnostic and are not used as a geometry repair.
    result["physical_union_external_grid_w4_ids_diagnostic_only"] = external_grid_ids[:24]
    result["physical_union_external_grid_w4_id_count"] = len(external_grid_ids)
    if not internal or not external:
        result["physical_union_first_unclosed_gate"] = (
            "source_internal_or_external_boundary_not_complete"
        )
    elif result["physical_union_external_grid_edge_count"]:
        result["physical_union_first_unclosed_gate"] = (
            "source_external_grid_owned_subedge_room_incomplete"
        )
    elif any(
        not grid_evidence.get(wall_id, ())
        for wall_id, edge in internal
    ):
        result["physical_union_first_unclosed_gate"] = (
            "source_grid_separator_receipt_unavailable"
        )
    else:
        result["physical_union_first_unclosed_gate"] = (
            "source_boundary_gates_passed_candidate_only"
        )
    return result


def inspect_split_grid_component_first_failure(
    candidate: Any,
    *,
    wall_scope: PhysicalWallCandidateScopeResult,
    room_scope: SourceRoomFaceScopeResult,
    label_scope: SourceRoomLabelScopeResult,
    grid_walls: set[str] | None = None,
    grid_evidence: Any = None,
    grid_adjacency: Any = None,
    local_counts: Any = None,
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

    # A scoped source run already has these producer-owned grid indexes.
    # Reuse them across candidates instead of rescanning every W4 and
    # source face separately for each native room label.
    if grid_walls is None or grid_evidence is None:
        fully_grid, grid_evidence = _fully_grid_opposed_wall_evidence(wall_scope)
    else:
        fully_grid = grid_walls
    output["fully_grid_opposed_w4_wall_count"] = len(fully_grid)
    if not fully_grid:
        output["first_unclosed_gate"] = "no_producer_authenticated_grid_opposed_w4"
        return output

    adjacency = (
        grid_adjacency if grid_adjacency is not None
        else _grid_local_adjacency(room_scope, fully_grid)
    )
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
        local_counts=local_counts,
    )
    if selected is None:
        output["physical_union_source_first_failure_diagnostic_only"] = (
            _physical_union_first_unclosed_gate(
                connected, room_scope=room_scope,
                fully_grid_wall_ids=fully_grid, grid_evidence=grid_evidence,
                local_counts=local_counts,
            )
        )
        output["first_unclosed_gate"] = (
            "grid_connected_component_physical_boundary_or_union_unproven"
        )
    else:
        # This states only that the EXISTING production function could
        # return a record; the diagnostic never publishes it.
        output["first_unclosed_gate"] = "production_grid_composite_available"
        output["production_composite_record_id_observed_only"] = selected.record_id
    return output
