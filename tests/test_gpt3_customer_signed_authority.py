"""Commercial audit must agree with every signed status/measurement receipt."""
from copy import deepcopy
import json
import pytest
from test_customer_output_verification import sealed_and_rows
from pb_customer_output_verification import (
    CustomerOutputVerificationError, verify_sealed_customer_output,
)


def mutate_provenance(field, new_value, section="quantity"):
    sealed, rows = sealed_and_rows()
    rows = deepcopy(rows)
    prov = rows[0]["commercial_projection_provenance"]
    prov[section][field] = new_value
    rows[0]["notes"] = json.dumps(prov)
    return sealed, rows


@pytest.mark.parametrize(("field", "value", "message"), [
    ("status", "candidate", "provenance.status"),
    ("authority", "unverified", "provenance.authority"),
    ("value", 990.0, "provenance.value"),
    ("confidence", 0.1, "provenance.confidence"),
    ("confidence", "0.99", "nonnumeric provenance.confidence"),
    ("abstained", True, "provenance.abstained"),
])
def test_signed_quantity_values_status_and_authority_cannot_drift(field,value,message):
    sealed,rows=mutate_provenance(field,value)
    with pytest.raises(CustomerOutputVerificationError, match=message):
        verify_sealed_customer_output(sealed,rows)


def test_provenance_cannot_claim_unsealed_current_revision():
    sealed,rows=mutate_provenance("current_revision_id","rev-foreign","source_trace")
    with pytest.raises(CustomerOutputVerificationError,match="provenance.current_revision_id"):
        verify_sealed_customer_output(sealed,rows)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("method", "unverified", "unrecognized measurement authority"),
    ("figured_dimension_ids", "dim-1", "figured_dimension_ids"),
])
def test_measurement_method_and_receipts_require_producer_form(field,value,message):
    sealed,rows=mutate_provenance(field,value,"measurement_authority")
    with pytest.raises(CustomerOutputVerificationError,match=message):
        verify_sealed_customer_output(sealed,rows)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("measurement_method", "scaled_geometry", "measurement_method"),
    ("quantity_authority", "invented", "quantity_authority"),
    ("ai_baseline_quantity", 10.0, "ai_baseline_quantity"),
    ("confidence", 0.001, "confidence"),
    ("figured_dimension_ids", ["fake"], "figured_dimension_ids"),
])
def test_direct_customer_receipts_must_agree_with_production(field,value,message):
    sealed,rows=sealed_and_rows()
    rows=[dict(row) for row in rows]
    rows[0][field]=value
    with pytest.raises(CustomerOutputVerificationError,match=message):
        verify_sealed_customer_output(sealed,rows)


def test_genuine_source_to_customer_bijection_still_passes():
    sealed,rows=sealed_and_rows()
    report=verify_sealed_customer_output(sealed,rows)
    assert report.valid_quantity_count==2
    assert report.abstained_quantity_count==1


def test_malformed_scaled_authority_cannot_be_relabelled_proven():
    sealed,rows=mutate_provenance("method","scaled_geometry","measurement_authority")
    prov=rows[0]["commercial_projection_provenance"]
    prov["measurement_authority"]["scale_status"]="calibrated"
    prov["measurement_authority"]["resolved_scale_id"]=None
    rows[0]["notes"]=json.dumps(prov)
    with pytest.raises(CustomerOutputVerificationError,match="unverified scaled measurement authority"):
        verify_sealed_customer_output(sealed,rows)
