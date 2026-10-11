"""Canonical stale/superseded receipts cannot be retained as customer quantities."""
from dataclasses import replace
import pytest

from pb_customer_output_verification import (
    CustomerOutputVerificationError, verify_sealed_customer_output,
)
from pb_quantity_takeoff_adapter import (
    CommercialTakeoffConflictError, quantity_evidence_to_takeoff_output_row,
)
from pb_source_closed_run_export import seal_source_closed_quantity, seal_source_closed_run
from test_customer_output_verification import quantity, trace, authority


@pytest.mark.parametrize("flag", ["is_stale","is_superseded"])
@pytest.mark.parametrize("status",[True,"true",1,None,{}])
def test_explicit_stale_or_superseded_source_marker_blocks_projection(flag,status):
    q=quantity("qty-stale","floor-old")
    q=replace(q,metadata={**q.metadata,flag:status})
    t=trace(q)
    sealed=seal_source_closed_quantity(q,trace=t)
    assert not sealed.lineage_ok
    assert "quantity_"+flag in sealed.lineage_reason_codes
    with pytest.raises(CommercialTakeoffConflictError,match=flag):
        quantity_evidence_to_takeoff_output_row(q,trace=t,authority=authority())


def test_explicit_current_flags_still_emit_review_only_customer_quantities():
    q=quantity("qty-current","floor-current")
    q=replace(q,metadata={**q.metadata,"is_stale":False,"is_superseded":False})
    t=trace(q)
    sealed=seal_source_closed_quantity(q,trace=t)
    assert sealed.lineage_ok
    row=quantity_evidence_to_takeoff_output_row(q,trace=t,authority=authority())
    assert row and row["quantity_id"]=="qty-current"
    assert row["quantity_status"]=="To review"


def test_sealed_stale_source_claim_fails_bijection_even_if_customer_row_is_forged():
    q=quantity("qty-stale","floor-old")
    source=trace(q)
    row=quantity_evidence_to_takeoff_output_row(q,trace=source,authority=authority())
    changed=replace(q,metadata={**q.metadata,"is_superseded":True})
    sealed=seal_source_closed_run([changed],project_id="project-7",
        traces_by_quantity_id={"qty-stale":source})
    assert not sealed.quantities[0].lineage_ok
    with pytest.raises(CustomerOutputVerificationError,match="incomplete lineage"):
        verify_sealed_customer_output(sealed,[row])
