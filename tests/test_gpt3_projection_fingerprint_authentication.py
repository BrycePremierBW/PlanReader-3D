"""GPT3 verifies actual M5 customer projection fingerprints, not just SHA syntax."""
from copy import deepcopy
import pytest
from test_customer_output_verification import sealed_and_rows
from pb_customer_output_verification import (
    CustomerOutputVerificationError,verify_sealed_customer_output,
)


def test_unchanged_production_projection_fingerprint_remains_valid():
    sealed,rows=sealed_and_rows()
    assert verify_sealed_customer_output(sealed,rows).valid_quantity_count==2


@pytest.mark.parametrize("fingerprint", ["0"*64,"b"*64])
def test_forged_well_formed_sha_cannot_masquerade_as_signed_projection(fingerprint):
    sealed,rows=sealed_and_rows()
    rows=deepcopy(rows)
    assert rows[0]["commercial_projection_fingerprint"] != fingerprint
    rows[0]["commercial_projection_fingerprint"]=fingerprint
    with pytest.raises(CustomerOutputVerificationError,match="projection fingerprint mismatch"):
        verify_sealed_customer_output(sealed,rows)


def test_projection_fingerprint_cannot_be_reused_across_distinct_quantity_rows():
    sealed,rows=sealed_and_rows()
    rows=deepcopy(rows)
    rows[0]["commercial_projection_fingerprint"]=rows[1]["commercial_projection_fingerprint"]
    with pytest.raises(CustomerOutputVerificationError,match="projection fingerprint mismatch"):
        verify_sealed_customer_output(sealed,rows)


def test_missing_direct_fingerprint_in_persisted_database_row_remains_supported():
    sealed,rows=sealed_and_rows()
    persisted=deepcopy(rows)
    for r in persisted:
        r.pop("commercial_projection_fingerprint",None)
    assert verify_sealed_customer_output(sealed,persisted).valid_quantity_count==2


def test_bad_fingerprint_receipt_must_be_hexadecimal():
    sealed,rows=sealed_and_rows()
    rows=deepcopy(rows)
    rows[0]["commercial_projection_fingerprint"]="not-a-sha"
    with pytest.raises(CustomerOutputVerificationError,match="invalid projection fingerprint"):
        verify_sealed_customer_output(sealed,rows)


def test_customer_workspace_id_cannot_drift_from_signed_source_trace():
    sealed,rows=sealed_and_rows()
    rows=deepcopy(rows)
    rows[0]["workspace_id"]=999
    with pytest.raises(CustomerOutputVerificationError,match="workspace_id mismatch"):
        verify_sealed_customer_output(sealed,rows)


@pytest.mark.parametrize("invalid",[True,"other-workspace",-1.5])
def test_invalid_customer_workspace_ids_never_pretend_to_be_producer_ids(invalid):
    sealed,rows=sealed_and_rows()
    rows=deepcopy(rows)
    rows[0]["workspace_id"]=invalid
    with pytest.raises(CustomerOutputVerificationError,match="invalid workspace_id"):
        verify_sealed_customer_output(sealed,rows)


def _bbox_customer_row():
    from dataclasses import replace
    import pb_quantity_takeoff_adapter as adapter
    from pb_source_closed_run_export import seal_source_closed_run
    from test_customer_output_verification import quantity,trace,authority
    q=quantity("qty-bbox","floor-bbox",value=12.5)
    original=trace(q)
    traced=replace(original,source_bbox=(1.0,2.0,11.0,22.0))
    sealed=seal_source_closed_run([q],project_id="project-7",
                                  traces_by_quantity_id={q.quantity_id:traced})
    row=adapter.quantity_evidence_to_takeoff_output_row(
        q,trace=traced,authority=authority(),
    )
    return sealed,[row]


def test_exact_original_native_bbox_remains_valid_with_correct_fingerprint():
    sealed,rows=_bbox_customer_row()
    assert verify_sealed_customer_output(sealed,rows).valid_quantity_count==1


@pytest.mark.parametrize("invalid",[
    [1.0,2.0,11.0,23.0],
    [1.0,2.0,11.0,float("nan")],
    [1.0,2.0,11.0,10**400],
    [True,2.0,11.0,22.0],
])
def test_customer_bbox_must_equal_signed_native_source_geometry(invalid):
    sealed,rows=_bbox_customer_row()
    rows=deepcopy(rows)
    rows[0]["source_bbox"]=invalid
    with pytest.raises(CustomerOutputVerificationError,match="source_bbox"):
        verify_sealed_customer_output(sealed,rows)


def test_persisted_rows_may_omit_adapter_only_native_bbox():
    sealed,rows=_bbox_customer_row()
    rows=deepcopy(rows)
    rows[0].pop("source_bbox")
    assert verify_sealed_customer_output(sealed,rows).valid_quantity_count==1
