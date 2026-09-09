"""Thin control-plane adapter for the frozen opening-count shadow provider.

Does not change extraction heuristics or the provider implementation.
NEW_SHADOW remains the registered authority state.  This adapter never
promotes the family and never loads gold.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from typing import Optional, Sequence

from pb_migration_contracts import QuantityEvidence
from pb_migration_provider_envelope import (
    EligibilityDecision,
    ProviderContext,
    ProviderDescriptor,
    ProviderResult,
    fingerprint_source_files,
)
from pb_opening_tag_normalization import normalize_opening_tag
from pb_provider_gold_isolation import assert_provider_gold_free
from pb_shadow_opening_count_gate import OPENING_COUNT_AUTHORITY_STATE, OPENING_COUNT_FAMILIES
from pb_shadow_opening_count_provider import (
    PROVIDER_ENGINE_ID,
    PROVIDER_ENGINE_VERSION,
    ShadowOpeningCountProvider,
)


ADAPTER_FAMILY = "opening_count"
_WD_KEY_RE = re.compile(r"^WD\d{1,3}$", re.IGNORECASE)
_CODE_MODULES = (
    "pb_shadow_opening_count_provider",
    "pb_shadow_opening_evidence",
    "pb_shadow_opening_count_gate",
    "pb_opening_count_control_adapter",
)


def is_production_opening_identity(semantic_key: str) -> bool:
    """Production-owned opening identity grammar. Not a benchmark mapping."""
    key = str(semantic_key or "").strip()
    if not key:
        return False
    if key in {"door_total", "window_total"}:
        return False
    if normalize_opening_tag(key) is not None:
        return True
    return bool(_WD_KEY_RE.fullmatch(key))


def opening_count_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=PROVIDER_ENGINE_ID,
        family=ADAPTER_FAMILY,
        provider_version=PROVIDER_ENGINE_VERSION,
        output_schema_version="1.0.0",
        code_fingerprint=fingerprint_source_files(_CODE_MODULES),
    )


class OpeningCountControlAdapter:
    """Control-plane envelope around ShadowOpeningCountProvider."""

    def __init__(self, provider: Optional[ShadowOpeningCountProvider] = None) -> None:
        assert_provider_gold_free(PROVIDER_ENGINE_ID, "pb_shadow_opening_count_provider")
        self._provider = provider or ShadowOpeningCountProvider()
        self.engine_id = self._provider.engine_id
        self.engine_version = self._provider.engine_version

    def descriptor(self) -> ProviderDescriptor:
        return opening_count_descriptor()

    def eligibility(self, context: ProviderContext) -> EligibilityDecision:
        reasons = []
        eligible = True
        if not context.source_sha256:
            eligible = False
            reasons.append("missing_source_sha")
        if not context.document_id:
            eligible = False
            reasons.append("missing_document")
        if OPENING_COUNT_AUTHORITY_STATE != "new_shadow":
            eligible = False
            reasons.append("unexpected_authority_state")
        if not reasons:
            reasons.append("opening_count_family_registered")
        return EligibilityDecision(
            eligible=eligible,
            family=ADAPTER_FAMILY,
            reasons=tuple(reasons),
            declared_identity_grammar="normalized_opening_tag|WD\\d+",
            eligible_semantic_keys=(),
        )

    def extract(self, context: ProviderContext) -> ProviderResult:
        if not context.source_pdf:
            raise ValueError("opening-count adapter requires context.source_pdf")
        pages = list(context.selected_pages) if context.selected_pages else None
        bundle = self._provider.extract_bundle(context.source_pdf, pages=pages)
        quantities = tuple(
            item
            for item in bundle.quantities
            if item.family in OPENING_COUNT_FAMILIES
        )
        return ProviderResult.build(
            descriptor=self.descriptor(),
            context=context,
            quantities=quantities,
            entities=bundle.entity_evidence,
        )

    def extract_quantities(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> tuple[QuantityEvidence, ...]:
        """M3-compatible pass-through. Extraction is unchanged."""
        return self._provider.extract_quantities(pdf_path, pages=pages)

    def extract_bundle(self, pdf_path: Path | str, pages: Optional[Sequence[int]] = None):
        return self._provider.extract_bundle(pdf_path, pages=pages)


def source_sha256(path: Path | str) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
