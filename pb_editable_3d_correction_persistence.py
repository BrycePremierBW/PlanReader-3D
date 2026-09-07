"""pb_editable_3d_correction_persistence.py — Persist & Replay Editable-3D Corrections (PR D.11F).

D.11E proved the correction/stale/recalculate pipeline end-to-end but kept it
entirely in st.session_state — real, but lost on reload or server restart.
This module is the persistence layer that replaces that: two new, additive
tables (`editable_3d_correction_events`, `editable_3d_object_state`, created
in pb_planreader_3d_app.init_local_db()) let a correction survive exactly
the way the rest of this app's data does, without touching `model_masses`/
`model_openings` — the original geometry source rows are never written to,
only ever read.

This module is pure and DB-free, matching every other module in this D-11
series: it converts between Editable3DCorrectionEvent and plain dict rows
(the shape sqlite3.Row -> dict already produces), and replays persisted rows
through the real Editable3DCorrectionLedger.apply_correction() pipeline — the
exact same code path a live correction uses, just driven by stored
parameters in a loop instead of one UI click. Callers (the Streamlit panel)
own the actual `lquery`/`lexecute` calls.

Why replay, not a snapshot restore
-----------------------------------
`editable_3d_object_state` is a materialized cache of the *current* state
(for fast lookup and as an independent check), but the append-only event log
in `editable_3d_correction_events` is the real source of truth. Hydration
always replays every persisted event for an object, in the order it was
recorded, through `ledger.apply_correction()` — never by trusting the cached
snapshot blindly. This is what makes "replay must deterministically
reproduce the current corrected geometry" a real, checked property rather
than an assertion: `replay_persisted_corrections()` calls
`Editable3DCorrectionLedger.replay()` (D.1, unchanged) after replaying and
compares the independently-recomputed hash against the object's live
revision_hash. A mismatch would mean data corruption or a bug — it's
surfaced as a ReplayWarning, never silently trusted.

A second, real integrity check: each persisted event's own
`previous_revision_hash` is compared against the wall's actual live-hydrated
(pre-correction) revision hash the first time it's replayed. If they differ,
the underlying `model_masses` row has genuinely changed since this
correction was recorded (someone edited the mass's dimensions on the "3D
Building Model" page afterwards) — real information worth surfacing, not
something to paper over. Replay still proceeds (a correction is never
silently dropped), but a warning is returned.

Canonical geometry consistency (PR D.11F.1)
--------------------------------------------
D.11F left one inconsistency behind: `Editable3DCorrectionLedger.apply_correction()`
only ever updated the flat `length` measurement, never the wall's `end_pt` —
so the ledger's own object could report a corrected length right next to a
stale, pre-correction endpoint. This module used to paper over that for the
3D viewer with a local, best-effort resync applied only to the *derived*
WallModel copy it returned, leaving the canonical object itself (and
anything else that reads it, e.g. the inspector's raw geometry JSON) still
inconsistent. That resync now lives inside `apply_correction()` itself
(pb_editable_3d_correction_model.py), so both a live correction and a
replayed one produce a canonically self-consistent object — this module no
longer needs its own resync step at all.

Persisted approvals (PR D.11G)
-------------------------------
Approval reuses the existing D.1/D.2 backend verbatim
(`approve_corrected_geometry()`) — this module only adds the same kind of
persist-and-replay wrapper D.11F already gave corrections, in a third
additive table (`editable_3d_approval_events`). It is append-only, exactly
like the correction event log: an approval is never edited or deleted, only
ever superseded by a later correction (which clears `approved_by`/
`approved_at` on the ledger object itself — `apply_correction()`'s own,
unchanged invariant) or a later, separate approval event.

Replay only ever restores the *latest* persisted approval for an object,
and only when that approval's recorded revision_hash still matches the
object's current revision_hash after every persisted correction has
already been replayed on top of it. If a correction landed after that
approval was recorded, the two hashes will no longer match — the object is
already back at REVIEW_REQUIRED from correction replay, and this module
must not paper over that by restoring FIRM anyway. That fail-closed
revision check is the same one `approve_corrected_geometry()` itself
enforces for a live approval; replay does not relax it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from pb_editable_3d_correction_model import (
    ApprovalResult,
    Editable3DCorrectionEvent,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    approve_corrected_geometry,
)
from pb_editable_3d_model import WallModel
from pb_editable_3d_model_bridge import editable_geometry_object_to_wall_model


def correction_event_to_row(workspace_id: int, event: Editable3DCorrectionEvent) -> Dict[str, Any]:
    """Lossless serialization of a correction event for persistence — every
    field the event actually carries, nothing summarized away."""
    return {
        "workspace_id": workspace_id,
        "correction_id": event.correction_id,
        "object_id": event.object_id,
        "object_type": event.object_type,
        "field": event.field,
        "old_value_json": json.dumps(event.old_value),
        "new_value_json": json.dumps(event.new_value),
        "reason": event.reason,
        "actor": event.actor,
        "source": event.source,
        "previous_revision_hash": event.previous_revision_hash,
        "new_revision_hash": event.new_revision_hash,
        "created_at": event.created_at,
    }


def row_to_correction_event(row: Mapping[str, Any]) -> Editable3DCorrectionEvent:
    """The exact inverse of correction_event_to_row — reconstructs the event
    with every field it was persisted with, so replay operates on the real
    recorded correction, never a reconstruction that guesses anything."""
    old_value_json = row.get("old_value_json")
    return Editable3DCorrectionEvent(
        correction_id=row["correction_id"],
        object_id=row["object_id"],
        object_type=row["object_type"],
        field=row["field"],
        old_value=json.loads(old_value_json) if old_value_json is not None else None,
        new_value=json.loads(row["new_value_json"]),
        reason=row["reason"],
        actor=row["actor"],
        created_at=row["created_at"],
        source=row["source"],
        previous_revision_hash=row.get("previous_revision_hash"),
        new_revision_hash=row["new_revision_hash"],
    )


def object_state_row(workspace_id: int, obj: EditableGeometryObject) -> Dict[str, Any]:
    """The row to upsert into `editable_3d_object_state` after a correction —
    a materialized snapshot for fast lookup, never the thing replay trusts
    over the real event log."""
    return {
        "workspace_id": workspace_id,
        "object_id": obj.object_id,
        "authority_status": obj.authority_status,
        "approved_by": obj.approved_by,
        "approved_at": obj.approved_at,
        "revision_hash": obj.revision_hash,
        "correction_ids_json": json.dumps(obj.correction_ids),
        "updated_at": obj.updated_at,
    }


@dataclass
class ReplayWarning:
    object_id: str
    reason: str


def replay_persisted_corrections(
    ledger: Editable3DCorrectionLedger,
    walls: Sequence[WallModel],
    event_rows: Sequence[Mapping[str, Any]],
) -> Tuple[List[WallModel], List[ReplayWarning]]:
    """Replay every persisted correction event (grouped by object, in the
    order they were originally recorded — insertion/id order, since the
    table is append-only) through the real
    Editable3DCorrectionLedger.apply_correction() pipeline (which keeps a
    wall's end_pt canonically consistent with any corrected length as of
    D.11F.1). Mutates `ledger` in place (so ledger.get_object()/
    events_for_object() reflect the full persisted history); returns the
    wall list for the 3D viewer and any integrity warnings. Never raises,
    never silently drops a real persisted correction."""
    walls_by_id = {w.wall_id: w for w in walls}
    corrected_walls = list(walls)
    warnings: List[ReplayWarning] = []

    events_by_object: "Dict[str, List[Editable3DCorrectionEvent]]" = {}
    for row in event_rows:
        event = row_to_correction_event(row)
        events_by_object.setdefault(event.object_id, []).append(event)

    for object_id, events in events_by_object.items():
        original_wall = walls_by_id.get(object_id)
        if original_wall is None:
            warnings.append(ReplayWarning(
                object_id=object_id,
                reason=(
                    "This object no longer exists in the live database — its "
                    "persisted corrections are orphaned and were not replayed."
                ),
            ))
            continue

        genesis_obj = ledger.get_object(object_id)
        genesis_hash = genesis_obj.revision_hash if genesis_obj else None
        first_event = events[0]
        if first_event.previous_revision_hash and genesis_hash and first_event.previous_revision_hash != genesis_hash:
            warnings.append(ReplayWarning(
                object_id=object_id,
                reason=(
                    f"Source geometry has changed since these corrections were made "
                    f"(recorded against revision {first_event.previous_revision_hash!r}, "
                    f"live geometry is now at {genesis_hash!r}) — replaying on top of "
                    f"the current geometry anyway."
                ),
            ))

        for event in events:
            outcome = ledger.apply_correction(
                correction_id=event.correction_id, object_id=object_id,
                field=event.field, new_value=event.new_value,
                reason=event.reason, actor=event.actor, source=event.source,
                created_at=event.created_at,
            )
            if not outcome.ok:
                warnings.append(ReplayWarning(
                    object_id=object_id,
                    reason=(
                        f"Persisted correction {event.correction_id!r} failed to "
                        f"replay: {'; '.join(outcome.blocking_reasons)}"
                    ),
                ))
                continue

        obj_after = ledger.get_object(object_id)
        if obj_after is None:
            continue

        replayed_hash = ledger.replay(object_id, genesis_hash=genesis_hash)
        if replayed_hash is not None and replayed_hash != obj_after.revision_hash:
            warnings.append(ReplayWarning(
                object_id=object_id,
                reason=(
                    f"Replay determinism check failed: independently replayed hash "
                    f"{replayed_hash!r} does not match the object's current hash "
                    f"{obj_after.revision_hash!r}."
                ),
            ))

        # apply_correction() itself now keeps a wall's end_pt canonically in
        # sync with any corrected length (PR D.11F.1) — no separate resync
        # step needed here; the conversion below reads the already-consistent
        # measurements straight off the replayed ledger object.
        corrected_wall = editable_geometry_object_to_wall_model(obj_after)
        corrected_walls = [corrected_wall if w.wall_id == object_id else w for w in corrected_walls]

    return corrected_walls, warnings


def verify_object_state_consistency(
    ledger: Editable3DCorrectionLedger,
    object_state_rows: Sequence[Mapping[str, Any]],
) -> List[ReplayWarning]:
    """Cross-check the independently-persisted `editable_3d_object_state`
    snapshot against the ledger state actually reconstructed by
    replay_persisted_corrections() from the append-only event log. These are
    two separate tables that could in principle drift apart (e.g. a partial
    write) — this is a genuine integrity check between two independent
    sources, not one that can only ever pass by mathematical construction
    the way comparing a hash against itself would. Call this after
    replay_persisted_corrections() has already run against the same ledger."""
    warnings: List[ReplayWarning] = []
    for row in object_state_rows:
        object_id = row["object_id"]
        obj = ledger.get_object(object_id)
        if obj is None:
            continue
        if row.get("revision_hash") != obj.revision_hash:
            warnings.append(ReplayWarning(
                object_id=object_id,
                reason=(
                    f"Persisted object-state snapshot revision "
                    f"{row.get('revision_hash')!r} does not match the revision "
                    f"{obj.revision_hash!r} reconstructed by replaying the "
                    f"correction event log — the two persisted tables have "
                    f"drifted out of sync."
                ),
            ))
    return warnings


def approval_result_to_row(workspace_id: int, object_type: str, result: ApprovalResult) -> Dict[str, Any]:
    """The row to append to `editable_3d_approval_events` after a successful
    approve_corrected_geometry() call — lossless, every field the result
    actually carries."""
    return {
        "workspace_id": workspace_id,
        "object_id": result.object_id,
        "object_type": object_type,
        "revision_hash": result.revision_hash,
        "approved_by": result.approved_by,
        "approved_at": result.approved_at,
        "created_at": result.approved_at,
    }


def replay_persisted_approvals(
    ledger: Editable3DCorrectionLedger,
    approval_rows: Sequence[Mapping[str, Any]],
) -> List[ReplayWarning]:
    """Re-apply the latest persisted approval for each object — but only when
    it still targets the object's current revision. Call this *after*
    replay_persisted_corrections() has already replayed every persisted
    correction onto the same ledger, so `ledger.get_object(object_id)`
    reflects the object's final, corrected state.

    `approval_rows` must be ordered by id (the same append-only order they
    were recorded in) — the last row per object_id is treated as the latest
    approval, matching how a real correction can supersede an earlier one.
    If that approval's revision_hash no longer matches the object's current
    revision_hash, a correction has landed since it was recorded: the
    object is already REVIEW_REQUIRED from correction replay (D.1's own
    apply_correction() invariant, unchanged), and this function leaves it
    that way rather than restoring FIRM for a revision that no longer
    exists. This mirrors the exact fail-closed rule
    approve_corrected_geometry() enforces for a live approval — replay does
    not relax it."""
    warnings: List[ReplayWarning] = []
    latest_by_object: Dict[str, Mapping[str, Any]] = {}
    for row in approval_rows:
        latest_by_object[row["object_id"]] = row  # last write wins — append-only id order

    for object_id, row in latest_by_object.items():
        obj = ledger.get_object(object_id)
        if obj is None:
            warnings.append(ReplayWarning(
                object_id=object_id,
                reason=(
                    "This object no longer exists in the live database — its "
                    "persisted approval is orphaned and was not replayed."
                ),
            ))
            continue

        if obj.revision_hash != row["revision_hash"]:
            # Correctly invalidated: a correction landed after this approval
            # was recorded. Correction replay already reset this object to
            # REVIEW_REQUIRED — nothing to restore.
            continue

        try:
            approve_corrected_geometry(
                ledger, object_id=object_id,
                approved_by=row["approved_by"],
                current_revision_hash=row["revision_hash"],
                approved_at=row["approved_at"],
            )
        except ValueError as exc:
            warnings.append(ReplayWarning(
                object_id=object_id,
                reason=f"Persisted approval failed to replay: {exc}",
            ))

    return warnings
