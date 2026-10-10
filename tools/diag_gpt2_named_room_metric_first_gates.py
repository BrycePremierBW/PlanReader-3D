"""Read-only producer receipt ledger for named-room metric first failures.

This is a diagnostic adapter, not a scale, room-area, or QuantityEvidence
producer. Never infer a metric quantity from a missing first-failure receipt.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def summarize_named_room_metric_first_gates(claim: Any) -> dict[str, Any]:
    """Report exact named source room ownership and existing measurement gates.

    Duplicate physical IDs, even with the same label, are not uniquely
    attributable. Their first-failure codes remain counted but cannot be
    assigned to a named room in the diagnostic output.
    """
    named = tuple(
        (
            raw_id.strip() if isinstance(raw_id, str) else "",
            " ".join(raw_label.upper().split()),
        )
        for room in getattr(claim, "canonical_rooms", ()) or ()
        for raw_id, raw_label in ((
            getattr(room, "physical_room_id", None),
            getattr(room, "room_label", None),
        ),)
        if isinstance(raw_label, str) and raw_label.strip()
    )
    counts = Counter(room_id for room_id, _ in named)
    owners = {room_id: label for room_id, label in named
              if room_id and counts[room_id] == 1}
    conflicts = sorted({room_id for room_id, _ in named
                        if not room_id or counts[room_id] != 1})

    kinds = (
        ("same_view", "same_view_room_area_first_failure_codes"),
        ("cross_view", "cross_view_room_area_first_failure_codes"),
        ("physical_scale", "physical_scale_first_failure_codes"),
    )
    ledger: dict[str, list[dict[str, Any]]] = {}
    total: dict[str, int] = {}
    malformed_receipts: dict[str, int] = {}
    ambiguous_gate_owners: dict[str, list[str]] = {}
    witnessed_room_ids: set[str] = set()
    for key, attr in kinds:
        raw_receipts = tuple(getattr(claim, attr, ()) or ())
        total[key] = len(raw_receipts)
        codes = tuple(
            receipt for receipt in raw_receipts
            if isinstance(receipt, (tuple, list)) and len(receipt) == 2
        )
        malformed_receipts[key] = total[key] - len(codes)
        owned_reasons: dict[str, set[str]] = defaultdict(set)
        for source_room_id, reason in codes:
            rid = source_room_id.strip() if isinstance(source_room_id, str) else ""
            if rid in owners:
                witnessed_room_ids.add(rid)
                owned_reasons[rid].add(repr(reason))
        conflicted = {
            rid for rid, distinct in owned_reasons.items() if len(distinct) > 1
        }
        ambiguous_gate_owners[key] = sorted(conflicted)
        entries = []
        emitted: set[str] = set()
        for source_room_id, reason in codes:
            room_id = source_room_id.strip() if isinstance(source_room_id, str) else ""
            if room_id not in owners or room_id in conflicted or room_id in emitted:
                continue
            emitted.add(room_id)
            if key == "physical_scale":
                # A scalar string is not a series of independent producer
                # reasons. Do not silently output its individual characters.
                codes = reason if isinstance(reason, (tuple, list)) else ()
                detail = {
                    "first_gates": [str(code) for code in codes],
                    "source_reason_receipt_valid": bool(codes) and all(
                        isinstance(code, str) and bool(code.strip())
                        for code in codes
                    ),
                }
            else:
                # None, whitespace, or structured objects are not concrete
                # same/cross-view source producer first-failure codes.
                valid_reason = isinstance(reason, str) and bool(reason.strip())
                detail = (
                    {"first_gate": reason}
                    if valid_reason
                    else {"first_gate": "", "source_reason_receipt_valid": False}
                )
            entries.append({
                "physical_room_id": room_id,
                "label": owners[room_id],
                **detail,
            })
        ledger[key] = sorted(entries, key=lambda row: (
            row["label"], row["physical_room_id"],
            repr(row.get("first_gate", row.get("first_gates"))),
        ))
    # Absence of a failed measurement receipt does not prove a measurement
    # passed. It may mean that producer was never run for that physical room.
    no_gate_receipt = [
        {"physical_room_id": room_id, "label": label}
        for room_id, label in sorted(owners.items(), key=lambda row: (row[1], row[0]))
        if room_id not in witnessed_room_ids
    ]
    return {
        "named_rooms_without_first_failure_receipts": no_gate_receipt,
        "ambiguous_metric_first_failure_owner_ids": ambiguous_gate_owners,
        "source_named_room_count": len(named),
        "uniquely_attributable_named_room_count": len(owners),
        "ambiguous_named_physical_room_ids": conflicts,
        "all_source_first_failure_receipt_counts": total,
        "malformed_source_first_failure_receipt_counts": malformed_receipts,
        "named_room_metric_first_failure_codes": ledger,
        "metric_quantity_published": False,
    }
