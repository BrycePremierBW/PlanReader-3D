"""Read-only W1-W10 wall/room topology diagnostics.

This module never participates in production extraction, scoring, mappings,
or wall classification. It accepts already-produced W1-W10 records (or
calls those existing APIs without changing their return values) and emits
deterministic JSON / Markdown / optional SVG summaries.

It does not decide whether a WallCandidate is a true wall.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pb_drawing_evidence_binding import DrawingViewType
from pb_migration_contracts import canonical_contract_json, stable_contract_id
from pb_vector_geometry_v130 import extract_native_page
from pb_viewport_segmentation import (
    SegmentedViewport,
    ViewportSegmentationStatus,
    segment_page_viewports,
)
from pb_wall_room_topology_canonical_adapter import adapt_topology_to_canonical_level
from pb_wall_room_topology_contracts import (
    JunctionCandidate,
    OpeningHostCandidate,
    RoomCandidate,
    RoomTopologyRelationship,
    TopologyRelationship,
    WallCandidate,
)
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_opening_host_binding import detect_opening_host_candidates
from pb_wall_room_topology_reconciliation import TopologyReconciliationSummary, reconcile_topology
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_room_label_binding import bind_room_labels_from_words
from pb_wall_room_topology_room_wall_relationships import derive_room_wall_relationships
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates, rekey_junctions_to_wall_candidates
from pb_wall_topology_ranking_validation import ranking_bucket, ranking_signals, summarize_ranking

DIAGNOSTIC_SCHEMA_VERSION = "1.0.0"
FLOAT_DIGITS = 6
UNKNOWN = "UNKNOWN"
UNAVAILABLE = "unavailable"
NOT_EVALUATED = "not_evaluated"

_HORIZONTAL_DEG = 15.0
_VERTICAL_LOW_DEG = 75.0
_VERTICAL_HIGH_DEG = 105.0

_HATCH_EXCLUSION_CODES = frozenset({"hatch_layer_excluded"})


def _round_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("non-finite float is not serializable in a diagnostic report")
    if numeric == 0.0:
        return 0.0
    return round(numeric, FLOAT_DIGITS)


def _round_point(point: Sequence[float]) -> List[float]:
    return [_round_float(float(point[0])), _round_float(float(point[1]))]


def _normalize(value: Any) -> Any:
    if isinstance(value, float):
        return _round_float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def report_to_canonical_json(report: Mapping[str, Any]) -> str:
    """Byte-stable canonical JSON for a diagnostic report."""
    return canonical_contract_json(_normalize(dict(report)))


def _polyline_length_pt(points: Sequence[Sequence[float]]) -> Optional[float]:
    if len(points) < 2:
        return None
    total = 0.0
    for index in range(len(points) - 1):
        x0, y0 = float(points[index][0]), float(points[index][1])
        x1, y1 = float(points[index + 1][0]), float(points[index + 1][1])
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def _bbox_from_points(points: Sequence[Sequence[float]]) -> Optional[List[float]]:
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [_round_float(min(xs)), _round_float(min(ys)), _round_float(max(xs)), _round_float(max(ys))]


def _orientation(points: Sequence[Sequence[float]]) -> Dict[str, Any]:
    if len(points) < 2:
        return {"class": UNKNOWN, "angle_deg": None}
    dx = float(points[-1][0]) - float(points[0][0])
    dy = float(points[-1][1]) - float(points[0][1])
    if dx == 0.0 and dy == 0.0:
        return {"class": UNKNOWN, "angle_deg": None}
    angle = math.degrees(math.atan2(dy, dx)) % 180.0
    if angle < _HORIZONTAL_DEG or angle > (180.0 - _HORIZONTAL_DEG):
        classification = "horizontal"
    elif _VERTICAL_LOW_DEG <= angle <= _VERTICAL_HIGH_DEG:
        classification = "vertical"
    else:
        classification = "diagonal"
    return {"class": classification, "angle_deg": _round_float(angle)}


def percentile(values: Sequence[float], percent: float) -> Optional[float]:
    """Linear-interpolation percentile on an already-collected sample.

    ``percent`` is in ``[0, 100]``. Empty input returns ``None``.
    """
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1 or percent <= 0.0:
        return _round_float(ordered[0])
    if percent >= 100.0:
        return _round_float(ordered[-1])
    rank = (len(ordered) - 1) * (percent / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return _round_float(ordered[low])
    weight = rank - low
    return _round_float(ordered[low] + (ordered[high] - ordered[low]) * weight)


def length_distribution(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
        }
    ordered = sorted(float(value) for value in values)
    mean = sum(ordered) / len(ordered)
    return {
        "count": len(ordered),
        "min": _round_float(ordered[0]),
        "max": _round_float(ordered[-1]),
        "mean": _round_float(mean),
        "median": percentile(ordered, 50.0),
        "p10": percentile(ordered, 10.0),
        "p25": percentile(ordered, 25.0),
        "p50": percentile(ordered, 50.0),
        "p75": percentile(ordered, 75.0),
        "p90": percentile(ordered, 90.0),
        "p95": percentile(ordered, 95.0),
    }


class _UnionFind:
    def __init__(self, keys: Iterable[str]) -> None:
        self._parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        parent = self._parent[key]
        if parent != key:
            parent = self.find(parent)
            self._parent[key] = parent
        return parent

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        if root_left < root_right:
            self._parent[root_right] = root_left
        else:
            self._parent[root_left] = root_right

    def groups(self) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for key in self._parent:
            grouped.setdefault(self.find(key), []).append(key)
        return {root: sorted(members) for root, members in grouped.items()}


def _point_in_bbox(point: Sequence[float], bbox: Sequence[float]) -> bool:
    return (
        float(bbox[0]) <= float(point[0]) <= float(bbox[2])
        and float(bbox[1]) <= float(point[1]) <= float(bbox[3])
    )


def _bbox_fully_inside(inner: Sequence[float], outer: Sequence[float]) -> bool:
    return (
        float(inner[0]) >= float(outer[0])
        and float(inner[1]) >= float(outer[1])
        and float(inner[2]) <= float(outer[2])
        and float(inner[3]) <= float(outer[3])
    )


def _segment_in_viewport(segment: Mapping[str, Any], bbox: Sequence[float]) -> bool:
    start = (float(segment["x1"]), float(segment["y1"]))
    end = (float(segment["x2"]), float(segment["y2"]))
    return _point_in_bbox(start, bbox) and _point_in_bbox(end, bbox)


def _paired_face_state(wall: WallCandidate) -> str:
    if wall.face_b_segment_ids:
        return "yes"
    if wall.representation == "double_line":
        return "yes"
    if wall.representation == "single_line":
        return "no"
    return UNAVAILABLE


def _opening_binding_state(
    wall_id: str,
    hosts: Sequence[OpeningHostCandidate],
    *,
    evaluated: bool,
) -> str:
    if not evaluated:
        return NOT_EVALUATED
    matching = [host for host in hosts if wall_id in host.candidate_wall_ids_considered]
    if not matching:
        return "UNBOUND"
    if any(host.host_status == "hosted" for host in matching):
        return "BOUND"
    if any(host.host_status == "ambiguous_host" for host in matching):
        return "AMBIGUOUS"
    return "UNBOUND"


@dataclass(frozen=True)
class TopologySnapshot:
    """Immutable bag of existing W1-W10 outputs for one viewport.

    Diagnostic code must not mutate any nested object the caller supplied.
    """

    document_id: str
    page_id: str
    page_number: int
    viewport_id: str
    viewport_authority: str
    view_type: Optional[str] = None
    raw_primitive_count: int = 0
    scoped_primitive_count: int = 0
    stage_a_graph: Mapping[str, Any] = field(default_factory=dict)
    junctions: Tuple[JunctionCandidate, ...] = ()
    relationships: Tuple[TopologyRelationship, ...] = ()
    walls: Tuple[WallCandidate, ...] = ()
    edge_id_to_wall_id: Mapping[str, str] = field(default_factory=dict)
    rooms: Tuple[RoomCandidate, ...] = ()
    room_relationships: Tuple[RoomTopologyRelationship, ...] = ()
    opening_hosts: Tuple[OpeningHostCandidate, ...] = ()
    opening_host_evaluated: bool = False
    reconciliation: Optional[TopologyReconciliationSummary] = None
    fail_closed_reason: Optional[str] = None

    def with_reconciliation(self) -> "TopologySnapshot":
        summary = reconcile_topology(
            self.viewport_id,
            junctions=self.junctions,
            walls=self.walls,
            rooms=self.rooms,
            room_relationships=self.room_relationships,
            opening_hosts=self.opening_hosts,
        )
        return replace(self, reconciliation=summary)


def collect_topology_from_segments(
    segments: Sequence[Mapping[str, Any]],
    *,
    document_id: str,
    page_id: str,
    page_number: int,
    viewport_id: str,
    viewport_authority: str = "caller_supplied",
    view_type: Optional[str] = None,
    words: Sequence[Mapping[str, Any]] = (),
    raw_primitive_count: Optional[int] = None,
    evaluate_opening_hosts: bool = True,
    bind_room_labels: bool = True,
) -> TopologySnapshot:
    """Run the existing W2-W10 APIs on already-scoped segments.

    This is an orchestrator, not a second reconstruction algorithm.
    """
    segment_list = [dict(segment) for segment in segments]
    graph = build_wall_graph_for_viewport(segment_list)
    junctions, relationships = classify_junctions(
        graph,
        document_id=document_id,
        page_id=page_id,
        viewport_id=viewport_id,
    )
    walls, edge_map = assemble_wall_candidates(
        graph, junctions, relationships, viewport_id=viewport_id
    )
    rekeyed = rekey_junctions_to_wall_candidates(junctions, edge_map)
    rooms = reconstruct_room_candidates(
        graph,
        edge_map,
        document_id=document_id,
        viewport_id=viewport_id,
        source_page=page_number,
    )
    rooms, walls, room_rels = derive_room_wall_relationships(rooms, walls)
    if bind_room_labels and words:
        rooms = bind_room_labels_from_words(rooms, list(words))
    hosts: List[OpeningHostCandidate] = []
    if evaluate_opening_hosts:
        hosts = detect_opening_host_candidates(walls)
    snapshot = TopologySnapshot(
        document_id=document_id,
        page_id=page_id,
        page_number=page_number,
        viewport_id=viewport_id,
        viewport_authority=viewport_authority,
        view_type=view_type,
        raw_primitive_count=int(
            raw_primitive_count if raw_primitive_count is not None else len(segment_list)
        ),
        scoped_primitive_count=len(segment_list),
        stage_a_graph=graph,
        junctions=tuple(rekeyed),
        relationships=tuple(relationships),
        walls=tuple(walls),
        edge_id_to_wall_id=dict(edge_map),
        rooms=tuple(rooms),
        room_relationships=tuple(room_rels),
        opening_hosts=tuple(hosts),
        opening_host_evaluated=evaluate_opening_hosts,
    )
    return snapshot.with_reconciliation()


def _eligible_floor_plan_viewports(
    viewports: Sequence[SegmentedViewport],
    *,
    allow_derived: bool,
) -> List[SegmentedViewport]:
    allowed = {ViewportSegmentationStatus.RESOLVED.value}
    if allow_derived:
        allowed.add(ViewportSegmentationStatus.DERIVED.value)
    return [
        viewport
        for viewport in viewports
        if viewport.status in allowed
        and viewport.bounding_box is not None
        and viewport.view_type == DrawingViewType.FLOOR_PLAN.value
    ]


def _authority_label(viewport: SegmentedViewport) -> str:
    if viewport.status == ViewportSegmentationStatus.RESOLVED.value:
        return "resolved_floor_plan"
    if viewport.status == ViewportSegmentationStatus.DERIVED.value:
        return "derived_floor_plan"
    return viewport.status


def collect_topology_from_page(
    page: Any,
    *,
    page_number: int,
    document_id: str,
    allow_derived: bool = False,
    viewport_id: Optional[str] = None,
    viewport_bbox: Optional[Sequence[float]] = None,
) -> TopologySnapshot:
    """Extract native geometry, require safe spatial authority, then run W2-W10.

    Authority is either a safe F.07 floor-plan viewport or an explicit
    caller-supplied ``viewport_bbox``. The harness never invents a box.
    """
    native = extract_native_page(page)
    page_id = f"page_{page_number}"
    raw_count = int(native.get("segment_count") or len(native.get("segments") or []))

    if viewport_bbox is not None:
        if len(viewport_bbox) != 4:
            raise ValueError("viewport_bbox must be (x0, y0, x1, y1)")
        bbox = [float(value) for value in viewport_bbox]
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError("viewport_bbox must have x0 < x1 and y0 < y1")
        scoped_segments = [
            segment for segment in native.get("segments") or [] if _segment_in_viewport(segment, bbox)
        ]
        scoped_words = [
            word
            for word in native.get("words") or []
            if word.get("bbox") and _bbox_fully_inside(word["bbox"], bbox)
        ]
        return collect_topology_from_segments(
            scoped_segments,
            document_id=document_id,
            page_id=page_id,
            page_number=page_number,
            viewport_id=viewport_id or f"caller_bbox_p{page_number}",
            viewport_authority="caller_supplied",
            view_type=None,
            words=scoped_words,
            raw_primitive_count=raw_count,
        )

    viewports = segment_page_viewports(page, page_number=page_number)
    eligible = _eligible_floor_plan_viewports(viewports, allow_derived=allow_derived)
    if viewport_id is not None:
        eligible = [viewport for viewport in eligible if viewport.view_id == viewport_id]
    if not eligible:
        reason = "safe_floor_plan_viewport_unavailable"
        if viewport_id is not None:
            reason = "requested_viewport_not_a_safe_floor_plan"
        return TopologySnapshot(
            document_id=document_id,
            page_id=page_id,
            page_number=page_number,
            viewport_id=viewport_id or "",
            viewport_authority="unavailable",
            view_type=None,
            raw_primitive_count=raw_count,
            fail_closed_reason=reason,
        )

    chosen = sorted(eligible, key=lambda item: (item.view_id, item.title_bbox))[0]
    bbox = chosen.bounding_box
    assert bbox is not None
    scoped_segments = [
        segment for segment in native.get("segments") or [] if _segment_in_viewport(segment, bbox)
    ]
    scoped_words = [
        word
        for word in native.get("words") or []
        if word.get("bbox") and _bbox_fully_inside(word["bbox"], bbox)
    ]
    return collect_topology_from_segments(
        scoped_segments,
        document_id=document_id,
        page_id=page_id,
        page_number=page_number,
        viewport_id=chosen.view_id,
        viewport_authority=_authority_label(chosen),
        view_type=chosen.view_type,
        words=scoped_words,
        raw_primitive_count=raw_count,
    )


def _connected_components(
    walls: Sequence[WallCandidate],
    junctions: Sequence[JunctionCandidate],
) -> Tuple[Dict[str, str], List[Dict[str, Any]], Dict[str, set], Dict[str, List[str]]]:
    wall_ids = [wall.candidate_id for wall in walls]
    union = _UnionFind(wall_ids)
    neighbor_degree: Dict[str, set] = {wall_id: set() for wall_id in wall_ids}
    junction_participation: Dict[str, List[str]] = {wall_id: [] for wall_id in wall_ids}

    for junction in junctions:
        incident = [wall_id for wall_id in junction.incident_wall_candidate_ids if wall_id in neighbor_degree]
        for wall_id in incident:
            junction_participation[wall_id].append(junction.node_id)
        for left in incident:
            for right in incident:
                if left == right:
                    continue
                union.union(left, right)
                neighbor_degree[left].add(right)

    groups = union.groups()
    component_records: List[Dict[str, Any]] = []
    wall_to_component: Dict[str, str] = {}
    for members in sorted(groups.values(), key=lambda item: (-len(item), item[0] if item else "")):
        component_id = stable_contract_id("comp", {"members": tuple(members)})
        component_records.append(
            {
                "component_id": component_id,
                "size": len(members),
                "wall_candidate_ids": members,
            }
        )
        for wall_id in members:
            wall_to_component[wall_id] = component_id
    return wall_to_component, component_records, neighbor_degree, junction_participation


def diagnose_wall_topology(snapshot: TopologySnapshot) -> Dict[str, Any]:
    """Summarize a snapshot. Never mutates ``snapshot`` or its nested records."""
    walls = list(snapshot.walls)
    rooms = list(snapshot.rooms)
    hosts = list(snapshot.opening_hosts)
    junctions = list(snapshot.junctions)
    graph = snapshot.stage_a_graph or {}
    excluded = list(graph.get("excluded_segments") or [])
    stage_a_edges = [edge for edge in graph.get("edges") or [] if not edge.get("_removed")]

    wall_to_component, components, neighbor_degree, junction_participation = _connected_components(
        walls, junctions
    )
    rooms_by_wall: Dict[str, List[str]] = {wall.candidate_id: [] for wall in walls}
    for room in rooms:
        for wall_id in room.bounding_wall_candidate_ids:
            rooms_by_wall.setdefault(wall_id, []).append(room.room_ref)

    wall_rows: List[Dict[str, Any]] = []
    for wall in sorted(walls, key=lambda item: item.candidate_id):
        length_pt = _polyline_length_pt(wall.centerline_pts)
        orientation = _orientation(wall.centerline_pts)
        component_id = wall_to_component.get(wall.candidate_id)
        component_size = next(
            (item["size"] for item in components if item["component_id"] == component_id),
            1 if walls else 0,
        )
        neighbors = sorted(neighbor_degree.get(wall.candidate_id, set()))
        junction_nodes = sorted(set(junction_participation.get(wall.candidate_id, [])))
        hatch_state = UNAVAILABLE
        wall_rows.append(
            {
                "candidate_id": wall.candidate_id,
                "source_primitive_ids": list(wall.face_a_segment_ids),
                "source_stage": "W4",
                "bbox": _bbox_from_points(wall.centerline_pts),
                "start": _round_point(wall.centerline_pts[0]) if wall.centerline_pts else None,
                "end": _round_point(wall.centerline_pts[-1]) if wall.centerline_pts else None,
                "length_pt": _round_float(length_pt),
                "length_m": _round_float(wall.length_m),
                "orientation": orientation["class"],
                "orientation_angle_deg": orientation["angle_deg"],
                "thickness_m": _round_float(wall.thickness_m),
                "thickness_authority": wall.thickness_authority.value,
                "spacing_evidence": UNAVAILABLE,
                "paired_face_evidence": _paired_face_state(wall),
                "fill_hatch_evidence": hatch_state,
                "junction_node_ids": junction_nodes,
                "junction_degree": len(neighbors),
                "connected_component_id": component_id,
                "connected_component_size": component_size,
                "room_face_participation": "yes" if rooms_by_wall.get(wall.candidate_id) else "no",
                "room_refs": sorted(set(rooms_by_wall.get(wall.candidate_id, []))),
                "relationship_degree": len(neighbors),
                "opening_host_state": _opening_binding_state(
                    wall.candidate_id, hosts, evaluated=snapshot.opening_host_evaluated
                ),
                "opening_host_ids": sorted(
                    host.host_candidate_id
                    for host in hosts
                    if wall.candidate_id in host.candidate_wall_ids_considered
                ),
                "provenance": {
                    "viewport_id": wall.viewport_id,
                    "end_node_ids": list(wall.end_node_ids),
                    "face_b_segment_ids": (
                        list(wall.face_b_segment_ids) if wall.face_b_segment_ids else None
                    ),
                    "supporting_evidence_ids": list(wall.supporting_evidence_ids),
                    "conflicting_evidence_ids": list(wall.conflicting_evidence_ids),
                },
                "ranking_bucket": ranking_bucket(wall),
                "ranking_signals": ranking_signals(wall),
                "resolution_status": wall.status.value,
                "ambiguity_state": (
                    "ambiguous"
                    if any("ambiguous" in code for code in wall.reason_codes)
                    or any(code.startswith("chain_extension_blocked_by:ambiguous") for code in wall.reason_codes)
                    else wall.status.value
                ),
                "rejection_or_abstention_reason": (
                    list(wall.reason_codes) if wall.reason_codes else None
                ),
                "interior_exterior": wall.interior_exterior,
                "confidence": _round_float(wall.confidence),
                "representation": wall.representation,
            }
        )

    lengths = [row["length_pt"] for row in wall_rows if row["length_pt"] is not None]
    orientation_counts = Counter(row["orientation"] for row in wall_rows)
    junction_degree_counts = Counter()
    for row in wall_rows:
        degree = row["junction_degree"]
        if degree <= 0:
            junction_degree_counts["0"] += 1
        elif degree == 1:
            junction_degree_counts["1"] += 1
        elif degree == 2:
            junction_degree_counts["2"] += 1
        else:
            junction_degree_counts["3+"] += 1

    isolated_ids = [row["candidate_id"] for row in wall_rows if row["connected_component_size"] == 1]
    room_yes = sum(1 for row in wall_rows if row["room_face_participation"] == "yes")
    paired_counts = Counter(row["paired_face_evidence"] for row in wall_rows)
    hatch_excluded = sum(
        1
        for segment in excluded
        if any(code in _HATCH_EXCLUSION_CODES for code in segment.get("reason_codes") or [])
    )
    binding_counts = Counter(row["opening_host_state"] for row in wall_rows)
    junction_types = Counter(junction.junction_type.value for junction in junctions)

    highest_connectivity = sorted(
        wall_rows,
        key=lambda row: (-int(row["junction_degree"]), -(row["length_pt"] or 0.0), row["candidate_id"]),
    )[:20]
    longest = sorted(
        wall_rows,
        key=lambda row: (-(row["length_pt"] or 0.0), row["candidate_id"]),
    )[:20]
    largest_component_members = []
    if components:
        largest = components[0]
        largest_component_members = [
            row for row in wall_rows if row["candidate_id"] in set(largest["wall_candidate_ids"])
        ]
        largest_component_members = sorted(
            largest_component_members,
            key=lambda row: (-(row["length_pt"] or 0.0), row["candidate_id"]),
        )[:20]

    ambiguous_candidates = [
        row["candidate_id"]
        for row in wall_rows
        if row["opening_host_state"] == "AMBIGUOUS" or row["ambiguity_state"] == "ambiguous"
    ]
    ambiguous_hosts = [
        {
            "host_candidate_id": host.host_candidate_id,
            "host_status": host.host_status,
            "considered_wall_ids": list(host.candidate_wall_ids_considered),
            "reason_codes": list(host.reason_codes),
        }
        for host in sorted(hosts, key=lambda item: item.host_candidate_id)
    ]

    stages_evaluated: List[str] = []
    if snapshot.stage_a_graph:
        stages_evaluated.extend(["W2", "W3", "W4", "W5", "W6"])
        if snapshot.opening_host_evaluated:
            stages_evaluated.append("W7")
        if any(room.label for room in rooms):
            stages_evaluated.append("W8")
        if snapshot.reconciliation is not None:
            stages_evaluated.append("W9")

    report = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "source": {
            "document_id": snapshot.document_id,
            "page_id": snapshot.page_id,
            "page_number": snapshot.page_number,
            "viewport_id": snapshot.viewport_id,
            "viewport_authority": snapshot.viewport_authority,
            "view_type": snapshot.view_type,
            "fail_closed_reason": snapshot.fail_closed_reason,
        },
        "pipeline": {
            "stages_evaluated": stages_evaluated,
            "opening_host_evaluated": snapshot.opening_host_evaluated,
        },
        "counts": {
            "raw_primitives": snapshot.raw_primitive_count,
            "scoped_primitives": snapshot.scoped_primitive_count,
            "stage_a_edges": len(stage_a_edges),
            "excluded_segments": len(excluded),
            "wall_candidates": len(wall_rows),
            "junctions": len(junctions),
            "topology_relationships": len(snapshot.relationships),
            "room_candidates": len(rooms),
            "room_relationships": len(snapshot.room_relationships),
            "opening_hosts": len(hosts),
            "connected_components": len(components),
            "isolated_candidates": len(isolated_ids),
        },
        "distributions": {
            "candidate_length_pt": length_distribution(lengths),
            "orientation": {
                "horizontal": orientation_counts.get("horizontal", 0),
                "vertical": orientation_counts.get("vertical", 0),
                "diagonal": orientation_counts.get("diagonal", 0),
                "UNKNOWN": orientation_counts.get(UNKNOWN, 0),
            },
            "junction_degree": {
                "0": junction_degree_counts.get("0", 0),
                "1": junction_degree_counts.get("1", 0),
                "2": junction_degree_counts.get("2", 0),
                "3+": junction_degree_counts.get("3+", 0),
            },
            "junction_types": dict(sorted(junction_types.items())),
            "room_face_participation": {
                "yes": room_yes,
                "no": len(wall_rows) - room_yes,
            },
            "paired_face_evidence": {
                "yes": paired_counts.get("yes", 0),
                "no": paired_counts.get("no", 0),
                "unavailable": paired_counts.get(UNAVAILABLE, 0),
            },
            "fill_hatch_evidence": {
                "yes": hatch_excluded,
                "no": 0,
                "unavailable": len(wall_rows),
                "note": (
                    "Per-candidate hatch/fill is unavailable: W4 does not attach "
                    "hatch evidence to WallCandidate. 'yes' counts Stage-A "
                    "segments excluded for hatch-layer metadata."
                ),
            },
            "opening_host_binding": {
                "BOUND": binding_counts.get("BOUND", 0),
                "AMBIGUOUS": binding_counts.get("AMBIGUOUS", 0),
                "UNBOUND": binding_counts.get("UNBOUND", 0),
                "not_evaluated": binding_counts.get(NOT_EVALUATED, 0),
            },
            "evidence_ranking": summarize_ranking(walls),
        },
        "components": components,
        "junctions": [
            {
                "node_id": junction.node_id,
                "position_pt": _round_point(junction.position_pt),
                "junction_type": junction.junction_type.value,
                "incident_wall_candidate_ids": list(junction.incident_wall_candidate_ids),
                "status": junction.status.value,
                "reason_codes": list(junction.reason_codes) if junction.reason_codes else None,
            }
            for junction in sorted(junctions, key=lambda item: item.node_id)
        ],
        "room_faces": [
            {
                "room_ref": room.room_ref,
                "label": room.label or "",
                "polygon_pdf_pts": [_round_point(point) for point in room.polygon_pdf_pts],
                "bounding_wall_candidate_ids": list(room.bounding_wall_candidate_ids),
                "status": room.status.value,
                "floor_area_m2": _round_float(room.floor_area_m2),
            }
            for room in sorted(rooms, key=lambda item: item.room_ref)
        ],
        "wall_candidates": wall_rows,
        "isolated_candidate_ids": isolated_ids,
        "ambiguous_candidate_ids": sorted(set(ambiguous_candidates)),
        "opening_hosts": ambiguous_hosts,
        "highest_connectivity_candidate_ids": [row["candidate_id"] for row in highest_connectivity],
        "longest_candidate_ids": [row["candidate_id"] for row in longest],
        "largest_component_candidate_ids": [row["candidate_id"] for row in largest_component_members],
        "reconciliation": snapshot.reconciliation.to_dict() if snapshot.reconciliation else None,
    }
    return _normalize(report)


def report_to_markdown(report: Mapping[str, Any]) -> str:
    counts = report.get("counts") or {}
    dist = report.get("distributions") or {}
    source = report.get("source") or {}
    length = dist.get("candidate_length_pt") or {}
    lines = [
        "# Wall Topology Diagnostic",
        "",
        f"Document `{source.get('document_id')}` page `{source.get('page_number')}` "
        f"viewport `{source.get('viewport_id') or '(none)'}` "
        f"authority `{source.get('viewport_authority')}`.",
        "",
    ]
    if source.get("fail_closed_reason"):
        lines.extend(
            [
                "## Fail-closed",
                "",
                f"`{source['fail_closed_reason']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Pipeline Counts",
            "",
            f"- raw primitives: `{counts.get('raw_primitives', 0)}`",
            f"- scoped primitives: `{counts.get('scoped_primitives', 0)}`",
            f"- Stage-A edges: `{counts.get('stage_a_edges', 0)}`",
            f"- excluded segments: `{counts.get('excluded_segments', 0)}`",
            f"- WallCandidates: `{counts.get('wall_candidates', 0)}`",
            f"- junctions: `{counts.get('junctions', 0)}`",
            f"- room candidates: `{counts.get('room_candidates', 0)}`",
            f"- opening hosts: `{counts.get('opening_hosts', 0)}`",
            "",
            "## Candidate Length Distribution",
            "",
            f"- min `{length.get('min')}` / max `{length.get('max')}` / mean `{length.get('mean')}` / median `{length.get('median')}`",
            f"- p10 `{length.get('p10')}` p25 `{length.get('p25')}` p50 `{length.get('p50')}` p75 `{length.get('p75')}` p90 `{length.get('p90')}` p95 `{length.get('p95')}`",
            "",
            "## Connected Components",
            "",
            f"- component count: `{counts.get('connected_components', 0)}`",
            f"- isolated candidates: `{counts.get('isolated_candidates', 0)}`",
        ]
    )
    components = report.get("components") or []
    if components:
        largest = components[0]
        lines.append(
            f"- largest component: `{largest.get('component_id')}` size `{largest.get('size')}`"
        )
    lines.extend(["", "## Junction Participation", ""])
    degrees = dist.get("junction_degree") or {}
    lines.append(
        f"- degree 0 `{degrees.get('0', 0)}` / 1 `{degrees.get('1', 0)}` / "
        f"2 `{degrees.get('2', 0)}` / 3+ `{degrees.get('3+', 0)}`"
    )
    types = dist.get("junction_types") or {}
    if types:
        lines.append("- types: " + ", ".join(f"`{name}` `{value}`" for name, value in types.items()))
    room_part = dist.get("room_face_participation") or {}
    paired = dist.get("paired_face_evidence") or {}
    hatch = dist.get("fill_hatch_evidence") or {}
    binding = dist.get("opening_host_binding") or {}
    lines.extend(
        [
            "",
            "## Room-Face Participation",
            "",
            f"- yes `{room_part.get('yes', 0)}` / no `{room_part.get('no', 0)}`",
            "",
            "## Paired-Face Evidence",
            "",
            f"- yes `{paired.get('yes', 0)}` / no `{paired.get('no', 0)}` / unavailable `{paired.get('unavailable', 0)}`",
            "",
            "## Fill/Hatch Evidence",
            "",
            f"- Stage-A hatch-layer exclusions `{hatch.get('yes', 0)}`",
            f"- per-candidate fill/hatch `{hatch.get('unavailable', 0)}` unavailable",
            "",
            "## Opening Host Binding",
            "",
            f"- BOUND `{binding.get('BOUND', 0)}` / AMBIGUOUS `{binding.get('AMBIGUOUS', 0)}` / "
            f"UNBOUND `{binding.get('UNBOUND', 0)}` / not evaluated `{binding.get('not_evaluated', 0)}`",
            "",
            "## Evidence Ranking",
            "",
        ]
    )
    ranking = dist.get("evidence_ranking") or {}
    buckets = ranking.get("buckets") or {}
    signals = ranking.get("signals") or {}
    lines.append(
        "- buckets: "
        + ", ".join(f"`{name}` `{buckets.get(name, 0)}`" for name in (
            "w4_unranked",
            "abstained",
            "candidate_single",
            "candidate_multi",
            "ambiguous",
            "corroborated",
        ))
    )
    lines.append(
        "- signals: "
        + ", ".join(f"`{name}` `{signals.get(name, 0)}`" for name in signals)
    )
    lines.extend(
        [
            "",
            "## Highest-Connectivity Candidates",
            "",
        ]
    )
    high = report.get("highest_connectivity_candidate_ids") or []
    lines.append(", ".join(f"`{item}`" for item in high) if high else "(none)")
    lines.extend(["", "## Isolated Candidates", ""])
    isolated = report.get("isolated_candidate_ids") or []
    lines.append(", ".join(f"`{item}`" for item in isolated) if isolated else "(none)")
    lines.extend(["", "## Ambiguous Candidates", ""])
    ambiguous = report.get("ambiguous_candidate_ids") or []
    lines.append(", ".join(f"`{item}`" for item in ambiguous) if ambiguous else "(none)")
    lines.append("")
    return "\n".join(lines)


def report_to_svg(report: Mapping[str, Any]) -> Optional[str]:
    """Optional overlay. Returns None when no drawable candidate geometry exists."""
    rows = [row for row in report.get("wall_candidates") or [] if row.get("start") and row.get("end")]
    rooms = [room for room in report.get("room_faces") or [] if room.get("polygon_pdf_pts")]
    junctions = [junction for junction in report.get("junctions") or [] if junction.get("position_pt")]
    if not rows:
        return None
    xs: List[float] = []
    ys: List[float] = []
    for row in rows:
        xs.extend([float(row["start"][0]), float(row["end"][0])])
        ys.extend([float(row["start"][1]), float(row["end"][1])])
        if row.get("bbox"):
            xs.extend([float(row["bbox"][0]), float(row["bbox"][2])])
            ys.extend([float(row["bbox"][1]), float(row["bbox"][3])])
    for room in rooms:
        for point in room["polygon_pdf_pts"]:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    for junction in junctions:
        xs.append(float(junction["position_pt"][0]))
        ys.append(float(junction["position_pt"][1]))
    if not xs or not ys:
        return None
    pad = 12.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {min_y} {width} {height}" '
        f'width="{width}" height="{height}" font-family="monospace" font-size="8">',
        "<desc>Read-only wall-topology overlay. Not a classification.</desc>",
    ]
    for room in rooms:
        points = " ".join(f"{point[0]},{point[1]}" for point in room["polygon_pdf_pts"])
        parts.append(
            f'<polygon points="{points}" fill="#4a90d9" fill-opacity="0.08" '
            f'stroke="#4a90d9" stroke-width="0.6" data-room="{room["room_ref"]}"/>'
        )
    for row in rows:
        x1, y1 = row["start"]
        x2, y2 = row["end"]
        color = "#444444"
        if row.get("opening_host_state") == "AMBIGUOUS":
            color = "#b36b00"
        elif row.get("connected_component_size") == 1:
            color = "#888888"
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="1.2" data-candidate="{row["candidate_id"]}" '
            f'data-component="{row.get("connected_component_id") or ""}"/>'
        )
        mid_x = (float(x1) + float(x2)) / 2.0
        mid_y = (float(y1) + float(y2)) / 2.0
        short_id = str(row["candidate_id"])[-8:]
        parts.append(
            f'<text x="{mid_x}" y="{mid_y}" fill="#222222">{short_id}</text>'
        )
    for junction in junctions:
        x, y = junction["position_pt"]
        parts.append(
            f'<circle cx="{x}" cy="{y}" r="2.2" fill="#c0392b" '
            f'data-junction="{junction["node_id"]}" '
            f'data-junction-type="{junction["junction_type"]}"/>'
        )
    for host in report.get("opening_hosts") or []:
        parts.append(
            f'<!-- opening-host {host.get("host_candidate_id")} status={host.get("host_status")} -->'
        )
    parts.append("</svg>")
    return "".join(parts)


def adapt_snapshot_to_canonical_level(snapshot: TopologySnapshot):
    """Call W10 without changing W1-W9 records. Unused by scoring."""
    return adapt_topology_to_canonical_level(
        document_id=snapshot.document_id,
        viewport_id=snapshot.viewport_id,
        walls=snapshot.walls,
        rooms=snapshot.rooms,
        opening_hosts=snapshot.opening_hosts,
    )


def document_id_from_path(path: str | Path) -> str:
    """Stable document label from a basename only — never an absolute path."""
    return Path(path).name


def list_page_viewports(
    page: Any,
    *,
    page_number: int,
    allow_derived: bool = False,
) -> List[Dict[str, Any]]:
    """Deterministic F.07 viewport listing for the CLI. Does not run W2-W10."""
    viewports = segment_page_viewports(page, page_number=page_number)
    rows: List[Dict[str, Any]] = []
    for viewport in sorted(viewports, key=lambda item: item.view_id):
        eligible = (
            viewport.status == ViewportSegmentationStatus.RESOLVED.value
            and viewport.bounding_box is not None
            and viewport.view_type == DrawingViewType.FLOOR_PLAN.value
        )
        if allow_derived and viewport.status == ViewportSegmentationStatus.DERIVED.value:
            eligible = (
                viewport.bounding_box is not None
                and viewport.view_type == DrawingViewType.FLOOR_PLAN.value
            )
        rows.append(
            {
                "view_id": viewport.view_id,
                "page_number": viewport.page_number,
                "view_type": viewport.view_type,
                "label": viewport.label,
                "status": viewport.status,
                "boundary_source": viewport.boundary_source,
                "bounding_box": (
                    [_round_float(float(value)) for value in viewport.bounding_box]
                    if viewport.bounding_box is not None
                    else None
                ),
                "safe_floor_plan": eligible,
            }
        )
    return rows
