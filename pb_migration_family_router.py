"""Central family-aware authority router.

This is the ONLY migration layer that decides whether the selected commercial
claim comes from legacy or a new provider.  Providers never choose authority.

States:
- LEGACY_AUTHORITATIVE: legacy selected; new does not run
- NEW_SHADOW: legacy selected; new may run diagnostically
- NEW_SELECTIVE: eligible+valid new -> new; abstention/conflict -> legacy fallback
- NEW_AUTHORITATIVE: new owns the family scope; abstention is NOT silently
  replaced by legacy (authoritative_abstention)

Invariant: exactly one selected claim per family + project + revision + semantic_key.
Never final = legacy + new for the same scoped claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from pb_migration_claim_arbiter import (
    ArbitrationReport,
    ClaimKey,
    arbitrate_claims,
    assert_exactly_one_selected,
    claim_key,
    is_accepted_quantity,
    is_blocked_quantity,
)
from pb_migration_contracts import MigrationAuthorityState, QuantityEvidence
from pb_migration_decision_ledger import (
    MigrationDecisionLedger,
    record_state_transition,
)
from pb_migration_provider_envelope import (
    EligibilityDecision,
    ProviderContext,
    ProviderDescriptor,
    ProviderResult,
    ProviderResultBindingError,
    assert_provider_result_binding,
)
from pb_provider_gold_isolation import assert_provider_gold_free


class FamilyRouterError(RuntimeError):
    """Raised when routing would violate the single-authority invariant."""


@dataclass
class FamilyRegistration:
    family: str
    provider_id: str
    provider_module: str
    default_state: str = MigrationAuthorityState.NEW_SHADOW.value
    trusted_descriptor: Optional[ProviderDescriptor] = None


@dataclass(frozen=True)
class SelectedClaim:
    claim: ClaimKey
    selected_authority: str
    quantity: Optional[QuantityEvidence]
    diagnostic_new: Optional[QuantityEvidence]
    fallback_reason: str
    blockers: tuple[str, ...]


@dataclass
class RoutingResult:
    family: str
    state: str
    selected: tuple[SelectedClaim, ...]
    arbitration: ArbitrationReport
    new_ran: bool
    commercially_selected_from_new: bool

    def selected_keys(self) -> tuple[ClaimKey, ...]:
        return tuple(item.claim for item in self.selected)


_DEFAULT_REGISTRY = {
    "opening_count": FamilyRegistration(
        family="opening_count",
        provider_id="shadow_opening_count",
        provider_module="pb_shadow_opening_count_provider",
        default_state=MigrationAuthorityState.NEW_SHADOW.value,
    ),
}


class FamilyAuthorityRouter:
    """Family-scoped authority router with rollback and an in-memory selection cache."""

    def __init__(
        self,
        ledger: MigrationDecisionLedger,
        *,
        registry: Optional[dict[str, FamilyRegistration]] = None,
    ) -> None:
        self.ledger = ledger
        self.registry = dict(registry or _DEFAULT_REGISTRY)
        self._selection_cache: dict[tuple[str, str, str], RoutingResult] = {}

    def current_state(self, family: str) -> str:
        registration = self.registry.get(family)
        default = registration.default_state if registration else MigrationAuthorityState.LEGACY_AUTHORITATIVE.value
        return self.ledger.family_state(family, default=default)

    def invalidate_cache(self, family: Optional[str] = None) -> None:
        if family is None:
            self._selection_cache.clear()
            return
        for key in list(self._selection_cache):
            if key[0] == family:
                self._selection_cache.pop(key, None)

    def set_state(
        self,
        family: str,
        new_state: str,
        *,
        project_id: str,
        provider: ProviderDescriptor,
        reason: str,
        run_id: str = "",
    ) -> str:
        allowed = {item.value for item in MigrationAuthorityState}
        if new_state not in allowed:
            raise FamilyRouterError(f"unknown migration state {new_state!r}")
        prior = self.current_state(family)
        record_state_transition(
            self.ledger,
            family=family,
            provider_id=provider.provider_id,
            provider_version=provider.provider_version,
            provider_fingerprint=provider.code_fingerprint,
            prior_state=prior,
            current_state=new_state,
            project_id=project_id,
            selected_authority="legacy" if new_state in {
                MigrationAuthorityState.LEGACY_AUTHORITATIVE.value,
                MigrationAuthorityState.NEW_SHADOW.value,
            } else "new",
            fallback_reason=reason,
            run_id=run_id,
            extra={"transition": f"{prior}->{new_state}"},
        )
        self.invalidate_cache(family)
        return new_state

    def registered_provider_descriptor(self, family: str) -> ProviderDescriptor:
        """Return the trusted production descriptor from the existing family registry."""
        registration = self.registry.get(family)
        if registration is None:
            raise FamilyRouterError(f"family {family!r} is not registered")
        if registration.trusted_descriptor is not None:
            descriptor = registration.trusted_descriptor
        elif family == "opening_count" and registration.provider_id == "shadow_opening_count":
            from pb_opening_count_control_adapter import opening_count_descriptor

            descriptor = opening_count_descriptor()
        else:
            raise FamilyRouterError(
                f"registered family {family!r} has no trusted production descriptor"
            )
        if str(descriptor.family) != str(family):
            raise FamilyRouterError(
                f"registered descriptor family {descriptor.family!r} does not match {family!r}"
            )
        if str(descriptor.provider_id) != str(registration.provider_id):
            raise FamilyRouterError(
                f"registered descriptor provider {descriptor.provider_id!r} "
                f"does not match registry {registration.provider_id!r}"
            )
        return descriptor

    def rollback(
        self,
        family: str,
        *,
        target: str,
        project_id: str,
        provider: ProviderDescriptor,
        reason: str,
        run_id: str = "",
    ) -> str:
        """Family-scoped rollback. Does not rewrite estimator-approved commercial rows."""
        current = self.current_state(family)
        if target not in {
            MigrationAuthorityState.NEW_SHADOW.value,
            MigrationAuthorityState.LEGACY_AUTHORITATIVE.value,
        }:
            raise FamilyRouterError("rollback target must be new_shadow or legacy_authoritative")
        if current not in {
            MigrationAuthorityState.NEW_SELECTIVE.value,
            MigrationAuthorityState.NEW_AUTHORITATIVE.value,
            MigrationAuthorityState.NEW_SHADOW.value,
        } and target == MigrationAuthorityState.LEGACY_AUTHORITATIVE.value:
            pass
        return self.set_state(
            family,
            target,
            project_id=project_id,
            provider=provider,
            reason=reason,
            run_id=run_id,
        )

    def route(
        self,
        *,
        family: str,
        context: ProviderContext,
        legacy_quantities: Sequence[QuantityEvidence],
        new_result: Optional[ProviderResult],
        eligibility: Optional[EligibilityDecision] = None,
        execute_new: bool = True,
    ) -> RoutingResult:
        state = self.current_state(family)
        cache_key = (family, context.project_id, context.revision_id or "")
        registration = self.registry.get(family)
        new_ran = False
        if new_result is not None:
            trusted_descriptor = self.registered_provider_descriptor(family)
            if str(new_result.descriptor.family) != str(family):
                raise FamilyRouterError(
                    f"provider result family {new_result.descriptor.family!r} "
                    f"does not match routed family {family!r}"
                )
            try:
                assert_provider_result_binding(new_result, trusted_descriptor, context)
            except ProviderResultBindingError as exc:
                raise FamilyRouterError(str(exc)) from exc
        if state == MigrationAuthorityState.LEGACY_AUTHORITATIVE.value:
            execute_new = False
        if registration is not None and execute_new and new_result is not None:
            assert_provider_gold_free(registration.provider_id, registration.provider_module)
            new_ran = True
        new_quantities = list(new_result.quantities) if new_result is not None and new_ran else []
        legacy_by_key = {item.semantic_key: item for item in legacy_quantities if not item.abstained}
        new_by_key: dict[str, QuantityEvidence] = {}
        new_abstentions: dict[str, QuantityEvidence] = {}
        new_blocked: dict[str, QuantityEvidence] = {}
        for item in new_quantities:
            if item.family != family and item.family not in {"window_count", "door_count", "opening_count"}:
                continue
            if item.abstained:
                new_abstentions[item.semantic_key] = item
            elif is_blocked_quantity(item):
                new_blocked[item.semantic_key] = item
            elif is_accepted_quantity(item):
                new_by_key.setdefault(item.semantic_key, item)

        arbitration = arbitrate_claims(
            family=family,
            project_id=context.project_id,
            revision_id=context.revision_id,
            new_quantities=new_quantities,
            legacy_keys=tuple(legacy_by_key),
        )
        conflict_keys = {
            item.claim.semantic_key
            for item in arbitration.findings
            if item.kind
            in {"duplicate_new_claim", "conflicting_new_claims", "unresolved_mixed_claim"}
        }

        eligible_keys = set(eligibility.eligible_semantic_keys) if eligibility is not None else set()
        family_eligible = True if eligibility is None else eligibility.eligible
        all_keys = sorted(
            set(legacy_by_key)
            | set(new_by_key)
            | set(new_abstentions)
            | set(new_blocked)
            | eligible_keys
        )

        selected: list[SelectedClaim] = []
        for key in all_keys:
            claim = claim_key(
                family=family,
                project_id=context.project_id,
                revision_id=context.revision_id,
                semantic_key=key,
            )
            legacy_row = legacy_by_key.get(key)
            new_row = new_by_key.get(key)
            abstained = new_abstentions.get(key)
            blocked = new_blocked.get(key)
            mixed = (new_row is not None and (abstained is not None or blocked is not None))
            claim_eligible = family_eligible and (not eligible_keys or key in eligible_keys)
            selected.append(
                self._select_one(
                    state=state,
                    claim=claim,
                    claim_eligible=claim_eligible,
                    legacy_row=legacy_row,
                    new_row=new_row,
                    abstained=abstained,
                    blocked=blocked,
                    conflict=key in conflict_keys or mixed,
                )
            )
            self._record_claim(
                family=family,
                state=state,
                context=context,
                claim=selected[-1],
                provider=new_result.descriptor if new_result is not None else None,
            )

        result = RoutingResult(
            family=family,
            state=state,
            selected=tuple(selected),
            arbitration=arbitration,
            new_ran=new_ran,
            commercially_selected_from_new=any(item.selected_authority == "new" for item in selected),
        )
        assert_exactly_one_selected(result.selected_keys())
        if result.commercially_selected_from_new and state == MigrationAuthorityState.NEW_SHADOW.value:
            raise FamilyRouterError("NEW_SHADOW leaked a commercially selected new claim")
        if state == MigrationAuthorityState.NEW_SHADOW.value and result.commercially_selected_from_new:
            raise FamilyRouterError("NEW_SHADOW must select legacy only")
        self._selection_cache[cache_key] = result
        return result

    def _select_one(
        self,
        *,
        state: str,
        claim: ClaimKey,
        claim_eligible: bool,
        legacy_row: Optional[QuantityEvidence],
        new_row: Optional[QuantityEvidence],
        abstained: Optional[QuantityEvidence],
        conflict: bool,
        blocked: Optional[QuantityEvidence] = None,
    ) -> SelectedClaim:
        diagnostic = new_row or abstained or blocked
        if state in {
            MigrationAuthorityState.LEGACY_AUTHORITATIVE.value,
            MigrationAuthorityState.NEW_SHADOW.value,
        }:
            return SelectedClaim(
                claim=claim,
                selected_authority="legacy",
                quantity=legacy_row,
                diagnostic_new=diagnostic,
                fallback_reason="" if legacy_row is not None else "legacy_missing",
                blockers=("new_is_diagnostic_only",) if state == MigrationAuthorityState.NEW_SHADOW.value else (),
            )

        if state == MigrationAuthorityState.NEW_SELECTIVE.value:
            if not claim_eligible:
                return SelectedClaim(claim, "legacy", legacy_row, diagnostic, "not_provider_eligible", ())
            if conflict:
                return SelectedClaim(claim, "legacy", legacy_row, diagnostic, "unresolved_authority_conflict", ("conflicting_new_claims",))
            if abstained is not None and new_row is None:
                return SelectedClaim(claim, "legacy", legacy_row, abstained, "new_abstention_fallback", abstained.blocking_reasons)
            if blocked is not None and new_row is None:
                return SelectedClaim(claim, "legacy", legacy_row, blocked, "new_blocked_fallback", blocked.blocking_reasons)
            if new_row is not None:
                return SelectedClaim(claim, "new", new_row, new_row, "", ())
            return SelectedClaim(claim, "legacy", legacy_row, diagnostic, "new_missing_fallback", ())

        if state == MigrationAuthorityState.NEW_AUTHORITATIVE.value:
            if conflict:
                return SelectedClaim(
                    claim,
                    "new_authoritative_abstention",
                    None,
                    diagnostic,
                    "authoritative_conflict_no_legacy_substitution",
                    ("conflicting_new_claims",),
                )
            if abstained is not None and new_row is None:
                return SelectedClaim(
                    claim,
                    "new_authoritative_abstention",
                    None,
                    abstained,
                    "authoritative_abstention_no_legacy_substitution",
                    abstained.blocking_reasons,
                )
            if blocked is not None and new_row is None:
                return SelectedClaim(
                    claim,
                    "new_authoritative_abstention",
                    None,
                    blocked,
                    "authoritative_blocked_no_legacy_substitution",
                    blocked.blocking_reasons,
                )
            if new_row is not None:
                return SelectedClaim(claim, "new", new_row, new_row, "", ())
            return SelectedClaim(
                claim,
                "new_authoritative_abstention",
                None,
                diagnostic,
                "authoritative_scope_unanswered",
                ("new_owns_family_scope",),
            )

        raise FamilyRouterError(f"unhandled migration state {state!r}")

    def _record_claim(
        self,
        *,
        family: str,
        state: str,
        context: ProviderContext,
        claim: SelectedClaim,
        provider: Optional[ProviderDescriptor],
    ) -> None:
        record_state_transition(
            self.ledger,
            family=family,
            provider_id=provider.provider_id if provider else "none",
            provider_version=provider.provider_version if provider else "",
            provider_fingerprint=provider.code_fingerprint if provider else "",
            prior_state=state,
            current_state=state,
            project_id=context.project_id,
            revision_id=context.revision_id or "",
            semantic_claim=claim.claim.semantic_key,
            selected_authority=claim.selected_authority,
            fallback_reason=claim.fallback_reason,
            blocker=";".join(claim.blockers),
            run_id=context.run_id,
            extra={"quantity_id": None if claim.quantity is None else claim.quantity.quantity_id},
        )
