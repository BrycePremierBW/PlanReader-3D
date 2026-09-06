"""Regression coverage for post-review AI takeoff mutation authority.

An estimator review of an AI-derived row authorises the reviewed row state. Later
commercially consequential edits must not inherit that review silently.
"""

from __future__ import annotations

from typing import Any

from pb_takeoff_authority_v164 import (
    prepare_ai_takeoff_editor_save,
    takeoff_row_publishability,
)


def _reviewed_ai_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "workspace_id": 7,
        "section": "External",
        "element": "External walls",
        "location": "Ground",
        "substrate": "Render",
        "finish_system": "Exterior acrylic",
        "quantity": 80.0,
        "unit": "m²",
        "quantity_status": "Measured",
        "source_page": "Render R01",
        "source_reference": "Render R01 visual interpretation",
        "inclusion_status": "INCLUSION",
        "coats": 2.0,
        "coverage_m2_per_litre": 12.0,
        "productivity_m2_per_hour": 8.0,
        "rate_per_unit": 25.0,
        "confidence": "Estimator verified",
        "notes": "AI draft — verified against issued drawing.",
        "row_role": "",
        "origin": "AI_REVIEWED",
        "ai_baseline_quantity": 80.0,
        "pre_map_quantity": None,
        "pre_map_quantity_status": "",
    }
    row.update(overrides)
    return row


def test_quantity_mutation_after_ai_review_requires_fresh_review() -> None:
    prior = _reviewed_ai_row()

    saved = prepare_ai_takeoff_editor_save(prior, {"quantity": 160.0})

    assert saved["origin"] == "AI"
    allowed, reason = takeoff_row_publishability(saved)
    assert allowed is False
    assert "review" in reason.lower()


def test_rate_mutation_after_ai_review_requires_fresh_review() -> None:
    prior = _reviewed_ai_row()

    saved = prepare_ai_takeoff_editor_save(prior, {"rate_per_unit": 250.0})

    assert saved["origin"] == "AI"
    assert takeoff_row_publishability(saved)[0] is False


def test_consequential_edit_with_explicit_review_field_change_can_be_reapproved() -> None:
    prior = _reviewed_ai_row()

    saved = prepare_ai_takeoff_editor_save(
        prior,
        {"quantity": 90.0, "quantity_status": "Mapped"},
    )

    assert saved["origin"] == "AI_REVIEWED"
    assert takeoff_row_publishability(saved) == (True, "PUBLISHABLE")
