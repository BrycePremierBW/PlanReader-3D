"""Read-only raster opening -> exact source primitive -> W4 owner census.

This diagnostic cannot select a wall host, prove local contact, change a W2/W4
candidate, override equivalence, prove opening universe completeness, publish
a count/quantity, or modify frozen benchmark truth. Original PDF SHA required.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path

from pb_live_physical_net_wall_integration import LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION
from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
from pb_migration_contracts import EvidenceResolutionStatus
from pb_opening_host_binding_authority import (
    _RASTER_WHOLE_WALL_CENTER_TOL_PT,
    _authenticated_raster_source_lines,
    _opening_geometry,
    _source_line_axis_data,
)
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT
from pb_physical_wall_candidate_authority import PhysicalWallCandidateSelector
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer


def nonpublishing_raster_source_w4_membership(
    records, source_lines_by_primitive, opening_geometry, *, page_id: str
) -> dict:
    """Audit shared authentic primitive references without asserting a host.

    Evidence that one source raster primitive is a W4 parent is not proof
    that its W4 chain touches a G17 aperture end. Even exact parent IDs can
    occur on remote fragments of a long source line, so keep all candidate
    rows and never return a chosen host.
    """
    owners_by_source = defaultdict(set)
    source_edges_by_parent = defaultdict(set)
    contradictory_source_edge_parent_receipts = set()
    skipped_nonusable = set()
    for r in records:
        identity = r.physical_identity
        raw_ids = tuple(identity.source_primitive_ids)
        if (
            any(not isinstance(parent, str) or not parent.strip() for parent in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)
        ):
            raise ValueError("invalid W4 source primitive parent inventory")
        ids = raw_ids
        if (not isinstance(r.wall_candidate_id, str)
                or not r.wall_candidate_id.strip()):
            raise ValueError("missing W4 source candidate identity")
        if not identity.usable:
            skipped_nonusable.update(ids)
            continue
        for source_id in ids:
            owners_by_source[source_id].add(str(r.wall_candidate_id))
        # W4's sealed source-edge fragments are the actual W2 sidecars, not
        # arbitrary candidate-line geometry or an inferred physical host.
        # Record exact parent+edge links, retaining every shared owner.
        for fragment in getattr(r, "source_edge_fragments", ()):
            edge_id = fragment.edge_id
            if not isinstance(edge_id, str) or not edge_id.strip():
                raise ValueError("missing W2 source edge identity")
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

    evidence_rows = []
    reasons = Counter()
    for sid, raw in sorted(source_lines_by_primitive.items()):
        try:
            coords = tuple(float(v) for v in raw)
        except (TypeError, ValueError, OverflowError):
            reasons["invalid_source_geometry"] += 1
            continue
        if len(coords) != 4 or any(not math.isfinite(v) for v in coords):
            reasons["invalid_source_geometry"] += 1
            continue
        axis = _source_line_axis_data(coords, opening_geometry)
        if axis is None:
            reasons["line_not_parallel_to_opening"] += 1
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
            "locally_authenticated_host": False,
        })

    return {
        "page_id": str(page_id),
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
        "source_original_opening_count": len(composition.opening_bindings),
        "source_original_host_count": sum(
            bool(t.host_wall_id) for t in composition.opening_bindings
        ),
        "source_original_frame_count": len(composition.host_frames),
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
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2)+"\n")
    print(json.dumps({
        "source_sha256": report["source_sha256"],
        "page_id": args.page_id,
        "opening_rows": len(report["opening_rows"]),
        "host_publication_allowed": False,
    },sort_keys=True))


if __name__ == "__main__":
    main()
