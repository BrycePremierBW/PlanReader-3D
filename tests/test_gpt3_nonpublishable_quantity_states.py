"""GPT3 provisional evidence may never masquerade as a source-closed quantity."""
import pytest
from test_source_closed_run_export import quantity, trace
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    MissingCommercialAuthorityError,
    quantity_evidence_to_takeoff_output_row,
    quantity_status_not_publishable,
)
from pb_source_closed_run_export import seal_source_closed_quantity


@pytest.mark.parametrize("status", [
    "raw", "candidate", "partial", "blocked", "abstained",
    "unresolved", "unsupported", "pending", "shadow", "conflict",
    "source_conflict",
])
def test_provisional_source_quantities_cannot_reach_commercial_rows(status):
    q = quantity(status=status)
    source = trace()
    sealed = seal_source_closed_quantity(q, trace=source)
    assert sealed.value == 13.270425  # preserve the evidence; do not invent zero
    assert not sealed.lineage_ok
    assert "quantity_status_not_publishable" in sealed.lineage_reason_codes
    assert quantity_status_not_publishable(status)
    with pytest.raises(MissingCommercialAuthorityError, match="nonpublishable"):
        quantity_evidence_to_takeoff_output_row(
            q, trace=source, authority=CommercialMeasurementAuthority(method="direct_evidence"),
        )


@pytest.mark.parametrize("status", ["firm", "corroborated"])
def test_firm_source_statuses_remain_eligible(status):
    q = quantity(status=status)
    source = trace()
    assert seal_source_closed_quantity(q, trace=source).lineage_ok
    assert not quantity_status_not_publishable(status)
    row = quantity_evidence_to_takeoff_output_row(
        q, trace=source, authority=CommercialMeasurementAuthority(method="direct_evidence"),
    )
    assert row is not None
    assert row["quantity"] == 13.270425
    assert row["quantity_id"] == "qty-1"


def test_real_abstention_keeps_its_missing_numeric_value():
    q = quantity(status="abstained", value=None, abstained=True,
                 blocking_reasons=("not_source_proven",))
    sealed = seal_source_closed_quantity(q, trace=trace())
    assert sealed.abstained and sealed.value is None
