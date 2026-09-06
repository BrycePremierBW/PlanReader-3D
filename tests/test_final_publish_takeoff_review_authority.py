"""Regression coverage for final-publish authority on unresolved takeoff REVIEW signals."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pb_commercial_export_preflight_v163 import (
    derive_export_preflight,
    verify_toctou_and_publish_jobhub,
)
from pb_commercial_review_v161 import CommercialReviewResult, CommercialReviewSignal


class _App:
    def lquery(self, sql, params=()):
        if "FROM workspaces" in sql:
            return [{
                "id": 1,
                "job_no": "JOB-REVIEW",
                "job_name": "Review authority",
                "builder_client": "Builder",
                "site_address": "Site",
                "drawing_issue": "Rev A",
                "estimator": "Estimator",
                "jobhub_job_id": 101,
            }]
        return []


class _Bridge:
    def query(self, sql, params=()):
        return []


def _review_result(source_family: str, category: str, summary: str) -> CommercialReviewResult:
    signal = CommercialReviewSignal(
        signal_id=f"review:1:{source_family}:1",
        workspace_id=1,
        source_family=source_family,
        source_type="takeoff_row" if source_family == "takeoff" else "register_item",
        source_id="1",
        category=category,
        severity="REVIEW",
        title="Unresolved commercial review",
        summary=summary,
        reasons=(summary,),
        status="Open",
    )
    return CommercialReviewResult(
        workspace_id=1,
        signals=[signal],
        source_coverage={"takeoff": "AVAILABLE", "register": "AVAILABLE", "scale": "AVAILABLE"},
    )


def _derive_with(review_result: CommercialReviewResult):
    with (
        patch(
            "pb_commercial_export_preflight_v163.collect_commercial_review_signals",
            return_value=review_result,
        ),
        patch(
            "pb_commercial_export_preflight_v163._get_takeoff_row_stats",
            return_value=(1, 1, 0, 0, 0, "payload-hash"),
        ),
        patch(
            "pb_commercial_export_preflight_v163._get_scale_authority_fingerprint",
            return_value="scale-hash",
        ),
    ):
        return derive_export_preflight(_App(), 1, bridge_available=True)


def test_takeoff_review_cannot_be_acknowledged_into_final_publish_authority() -> None:
    review_result = _review_result(
        "takeoff",
        "Measurement",
        "Quantity status is provisional ('Provisional measured')",
    )
    preflight = _derive_with(review_result)

    # Draft/internal review may remain warning-capable, but final publication must
    # fail closed: acknowledgement cannot create measurement authority.
    assert preflight.preflight_status == "AVAILABLE_WITH_WARNING"
    assert preflight.final_publish_state == "BLOCKED"

    publish = MagicMock(return_value={"package_id": 501, "published": True})
    with (
        patch(
            "pb_commercial_export_preflight_v163.collect_commercial_review_signals",
            return_value=review_result,
        ),
        patch(
            "pb_commercial_export_preflight_v163._get_takeoff_row_stats",
            return_value=(1, 1, 0, 0, 0, "payload-hash"),
        ),
        patch(
            "pb_commercial_export_preflight_v163._get_scale_authority_fingerprint",
            return_value="scale-hash",
        ),
        pytest.raises(RuntimeError, match="Final publish blocked"),
    ):
        verify_toctou_and_publish_jobhub(
            _App(),
            1,
            bridge=_Bridge(),
            user_name="Estimator",
            expected_fingerprint=preflight.preflight_fingerprint,
            acknowledgement_confirmed=True,
            publish_fn=publish,
        )
    publish.assert_not_called()


def test_register_review_remains_acknowledgement_capable() -> None:
    review_result = _review_result(
        "register",
        "Clarification",
        "Open RFI requires estimator acknowledgement",
    )
    preflight = _derive_with(review_result)

    assert preflight.preflight_status == "AVAILABLE_WITH_WARNING"
    assert preflight.final_publish_state == "AVAILABLE_WITH_WARNING"
