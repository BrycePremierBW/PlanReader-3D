"""Adversarial GPT3 customer-output integrity regression gates."""
import copy
import json
import pytest

from pb_customer_output_verification import (
    CustomerOutputVerificationError, verify_sealed_customer_output,
)
from tests.test_customer_output_verification import sealed_and_rows


def check_mutation(mutator, message):
    sealed, rows = sealed_and_rows()
    rows = copy.deepcopy(rows)
    mutator(rows)
    with pytest.raises(CustomerOutputVerificationError, match=message):
        verify_sealed_customer_output(sealed, rows)


def test_wrong_direct_adapter_must_fail_even_when_identity_matches():
    check_mutation(lambda rows: rows[0]["commercial_projection_provenance"].update(adapter="manual"), "adapter")


def test_wrong_persisted_adapter_must_fail_without_direct_copy():
    def mutate(rows):
        rows[0].pop("commercial_projection_provenance")
        notes = json.loads(rows[0]["notes"])
        notes["adapter"] = "manual"
        rows[0]["notes"] = json.dumps(notes)
    check_mutation(mutate, "adapter")


def test_repeated_source_evidence_array_cannot_collate_to_unique_set():
    def mutate(rows):
        prov = rows[0]["commercial_projection_provenance"]
        ids = prov["quantity"]["evidence_ids"]
        ids.append(ids[0])
        rows[0]["notes"] = json.dumps(prov)
    check_mutation(mutate, "duplicate identities")


@pytest.mark.parametrize("bad", [True, 1, 1.5, ["qty-1"], {"id":"qty-1"}])
def test_non_string_direct_quantity_identity_is_invalid(bad):
    check_mutation(lambda rows: rows[0].update(quantity_id=bad), "malformed quantity identity")


def test_padded_direct_quantity_identity_is_invalid():
    check_mutation(lambda rows: rows[0].update(quantity_id=" qty-1 "), "malformed quantity identity")


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_nonfinite_customer_measurement_fails_closed(bad):
    check_mutation(lambda rows: rows[0].update(quantity=bad), "non-finite quantity")


@pytest.mark.parametrize("not_rows", ["x", b"x", {"quantity_id":"qty-1"}])
def test_nonsequence_customer_collection_is_rejected(not_rows):
    sealed, _ = sealed_and_rows()
    with pytest.raises(CustomerOutputVerificationError, match="sequence of row mappings"):
        verify_sealed_customer_output(sealed, not_rows)


def test_corrupt_notes_with_machine_source_receipt_cannot_be_manual():
    sealed, rows = sealed_and_rows()
    orphan = dict(rows[0])
    orphan.pop("quantity_id")
    orphan.pop("commercial_projection_provenance")
    orphan["notes"] = '{"adapter":"commercial_takeoff","adapter":"manual"}'
    with pytest.raises(CustomerOutputVerificationError, match="duplicate provenance key"):
        verify_sealed_customer_output(sealed, [*rows, orphan])
