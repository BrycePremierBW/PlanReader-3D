"""Read-only raster opening -> exact source primitive -> W4 owner census.

This diagnostic cannot select a wall host, prove local contact, change a W2/W4
candidate, override equivalence, prove opening universe completeness, publish
a count/quantity, or modify frozen benchmark truth. Original PDF SHA required.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pb_physical_wall_candidate_authority as wall_producer
from pb_live_physical_net_wall_integration import (
    LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION,
)
from pb_live_wall_opening_authority_composition import (
    compose_live_wall_opening_authority,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_opening_host_binding_authority import (
    _COORD_TOL,
    _RASTER_WHOLE_WALL_CENTER_TOL_PT,
    _authenticated_raster_source_lines,
    _opening_geometry,
    _source_line_axis_data,
)
from pb_physical_wall_candidate_authority import (
    MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
    PhysicalWallCandidateSelector,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer
from pb_wall_room_topology_junction_classifier import deduplicate_coincident_edges
from pb_wall_room_topology_primitive_lineage import fragment_contained_in_segment
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT


def _source_parent_inventory(value, label: str) -> tuple[str, ...]:
    if (not isinstance(value, (list, tuple))
            or any(not isinstance(p, str) or not p.strip() for p in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"invalid {label}")
    return tuple(value)


def _finite_coordinates(value, size: int, label: str) -> tuple[float, ...]:
    if (not isinstance(value, (list, tuple)) or len(value) != size
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)):
        raise ValueError(f"invalid {label}")
    try:
        result = tuple(float(v) for v in value)
    except (ValueError, OverflowError):
        raise ValueError(f"invalid {label}") from None
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"nonfinite {label}")
    return result


def nonpublishing_w2_input_scope(segments, published, *, page_id: str) -> dict:
    """Retain the actual graph inputs and the producer snapshot at graph time."""
    scope = {"document_id": published.revision.document_id,
             "revision_id": published.revision.revision_id,
             "source_sha256": published.revision.source_sha256,
             "snapshot_id": published.snapshot.snapshot_id, "page_id": page_id}
    if any(not isinstance(v, str) or not v.strip() for v in scope.values()):
        raise ValueError("invalid W2 input source scope")
    inputs = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise TypeError("invalid W2 input source segment")
        if any(segment.get(k) != scope[k] for k in ("document_id", "page_id")):
            raise ValueError("W2 input source scope mismatch")
        for key in ("id", "viewport_id", "source_observation_id"):
            if not isinstance(segment.get(key), str) or not segment[key].strip():
                raise ValueError("invalid W2 input source address")
        inputs.append({"source_primitive_id": segment["id"],
                       "source_observation_id": segment["source_observation_id"],
                       "viewport_id": segment["viewport_id"],
                       "source_geometry_pt": list(_finite_coordinates(
                           tuple(segment.get(k) for k in ("x1", "y1", "x2", "y2")),
                           4, "W2 input source geometry"))})
    addresses = [row["source_primitive_id"] for row in inputs]
    if len(set(addresses)) != len(addresses):
        raise ValueError("duplicate W2 input source primitive address")
    return {**scope, "input_source_receipts": sorted(inputs, key=lambda r: r["source_primitive_id"]),
            "input_viewport_ids": sorted({r["viewport_id"] for r in inputs}),
            "input_source_scope_observed": bool(inputs),
            "source_ownership_proven": False, "host_publication_allowed": False}


def _validate_aperture_basis(opening) -> None:
    try:
        origin, axis, normal = (tuple(float(v) for v in getattr(opening, name))
                                for name in ("origin", "axis", "normal"))
        length, thickness = float(opening.length), float(opening.thickness)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValueError("invalid source aperture coordinate basis") from None
    if (any(len(v) != 2 for v in (origin, axis, normal))
            or not all(math.isfinite(v) for v in (*origin, *axis, *normal, length, thickness))
            or length <= _COORD_TOL or thickness <= _COORD_TOL
            or abs(math.hypot(*axis) - 1.) > _COORD_TOL
            or abs(math.hypot(*normal) - 1.) > _COORD_TOL
            or abs(sum(a * n for a, n in zip(axis, normal))) > _COORD_TOL):
        raise ValueError("invalid source aperture coordinate basis")


def _finite_source_axis(raw, opening) -> tuple[tuple[float, ...] | None, tuple | None, str | None]:
    try:
        coords = tuple(float(v) for v in raw)
    except (TypeError, ValueError, OverflowError):
        return None, None, "invalid_source_geometry"
    if len(coords) != 4 or any(not math.isfinite(v) for v in coords):
        return None, None, "invalid_source_geometry"
    length = math.dist(coords[:2], coords[2:])
    if not math.isfinite(length) or length <= _COORD_TOL:
        return None, None, "invalid_source_geometry"
    axis = _source_line_axis_data(coords, opening)
    if axis is None:
        return coords, None, "line_not_parallel_to_opening"
    if not all(math.isfinite(v) for v in axis):
        return coords, None, "nonfinite_source_projection"
    return coords, axis, None


def _fragment_geometry_observation(fragment, opening, parent_line) -> dict:
    raw = getattr(fragment, "geometry", None)
    coords, axis, failure = _finite_source_axis(raw, opening)
    result = {"source_edge_id": fragment.edge_id,
              "geometry_disposition": failure or "finite_parallel_fragment_observed",
              "physical_contact_proven": False, "host_publication_allowed": False}
    if coords is not None:
        result["producer_w2_fragment_geometry_pt"] = list(coords)
    if failure:
        return result
    lo, hi, offset = axis
    cross_limit = (opening.thickness / 2. + DEFAULT_GAP_SNAP_TOLERANCE_PT
                   + _RASTER_WHOLE_WALL_CENTER_TOL_PT)
    near_along = (hi >= -DEFAULT_GAP_SNAP_TOLERANCE_PT
                  and lo <= opening.length + DEFAULT_GAP_SNAP_TOLERANCE_PT)
    near_cross = abs(offset) <= cross_limit
    end_distances = [min(abs(lo), abs(hi)),
                     min(abs(lo - opening.length), abs(hi - opening.length))]
    if not all(math.isfinite(value) for value in end_distances):
        result["geometry_disposition"] = "nonfinite_aperture_end_distance"
        return result
    result.update({
        "aperture_axis_span_pt": [lo, hi],
        "aperture_normal_offset_pt": offset,
        "within_aperture_diagnostic_band": near_along and near_cross,
        "axis_interval_overlaps_aperture": hi >= 0. and lo <= opening.length,
        "distance_from_fragment_axis_endpoints_to_aperture_ends_pt": end_distances,
        "source_parent_contains_w2_fragment_geometry": fragment_contained_in_segment(
            (coords[:2], coords[2:]),
            dict(zip(("x1", "y1", "x2", "y2"), parent_line)),
        ),
    })
    return result


def nonpublishing_w2_deduplication_receipts(graph) -> dict:
    """Observe actual W3 snapped-node association without granting sameness.

    The original W2 edges and source parents remain separate. This does not
    attach an excluded parent to the surviving W4 identity or alter the graph.
    """
    if (not isinstance(graph, Mapping)
            or not isinstance(graph.get("nodes"), (list, tuple))
            or not isinstance(graph.get("edges"), (list, tuple))):
        raise TypeError("invalid W2 deduplication graph inventory")
    nodes = {}
    for node in graph["nodes"]:
        if not isinstance(node, Mapping):
            raise TypeError("invalid W2 deduplication node inventory")
        nid = node.get("id")
        if type(nid) is not int or nid in nodes:
            raise ValueError("invalid W2 deduplication node address")
        position = _finite_coordinates((node.get("x"), node.get("y")), 2, "W2 deduplication node geometry")
        nodes[nid] = position

    edges = {}
    for edge in graph["edges"]:
        if not isinstance(edge, Mapping):
            raise TypeError("invalid W2 deduplication edge inventory")
        eid = edge.get("id")
        if not isinstance(eid, str) or not eid.strip() or eid in edges:
            raise ValueError("invalid W2 deduplication edge address")
        pair = (edge.get("a"), edge.get("b"))
        if (any(type(nid) is not int or nid not in nodes for nid in pair)
                or pair[0] == pair[1]):
            raise ValueError("invalid W2 deduplication edge endpoints")
        lineage = edge.get("primitive_lineage")
        if lineage is None:
            lineage = {}
        if not isinstance(lineage, Mapping):
            raise TypeError("invalid W2 deduplication source lineage")
        parents = _source_parent_inventory(lineage.get("source_primitive_ids", ()), "W2 deduplication source parent inventory")
        geometry = _finite_coordinates(tuple(edge.get(k) for k in ("x1", "y1", "x2", "y2")), 4, "W2 deduplication edge geometry")
        edges[eid] = {
            "source_edge_id": eid,
            "source_primitive_ids": list(parents),
            "producer_w2_edge_geometry_pt": list(geometry),
            "snapped_node_ids": list(pair),
            "snapped_endpoint_geometry_pt": [list(nodes[nid]) for nid in pair],
        }

    # Replay the exact existing production helper. It returns a new graph and
    # does not change the original edges, their lineage or snapped nodes.
    retained, removed = deduplicate_coincident_edges(graph)
    retained_by_pair = {
        frozenset((edge["a"], edge["b"])): edge["id"]
        for edge in retained["edges"]
    }
    rows = []
    for eid in removed:
        removed_receipt = edges[eid]
        kept_id = retained_by_pair[frozenset(removed_receipt["snapped_node_ids"])]
        rows.append({
            "removed_w2_edge": removed_receipt,
            "retained_w2_edge": edges[kept_id],
            "association_basis": "same_actual_snapped_node_pair",
            "source_parents_transferred_to_w4": False,
            "physical_equivalence_proven": False,
            "host_publication_allowed": False,
        })
    return {
        "original_w2_edge_count": len(graph["edges"]),
        "retained_w3_edge_count": len(retained["edges"]),
        "removed_w2_edge_count": len(removed),
        "all_w2_edge_receipts": [
            {**edges[eid], "w3_disposition": "REMOVED_SNAPPED_NODE_DUPLICATE" if eid in removed
             else "RETAINED", "source_parents_transferred_to_w4": False}
            for eid in sorted(edges)
        ],
        "removed_edge_receipts": sorted(rows, key=lambda row: row["removed_w2_edge"]["source_edge_id"]),
        "source_parents_transferred_to_w4": False,
        "physical_equivalence_proven": False,
        "host_publication_allowed": False,
    }


def nonpublishing_w2_w4_edge_membership(census, records) -> dict:
    """Retain every actual W4 sidecar alternative without assigning its owner."""
    records = tuple(records)
    if any(not isinstance(r.wall_candidate_id, str) or not r.wall_candidate_id.strip() for r in records):
        raise ValueError("invalid W4 candidate address")
    counts = Counter(r.wall_candidate_id for r in records)
    fragments_by_edge = defaultdict(list)
    for record in records:
        for fragment in record.source_edge_fragments:
            if not isinstance(fragment.edge_id, str) or not fragment.edge_id.strip():
                raise ValueError("invalid W4 source edge address")
            parents = _source_parent_inventory(fragment.source_primitive_ids, "W4 edge parent inventory")
            identity_parents = _source_parent_inventory(
                record.physical_identity.source_primitive_ids, "W4 source primitive parent inventory")
            geometry = getattr(fragment, "geometry", None)
            fragments_by_edge[fragment.edge_id].append({
                "wall_candidate_id": record.wall_candidate_id,
                "w4_identity_usable": bool(record.physical_identity.usable),
                "candidate_address_quarantined": counts[record.wall_candidate_id] != 1,
                "source_primitive_ids": list(parents),
                "producer_w4_source_edge_geometry_pt": list(_finite_coordinates(
                    geometry, 4, "W4 source edge geometry")) if geometry is not None else None,
                "edge_parents_in_w4_identity": set(parents).issubset(identity_parents),
                "physical_equivalence_proven": False, "host_publication_allowed": False,
            })
    conflicted_edges = {eid for eid, fragments in fragments_by_edge.items()
        if len({json.dumps([sorted(f["source_primitive_ids"]), f["producer_w4_source_edge_geometry_pt"]])
                for f in fragments}) > 1}
    rows = []
    for edge in census["all_w2_edge_receipts"]:
        alternatives = []
        for fragment in fragments_by_edge.get(edge["source_edge_id"], ()):
            exact = (sorted(fragment["source_primitive_ids"]) == sorted(edge["source_primitive_ids"])
                     and fragment["producer_w4_source_edge_geometry_pt"] == edge["producer_w2_edge_geometry_pt"])
            alternatives.append({**fragment, "exact_w2_sidecar_receipt_match": exact,
                                 "source_edge_address_conflicted": edge["source_edge_id"] in conflicted_edges,
                                 "w4_membership_receipt_usable": exact
                                 and edge["source_edge_id"] not in conflicted_edges
                                 and fragment["w4_identity_usable"]
                                 and fragment["edge_parents_in_w4_identity"]
                                 and not fragment["candidate_address_quarantined"]
                                 and edge["w3_disposition"] == "RETAINED"})
        rows.append({**edge, "actual_w4_edge_membership_alternatives": sorted(
            alternatives, key=lambda item: (item["wall_candidate_id"], json.dumps(item, sort_keys=True))),
            "physical_equivalence_proven": False, "host_publication_allowed": False})
    return {**census, "all_w2_edge_receipts": rows}


def nonpublishing_w2_parent_stage_receipts(census) -> dict:
    """A removed edge is not a lost parent if another edge retains that parent."""
    by_parent = defaultdict(list)
    for edge in census["all_w2_edge_receipts"]:
        for parent in edge["source_primitive_ids"]:
            by_parent[parent].append(edge)
    rows = []
    for parent, edges in sorted(by_parent.items()):
        retained = sorted(e["source_edge_id"] for e in edges if e["w3_disposition"] == "RETAINED")
        removed = sorted(e["source_edge_id"] for e in edges if e["w3_disposition"] != "RETAINED")
        memberships = sorted((e["source_edge_id"], a["wall_candidate_id"])
            for e in edges for a in e["actual_w4_edge_membership_alternatives"]
            if a["w4_membership_receipt_usable"])
        disposition = ("USABLE_W4_EDGE_MEMBERSHIP_OBSERVED" if memberships
                       else "W3_PARENT_RETAINED_NO_USABLE_W4_EDGE_MEMBERSHIP" if retained
                       else "W2_PARENT_ONLY_REMOVED_EDGES")
        rows.append({"source_primitive_id": parent,
                     "retained_w3_source_edge_ids": retained, "removed_w2_source_edge_ids": removed,
                     "actual_usable_w4_edge_memberships": [
                         {"source_edge_id": eid, "wall_candidate_id": cid} for eid, cid in memberships],
                     "source_ancestry_disposition": disposition,
                     "source_parent_removed_from_entire_w3_inventory": not retained,
                     "source_parents_transferred_to_w4": False, "host_publication_allowed": False})
    return {**census, "source_parent_stage_receipts": rows,
            "w2_edges_with_unknown_parent_inventory": sorted(e["source_edge_id"]
                for e in census["all_w2_edge_receipts"] if not e["source_primitive_ids"])}


def nonpublishing_support_projection(raw, opening) -> dict:
    """Signed coordinates for both faces and ends; no contact classification."""
    _validate_aperture_basis(opening)
    try:
        coords = _finite_coordinates(raw, 4, "G17 source support geometry")
    except ValueError:
        return {"geometry_disposition": "invalid_source_support_geometry",
                "physical_contact_proven": False, "host_publication_allowed": False}
    result = {"original_source_support_geometry_pt": list(coords),
              "physical_contact_proven": False, "host_publication_allowed": False}
    length = math.dist(coords[:2], coords[2:])
    if not math.isfinite(length) or length <= _COORD_TOL:
        return {**result, "geometry_disposition": "invalid_source_support_segment_length"}
    points = [(coords[i] - opening.origin[0], coords[i+1] - opening.origin[1]) for i in (0, 2)]
    axis = [sum(v * a for v, a in zip(p, opening.axis)) for p in points]
    normal = [sum(v * n for v, n in zip(p, opening.normal)) for p in points]
    if not all(math.isfinite(v) for v in (*axis, *normal)):
        return {**result, "geometry_disposition": "nonfinite_source_support_projection"}
    return {**result, "geometry_disposition": "finite_signed_support_projection_observed",
            "signed_aperture_axis_coordinates_pt": axis,
            "signed_aperture_normal_coordinates_pt": normal}


def nonpublishing_g17_support_receipts(authority, opening, geometry) -> list[dict]:
    """Resolve each requested support through the existing sealed G17 reader."""
    ids = _source_parent_inventory(opening.source_observation_ids, "G17 support observation inventory")
    visibility = authority.source_visibility_authority()
    rows = []
    for oid in sorted(ids):
        selector = ObservationSelector(document_id=opening.document_id,
            revision_id=opening.revision_id, source_sha256=opening.source_sha256,
            snapshot_id=opening.snapshot_id, observation_id=oid)
        resolved = visibility.resolve_raster_opening_primitive(selector)
        observation = resolved.observation
        row = {"requested_source_observation_id": oid,
               "resolution_status": resolved.status.value,
               "original_resolution_reason_codes": list(resolved.reason_codes),
               "source_receipt_authenticated": False, "physical_contact_proven": False,
               "host_publication_allowed": False}
        if resolved.status is not EvidenceResolutionStatus.CORROBORATED or observation is None:
            rows.append(row)
            continue
        if (any(getattr(observation, k, None) != getattr(selector, k)
                for k in ("document_id", "revision_id", "source_sha256", "snapshot_id", "observation_id"))
                or observation.page_id != opening.page_id or observation.viewport_id is not None
                or observation.observation_kind not in ("raster_wall_band_face", "raster_wall_band_end")):
            rows.append({**row, "diagnostic_rejection_reason": "G17_support_source_scope_mismatch"})
            continue
        rows.append({**row, "source_receipt_authenticated": True,
                     "document_id": observation.document_id, "revision_id": observation.revision_id,
                     "source_sha256": observation.source_sha256, "snapshot_id": observation.snapshot_id,
                     "page_id": observation.page_id, "viewport_id": observation.viewport_id,
                     "source_observation_id": observation.observation_id,
                     "observation_kind": observation.observation_kind,
                     "source_primitive_ref": observation.source_primitive_ref,
                     "derivation_parent_ids": list(observation.derivation_parent_ids),
                     "observation_payload_sha256": observation.observation_payload_sha256,
                     **nonpublishing_support_projection(observation.geometry, geometry)})
    return rows


class DiagnosticRasterLineCache:
    """Run-local immutable reuse, scoped to this authority and exact selectors."""

    def __init__(self):
        self._entries = {}

    def resolve(self, authority, opening, observation_ids, *, published):
        ids = _source_parent_inventory(observation_ids, "raster line observation inventory")
        scope = tuple(getattr(opening, k) for k in (
            "document_id", "revision_id", "source_sha256", "snapshot_id", "page_id", "viewport_id"))
        if (any(not isinstance(v, str) or not v.strip() for v in scope[:-1])
                or (scope[-1] is not None and (not isinstance(scope[-1], str) or not scope[-1].strip()))):
            raise ValueError("incomplete raster line source cache scope")
        if scope[:4] != (published.revision.document_id, published.revision.revision_id,
                         published.revision.source_sha256, published.snapshot.snapshot_id):
            raise ValueError("raster line cache published source scope mismatch")
        # Revalidate the producer-owned snapshot before any warm-cache reuse.
        # Replaced records, parent receipts and corrupted source bytes cannot
        # become positive diagnostic evidence through a stale cached mapping.
        authenticated = authority.source_visibility_authority().authenticated_visible_observations(published)
        manifest = tuple(sorted((oid, observation.observation_payload_sha256)
                                for oid, observation in authenticated))
        # Keep the authority object alive in the key, not a reusable numeric id.
        key = (authority, scope, tuple(sorted(ids)), manifest)
        if key not in self._entries:
            lines = _authenticated_raster_source_lines(authority, opening, ids)
            self._entries[key] = MappingProxyType({sid: tuple(coords) for sid, coords in lines.items()})
        return self._entries[key]


def nonpublishing_raster_source_w4_membership(
    records, source_lines_by_primitive, opening_geometry, *, page_id: str
) -> dict:
    """Audit shared authentic primitive references without asserting a host.

    Evidence that one source raster primitive is a W4 parent is not proof
    that its W4 chain touches a G17 aperture end. Even exact parent IDs can
    occur on remote fragments of a long source line, so keep all candidate
    rows and never return a chosen host.
    """
    _validate_aperture_basis(opening_geometry)
    records = tuple(records)
    candidate_rows = defaultdict(list)
    edge_receipts = defaultdict(set)
    for record in records:
        cid = record.wall_candidate_id
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError("missing W4 source candidate address")
        candidate_rows[cid].append(record)
        for fragment in getattr(record, "source_edge_fragments", ()):
            if not isinstance(fragment.edge_id, str) or not fragment.edge_id.strip():
                raise ValueError("missing W2 source edge identity (address)")
            parents = _source_parent_inventory(fragment.source_primitive_ids, "W2 source edge parent inventory")
            # Missing geometry remains unavailable, never an inferred line.
            geometry = getattr(fragment, "geometry", None)
            signature = json.dumps([sorted(parents), geometry], sort_keys=True)
            edge_receipts[fragment.edge_id].add(signature)
    collided_candidates = {cid for cid, rows in candidate_rows.items() if len(rows) > 1}
    conflicted_edges = {eid for eid, receipts in edge_receipts.items() if len(receipts) > 1}
    owners_by_source = defaultdict(set)
    source_edges_by_parent = defaultdict(set)
    source_edge_fragments = {}
    snap_losses_by_parent = defaultdict(list)
    contradictory_source_edge_parent_receipts = set()
    skipped_nonusable = set()
    for r in records:
        identity = r.physical_identity
        ids = _source_parent_inventory(identity.source_primitive_ids, "W4 source primitive parent inventory")
        if r.wall_candidate_id in collided_candidates:
            continue
        if not identity.usable:
            skipped_nonusable.update(ids)
            continue
        for source_id in ids:
            owners_by_source[source_id].add(str(r.wall_candidate_id))
        for fragment in getattr(r, "source_snap_collapsed_fragments", ()):
            if (not isinstance(fragment.edge_id, str) or not fragment.edge_id.strip()
                    or fragment.edge_id in edge_receipts):
                raise ValueError("source snap-loss receipt has a missing or surviving W2 edge identity")
            parents = _source_parent_inventory(fragment.source_primitive_ids, "source snap-loss parent inventory")
            if not parents:
                raise ValueError("source snap-loss parent inventory unavailable")
            for parent_id in parents:
                if (not isinstance(parent_id, str) or not parent_id.strip()
                        or parent_id not in ids):
                    raise ValueError("source snap-loss receipt contradicts W4 parent inventory")
                snap_losses_by_parent[parent_id].append((r.wall_candidate_id, fragment))
        # W4's sealed source-edge fragments are the actual W2 sidecars, not
        # arbitrary candidate-line geometry or an inferred physical host.
        # Record exact parent+edge links, retaining every shared owner.
        for fragment in getattr(r, "source_edge_fragments", ()):
            edge_id = str(fragment.edge_id)
            if edge_id in conflicted_edges:
                continue
            for parent_id in tuple(fragment.source_primitive_ids):
                if not isinstance(parent_id, str) or not parent_id:
                    continue
                if parent_id not in ids:
                    # A W2 source-edge receipt which contradicts its own W4
                    # source parent inventory is a lineage defect, not an
                    # additional source-authorised candidate for this flank.
                    contradictory_source_edge_parent_receipts.add(
                        (str(r.wall_candidate_id), edge_id, parent_id)
                    )
                    continue
                source_edges_by_parent[parent_id].add(
                    (str(r.wall_candidate_id), edge_id)
                )
                source_edge_fragments[(r.wall_candidate_id, edge_id)] = fragment

    evidence_rows = []
    reasons = Counter()
    for sid, raw in sorted(source_lines_by_primitive.items()):
        coords, axis, failure = _finite_source_axis(raw, opening_geometry)
        if failure:
            reasons[failure] += 1
            continue
        lo, hi, offset = axis
        # Only geometry-local *diagnostic* candidates. Source identity + axis
        # overlap does not prove physical host, gap closure or equivalence.
        # Follow W2's existing endpoint snap and the source raster render
        # tolerance; do not invent another physical closure tolerance.
        local_along = DEFAULT_GAP_SNAP_TOLERANCE_PT
        local_cross = (
            opening_geometry.thickness / 2.0
            + DEFAULT_GAP_SNAP_TOLERANCE_PT
            + _RASTER_WHOLE_WALL_CENTER_TOL_PT
        )
        if (hi < -local_along
                or lo > opening_geometry.length + local_along
                or abs(offset) > local_cross):
            reasons["line_outside_aperture_local_band"] += 1
            continue
        owners = sorted(owners_by_source.get(sid, ()))
        edge_geometry_rows = [
            {"wall_candidate_id": owner_id,
             **_fragment_geometry_observation(
                 source_edge_fragments[(owner_id, edge_id)], opening_geometry, coords)}
            for owner_id, edge_id in sorted(source_edges_by_parent.get(sid, ()))
            if owner_id in owners
        ]
        snap_loss_rows = [
            {"associated_w4_candidate_id": cid,
             **_fragment_geometry_observation(fragment, opening_geometry, coords),
             "w2_disposition": "SNAP_COLLAPSED_NOT_SURVIVING_EDGE",
             "producer_disappearance_reason": getattr(fragment, "reason_code", None),
             "surviving_w2_edge": False,
             "wall_continuity_proven": False}
            for cid, fragment in sorted(snap_losses_by_parent.get(sid, ()),
                key=lambda item: (item[0], item[1].edge_id))
        ]
        reasons["local_positive_source_with_w4_ancestry" if owners
                else "local_source_without_usable_w4_ancestry"] += 1
        evidence_rows.append({
            "source_primitive_id": sid,
            "original_source_line_pt": list(coords),
            "opening_axis_span_pt": [lo, hi],
            "opening_normal_offset_pt": offset,
            "exact_positive_ancestry_w4_candidate_ids": owners,
            "actual_w2_source_edges_by_w4_candidate": [
                {"wall_candidate_id": owner_id, "source_edge_id": edge_id}
                for owner_id, edge_id in sorted(source_edges_by_parent.get(sid, ()))
                if owner_id in owners
            ],
            "w2_source_fragment_geometry_by_w4_candidate": edge_geometry_rows,
            "w2_snap_loss_geometry_by_associated_w4_candidate": snap_loss_rows,
            "locally_authenticated_host": False,
        })

    return {
        "page_id": str(page_id),
        "quarantined_w4_candidate_addresses": [
            {"wall_candidate_id": cid, "source_record_count": len(candidate_rows[cid]),
             "source_parent_ids_by_record": sorted(
                 sorted(set(r.physical_identity.source_primitive_ids))
                 for r in candidate_rows[cid]
             )}
            for cid in sorted(collided_candidates)
        ],
        "conflicting_w2_source_edge_addresses": sorted(conflicted_edges),
        "diagnostic_local_raster_lines": evidence_rows,
        "original_source_stage_counts": dict(sorted(reasons.items())),
        "unusable_identity_source_parent_count": len(skipped_nonusable),
        "source_edge_parent_identity_contradictions": [
            {
                "wall_candidate_id": wall_id,
                "source_edge_id": edge_id,
                "unowned_source_parent_id": parent_id,
            }
            for wall_id, edge_id, parent_id in sorted(
                contradictory_source_edge_parent_receipts
            )
        ],
        "source_edge_parent_identity_contradiction_count": len(
            contradictory_source_edge_parent_receipts
        ),
        "w4_identity_count": len(records),
        "candidate_ancestry_only": True,
        "local_host_contact_proven": False,
        "physical_equivalence_proven": False,
        "host_publication_allowed": False,
        "opening_count_publication_allowed": False,
        "metric_quantity_publication_allowed": False,
        "benchmark_accuracy": None,
    }


def original_raster_host_ancestry_census(
    source_bytes: bytes, *, page_id: str, expected_source_sha: str
) -> dict:
    digest = sha256(source_bytes).hexdigest()
    if digest != expected_source_sha:
        raise ValueError("original raster source PDF SHA-256 mismatch")
    if not page_id.isdigit() or int(page_id) < 1:
        raise ValueError("invalid page for original source")
    producer = SourceVisibilityProducer(
        producer_method="live-physical-net-wall",
        producer_version=LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION,
    )
    source = producer.ingest_native_pdf_bytes(
        document_id=f"live-source:{digest[:32]}",
        source_bytes=source_bytes,
        source_locator="memory://live-physical-net-wall-source.pdf",
        page_ids=(page_id,),
    )
    w2_deduplication_censuses = []
    build_graph = wall_producer.build_wall_graph_for_viewport

    def observe_actual_w2_graph(segments, **kwargs):
        observed = producer.published_snapshot_for_revision(source.revision.revision_id)
        if observed is None:
            raise ValueError("W2 graph-time producer snapshot missing")
        scope = nonpublishing_w2_input_scope(segments, observed, page_id=page_id)
        graph = build_graph(segments, **kwargs)
        census = nonpublishing_w2_deduplication_receipts(graph)
        census["source_scope_at_graph_time"] = scope
        w2_deduplication_censuses.append(census)
        return graph

    with patch.object(wall_producer, "build_wall_graph_for_viewport", observe_actual_w2_graph):
        composition = compose_live_wall_opening_authority(
            source_visibility_producer=producer,
            revision_id=source.revision.revision_id,
            page_ids=(page_id,),
        )
    published = producer.published_snapshot_for_revision(source.revision.revision_id)
    if published is None:
        raise ValueError("original raster source snapshot missing")
    wall = composition.physical_wall_candidate_authority.resolve_scope(
        PhysicalWallCandidateSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            page_id=page_id,
            decision_scope_id=f"wall-source:page-{page_id}",
        )
    )
    if not wall.scope_complete or wall.equivalence is None:
        return {
            "source_sha256": digest, "page_id": page_id,
            "wall_scope_status": str(wall.status.value),
            "wall_scope_complete": False,
            "opening_rows": [],
            "source_w2_deduplication_censuses": w2_deduplication_censuses,
            "source_audit_abstained": True,
            "host_publication_allowed": False,
            "opening_count_publication_allowed": False,
            "metric_quantity_publication_allowed": False,
            "benchmark_accuracy": None,
        }
    authority = composition.physical_opening_authority
    w2_deduplication_censuses = [nonpublishing_w2_parent_stage_receipts(
        nonpublishing_w2_w4_edge_membership(census, wall.records))
        for census in w2_deduplication_censuses]
    line_cache = DiagnosticRasterLineCache()
    opening_rows = []
    for trace in composition.opening_bindings:
        if trace.host_wall_id or trace.page_id != page_id:
            continue
        if not any("raster_source_band_" in str(r) for r in trace.reason_codes):
            continue
        result = authority.prove_existence(ObservationSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            observation_id=trace.representative_observation_id,
        ))
        opening = result.existence_record
        if result.status is not EvidenceResolutionStatus.CORROBORATED or opening is None:
            continue
        geometry = _opening_geometry(authority, opening)
        if geometry is None:
            continue
        lines = line_cache.resolve(authority, opening, wall.source_observation_ids, published=published)
        row = nonpublishing_raster_source_w4_membership(
            wall.records, lines, geometry, page_id=page_id,
        )
        opening_rows.append({
            "opening_identity_id": trace.opening_identity_id,
            "representative_source_observation_id": trace.representative_observation_id,
            "original_binding_reason_codes": list(trace.reason_codes),
            "original_g17_support_observation_ids": list(opening.source_observation_ids),
            "original_g17_support_receipts": nonpublishing_g17_support_receipts(authority, opening, geometry),
            "original_aperture_coordinate_basis": asdict(geometry),
            "source_w4_ancestry_audit": row,
        })
    return {
        "source_sha256": digest,
        "page_id": page_id,
        "selected_geometry_page_ids": [page_id],
        "primitive_safety_cap": MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
        "revision_id": published.revision.revision_id,
        "snapshot_id": published.snapshot.snapshot_id,
        # Retain exact real producer receipts for the existing strict original
        # opening/host/frame comparator. Tally equality alone is insufficient.
        "opening_bindings": json.loads(json.dumps(
            [asdict(trace) for trace in composition.opening_bindings],
            default=lambda value: value.value,
        )),
        "host_frames": json.loads(json.dumps(
            [asdict(trace) for trace in composition.host_frames],
            default=lambda value: value.value,
        )),
        "source_original_opening_count": len(composition.opening_bindings),
        "source_original_host_count": sum(
            bool(t.host_wall_id) for t in composition.opening_bindings
        ),
        # The composition retains ABSTAIN frame attempts as negative evidence.
        # Their presence is not an authenticated frame receipt.
        "source_original_frame_count": sum(
            bool(t.record_id) for t in composition.host_frames
        ),
        "source_original_frame_trace_count": len(composition.host_frames),
        "source_w2_deduplication_censuses": w2_deduplication_censuses,
        "wall_scope_complete": True,
        "opening_rows": sorted(opening_rows, key=lambda x:x["opening_identity_id"]),
        "source_audit_abstained": False,
        "host_publication_allowed": False,
        "opening_count_publication_allowed": False,
        "metric_quantity_publication_allowed": False,
        "benchmark_accuracy": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = original_raster_host_ancestry_census(
        args.pdf.read_bytes(), page_id=args.page_id,
        expected_source_sha=args.expected_source_sha,
    )
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+"\n")
    print(json.dumps({
        "source_sha256": report["source_sha256"],
        "page_id": args.page_id,
        "opening_rows": len(report["opening_rows"]),
        "host_publication_allowed": False,
    },sort_keys=True))


if __name__ == "__main__":
    main()
