"""Fail-closed composite source-room faces for grid-split room labels.

This producer repairs one narrow topology failure without deleting wall geometry:
an independently authenticated multi-word room label may be split across adjacent
SourceRoomFace records by drafting-grid walls. A composite is published only
when every internal face transition is separated exclusively by W4 candidates
whose contributing W2 edges all carry producer-owned source-lineage KIND_GRID
opposition. When the authenticated label words occupy only part of that grid
component, the producer completes the exact connected component through those
same proven grid separators. The final constituent union must be one valid
polygon, contain no conflicting authenticated room label, and expose no
remaining grid-opposed external boundary.

The producer never invents dimensions, metric area, room semantics, nearest-face
matches, or project-specific rules. Original wall and room-face authorities stay
unchanged and remain available for audit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from typing import Mapping

from shapely.geometry import Polygon
from shapely.ops import unary_union

from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_physical_wall_candidate_authority import PhysicalWallCandidateScopeResult
from pb_source_room_face_authority import SourceRoomFaceScopeResult
from pb_source_room_label_authority import (
    SourceRoomLabelScopeResult,
    SourceRoomSplitLabelCandidate,
)
from pb_wall_room_topology_typed_negative_evidence import (
    KIND_GRID,
    POLARITY_OPPOSING,
)


SOURCE_COMPOSITE_ROOM_FACE_SCHEMA_VERSION = "1.0.0"
SOURCE_COMPOSITE_ROOM_FACE_RESOLVED = "source_composite_room_face_resolved"
SOURCE_COMPOSITE_ROOM_FACE_UNAVAILABLE = "source_composite_room_face_unavailable"
SOURCE_COMPOSITE_ROOM_FACE_LINEAGE_CONFLICT = (
    "source_composite_room_face_lineage_conflict"
)
SOURCE_COMPOSITE_ROOM_FACE_SEPARATOR_UNRESOLVED = (
    "source_composite_room_face_separator_unresolved"
)
SOURCE_COMPOSITE_ROOM_FACE_UNION_UNRESOLVED = (
    "source_composite_room_face_union_unresolved"
)
SOURCE_LINEAGE_GRID_REASON = "source_lineage_dense_orthogonal_lattice"


@dataclass(frozen=True)
class CompositeSourceRoomFaceRecord:
    record_id: str
    face_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    polygon_pdf_pts: tuple[tuple[float, float], ...]
    bounding_wall_ids: tuple[str, ...]
    area_page_pts2: float
    label: str
    label_candidate_record_id: str
    label_evidence_ids: tuple[str, ...]
    constituent_face_ids: tuple[str, ...]
    constituent_source_room_face_record_ids: tuple[str, ...]
    separator_wall_ids: tuple[str, ...]
    grid_evidence_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    schema_version: str = SOURCE_COMPOSITE_ROOM_FACE_SCHEMA_VERSION


@dataclass(frozen=True)
class CompositeSourceRoomFaceResult:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    records: tuple[CompositeSourceRoomFaceRecord, ...]
    unresolved_label_candidate_ids: tuple[str, ...]
    schema_version: str = SOURCE_COMPOSITE_ROOM_FACE_SCHEMA_VERSION


def _lineage(value) -> tuple[str, str, str, str, str, str]:
    return (
        str(value.document_id),
        str(value.revision_id),
        str(value.source_sha256),
        str(value.snapshot_id),
        str(value.page_id),
        str(value.decision_scope_id),
    )


def _wall_edge_ids(record) -> tuple[str, ...]:
    wall = record.wall_candidate
    return tuple(
        dict.fromkeys(
            (
                *tuple(str(v) for v in (wall.face_a_segment_ids or ())),
                *tuple(str(v) for v in (wall.face_b_segment_ids or ())),
            )
        )
    )


def _fully_grid_opposed_wall_evidence(
    wall_scope: PhysicalWallCandidateScopeResult,
) -> tuple[set[str], Mapping[str, tuple[str, ...]]]:
    grid_evidence_by_edge: dict[str, set[str]] = defaultdict(set)
    for atom in tuple(wall_scope.typed_semantic_evidence_atoms or ()):
        metadata = dict(getattr(atom, "metadata", {}) or {})
        if (
            getattr(atom, "kind", None) != KIND_GRID
            or getattr(atom, "status", None) is not EvidenceResolutionStatus.CANDIDATE
            or str(metadata.get("polarity") or "") != POLARITY_OPPOSING
            or SOURCE_LINEAGE_GRID_REASON
            not in tuple(getattr(atom, "reason_codes", ()) or ())
        ):
            continue
        edge_id = str(metadata.get("target_edge_id") or "").strip()
        evidence_id = str(getattr(atom, "evidence_id", "") or "").strip()
        if edge_id and evidence_id:
            grid_evidence_by_edge[edge_id].add(evidence_id)

    # W4 addresses are not inherently unique physical identities. If a
    # producer scope contains two candidates with the same wall ID, neither
    # can authorize a grid separator until W4 source identity is resolved.
    # This preserves independent wall evidence while preventing ambiguous
    # source edge ancestry from silently connecting physical room cells.
    wall_ids = Counter(str(record.wall_candidate_id) for record in wall_scope.records)
    fully: set[str] = set()
    evidence_by_wall: dict[str, tuple[str, ...]] = {}
    for record in wall_scope.records:
        wall_id = str(record.wall_candidate_id)
        if not wall_id.strip() or wall_ids[wall_id] != 1:
            continue
        edge_ids = _wall_edge_ids(record)
        if not edge_ids or not all(edge_id in grid_evidence_by_edge for edge_id in edge_ids):
            continue
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for edge_id in edge_ids
                    for evidence_id in grid_evidence_by_edge.get(edge_id, ())
                }
            )
        )
        if evidence_ids:
            fully.add(wall_id)
            evidence_by_wall[wall_id] = evidence_ids
    return fully, evidence_by_wall


def _edge_key(value) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Normalize one producer-owned planarized edge without adding tolerance."""

    try:
        first = (float(value[0][0]), float(value[0][1]))
        second = (float(value[1][0]), float(value[1][1]))
    except (IndexError, TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(v) for point in (first, second) for v in point):
        return None
    if first == second:
        return None
    return (first, second) if first <= second else (second, first)


def _atomic_source_wall_edge_counts(
    room_scope: SourceRoomFaceScopeResult,
    fully_grid_wall_ids: set[str],
) -> Mapping[
    tuple[str, tuple[tuple[float, float], tuple[float, float]]],
    Counter[str],
]:
    """Node only axis-aligned, producer-owned W4 grid edges at source endpoints.

    RoomFace boundary edges can end at different source-authenticated grid
    intersections although the same physical W4 wall owns their overlap.
    The existing exact-edge owner map then sees no two-sided local separator.

    This function *only subdivides* the source's original collinear edges.
    It never snaps offset lines, extends a wall, connects at point contacts,
    substitutes a different W4 wall, or authorizes any room. Non-grid and
    non-axis-aligned edges retain their exact producer-owned edge identity.
    Duplicate same-face edge claims remain duplicated and cannot be used as
    two distinct physical owners by the caller.
    """
    counts: dict[
        tuple[str, tuple[tuple[float, float], tuple[float, float]]],
        Counter[str],
    ] = defaultdict(Counter)
    grid_intervals: dict[
        tuple[str, str, float],
        list[tuple[float, float, str]],
    ] = defaultdict(list)

    for record in room_scope.records:
        face_id = str(record.face_id)
        for item in tuple(getattr(record, "boundary_wall_edges", ()) or ()):
            try:
                wall_id = str(item[0] or "").strip()
                edge = _edge_key(item[1])
            except (IndexError, TypeError):
                continue
            if not wall_id or edge is None:
                continue
            (ax, ay), (bx, by) = edge
            if wall_id in fully_grid_wall_ids and ax == bx:
                grid_intervals[(wall_id, "vertical", ax)].append(
                    (min(ay, by), max(ay, by), face_id)
                )
            elif wall_id in fully_grid_wall_ids and ay == by:
                grid_intervals[(wall_id, "horizontal", ay)].append(
                    (min(ax, bx), max(ax, bx), face_id)
                )
            else:
                counts[(wall_id, edge)][face_id] += 1

    for (wall_id, axis, fixed), spans in grid_intervals.items():
        # Sweep exact source endpoints instead of scanning every source
        # interval for every atomic edge. This preserves per-face multiplicity:
        # overlapping duplicate receipts count twice and never authenticate
        # an apparent two-sided W4 separator.
        events: dict[float, Counter[str]] = defaultdict(Counter)
        for start, end, face_id in spans:
            events[start][face_id] += 1
            events[end][face_id] -= 1
        cuts = sorted(events)
        active: Counter[str] = Counter()
        for index, start in enumerate(cuts[:-1]):
            for face_id, delta in events[start].items():
                new_count = active[face_id] + delta
                if new_count > 0:
                    active[face_id] = new_count
                else:
                    active.pop(face_id, None)
            end = cuts[index + 1]
            if end <= start or not active:
                continue
            atomic_edge = (
                ((fixed, start), (fixed, end))
                if axis == "vertical"
                else ((start, fixed), (end, fixed))
            )
            counts[(wall_id, atomic_edge)].update(active)
    return counts


def _local_edge_owners(
    room_scope: SourceRoomFaceScopeResult,
) -> Mapping[
    tuple[str, tuple[tuple[float, float], tuple[float, float]]],
    tuple[str, ...],
]:
    """Exact (W4 wall id, planarized subedge) ownership from room authority."""

    owners: dict[
        tuple[str, tuple[tuple[float, float], tuple[float, float]]],
        set[str],
    ] = defaultdict(set)
    for record in room_scope.records:
        face_id = str(record.face_id)
        for item in tuple(getattr(record, "boundary_wall_edges", ()) or ()):
            try:
                wall_id = str(item[0] or "").strip()
                edge = _edge_key(item[1])
            except (IndexError, TypeError):
                continue
            if wall_id and edge is not None:
                owners[(wall_id, edge)].add(face_id)
    return {
        key: tuple(sorted(face_ids))
        for key, face_ids in owners.items()
    }


def _grid_local_adjacency(
    room_scope: SourceRoomFaceScopeResult,
    fully_grid_wall_ids: set[str],
    *,
    local_counts=None,
) -> Mapping[
    str,
    tuple[
        tuple[
            str,
            str,
            tuple[tuple[float, float], tuple[float, float]],
        ],
        ...,
    ],
]:
    """Return neighbours sharing the exact same grid-owned planarized subedge.

    A W4 wall may span many room cells, so whole-wall owner counts are not
    adjacency evidence. The SourceRoomFace producer already proved a unique
    wall owner for every published face subedge; exactly two published faces
    owning the same (wall, subedge) is the local two-sided separator proof.
    """

    adjacency: dict[
        str,
        set[
            tuple[
                str,
                str,
                tuple[tuple[float, float], tuple[float, float]],
            ]
        ],
    ] = defaultdict(set)
    if local_counts is None:
        local_counts = _atomic_source_wall_edge_counts(room_scope, fully_grid_wall_ids)
    for (wall_id, edge), face_counts in local_counts.items():
        if (
            wall_id not in fully_grid_wall_ids
            or len(face_counts) != 2
            or any(count != 1 for count in face_counts.values())
        ):
            continue
        left_id, right_id = sorted(face_counts)
        adjacency[left_id].add((right_id, wall_id, edge))
        adjacency[right_id].add((left_id, wall_id, edge))
    return {
        face_id: tuple(sorted(values))
        for face_id, values in adjacency.items()
    }


def _grid_connected_component(
    seed_face_ids: tuple[str, ...],
    *,
    room_scope: SourceRoomFaceScopeResult,
    fully_grid_wall_ids: set[str],
    adjacency=None,
) -> tuple[str, ...] | None:
    """Complete one room through exact two-sided grid-owned subedges."""

    room_by_face = {str(record.face_id): record for record in room_scope.records}
    seeds = tuple(dict.fromkeys(str(value) for value in seed_face_ids))
    if len(seeds) < 2 or any(face_id not in room_by_face for face_id in seeds):
        return None

    if adjacency is None:
        adjacency = _grid_local_adjacency(room_scope, fully_grid_wall_ids)
    visited: set[str] = {seeds[0]}
    pending = [seeds[0]]
    while pending:
        face_id = pending.pop()
        for neighbour, _wall_id, _edge in adjacency.get(face_id, ()):
            if neighbour not in visited:
                visited.add(neighbour)
                pending.append(neighbour)

    if any(seed not in visited for seed in seeds):
        return None
    return tuple(sorted(visited))


def _component_has_conflicting_label(
    component_face_ids: tuple[str, ...],
    candidate: SourceRoomSplitLabelCandidate,
    *,
    label_scope: SourceRoomLabelScopeResult,
) -> bool:
    """Block a completed grid component that contains another room identity."""

    component = set(component_face_ids)
    if any(
        str(record.face_id) in component
        for record in tuple(label_scope.records or ())
    ):
        return True

    for other in tuple(label_scope.split_face_candidates or ()):
        if str(other.record_id) == str(candidate.record_id):
            continue
        if component.intersection(str(value) for value in other.word_face_ids):
            return True
    return False


def _candidate_record(
    candidate: SourceRoomSplitLabelCandidate,
    *,
    wall_scope: PhysicalWallCandidateScopeResult,
    room_scope: SourceRoomFaceScopeResult,
    label_scope: SourceRoomLabelScopeResult,
    fully_grid_wall_ids: set[str],
    grid_evidence_by_wall: Mapping[str, tuple[str, ...]],
    local_counts=None,
    grid_adjacency=None,
) -> CompositeSourceRoomFaceRecord | None:
    room_by_face = {str(record.face_id): record for record in room_scope.records}
    seed_face_ids = tuple(str(value) for value in candidate.word_face_ids)
    constituent_face_ids = _grid_connected_component(
        seed_face_ids,
        room_scope=room_scope,
        fully_grid_wall_ids=fully_grid_wall_ids,
        adjacency=grid_adjacency,
    )
    if constituent_face_ids is None:
        return None
    if _component_has_conflicting_label(
        constituent_face_ids,
        candidate,
        label_scope=label_scope,
    ):
        return None

    constituent = [room_by_face[face_id] for face_id in constituent_face_ids]
    polygons = [Polygon(record.polygon_pdf_pts) for record in constituent]
    if any(poly.is_empty or not poly.is_valid or poly.area <= 0.0 for poly in polygons):
        return None
    merged = unary_union(polygons)
    if (
        merged.geom_type != "Polygon"
        or merged.is_empty
        or not merged.is_valid
        or merged.area <= 0.0
        or len(tuple(merged.interiors)) != 0
        or abs(sum(poly.area for poly in polygons) - merged.area)
        > max(1e-6, merged.length * 1e-6)
    ):
        # Source faces must partition a physical room, never overlap in area.
        # This is a fail-closed geometric conservation gate; it does not
        # authenticate an internal source-grid separator on its own.
        return None

    polygon = tuple(
        (round(float(x), 6), round(float(y), 6))
        for x, y in tuple(merged.exterior.coords)[:-1]
    )
    if len(polygon) < 3:
        return None

    component_face_set = set(constituent_face_ids)
    # Validate every actual face-boundary receipt; invalid or missing source
    # edges must not disappear simply because noding skips them.
    for record in constituent:
        for item in tuple(getattr(record, "boundary_wall_edges", ()) or ()):
            try:
                wall_id = str(item[0] or "").strip()
                edge = _edge_key(item[1])
            except (IndexError, TypeError):
                return None
            if not wall_id or edge is None:
                return None

    if local_counts is None:
        local_counts = _atomic_source_wall_edge_counts(room_scope, fully_grid_wall_ids)
    edge_owners = {
        key: tuple(sorted(face_counts))
        for key, face_counts in local_counts.items()
        if all(count == 1 for count in face_counts.values())
    }
    component_edge_counts: Counter[
        tuple[str, tuple[tuple[float, float], tuple[float, float]]]
    ] = Counter({
        key: sum(count for face_id, count in face_counts.items()
                 if face_id in component_face_set)
        for key, face_counts in local_counts.items()
    })
    component_edge_counts = +component_edge_counts

    if not component_edge_counts or any(count > 2 for count in component_edge_counts.values()):
        return None

    separator_keys: set[
        tuple[str, tuple[tuple[float, float], tuple[float, float]]]
    ] = set()
    external_keys: set[
        tuple[str, tuple[tuple[float, float], tuple[float, float]]]
    ] = set()
    for key, count in component_edge_counts.items():
        wall_id, _edge = key
        global_owners = edge_owners.get(key, ())
        if count == 2:
            # An internal boundary may disappear only when the exact local
            # subedge is globally two-sided and its W4 wall is fully grid.
            if (
                wall_id not in fully_grid_wall_ids
                or len(global_owners) != 2
                or not set(global_owners).issubset(component_face_set)
            ):
                return None
            separator_keys.add(key)
        elif count == 1:
            external_keys.add(key)
        else:
            return None

    if not separator_keys or not external_keys:
        return None

    # Preserve the #1683 hardening at subedge resolution. A long grid wall can
    # be internal at one cell and external at another; any grid-owned external
    # subedge means the room component is still incomplete and must abstain.
    if any(wall_id in fully_grid_wall_ids for wall_id, _edge in external_keys):
        return None

    separator_wall_ids = {wall_id for wall_id, _edge in separator_keys}
    external_walls = tuple(sorted({wall_id for wall_id, _edge in external_keys}))
    if not external_walls:
        return None

    grid_evidence_ids: set[str] = set()
    for wall_id in separator_wall_ids:
        grid_evidence_ids.update(grid_evidence_by_wall.get(wall_id, ()))
    if not grid_evidence_ids:
        return None

    constituent_record_ids = tuple(
        room_by_face[face_id].record_id for face_id in constituent_face_ids
    )
    decision_scope_id = stable_contract_id(
        "composite_source_room_face_scope",
        {
            "document_id": candidate.document_id,
            "page_id": candidate.page_id,
            "parent_decision_scope_id": candidate.decision_scope_id,
            "label_candidate_record_id": candidate.record_id,
            "constituent_source_room_face_record_ids": constituent_record_ids,
        },
        digest_chars=32,
    )
    face_id = stable_contract_id(
        "composite_source_room_face",
        {
            "document_id": candidate.document_id,
            "revision_id": candidate.revision_id,
            "source_sha256": candidate.source_sha256,
            "snapshot_id": candidate.snapshot_id,
            "page_id": candidate.page_id,
            "decision_scope_id": decision_scope_id,
            "polygon_pdf_pts": polygon,
        },
        digest_chars=32,
    )
    label_evidence_ids = tuple(
        dict.fromkeys(
            (
                *candidate.observation_ids,
                *(str(word.authority_record_id) for word in candidate.word_evidence),
            )
        )
    )
    grid_ids = tuple(sorted(grid_evidence_ids))
    evidence_ids = tuple(
        dict.fromkeys(
            (
                *constituent_record_ids,
                candidate.record_id,
                *label_evidence_ids,
                *grid_ids,
            )
        )
    )
    record_id = stable_contract_id(
        "composite_source_room_face_record",
        {
            "face_id": face_id,
            "label_candidate_record_id": candidate.record_id,
            "constituent_source_room_face_record_ids": constituent_record_ids,
            "separator_wall_ids": tuple(sorted(separator_wall_ids)),
            "grid_evidence_ids": grid_ids,
        },
        digest_chars=32,
    )
    return CompositeSourceRoomFaceRecord(
        record_id=record_id,
        face_id=face_id,
        document_id=candidate.document_id,
        revision_id=candidate.revision_id,
        source_sha256=candidate.source_sha256,
        snapshot_id=candidate.snapshot_id,
        page_id=candidate.page_id,
        decision_scope_id=decision_scope_id,
        polygon_pdf_pts=polygon,
        bounding_wall_ids=external_walls,
        area_page_pts2=float(merged.area),
        label=candidate.label,
        label_candidate_record_id=candidate.record_id,
        label_evidence_ids=label_evidence_ids,
        constituent_face_ids=constituent_face_ids,
        constituent_source_room_face_record_ids=constituent_record_ids,
        separator_wall_ids=tuple(sorted(separator_wall_ids)),
        grid_evidence_ids=grid_ids,
        evidence_ids=evidence_ids,
    )

def compose_grid_separated_room_faces(
    *,
    wall_scope: PhysicalWallCandidateScopeResult,
    room_scope: SourceRoomFaceScopeResult,
    label_scope: SourceRoomLabelScopeResult,
) -> CompositeSourceRoomFaceResult:
    """Publish only exact, connected composites of authenticated split labels."""

    if (
        type(wall_scope) is not PhysicalWallCandidateScopeResult
        or type(room_scope) is not SourceRoomFaceScopeResult
        or type(label_scope) is not SourceRoomLabelScopeResult
    ):
        raise TypeError("composite room inputs must be exact producer-owned scope results")
    if not (_lineage(wall_scope) == _lineage(room_scope) == _lineage(label_scope)):
        return CompositeSourceRoomFaceResult(
            status=EvidenceResolutionStatus.CONFLICT,
            reason_codes=(SOURCE_COMPOSITE_ROOM_FACE_LINEAGE_CONFLICT,),
            records=(),
            unresolved_label_candidate_ids=tuple(
                candidate.record_id for candidate in label_scope.split_face_candidates
            ),
        )
    if (
        wall_scope.status is not EvidenceResolutionStatus.CORROBORATED
        or room_scope.status is not EvidenceResolutionStatus.CORROBORATED
        or not room_scope.scope_complete
        or not room_scope.records
        or not label_scope.split_face_candidates
    ):
        return CompositeSourceRoomFaceResult(
            status=EvidenceResolutionStatus.ABSTAINED,
            reason_codes=(SOURCE_COMPOSITE_ROOM_FACE_UNAVAILABLE,),
            records=(),
            unresolved_label_candidate_ids=tuple(
                candidate.record_id for candidate in label_scope.split_face_candidates
            ),
        )

    fully_grid, evidence_by_wall = _fully_grid_opposed_wall_evidence(wall_scope)
    # Source-wall node ownership and grid connectivity are scope-global.
    # Build once, then preserve exactly the same candidate-local checks.
    local_counts = _atomic_source_wall_edge_counts(room_scope, fully_grid)
    grid_adjacency = _grid_local_adjacency(
        room_scope, fully_grid, local_counts=local_counts
    )
    records: list[CompositeSourceRoomFaceRecord] = []
    unresolved: list[str] = []
    for candidate in label_scope.split_face_candidates:
        record = _candidate_record(
            candidate,
            wall_scope=wall_scope,
            room_scope=room_scope,
            label_scope=label_scope,
            fully_grid_wall_ids=fully_grid,
            grid_evidence_by_wall=evidence_by_wall,
            local_counts=local_counts,
            grid_adjacency=grid_adjacency,
        )
        if record is None:
            unresolved.append(candidate.record_id)
        else:
            records.append(record)

    records.sort(key=lambda record: (record.label, record.record_id))
    if records and not unresolved:
        status = EvidenceResolutionStatus.CORROBORATED
        reasons = (SOURCE_COMPOSITE_ROOM_FACE_RESOLVED,)
    elif records:
        status = EvidenceResolutionStatus.CANDIDATE
        reasons = (
            SOURCE_COMPOSITE_ROOM_FACE_RESOLVED,
            SOURCE_COMPOSITE_ROOM_FACE_SEPARATOR_UNRESOLVED,
        )
    else:
        status = EvidenceResolutionStatus.ABSTAINED
        reasons = (
            SOURCE_COMPOSITE_ROOM_FACE_SEPARATOR_UNRESOLVED,
            SOURCE_COMPOSITE_ROOM_FACE_UNION_UNRESOLVED,
        )
    return CompositeSourceRoomFaceResult(
        status=status,
        reason_codes=reasons,
        records=tuple(records),
        unresolved_label_candidate_ids=tuple(sorted(unresolved)),
    )


__all__ = [
    "SOURCE_COMPOSITE_ROOM_FACE_SCHEMA_VERSION",
    "SOURCE_COMPOSITE_ROOM_FACE_RESOLVED",
    "SOURCE_COMPOSITE_ROOM_FACE_UNAVAILABLE",
    "SOURCE_COMPOSITE_ROOM_FACE_LINEAGE_CONFLICT",
    "SOURCE_COMPOSITE_ROOM_FACE_SEPARATOR_UNRESOLVED",
    "SOURCE_COMPOSITE_ROOM_FACE_UNION_UNRESOLVED",
    "CompositeSourceRoomFaceRecord",
    "CompositeSourceRoomFaceResult",
    "compose_grid_separated_room_faces",
]
