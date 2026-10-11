"""Source-closed export for canonical ceiling-area quantities.

Consumes only FIRM canonical ceiling QuantityEvidence already published by
publish_live_ceiling_area_quantities. This module does not discover ceilings,
measure geometry, promote customer rows, or read benchmark truth.
"""
from __future__ import annotations

import math
from types import MappingProxyType
from typing import Mapping

from pb_live_ceiling_area_quantity_publication import (
    publish_live_ceiling_area_quantities,
)
from pb_live_ceiling_lining_integration import LiveCeilingLiningResult
from pb_migration_contracts import QuantityEvidence
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace
from pb_source_closed_run_export import (
    SealedSourceClosedRun,
    SourceClosedRunConflictError,
    seal_source_closed_run,
)


def _clean(value: object) -> str:
    return str(value or "").strip()


def build_live_ceiling_area_source_traces(
    result: LiveCeilingLiningResult,
    *,
    workspace_id: int,
    project_id: str,
) -> Mapping[str, CommercialTakeoffSourceTrace]:
    """Build exact canonical-ceiling source traces for final ceiling quantities."""
    if type(result) is not LiveCeilingLiningResult:
        raise TypeError("result must be LiveCeilingLiningResult")

    ceilings = {}
    for ceiling in result.canonical_ceilings:
        canonical_id = _clean(ceiling.canonical_ceiling_id)
        if not canonical_id:
            continue
        if canonical_id in ceilings:
            raise SourceClosedRunConflictError(
                f"duplicate canonical ceiling identity: {canonical_id}"
            )
        ceilings[canonical_id] = ceiling

    traces: dict[str, CommercialTakeoffSourceTrace] = {}
    for quantity in publish_live_ceiling_area_quantities(result):
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("ceiling quantities must contain QuantityEvidence")
        if quantity.family != "ceiling_lining":
            raise SourceClosedRunConflictError(
                f"non-ceiling quantity reached ceiling exporter: {quantity.quantity_id}"
            )
        if quantity.abstained or quantity.value is None:
            continue
        if len(quantity.input_entity_ids) != 1:
            raise SourceClosedRunConflictError(
                f"ceiling quantity must own one canonical ceiling: {quantity.quantity_id}"
            )

        canonical_id = _clean(quantity.input_entity_ids[0])
        ceiling = ceilings.get(canonical_id)
        if ceiling is None:
            raise SourceClosedRunConflictError(
                f"ceiling quantity references unknown canonical ceiling: {canonical_id}"
            )
        try:
            qvalue = float(quantity.value)
            ceiling_value = float(ceiling.area_m2)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceClosedRunConflictError(
                f"ceiling quantity is not metric: {quantity.quantity_id}"
            ) from exc
        if (
            not math.isfinite(qvalue)
            or qvalue <= 0.0
            or not math.isfinite(ceiling_value)
            or abs(qvalue - ceiling_value) > 1e-9
        ):
            raise SourceClosedRunConflictError(
                f"ceiling quantity value disagrees with canonical ceiling: {quantity.quantity_id}"
            )

        metadata = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        if _clean(metadata.get("canonical_ceiling_id")) != canonical_id:
            raise SourceClosedRunConflictError(
                f"ceiling quantity canonical identity mismatch: {quantity.quantity_id}"
            )
        if (
            _clean(metadata.get("source_sha256")).lower()
            != _clean(ceiling.source_sha256).lower()
        ):
            raise SourceClosedRunConflictError(
                f"ceiling quantity source SHA mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("revision_id")) != _clean(ceiling.revision_id):
            raise SourceClosedRunConflictError(
                f"ceiling quantity revision mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("viewport_id")) != _clean(ceiling.viewport_id):
            raise SourceClosedRunConflictError(
                f"ceiling quantity viewport mismatch: {quantity.quantity_id}"
            )
        if _clean(metadata.get("page_no")) != str(ceiling.source_page):
            raise SourceClosedRunConflictError(
                f"ceiling quantity page mismatch: {quantity.quantity_id}"
            )

        # Source metadata is meaningful only with intact original receipts.
        # Deduplication here must not conceal a malformed producer universe.
        for receipts in (ceiling.evidence_ids, quantity.evidence_ids):
            if (
                not isinstance(receipts, (tuple, list))
                or not receipts
                or any(type(value) is not str or not value.strip() for value in receipts)
                or len(set(receipts)) != len(receipts)
            ):
                raise SourceClosedRunConflictError(
                    f"ceiling source evidence receipts are incomplete: {quantity.quantity_id}"
                )
        evidence_ids = tuple(ceiling.evidence_ids)
        if not set(quantity.evidence_ids).issubset(set(evidence_ids)):
            raise SourceClosedRunConflictError(
                f"ceiling source trace does not cover quantity evidence: {quantity.quantity_id}"
            )

        points = tuple(ceiling.polygon_pdf_pts or ())
        if not ceiling.geometry_complete or len(points) < 3:
            raise SourceClosedRunConflictError(
                f"ceiling source polygon is incomplete: {quantity.quantity_id}"
            )
        source_bbox = None
        if points:
            try:
                xs = tuple(float(point[0]) for point in points)
                ys = tuple(float(point[1]) for point in points)
            except (TypeError, ValueError, IndexError) as exc:
                raise SourceClosedRunConflictError(
                    f"ceiling source polygon is invalid: {quantity.quantity_id}"
                ) from exc
            if xs and ys:
                if (
                    not all(math.isfinite(v) for v in (*xs, *ys))
                    or max(xs) <= min(xs)
                    or max(ys) <= min(ys)
                ):
                    raise SourceClosedRunConflictError(
                        f"ceiling source polygon is invalid: {quantity.quantity_id}"
                    )
                source_bbox = (min(xs), min(ys), max(xs), max(ys))

        trace = CommercialTakeoffSourceTrace(
            workspace_id=int(workspace_id),
            project_id=str(project_id),
            document_id=ceiling.document_id,
            source_sha256=ceiling.source_sha256,
            source_page=str(ceiling.source_page),
            viewport_id=ceiling.viewport_id,
            revision_id=ceiling.revision_id,
            current_revision_id=ceiling.revision_id,
            evidence_ids=evidence_ids,
            canonical_entity_ids=(canonical_id,),
            source_bbox=source_bbox,
            metadata={
                "family": "ceiling_lining",
                "canonical_ceiling_id": canonical_id,
                "room_entity_id": ceiling.room_entity_id,
                "room_area_quantity_id": ceiling.room_area_quantity_id,
                "shadow_ceiling_quantity_id": ceiling.ceiling_quantity_id,
                "source_room_index_id": ceiling.source_room_index_id,
                "measurement_authority": ceiling.measurement_authority,
                "figured_dimension_ids": tuple(ceiling.figured_dimension_ids),
                "physical_scale_record_id": ceiling.physical_scale_record_id,
                "finish_descriptor": ceiling.finish_descriptor,
            },
        )
        if quantity.quantity_id in traces:
            raise SourceClosedRunConflictError(
                f"duplicate ceiling quantity id: {quantity.quantity_id}"
            )
        traces[quantity.quantity_id] = trace

    return MappingProxyType(traces)


def seal_live_ceiling_area_run(
    result: LiveCeilingLiningResult,
    *,
    workspace_id: int,
    project_id: str,
) -> SealedSourceClosedRun:
    """Seal final canonical ceiling-area quantities on canonical identity."""
    quantities = tuple(
        quantity
        for quantity in publish_live_ceiling_area_quantities(result)
        if not quantity.abstained and quantity.value is not None
    )
    traces = build_live_ceiling_area_source_traces(
        result,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return seal_source_closed_run(
        quantities,
        project_id=project_id,
        traces_by_quantity_id=traces,
    )


__all__ = [
    "build_live_ceiling_area_source_traces",
    "seal_live_ceiling_area_run",
]
