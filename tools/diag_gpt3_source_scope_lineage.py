"""Audit snapshot/decision-scope receipts without promoting them to signed authority.

The source-closed V1 seal signs document/revision/SHA and object/evidence IDs,
but not the source snapshot or decision scope. This benchmark-neutral audit
makes that migration gap visible; it never guesses them from labels, SHA or
the presence of matching unsealed metadata.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pb_migration_contracts import QuantityEvidence
from pb_quantity_takeoff_adapter import CommercialTakeoffSourceTrace

SNAPSHOT_FIELDS = ("source_snapshot_id", "evidence_snapshot_id", "snapshot_id")
SCOPE_FIELDS = ("decision_scope_id",)
SOURCE_SCOPE_AUDIT_SCHEMA_VERSION = "1.0.0"


def _value(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[str | None, bool]:
    claimed = [metadata.get(key) for key in keys if key in metadata]
    if not claimed:
        return None, False
    if any(type(v) is not str or not v or v != v.strip() for v in claimed):
        return None, True
    different = set(claimed)
    if len(different) != 1:
        return None, True
    return claimed[0], False


def audit_source_scope_receipts(
    quantities: Sequence[QuantityEvidence],
    traces_by_quantity_id: Mapping[str, CommercialTakeoffSourceTrace],
) -> dict[str, Any]:
    """Return diagnostic-only scope ownership and first failure per quantity.

    Matching producer/quantity metadata is not source authentication: neither
    scope identity is currently included in V1 sealed fingerprints. An absent
    claim is UNAVAILABLE, never an inferred identity or an empty-string proof.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for quantity in sorted(quantities, key=lambda q: q.quantity_id):
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("scope audit expects QuantityEvidence records")
        if quantity.quantity_id in seen:
            raise ValueError(f"duplicate scope-audit quantity ID: {quantity.quantity_id}")
        seen.add(quantity.quantity_id)
        trace = traces_by_quantity_id.get(quantity.quantity_id)
        if trace is not None and not isinstance(trace, CommercialTakeoffSourceTrace):
            raise TypeError("scope audit trace must be CommercialTakeoffSourceTrace")

        qmeta = quantity.metadata if isinstance(quantity.metadata, Mapping) else {}
        tmeta = trace.metadata if trace is not None and isinstance(trace.metadata, Mapping) else {}
        snap_q, snap_q_bad = _value(qmeta, SNAPSHOT_FIELDS)
        snap_t, snap_t_bad = _value(tmeta, SNAPSHOT_FIELDS)
        scope_q, scope_q_bad = _value(qmeta, SCOPE_FIELDS)
        scope_t, scope_t_bad = _value(tmeta, SCOPE_FIELDS)
        reasons: list[str] = []
        if trace is None:
            reasons.append("SOURCE_TRACE_MISSING")
        if snap_q_bad or snap_t_bad:
            reasons.append("SNAPSHOT_RECEIPT_MALFORMED_OR_CONFLICTING")
        if scope_q_bad or scope_t_bad:
            reasons.append("DECISION_SCOPE_RECEIPT_MALFORMED_OR_CONFLICTING")
        if not snap_q or not snap_t:
            reasons.append("SNAPSHOT_SOURCE_OWNERSHIP_INCOMPLETE")
        elif snap_q != snap_t:
            reasons.append("SNAPSHOT_RECEIPTS_DISAGREE")
        if not scope_q or not scope_t:
            reasons.append("DECISION_SCOPE_SOURCE_OWNERSHIP_INCOMPLETE")
        elif scope_q != scope_t:
            reasons.append("DECISION_SCOPE_RECEIPTS_DISAGREE")
        if trace is not None and isinstance(qmeta.get("source_sha256"), str):
            if qmeta["source_sha256"].lower() != trace.source_sha256:
                reasons.append("SOURCE_SHA_RECEIPTS_DISAGREE")
        if trace is not None and isinstance(qmeta.get("revision_id"), str):
            if qmeta["revision_id"] != trace.revision_id:
                reasons.append("REVISION_RECEIPTS_DISAGREE")
        rows.append({
            "quantity_id": quantity.quantity_id,
            "family": quantity.family,
            "abstained": quantity.abstained,
            "snapshot_id": snap_q if snap_q and snap_t == snap_q else None,
            "decision_scope_id": scope_q if scope_q and scope_t == scope_q else None,
            "receipt_consistency": "UNBOUND" if reasons else "MATCHING_UNSIGNED_METADATA",
            "source_signed_scope_verified": False,
            "v1_sealed_scope_supported": False,
            "first_failing_gate": reasons[0] if reasons else "V1_SCOPE_NOT_SIGNED",
            "reason_codes": reasons if reasons else ["V1_SCOPE_NOT_SIGNED"],
        })
    return {
        "schema_version": SOURCE_SCOPE_AUDIT_SCHEMA_VERSION,
        "status": "DIAGNOSTIC_UNPUBLISHED",
        "signed_scope_verification_complete": False,
        "quantity_count": len(rows),
        "unbound_or_conflicting": sum(row["receipt_consistency"] == "UNBOUND" for row in rows),
        "matching_but_unsigned": sum(row["receipt_consistency"] == "MATCHING_UNSIGNED_METADATA" for row in rows),
        "quantities": rows,
    }


__all__ = [
    "SOURCE_SCOPE_AUDIT_SCHEMA_VERSION",
    "audit_source_scope_receipts",
]
