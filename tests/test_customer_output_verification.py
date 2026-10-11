from __future__ import annotations

from dataclasses import replace

import pytest

import pb_quantity_takeoff_adapter as adapter
from pb_customer_output_verification import (
    CustomerOutputVerificationError,
    verify_sealed_customer_output,
)
from pb_migration_contracts import QuantityEvidence
from pb_source_closed_run_export import seal_source_closed_run


SHA = "a" * 64


def quantity(
    quantity_id: str,
    entity_id: str,
    *,
    value: float | None = 12.5,
    abstained: bool = False,
) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id=quantity_id,
        family="floor_area",
        semantic_key="floor.area",
        value=value,
        unit="m²",
        input_entity_ids=(entity_id,),
        formula="documented_area",
        formula_version="1",
        evidence_ids=(f"ev-{quantity_id}",),
        authority="documented_dimension",
        status="corroborated" if not abstained else "abstained",
        confidence=0.99,
        abstained=abstained,
        blocking_reasons=("insufficient evidence",) if abstained else (),
        metadata={
            "workspace_id": 7,
            "project_id": "project-7",
            "document_id": "doc-1",
            "source_sha256": SHA,
            "revision_id": "rev-3",
            "section": "Floors",
            "location": "Level 1",
        },
    )


def trace(q: QuantityEvidence, *, include_evidence: bool = True) -> adapter.CommercialTakeoffSourceTrace:
    return adapter.CommercialTakeoffSourceTrace(
        workspace_id=7,
        project_id="project-7",
        document_id="doc-1",
        source_sha256=SHA,
        source_page="A-101 / p3",
        viewport_id=f"vp-{q.quantity_id}",
        revision_id="rev-3",
        current_revision_id="rev-3",
        evidence_ids=tuple(q.evidence_ids) if include_evidence else (),
        canonical_entity_ids=tuple(q.input_entity_ids),
    )


def authority() -> adapter.CommercialMeasurementAuthority:
    return adapter.CommercialMeasurementAuthority(method="direct_evidence")


def sealed_and_rows():
    q1 = quantity("qty-1", "floor-1", value=12.5)
    q2 = quantity("qty-2", "floor-2", value=13.0)
    abstain = quantity("qty-abstain", "floor-3", value=None, abstained=True)
    quantities = (q1, q2, abstain)
    traces = {q.quantity_id: trace(q) for q in quantities}
    authorities = {"qty-1": authority(), "qty-2": authority()}

    sealed = seal_source_closed_run(
        quantities,
        project_id="project-7",
        traces_by_quantity_id=traces,
    )
    rows = adapter.quantities_to_takeoff_output_rows(
        quantities,
        traces_by_quantity_id=traces,
        authorities_by_quantity_id=authorities,
    )
    return sealed, rows


def test_every_valid_sealed_quantity_has_exactly_one_complete_customer_row() -> None:
    sealed, rows = sealed_and_rows()

    report = verify_sealed_customer_output(sealed, rows)

    assert report.to_dict() == {
        "project_id": "project-7",
        "sealed_quantity_count": 3,
        "valid_quantity_count": 2,
        "abstained_quantity_count": 1,
        "customer_row_count": 2,
        "verified_quantity_ids": ["qty-1", "qty-2"],
        "complete": True,
    }


def test_persisted_database_shape_keeps_complete_lineage_in_notes_and_reference() -> None:
    sealed, rows = sealed_and_rows()
    adapter_only_fields = {
        "project_id",
        "quantity_id",
        "semantic_key",
        "quantity_family",
        "quantity_authority",
        "document_id",
        "source_sha256",
        "revision_id",
        "viewport_id",
        "source_bbox",
        "evidence_ids",
        "canonical_entity_ids",
        "measurement_method",
        "figured_dimension_ids",
        "resolved_scale_id",
        "scale_status",
        "scale_conflicts",
        "commercial_projection_fingerprint",
        "commercial_projection_provenance",
    }
    persisted = []
    for row in rows:
        copy_row = {
            key: value
            for key, value in row.items()
            if key not in adapter_only_fields
        }
        persisted.append(copy_row)

    report = verify_sealed_customer_output(sealed, persisted)

    assert report.verified_quantity_ids == ("qty-1", "qty-2")


def test_tampered_sealed_run_envelope_fails_before_customer_verification() -> None:
    sealed, rows = sealed_and_rows()
    tampered = replace(sealed, run_id="tampered-run")

    with pytest.raises(CustomerOutputVerificationError, match="cryptographic verification"):
        verify_sealed_customer_output(tampered, rows)


def test_missing_valid_customer_row_fails_closed() -> None:
    sealed, rows = sealed_and_rows()

    with pytest.raises(CustomerOutputVerificationError, match="missing customer rows"):
        verify_sealed_customer_output(sealed, rows[:1])


def test_duplicate_customer_row_fails_closed() -> None:
    sealed, rows = sealed_and_rows()

    with pytest.raises(CustomerOutputVerificationError, match="duplicate customer row"):
        verify_sealed_customer_output(sealed, [*rows, dict(rows[0])])


def test_abstained_quantity_cannot_leak_into_customer_output() -> None:
    sealed, rows = sealed_and_rows()
    leaked = dict(rows[0])
    leaked["quantity_id"] = "qty-abstain"

    with pytest.raises(CustomerOutputVerificationError, match="abstained quantities leaked"):
        verify_sealed_customer_output(sealed, [*rows, leaked])


def test_customer_lineage_mismatch_fails_closed() -> None:
    sealed, rows = sealed_and_rows()
    tampered = [dict(row) for row in rows]
    tampered[0]["canonical_entity_ids"] = ["other-floor"]

    with pytest.raises(CustomerOutputVerificationError, match="canonical_entity_ids mismatch"):
        verify_sealed_customer_output(sealed, tampered)


def test_persisted_source_reference_tamper_fails_closed() -> None:
    sealed, rows = sealed_and_rows()
    tampered = [dict(row) for row in rows]
    tampered[0].pop("commercial_projection_provenance")
    tampered[0].pop("quantity_id")
    tampered[0]["source_reference"] = "QuantityEvidence qty-1; document=doc-1"

    with pytest.raises(CustomerOutputVerificationError, match="source_reference lineage is incomplete"):
        verify_sealed_customer_output(sealed, tampered)


def test_customer_source_revision_mismatch_fails_closed() -> None:
    sealed, rows = sealed_and_rows()
    tampered = [dict(row) for row in rows]
    tampered[0]["revision_id"] = "rev-4"

    with pytest.raises(CustomerOutputVerificationError, match="revision_id mismatch"):
        verify_sealed_customer_output(sealed, tampered)


def test_non_abstained_sealed_quantity_with_incomplete_lineage_fails_closed() -> None:
    q = quantity("qty-1", "floor-1")
    good_trace = trace(q)
    bad_trace = trace(q, include_evidence=False)
    sealed = seal_source_closed_run(
        (q,),
        project_id="project-7",
        traces_by_quantity_id={"qty-1": bad_trace},
    )
    row = adapter.quantity_evidence_to_takeoff_output_row(
        q,
        trace=good_trace,
        authority=authority(),
    )
    assert row is not None

    with pytest.raises(CustomerOutputVerificationError, match="incomplete lineage"):
        verify_sealed_customer_output(sealed, [row])


def test_orphaned_automated_customer_row_cannot_hide_as_manual_row() -> None:
    sealed, rows = sealed_and_rows()
    orphan = dict(rows[0])
    orphan.pop("quantity_id")
    orphan.pop("commercial_projection_provenance", None)
    orphan["notes"] = ""
    # Source-owned automated provenance still declares this row as a
    # QuantityEvidence projection even after its direct ID was stripped.
    assert orphan["source_reference"].startswith("QuantityEvidence qty-1")
    with pytest.raises(CustomerOutputVerificationError, match="missing quantity identity"):
        verify_sealed_customer_output(sealed, [*rows, orphan])


def test_malformed_automated_provenance_cannot_lose_its_quantity_identity() -> None:
    sealed, rows = sealed_and_rows()
    orphan = dict(rows[0])
    orphan.pop("quantity_id")
    orphan["commercial_projection_provenance"] = {}
    orphan["source_reference"] = "manual note"
    orphan["notes"] = ""
    with pytest.raises(CustomerOutputVerificationError, match="missing quantity identity"):
        verify_sealed_customer_output(sealed, [*rows, orphan])


def test_manual_row_without_projection_identity_remains_outside_automated_bijection() -> None:
    sealed, rows = sealed_and_rows()
    manual = {"description": "Estimator note", "quantity": 1, "source_reference": "manual"}
    report = verify_sealed_customer_output(sealed, [*rows, manual])
    assert report.verified_quantity_ids == ("qty-1", "qty-2")
    assert report.customer_row_count == 2


def test_orphaned_auto_notes_cannot_hide_even_if_source_reference_is_erased() -> None:
    sealed, rows = sealed_and_rows()
    orphan = dict(rows[0])
    orphan.pop("quantity_id")
    orphan.pop("commercial_projection_provenance", None)
    orphan["source_reference"] = "manual note"
    # Keep the serialized commercial adapter marker, but strip the actual
    # nested quantity ID so the row is genuinely orphaned.
    assert isinstance(orphan["notes"], str)
    import json
    notes = json.loads(orphan["notes"])
    assert notes["adapter"] == "commercial_takeoff"
    notes["quantity"].pop("quantity_id", None)
    orphan["notes"] = json.dumps(notes)
    with pytest.raises(CustomerOutputVerificationError, match="missing quantity identity"):
        verify_sealed_customer_output(sealed, [*rows, orphan])


def test_conflicting_persisted_commercial_source_sha_cannot_hide_behind_direct_copy() -> None:
    import json

    sealed, rows = sealed_and_rows()
    corrupted = dict(rows[0])
    notes = json.loads(corrupted["notes"])
    assert notes["adapter"] == "commercial_takeoff"
    notes["source_trace"]["source_sha256"] = "b" * 64
    corrupted["notes"] = json.dumps(notes, sort_keys=True)

    with pytest.raises(
        CustomerOutputVerificationError,
        match="conflicting direct and persisted projection provenance",
    ):
        verify_sealed_customer_output(sealed, [corrupted, rows[1]])


def test_conflicting_persisted_commercial_quantity_id_fails_closed() -> None:
    import json

    sealed, rows = sealed_and_rows()
    corrupted = dict(rows[0])
    notes = json.loads(corrupted["notes"])
    notes["quantity"]["quantity_id"] = "qty-2"
    corrupted["notes"] = json.dumps(notes, sort_keys=True)

    with pytest.raises(
        CustomerOutputVerificationError,
        match="conflicting direct and persisted projection provenance",
    ):
        verify_sealed_customer_output(sealed, [corrupted, rows[1]])


def test_identical_independently_serialized_commercial_provenance_still_passes() -> None:
    import json

    sealed, rows = sealed_and_rows()
    reserialized = [dict(row) for row in rows]
    for row in reserialized:
        row["notes"] = json.dumps(
            json.loads(row["notes"]), ensure_ascii=False, sort_keys=False,
        )
    verified = verify_sealed_customer_output(sealed, reserialized)
    assert verified.verified_quantity_ids == ("qty-1", "qty-2")


def test_source_reference_prefix_cannot_impersonate_exact_source_document() -> None:
    sealed, rows = sealed_and_rows()
    tampered = dict(rows[0])
    tampered["source_reference"] = tampered["source_reference"].replace(
        "document=doc-1;", "document=doc-1-foreign;"
    )
    # The machine notes remain genuine: only the visible receipt is damaged.
    with pytest.raises(CustomerOutputVerificationError, match="source_reference lineage is incomplete"):
        verify_sealed_customer_output(sealed, [tampered, rows[1]])


def test_source_reference_conflicting_duplicate_identity_token_fails_closed() -> None:
    sealed, rows = sealed_and_rows()
    tampered = dict(rows[0])
    tampered["source_reference"] += "; document=doc-foreign"
    with pytest.raises(CustomerOutputVerificationError, match="conflicting identity tokens"):
        verify_sealed_customer_output(sealed, [tampered, rows[1]])


def test_source_reference_extra_nonidentity_estimator_note_is_allowed() -> None:
    sealed, rows = sealed_and_rows()
    annotated = dict(rows[0])
    annotated["source_reference"] += "; estimator note: checked"
    report = verify_sealed_customer_output(sealed, [annotated, rows[1]])
    assert report.verified_quantity_ids == ("qty-1", "qty-2")


def test_live_pb_auto_geometry_caption_preserves_exact_machine_source_identity() -> None:
    sealed, rows = sealed_and_rows()
    customer_rows = [dict(row) for row in rows]
    customer_rows[0]["source_reference"] = (
        "PB Auto Geometry v1.2.19 · " + customer_rows[0]["source_reference"]
    )
    assert verify_sealed_customer_output(sealed, customer_rows).verified_quantity_ids == (
        "qty-1", "qty-2",
    )


def test_live_caption_cannot_hide_suffix_forged_quantity_id() -> None:
    sealed, rows = sealed_and_rows()
    customer_rows = [dict(row) for row in rows]
    original = customer_rows[0]["source_reference"]
    assert original.startswith("QuantityEvidence qty-1;")
    customer_rows[0]["source_reference"] = (
        "PB Auto Geometry v1.2.19 · "
        + original.replace("QuantityEvidence qty-1;", "QuantityEvidence qty-1-foreign;", 1)
    )
    with pytest.raises(CustomerOutputVerificationError, match="source_reference lineage is incomplete"):
        verify_sealed_customer_output(sealed, customer_rows)


def test_boolean_customer_quantity_cannot_impersonate_one_sealed_unit() -> None:
    q = quantity("qty-boolean", "floor-boolean", value=1.0)
    source_trace = trace(q)
    sealed = seal_source_closed_run(
        (q,), project_id="project-7",
        traces_by_quantity_id={q.quantity_id: source_trace},
    )
    rows = adapter.quantities_to_takeoff_output_rows(
        (q,),
        traces_by_quantity_id={q.quantity_id: source_trace},
        authorities_by_quantity_id={q.quantity_id: authority()},
    )
    assert len(rows) == 1
    assert verify_sealed_customer_output(sealed, rows).valid_quantity_count == 1

    false_measurement = dict(rows[0], quantity=True)
    with pytest.raises(CustomerOutputVerificationError, match="Boolean"):
        verify_sealed_customer_output(sealed, (false_measurement,))

    # Real numeric representations, including persisted database numeric
    # strings, are still source/lineage verified against the sealed value.
    numeric_int = dict(rows[0], quantity=1)
    numeric_string = dict(rows[0], quantity="1.0")
    assert verify_sealed_customer_output(sealed, (numeric_int,)).valid_quantity_count == 1
    assert verify_sealed_customer_output(sealed, (numeric_string,)).valid_quantity_count == 1


@pytest.mark.parametrize(
    "invalid_notes",
    ('{"adapter":"commercial_takeoff",', '"manual text"', "corrupt notes"),
)
def test_direct_customer_provenance_cannot_hide_invalid_persisted_notes(
    invalid_notes: str,
) -> None:
    sealed, rows = sealed_and_rows()
    corrupted = dict(rows[0], notes=invalid_notes)
    with pytest.raises(CustomerOutputVerificationError, match="projection provenance"):
        verify_sealed_customer_output(sealed, (corrupted, rows[1]))


def test_nested_duplicate_notes_identity_cannot_hide_behind_direct_copy() -> None:
    import json

    sealed, rows = sealed_and_rows()
    corrupted = dict(rows[0])
    original_notes = json.loads(corrupted["notes"])
    assert original_notes["source_trace"]["source_sha256"] == SHA
    encoded = json.dumps(original_notes, sort_keys=True)
    assert '"source_trace": {' in encoded
    corrupted["notes"] = encoded.replace(
        '"source_trace": {',
        '"source_trace": {"source_sha256": "' + ("b" * 64) + '", ',
        1,
    )
    # Last-write-wins would have accepted the later genuine SHA field while
    # silently discarding a first, conflicting source identity.
    with pytest.raises(CustomerOutputVerificationError, match="duplicate provenance key"):
        verify_sealed_customer_output(sealed, (corrupted, rows[1]))


def test_notes_provenance_must_remain_a_structured_commercial_receipt() -> None:
    import json

    sealed, rows = sealed_and_rows()
    structured = dict(rows[0], notes=json.dumps({"other": "manual"}))
    with pytest.raises(
        CustomerOutputVerificationError,
        match="conflicting direct and persisted projection provenance",
    ):
        verify_sealed_customer_output(sealed, (structured, rows[1]))


def test_captioned_automated_receipt_cannot_be_disguised_as_manual() -> None:
    sealed, rows = sealed_and_rows()
    orphan = dict(rows[0])
    orphan.pop("quantity_id")
    orphan.pop("commercial_projection_provenance", None)
    orphan["notes"] = "damaged persisted provenance"
    orphan["source_reference"] = (
        "PB Auto Geometry v1.2.19 · " + rows[0]["source_reference"]
    )
    with pytest.raises(CustomerOutputVerificationError, match="missing quantity identity"):
        verify_sealed_customer_output(sealed, [*rows, orphan])


def test_manual_caption_without_machine_quantity_receipt_stays_manual() -> None:
    sealed, rows = sealed_and_rows()
    manual = {
        "description": "Estimator manual observation",
        "source_reference": "PB Auto Geometry v1.2.19 · estimator note only",
        "quantity": 1,
    }
    report = verify_sealed_customer_output(sealed, [*rows, manual])
    assert report.verified_quantity_ids == ("qty-1", "qty-2")
    assert report.customer_row_count == 2



@pytest.mark.parametrize(("section", "field"), (
    ("quantity", "input_entity_ids"),
    ("quantity", "evidence_ids"),
    ("source_trace", "canonical_entity_ids"),
    ("source_trace", "evidence_ids"),
))
@pytest.mark.parametrize("forged", ("mapping", "string"))
def test_customer_source_lineage_never_coerces_non_array_identity_receipts(
    section: str, field: str, forged: str,
) -> None:
    import copy
    import json

    sealed, rows = sealed_and_rows()
    corrupt = dict(rows[0])
    provenance = copy.deepcopy(corrupt["commercial_projection_provenance"])
    genuine = provenance[section][field]
    assert type(genuine) is list and genuine
    if forged == "mapping":
        provenance[section][field] = {str(value): None for value in genuine}
    else:
        if len(genuine) > 1:
            # Use a one-element clone to trigger the shape gate; the verifier
            # must reject the wire format before using identity correspondence.
            provenance[section][field] = str(genuine[0])
        else:
            provenance[section][field] = str(genuine[0])
    corrupt["commercial_projection_provenance"] = provenance
    corrupt["notes"] = json.dumps(provenance)
    with pytest.raises(CustomerOutputVerificationError, match="array of canonical strings"):
        verify_sealed_customer_output(sealed, [corrupt, rows[1]])


@pytest.mark.parametrize("field", ("canonical_entity_ids", "evidence_ids"))
def test_customer_projection_top_level_lineage_requires_arrays(field: str) -> None:
    sealed, rows = sealed_and_rows()
    corrupt = dict(rows[0])
    genuine = corrupt[field]
    assert type(genuine) in (list, tuple)
    corrupt[field] = {str(item): None for item in genuine}
    with pytest.raises(CustomerOutputVerificationError, match="array of canonical strings"):
        verify_sealed_customer_output(sealed, [corrupt, rows[1]])


def test_valid_producer_array_receipts_remain_verified_after_wire_shape_guard() -> None:
    sealed, rows = sealed_and_rows()
    result = verify_sealed_customer_output(sealed, rows)
    assert result.verified_quantity_ids == ("qty-1", "qty-2")
    assert result.customer_row_count == 2



@pytest.mark.parametrize("alteration", ("blank", "leading-space", "trailing-space"))
def test_customer_source_lineage_cannot_hide_noncanonical_extra_id(
    alteration: str,
) -> None:
    import copy
    import json

    sealed, rows = sealed_and_rows()
    modified = dict(rows[0])
    provenance = copy.deepcopy(modified["commercial_projection_provenance"])
    source_ids = provenance["quantity"]["input_entity_ids"]
    assert type(source_ids) is list and len(source_ids) == 1
    if alteration == "blank":
        source_ids.append("")
    elif alteration == "leading-space":
        source_ids[0] = " " + source_ids[0]
    else:
        source_ids[0] += " "
    modified["commercial_projection_provenance"] = provenance
    modified["notes"] = json.dumps(provenance)
    with pytest.raises(CustomerOutputVerificationError, match="array of canonical strings"):
        verify_sealed_customer_output(sealed, [modified, rows[1]])
