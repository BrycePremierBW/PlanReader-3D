"""Fail-closed audit for sealed QuantityEvidence -> customer takeoff rows.

This module does not create, transform, approve, or score quantities. It proves
that the non-abstained rows in a sealed source-closed run are represented
exactly once in the commercial customer projection with the same source,
revision, canonical-entity, and evidence lineage.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import re
from typing import Any

from pb_source_closed_run_export import (
    SealedSourceClosedRun,
    SealedSourceClosedQuantity,
    SourceClosedRunExportError,
    sealed_source_closed_run_from_dict,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CustomerOutputVerificationError(RuntimeError):
    """The sealed run and customer projection are not a one-to-one lineage match."""


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _norm_unit(value: Any) -> str:
    clean = _clean(value).lower().replace(" ", "")
    aliases = {
        "m²": "m2",
        "sqm": "m2",
        "m³": "m3",
        "each": "ea",
        "no": "ea",
        "nr": "ea",
        "lm": "m",
    }
    return aliases.get(clean, clean)


def _string_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (_clean(values),) if _clean(values) else ()
    try:
        return tuple(sorted(_clean(value) for value in values if _clean(value)))
    except TypeError as exc:
        raise CustomerOutputVerificationError(
            "customer lineage field must be a sequence"
        ) from exc


def _strict_customer_notes(notes: str) -> Mapping[str, Any]:
    """Parse automated notes without last-write-wins or corrupted lineage."""
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CustomerOutputVerificationError(
                    f"customer row notes contain duplicate provenance key: {key}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(notes, object_pairs_hook=unique_keys)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise CustomerOutputVerificationError(
            "customer row notes contain invalid projection provenance JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CustomerOutputVerificationError(
            "customer row notes projection provenance is not an object"
        )
    return payload


def _canonical_source_id_array(name: str, values: Any) -> tuple[str, ...]:
    """Require source-authenticated array receipts, not coerced keys/chars."""
    if type(values) not in (list, tuple) or any(
        type(item) is not str or not item or item != item.strip()
        for item in values
    ):
        raise CustomerOutputVerificationError(
            f"customer source provenance {name} must be an array of canonical strings"
        )
    normalized = _string_tuple(values)
    if len(normalized) != len(set(normalized)):
        raise CustomerOutputVerificationError(f"customer source provenance {name} contains duplicate identities")
    return normalized


def _projection_provenance(row: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = row.get("commercial_projection_provenance")
    if isinstance(direct, Mapping):
        if _clean(direct.get("adapter")) != "commercial_takeoff":
            raise CustomerOutputVerificationError("customer row has invalid commercial projection adapter")
        # Automated notes are a second persisted source receipt, not an
        # optional escape hatch for a valid-looking structured copy.
        notes = row.get("notes")
        if isinstance(notes, str) and notes.strip():
            persisted = _strict_customer_notes(notes)
            if (
                _clean(persisted.get("adapter")) != "commercial_takeoff"
                or persisted != direct
            ):
                raise CustomerOutputVerificationError(
                    "customer row has conflicting direct and persisted projection provenance"
                )
        return direct

    notes = row.get("notes")
    if isinstance(notes, str) and notes.strip():
        parsed = _strict_customer_notes(notes)
        if _clean(parsed.get("adapter")) != "commercial_takeoff":
            raise CustomerOutputVerificationError("customer row has invalid commercial projection adapter")
        return parsed

    raise CustomerOutputVerificationError(
        "customer row is missing commercial projection provenance"
    )


def _customer_quantity_id(row: Mapping[str, Any]) -> str:
    direct_value = row.get("quantity_id")
    if direct_value is not None:
        if type(direct_value) is not str or direct_value != direct_value.strip():
            raise CustomerOutputVerificationError("customer row has malformed quantity identity")
        if direct_value:
            return direct_value

    provenance = row.get("commercial_projection_provenance")
    if isinstance(provenance, Mapping):
        qprov = provenance.get("quantity")
        if isinstance(qprov, Mapping):
            return _clean(qprov.get("quantity_id"))

    notes = row.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        return ""
    try:
        parsed = _strict_customer_notes(notes)
    except CustomerOutputVerificationError as exc:
        if _has_machine_quantity_receipt(row.get("source_reference")) and "duplicate provenance key" not in str(exc):
            raise CustomerOutputVerificationError(
                "automated customer row is missing quantity identity"
            ) from exc
        if "duplicate provenance key" in str(exc):
            raise
        return ""
    if not isinstance(parsed, Mapping):
        return ""
    if _clean(parsed.get("adapter")) != "commercial_takeoff":
        return ""
    qprov = parsed.get("quantity")
    if not isinstance(qprov, Mapping):
        return ""
    return _clean(qprov.get("quantity_id"))


def _has_machine_quantity_receipt(value: Any) -> bool:
    """Recognize signed auto receipt even after the known UI caption prefix."""
    source_reference = _clean(value)
    first_token = source_reference.split(";", 1)[0].strip()
    if " · " in first_token:
        first_token = first_token.rsplit(" · ", 1)[-1].strip()
    return first_token.startswith("QuantityEvidence ") and bool(
        first_token[len("QuantityEvidence "):].strip()
    )


def _require_optional_equal(
    name: str,
    actual: Any,
    expected: Any,
    quantity_id: str,
) -> None:
    if actual is None or _clean(actual) == "":
        return
    _require_equal(name, actual, expected, quantity_id)


def _require_equal(name: str, actual: Any, expected: Any, quantity_id: str) -> None:
    if actual != expected:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} {name} mismatch: "
            f"{actual!r} != {expected!r}"
        )


def _verify_row_lineage(
    sealed: SealedSourceClosedQuantity,
    row: Mapping[str, Any],
) -> None:
    quantity_id = sealed.quantity_id
    if not sealed.lineage_ok:
        raise CustomerOutputVerificationError(
            f"sealed quantity {quantity_id!r} has incomplete lineage: "
            + ", ".join(sealed.lineage_reason_codes)
        )

    provenance = _projection_provenance(row)
    qprov = provenance.get("quantity")
    tprov = provenance.get("source_trace")
    apro = provenance.get("measurement_authority")
    if (
        not isinstance(qprov, Mapping)
        or not isinstance(tprov, Mapping)
        or not isinstance(apro, Mapping)
    ):
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has incomplete projection provenance"
        )
    if not _clean(apro.get("method")):
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} is missing measurement authority lineage"
        )

    # A signed source-closed quantity also authenticates its evidence status,
    # authority and confidence. A row that changes these claims while keeping
    # its quantity ID and value must not pass commercial lineage verification.
    _require_equal("provenance.status", _clean(qprov.get("status")), sealed.status, quantity_id)
    _require_equal("provenance.authority", _clean(qprov.get("authority")), sealed.authority, quantity_id)
    if type(qprov.get("abstained")) is not bool or qprov["abstained"] is not False:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has invalid provenance.abstained"
        )
    for name, actual, expected in (
        ("provenance.value", qprov.get("value"), sealed.value),
        ("provenance.confidence", qprov.get("confidence"), sealed.confidence),
    ):
        if type(actual) not in (int, float):
            raise CustomerOutputVerificationError(
                f"customer row {quantity_id!r} has nonnumeric {name}"
            )
        if not math.isfinite(actual):
            raise CustomerOutputVerificationError(
                f"customer row {quantity_id!r} has non-finite {name}"
            )
        _require_equal(name, float(actual), float(expected), quantity_id)
    _require_equal(
        "provenance.current_revision_id",
        _clean(tprov.get("current_revision_id")),
        sealed.revision_id,
        quantity_id,
    )
    method = _clean(apro.get("method"))
    if method not in {"direct_evidence", "figured_dimension", "scaled_geometry"}:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has unrecognized measurement authority method"
        )
    figured = _canonical_source_id_array(
        "figured_dimension_ids", apro.get("figured_dimension_ids")
    )
    if method == "figured_dimension" and not figured:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has incomplete figured measurement authority"
        )
    if method == "scaled_geometry" and (
        not _clean(apro.get("resolved_scale_id"))
        or _clean(apro.get("scale_status")).lower() not in {"verified", "resolved"}
        or apro.get("scale_conflicts")
    ):
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has unverified scaled measurement authority"
        )
    if row.get("measurement_method") is not None:
        _require_equal("measurement_method", _clean(row.get("measurement_method")), method, quantity_id)
    if row.get("figured_dimension_ids") is not None:
        _require_equal(
            "figured_dimension_ids",
            _canonical_source_id_array("figured_dimension_ids", row.get("figured_dimension_ids")),
            figured, quantity_id,
        )
    if row.get("quantity_authority") is not None:
        _require_equal("quantity_authority", _clean(row.get("quantity_authority")), sealed.authority, quantity_id)

    _require_equal(
        "provenance.quantity_id",
        _clean(qprov.get("quantity_id")),
        sealed.quantity_id,
        quantity_id,
    )
    _require_equal(
        "provenance.family",
        _clean(qprov.get("family")),
        sealed.family,
        quantity_id,
    )
    _require_equal(
        "provenance.semantic_key",
        _clean(qprov.get("semantic_key")),
        sealed.semantic_key,
        quantity_id,
    )
    _require_equal(
        "provenance.unit",
        _norm_unit(qprov.get("unit")),
        _norm_unit(sealed.unit),
        quantity_id,
    )
    _require_equal(
        "provenance.input_entity_ids",
        _canonical_source_id_array("input_entity_ids", qprov.get("input_entity_ids")),
        tuple(sorted(sealed.object_identity_refs)),
        quantity_id,
    )
    _require_equal(
        "provenance.quantity_evidence_ids",
        _canonical_source_id_array("evidence_ids", qprov.get("evidence_ids")),
        tuple(sorted(sealed.evidence_ids)),
        quantity_id,
    )
    _require_equal(
        "provenance.source_project_id",
        _clean(tprov.get("project_id")),
        sealed.project_id,
        quantity_id,
    )
    _require_equal(
        "provenance.source_document_id",
        _clean(tprov.get("document_id")),
        sealed.document_id,
        quantity_id,
    )
    _require_equal(
        "provenance.source_sha256",
        _clean(tprov.get("source_sha256")).lower(),
        sealed.source_sha256.lower(),
        quantity_id,
    )
    _require_equal(
        "provenance.source_page",
        _clean(tprov.get("source_page")),
        sealed.source_page,
        quantity_id,
    )
    _require_equal(
        "provenance.viewport_id",
        _clean(tprov.get("viewport_id")),
        sealed.viewport_id,
        quantity_id,
    )
    _require_equal(
        "provenance.revision_id",
        _clean(tprov.get("revision_id")),
        sealed.revision_id,
        quantity_id,
    )
    _require_equal(
        "provenance.canonical_entity_ids",
        _canonical_source_id_array("canonical_entity_ids", tprov.get("canonical_entity_ids")),
        tuple(sorted(sealed.trace_canonical_entity_ids)),
        quantity_id,
    )
    _require_equal(
        "provenance.trace_evidence_ids",
        _canonical_source_id_array("trace_evidence_ids", tprov.get("evidence_ids")),
        tuple(sorted(sealed.trace_evidence_ids)),
        quantity_id,
    )

    _require_optional_equal(
        "project_id", _clean(row.get("project_id")), sealed.project_id, quantity_id
    )
    _require_optional_equal(
        "quantity_family", _clean(row.get("quantity_family")), sealed.family, quantity_id
    )
    _require_optional_equal(
        "semantic_key", _clean(row.get("semantic_key")), sealed.semantic_key, quantity_id
    )
    _require_equal("unit", _norm_unit(row.get("unit")), _norm_unit(sealed.unit), quantity_id)
    _require_optional_equal(
        "document_id", _clean(row.get("document_id")), sealed.document_id, quantity_id
    )
    if _clean(row.get("source_sha256")):
        _require_equal(
            "source_sha256",
            _clean(row.get("source_sha256")).lower(),
            sealed.source_sha256.lower(),
            quantity_id,
        )
    _require_equal("source_page", _clean(row.get("source_page")), sealed.source_page, quantity_id)
    _require_optional_equal(
        "viewport_id", _clean(row.get("viewport_id")), sealed.viewport_id, quantity_id
    )
    _require_optional_equal(
        "revision_id", _clean(row.get("revision_id")), sealed.revision_id, quantity_id
    )

    if sealed.value is None:
        raise CustomerOutputVerificationError(
            f"non-abstained sealed quantity {quantity_id!r} has no value"
        )
    # bool is a subclass of int in Python; float(True) == 1.0 and
    # float(False) == 0.0. A Boolean customer field is not a measured
    # quantity, even if it numerically equals the sealed value.
    if type(row.get("quantity")) is bool:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has Boolean instead of measured quantity"
        )
    try:
        row_value = float(row.get("quantity"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has invalid quantity"
        ) from exc
    if not math.isfinite(row_value):
        raise CustomerOutputVerificationError(f"customer row {quantity_id!r} has non-finite quantity")
    _require_equal("quantity", row_value, float(sealed.value), quantity_id)
    if row.get("ai_baseline_quantity") is not None:
        actual_baseline = row.get("ai_baseline_quantity")
        if type(actual_baseline) not in (int, float) or not math.isfinite(actual_baseline):
            raise CustomerOutputVerificationError(
                f"customer row {quantity_id!r} has invalid ai_baseline_quantity"
            )
        _require_equal("ai_baseline_quantity", float(actual_baseline), float(sealed.value), quantity_id)
    if row.get("confidence") is not None:
        actual_confidence = row.get("confidence")
        if type(actual_confidence) not in (int, float) or not math.isfinite(actual_confidence):
            raise CustomerOutputVerificationError(
                f"customer row {quantity_id!r} has invalid confidence"
            )
        _require_equal("confidence", float(actual_confidence), float(sealed.confidence), quantity_id)

    if row.get("canonical_entity_ids") is not None:
        _require_equal(
            "canonical_entity_ids",
            _canonical_source_id_array("canonical_entity_ids", row.get("canonical_entity_ids")),
            tuple(sorted(sealed.trace_canonical_entity_ids)),
            quantity_id,
        )
    if row.get("evidence_ids") is not None:
        _require_equal(
            "evidence_ids",
            _canonical_source_id_array("trace_evidence_ids", row.get("evidence_ids")),
            tuple(sorted(sealed.trace_evidence_ids)),
            quantity_id,
        )

    fingerprint = _clean(row.get("commercial_projection_fingerprint")).lower()
    if fingerprint and not _SHA256_RE.fullmatch(fingerprint):
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} has an invalid projection fingerprint"
        )

    source_reference = _clean(row.get("source_reference"))
    if not source_reference:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} is missing source_reference lineage"
        )
    required_reference_parts = (
        f"QuantityEvidence {quantity_id}",
        f"document={sealed.document_id}",
        f"sha256={sealed.source_sha256}",
        f"viewport={sealed.viewport_id}",
        f"revision={sealed.revision_id}",
    )
    # The source reference is a semicolon-delimited machine receipt.
    # Substring matching accepts e.g. document=doc-1-changed as proof of
    # document=doc-1. Demand exact receipt tokens and reject duplicate
    # identity-bearing tokens rather than interpreting prefixes as lineage.
    reference_parts = tuple(
        part.strip() for part in source_reference.split(";") if part.strip()
    )
    # Existing live PB Auto Geometry customer rows prepend a human-readable
    # producer caption to the *first* machine token using the middle-dot
    # delimiter. Preserve that one known envelope while still requiring the
    # actual QuantityEvidence ID as one complete terminal token, not a prefix.
    # Never strip or normalize the document/SHA/viewport/revision tokens.
    if reference_parts and " · " in reference_parts[0]:
        reference_parts = (
            reference_parts[0].rsplit(" · ", 1)[-1].strip(),
            *reference_parts[1:],
        )
    missing_reference_parts = [
        part for part in required_reference_parts if part not in reference_parts
    ]
    duplicate_reference_keys = [
        key for key in ("QuantityEvidence ", "document=", "sha256=", "viewport=", "revision=")
        if sum(part.startswith(key) for part in reference_parts) > 1
    ]
    if duplicate_reference_keys:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} source_reference has conflicting identity tokens: "
            + ", ".join(duplicate_reference_keys)
        )
    if missing_reference_parts:
        raise CustomerOutputVerificationError(
            f"customer row {quantity_id!r} source_reference lineage is incomplete: "
            + ", ".join(missing_reference_parts)
        )


@dataclass(frozen=True)
class SealedCustomerOutputVerification:
    project_id: str
    sealed_quantity_count: int
    valid_quantity_count: int
    abstained_quantity_count: int
    customer_row_count: int
    verified_quantity_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "sealed_quantity_count": self.sealed_quantity_count,
            "valid_quantity_count": self.valid_quantity_count,
            "abstained_quantity_count": self.abstained_quantity_count,
            "customer_row_count": self.customer_row_count,
            "verified_quantity_ids": list(self.verified_quantity_ids),
            "complete": True,
        }


def verify_sealed_customer_output(
    sealed_run: SealedSourceClosedRun,
    customer_rows: Sequence[Mapping[str, Any]],
) -> SealedCustomerOutputVerification:
    """Prove a bijection between valid sealed quantities and customer rows.

    Rows without quantity_id are outside this automated projection and are
    ignored (for example manual estimator rows). Every row with a quantity_id is
    treated as an automated customer projection and must correspond to exactly
    one non-abstained sealed quantity.
    """
    if not isinstance(sealed_run, SealedSourceClosedRun):
        raise TypeError("sealed_run must be a SealedSourceClosedRun")
    try:
        sealed_run = sealed_source_closed_run_from_dict(sealed_run.to_dict())
    except SourceClosedRunExportError as exc:
        raise CustomerOutputVerificationError(
            "sealed source-closed run failed cryptographic verification"
        ) from exc

    if isinstance(customer_rows, (str, bytes, Mapping)):
        raise CustomerOutputVerificationError("customer rows must be a sequence of row mappings")
    sealed_by_id = {row.quantity_id: row for row in sealed_run.quantities}
    if len(sealed_by_id) != len(sealed_run.quantities):
        raise CustomerOutputVerificationError("sealed run contains duplicate quantity ids")

    valid = {
        row.quantity_id: row
        for row in sealed_run.quantities
        if not row.abstained
    }
    abstained_ids = {
        row.quantity_id for row in sealed_run.quantities if row.abstained
    }

    customer_by_id: dict[str, Mapping[str, Any]] = {}
    for row in customer_rows:
        if not isinstance(row, Mapping):
            raise TypeError("customer_rows must contain mappings")
        quantity_id = _customer_quantity_id(row)
        if not quantity_id:
            # A damaged automated projection must not evade the bijection
            # by dropping its quantity ID and embedded provenance. Manual
            # estimator rows without automated source signatures remain out
            # of scope for source-closed quantity reconciliation.
            notes = row.get("notes")
            notes_provenance = None
            if isinstance(notes, str) and notes.strip():
                try:
                    notes_provenance = _strict_customer_notes(notes)
                except CustomerOutputVerificationError:
                    if _has_machine_quantity_receipt(row.get("source_reference")):
                        raise
                    # Malformed notes without a source receipt are manual-only
                    # unless their structured projection receipt says otherwise.
                    pass
            if (
                row.get("commercial_projection_provenance") is not None
                or _has_machine_quantity_receipt(row.get("source_reference"))
                or (
                    isinstance(notes_provenance, Mapping)
                    and _clean(notes_provenance.get("adapter")) == "commercial_takeoff"
                )
            ):
                raise CustomerOutputVerificationError(
                    "automated customer row is missing quantity identity"
                )
            continue
        if quantity_id in customer_by_id:
            raise CustomerOutputVerificationError(
                f"duplicate customer row for quantity {quantity_id!r}"
            )
        customer_by_id[quantity_id] = row

    expected_ids = set(valid)
    actual_ids = set(customer_by_id)
    missing = sorted(expected_ids - actual_ids)
    leaked_abstentions = sorted(abstained_ids & actual_ids)
    extra = sorted(actual_ids - expected_ids - abstained_ids)
    if missing:
        raise CustomerOutputVerificationError(
            "valid sealed quantities missing customer rows: " + ", ".join(missing)
        )
    if leaked_abstentions:
        raise CustomerOutputVerificationError(
            "abstained quantities leaked into customer output: "
            + ", ".join(leaked_abstentions)
        )
    if extra:
        raise CustomerOutputVerificationError(
            "customer rows have no valid sealed quantity: " + ", ".join(extra)
        )

    for quantity_id in sorted(expected_ids):
        _verify_row_lineage(valid[quantity_id], customer_by_id[quantity_id])

    return SealedCustomerOutputVerification(
        project_id=sealed_run.project_id,
        sealed_quantity_count=len(sealed_run.quantities),
        valid_quantity_count=len(valid),
        abstained_quantity_count=len(abstained_ids),
        customer_row_count=len(customer_by_id),
        verified_quantity_ids=tuple(sorted(expected_ids)),
    )
