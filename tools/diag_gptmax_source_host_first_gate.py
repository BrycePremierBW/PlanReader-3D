"""Read-only source-produced opening host and W4 identity first-gate census.

Input MUST be a report from tools/diag_opening_wall_face_preservation.py.
That tool obtains evidence through the original producer. A JSON report alone
cannot independently authenticate a PDF; use --expected-source-sha to verify
the report's asserted source lineage against a separately known SHA.

Never publish physical host, wall equivalence, count, dimensions or accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import re
from pathlib import Path


def _string_inventory(value, label: str) -> tuple[str, ...]:
    if (not isinstance(value, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"invalid or duplicate {label} inventory")
    return tuple(value)


def source_first_gate_census(report: dict, *, expected_source_sha: str | None = None) -> dict:
    if not isinstance(report, dict):
        raise ValueError("original source report must be a JSON object")
    sha = report.get("source_sha256")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        raise ValueError("missing or invalid original source SHA-256")
    if expected_source_sha is not None and expected_source_sha != sha:
        raise ValueError("original source SHA-256 mismatch")
    if type(report.get("primitive_safety_cap")) is not int or report["primitive_safety_cap"] != 20_000:
        raise ValueError("source safety cap is missing or altered")
    revision_id = report.get("revision_id")
    snapshot_id = report.get("snapshot_id")
    coverage = report.get("source_decode_coverage")
    if (not isinstance(revision_id, str) or not revision_id
            or not isinstance(snapshot_id, str) or not snapshot_id
            or not isinstance(coverage, dict)
            or not isinstance(coverage.get("document_id"), str)
            or not coverage["document_id"]
            or coverage.get("revision_id") != revision_id):
        raise ValueError("inconsistent original source revision and snapshot lineage")
    document_id = coverage["document_id"]
    pages = report.get("selected_geometry_page_ids")
    if (not isinstance(pages, (list, tuple)) or not pages
            or any(not isinstance(p, str) or not p.isdigit() or int(p) < 1 for p in pages)
            or len(set(pages)) != len(pages)):
        raise ValueError("invalid original source page scope")
    decoded = coverage.get("decoded_pages")
    failed = coverage.get("failed_pages")
    if (not isinstance(decoded, (list, tuple))
            or not isinstance(failed, (list, tuple))
            or any(type(p) is not int or p < 1 for p in (*decoded, *failed))
            or any(int(p) not in decoded or int(p) in failed for p in pages)):
        raise ValueError("selected original source pages were not all decoded")
    scopes = report.get("source_owned_wall_scope_results")
    bindings = report.get("opening_bindings")
    frames = report.get("host_frames")
    summary = report.get("summary")
    if (not isinstance(scopes, list) or not isinstance(bindings, list)
            or not isinstance(frames, list)
            or any(not isinstance(b, dict) for b in bindings)
            or any(not isinstance(f, dict) for f in frames)
            or any(not isinstance(s, dict) for s in scopes)):
        raise ValueError("original source wall/opening/frame receipts unavailable")
    if not isinstance(summary, dict):
        raise ValueError("source report has no producer summary")
    expected = {
        "physical_existence_claims": len(bindings),
        "host_bindings": sum(bool(b.get("host_wall_id")) for b in bindings),
        "host_frames": sum(bool(f.get("record_id")) for f in frames),
    }
    if any(type(summary.get(key)) is not int or summary[key] != count
           for key, count in expected.items()):
        raise ValueError("source report summary contradicts individual receipts")
    semantic = report.get("semantic_inventory")
    semantic_record = semantic.get("record") if isinstance(semantic, dict) else None
    if not isinstance(semantic_record, dict):
        raise ValueError("source semantic opening universe receipt unavailable")
    for field, expected_value in (
        ("document_id", document_id), ("revision_id", revision_id),
        ("snapshot_id", snapshot_id), ("source_sha256", sha),
    ):
        if semantic_record.get(field) != expected_value:
            raise ValueError(f"foreign source semantic opening inventory {field}")
    semantic_pages = _string_inventory(semantic_record.get("page_ids"), "semantic page scope")
    if set(semantic_pages) != set(pages):
        raise ValueError("foreign source semantic opening inventory page scope")
    semantic_opening_ids = _string_inventory(
        semantic_record.get("representative_observation_ids"), "semantic representative source IDs"
    )
    if len(semantic_opening_ids) != len(bindings):
        raise ValueError("semantic inventory and original opening receipts disagree")
    # Matching cardinality cannot prove that the same physical source members
    # reached the opening host gate: require exact producer observation IDs.
    observed_representatives = tuple(
        b.get("representative_observation_id") for b in bindings
    )
    if (any(not isinstance(x, str) or not x.strip() for x in observed_representatives)
            or len(set(observed_representatives)) != len(observed_representatives)
            or set(observed_representatives) != set(semantic_opening_ids)):
        raise ValueError("semantic source representative IDs disagree with host bindings")
    semantic_physical_ids = _string_inventory(
        semantic_record.get("physical_opening_record_ids"), "semantic physical-opening identities"
    )
    if (len(semantic_physical_ids) != len(bindings)
            or set(semantic_physical_ids) != {
                b.get("opening_identity_id") for b in bindings
            }):
        raise ValueError("semantic source physical-opening identities disagree with host bindings")
    residual_ids = _string_inventory(
        semantic_record.get("residual_visible_observation_ids"), "semantic residual source IDs"
    )
    conflict_ids = _string_inventory(
        semantic_record.get("conflict_observation_ids"), "semantic conflict source IDs"
    )
    for flag in ("physical_opening_universe_complete", "structural_enumeration_complete"):
        if type(semantic_record.get(flag)) is not bool:
            raise ValueError(f"invalid semantic completeness flag {flag}")
    semantic_census = {
        "status": semantic.get("status"),
        "producer_reason_codes": list(semantic.get("reason_codes") or ()),
        "physical_opening_universe_complete": (
            semantic_record.get("physical_opening_universe_complete") is True
        ),
        "structural_enumeration_complete": (
            semantic_record.get("structural_enumeration_complete") is True
        ),
        "representative_source_opening_count": len(semantic_opening_ids),
        "residual_source_observation_count": len(residual_ids),
        "conflict_source_observation_count": len(conflict_ids),
    }
    observed_pages = {str(s.get("page_id")) for s in scopes}
    if observed_pages != set(pages):
        raise ValueError("wall scopes do not match requested original source pages")
    if any(s.get("source_sha256") != sha for s in scopes):
        raise ValueError("foreign source wall scope")
    if any(
        scope.get("revision_id") != revision_id
        or scope.get("snapshot_id") != snapshot_id
        or scope.get("document_id") != document_id
        for scope in scopes
    ):
        raise ValueError("foreign original revision, snapshot, or document wall scope")
    scope_ids = [s.get("decision_scope_id") for s in scopes]
    if any(not isinstance(s, str) or not s.strip() for s in scope_ids) or len(set(scope_ids)) != len(scope_ids):
        raise ValueError("repeated or missing producer-owned wall decision scope")

    collisions = []
    sidecar_mismatches = []
    scope_census = []
    for scope in sorted(scopes, key=lambda s: (int(s["page_id"]), s["decision_scope_id"])):
        records = scope.get("records")
        if not isinstance(records, (list, tuple)):
            raise ValueError("missing original wall record inventory")
        by_id = defaultdict(list)
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("wall_candidate_id"), str):
                raise ValueError("invalid source wall record")
            candidate = record.get("wall_candidate")
            identity = record.get("physical_identity")
            if not isinstance(candidate, dict) or not isinstance(identity, dict):
                raise ValueError("missing W4 source candidate/physical identity")
            if candidate.get("candidate_id") != record["wall_candidate_id"]:
                raise ValueError("wall record and W4 address disagree")
            if identity.get("wall_candidate_id") != record["wall_candidate_id"]:
                raise ValueError("wall record and physical identity address disagree")
            by_id[record["wall_candidate_id"]].append(record)
            source_edges = tuple(candidate.get("face_a_segment_ids") or ()) + tuple(
                candidate.get("face_b_segment_ids") or ())
            identity_edges = tuple(identity.get("edge_ids") or ())
            if source_edges != identity_edges:
                sidecar_mismatches.append({
                    "page_id": scope["page_id"],
                    "wall_candidate_id": record["wall_candidate_id"],
                    "w4_source_edge_ids": list(source_edges),
                    "identity_sidecar_edge_ids": list(identity_edges),
                })
        for wall_id, group in sorted(by_id.items()):
            if len(group) < 2:
                continue
            collisions.append({
                "page_id": scope["page_id"],
                "wall_candidate_id": wall_id,
                "source_candidate_count": len(group),
                "source_edges_by_candidate": [
                    list(c["wall_candidate"].get("face_a_segment_ids") or ())
                    for c in group
                ],
                "w3_junctions_by_candidate": [
                    list(c["wall_candidate"].get("end_node_ids") or ())
                    for c in group
                ],
            })
        scope_census.append({
            "page_id": scope["page_id"],
            "decision_scope_id": scope["decision_scope_id"],
            "w4_source_candidate_records": len(records),
            "unique_w4_candidate_addresses": len(by_id),
            "collided_w4_address_count": sum(len(group) > 1 for group in by_id.values()),
        })

    seen = set()
    first_gates = Counter()
    unhosted = []
    for trace in sorted(bindings, key=lambda b: (str(b.get("page_id")), str(b.get("opening_identity_id")))):
        page = trace.get("page_id")
        opening_id = trace.get("opening_identity_id")
        if (page not in pages or not isinstance(opening_id, str) or not opening_id
                or (page, opening_id) in seen):
            raise ValueError("duplicate, missing, or foreign opening source identity")
        seen.add((page, opening_id))
        if trace.get("host_wall_id"):
            continue
        reasons = tuple(trace.get("reason_codes") or ())
        if any(not isinstance(code, str) or not code for code in reasons):
            raise ValueError("invalid original source host blockers")
        specific = {
            "raster_source_band_left_source_primitive_unmapped":
                "left_original_raster_source_primitive_unmapped",
            "raster_source_band_right_source_primitive_unmapped":
                "right_original_raster_source_primitive_unmapped",
            "raster_source_band_left_local_wall_owner_unmapped":
                "left_source_local_w4_owner_unmapped",
            "raster_source_band_right_local_wall_owner_unmapped":
                "right_source_local_w4_owner_unmapped",
        }
        observed = tuple(sorted(specific[code] for code in reasons if code in specific))
        # Two independent flank failures do not have an authenticated order.
        # Never arbitrarily call 'left' the first evidence gate.
        if observed:
            stage = (observed[0] if len(observed) == 1
                     else "multiple_source_host_gates_unresolved")
        elif "complete_authenticated_host_wall_universe_required" in reasons:
            stage = "source_wall_scope_boundary_or_completeness_unproven"
        elif "ambiguous_physical_wall_equivalence_for_host" in reasons:
            stage = "physical_wall_equivalence_ambiguous_for_host"
        elif "no_authenticated_host_wall_band" in reasons:
            stage = "source_host_wall_band_unproven"
        else:
            stage = "other_source_host_blocker"
        first_gates[stage] += 1
        unhosted.append({
            "page_id": page,
            "opening_identity_id": opening_id,
            "first_observed_host_gate": stage,
            "all_specific_observed_gates": list(observed),
            "original_source_reason_codes": list(reasons),
        })
    # A frame tally must retain the same physical-opening and host receipts.
    # Equal cardinality cannot excuse a foreign/substituted frame identity.
    bindings_by_opening = {b["opening_identity_id"]: b for b in bindings}
    frame_openings, frame_record_ids = set(), set()
    walls_by_page = defaultdict(set)
    for scope in scopes:
        walls_by_page[scope["page_id"]].update(
            record["wall_candidate_id"] for record in scope["records"]
        )
    for frame in frames:
        opening_id = frame.get("opening_identity_id")
        if (not isinstance(opening_id, str) or not opening_id
                or opening_id not in bindings_by_opening or opening_id in frame_openings):
            raise ValueError("duplicate or foreign source frame opening identity")
        frame_openings.add(opening_id)
        binding = bindings_by_opening[opening_id]
        frame_id = frame.get("record_id")
        if frame_id is None:
            if frame.get("host_wall_id") or frame.get("whole_wall_candidate_ids"):
                raise ValueError("unresolved source frame cannot assert a host or wall members")
            continue
        if (not isinstance(frame_id, str) or not frame_id.strip()
                or frame_id in frame_record_ids):
            raise ValueError("duplicate or invalid source frame receipt identity")
        frame_record_ids.add(frame_id)
        if (frame.get("status") != "corroborated"
                or not binding.get("host_wall_id")
                or frame.get("host_wall_id") != binding["host_wall_id"]):
            raise ValueError("source frame host contradicts opening host binding")
        members = _string_inventory(frame.get("whole_wall_candidate_ids"), "source frame wall members")
        if not members or not set(members).issubset(walls_by_page[binding["page_id"]]):
            raise ValueError("source frame contains missing or foreign page wall members")
    return {
        "original_source_report_sha256": sha,
        "selected_geometry_page_ids": list(pages),
        "source_summary_verified": expected,
        "semantic_opening_universe_source_census": semantic_census,
        "source_wall_scope_census": scope_census,
        "w4_candidate_address_collisions": collisions,
        "physical_identity_sidecar_edge_mismatches": sidecar_mismatches,
        "unhosted_original_openings": unhosted,
        "unhosted_first_gate_counts": dict(sorted(first_gates.items())),
        "source_report_only": True,
        "original_pdf_bytes_reauthenticated_by_this_report": False,
        "host_publication_allowed": False,
        "physical_wall_equivalence_proven": False,
        "opening_count_publication_allowed": False,
        "metric_quantity_publication_allowed": False,
        "benchmark_accuracy": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    census = source_first_gate_census(
        json.loads(args.source_report.read_text()),
        expected_source_sha=args.expected_source_sha,
    )
    args.output.write_text(json.dumps(census, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "source_sha256": census["original_source_report_sha256"],
        "unhosted": len(census["unhosted_original_openings"]),
        "first_gates": census["unhosted_first_gate_counts"],
        "w4_candidate_address_collisions": len(census["w4_candidate_address_collisions"]),
        "physical_identity_edge_mismatches": len(census["physical_identity_sidecar_edge_mismatches"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
