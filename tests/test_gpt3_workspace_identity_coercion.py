"""Workspace identity is an exact positive integer, not a coercible source alias."""
from dataclasses import replace

import pytest

from pb_source_closed_run_export import seal_source_closed_quantity
from pb_quantity_takeoff_adapter import (
    CommercialTakeoffConflictError, quantity_evidence_to_takeoff_output_row,
)
from test_customer_output_verification import quantity, trace, authority


@pytest.mark.parametrize("bad", [True,False,7.5,7.0,"7.0"," 7",0,-1,"8",[],{}])
def test_coercible_or_wrong_workspace_metadata_cannot_authenticate_signed_source(bad):
    q=quantity("qty-workspace","floor-workspace")
    q=replace(q, metadata={**q.metadata,"workspace_id":bad})
    source=trace(q)
    sealed=seal_source_closed_quantity(q,trace=source)
    assert not sealed.lineage_ok
    assert "workspace_id_mismatch" in sealed.lineage_reason_codes
    with pytest.raises(CommercialTakeoffConflictError,match="workspace_id"):
        quantity_evidence_to_takeoff_output_row(q,trace=source,authority=authority())


@pytest.mark.parametrize("canonical", [7,"7","007"])
def test_authentic_numeric_workspace_metadata_keeps_original_source_lineage(canonical):
    q=quantity("qty-workspace","floor-workspace")
    q=replace(q,metadata={**q.metadata,"workspace_id":canonical})
    source=trace(q)
    assert seal_source_closed_quantity(q,trace=source).lineage_ok
    row=quantity_evidence_to_takeoff_output_row(q,trace=source,authority=authority())
    assert row is not None
    assert row["workspace_id"]==7
