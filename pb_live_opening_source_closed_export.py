"""Benchmark-neutral source-closed export for live physical opening areas.

This module bridges the already-authenticated live opening composition into the
existing source-closed run exporter. It does not discover openings, perform
benchmark identity mapping, read expected quantities, or weaken commercial
trace requirements.

Every sealed quantity is traced to the exact canonical physical opening,
document/revision/hash, owned viewport, source page and complete evidence set.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Sequence

from pb_live_opening_area_quantity_publication import (
    _opening_quantity,
    publish_live_opening_area_quantities,
)
from pb_live_physical_opening_void_composition import (
    LiveCanonicalOpeningObject,
    LivePhysicalOpeningVoidComposition,
)
from pb_migration_contracts import QuantityEvidence
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace
from pb_source_closed_run_export import (
    SealedSourceClosedRun,
    SourceClosedRunConflictError,
    seal_source_closed_run,
)


def _opening_map(
    canonical_openings: Sequence[LiveCanonicalOpeningObject],
) -> Mapping[str, LiveCanonicalOpeningObject]:
    by_id: dict[str, LiveCanonicalOpeningObject] = {}
    for opening in canonical_openings:
        if type(opening) is not LiveCanonicalOpeningObject:
            raise TypeError(
                "canonical_openings must contain LiveCanonicalOpeningObject"
            )
        canonical_id = str(opening.canonical_opening_id or "").strip()
        if not canonical_id:
            raise SourceClosedRunConflictError(
                "canonical opening identity must be non-empty"
            )
        if canonical_id in by_id:
            raise SourceClosedRunConflictError(
                f"duplicate canonical opening identity: {canonical_id}"
            )
        by_id[canonical_id] = opening
    return MappingProxyType(by_id)


def _opening_by_identity(
    composition: LivePhysicalOpeningVoidComposition,
) -> Mapping[str, LiveCanonicalOpeningObject]:
    return _opening_map(composition.canonical_openings)


def _build_opening_area_source_traces(
    quantities: Sequence[QuantityEvidence],
    canonical_openings: Sequence[LiveCanonicalOpeningObject],
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    openings = _opening_map(canonical_openings)
    traces: dict[str, CommercialTakeoffSourceTrace] = {}

    for quantity in quantities:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError(
                "opening area quantities must contain QuantityEvidence"
            )
        if quantity.family != "opening_area":
            raise SourceClosedRunConflictError(
                "opening-area export received a non-opening-area quantity"
            )
        if quantity.abstained:
            continue
        if len(quantity.input_entity_ids) != 1:
            raise SourceClosedRunConflictError(
                "opening area quantity must reference exactly one canonical opening"
            )
        canonical_id = str(quantity.input_entity_ids[0])
        opening = openings.get(canonical_id)
        if opening is None:
            raise SourceClosedRunConflictError(
                f"opening area quantity references unknown identity: {canonical_id}"
            )
        if opening.physical_opening_id != canonical_id:
            raise SourceClosedRunConflictError(
                f"canonical/physical opening identity mismatch: {canonical_id}"
            )
        # A final live claim can reach this exporter without re-running the
        # canonical publisher. Re-derive source-authenticated measurement and
        # identity before sealing: possession of old evidence IDs alone does
        # not authorize a different numeric area or measurement method.
        for receipts in (opening.evidence_ids, quantity.evidence_ids):
            if (
                not isinstance(receipts, (tuple, list))
                or not receipts
                or any(type(item) is not str or not item.strip() for item in receipts)
                or len(set(receipts)) != len(receipts)
            ):
                raise SourceClosedRunConflictError(
                    f"opening original source evidence is incomplete: {quantity.quantity_id}"
                )
        authenticated = _opening_quantity(opening)
        if (
            authenticated is None
            or quantity.quantity_id != authenticated.quantity_id
            or type(quantity.value) not in (int, float)
            or quantity.value != authenticated.value
            or quantity.authority != authenticated.authority
            or quantity.semantic_key != authenticated.semantic_key
            or quantity.unit != authenticated.unit
            or quantity.input_entity_ids != authenticated.input_entity_ids
            or set(quantity.evidence_ids) != set(authenticated.evidence_ids)
            or quantity.status != authenticated.status
        ):
            raise SourceClosedRunConflictError(
                f"opening area claim differs from original source measurement: {canonical_id}"
            )

        viewport_id = str(opening.viewport_id or "").strip()
        if not viewport_id:
            raise SourceClosedRunConflictError(
                f"opening area quantity lacks owned viewport: {canonical_id}"
            )
        # An explicitly retained source owner cannot be replayed onto a
        # different document/revision/snapshot even when metric area matches.
        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        for name, source_value in (
            ("document_id", opening.document_id),
            ("revision_id", opening.revision_id),
            ("source_sha256", opening.source_sha256),
            ("snapshot_id", opening.snapshot_id),
            ("viewport_id", opening.viewport_id),
            ("canonical_opening_id", canonical_id),
            ("physical_opening_id", opening.physical_opening_id),
        ):
            if metadata.get(name) is not None and str(metadata[name]).strip() != str(source_value).strip():
                raise SourceClosedRunConflictError(
                    f"opening source {name} identity mismatch: {quantity.quantity_id}"
                )
        evidence_ids = tuple(opening.evidence_ids)
        missing_evidence = set(quantity.evidence_ids) - set(evidence_ids)
        if missing_evidence:
            raise SourceClosedRunConflictError(
                "canonical opening trace does not cover quantity evidence: "
                + ", ".join(sorted(missing_evidence))
            )

        trace = CommercialTakeoffSourceTrace(
            workspace_id=workspace_id,
            project_id=project_id,
            document_id=opening.document_id,
            source_sha256=opening.source_sha256,
            source_page=opening.page_id,
            viewport_id=viewport_id,
            revision_id=opening.revision_id,
            current_revision_id=opening.revision_id,
            evidence_ids=evidence_ids,
            canonical_entity_ids=(canonical_id,),
            metadata={
                "family": quantity.family,
                "opening_kind": opening.opening_kind,
                "area_basis": opening.area_basis,
                "host_wall_id": opening.host_wall_id,
            },
        )
        if quantity.quantity_id in traces:
            raise SourceClosedRunConflictError(
                f"duplicate opening quantity id: {quantity.quantity_id}"
            )
        traces[quantity.quantity_id] = trace

    return MappingProxyType(traces)


def build_live_opening_area_source_traces(
    composition: LivePhysicalOpeningVoidComposition,
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    """Build exact source traces for quantities publishable from a composition."""

    if type(composition) is not LivePhysicalOpeningVoidComposition:
        raise TypeError(
            "composition must be LivePhysicalOpeningVoidComposition"
        )

    quantities = publish_live_opening_area_quantities(composition)
    return _build_opening_area_source_traces(
        quantities,
        composition.canonical_openings,
        workspace_id=workspace_id,
        project_id=project_id,
    )


def build_live_opening_area_claim_source_traces(
    claim,
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    """Build traces directly from the final live production claim."""
    from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim

    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")
    return _build_opening_area_source_traces(
        tuple(claim.opening_quantity_evidence),
        tuple(claim.canonical_openings),
        workspace_id=workspace_id,
        project_id=project_id,
    )


def seal_live_opening_area_claim_run(
    claim,
    *,
    workspace_id: int,
    project_id: str,
) -> SealedSourceClosedRun:
    """Seal opening areas already present on one final live production claim."""
    from pb_live_physical_net_wall_integration import LivePhysicalNetWallClaim

    if type(claim) is not LivePhysicalNetWallClaim:
        raise TypeError("claim must be LivePhysicalNetWallClaim")
    quantities = tuple(
        quantity
        for quantity in claim.opening_quantity_evidence
        if not quantity.abstained
    )
    traces = build_live_opening_area_claim_source_traces(
        claim,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return seal_source_closed_run(
        quantities,
        project_id=project_id,
        traces_by_quantity_id=traces,
    )


def seal_live_opening_area_run(
    composition: LivePhysicalOpeningVoidComposition,
    *,
    workspace_id: int,
    project_id: str,
) -> SealedSourceClosedRun:
    """Seal all currently corroborated opening-area quantities.

    The returned run remains benchmark-neutral. Frozen identity mapping and V2
    reconciliation happen only after this function has returned the sealed run.
    """

    quantities = publish_live_opening_area_quantities(composition)
    traces = build_live_opening_area_source_traces(
        composition,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return seal_source_closed_run(
        quantities,
        project_id=project_id,
        traces_by_quantity_id=traces,
    )


__all__ = [
    "build_live_opening_area_claim_source_traces",
    "build_live_opening_area_source_traces",
    "seal_live_opening_area_claim_run",
    "seal_live_opening_area_run",
]
