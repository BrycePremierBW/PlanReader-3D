"""Read-only raster opening -> exact source primitive -> W4 owner census.

This diagnostic cannot select a wall host, prove local contact, change a W2/W4
candidate, override equivalence, prove opening universe completeness, publish
a count/quantity, or modify frozen benchmark truth. Original PDF SHA required.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path

from pb_live_physical_net_wall_integration import LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION
from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
from pb_migration_contracts import EvidenceResolutionStatus
from pb_opening_host_binding_authority import (
    _COORD_TOL,
    _RASTER_WHOLE_WALL_CENTER_TOL_PT,
    _authenticated_raster_source_lines,
    _opening_geometry,
    _source_line_axis_data,
)
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT
from pb_wall_room_topology_primitive_lineage import fragment_contained_in_segment
from pb_physical_wall_candidate_authority import (
    MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
    PhysicalWallCandidateSelector,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer


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
            parents = tuple(fragment.source_primitive_ids)
            if any(not isinstance(p, str) or not p.strip() for p in parents):
                raise ValueError("invalid W2 source edge parent inventory")
            # Missing geometry remains unavailable, never an inferred line.
            geometry = getattr(fragment, "geometry", None)
            signature = json.dumps([sorted(set(parents)), geometry], sort_keys=True)
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
        ids = tuple(identity.source_primitive_ids)
        if (any(not isinstance(p, str) or not p.strip() for p in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("invalid W4 source primitive parent inventory")
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
            for parent_id in tuple(fragment.source_primitive_ids):
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
            "source_audit_abstained": True,
            "host_publication_allowed": False,
            "opening_count_publication_allowed": False,
            "metric_quantity_publication_allowed": False,
            "benchmark_accuracy": None,
        }
    authority = composition.physical_opening_authority
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
        lines = _authenticated_raster_source_lines(
            authority, opening, wall.source_observation_ids
        )
        row = nonpublishing_raster_source_w4_membership(
            wall.records, lines, geometry, page_id=page_id,
        )
        opening_rows.append({
            "opening_identity_id": trace.opening_identity_id,
            "representative_source_observation_id": trace.representative_observation_id,
            "original_binding_reason_codes": list(trace.reason_codes),
            "original_g17_support_observation_ids": list(opening.source_observation_ids),
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
