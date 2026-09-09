from __future__ import annotations

from pb_migration_contracts import QuantityEvidence
from pb_shadow_opening_count_eval import (
    EligibleOpeningItem,
    aggregate_development_metrics,
    score_frozen_quantities,
)
from pb_shadow_opening_count_gate import evaluate_opening_count_migration_gate


def _qty(key: str, value: float | None, *, abstained: bool = False, formula: str = "explicit_schedule_count") -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id=f"qty_{key}_{'x' if abstained else value}",
        family="window_count" if key.startswith("W") else "door_count",
        semantic_key=key,
        value=value,
        unit="ea",
        input_entity_ids=("ent_type",) if not abstained else (),
        evidence_ids=("ev_1",) if not abstained else (),
        formula=formula,
        formula_version="1.0.0",
        authority="schedule_extracted" if not abstained else "blocked",
        status="firm" if not abstained else "blocked",
        confidence=0.9 if not abstained else 0.0,
        abstained=abstained,
        blocking_reasons=("conflict_manual_review",) if abstained else (),
    )


def test_evaluator_scores_frozen_outputs_without_reextracting() -> None:
    eligible = (
        EligibleOpeningItem("demo", "I1", "W1", 6.0, "NO", "Window W1", "schedule_extractable"),
        EligibleOpeningItem("demo", "I2", "D1", 3.0, "NO", "Door D1", "schedule_extractable"),
    )
    frozen = (_qty("W1", 6.0), _qty("D1", None, abstained=True), _qty("W99", 2.0))
    metrics = score_frozen_quantities(
        benchmark_id="demo",
        frozen_quantities=frozen,
        eligible=eligible,
        conflicts=(),
    )
    assert metrics["eligible_opening_count_items"] == 2
    assert metrics["answered"] == 2
    assert metrics["hallucinations"] == 1
    assert metrics["precision_on_answered_identities"] == 0.5
    assert metrics["exact_correctness_on_answered_counts"] == 0.5
    assert "W99" in metrics["hallucinated_keys"]


def test_gate_is_applied_to_aggregated_metrics_without_changing_thresholds() -> None:
    rows = [
        {
            "benchmark_id": "a",
            "eligible_opening_count_items": 2,
            "answered": 2,
            "abstained": 0,
            "precision_on_answered_identities": 1.0,
            "exact_correctness_on_answered_counts": 1.0,
            "hallucinations": 0,
            "duplicate_counts": 0,
            "critical_duplicate_counts": 0,
            "conflicts": 0,
            "ambiguous_identities": 0,
            "accepted_missing_provenance": 0,
            "conflict_not_fail_closed": 0,
            "dimension_derived_fake_identities": 0,
            "legacy_new_agreement": {"agree": 1, "compared": 1},
            "by_authority": {"schedule_extracted": 2},
            "by_formula": {"explicit_schedule_count": 2},
        }
    ]
    aggregated = aggregate_development_metrics(rows)
    gate = evaluate_opening_count_migration_gate(aggregated)
    assert gate["decision"] == "PASS"
    assert gate["authority_recommendation"] == "remain_new_shadow"
    assert gate["gate"]["min_precision_on_answered_identities"] == 0.99
