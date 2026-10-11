"""Diagnostic-only Lot16 room-face source geometry trace (no authority changes).

Run: PYTHONPATH=. python tools/diag_lot16_room_face_scope.py --pdf "documents/sources/1. Construction Plans - Lot 16 Power (REV E).pdf" --page-index 2 --output lot16-room-face-scope.json
The PDF path must be an actual source file; no benchmark gold is loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import pb_source_room_face_authority as face_authority
import pb_source_room_label_authority as label_authority
import pb_same_view_room_area_authority as same_view_authority
from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_live_floor_area_quantity_publication import publish_live_floor_area_quantities
from pb_live_physical_net_wall_integration import collect_live_physical_net_wall_claim



def _has_firm_metric_floor_receipt(floor) -> bool:
    """Count only source-measured canonical floors with complete metric receipts.

    LiveCanonicalFloorSurfaceObject has no metric_area_complete property.
    A geometry-complete but unscaled floor is not a metric area.
    """
    try:
        area = float(floor.metric_area_m2)
    except (TypeError, ValueError, OverflowError, AttributeError):
        return False
    return (
        math.isfinite(area)
        and area > 0.0
        and bool(str(floor.metric_area_quantity_id or "").strip())
        and str(floor.metric_area_authority or "").strip() in {
            MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            MeasurementAuthorityType.PDF_SCALED.value,
        }
        and bool(str(floor.source_room_face_record_id or "").strip())
        and bool(floor.evidence_ids)
    )



def _floor_quantity_first_failure(floor, room, area_quantity_ids: set[str]) -> str:
    """Identify the earliest unresolved floor-to-measurement stage.

    A PDF polygon area is never a physical m² measurement. A correctly
    corroborated source room label does not by itself authenticate scale.
    """
    if not floor.physical_floor_surface_identity_resolved or not floor.physical_floor_surface_id:
        return "physical_floor_identity_unresolved"
    if not floor.source_room_face_record_id or not floor.evidence_ids:
        return "source_room_face_evidence_unavailable"
    if room is None:
        return "canonical_room_owner_unavailable"
    # A separately source-authenticated physical scale can close metric area
    # without an identifiable room-text label. Check an actual measurement
    # receipt first; the label branch diagnoses only the unmeasured path.
    if _has_firm_metric_floor_receipt(floor):
        if floor.metric_area_quantity_id not in area_quantity_ids:
            return "metric_floor_area_quantity_evidence_unavailable"
        return "floor_area_quantity_prerequisites_resolved"
    if (
        not room.room_label
        or not room.room_label_binding_record_id
        or not room.room_label_evidence_ids
    ):
        return "authenticated_room_label_ownership_unavailable"
    return "documented_dimension_or_physical_scale_measurement_unavailable"


def _floor_quantity_diagnostic(claim) -> dict:
    rooms_by_id = {
        str(room.canonical_room_id): room
        for room in claim.canonical_rooms
    }
    # The raw room-area source universe is NOT proof of a publishable floor
    # quantity. Reuse the exact production floor publisher, which validates
    # physical face, canonical/physical floor uniqueness, area, units, source
    # SHA/revision, room snapshot and evidence lineage. This read-only
    # diagnostic can only mark a floor as ready when that gate really passes.
    try:
        approved_floor_quantities = publish_live_floor_area_quantities(claim)
    except (TypeError, ValueError):
        approved_floor_quantities = ()
    areas = {
        str(quantity.metadata.get("upstream_room_area_quantity_id"))
        for quantity in approved_floor_quantities
        if quantity.metadata.get("upstream_room_area_quantity_id")
    }
    finishes: dict[str, list[str]] = {}
    for quantity in claim.floor_finish_quantity_evidence:
        for entity_id in quantity.input_entity_ids:
            finishes.setdefault(str(entity_id), []).append(quantity.quantity_id)
    rows = []
    for floor in claim.canonical_floors:
        reason = _floor_quantity_first_failure(
            floor, rooms_by_id.get(str(floor.room_entity_id)), areas
        )
        rows.append({
            "canonical_floor_id": floor.canonical_floor_id,
            "physical_floor_surface_id": floor.physical_floor_surface_id,
            "room_entity_id": floor.room_entity_id,
            "source_room_face_record_id": floor.source_room_face_record_id,
            "source_receipt_count": len(floor.evidence_ids),
            "geometry_area_page_pts2": floor.area_page_pts2,
            "metric_area_m2": floor.metric_area_m2,
            "metric_area_authority": floor.metric_area_authority,
            "metric_area_quantity_id": floor.metric_area_quantity_id,
            "finish_descriptor": floor.finish_descriptor,
            "published_finish_quantity_ids": sorted(
                finishes.get(str(floor.canonical_floor_id), [])
            ),
            "first_missing_prerequisite": reason,
        })
    return {
        "canonical_floor_count": len(rows),
        "first_failure_frequency": dict(Counter(
            row["first_missing_prerequisite"] for row in rows
        )),
        "area_quantity_count": len(claim.room_area_quantity_evidence),
        "source_closed_floor_quantity_count": len(approved_floor_quantities),
        "finish_quantity_count": len(claim.floor_finish_quantity_evidence),
        "per_floor": rows,
    }


def _wall_metric_first_failure(wall) -> str:
    """Classify the first absent producer-owned wall quantity prerequisite.

    This is a diagnostic ledger, not a new measurement or a claim that the
    source supports a physical wall, a height or a finish.
    """
    if not wall.physical_identity_resolved or not wall.physical_wall_id:
        return "physical_wall_identity_unresolved"
    if not wall.evidence_ids or not wall.plan_members:
        return "canonical_wall_source_receipts_unavailable"
    if wall.length_m is None:
        return "metric_wall_length_unavailable"
    if wall.height_m is None:
        return "authenticated_wall_height_unavailable"
    if wall.gross_area_m2 is None or not wall.gross_polygon_wkb_hex:
        return "gross_wall_area_unavailable"
    if not wall.role or not wall.whole_wall_role_record_id:
        return "authenticated_whole_wall_role_unavailable"
    if wall.net_area_m2 is None or not wall.net_polygon_wkb_hex:
        return "net_wall_area_or_deduction_unavailable"
    return "canonical_net_wall_area_available"


def _wall_metric_diagnostic(claim) -> dict:
    ledger = []
    for wall in claim.canonical_walls:
        ledger.append({
            "canonical_wall_id": wall.canonical_wall_id,
            "physical_wall_id": wall.physical_wall_id,
            "page_id": wall.page_id,
            "physical_identity_resolved": bool(wall.physical_identity_resolved),
            "identity_status": wall.identity_status,
            "plan_member_count": len(wall.plan_members),
            "evidence_receipt_count": len(wall.evidence_ids),
            "role": wall.role,
            "length_m": wall.length_m,
            "height_m": wall.height_m,
            "gross_area_m2": wall.gross_area_m2,
            "net_area_m2": wall.net_area_m2,
            "opening_void_count": len(wall.opening_voids),
            "first_missing_prerequisite": _wall_metric_first_failure(wall),
        })
    return {
        "canonical_wall_count": len(claim.canonical_walls),
        "wall_authority_status": str(getattr(claim.canonical_wall_status, "value", claim.canonical_wall_status)),
        "wall_authority_reasons": list(claim.canonical_wall_reason_codes),
        "first_failure_frequency": dict(Counter(
            entry["first_missing_prerequisite"] for entry in ledger
        )),
        "source_proven_net_wall_publication_status": str(
            getattr(claim.publication.status, "value", claim.publication.status)
        ),
        "external_wall_quantity_published": claim.publication.quantity_evidence is not None,
        "external_wall_ids_count": len(claim.external_wall_ids),
        "per_wall": ledger,
    }



def _opening_quantity_first_failure(opening) -> str:
    """Mirror the existing area publisher's ordered admissibility gates.

    This is source-diagnostic only. Unknown opening labels, counts and geometry
    remain unavailable rather than zero.
    """
    canonical_id = str(opening.canonical_opening_id or "").strip()
    physical_id = str(opening.physical_opening_id or "").strip()
    if not canonical_id or canonical_id != physical_id:
        return "canonical_physical_opening_identity_unresolved"
    if not str(opening.viewport_id or "").strip():
        return "authenticated_opening_viewport_unavailable"
    if not str(opening.host_wall_id or "").strip():
        return "opening_host_wall_unresolved"
    if not (
        str(opening.host_binding_record_id or "").strip()
        or str(opening.host_frame_record_id or "").strip()
    ):
        return "opening_host_source_receipt_unavailable"
    if str(opening.opening_kind or "").strip().lower() not in {"door", "window"}:
        return "authenticated_door_window_semantics_unavailable"
    basis = str(opening.area_basis or "").strip()
    bases = {
        "figured_opening_label": "figured_area_record_id",
        "resolved_opening_geometry": "opening_void_record_id",
        "authenticated_elevation_frame": "figured_area_record_id",
        "authenticated_frame_schedule": "schedule_binding_record_id",
    }
    if basis not in bases:
        return "authenticated_opening_area_basis_unavailable"
    try:
        area = float(opening.area_m2)
    except (TypeError, ValueError, OverflowError):
        return "metric_opening_area_unavailable"
    if not math.isfinite(area) or area <= 0.0:
        return "metric_opening_area_unavailable"
    evidence = {str(value).strip() for value in opening.evidence_ids if str(value).strip()}
    if not evidence:
        return "opening_source_evidence_unavailable"
    authority_record_id = str(getattr(opening, bases[basis]) or "").strip()
    if not authority_record_id or authority_record_id not in evidence:
        return "opening_area_measurement_source_receipt_unavailable"
    if (
        basis == "authenticated_frame_schedule"
        and str(opening.schedule_row_dimension_basis or "").strip().lower() != "frame"
    ):
        return "authenticated_frame_schedule_basis_unavailable"
    return "opening_area_quantity_prerequisites_resolved"


def _opening_quantity_diagnostic(claim) -> dict:
    published_by_opening = {}
    for quantity in claim.opening_quantity_evidence:
        for identity in quantity.input_entity_ids:
            published_by_opening.setdefault(str(identity), []).append(quantity)
    ledger = []
    for opening in claim.canonical_openings:
        published = published_by_opening.get(str(opening.canonical_opening_id), ())
        ledger.append({
            "canonical_opening_id": opening.canonical_opening_id,
            "physical_opening_id": opening.physical_opening_id,
            "page_id": opening.page_id,
            "opening_kind": opening.opening_kind,
            "semantic_class": opening.semantic_class,
            "viewport_id": opening.viewport_id,
            "host_wall_id": opening.host_wall_id,
            "host_receipt_available": bool(
                opening.host_binding_record_id or opening.host_frame_record_id
            ),
            "area_basis": opening.area_basis,
            "area_m2": opening.area_m2,
            "source_evidence_count": len(opening.evidence_ids),
            "schedule_explicit_count": bool(opening.schedule_count_explicit),
            "first_missing_prerequisite": _opening_quantity_first_failure(opening),
            "published_area_quantity_ids": [quantity.quantity_id for quantity in published],
        })
    return {
        "canonical_opening_count": len(claim.canonical_openings),
        "published_area_quantity_count": len(claim.opening_quantity_evidence),
        "published_explicit_count_quantity_count": len(
            claim.opening_count_quantity_evidence
        ),
        "first_failure_frequency": dict(Counter(
            row["first_missing_prerequisite"] for row in ledger
        )),
        "producer_ready_but_no_area_quantity_count": sum(
            row["first_missing_prerequisite"] == "opening_area_quantity_prerequisites_resolved"
            and not row["published_area_quantity_ids"]
            for row in ledger
        ),
        "per_opening": ledger,
    }



def _opening_sealing_diagnostic(claim) -> dict:
    """Exercise existing source-closed sealing and draft customer verification.

    The synthetic workspace ID is diagnostic only; no persistence or scoring.
    """
    from pb_live_opening_source_closed_export import seal_live_opening_area_claim_run
    from pb_live_opening_customer_projection import project_live_opening_customer_rows
    from pb_customer_output_verification import verify_sealed_customer_output

    upstream_ids = sorted(
        quantity.quantity_id for quantity in claim.opening_quantity_evidence
    )
    report = {
        "diagnostic_workspace_only": True,
        "input_opening_area_quantity_count": len(upstream_ids),
        "upstream_quantity_ids": upstream_ids,
    }
    try:
        sealed = seal_live_opening_area_claim_run(
            claim, workspace_id=1, project_id="source-diagnostic:lot16"
        )
        sealed_ids = sorted(quantity.quantity_id for quantity in sealed.quantities)
        report["sealed_opening_area_quantity_count"] = len(sealed_ids)
        report["sealed_quantity_ids"] = sealed_ids
        report["unsealed_upstream_ids"] = sorted(set(upstream_ids) - set(sealed_ids))
        rows = project_live_opening_customer_rows(
            claim, workspace_id=1, project_id="source-diagnostic:lot16"
        )
        verified = verify_sealed_customer_output(sealed, rows)
        report["customer_draft_row_count"] = len(rows)
        report["verified_quantity_ids"] = sorted(verified.verified_quantity_ids)
        report["verified_quantity_count"] = verified.valid_quantity_count
        report["status"] = (
            "source_sealed_and_customer_rows_verified"
            if sealed_ids == upstream_ids
            and len(rows) == len(sealed_ids)
            and sorted(verified.verified_quantity_ids) == sealed_ids
            else "source_to_customer_quantity_mismatch"
        )
    except Exception as error:
        report["status"] = "source_to_customer_exception"
        report["error_type"] = type(error).__name__
        report["error"] = str(error)[:1000]
    return report


def inspect_source(pdf: Path, page_index: int) -> dict:
    payload = pdf.read_bytes()
    observations = []
    original_derive = face_authority._derive_scope_outcome
    original_extract = face_authority.extract_planar_faces
    original_label_resolve = label_authority.SourceRoomLabelAuthority.resolve_scope
    original_witness_intersect = same_view_authority._witness_systems_intersect
    original_trusted_lines = same_view_authority._trusted_lines_for_page
    active_label = {"value": "", "bbox": None}
    def traced_trusted_lines(*args, **kwargs):
        lines = original_trusted_lines(*args, **kwargs)
        candidate_labels = tuple(kwargs.get("candidate_labels") or ())
        active_label["value"] = str(candidate_labels[0]) if len(candidate_labels) == 1 else ""
        active_label["bbox"] = [
            list(line.bbox) for line in lines
        ]
        return lines
    label_scopes = []
    witness_audit = {
        "attempted_pairs": 0,
        "intersecting_pairs": 0,
        "nonintersecting_pairs": 0,
        "failed_pair_samples": [],
    }

    def traced_label_resolve(authority, selector):
        result = original_label_resolve(authority, selector)
        label_scopes.append({
            "page_id": str(selector.page_id),
            "decision_scope_id": str(selector.decision_scope_id),
            "status": str(getattr(result.status, "value", result.status)),
            "reasons": list(result.reason_codes),
            "bound_label_count": len(result.records),
            "split_face_candidate_count": len(result.split_face_candidates),
            "bound_labels": [
                {
                    "label": record.label,
                    "face_id": record.face_id,
                    "source_room_face_record_id": record.source_room_face_record_id,
                }
                for record in result.records
            ],
        })
        return result

    def traced_witness_intersect(horizontal, vertical):
        proven = original_witness_intersect(horizontal, vertical)
        witness_audit["attempted_pairs"] += 1
        witness_audit[
            "intersecting_pairs" if proven else "nonintersecting_pairs"
        ] += 1
        if not proven and len(witness_audit["failed_pair_samples"]) < 300:
            witness_audit["failed_pair_samples"].append({
                "room_label": active_label["value"],
                "trusted_label_bboxes": active_label["bbox"],
                "horizontal_dimension_id": str(horizontal.dimension_id),
                "vertical_dimension_id": str(vertical.dimension_id),
                "horizontal_value_mm": float(horizontal.value_mm),
                "vertical_value_mm": float(vertical.value_mm),
                "horizontal_endpoints_pt": horizontal.endpoints_pt,
                "vertical_endpoints_pt": vertical.endpoints_pt,
                "horizontal_witness_count": len(horizontal.witness_geometries),
                "vertical_witness_count": len(vertical.witness_geometries),
                "horizontal_witness_segments": horizontal.witness_geometries,
                "vertical_witness_segments": vertical.witness_geometries,
                "horizontal_source_witness_ids": list(horizontal.witness_observation_ids),
                "vertical_source_witness_ids": list(vertical.witness_observation_ids),
            })
        return proven

    def traced_extract(segments, *args, **kwargs):
        faces = original_extract(segments, *args, **kwargs)
        areas = sorted(
            (round(face_authority._polygon_area(face_authority._canonical_polygon(face)), 6)
             for face in faces if face_authority._canonical_polygon(face))
        )
        observations[-1]["planar_faces"] = {
            "count": len(faces),
            "canonical_count": len(areas),
            "areas_pt2_sorted": areas[:1000],
            "areas_truncated": len(areas) > 1000,
            "under_absolute_threshold": sum(
                area < face_authority._ABSOLUTE_DEGENERATE_AREA_PT2 for area in areas
            ),
            "under_relative_threshold": sum(
                area < (areas[-1] * face_authority._TINY_RELATIVE_THRESHOLD)
                for area in areas
            ) if areas else 0,
        }
        return faces

    def traced_derive(scope):
        records = tuple(getattr(scope, "records", ()) or ())
        edges_by_wall = {}
        for record in records:
            wall_id = str(getattr(record, "wall_candidate_id", "") or "")
            if wall_id:
                edges_by_wall[wall_id] = face_authority._wall_edges(record)
        observation = {
            "page_id": str(getattr(scope, "page_id", "") or ""),
            "decision_scope_id": str(getattr(scope, "decision_scope_id", "") or ""),
            "scope_status": str(getattr(getattr(scope, "status", None), "value", getattr(scope, "status", None))),
            "scope_complete": bool(getattr(scope, "scope_complete", False)),
            "source_wall_record_count": len(records),
            "source_wall_identity_count": len(edges_by_wall),
            "source_wall_edge_count": sum(map(len, edges_by_wall.values())),
            "source_wall_zero_edge_count": sum(not edges for edges in edges_by_wall.values()),
        }
        observations.append(observation)
        outcome = original_derive(scope)
        observation["outcome_status"] = str(getattr(getattr(outcome, "status", None), "value", getattr(outcome, "status", None)))
        observation["outcome_reasons"] = list(getattr(outcome, "reason_codes", ()) or ())
        observation["published_face_count"] = len(getattr(outcome, "records", ()) or ())
        return outcome

    try:
        face_authority._derive_scope_outcome = traced_derive
        face_authority.extract_planar_faces = traced_extract
        label_authority.SourceRoomLabelAuthority.resolve_scope = traced_label_resolve
        same_view_authority._witness_systems_intersect = traced_witness_intersect
        same_view_authority._trusted_lines_for_page = traced_trusted_lines
        claim = collect_live_physical_net_wall_claim(
            pdf, pages=(page_index,), topology_pages=(page_index,),
            room_area_support_pages=None,
        )
        return {
            "diagnostic_only": True, "pdf_sha256": hashlib.sha256(payload).hexdigest(),
            "source_page_index_zero_based": page_index,
            "scope_outcomes": observations,
            "claim_type": type(claim).__name__,
            "floor_quantity_diagnostic": _floor_quantity_diagnostic(claim),
            "wall_metric_diagnostic": _wall_metric_diagnostic(claim),
            "opening_quantity_diagnostic": _opening_quantity_diagnostic(claim),
            "opening_sealing_diagnostic": _opening_sealing_diagnostic(claim),
            "source_label_scope_diagnostic": label_scopes,
            "same_view_witness_intersection_audit": witness_audit,
            "label_ownership_diagnostic": {
                "labelled_room_count": sum(bool(room.room_label) for room in claim.canonical_rooms),
                "unlabelled_room_count": sum(not bool(room.room_label) for room in claim.canonical_rooms),
                "label_reason_frequency": dict(Counter(
                    code for room in claim.canonical_rooms
                    for code in (room.room_label_reason_codes or ())
                )),
                "labelled_rooms": [
                    {
                        "physical_room_id": room.physical_room_id,
                        "room_label": room.room_label,
                        "source_face_id": room.source_room_face_record_id,
                        "label_binding_id": room.room_label_binding_record_id,
                        "label_evidence_count": len(room.room_label_evidence_ids),
                        "label_reason_codes": list(room.room_label_reason_codes),
                        "polygon_pdf_pts": [list(point) for point in room.polygon_pdf_pts],
                        "bounding_wall_ids": list(room.bounding_wall_ids),
                        "polygon_area_page_pts2": float(room.area_page_pts2),
                    }
                    for room in claim.canonical_rooms if room.room_label
                ],
            },
            "same_view_prerequisite_breakdown": {
                "room_count": len(claim.canonical_rooms),
                "geometry_incomplete": sum(not room.geometry_complete for room in claim.canonical_rooms),
                "physical_room_id_missing": sum(not str(room.physical_room_id or "").strip() for room in claim.canonical_rooms),
                "source_face_id_missing": sum(not str(room.source_room_face_record_id or "").strip() for room in claim.canonical_rooms),
                "room_label_missing": sum(not str(room.room_label or "").strip() for room in claim.canonical_rooms),
                "room_label_binding_missing": sum(not str(room.room_label_binding_record_id or "").strip() for room in claim.canonical_rooms),
                "room_label_evidence_missing": sum(not bool(room.room_label_evidence_ids) for room in claim.canonical_rooms),
            },
            "downstream": {
                "canonical_room_count": len(claim.canonical_rooms),
                "canonical_room_status": str(getattr(claim.canonical_room_status, "value", claim.canonical_room_status)),
                "canonical_room_reasons": list(claim.canonical_room_reason_codes),
                "canonical_floor_count": len(claim.canonical_floors),
                "canonical_floor_status": str(getattr(claim.canonical_floor_status, "value", claim.canonical_floor_status)),
                "canonical_floor_reasons": list(claim.canonical_floor_reason_codes),
                "metric_floor_count": sum(_has_firm_metric_floor_receipt(floor) for floor in claim.canonical_floors),
                "room_area_quantity_count": len(claim.room_area_quantity_evidence),
                "floor_finish_quantity_count": len(claim.floor_finish_quantity_evidence),
                "same_view_first_failures": list(claim.same_view_room_area_first_failure_codes),
                "cross_view_first_failures": list(claim.cross_view_room_area_first_failure_codes),
                "physical_scale_first_failures": list(claim.physical_scale_first_failure_codes),
            },
            "scope_reason_frequency": dict(Counter(
                reason for item in observations for reason in item["outcome_reasons"]
            )),
        }
    finally:
        face_authority._derive_scope_outcome = original_derive
        face_authority.extract_planar_faces = original_extract
        label_authority.SourceRoomLabelAuthority.resolve_scope = original_label_resolve
        same_view_authority._witness_systems_intersect = original_witness_intersect
        same_view_authority._trusted_lines_for_page = original_trusted_lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--page-index", type=int, default=2)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.page_index < 0:
        parser.error("--page-index must be >= 0")
    if not args.pdf.is_file():
        parser.error(f"source PDF unavailable: {args.pdf}")
    report = inspect_source(args.pdf, args.page_index)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "pdf_sha256": report["pdf_sha256"],
        "scope_count": len(report["scope_outcomes"]),
        "scope_reason_frequency": report["scope_reason_frequency"],
        "opening_seal_status": report["opening_sealing_diagnostic"]["status"],
        "output": str(args.output),
    }, sort_keys=True))
    # The artifact is written even on failure so source/quantity first gates
    # remain inspectable. Do not quietly pass source-to-customer mismatches.
    if report["opening_sealing_diagnostic"]["status"] != "source_sealed_and_customer_rows_verified":
        raise SystemExit("source-to-sealed opening/customer row validation failed")


if __name__ == "__main__":
    main()
