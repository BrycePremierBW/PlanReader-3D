"""Standard logical provider envelope for migration control-plane providers.

This does not replace QuantityEvidence / EntityEvidence.  It standardizes how a
provider is described, how a run is contextualized, and how a result is
fingerprinted before any gold join.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Optional, Protocol, Sequence

from pb_migration_contracts import (
    EntityEvidence,
    QuantityEvidence,
    canonical_contract_json,
    stable_contract_id,
)
from pb_provider_gold_isolation import REPO_ROOT


ENVELOPE_SCHEMA_VERSION = "1.0.1"


class ProviderResultBindingError(RuntimeError):
    """Raised when a ProviderResult is presented under a different identity/context."""


def fingerprint_payload(payload: object) -> str:
    return sha256(canonical_contract_json(payload).encode("utf-8")).hexdigest()


def fingerprint_source_files(module_names: Sequence[str]) -> str:
    chunks: list[str] = []
    for name in module_names:
        path = REPO_ROOT / f"{name}.py"
        if not path.is_file():
            raise FileNotFoundError(f"cannot fingerprint missing module {name}")
        chunks.append(f"{name}:{sha256(path.read_bytes()).hexdigest()}")
    return fingerprint_payload(chunks)


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    family: str
    provider_version: str
    output_schema_version: str
    code_fingerprint: str

    def fingerprint(self) -> str:
        return fingerprint_payload(
            {
                "provider_id": self.provider_id,
                "family": self.family,
                "provider_version": self.provider_version,
                "output_schema_version": self.output_schema_version,
                "code_fingerprint": self.code_fingerprint,
            }
        )


@dataclass(frozen=True)
class ProviderContext:
    run_id: str
    workspace_id: str
    project_id: str
    document_id: str
    source_sha256: str
    revision_id: Optional[str]
    current_revision_id: Optional[str]
    selected_pages: tuple[int, ...]
    owned_viewport_ids: tuple[str, ...]
    evidence_snapshot_id: str
    canonical_graph_snapshot_id: Optional[str] = None
    measurement_authority_snapshot_id: Optional[str] = None
    source_pdf: Optional[str] = None
    workspace_record_id: Optional[int] = 1
    owned_page_numbers: tuple[int, ...] = ()
    viewport_page_ownership: tuple[tuple[str, int], ...] = ()

    def fingerprint(self) -> str:
        return fingerprint_payload(
            {
                "run_id": self.run_id,
                "workspace_id": self.workspace_id,
                "workspace_record_id": self.workspace_record_id,
                "project_id": self.project_id,
                "document_id": self.document_id,
                "source_sha256": self.source_sha256,
                "revision_id": self.revision_id,
                "current_revision_id": self.current_revision_id,
                "selected_pages": list(self.selected_pages),
                "owned_viewport_ids": list(self.owned_viewport_ids),
                "owned_page_numbers": list(self.owned_page_numbers),
                "viewport_page_ownership": [list(item) for item in self.viewport_page_ownership],
                "evidence_snapshot_id": self.evidence_snapshot_id,
                "canonical_graph_snapshot_id": self.canonical_graph_snapshot_id,
                "measurement_authority_snapshot_id": self.measurement_authority_snapshot_id,
                "source_pdf": self.source_pdf,
            }
        )

    def trusted_page_numbers(self) -> frozenset[int]:
        pages = {int(page) for page in self.owned_page_numbers if int(page) > 0}
        for page in self.selected_pages:
            pages.add(int(page) + 1)
        return frozenset(pages)

    def trusted_viewport_ids(self) -> frozenset[str]:
        return frozenset(str(item) for item in self.owned_viewport_ids if str(item))

    def page_for_viewport(self, viewport_id: str) -> Optional[int]:
        wanted = str(viewport_id or "").strip()
        for viewport, page in self.viewport_page_ownership:
            if str(viewport) == wanted:
                return int(page)
        return None


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    family: str
    reasons: tuple[str, ...]
    declared_identity_grammar: str
    # Production identities that *could* be claimed. Never "keys the provider answered".
    eligible_semantic_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderResult:
    descriptor: ProviderDescriptor
    context_fingerprint: str
    quantities: tuple[QuantityEvidence, ...]
    entities: tuple[EntityEvidence, ...]
    result_fingerprint: str

    @staticmethod
    def build(
        *,
        descriptor: ProviderDescriptor,
        context: ProviderContext,
        quantities: Sequence[QuantityEvidence],
        entities: Sequence[EntityEvidence] = (),
    ) -> "ProviderResult":
        qty_tuple = tuple(quantities)
        ent_tuple = tuple(entities)
        context_fp = context.fingerprint()
        result_fp = fingerprint_payload(
            {
                "descriptor": descriptor.fingerprint(),
                "context_fingerprint": context_fp,
                "quantities": [item.to_dict() for item in qty_tuple],
                "entities": [item.to_dict() for item in ent_tuple],
            }
        )
        return ProviderResult(
            descriptor=descriptor,
            context_fingerprint=context_fp,
            quantities=qty_tuple,
            entities=ent_tuple,
            result_fingerprint=result_fp,
        )


def assert_provider_result_binding(
    result: ProviderResult,
    descriptor: ProviderDescriptor,
    context: ProviderContext,
) -> None:
    """Reject replay/substitution under a different provider, source, revision, or family."""
    if result.descriptor.family != descriptor.family:
        raise ProviderResultBindingError("provider result family does not match presented descriptor")
    if descriptor.family and result.descriptor.family != descriptor.family:
        raise ProviderResultBindingError("provider family mismatch")
    if result.descriptor.fingerprint() != descriptor.fingerprint():
        raise ProviderResultBindingError("provider descriptor fingerprint does not match presented provider")
    if result.context_fingerprint != context.fingerprint():
        raise ProviderResultBindingError(
            "provider result context fingerprint does not match presented source/revision/context"
        )
    rebuilt = ProviderResult.build(
        descriptor=descriptor,
        context=context,
        quantities=result.quantities,
        entities=result.entities,
    )
    if rebuilt.result_fingerprint != result.result_fingerprint:
        raise ProviderResultBindingError("provider result fingerprint does not match descriptor+context+outputs")
    if rebuilt.context_fingerprint != result.context_fingerprint:
        raise ProviderResultBindingError("provider context fingerprint replay mismatch")


class MigrationProvider(Protocol):
    def descriptor(self) -> ProviderDescriptor: ...

    def eligibility(self, context: ProviderContext) -> EligibilityDecision: ...

    def extract(self, context: ProviderContext) -> ProviderResult: ...


class M3ShadowEngineAdapter:
    """Keep existing M3 ``extract_quantities(pdf, pages)`` engines usable."""

    def __init__(self, provider: MigrationProvider) -> None:
        self._provider = provider
        self.engine_id = provider.descriptor().provider_id
        self.engine_version = provider.descriptor().provider_version

    def extract_quantities(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> tuple[QuantityEvidence, ...]:
        context = ProviderContext(
            run_id=stable_contract_id("run", {"pdf": str(pdf_path)}),
            workspace_id="m3",
            project_id="m3",
            document_id=stable_contract_id("doc", {"pdf": str(pdf_path)}),
            source_sha256="0" * 64,
            revision_id=None,
            current_revision_id=None,
            selected_pages=tuple(int(p) for p in (pages or ())),
            owned_viewport_ids=(),
            evidence_snapshot_id="m3",
            source_pdf=str(pdf_path),
        )
        # M3 adapters that wrap real extractors replace source SHA internally.
        return self._provider.extract(context).quantities
