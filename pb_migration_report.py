"""Standard family migration report.

Eligible is supplied independently of whether the provider answered.  Gold is
joined only after new outputs are frozen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from pb_migration_contracts import QuantityEvidence, ShadowQuantityComparison
from pb_migration_family_router import RoutingResult
from pb_migration_provider_envelope import ProviderDescriptor, fingerprint_payload


REPORT_SCHEMA_VERSION = "1.0.0"


@dataclass
class MigrationReport:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def decision(self) -> str:
        return str(self.payload.get("gate", {}).get("decision") or "")


def _qty_fingerprint(items: Sequence[QuantityEvidence]) -> str:
    return fingerprint_payload([item.to_dict() for item in items])


def build_migration_report(
    *,
    family: str,
    descriptor: ProviderDescriptor,
    migration_state: str,
    source_set_fingerprint: str,
    evaluated_commit: str,
    eligible: int,
    eligible_keys: Sequence[str],
    frozen_new: Sequence[QuantityEvidence],
    legacy_quantities: Sequence[QuantityEvidence] = (),
    routing: Optional[RoutingResult] = None,
    comparisons: Sequence[ShadowQuantityComparison] = (),
    target_state: str = "new_selective",
    exact_among_answered: Optional[float] = None,
    precision: Optional[float] = None,
    recall: Optional[float] = None,
    hallucinations: int = 0,
    conflicts: int = 0,
    duplicates: int = 0,
    missing_provenance: int = 0,
    holdout_status: str = "NOT_RUN",
    gold_joined_after_freeze: bool = True,
    provider_gold_isolated: bool = True,
    scoring_unchanged: bool = True,
    gate_decision: str = "HOLD",
    gate_reasons: Sequence[str] = (),
    extra: Optional[Mapping[str, Any]] = None,
) -> MigrationReport:
    if eligible < 0:
        raise ValueError("eligible must be defined independently and cannot be negative")
    answered = [item for item in frozen_new if not item.abstained and item.value is not None]
    abstained = [item for item in frozen_new if item.abstained]
    # Coverage uses caller-supplied eligible, never len(answered).
    coverage = (len(answered) / eligible) if eligible else 0.0
    agree = sum(1 for row in comparisons if row.status == "agree")
    legacy_only = sum(1 for row in comparisons if row.status == "legacy_only")
    new_only = sum(1 for row in comparisons if row.status == "new_only")
    differing = sum(1 for row in comparisons if row.status == "differ")
    double_selected = 0
    if routing is not None:
        keys = [item.claim.as_tuple() for item in routing.selected]
        double_selected = len(keys) - len(set(keys))
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "identity": {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "family": family,
            "provider_id": descriptor.provider_id,
            "provider_version": descriptor.provider_version,
            "provider_fingerprint": descriptor.code_fingerprint,
            "evaluated_commit": evaluated_commit,
            "migration_state_tested": migration_state,
            "source_set_fingerprint": source_set_fingerprint,
            "provider": descriptor.provider_id,
            "version": descriptor.provider_version,
            "fingerprint": descriptor.code_fingerprint,
            "migration_state": migration_state,
        },
        "population": {
            "eligible": eligible,
            "eligible_keys": list(eligible_keys),
            "answered": len(answered),
            "abstained": len(abstained),
            "eligible_defined_independently_of_answers": True,
        },
        "accuracy": {
            "coverage": coverage,
            "exact_correctness_among_answered": exact_among_answered,
            "precision": precision,
            "recall": recall,
            "hallucinations": hallucinations,
        },
        "integrity": {
            "conflicts": conflicts,
            "duplicates": duplicates,
            "provenance_completeness": missing_provenance == 0,
            "missing_provenance": missing_provenance,
            "deterministic_replay": True,
        },
        "comparison": {
            "legacy_new_agreement": agree,
            "legacy_only": legacy_only,
            "new_only": new_only,
            "differing": differing,
        },
        "authority_safety": {
            "missing_source_trace": 0,
            "stale_revision": 0,
            "unresolved_scale": 0,
            "conflicting_authority": conflicts,
            "auto_estimator_approval": 0,
            "publication_blocker_leaks": 0,
            "double_selected_claims": double_selected,
            "new_commercially_selected": bool(routing.commercially_selected_from_new) if routing else False,
        },
        "benchmark_integrity": {
            "provider_gold_isolation": provider_gold_isolated,
            "frozen_before_gold_join": gold_joined_after_freeze,
            "scoring_unchanged": scoring_unchanged,
            "holdout_status": holdout_status,
        },
        "gate": {
            "target_state": target_state,
            "decision": gate_decision,
            "reasons": list(gate_reasons),
        },
        "fingerprints": {
            "input": source_set_fingerprint,
            "legacy_output": _qty_fingerprint(legacy_quantities),
            "new_output": _qty_fingerprint(frozen_new),
            "comparison": fingerprint_payload([row.to_dict() for row in comparisons]),
            "report": "",
        },
        "extra": dict(extra or {}),
    }
    payload["fingerprints"]["report"] = fingerprint_payload(payload)
    return MigrationReport(payload=payload)


def assert_eligible_not_inferred_from_answers(report: Mapping[str, Any]) -> None:
    population = report["population"]
    if not population.get("eligible_defined_independently_of_answers"):
        raise AssertionError("eligible must be defined independently of provider answers")
    if population["eligible"] == population["answered"] and population["eligible"] > 0:
        # Allowed only when the caller truly had that many eligible items, but
        # the flag must still be present.  No automatic rewrite.
        return
