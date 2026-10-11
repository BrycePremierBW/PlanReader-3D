"""Bad source identifiers never become commercial customer quantity claims."""
import pytest
import pb_quantity_takeoff_adapter as adapter
from test_quantity_takeoff_adapter import quantity,source_trace,figured


@pytest.mark.parametrize("bad",["", " ", "  entity-1","entity-1  "])
def test_invalid_quantity_parent_cannot_project_even_with_matching_trace(bad):
    q=quantity(input_entity_ids=(bad,))
    trace=source_trace(canonical_entity_ids=(bad,))
    with pytest.raises(adapter.MissingCommercialAuthorityError,match="canonical nonblank"):
        adapter.quantity_evidence_to_takeoff_output_row(q,trace=trace,authority=figured())


@pytest.mark.parametrize("bad",["", " ", "  ev-1","ev-1  "])
def test_invalid_evidence_id_cannot_project_even_with_matching_trace(bad):
    q=quantity(evidence_ids=(bad,))
    trace=source_trace(evidence_ids=(bad,))
    with pytest.raises(adapter.MissingCommercialAuthorityError,match="canonical nonblank"):
        adapter.quantity_evidence_to_takeoff_output_row(q,trace=trace,authority=figured())


def test_invalid_source_trace_parent_cannot_authenticate_a_good_quantity():
    q=quantity()
    trace=source_trace(canonical_entity_ids=("entity-1"," "))
    with pytest.raises(adapter.MissingCommercialAuthorityError,match="canonical nonblank"):
        adapter.quantity_evidence_to_takeoff_output_row(q,trace=trace,authority=figured())


def test_invalid_source_trace_evidence_cannot_authenticate_a_good_quantity():
    q=quantity()
    trace=source_trace(evidence_ids=("ev-1","  "))
    with pytest.raises(adapter.MissingCommercialAuthorityError,match="canonical nonblank"):
        adapter.quantity_evidence_to_takeoff_output_row(q,trace=trace,authority=figured())


def test_valid_original_source_ids_continue_to_project_one_review_row():
    row=adapter.quantity_evidence_to_takeoff_output_row(
        quantity(),trace=source_trace(),authority=figured(),
    )
    assert row is not None
    assert row["quantity_id"]=="qty-1"
    assert row["quantity_status"]=="To review"
    assert row["canonical_entity_ids"]==["entity-1"]
