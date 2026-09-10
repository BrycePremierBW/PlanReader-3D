"""W5: room-face reconstruction from W4's WallCandidates + Stage-A graph.

Converts:

    WallCandidates (W4) + their contributing Stage-A edges (W2)
    -> closed planar faces (pb_accuracy_v13_engines_v145.extract_planar_faces,
       REUSED UNMODIFIED -- not forked, not edited)
    -> RoomCandidate topology candidates (W1 contract, extended here)

Does NOT:
- compute or emit any quantity / floor area authority (``floor_area_m2`` is
  always ``None`` -- ``area_page_pts2`` is populated, a raw page-space value,
  never confused with a calibrated real-world area);
- emit ``QuantityEvidence``;
- infer a semantic room name/type (``label`` is always ``""`` here -- that is
  W8's job, gated on explicit text evidence, not attempted from geometry
  alone);
- wire into any live extraction path;
- touch benchmark gold, scoring, or tolerances;
- modify ``pb_accuracy_v13_engines_v145.py`` in place (it is shared with
  ``pb_room_face_takeoff.py``, ``pb_opening_production_v175.py``, and
  ``pb_planreader_reconstruction_v139_app.py`` -- calling it, not editing it,
  is the same "wrap, don't fork a shared module" discipline already used for
  ``pb_vector_geometry_v130.snap_geometry``/``detect_wall_pairs`` in W2).

PROVENANCE BACK TO REAL WALL CANDIDATES
-----------------------------------------
``extract_planar_faces`` returns bare point-list polygons with no record of
which input segment contributed which boundary edge. This module rebuilds
that link itself, external to the shared function: every polygon edge is
matched back (by its own two endpoint coordinates, rounded) to the Stage-A
edge that produced it, and that edge's already-known W4
``wall_candidate_id`` (from ``pb_wall_room_topology_wall_assembly.
assemble_wall_candidates``'s own return value) becomes one entry in
``RoomCandidate.bounding_wall_candidate_ids``. A room boundary is never left
keyed only to a raw Stage-A edge id.

OUTER/UNBOUNDED FACE
-----------------------
``extract_planar_faces`` already excludes the unbounded exterior region by
construction (its own positive-signed-area filter keeps only bounded
interior faces, per its docstring and source) -- this module does not need
(and does not add) a second exclusion mechanism for that. What it does add,
reusing the exact concept already proven in ``pb_room_face_takeoff.
filter_face``, is void/hole detection: a face that geometrically contains
another valid face's centroid is flagged ``has_voids=True`` rather than
silently double-counted or silently dropped -- this correctly handles a
disconnected inner enclosure (e.g. a nested WC) that the planar-graph
algorithm has no way to know sits inside a larger, separately-bounded outer
region, since the two are different connected sub-graphs.

AMBIGUITY / FAIL-CLOSED
-------------------------
- A face with any boundary edge that cannot be traced back to a real
  Stage-A edge (should not happen given consistent inputs, but handled
  defensively) is marked ``ABSTAINED`` with a reason code, never silently
  accepted as fully resolved.
- A face whose area is both below an absolute floor and small relative to
  the largest face on the same viewport is flagged ``ABSTAINED`` as a
  "tiny spurious loop" for review, not silently deleted and not silently
  promoted as a real room.
- Duplicate/split/merged vector geometry cannot duplicate a room: this
  module deduplicates coincident edges (reusing W3's own
  ``deduplicate_coincident_edges``, the same pass W4 already applies before
  it) before ever calling ``extract_planar_faces``, and additionally
  deduplicates its own final output by each face's canonical (rotation- and
  direction-invariant) polygon fingerprint, in case two directed traversals
  of the same physical face were not already collapsed by
  ``extract_planar_faces``'s own internal rotation dedup.
"""
from __future__ import annotations

import math
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from pb_accuracy_v13_engines_v145 import extract_planar_faces
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_wall_room_topology_contracts import RoomCandidate
from pb_wall_room_topology_junction_classifier import deduplicate_coincident_edges

# A face this small (in raw PDF point^2) is degenerate regardless of drawing
# scale -- a rounding artifact, not a room. Deliberately tiny and expressed
# in absolute point^2 (not a fraction), since it only exists to reject
# genuinely near-zero-area slivers before the relative check below even
# applies. This is THIS module's own review threshold, applied to whatever
# extract_planar_faces returns -- kept deliberately larger than the value
# actually passed to that function (see _MIN_AREA_PASSED_TO_LIBRARY below),
# so a "tiny spurious loop" is still surfaced as a visible, flagged
# RoomCandidate for review rather than silently discarded before this
# module ever sees it.
ABSOLUTE_DEGENERATE_AREA_PT2 = 1.0

# Passed to extract_planar_faces itself: deliberately much smaller than
# ABSOLUTE_DEGENERATE_AREA_PT2, so that function only discards genuinely
# zero-area artifacts (coincident points, numerical noise), never a face
# this module's own tiny-loop review logic is supposed to have a chance to
# flag and surface.
_MIN_AREA_PASSED_TO_LIBRARY = 1e-6

# A face smaller than this fraction of the LARGEST face on the same viewport
# is flagged for review rather than accepted outright -- a scale-independent,
# relative threshold (matching the same relative-not-absolute pattern already
# used for W3's short-arm demotion), not tuned to any one project's drawing
# scale.
DEFAULT_TINY_RELATIVE_THRESHOLD = 0.01


def _round_pt(point: Tuple[float, float], ndigits: int = 6) -> Tuple[float, float]:
    return (round(point[0], ndigits), round(point[1], ndigits))


def _polygon_area(points: Sequence[Tuple[float, float]]) -> float:
    n = len(points)
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polygon_perimeter_pt(points: Sequence[Tuple[float, float]]) -> float:
    n = len(points)
    return sum(math.dist(points[i], points[(i + 1) % n]) for i in range(n))


def _polygon_centroid(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _point_in_polygon(point: Tuple[float, float], polygon: Sequence[Tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
        ):
            inside = not inside
    return inside


def _canonicalize_polygon(
    points: Sequence[Tuple[float, float]], ndigits: int = 6
) -> Tuple[Tuple[float, float], ...]:
    """Rotation- and direction-invariant fingerprint of a closed polygon.

    Tries every starting vertex in both winding directions and keeps the
    lexicographically smallest resulting sequence -- the standard technique
    for canonical polygon identity, used here so a room's stable id does not
    depend on which vertex/direction the underlying traversal happened to
    start from (which can vary with input segment order).
    """
    rounded = [_round_pt(p, ndigits) for p in points]
    n = len(rounded)
    candidates = []
    for start in range(n):
        forward = tuple(rounded[(start + i) % n] for i in range(n))
        candidates.append(forward)
        backward = tuple(rounded[(start - i) % n] for i in range(n))
        candidates.append(backward)
    return min(candidates)


def _connected_components(graph: Dict[str, Any]) -> Dict[int, int]:
    """Union-find over graph nodes via live edges -> node_idx -> component id."""
    parent: Dict[int, int] = {n["id"]: n["id"] for n in graph["nodes"]}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            parent[hi] = lo

    for edge in graph["edges"]:
        if edge.get("_removed"):
            continue
        union(edge["a"], edge["b"])

    return {node_idx: find(node_idx) for node_idx in parent}


def reconstruct_room_candidates(
    graph: Dict[str, Any],
    edge_id_to_wall_candidate_id: Dict[str, str],
    *,
    document_id: str,
    viewport_id: str,
    source_page: int = 0,
    min_area_pt2: float = ABSOLUTE_DEGENERATE_AREA_PT2,
    tiny_relative_threshold: float = DEFAULT_TINY_RELATIVE_THRESHOLD,
) -> List[RoomCandidate]:
    """Reconstruct room-face candidates for one viewport.

    ``graph`` should be the same Stage-A graph given to
    ``pb_wall_room_topology_junction_classifier.classify_junctions`` and
    ``pb_wall_room_topology_wall_assembly.assemble_wall_candidates`` for this
    viewport; ``edge_id_to_wall_candidate_id`` is that function's own second
    return value.
    """
    graph, _ = deduplicate_coincident_edges(graph)
    live_edges = [e for e in graph["edges"] if not e.get("_removed")]

    edge_lookup: Dict[FrozenSet[Tuple[float, float]], str] = {}
    for edge in live_edges:
        wall_id = edge_id_to_wall_candidate_id.get(str(edge.get("id")))
        if wall_id is None:
            continue
        key = frozenset({_round_pt((edge["x1"], edge["y1"])), _round_pt((edge["x2"], edge["y2"]))})
        edge_lookup[key] = wall_id

    components = _connected_components(graph)
    node_component_by_position: Dict[Tuple[float, float], int] = {
        _round_pt((n["x"], n["y"])): components[n["id"]] for n in graph["nodes"]
    }

    segments = [((e["x1"], e["y1"]), (e["x2"], e["y2"])) for e in live_edges]
    raw_faces = extract_planar_faces(segments, min_area=_MIN_AREA_PASSED_TO_LIBRARY)

    # Deduplicate raw faces by canonical fingerprint before building any
    # RoomCandidate at all -- defensive, in case two directed traversals of
    # the same physical face were not already collapsed upstream.
    seen_fingerprints: set = set()
    unique_faces: List[List[Tuple[float, float]]] = []
    for face in raw_faces:
        fingerprint = _canonicalize_polygon(face)
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        unique_faces.append(face)

    face_areas = [_polygon_area(f) for f in unique_faces]
    largest_area = max(face_areas) if face_areas else 0.0

    prelim: List[Dict[str, Any]] = []
    for face, area in zip(unique_faces, face_areas):
        n = len(face)
        bounding_wall_ids: List[str] = []
        unresolved = False
        for i in range(n):
            p1, p2 = _round_pt(face[i]), _round_pt(face[(i + 1) % n])
            wall_id = edge_lookup.get(frozenset({p1, p2}))
            if wall_id is None:
                unresolved = True
            else:
                bounding_wall_ids.append(wall_id)
        ordered_unique_wall_ids = tuple(dict.fromkeys(bounding_wall_ids))

        component_id = node_component_by_position.get(_round_pt(face[0]))
        prelim.append(
            {
                "polygon": tuple(_round_pt(p) for p in face),
                "area": area,
                "bounding_wall_ids": ordered_unique_wall_ids,
                "unresolved_boundary": unresolved,
                "component_id": component_id,
                "centroid": _polygon_centroid(face),
            }
        )

    # Void detection: a face containing a SMALLER face's centroid. The area
    # comparison (not just centroid containment) matters for concentric
    # geometry: two nested rectangles sharing a centroid would otherwise each
    # appear to "contain" the other's centroid symmetrically, which is
    # geometrically nonsensical -- only the larger of two nested faces can
    # have a void from the smaller one, never the reverse.
    for i, outer in enumerate(prelim):
        outer["has_voids"] = False
        for j, inner in enumerate(prelim):
            if i == j or inner["area"] >= outer["area"]:
                continue
            if _point_in_polygon(inner["centroid"], outer["polygon"]):
                outer["has_voids"] = True
                break

    # Exterior-boundary detection: a wall used by only one identified room is
    # on that room's outer/unshared side.
    wall_usage_count: Dict[str, int] = {}
    for room in prelim:
        for wall_id in room["bounding_wall_ids"]:
            wall_usage_count[wall_id] = wall_usage_count.get(wall_id, 0) + 1

    rooms: List[RoomCandidate] = []
    for room in prelim:
        reason_codes: List[str] = []
        status = EvidenceResolutionStatus.CANDIDATE
        confidence = 0.85

        if room["unresolved_boundary"]:
            status = EvidenceResolutionStatus.ABSTAINED
            reason_codes.append("boundary_segment_not_traced_to_wall_candidate")
            confidence = 0.0

        is_tiny = room["area"] < min_area_pt2 or (
            largest_area > 0 and room["area"] < tiny_relative_threshold * largest_area
        )
        if is_tiny and status != EvidenceResolutionStatus.ABSTAINED:
            status = EvidenceResolutionStatus.ABSTAINED
            reason_codes.append("tiny_spurious_loop_flagged_for_review")
            confidence = 0.1

        exterior_boundary = any(
            wall_usage_count.get(wid, 0) <= 1 for wid in room["bounding_wall_ids"]
        )

        room_ref = stable_contract_id(
            "room",
            {
                "viewport_id": viewport_id,
                "canonical_polygon": _canonicalize_polygon(room["polygon"]),
            },
        )

        rooms.append(
            RoomCandidate(
                room_ref=room_ref,
                document_id=document_id,
                viewport_id=viewport_id,
                label="",
                polygon_pdf_pts=room["polygon"],
                polygon_m=None,
                floor_area_m2=None,
                area_page_pts2=room["area"],
                perimeter_m=None,
                geometry_confidence=confidence,
                evidence=(),
                source_page=source_page,
                drawing_number="",
                scale_source="",
                calibration_confidence=0.0,
                has_voids=room["has_voids"],
                status=status,
                bounding_wall_candidate_ids=room["bounding_wall_ids"],
                exterior_boundary=exterior_boundary,
                building_component_id=(
                    str(room["component_id"]) if room["component_id"] is not None else ""
                ),
                reason_codes=tuple(reason_codes),
            )
        )

    return rooms
