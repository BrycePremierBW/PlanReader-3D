"""Read-only physical-opening four-face → W2/W4 first failure census.

Runs the original source producer unchanged. A stage observation never
establishes wall equivalence, a host, a complete count or a quantity.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from pb_live_physical_net_wall_integration import LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION
from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
from pb_migration_contracts import EvidenceResolutionStatus
from pb_physical_opening_authority import JAMB_BOUNDED_TWO_FACE_INTERRUPTION
from pb_physical_wall_candidate_authority import (
    PhysicalWallCandidateSelector,
    _filter_proven_wall_strip_geometry,
    _filter_repeated_non_physical_drafting_primitives,
    _opening_raw_relation_sets,
    _proven_filled_wall_strips,
    _source_page_segments,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import (
    NATIVE_PDF_VISIBLE_SEGMENT,
    RASTER_PDF_VISIBLE_SEGMENT,
    SourceVisibilityProducer,
)
from pb_wall_room_topology_primitive_lineage import LINEAGE_KEY
from pb_wall_room_topology_stage_a import (
    build_wall_graph_for_viewport,
    is_structural_candidate_segment,
)



def state(value):
    return str(getattr(value, "value", value))


def raw_id_for_observation(observation):
    ref = str(observation.source_primitive_ref or "")
    if observation.observation_kind == NATIVE_PDF_VISIBLE_SEGMENT:
        prefix = "visible:segment:"
        return ref[len(prefix):] if ref.startswith(prefix) else None
    if observation.observation_kind == RASTER_PDF_VISIBLE_SEGMENT:
        prefix = "visible:"
        return ref[len(prefix):] if ref.startswith(prefix) else None
    return None


def edge_lineage_raw_ids(graph):
    by_raw = defaultdict(list)
    for edge in tuple(graph.get("edges") or ()):
        lineage = edge.get(LINEAGE_KEY) or {}
        for raw_id in tuple(lineage.get("source_primitive_ids") or ()):
            by_raw[str(raw_id)].append(str(edge.get("id") or ""))
    return by_raw


def source_face_stage_audit(source_bytes: bytes, *, page_id: str,
                            expected_source_sha: str | None = None) -> dict:
    """Source-authenticated, nonpublishing first-failure census for one page."""
    if not isinstance(page_id, str) or not page_id.isdigit() or int(page_id) < 1:
        raise ValueError("invalid original source page")
    actual = hashlib.sha256(source_bytes).hexdigest()
    if expected_source_sha is not None and actual != expected_source_sha:
        raise ValueError("original source SHA-256 mismatch")
    scope_id = f"wall-source:page-{page_id}"

    source = SourceVisibilityProducer(
        producer_method="live-physical-net-wall",
        producer_version=LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION,
    )
    initial = source.ingest_native_pdf_bytes(
        document_id=f"live-source:{actual[:32]}",
        source_bytes=source_bytes,
        source_locator="memory://live-physical-net-wall-source.pdf",
        page_ids=(page_id,),
    )
    composition = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=initial.revision.revision_id,
        page_ids=(page_id,),
    )
    current = source.published_snapshot_for_revision(initial.revision.revision_id)
    assert current is not None

    wall_result = composition.physical_wall_candidate_authority.resolve_scope(
        PhysicalWallCandidateSelector(
            document_id=current.revision.document_id,
            revision_id=current.revision.revision_id,
            source_sha256=current.revision.source_sha256,
            snapshot_id=current.snapshot.snapshot_id,
            page_id=page_id,
            decision_scope_id=scope_id,
        )
    )

    segments, _, page_width, page_height = _source_page_segments(
        source_producer=source,
        published=current,
        source_bytes=source_bytes,
        page_id=page_id,
        decision_scope_id=scope_id,
    )
    raw_segment = {str(s.get("id") or ""): s for s in segments if str(s.get("id") or "")}
    motif_filtered = _filter_repeated_non_physical_drafting_primitives(
        segments,
        page_width=page_width,
        page_height=page_height,
    )
    motif_ids = {str(s.get("id") or "") for s in motif_filtered}
    strips = _proven_filled_wall_strips(motif_filtered)
    graph_segments = _filter_proven_wall_strip_geometry(motif_filtered, strips)
    graph_segment_ids = {str(s.get("id") or "") for s in graph_segments}
    graph = build_wall_graph_for_viewport(graph_segments)
    graph_lineage = edge_lineage_raw_ids(graph)

    owners_by_raw = defaultdict(list)
    usable_owners_by_raw = defaultdict(list)
    for record in wall_result.records:
        for raw_id in record.physical_identity.source_primitive_ids:
            owners_by_raw[str(raw_id)].append(record)
            if record.physical_identity.usable:
                usable_owners_by_raw[str(raw_id)].append(record)

    equivalence = wall_result.equivalence
    ambiguous_ids = set(() if equivalence is None else equivalence.ambiguous_wall_ids)

    visibility = composition.physical_opening_authority.source_visibility_authority()
    opening_rows = []
    stage_counts = Counter()
    owner_count_distribution = Counter()
    pair_class_counts = Counter()

    for trace in composition.opening_bindings:
        existence = composition.physical_opening_authority.prove_existence(
            ObservationSelector(
                document_id=current.revision.document_id,
                revision_id=current.revision.revision_id,
                source_sha256=current.revision.source_sha256,
                snapshot_id=current.snapshot.snapshot_id,
                observation_id=trace.representative_observation_id,
            )
        )
        opening = existence.existence_record
        if (
            existence.status is not EvidenceResolutionStatus.CORROBORATED
            or opening is None
            or opening.structural_pattern != JAMB_BOUNDED_TWO_FACE_INTERRUPTION
        ):
            continue

        observations = []
        raw_lines = {}
        for observation_id in opening.source_observation_ids:
            resolved = visibility.resolve_visible(
                ObservationSelector(
                    document_id=current.revision.document_id,
                    revision_id=current.revision.revision_id,
                    source_sha256=current.revision.source_sha256,
                    snapshot_id=current.snapshot.snapshot_id,
                    observation_id=observation_id,
                )
            )
            observation = resolved.observation
            if resolved.status is not EvidenceResolutionStatus.CORROBORATED or observation is None:
                continue
            raw_id = raw_id_for_observation(observation)
            if raw_id is None:
                continue
            geometry = tuple(float(v) for v in observation.geometry)
            if len(geometry) != 4:
                continue
            observations.append((observation_id, observation, raw_id))
            raw_lines[raw_id] = geometry

        relations = _opening_raw_relation_sets(raw_lines)
        same_pairs = sorted(
            pair
            for pair, classes in relations.items()
            if {state(value) for value in classes} == {"same_physical_wall"}
        )
        face_raw_ids = sorted({raw for pair in same_pairs for raw in pair})
        if len(face_raw_ids) != 4:
            pair_class_counts["face_role_unresolved"] += 1
            continue

        face_rows = []
        for raw_id in face_raw_ids:
            segment = raw_segment.get(raw_id)
            structural = None
            structural_reasons = []
            if segment is not None:
                structural, structural_reasons = is_structural_candidate_segment(segment)
            owners = owners_by_raw.get(raw_id, [])
            usable = usable_owners_by_raw.get(raw_id, [])
            owner_ids = sorted(record.wall_candidate_id for record in owners)
            usable_ids = sorted(record.wall_candidate_id for record in usable)
            ambiguous_owner_ids = sorted(set(owner_ids) & ambiguous_ids)

            if raw_id not in raw_segment:
                stage = "missing_from_w2_source_segments"
            elif raw_id not in motif_ids:
                stage = "filtered_repeated_motif"
            elif raw_id not in graph_segment_ids:
                stage = "filtered_wall_strip_geometry"
            elif not structural:
                stage = "non_structural_candidate"
            elif not graph_lineage.get(raw_id):
                stage = "absent_from_wall_graph_lineage"
            elif not owners:
                stage = "graph_lineage_no_w4_owner"
            elif not usable:
                stage = "w4_owner_identity_unusable"
            elif ambiguous_owner_ids:
                stage = "w4_owner_equivalence_ambiguous"
            elif len(usable_ids) > 1:
                stage = "multiple_usable_w4_owners"
            else:
                stage = "single_usable_w4_owner"

            stage_counts[stage] += 1
            owner_count_distribution[str(len(usable_ids))] += 1
            face_rows.append({
                "raw_id": raw_id,
                "stage": stage,
                "source_kind": None if segment is None else str(segment.get("source_kind") or "native"),
                "layer": None if segment is None else str(segment.get("layer") or ""),
                "structural_candidate": structural,
                "structural_reasons": list(structural_reasons or ()),
                "motif_survives": raw_id in motif_ids,
                "wall_strip_survives": raw_id in graph_segment_ids,
                "graph_edge_ids": sorted(graph_lineage.get(raw_id, ())),
                "w4_owner_ids": owner_ids,
                "usable_w4_owner_ids": usable_ids,
                "ambiguous_owner_ids": ambiguous_owner_ids,
            })

        opening_rows.append({
            "opening_identity_id": trace.opening_identity_id,
            "host_binding_status": state(trace.status),
            "host_binding_reason_codes": list(trace.reason_codes),
            "same_face_pairs": [list(pair) for pair in same_pairs],
            "face_rows": face_rows,
        })

    payload = {
        "source_sha256": actual,
        "snapshot_id": current.snapshot.snapshot_id,
        "wall_scope_status": state(wall_result.status),
        "wall_scope_complete": bool(wall_result.scope_complete),
        "wall_scope_reason_codes": list(wall_result.reason_codes),
        "wall_candidate_count": len(wall_result.records),
        "equivalence_ambiguous_wall_count": 0 if equivalence is None else len(equivalence.ambiguous_wall_ids),
        "two_face_opening_count": len(opening_rows),
        "interrupted_face_primitive_count": sum(len(row["face_rows"]) for row in opening_rows),
        "face_stage_counts": dict(stage_counts.most_common()),
        "usable_owner_count_distribution": dict(sorted(owner_count_distribution.items())),
        "opening_rows": opening_rows,
    }
    payload.update({
        "source_evidence_only": True,
        "production_graph_modified_by_audit": False,
        "physical_host_publication_allowed": False,
        "opening_count_publication_allowed": False,
        "metric_quantity_publication_allowed": False,
        "benchmark_accuracy": None,
    })
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--expected-source-sha", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = source_face_stage_audit(
        args.pdf.read_bytes(),
        page_id=args.page_id,
        expected_source_sha=args.expected_source_sha,
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "source_sha256": report["source_sha256"],
        "page_id": args.page_id,
        "two_face_opening_count": report["two_face_opening_count"],
        "face_stage_counts": report["face_stage_counts"],
        "source_evidence_only": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
