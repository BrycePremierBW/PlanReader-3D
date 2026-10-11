"""Sealed wire receipts must preserve original scalar types and text."""
import pytest
from test_source_closed_run_export import quantity, trace
from pb_source_closed_run_export import (
    seal_source_closed_run, sealed_source_closed_run_from_dict,
    SourceClosedRunConflictError,
)


def original(**trace_kw):
    run=seal_source_closed_run(
        [quantity()], project_id="project-a",
        traces_by_quantity_id={"qty-1":trace(**trace_kw)},
    )
    return run.to_dict()


@pytest.mark.parametrize(("field", "replacement"), [
    ("quantity_id", " qty-1 "),
    ("project_id", " project-a "),
    ("source_page", " A140 / p8 "),
    ("viewport_id", " vp-a140-main "),
    ("revision_id", " rev-a "),
    ("document_id", " doc-a "),
    ("family", " room_area "),
    ("semantic_key", " room:food-prep:area "),
    ("source_sha256", ("a"*64).upper()),
])
def test_quantity_receipt_rejects_normalized_scalar_spoofing(field, replacement):
    payload=original()
    payload["quantities"][0][field]=replacement
    with pytest.raises(SourceClosedRunConflictError, match="noncanonical"):
        sealed_source_closed_run_from_dict(payload)


def test_signed_source_page_number_does_not_coerce_to_original_string():
    payload=original(source_page="9")
    assert payload["quantities"][0]["source_page"]=="9"
    payload["quantities"][0]["source_page"]=9
    with pytest.raises(SourceClosedRunConflictError, match="noncanonical scalar source_page"):
        sealed_source_closed_run_from_dict(payload)


@pytest.mark.parametrize(("field", "replacement"), [
    ("run_id", " source_closed_run_ignored "),
    ("project_id", " project-a "),
    ("fingerprint", ("0"*64).upper()),
])
def test_run_envelope_rejects_noncanonical_scalar_identity(field,replacement):
    payload=original()
    if field=="run_id":
        replacement=" "+payload["run_id"]+" "
    if field=="fingerprint":
        replacement=payload["fingerprint"].upper()
    payload[field]=replacement
    with pytest.raises(SourceClosedRunConflictError, match="noncanonical"):
        sealed_source_closed_run_from_dict(payload)


def test_lowercase_signed_original_round_trips_without_mutation():
    payload=original()
    loaded=sealed_source_closed_run_from_dict(payload)
    assert loaded.to_dict()==payload


def test_uppercase_nested_fingerprint_cannot_substitute_original():
    payload=original()
    payload["quantities"][0]["fingerprint"]=payload["quantities"][0]["fingerprint"].upper()
    with pytest.raises(SourceClosedRunConflictError, match="noncanonical fingerprint"):
        sealed_source_closed_run_from_dict(payload)


def test_noncanonical_source_envelope_hash_stays_blocked():
    payload=original()
    payload["source_sha256s"][0]=payload["source_sha256s"][0].upper()
    with pytest.raises(SourceClosedRunConflictError, match="noncanonical source_sha256s"):
        sealed_source_closed_run_from_dict(payload)
