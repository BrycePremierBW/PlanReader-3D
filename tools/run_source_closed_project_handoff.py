"""Generate benchmark-neutral source-closed production handoff artifacts.

This command runs source-owned production extraction against one PDF, discovers
eligible floor-plan topology from source evidence, seals every currently
supported production family, and combines those family runs into one project
handoff.

It deliberately has no dependency on frozen benchmark truth, expected
quantities, tolerances, denominator eligibility, identity maps, or scoring.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

import fitz

from pb_live_ceiling_area_quantity_publication import (
    publish_live_ceiling_area_quantities,
)
from pb_live_ceiling_area_source_closed_export import seal_live_ceiling_area_run
from pb_live_ceiling_lining_integration import collect_live_ceiling_lining_claims
from pb_live_ceiling_lining_source_closed_export import (
    seal_live_ceiling_lining_run,
)
from pb_source_floor_plan_page_scope import source_floor_plan_topology_scope
from pb_live_opening_count_source_closed_export import (
    seal_live_opening_count_run,
)
from pb_live_opening_source_closed_export import (
    seal_live_opening_area_claim_run,
)
from pb_live_physical_net_wall_integration import (
    collect_live_physical_net_wall_claim,
)
from pb_live_floor_area_quantity_publication import (
    publish_live_floor_area_quantities,
)
from pb_live_floor_area_source_closed_export import seal_live_floor_area_run
from pb_live_floor_finish_area_source_closed_export import (
    seal_live_floor_finish_area_run,
)
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import (
    SealedSourceClosedRun,
    combine_source_closed_runs,
)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_page_scopes(
    path: Path,
) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    """Return production topology + cross-view support scopes from source evidence.

    This mirrors the customer runtime contract:
    - topology narrows only when source classification positively proves it;
    - cross-view room-area support receives only positively classified evidence
      pages;
    - when scope is unavailable/unproven, topology remains the full universe and
      no extra room-area support pages are invented.
    """
    doc = fitz.open(path)
    try:
        page_count = int(doc.page_count)
    finally:
        doc.close()

    selected = tuple(range(page_count))
    if not selected:
        return (), (), page_count

    scope = source_floor_plan_topology_scope(path, selected)
    if scope is None:
        return selected, (), page_count

    topology = scope.topology_page_indices()
    support = tuple(
        getattr(
            scope,
            "room_area_support_page_indices",
            getattr(scope, "evidence_page_indices", ()),
        )
        or ()
    )
    if topology is None:
        return selected, (), page_count
    return tuple(topology), support, page_count


def _source_topology_pages(path: Path) -> tuple[tuple[int, ...], int]:
    """Compatibility helper for diagnostics that need only topology pages."""
    topology, _support, page_count = _source_page_scopes(path)
    return topology, page_count


def _non_abstained(
    quantities: Iterable[QuantityEvidence],
) -> tuple[QuantityEvidence, ...]:
    """Only source-closed eligible quantities may enter a sealed handoff.

    Non-ABSTAIN with a numeric value is not itself a publication grant.
    Shadow and conflicted provisional records remain unavailable, not zero.
    """
    retained = []
    for quantity in quantities:
        if not isinstance(quantity, QuantityEvidence) or quantity.abstained or quantity.value is None:
            continue
        if type(quantity.value) not in (int, float):
            continue
        try:
            if not math.isfinite(quantity.value):
                continue
        except OverflowError:
            continue
        status = getattr(quantity.status, "value", quantity.status)
        status = str(status).strip().lower().replace("-", "_").replace(" ", "_")
        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        if status not in {"firm", "corroborated"}:
            continue
        if quantity.blocking_reasons or any(
            any(token in str(code).lower() for token in ("conflict", "stale", "superseded"))
            for code in quantity.reason_codes
        ):
            continue
        if "shadow_only" in metadata and metadata["shadow_only"] is not False:
            continue
        if "commercial_projection_allowed" in metadata and metadata["commercial_projection_allowed"] is not True:
            continue
        if metadata.get("is_stale") is not None and metadata.get("is_stale") is not False:
            continue
        if metadata.get("is_superseded") is not None and metadata.get("is_superseded") is not False:
            continue
        retained.append(quantity)
    return tuple(retained)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_run(
    directory: Path,
    family: str,
    run: SealedSourceClosedRun,
) -> Path:
    path = directory / "family_runs" / f"{family}.sealed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.to_json(), encoding="utf-8")
    return path


def generate_project_handoff(
    *,
    pdf_path: Path,
    project_id: str,
    workspace_id: int,
    output_dir: Path,
    family_group: str = "all",
) -> dict[str, Any]:
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if type(project_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", project_id):
        raise ValueError("project_id must be a single filename-safe source identity")
    # A fractional/Boolean ID cannot be converted into a different producer's
    # workspace before source authentication. CLI already supplies an integer.
    if type(workspace_id) is not int or workspace_id <= 0:
        raise ValueError("workspace_id must be a positive integer")

    clean_family_group = str(family_group or "").strip().lower()
    if clean_family_group not in {"all", "core", "surfaces"}:
        raise ValueError(
            "family_group must be one of: all, core, surfaces"
        )

    source_sha256 = _sha256(pdf_path)
    topology_pages, room_area_support_pages, page_count = _source_page_scopes(
        pdf_path
    )
    all_pages = tuple(range(page_count))
    topology_restricted = bool(topology_pages) and (
        tuple(topology_pages) != tuple(all_pages)
    )
    topology_mode = (
        "source_classified_scope"
        if topology_restricted
        else "live_authority_all_pages_fallback"
    )

    if topology_restricted:
        if clean_family_group == "core":
            # Core execution is intentionally topology-only.
            claim_execution_pages = tuple(topology_pages)
            semantic_execution_pages = tuple(topology_pages)
            execution_room_support_pages = None
        elif clean_family_group == "surfaces":
            # Surface geometry and room measurement only need positively
            # classified topology plus plan-like room-area support pages.
            claim_execution_pages = tuple(
                sorted(set(topology_pages) | set(room_area_support_pages))
            )
            # Ceiling/material semantics remain free to authenticate against the
            # complete source evidence universe. This narrows expensive geometry
            # work without narrowing semantic evidence authority.
            semantic_execution_pages = tuple(all_pages)
            execution_room_support_pages = (
                room_area_support_pages
                if room_area_support_pages
                else None
            )
        else:
            # Complete handoff preserves the all-page evidence universe because
            # opening families may depend on schedules/elevations/support pages.
            claim_execution_pages = tuple(all_pages)
            semantic_execution_pages = tuple(all_pages)
            execution_room_support_pages = (
                room_area_support_pages
                if room_area_support_pages
                else None
            )
    else:
        claim_execution_pages = tuple(all_pages)
        semantic_execution_pages = tuple(all_pages)
        execution_room_support_pages = (
            room_area_support_pages
            if room_area_support_pages
            else None
        )

    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "source_path": str(pdf_path),
        "source_sha256": source_sha256,
        "page_count": page_count,
        "topology_pages": [page + 1 for page in topology_pages],
        "room_area_support_pages": [
            page + 1 for page in room_area_support_pages
        ],
        "topology_mode": topology_mode,
        "family_group": clean_family_group,
        "complete_project_handoff": clean_family_group == "all",
        "execution_pages": [page + 1 for page in claim_execution_pages],
        "semantic_execution_pages": [
            page + 1 for page in semantic_execution_pages
        ],
        "status": "unavailable",
        "family_counts": {},
        "family_run_ids": {},
        "family_run_files": {},
        "combined_run_file": None,
        "combined_run_id": None,
        "canonical_counts": {},
        "claim_status": None,
        "claim_reason_codes": [],
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        claim = collect_live_physical_net_wall_claim(
            pdf_path,
            pages=claim_execution_pages,
            topology_pages=(topology_pages if topology_restricted else None),
            # Core-family execution never activates cross-view room-area
            # measurement. Surface/all execution retains the source-classified
            # support-page contract.
            room_area_support_pages=execution_room_support_pages,
            surface_semantic_pages=semantic_execution_pages,
        )
    except Exception as exc:
        summary["status"] = "production_failed"
        summary["production_error_type"] = type(exc).__name__
        summary["production_error_message"] = str(exc)
        summary["claim_reason_codes"] = [
            f"production_extraction_error:{type(exc).__name__}"
        ]
        _write_json(output_dir / "production_summary.json", summary)
        raise
    summary["claim_status"] = getattr(
        getattr(claim, "status", None),
        "value",
        str(getattr(claim, "status", "")),
    )
    summary["claim_reason_codes"] = list(
        getattr(claim, "reason_codes", ()) or ()
    )
    summary["canonical_counts"] = {
        "walls": len(tuple(getattr(claim, "canonical_walls", ()) or ())),
        "openings": len(tuple(getattr(claim, "canonical_openings", ()) or ())),
        "rooms": len(tuple(getattr(claim, "canonical_rooms", ()) or ())),
        "floors": len(tuple(getattr(claim, "canonical_floors", ()) or ())),
        "ceilings": len(tuple(getattr(claim, "canonical_ceilings", ()) or ())),
        "spaces": len(tuple(getattr(claim, "canonical_spaces", ()) or ())),
    }

    family_runs: list[tuple[str, SealedSourceClosedRun]] = []

    if clean_family_group in {"all", "surfaces"}:
        floor_quantities = _non_abstained(
            publish_live_floor_area_quantities(claim)
        )
    else:
        floor_quantities = ()
    summary["family_counts"]["floor_area"] = len(floor_quantities)
    if floor_quantities:
        family_runs.append(
            (
                "floor_area",
                seal_live_floor_area_run(
                    claim,
                    workspace_id=int(workspace_id),
                    project_id=project_id,
                ),
            )
        )

    if clean_family_group in {"all", "surfaces"}:
        floor_finish_quantities = _non_abstained(
            getattr(claim, "floor_finish_quantity_evidence", ())
        )
    else:
        floor_finish_quantities = ()
    summary["family_counts"]["floor_finish_area"] = len(
        floor_finish_quantities
    )
    if floor_finish_quantities:
        family_runs.append(
            (
                "floor_finish_area",
                seal_live_floor_finish_area_run(
                    claim,
                    workspace_id=int(workspace_id),
                    project_id=project_id,
                ),
            )
        )

    if clean_family_group in {"all", "core"}:
        opening_area_quantities = _non_abstained(
            getattr(claim, "opening_quantity_evidence", ())
        )
    else:
        opening_area_quantities = ()
    summary["family_counts"]["opening_area"] = len(
        opening_area_quantities
    )
    if opening_area_quantities:
        family_runs.append(
            (
                "opening_area",
                seal_live_opening_area_claim_run(
                    claim,
                    workspace_id=int(workspace_id),
                    project_id=project_id,
                ),
            )
        )

    if clean_family_group in {"all", "core"}:
        opening_count_quantities = _non_abstained(
            getattr(claim, "opening_count_quantity_evidence", ())
        )
    else:
        opening_count_quantities = ()
    summary["family_counts"]["opening_count"] = len(
        opening_count_quantities
    )
    if opening_count_quantities:
        family_runs.append(
            (
                "opening_count",
                seal_live_opening_count_run(
                    claim,
                    workspace_id=int(workspace_id),
                    project_id=project_id,
                ),
            )
        )

    new_ceiling_quantities: tuple[QuantityEvidence, ...] = ()
    legacy_ceiling_quantities: tuple[QuantityEvidence, ...] = ()
    ceiling_result = None
    if clean_family_group in {"all", "surfaces"}:
        new_ceiling_quantities = _non_abstained(
            getattr(claim, "ceiling_lining_quantity_evidence", ())
        )

        # Preserve the existing scale-aware/same-scope ceiling path for rooms
        # not already owned by the new RCP authority. One valid new ceiling
        # must never suppress unrelated valid existing output.
        ceiling_result = collect_live_ceiling_lining_claims(
            pdf_path,
            # Ceiling semantics may live on schedules, legends and RCP support
            # sheets. Keep the full surface execution evidence universe visible;
            # the collector still owns topology independently.
            pages=semantic_execution_pages,
            topology_pages=(
                topology_pages if topology_pages else semantic_execution_pages
            ),
            authoritative_room_area_quantities=tuple(
                getattr(claim, "room_area_quantity_evidence", ()) or ()
            ),
        )
        published_new_ids = {
            _clean(quantity.quantity_id)
            for quantity in new_ceiling_quantities
            if _clean(quantity.quantity_id)
        }
        # Only a genuinely published new quantity may supersede legacy.
        # A candidate canonical ceiling without FIRM QuantityEvidence must
        # leave independently valid legacy output untouched.
        published_new_ceilings = tuple(
            ceiling
            for ceiling in tuple(getattr(claim, "canonical_ceilings", ()) or ())
            if _clean(getattr(ceiling, "ceiling_quantity_id", ""))
            in published_new_ids
        )
        new_room_index_ids = {
            _clean(ceiling.source_room_index_id)
            for ceiling in published_new_ceilings
            if _clean(ceiling.source_room_index_id)
        }
        # Two different room-index IDs can describe the same authenticated
        # room-area source after cross-view remapping. A single upstream area
        # receipt must never mint duplicate legacy + RCP ceiling quantities.
        new_room_area_quantity_ids = {
            _clean(ceiling.room_area_quantity_id)
            for ceiling in published_new_ceilings
            if _clean(getattr(ceiling, "room_area_quantity_id", ""))
        }
        if new_room_index_ids or new_room_area_quantity_ids:
            retained_legacy_ceilings = tuple(
                ceiling
                for ceiling in ceiling_result.canonical_ceilings
                if _clean(ceiling.source_room_index_id)
                not in new_room_index_ids
                and _clean(getattr(ceiling, "room_area_quantity_id", ""))
                not in new_room_area_quantity_ids
            )
            retained_shadow_ids = {
                _clean(ceiling.ceiling_quantity_id)
                for ceiling in retained_legacy_ceilings
                if _clean(ceiling.ceiling_quantity_id)
            }
            ceiling_result = replace(
                ceiling_result,
                claims=(),
                canonical_ceilings=retained_legacy_ceilings,
                quantity_evidence=tuple(
                    quantity
                    for quantity in ceiling_result.quantity_evidence
                    if _clean(quantity.quantity_id) in retained_shadow_ids
                ),
            )
        legacy_ceiling_quantities = _non_abstained(
            publish_live_ceiling_area_quantities(ceiling_result)
        )

    ceiling_quantities = (
        *new_ceiling_quantities,
        *legacy_ceiling_quantities,
    )
    summary["family_counts"]["ceiling_area"] = len(ceiling_quantities)
    if new_ceiling_quantities and legacy_ceiling_quantities:
        summary["ceiling_authority_path"] = (
            "cross_view_rcp_plus_legacy_nonoverlap"
        )
    elif new_ceiling_quantities:
        summary["ceiling_authority_path"] = (
            "cross_view_room_area_plus_rcp_finish"
        )
    elif legacy_ceiling_quantities:
        summary["ceiling_authority_path"] = "legacy_same_scope_ceiling_lining"
    else:
        summary["ceiling_authority_path"] = "unavailable"

    if ceiling_quantities:
        ceiling_runs: list[SealedSourceClosedRun] = []
        if new_ceiling_quantities:
            ceiling_runs.append(
                seal_live_ceiling_lining_run(
                    claim,
                    workspace_id=int(workspace_id),
                    project_id=project_id,
                )
            )
        if legacy_ceiling_quantities and ceiling_result is not None:
            ceiling_runs.append(
                seal_live_ceiling_area_run(
                    ceiling_result,
                    workspace_id=int(workspace_id),
                    project_id=project_id,
                )
            )
        ceiling_run = (
            ceiling_runs[0]
            if len(ceiling_runs) == 1
            else combine_source_closed_runs(
                tuple(ceiling_runs),
                project_id=project_id,
            )
        )
        family_runs.append(("ceiling_area", ceiling_run))

    # The extractor may reread the file across page/source passes. Reject
    # replaced input PDFs before writing *any* family/customer seal artifact.
    try:
        current_source_sha = _sha256(pdf_path)
    except OSError as exc:
        summary["status"] = "source_unavailable_during_production"
        summary["claim_reason_codes"] = [
            *summary["claim_reason_codes"], "source_read_failed_during_production"
        ]
        _write_json(output_dir / "production_summary.json", summary)
        raise RuntimeError("source PDF unavailable during production handoff") from exc
    if current_source_sha != source_sha256:
        summary["status"] = "source_changed_during_production"
        summary["claim_reason_codes"] = [*summary["claim_reason_codes"], "source_sha_changed"]
        _write_json(output_dir / "production_summary.json", summary)
        raise RuntimeError("source PDF SHA changed during production handoff")

    # Validate *all* families before writing a single sealed file: checking
    # after _write_run would leave a plausible but unauthenticated artifact.
    # This production command accepts exactly one PDF; sibling source digests
    # in its sealed envelope have no authenticated owner here.
    for family, run in family_runs:
        if set(run.source_sha256s) != {source_sha256}:
            summary["status"] = "source_envelope_conflict"
            summary["claim_reason_codes"] = [
                *summary["claim_reason_codes"],
                f"sealed_source_envelope_conflict:{family}",
            ]
            _write_json(output_dir / "production_summary.json", summary)
            raise RuntimeError(f"{family} sealed run has conflicting source SHA envelope")

    expected_by_family = {
        "floor_area": floor_quantities,
        "floor_finish_area": floor_finish_quantities,
        "opening_area": opening_area_quantities,
        "opening_count": opening_count_quantities,
        "ceiling_area": ceiling_quantities,
    }
    for family, run in family_runs:
        expected_quantities = expected_by_family[family]
        expected_ids = tuple(q.quantity_id for q in expected_quantities)
        actual_ids = tuple(q.quantity_id for q in run.quantities)
        by_producer_id = {q.quantity_id: q for q in expected_quantities}
        content_changed = False
        for sealed_row in run.quantities:
            original = by_producer_id.get(sealed_row.quantity_id)
            if original is None:
                content_changed = True
                continue
            if any(
                getattr(sealed_row, name, None) != getattr(original, name)
                for name in (
                    "family", "semantic_key", "value", "unit", "status",
                    "authority", "confidence", "abstained",
                )
            ) or any(
                getattr(sealed_row, field, None) != tuple(sorted(getattr(original, source_field)))
                for field, source_field in (
                    ("object_identity_refs", "input_entity_ids"),
                    ("evidence_ids", "evidence_ids"),
                    ("blocking_reasons", "blocking_reasons"),
                    ("reason_codes", "reason_codes"),
                )
            ):
                content_changed = True
        if (
            content_changed
            or             len(set(expected_ids)) != len(expected_ids)
            or len(set(actual_ids)) != len(actual_ids)
            or set(expected_ids) != set(actual_ids)
            or any(q.abstained or not q.lineage_ok for q in run.quantities)
        ):
            summary["status"] = "family_quantity_identity_conflict"
            summary["claim_reason_codes"] = [
                *summary["claim_reason_codes"],
                f"family_quantity_identity_conflict:{family}",
            ]
            _write_json(output_dir / "production_summary.json", summary)
            raise RuntimeError(
                f"{family} sealed quantities differ from authenticated publisher receipts"
            )

    # Project-level reconciliation is another source authority gate. Do not
    # publish even individually valid family files until the complete combined
    # seal passes duplicate, lineage and source-envelope checks.
    combined = None
    if family_runs:
        try:
            combined = combine_source_closed_runs(
                tuple(run for _, run in family_runs),
                project_id=project_id,
            )
        except Exception as exc:
            summary["status"] = "sealed_project_combination_failed"
            summary["claim_reason_codes"] = [
                *summary["claim_reason_codes"],
                f"sealed_project_combination_error:{type(exc).__name__}",
            ]
            _write_json(output_dir / "production_summary.json", summary)
            raise
        if set(combined.source_sha256s) != {source_sha256}:
            summary["status"] = "source_envelope_conflict"
            summary["claim_reason_codes"] = [
                *summary["claim_reason_codes"], "combined_source_envelope_conflict",
            ]
            _write_json(output_dir / "production_summary.json", summary)
            raise RuntimeError("combined sealed run has conflicting source SHA envelope")

    for family, run in family_runs:
        run_path = _write_run(output_dir, family, run)
        summary["family_run_ids"][family] = run.run_id
        summary["family_run_files"][family] = str(run_path)

    if combined is not None:
        combined_filename = (
            f"{project_id}.json"
            if clean_family_group == "all"
            else f"{project_id}.{clean_family_group}.json"
        )
        combined_path = output_dir / combined_filename
        combined_path.write_text(combined.to_json(), encoding="utf-8")
        summary["combined_run_file"] = str(combined_path)
        summary["combined_run_id"] = combined.run_id
        summary["combined_quantity_count"] = len(combined.quantities)
        summary["status"] = "sealed"
    else:
        summary["combined_quantity_count"] = 0
        summary["status"] = "no_sealable_quantities"

    _write_json(output_dir / "production_summary.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate source-closed production handoff JSON."
    )
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", type=int, default=1)
    parser.add_argument(
        "--family-group",
        choices=("all", "core", "surfaces"),
        default="all",
        help=(
            "Families to seal: all=current behavior, "
            "core=opening area/count only, surfaces=floor/ceiling only"
        ),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = generate_project_handoff(
        pdf_path=args.pdf,
        project_id=args.project_id,
        workspace_id=args.workspace_id,
        output_dir=args.output_dir,
        family_group=args.family_group,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
