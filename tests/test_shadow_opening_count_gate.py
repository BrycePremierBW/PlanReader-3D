from __future__ import annotations

from pb_shadow_opening_count_gate import (
    OPENING_COUNT_MIGRATION_GATE,
    evaluate_opening_count_migration_gate,
)


def test_migration_gate_was_predeclared_and_is_not_relaxed() -> None:
    assert OPENING_COUNT_MIGRATION_GATE == {
        "min_precision_on_answered_identities": 0.99,
        "min_exact_correctness_on_answered_counts": 0.99,
        "max_dimension_derived_fake_identities": 0,
        "max_critical_duplicate_counts": 0,
        "require_complete_provenance_on_accepted": True,
        "conflicts_must_fail_closed_or_review": True,
    }


def test_zero_answered_quantities_cannot_pass_the_gate() -> None:
    result = evaluate_opening_count_migration_gate(
        {
            "precision_on_answered_identities": 1.0,
            "exact_correctness_on_answered_counts": 1.0,
            "dimension_derived_fake_identities": 0,
            "critical_duplicate_counts": 0,
            "accepted_answered_count": 0,
            "accepted_missing_provenance": 0,
            "conflict_not_fail_closed": 0,
        }
    )
    assert result["decision"] == "FAIL"
    assert result["authority_recommendation"] == "remain_new_shadow"
    assert result["coverage_is_not_a_gate_input"] is True


def test_gate_passes_only_when_all_frozen_thresholds_hold() -> None:
    result = evaluate_opening_count_migration_gate(
        {
            "precision_on_answered_identities": 1.0,
            "exact_correctness_on_answered_counts": 1.0,
            "dimension_derived_fake_identities": 0,
            "critical_duplicate_counts": 0,
            "accepted_answered_count": 4,
            "accepted_missing_provenance": 0,
            "conflict_not_fail_closed": 0,
        }
    )
    assert result["decision"] == "PASS"
    assert result["authority_recommendation"] == "remain_new_shadow"
    assert result["authority_state"] == "new_shadow"
