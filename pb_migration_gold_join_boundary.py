"""Process boundary: extract and freeze before any gold join.

Pipeline:

    source/context
    -> production eligibility (no gold)
    -> provider extract
    -> ProviderResult frozen/fingerprinted
    -> shadow comparison frozen
    -> seal (live extract callback discarded)
    -> ONLY THEN gold/evaluator stage

The evaluator receives a sealed artifact.  It does not receive a provider and
cannot invoke extract().  A boolean flag is not the boundary; the missing
callback is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from pb_gold_free_shadow_runner import compare_shadow_quantities
from pb_legacy_extractor_adapter import LegacyExtractionResult
from pb_migration_contracts import QuantityEvidence, ShadowQuantityComparison
from pb_migration_eligibility import EligibilityDecision
from pb_migration_provider_envelope import ProviderContext, ProviderResult, fingerprint_payload


class GoldJoinBoundaryError(RuntimeError):
    """Raised when extract is attempted after seal or gold is joined too early."""


@dataclass(frozen=True)
class FrozenProviderOutput:
    result: ProviderResult
    quantities: tuple[QuantityEvidence, ...]
    result_fingerprint: str
    context_fingerprint: str


@dataclass(frozen=True)
class SealedShadowBundle:
    frozen: FrozenProviderOutput
    comparisons: tuple[ShadowQuantityComparison, ...]
    comparison_fingerprint: str
    eligibility: EligibilityDecision
    gold_join_permitted: bool = True

    def extract(self, *args: Any, **kwargs: Any) -> None:
        raise GoldJoinBoundaryError("provider extract is sealed; gold join cannot re-extract")


class GoldJoinEvaluator:
    """Evaluator-side scorer with no live provider callback."""

    def __init__(self, sealed: SealedShadowBundle) -> None:
        self._sealed = sealed
        self._gold_loaded = False

    @property
    def provider(self) -> None:
        raise GoldJoinBoundaryError("evaluator has no live provider")

    def extract(self, *args: Any, **kwargs: Any) -> None:
        raise GoldJoinBoundaryError("evaluator cannot re-extract after gold join")

    def load_gold_and_score(self, gold_payload: Any) -> dict[str, Any]:
        self._gold_loaded = True
        frozen = self._sealed.frozen.quantities
        return {
            "gold_joined_after_freeze": True,
            "used_result_fingerprint": self._sealed.frozen.result_fingerprint,
            "used_quantity_ids": [item.quantity_id for item in frozen],
            "gold_payload_type": type(gold_payload).__name__,
            "reextract_possible": False,
        }


class MigrationExtractPipeline:
    """Owns extract → freeze → compare → seal. Discards the provider at seal."""

    def __init__(self) -> None:
        self._provider: Any = None
        self._sealed: Optional[SealedShadowBundle] = None

    def run(
        self,
        *,
        provider: Any,
        context: ProviderContext,
        eligibility: EligibilityDecision,
        legacy_output: Optional[LegacyExtractionResult] = None,
        legacy_quantities: Sequence[QuantityEvidence] = (),
    ) -> SealedShadowBundle:
        if self._sealed is not None:
            raise GoldJoinBoundaryError("pipeline already sealed")
        self._provider = provider
        result = provider.extract(context)
        if not isinstance(result, ProviderResult):
            raise TypeError("provider.extract must return ProviderResult")
        frozen = FrozenProviderOutput(
            result=result,
            quantities=tuple(result.quantities),
            result_fingerprint=result.result_fingerprint,
            context_fingerprint=result.context_fingerprint,
        )
        comparisons: tuple[ShadowQuantityComparison, ...] = ()
        if legacy_output is not None:
            comparisons = tuple(compare_shadow_quantities(legacy_output, frozen.quantities))
        sealed = SealedShadowBundle(
            frozen=frozen,
            comparisons=comparisons,
            comparison_fingerprint=fingerprint_payload([row.to_dict() for row in comparisons]),
            eligibility=eligibility,
        )
        self._provider = None
        self._sealed = sealed
        return sealed

    def extract(self, *args: Any, **kwargs: Any) -> None:
        if self._sealed is not None:
            raise GoldJoinBoundaryError("pipeline sealed; extract callback discarded")
        raise GoldJoinBoundaryError("extract is only available inside run() before seal")
