"""Predeclared authority gate for door/window opening-count shadow migration.

These thresholds were fixed BEFORE any development-project shadow measurement.
Do not edit them after seeing results.  Coverage is reported separately and is
not a reason to lower this gate.

A FAIL result means the family stays NEW_SHADOW.  That is a valid outcome.
This module does not activate NEW_SELECTIVE or NEW_AUTHORITATIVE.
"""
from __future__ import annotations

from typing import Any, Mapping


# Canonical frozen gate. Do not revise after scoring. Coverage is not a gate input.
OPENING_COUNT_MIGRATION_GATE = {
    "min_precision_on_answered_identities": 0.99,
    "min_exact_correctness_on_answered_counts": 0.99,
    "max_dimension_derived_fake_identities": 0,
    "max_critical_duplicate_counts": 0,
    "require_complete_provenance_on_accepted": True,
    "conflicts_must_fail_closed_or_review": True,
}

OPENING_COUNT_FAMILIES = frozenset({"window_count", "door_count", "opening_count"})
OPENING_COUNT_AUTHORITY_STATE = "new_shadow"
OPENING_COUNT_AUTHORITY_RECOMMENDATION = "remain_new_shadow"


def evaluate_opening_count_migration_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the predeclared gate. Does not mutate thresholds."""
    gate = dict(OPENING_COUNT_MIGRATION_GATE)
    precision = float(metrics.get("precision_on_answered_identities") or 0.0)
    exact = float(metrics.get("exact_correctness_on_answered_counts") or 0.0)
    fake_ids = int(metrics.get("dimension_derived_fake_identities") or 0)
    duplicates = int(metrics.get("critical_duplicate_counts") or 0)
    accepted = int(metrics.get("accepted_answered_count") or 0)
    missing_provenance = int(metrics.get("accepted_missing_provenance") or 0)
    conflict_leaks = int(metrics.get("conflict_not_fail_closed") or 0)

    checks = {
        "precision_on_answered_identities": precision >= gate["min_precision_on_answered_identities"],
        "exact_correctness_on_answered_counts": exact >= gate["min_exact_correctness_on_answered_counts"],
        "zero_dimension_derived_fake_identities": fake_ids <= gate["max_dimension_derived_fake_identities"],
        "zero_critical_duplicate_counts": duplicates <= gate["max_critical_duplicate_counts"],
        "complete_provenance_on_accepted": (
            not gate["require_complete_provenance_on_accepted"] or missing_provenance == 0
        ),
        "conflicts_fail_closed_or_review": (
            not gate["conflicts_must_fail_closed_or_review"] or conflict_leaks == 0
        ),
    }
    if accepted == 0:
        # No answered quantities cannot satisfy a 99% correctness claim.
        checks["precision_on_answered_identities"] = False
        checks["exact_correctness_on_answered_counts"] = False

    passed = all(checks.values())
    return {
        "gate": gate,
        "checks": checks,
        "decision": "PASS" if passed else "FAIL",
        "authority_recommendation": OPENING_COUNT_AUTHORITY_RECOMMENDATION,
        "authority_state": OPENING_COUNT_AUTHORITY_STATE,
        "coverage_is_not_a_gate_input": True,
    }
