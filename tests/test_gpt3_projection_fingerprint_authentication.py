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
