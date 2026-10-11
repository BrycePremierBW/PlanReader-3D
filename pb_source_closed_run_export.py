"""Benchmark-neutral sealed export of source-closed production quantities.

The export contains only production-owned identities and provenance. It has no
knowledge of benchmark IDs, expected quantities, reference truth values, or scoring
rules. A benchmark may reconcile these records only after the run is sealed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from pb_migration_contracts import (
    QuantityEvidence,
    canonical_contract_json,
    stable_contract_id,
)
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace, quantity_status_not_publishable


SOURCE_CLOSED_RUN_EXPORT_SCHEMA_VERSION = "1.0.0"


class SourceClosedRunExportError(RuntimeError):
    """Base error for fail-closed source-closed run export."""


class MissingSourceClosedRunTraceError(SourceClosedRunExportError):
    """A production quantity is missing the source/canonical trace needed to seal it."""


class SourceClosedRunConflictError(SourceClosedRunExportError):
    """The supplied run contains contradictory identity or project lineage."""


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _metadata(quantity: QuantityEvidence) -> Mapping[str, Any]:
    return quantity.metadata if isinstance(quantity.metadata, Mapping) else {}


def _lineage_reasons(
    quantity: QuantityEvidence,
    trace: CommercialTakeoffSourceTrace,
) -> tuple[str, ...]:
    reasons: list[str] = []
    metadata = _metadata(quantity)
    expected = {
        "project_id": trace.project_id,
        "document_id": trace.document_id,
        "source_sha256": trace.source_sha256,
        "revision_id": trace.revision_id,
    }
    for key, authoritative in expected.items():
        candidate = metadata.get(key)
        if candidate is None:
            continue
        if _clean(candidate).lower() != _clean(authoritative).lower():
            reasons.append(f"{key}_mismatch")

    missing_entities = set(quantity.input_entity_ids) - set(trace.canonical_entity_ids)
    if missing_entities:
        reasons.append("canonical_entity_trace_incomplete")
    missing_evidence = set(quantity.evidence_ids) - set(trace.evidence_ids)
    if missing_evidence:
        reasons.append("evidence_trace_incomplete")

    if not quantity.abstained and not quantity.input_entity_ids:
        reasons.append("quantity_identity_missing")
    if not quantity.abstained and quantity.blocking_reasons:
        reasons.append("quantity_publication_blocked")
    status = _clean(quantity.status).lower()
    if "conflict" in status:
        reasons.append("quantity_status_conflict")
    if not quantity.abstained and quantity_status_not_publishable(status):
        reasons.append("quantity_status_not_publishable")
    if any("conflict" in _clean(reason).lower() for reason in quantity.reason_codes):
        reasons.append("quantity_reason_conflict")
    return tuple(dict.fromkeys(reasons))


@dataclass(frozen=True)
class SealedSourceClosedQuantity:
    project_id: str
    quantity_id: str
    family: str
    semantic_key: str
    value: float | None
    unit: str
    status: str
    authority: str
    confidence: float
    abstained: bool
    document_id: str
    source_sha256: str
    source_page: str
    viewport_id: str
    revision_id: str
    object_identity_refs: tuple[str, ...]
    trace_canonical_entity_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    trace_evidence_ids: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    lineage_ok: bool
    lineage_reason_codes: tuple[str, ...]
    schema_version: str = SOURCE_CLOSED_RUN_EXPORT_SCHEMA_VERSION

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "quantity_id": self.quantity_id,
            "family": self.family,
            "semantic_key": self.semantic_key,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "authority": self.authority,
            "confidence": float(self.confidence),
            "abstained": bool(self.abstained),
            "document_id": self.document_id,
            "source_sha256": self.source_sha256,
            "source_page": self.source_page,
            "viewport_id": self.viewport_id,
            "revision_id": self.revision_id,
            "object_identity_refs": list(self.object_identity_refs),
            "trace_canonical_entity_ids": list(self.trace_canonical_entity_ids),
            "evidence_ids": list(self.evidence_ids),
            "trace_evidence_ids": list(self.trace_evidence_ids),
            "blocking_reasons": list(self.blocking_reasons),
            "reason_codes": list(self.reason_codes),
            "lineage_ok": bool(self.lineage_ok),
            "lineage_reason_codes": list(self.lineage_reason_codes),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            canonical_contract_json(self.payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "fingerprint": self.fingerprint}


def sealed_source_closed_run_from_dict(
    payload: Mapping[str, Any],
) -> "SealedSourceClosedRun":
    """Load and cryptographically re-verify a sealed run dictionary.

    This is intentionally stricter than ordinary dataclass construction. Every
    nested quantity fingerprint, the source/revision envelope, deterministic
    run_id and top-level fingerprint are recomputed before the run is accepted.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("sealed run payload must be a mapping")
    if _clean(payload.get("schema_version")) != SOURCE_CLOSED_RUN_EXPORT_SCHEMA_VERSION:
        raise SourceClosedRunConflictError("unsupported sealed run schema_version")

    # The canonical producer writes actual arrays of source envelope IDs.
    # JSON strings and mappings must not be iterated/coerced to reconstruct
    # the same signed ID tuples from different wire receipts.
    for envelope_field in ("source_sha256s", "revision_ids"):
        envelope = payload.get(envelope_field)
        if type(envelope) not in (list, tuple) or any(
            type(item) is not str for item in envelope
        ):
            raise SourceClosedRunConflictError(
                f"sealed run {envelope_field} must be an array of strings"
            )

    raw_rows = payload.get("quantities")
    if not isinstance(raw_rows, (list, tuple)):
        raise SourceClosedRunConflictError("sealed run quantities must be a sequence")

    rows: list[SealedSourceClosedQuantity] = []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise SourceClosedRunConflictError(
                f"sealed quantity {index} must be a mapping"
            )
        # Signed lineage arrays are canonical JSON sequences, not strings,
        # mappings or numerics with keys/characters that happen to rehydrate
        # into the same source identities and preserve a normalized fingerprint.
        for lineage_field in (
            "object_identity_refs", "trace_canonical_entity_ids",
            "evidence_ids", "trace_evidence_ids", "blocking_reasons",
            "reason_codes", "lineage_reason_codes",
        ):
            raw_values = raw.get(lineage_field)
            if type(raw_values) not in (list, tuple) or any(
                type(item) is not str for item in raw_values
            ):
                raise SourceClosedRunConflictError(
                    f"sealed quantity {index} has non-array lineage {lineage_field}"
                )
        # A valid original seal emits genuine JSON booleans and numeric
        # quantities. Last-minute string/int coercion during import can let
        # an altered receipt retain the same normalized fingerprint (e.g.
        # bool("false") is True, float("13.27") equals 13.27).
        # Reject a noncanonical wire type before re-verifying the fingerprint.
        for boolean_field in ("abstained", "lineage_ok"):
            if type(raw.get(boolean_field)) is not bool:
                raise SourceClosedRunConflictError(
                    f"sealed quantity {index} has non-Boolean {boolean_field}"
                )
        for numeric_field in ("value", "confidence"):
            numeric_value = raw.get(numeric_field)
            if (numeric_field == "confidence" or numeric_value is not None) and (
                type(numeric_value) not in (int, float)
            ):
                raise SourceClosedRunConflictError(
                    f"sealed quantity {index} has nonnumeric {numeric_field}"
                )
            if numeric_value is not None:
                try:
                    finite = math.isfinite(numeric_value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise SourceClosedRunConflictError(
                        f"sealed quantity {index} has non-finite {numeric_field}"
                    )
        try:
            row = SealedSourceClosedQuantity(
                project_id=_clean(raw.get("project_id")),
                quantity_id=_clean(raw.get("quantity_id")),
                family=_clean(raw.get("family")),
                semantic_key=_clean(raw.get("semantic_key")),
                value=(
                    None
                    if raw.get("value") is None
                    else float(raw.get("value"))
                ),
                unit=_clean(raw.get("unit")),
                status=_clean(raw.get("status")),
                authority=_clean(raw.get("authority")),
                confidence=float(raw.get("confidence")),
                abstained=bool(raw.get("abstained")),
                document_id=_clean(raw.get("document_id")),
                source_sha256=_clean(raw.get("source_sha256")),
                source_page=_clean(raw.get("source_page")),
                viewport_id=_clean(raw.get("viewport_id")),
                revision_id=_clean(raw.get("revision_id")),
                object_identity_refs=tuple(
                    _clean(value)
                    for value in (raw.get("object_identity_refs") or ())
                ),
                trace_canonical_entity_ids=tuple(
                    _clean(value)
                    for value in (raw.get("trace_canonical_entity_ids") or ())
                ),
                evidence_ids=tuple(
                    _clean(value) for value in (raw.get("evidence_ids") or ())
                ),
                trace_evidence_ids=tuple(
                    _clean(value)
                    for value in (raw.get("trace_evidence_ids") or ())
                ),
                blocking_reasons=tuple(
                    _clean(value)
                    for value in (raw.get("blocking_reasons") or ())
                ),
                reason_codes=tuple(
                    _clean(value) for value in (raw.get("reason_codes") or ())
                ),
                lineage_ok=bool(raw.get("lineage_ok")),
                lineage_reason_codes=tuple(
                    _clean(value)
                    for value in (raw.get("lineage_reason_codes") or ())
                ),
                schema_version=_clean(raw.get("schema_version")),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceClosedRunConflictError(
                f"sealed quantity {index} is invalid"
            ) from exc

        supplied_fingerprint = _clean(raw.get("fingerprint")).lower()
        if not supplied_fingerprint or supplied_fingerprint != row.fingerprint:
            raise SourceClosedRunConflictError(
                f"sealed quantity fingerprint mismatch: {row.quantity_id or index}"
            )
        rows.append(row)

    project_id = _clean(payload.get("project_id"))
    expected = _build_sealed_run(rows, project_id=project_id)

    supplied_sources = tuple(
        sorted(
            _clean(value).lower()
            for value in (payload.get("source_sha256s") or ())
            if _clean(value)
        )
    )
    if supplied_sources != tuple(value.lower() for value in expected.source_sha256s):
        raise SourceClosedRunConflictError("sealed run source envelope is inconsistent")

    supplied_revisions = tuple(
        sorted(
            _clean(value)
            for value in (payload.get("revision_ids") or ())
            if _clean(value)
        )
    )
    if supplied_revisions != expected.revision_ids:
        raise SourceClosedRunConflictError("sealed run revision envelope is inconsistent")

    if _clean(payload.get("run_id")) != expected.run_id:
        raise SourceClosedRunConflictError("sealed run_id is inconsistent")
    supplied_fingerprint = _clean(payload.get("fingerprint")).lower()
    if not supplied_fingerprint or supplied_fingerprint != expected.fingerprint:
        raise SourceClosedRunConflictError("sealed run fingerprint is inconsistent")

    return expected


def seal_source_closed_quantity(
    quantity: QuantityEvidence,
    *,
    trace: CommercialTakeoffSourceTrace,
) -> SealedSourceClosedQuantity:
    """Seal one production quantity without benchmark knowledge or identity mapping."""
    if not isinstance(quantity, QuantityEvidence):
        raise TypeError("quantity must be a QuantityEvidence record")
    if not isinstance(trace, CommercialTakeoffSourceTrace):
        raise TypeError("trace must be a CommercialTakeoffSourceTrace")

    reasons = _lineage_reasons(quantity, trace)
    value = None if quantity.abstained else float(quantity.value)
    return SealedSourceClosedQuantity(
        project_id=trace.project_id,
        quantity_id=quantity.quantity_id,
        family=quantity.family,
        semantic_key=quantity.semantic_key,
        value=value,
        unit=quantity.unit,
        status=quantity.status,
        authority=quantity.authority,
        confidence=float(quantity.confidence),
        abstained=bool(quantity.abstained),
        document_id=trace.document_id,
        source_sha256=trace.source_sha256,
        source_page=trace.source_page,
        viewport_id=trace.viewport_id,
        revision_id=trace.revision_id,
        object_identity_refs=tuple(sorted(quantity.input_entity_ids)),
        trace_canonical_entity_ids=tuple(sorted(trace.canonical_entity_ids)),
        evidence_ids=tuple(sorted(quantity.evidence_ids)),
        trace_evidence_ids=tuple(sorted(trace.evidence_ids)),
        blocking_reasons=tuple(sorted(quantity.blocking_reasons)),
        reason_codes=tuple(sorted(quantity.reason_codes)),
        lineage_ok=not reasons,
        lineage_reason_codes=tuple(sorted(reasons)),
    )


@dataclass(frozen=True)
class SealedSourceClosedRun:
    run_id: str
    project_id: str
    source_sha256s: tuple[str, ...]
    revision_ids: tuple[str, ...]
    quantities: tuple[SealedSourceClosedQuantity, ...]
    schema_version: str = SOURCE_CLOSED_RUN_EXPORT_SCHEMA_VERSION

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "source_sha256s": list(self.source_sha256s),
            "revision_ids": list(self.revision_ids),
            "quantities": [row.to_dict() for row in self.quantities],
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            canonical_contract_json(self.payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "fingerprint": self.fingerprint}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _build_sealed_run(
    rows: Sequence[SealedSourceClosedQuantity],
    *,
    project_id: str,
) -> SealedSourceClosedRun:
    """Build one deterministic run envelope from already-sealed quantities."""
    clean_project_id = _clean(project_id)
    if not clean_project_id:
        raise ValueError("project_id must be non-empty")

    normalized: list[SealedSourceClosedQuantity] = []
    quantity_ids: set[str] = set()
    physical_claims: dict[
        tuple[str, str, tuple[str, ...]],
        SealedSourceClosedQuantity,
    ] = {}
    for row in rows:
        if not isinstance(row, SealedSourceClosedQuantity):
            raise TypeError(
                "sealed rows must contain only SealedSourceClosedQuantity records"
            )
        if row.project_id != clean_project_id:
            raise SourceClosedRunConflictError(
                f"quantity {row.quantity_id} belongs to project {row.project_id}"
            )
        if row.quantity_id in quantity_ids:
            raise SourceClosedRunConflictError(
                f"duplicate sealed quantity id: {row.quantity_id}"
            )
        quantity_ids.add(row.quantity_id)

        identities = tuple(
            sorted({_clean(value) for value in row.object_identity_refs if _clean(value)})
        )
        if not row.abstained and identities:
            claim_key = (
                _clean(row.family).lower(),
                _clean(row.semantic_key),
                identities,
            )
            prior = physical_claims.get(claim_key)
            if prior is not None:
                same_claim = (
                    prior.value == row.value
                    and _clean(prior.unit).lower() == _clean(row.unit).lower()
                )
                detail = "duplicate" if same_claim else "conflicting"
                raise SourceClosedRunConflictError(
                    f"{detail} sealed physical claim for family "
                    f"{row.family!r}, semantic key {row.semantic_key!r}, "
                    f"identities {identities!r}: "
                    f"{prior.quantity_id!r} vs {row.quantity_id!r}"
                )
            physical_claims[claim_key] = row

        normalized.append(row)

    normalized.sort(key=lambda row: row.quantity_id)
    source_sha256s = tuple(sorted({row.source_sha256 for row in normalized}))
    revision_ids = tuple(sorted({row.revision_id for row in normalized}))
    run_payload = {
        "schema_version": SOURCE_CLOSED_RUN_EXPORT_SCHEMA_VERSION,
        "project_id": clean_project_id,
        "source_sha256s": source_sha256s,
        "revision_ids": revision_ids,
        "quantity_fingerprints": tuple(row.fingerprint for row in normalized),
    }
    run_id = stable_contract_id("source_closed_run", run_payload, digest_chars=32)
    return SealedSourceClosedRun(
        run_id=run_id,
        project_id=clean_project_id,
        source_sha256s=source_sha256s,
        revision_ids=revision_ids,
        quantities=tuple(normalized),
    )


def seal_source_closed_run(
    quantities: Sequence[QuantityEvidence],
    *,
    project_id: str,
    traces_by_quantity_id: Mapping[str, CommercialTakeoffSourceTrace],
) -> SealedSourceClosedRun:
    """Seal a deterministic production run for later independent reconciliation."""
    clean_project_id = _clean(project_id)
    if not clean_project_id:
        raise ValueError("project_id must be non-empty")
    quantity_ids = [quantity.quantity_id for quantity in quantities]
    if len(quantity_ids) != len(set(quantity_ids)):
        raise SourceClosedRunConflictError("quantity ids must be unique")

    rows: list[SealedSourceClosedQuantity] = []
    for quantity in quantities:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("quantities must contain only QuantityEvidence records")
        trace = traces_by_quantity_id.get(quantity.quantity_id)
        if trace is None:
            raise MissingSourceClosedRunTraceError(
                f"missing source trace for quantity {quantity.quantity_id}"
            )
        if trace.project_id != clean_project_id:
            raise SourceClosedRunConflictError(
                f"quantity {quantity.quantity_id} belongs to project {trace.project_id}"
            )
        rows.append(seal_source_closed_quantity(quantity, trace=trace))

    return _build_sealed_run(rows, project_id=clean_project_id)


def combine_source_closed_runs(
    runs: Sequence[SealedSourceClosedRun],
    *,
    project_id: str | None = None,
) -> SealedSourceClosedRun:
    """Combine independently sealed production families into one project run.

    This is a benchmark-neutral composition operation. It does not map physical
    identities to benchmark objects, choose expected quantities, or score
    anything. Every input run must already be internally consistent, belong to
    exactly the same project, and contribute unique quantity identities.
    """
    if not runs:
        raise ValueError("at least one sealed source-closed run is required")

    for run in runs:
        if not isinstance(run, SealedSourceClosedRun):
            raise TypeError(
                "runs must contain only SealedSourceClosedRun records"
            )

    clean_project_id = _clean(project_id or runs[0].project_id)
    if not clean_project_id:
        raise ValueError("project_id must be non-empty")

    combined_rows: list[SealedSourceClosedQuantity] = []
    for run in runs:
        if run.project_id != clean_project_id:
            raise SourceClosedRunConflictError(
                f"sealed run {run.run_id} belongs to project {run.project_id}"
            )

        actual_source_sha256s = tuple(
            sorted({row.source_sha256 for row in run.quantities})
        )
        actual_revision_ids = tuple(
            sorted({row.revision_id for row in run.quantities})
        )
        if actual_source_sha256s != tuple(run.source_sha256s):
            raise SourceClosedRunConflictError(
                f"sealed run {run.run_id} source envelope is inconsistent"
            )
        if actual_revision_ids != tuple(run.revision_ids):
            raise SourceClosedRunConflictError(
                f"sealed run {run.run_id} revision envelope is inconsistent"
            )

        expected = _build_sealed_run(run.quantities, project_id=clean_project_id)
        if expected.run_id != run.run_id or expected.fingerprint != run.fingerprint:
            raise SourceClosedRunConflictError(
                f"sealed run {run.run_id} fingerprint is inconsistent"
            )
        combined_rows.extend(run.quantities)

    return _build_sealed_run(combined_rows, project_id=clean_project_id)


__all__ = [
    "MissingSourceClosedRunTraceError",
    "SOURCE_CLOSED_RUN_EXPORT_SCHEMA_VERSION",
    "SealedSourceClosedQuantity",
    "SealedSourceClosedRun",
    "SourceClosedRunConflictError",
    "SourceClosedRunExportError",
    "combine_source_closed_runs",
    "seal_source_closed_quantity",
    "seal_source_closed_run",
    "sealed_source_closed_run_from_dict",
]
