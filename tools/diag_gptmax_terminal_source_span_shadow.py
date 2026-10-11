"""Observe terminal source-path hypotheses inside the original PDF producer.

No graph, identity, source report, host, frame or quantity is changed. Runtime
association is observational evidence, never a physical-equivalence decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pb_physical_wall_candidate_authority as wall_authority
from tools.diag_opening_wall_face_preservation import source_face_report
from tools.gptmax_terminal_source_span_shadow import preview_terminal_source_spans


def _graph_fingerprint(graph):
    ordinary = {k: v for k, v in graph.items()
                if k != "short_source_fragment_retention_audit"}
    return hashlib.sha256(json.dumps(ordinary, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _records_from_original_call(walls, identities, graph):
    # The production collector is keyed by candidate_id; original W4 source
    # scope rows can nevertheless have a hash collision. Keep every producer
    # row for multiset verification; never silently pick a duplicate wall.
    wall_ids = [wall.candidate_id for wall in walls]
    if (any(not isinstance(cid, str) or not cid for cid in wall_ids)
            or set(wall_ids) != set(identities)):
        raise RuntimeError("foreign or missing source assembly identity")
    edges = {str(edge["id"]): edge for edge in graph["edges"]}
    if len(edges) != len(graph["edges"]):
        raise RuntimeError("duplicate source assembly graph edge")
    records = []
    for wall in sorted(walls, key=lambda row: row.candidate_id):
        identity = identities[wall.candidate_id]
        fragments = []
        for edge_id in sorted(identity.edge_ids):
            edge = edges.get(str(edge_id))
            if edge is None:
                raise RuntimeError("source assembly identity edge unavailable")
            fragments.append({
                "edge_id": str(edge_id),
                "geometry": wall_authority._segment_geometry(edge),
                "source_primitive_ids": tuple(sorted(set(
                    (edge.get(wall_authority.LINEAGE_KEY) or {}).get("source_primitive_ids", ())
                ))),
            })
        records.append({
            "wall_candidate_id": wall.candidate_id,
            "wall_candidate": asdict(wall),
            "physical_identity": asdict(identity),
            "source_edge_fragments": tuple(fragments),
        })
    return records


def terminal_source_span_shadow_report(source_bytes: bytes, *, page_ids: tuple[str, ...]) -> dict:
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    original_build = wall_authority.build_wall_graph_for_viewport
    original_collect = wall_authority.collect_physical_wall_identities
    graphs, calls = {}, []

    def observe_graph(segments, **kwargs):
        graph = original_build(segments, **kwargs)
        if graph.get("short_source_fragment_retention_audit") is None:
            raise RuntimeError("actual source graph endpoint trace unavailable")
        if id(graph) in graphs:
            raise RuntimeError("duplicate original source graph object")
        graphs[id(graph)] = graph  # Keep the exact producer object alive.
        return graph

    def observe_identities(walls, graph):
        if graphs.get(id(graph)) is not graph:
            raise RuntimeError("source assembly graph was not observed")
        if any(call["graph"] is graph for call in calls):
            raise RuntimeError("duplicate source assembly call")
        fingerprint = _graph_fingerprint(graph)
        identities = original_collect(walls, graph)
        records = _records_from_original_call(walls, identities, graph)
        candidate_counts = Counter(record["wall_candidate_id"] for record in records)
        collided = sorted(cid for cid, count in candidate_counts.items() if count > 1)
        if collided:
            # Scope-wide abstention: removing only colliding records would hide
            # their competing source endpoints and invent unique ownership.
            preview = {
                "source_path_previews": [],
                "disposition_counts": {
                    "source_identity_collision_scope_quarantined": len(collided),
                },
                "source_scope_association_authenticated_by_this_preview": False,
                "physical_equivalence_proven": False,
                "graph_mutation_allowed": False,
                "host_count_quantity_publication_allowed": False,
                "benchmark_accuracy": None,
            }
        else:
            preview = preview_terminal_source_spans(
                records, graph["short_source_fragment_retention_audit"])
        if _graph_fingerprint(graph) != fingerprint:
            raise RuntimeError("shadow preview mutated source graph")
        calls.append({"graph": graph, "records": records, "preview": preview,
                      "graph_sha256": fingerprint, "collision_ids": collided})
        return identities  # Never replace, extend or rekey an identity.

    with patch.dict("os.environ", {"GPTMAX_W2_SHORT_SOURCE_AUDIT": "1"}), \
            patch.object(wall_authority, "build_wall_graph_for_viewport", observe_graph), \
            patch.object(wall_authority, "collect_physical_wall_identities", observe_identities):
        source_report = source_face_report(source_bytes, page_ids=page_ids)
    if not calls or len(calls) != len(graphs):
        raise RuntimeError("complete source assembly observation unavailable")
    if (source_report.get("source_sha256") != source_sha
            or source_report.get("primitive_safety_cap") != 20_000
            or tuple(source_report.get("selected_geometry_page_ids", ())) != page_ids):
        raise RuntimeError("original source report provenance mismatch")
    coverage = source_report["source_decode_coverage"]
    document_id = coverage.get("document_id")
    if (not isinstance(document_id, str) or not document_id
            or coverage.get("revision_id") != source_report["revision_id"]):
        raise RuntimeError("original decoded source document mismatch")
    scopes = source_report["source_owned_wall_scope_results"]
    by_scope = {scope["decision_scope_id"]: scope for scope in scopes}
    if len(by_scope) != len(scopes):
        raise RuntimeError("duplicate original source decision scope")
    observed_scopes, rows = set(), []
    for call in calls:
        records = call["records"]
        if not records:
            continue
        scope_id = records[0]["physical_identity"]["viewport_id"]
        scope = by_scope.get(scope_id)
        if scope is None or scope_id in observed_scopes:
            raise RuntimeError("missing or duplicate original source assembly scope")
        observed_scopes.add(scope_id)
        if (scope["document_id"] != document_id
                or scope["source_sha256"] != source_sha or scope["page_id"] not in page_ids
                or scope["revision_id"] != source_report["revision_id"]
                or scope["snapshot_id"] != source_report["snapshot_id"]):
            raise RuntimeError("foreign source assembly scope provenance")
        # Compare the complete multiset of raw source rows, not a dict that
        # overwrites colliding candidate IDs. Physical source identity must be
        # byte-equivalent even when W4 emitted conflicting candidate instances.
        fields = ("wall_candidate_id", "wall_candidate",
                  "physical_identity", "source_edge_fragments")
        def receipt_key(row):
            if any(k not in row for k in fields):
                raise RuntimeError("incomplete original source assembly record")
            return json.dumps({k: row[k] for k in fields}, sort_keys=True,
                              allow_nan=False, default=lambda value: value.value)
        if (Counter(receipt_key(r) for r in scope["records"])
                != Counter(receipt_key(r) for r in records)):
            raise RuntimeError("original source assembly record multiset mismatch")
        rows.append({
            "source_scope_provenance": {key: scope[key] for key in (
                "document_id", "source_sha256", "revision_id", "snapshot_id",
                "page_id", "decision_scope_id")},
            "same_producer_graph_and_identity_call_observed": True,
            "original_scope_records_match_observed_call": True,
            "graph_without_diagnostic_sha256": call["graph_sha256"],
            "original_identity_count": len(records),
            "quarantined_collision_candidate_ids": call["collision_ids"],
            "source_scope_collision_quarantined": bool(call["collision_ids"]),
            "terminal_source_path_preview": call["preview"],
        })
    if not rows:
        raise RuntimeError("no observed original source wall records")
    return {
        "source_sha256": source_sha,
        "source_report": source_report,
        "source_assembly_call_previews": rows,
        "quarantined_source_scope_count": sum(
            bool(row["source_scope_collision_quarantined"]) for row in rows),
        "source_evidence_only": True,
        "physical_equivalence_proven": False,
        "graph_identity_host_frame_quantity_mutation_allowed": False,
        "benchmark_accuracy": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = terminal_source_span_shadow_report(
        args.pdf.read_bytes(), page_ids=tuple(sorted(set(args.page_id), key=int)))
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False,
                                     default=lambda value: value.value) + "\n")
    print(json.dumps({"source_sha256": result["source_sha256"],
                      "summary": result["source_report"]["summary"],
                      "observed_assembly_calls": len(result["source_assembly_call_previews"])}))


if __name__ == "__main__":
    main()
