"""Production provider eligibility vs evaluation eligible universe.

These are two different contracts:

PRODUCTION PROVIDER ELIGIBILITY
    Owned by the control plane / provider adapter.
    Computed from source, context, and domain rules only.
    Must be computable BEFORE extract() runs.
    Must not read gold, mappings, scoring, or holdout.
    Must not shrink to the keys the provider happened to answer.

EVALUATION ELIGIBLE UNIVERSE
    Owned by the external evaluator for a named evaluation set.
    For the frozen opening-count development set the count is 24.
    Locked before gold join / before answers are inspected.
    Cannot be rewritten downward after seeing provider outputs.

The 24-item development denominator is an evaluation-universe fact.  It is not
a production identity list and must not be copied into the provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from pb_migration_provider_envelope import EligibilityDecision, ProviderContext, fingerprint_payload


OPENING_COUNT_DEVELOPMENT_EVALUATION_ELIGIBLE_COUNT = 24
OPENING_COUNT_PRODUCTION_IDENTITY_GRAMMAR = r"normalized_opening_tag|WD\d+"


class EligibilityContractError(RuntimeError):
    """Raised when eligibility is mutated from answers or gold."""


@dataclass(frozen=True)
class EvaluationEligibleUniverse:
    """Locked evaluator-owned eligible set. Independent of provider success."""

    family: str
    eligible_count: int
    eligible_keys: tuple[str, ...]
    source: str
    fingerprint: str
    locked: bool = True

    def assert_locked_development_opening_count(self) -> None:
        if self.family != "opening_count":
            return
        if self.source == "development_evaluator" and self.eligible_count != OPENING_COUNT_DEVELOPMENT_EVALUATION_ELIGIBLE_COUNT:
            raise EligibilityContractError(
                "opening-count development evaluation universe must remain 24; "
                f"got {self.eligible_count}"
            )

    def reject_answer_driven_shrink(self, answered: int) -> None:
        if not self.locked:
            raise EligibilityContractError("evaluation eligible universe must be locked")
        if (
            self.family == "opening_count"
            and self.source == "development_evaluator"
            and answered != self.eligible_count
            and self.eligible_count != OPENING_COUNT_DEVELOPMENT_EVALUATION_ELIGIBLE_COUNT
        ):
            raise EligibilityContractError("development evaluation universe drifted from 24")
        if self.eligible_count == answered and answered > 0 and self.source == "derived_from_answers":
            raise EligibilityContractError("evaluation eligible universe was derived from answers")


class LockedEvaluationUniverse:
    """Handle that refuses post-hoc denominator edits after outputs are known."""

    def __init__(self, universe: EvaluationEligibleUniverse) -> None:
        self._universe = universe
        universe.assert_locked_development_opening_count()

    @property
    def universe(self) -> EvaluationEligibleUniverse:
        return self._universe

    def replace_eligible_count(self, new_count: int) -> None:
        raise EligibilityContractError(
            "evaluation eligible universe is locked; evaluator cannot choose a "
            f"smaller denominator after seeing outputs (attempted {new_count})"
        )

    def replace_eligible_keys(self, keys: Sequence[str]) -> None:
        raise EligibilityContractError(
            "evaluation eligible universe is locked; keys cannot be rewritten from provider output"
        )


def lock_evaluation_universe(
    *,
    family: str,
    eligible_count: int,
    eligible_keys: Sequence[str] = (),
    source: str,
) -> LockedEvaluationUniverse:
    if eligible_count < 0:
        raise EligibilityContractError("eligible_count cannot be negative")
    keys = tuple(str(item) for item in eligible_keys)
    if keys and len(keys) != eligible_count:
        raise EligibilityContractError("eligible_keys length must match eligible_count when keys are supplied")
    payload = {
        "family": family,
        "eligible_count": eligible_count,
        "eligible_keys": list(keys),
        "source": source,
    }
    universe = EvaluationEligibleUniverse(
        family=family,
        eligible_count=eligible_count,
        eligible_keys=keys,
        source=source,
        fingerprint=fingerprint_payload(payload),
        locked=True,
    )
    return LockedEvaluationUniverse(universe)


def lock_opening_count_development_universe(
    eligible_keys: Sequence[str] = (),
) -> LockedEvaluationUniverse:
    """Lock the frozen development evaluation denominator at 24.

    Keys are optional.  When omitted, only the count is locked.  Keys must never
    be harvested from provider answers.
    """
    if eligible_keys and len(tuple(eligible_keys)) != OPENING_COUNT_DEVELOPMENT_EVALUATION_ELIGIBLE_COUNT:
        raise EligibilityContractError(
            "opening-count development universe keys must be 24 when supplied"
        )
    return lock_evaluation_universe(
        family="opening_count",
        eligible_count=OPENING_COUNT_DEVELOPMENT_EVALUATION_ELIGIBLE_COUNT,
        eligible_keys=eligible_keys,
        source="development_evaluator",
    )


def production_opening_count_eligibility(context: ProviderContext) -> EligibilityDecision:
    """Source/context/domain eligibility. No gold identities. No answered keys."""
    reasons: list[str] = []
    eligible = True
    sha = str(context.source_sha256 or "").strip().lower()
    if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        eligible = False
        reasons.append("missing_or_invalid_source_sha")
    if not str(context.document_id or "").strip():
        eligible = False
        reasons.append("missing_document")
    if not str(context.project_id or "").strip():
        eligible = False
        reasons.append("missing_project")
    if context.revision_id and context.current_revision_id:
        if context.revision_id != context.current_revision_id:
            eligible = False
            reasons.append("stale_revision")
    if not reasons:
        reasons.append("opening_count_domain_context_complete")
        reasons.append("computed_before_extract")
    return EligibilityDecision(
        eligible=eligible,
        family="opening_count",
        reasons=tuple(reasons),
        declared_identity_grammar=OPENING_COUNT_PRODUCTION_IDENTITY_GRAMMAR,
        eligible_semantic_keys=(),
    )


def eligibility_before_extract(
    decide,
    context: ProviderContext,
) -> EligibilityDecision:
    """Run a production eligibility function and mark it as pre-extract."""
    decision = decide(context)
    if decision.eligible_semantic_keys:
        raise EligibilityContractError(
            "production opening-count eligibility must not enumerate gold/answered semantic keys"
        )
    return decision
