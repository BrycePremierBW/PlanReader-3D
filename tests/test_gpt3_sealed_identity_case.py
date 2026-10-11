"""Seal evidence lineage agrees with exact commercial source identifiers."""
from copy import deepcopy
import pytest

from test_source_closed_run_export import quantity, trace
from pb_source_closed_run_export import seal_source_closed_quantity
from pb_quantity_takeoff_adapter import (
    quantity_evidence_to_takeoff_output_row, CommercialMeasurementAuthority,
    CommercialTakeoffConflictError,
)


@pytest.mark.parametrize(("field", "replacement"), [
    ("project_id", "Project-A"),
    ("document_id", "Doc-a"),
    ("revision_id", "Rev-a"),
])
def test_case_variant_source_identifiers_block_sealing_and_commercial_projection(
    field, replacement
):
    q=quantity()
    meta=dict(q.metadata)
    meta[field]=replacement
    q=quantity(metadata=meta)
    signed=seal_source_closed_quantity(q,trace=trace())
    assert signed.lineage_ok is False
    assert field+"_mismatch" in signed.lineage_reason_codes
    with pytest.raises(CommercialTakeoffConflictError,match=field):
        quantity_evidence_to_takeoff_output_row(
            q,trace=trace(),authority=CommercialMeasurementAuthority(method="direct_evidence")
        )


def test_identical_production_source_identifiers_remain_firm():
    q=quantity()
    signed=seal_source_closed_quantity(q,trace=trace())
    assert signed.lineage_ok
    assert signed.lineage_reason_codes==()


def test_uppercase_sha_metadata_representation_remains_same_digest():
    q=quantity()
    meta=dict(q.metadata)
    meta["source_sha256"]=("A"*64)
    signed=seal_source_closed_quantity(quantity(metadata=meta),trace=trace())
    assert signed.lineage_ok
    assert signed.source_sha256=="a"*64
