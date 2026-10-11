"""Nonpublishing reader: required sealed flank versus reported raw source lines.

A JSON receipt is not fresh PDF authentication. No candidate is chosen as a
host, and absence from a reported local inventory cannot prove source absence.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

from pb_opening_host_binding_authority import (
    _COORD_TOL,
    _RASTER_WHOLE_WALL_CENTER_TOL_PT,
    _OpeningGeometry,
)
from pb_wall_room_topology_stage_a import DEFAULT_GAP_SNAP_TOLERANCE_PT
from tools.diag_gptmax_raster_host_source_membership import (
    _finite_coordinates,
    _finite_source_axis,
    _source_parent_inventory,
    _validate_aperture_basis,
    nonpublishing_support_projection,
)


def _reported_flanks(row, opening, report):
    support = row["original_g17_support_receipts"]
    ids = _source_parent_inventory([r["requested_source_observation_id"] for r in support], "reported G17 support IDs")
    if sorted(ids) != sorted(row["original_g17_support_observation_ids"]):
        raise ValueError("reported G17 support inventory mismatch")
    band = [r for r in support if r.get("observation_kind") in ("raster_wall_band_face", "raster_wall_band_end")]
    if len(band) != 6:
        return None
    intervals, ends, documents = defaultdict(list), [], set()
    for receipt in band:
        if (receipt.get("source_receipt_authenticated") is not True
                or receipt.get("source_observation_id") != receipt["requested_source_observation_id"]
                or any(receipt.get(k) != report[k] for k in ("source_sha256", "revision_id", "snapshot_id", "page_id"))
                or receipt.get("viewport_id") is not None):
            raise ValueError("reported G17 support source scope mismatch")
        document_id = receipt.get("document_id")
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("reported G17 support document scope unavailable")
        documents.add(document_id)
        geometry = receipt["original_source_support_geometry_pt"]
        if receipt["observation_kind"] == "raster_wall_band_face":
            _, data, failure = _finite_source_axis(geometry, opening)
            if failure:
                return None
            lo, hi, offset = data
            intervals[(lo, hi)].append((offset, receipt["source_observation_id"]))
        else:
            projected = nonpublishing_support_projection(geometry, opening)
            if projected["geometry_disposition"] != "finite_signed_support_projection_observed":
                return None
            ends.append((projected["signed_aperture_axis_coordinates_pt"],
                         sorted(projected["signed_aperture_normal_coordinates_pt"]), receipt["source_observation_id"]))
    if len(documents) != 1 or len(intervals) != 2 or any(len(v) != 2 for v in intervals.values()) or len(ends) != 2:
        return None
    pixel_tol = _RASTER_WHOLE_WALL_CENTER_TOL_PT + _COORD_TOL
    flanks = {}
    # Exact existing host-reader grouping predicates, observed only. These do
    # not select an owner or change any geometry/closure tolerance.
    for (lo, hi), faces in intervals.items():
        offsets = sorted(o for o, _ in faces)
        if offsets[1] - offsets[0] <= _COORD_TOL or offsets[0] > pixel_tol or offsets[1] < -pixel_tol:
            return None
        if lo < -pixel_tol and abs(hi) <= pixel_tol:
            role, edge = "left", hi
        elif hi > opening.length + pixel_tol and abs(lo - opening.length) <= pixel_tol:
            role, edge = "right", lo
        else:
            return None
        matching = [oid for along, cross, oid in ends
                    if all(abs(v-edge) <= _COORD_TOL for v in along)
                    and all(abs(a-b) <= _COORD_TOL for a, b in zip(cross, offsets))]
        if len(matching) != 1 or role in flanks:
            return None
        flanks[role] = {"axis_span_pt": [lo, hi], "normal_span_pt": offsets, "end_axis_coordinate_pt": edge,
                        "reported_face_observation_ids": sorted(oid for _, oid in faces),
                        "reported_end_observation_id": matching[0]}
    return flanks if set(flanks) == {"left", "right"} else None


def required_flank_source_census(report, *, expected_source_sha):
    if report.get("source_sha256") != expected_source_sha:
        raise ValueError("reported original source SHA mismatch")
    if (any(report.get(k) is not False for k in ("host_publication_allowed", "opening_count_publication_allowed", "metric_quantity_publication_allowed"))
            or report.get("benchmark_accuracy") is not None):
        raise ValueError("source report publication boundary unavailable")
    if any(not isinstance(report.get(k), str) or not report[k].strip()
           for k in ("source_sha256", "revision_id", "snapshot_id", "page_id")):
        raise ValueError("source report lineage scope unavailable")
    rows = []
    for row in report["opening_rows"]:
        basis = row["original_aperture_coordinate_basis"]
        vectors = {name: _finite_coordinates(basis[name], 2, "reported aperture basis") for name in ("origin", "axis", "normal")}
        length, thickness = _finite_coordinates((basis["length"], basis["thickness"]), 2, "reported aperture dimensions")
        opening = _OpeningGeometry(**vectors, length=length, thickness=thickness)
        _validate_aperture_basis(opening)
        flanks = _reported_flanks(row, opening, report)
        output = {"opening_identity_id": row["opening_identity_id"],
                  "original_binding_reason_codes": row["original_binding_reason_codes"],
                  "reported_flank_geometry_available": flanks is not None, "flanks": [],
                  "local_contact_proven": False, "host_publication_allowed": False}
        if flanks is not None:
            lines = row["source_w4_ancestry_audit"]["diagnostic_local_raster_lines"]
            _source_parent_inventory([line["source_primitive_id"] for line in lines], "reported local source IDs")
            pixel_tol = _RASTER_WHOLE_WALL_CENTER_TOL_PT + _COORD_TOL
            snap_tol = DEFAULT_GAP_SNAP_TOLERANCE_PT + _COORD_TOL
            for role, flank in sorted(flanks.items()):
                lo, hi = flank["axis_span_pt"]
                cross_lo, cross_hi = flank["normal_span_pt"]
                candidates = []
                for line in lines:
                    coords, data, failure = _finite_source_axis(line["original_source_line_pt"], opening)
                    if failure:
                        continue
                    p_lo, p_hi, offset = data
                    endpoint = p_hi if role == "left" else p_lo
                    if (abs(endpoint-flank["end_axis_coordinate_pt"]) > snap_tol
                            or offset < cross_lo-pixel_tol or offset > cross_hi+pixel_tol
                            or min(p_hi, hi)-max(p_lo, lo) <= pixel_tol):
                        continue
                    owners = _source_parent_inventory(line["exact_positive_ancestry_w4_candidate_ids"], "reported W4 alternatives")
                    candidates.append({"source_primitive_id": line["source_primitive_id"], "original_source_line_pt": list(coords),
                        "reported_w4_candidate_alternatives": sorted(owners), "local_contact_proven": False,
                        "host_publication_allowed": False})
                output["flanks"].append({"role": role, **flank,
                    "reported_source_primitive_candidates": sorted(candidates, key=lambda r: r["source_primitive_id"]),
                    "no_qualifying_primitive_observed_in_reported_local_inventory": not candidates,
                    "source_universe_completeness_proven": False, "host_publication_allowed": False})
        rows.append(output)
    return {"source_sha256": expected_source_sha, "page_id": report["page_id"],
            "opening_rows": sorted(rows, key=lambda r: r["opening_identity_id"]),
            "original_pdf_reauthenticated": False, "source_universe_completeness_proven": False,
            "physical_equivalence_proven": False, "host_publication_allowed": False,
            "opening_count_publication_allowed": False, "metric_quantity_publication_allowed": False,
            "benchmark_accuracy": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = args.source_report.read_bytes()
    result = required_flank_source_census(json.loads(payload), expected_source_sha=args.expected_source_sha)
    result["input_report_sha256"] = sha256(payload).hexdigest()
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"opening_rows": len(result["opening_rows"]), "host_publication_allowed": False}))


if __name__ == "__main__":
    main()
