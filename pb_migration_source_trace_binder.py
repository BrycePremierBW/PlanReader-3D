"""Authoritative source-trace binder for canonical M5 commercial projection.

Providers supply evidence references.  They must not self-certify project
identity, source SHA, or the current revision.  This binder constructs
``pb_quantity_takeoff_adapter.CommercialTakeoffSourceTrace`` from
orchestration-owned ProviderContext and fails closed on mismatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from pb_migration_contracts import QuantityEvidence, canonical_contract_json
from pb_migration_provider_envelope import ProviderContext, fingerprint_payload
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace


class SourceTraceBindingError(RuntimeError):
    """Raised when provider-supplied identity disagrees with authoritative context."""


@dataclass(frozen=True)
class ContributingSource:
    page: Optional[int]
    viewport_id: Optional[str]
    evidence_id: str
    page_id: Optional[str] = None


@dataclass(frozen=True)
class MultiSourceProvenance:
    primary: CommercialTakeoffSourceTrace
    contributors: tuple[ContributingSource, ...]
    evidence_fingerprint: str


def _meta(quantity: QuantityEvidence) -> Mapping[str, Any]:
    return quantity.metadata if isinstance(quantity.metadata, Mapping) else {}


def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    page = int(value)
    if page <= 0:
        raise SourceTraceBindingError("source page must be a positive 1-based integer")
    return page


def _workspace_record_id(context: ProviderContext) -> int:
    raw = context.workspace_record_id
    if raw is None:
        raise SourceTraceBindingError("authoritative workspace_record_id is required")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise SourceTraceBindingError("authoritative workspace_record_id must be a positive integer") from exc
    if value <= 0:
        raise SourceTraceBindingError("authoritative workspace_record_id must be a positive integer")
    return value


def bind_commercial_source_trace(
    quantity: QuantityEvidence,
    context: ProviderContext,
    *,
    primary_page: Optional[int] = None,
    primary_viewport_id: Optional[str] = None,
) -> CommercialTakeoffSourceTrace:
    """Build canonical M5 CommercialTakeoffSourceTrace from authoritative context."""
    meta = _meta(quantity)
    provider_project = str(meta.get("project_id") or "").strip() or None
    provider_sha = str(meta.get("source_sha256") or "").strip() or None
    provider_revision = str(meta.get("revision_id") or meta.get("revision_hash") or "").strip() or None

    if provider_project and provider_project != context.project_id:
        raise SourceTraceBindingError(
            f"provider project {provider_project!r} does not match authoritative {context.project_id!r}"
        )
    if provider_sha and provider_sha != context.source_sha256:
        raise SourceTraceBindingError("provider source SHA does not match authoritative document")
    if not context.revision_id or not context.current_revision_id:
        raise SourceTraceBindingError("authoritative revision and current revision are required")
    if context.revision_id != context.current_revision_id:
        raise SourceTraceBindingError("stale revision: measurement revision is not current")
    if provider_revision and provider_revision != context.current_revision_id:
        raise SourceTraceBindingError("provider revision is stale relative to current revision")

    page = primary_page
    if page is None:
        page = _optional_int(meta.get("source_page") or meta.get("page"))
    if page is None:
        raise SourceTraceBindingError("source page is required for commercial source trace")
    viewport = (
        primary_viewport_id
        or str(meta.get("viewport_id") or "").strip()
        or (context.owned_viewport_ids[0] if context.owned_viewport_ids else "")
    )
    if not viewport:
        raise SourceTraceBindingError("viewport is required for commercial source trace")

    try:
        return CommercialTakeoffSourceTrace(
            workspace_id=_workspace_record_id(context),
            project_id=context.project_id,
            document_id=context.document_id,
            source_sha256=context.source_sha256,
            source_page=str(page),
            viewport_id=viewport,
            revision_id=str(context.revision_id),
            current_revision_id=str(context.current_revision_id),
            evidence_ids=tuple(quantity.evidence_ids),
            canonical_entity_ids=tuple(quantity.input_entity_ids),
            metadata={
                "bound_by": "pb_migration_source_trace_binder",
                "provider_cannot_self_certify": True,
                "canonical_m5_module": "pb_quantity_takeoff_adapter",
            },
        )
    except Exception as exc:
        if isinstance(exc, SourceTraceBindingError):
            raise
        raise SourceTraceBindingError(str(exc)) from exc


def bind_multi_source_provenance(
    quantity: QuantityEvidence,
    context: ProviderContext,
    *,
    contributing_pages: Sequence[int] = (),
    contributing_viewports: Sequence[Optional[str]] = (),
) -> MultiSourceProvenance:
    """Keep one primary M5 trace plus structured contributing-source provenance."""
    pages = [int(p) for p in contributing_pages if p]
    if not pages:
        meta = _meta(quantity)
        raw_pages = meta.get("source_pages") or []
        if isinstance(raw_pages, (list, tuple)):
            pages = [int(p) for p in raw_pages]
        elif meta.get("source_page") not in (None, ""):
            pages = [int(meta["source_page"])]
    primary_page = pages[0] if pages else None
    viewports = list(contributing_viewports)
    primary_viewport = viewports[0] if viewports else None
    primary = bind_commercial_source_trace(
        quantity,
        context,
        primary_page=primary_page,
        primary_viewport_id=primary_viewport,
    )
    contributors: list[ContributingSource] = []
    evidence_ids = list(quantity.evidence_ids)
    for index, evidence_id in enumerate(evidence_ids):
        contributors.append(
            ContributingSource(
                page=pages[index] if index < len(pages) else primary_page,
                viewport_id=viewports[index] if index < len(viewports) else primary_viewport,
                evidence_id=evidence_id,
            )
        )
    if not contributors and primary_page is not None:
        contributors.append(
            ContributingSource(
                page=primary_page,
                viewport_id=primary_viewport,
                evidence_id=quantity.quantity_id,
            )
        )
    fingerprint = fingerprint_payload(
        {
            "primary_page": primary.source_page,
            "contributors": [canonical_contract_json(item) for item in contributors],
            "evidence_ids": list(quantity.evidence_ids),
        }
    )
    return MultiSourceProvenance(
        primary=primary,
        contributors=tuple(contributors),
        evidence_fingerprint=fingerprint,
    )
